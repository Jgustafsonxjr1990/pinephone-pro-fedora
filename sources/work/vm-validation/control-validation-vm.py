#!/usr/bin/env python3
"""Unstarted final-validation controller: MMIO launches, exact LF receipts.

Runtime requires --run and a fresh --state-dir. Receipt files document observed
guest exits only. No VM is adopted, resumed or searched for by this controller.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import secrets
import selectors
import shlex
import signal
import subprocess
import sys
import time

from receipts import CompleteLines, parse_receipt, receipt_pattern

BASE = Path('/path/to/workspace')
SCRIPT_DIR = Path(__file__).resolve().parent
MAX_WIRE_BYTES = 3800
STANDARD_PATH = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)')


class ValidationFailure(Exception):
    pass


def load_launcher(mode):
    name = 'launch-offline-growth-vm.py' if mode == 'offline' else 'launch-verify-vm.py'
    spec = importlib.util.spec_from_file_location('final_validation_launcher', SCRIPT_DIR / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def wait_owned_exit(process, console, timeout):
    """Drain only this child's serial pipe while waiting for clean shutdown."""
    deadline = time.monotonic() + timeout
    with selectors.DefaultSelector() as drain:
        drain.register(process.stdout, selectors.EVENT_READ)
        while process.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(process.args, timeout)
            for key, _ in drain.select(timeout=min(0.5, remaining)):
                data = os.read(key.fd, 65536)
                if data:
                    console.write(data)
                else:
                    drain.unregister(key.fileobj)
            if not drain.get_map():
                return process.wait(timeout=max(0.001, deadline - time.monotonic()))
    return process.returncode


def exclusive_bytes(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    identity = os.fstat(fd)
    try:
        remaining = data
        while remaining:
            written = os.write(fd, remaining)
            if not written:
                raise OSError('Receipt write made no progress')
            remaining = remaining[written:]
        os.fsync(fd)
        sync_directory(path.parent)
        # close() may have already released its descriptor when it raises.
        # Clear our reference first; never retry that possibly reused number.
        closing_fd, fd = fd, None
        os.close(closing_fd)
    except BaseException as error:
        try:
            current = path.lstat()
            if (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
                try:
                    path.unlink()
                except OSError:
                    # Keep a failed receipt when unlink is unavailable; never
                    # leave the already-written successful JSON as evidence.
                    replacement = os.open(path, os.O_WRONLY | os.O_NOFOLLOW)
                    try:
                        opened = os.fstat(replacement)
                        if (opened.st_dev, opened.st_ino) != (identity.st_dev, identity.st_ino):
                            raise OSError('Receipt rollback refuses a replaced inode')
                        os.ftruncate(replacement, 0)
                        os.write(replacement, b'{"status":"receipt_write_failed","controller_exit":1}\n')
                        os.fsync(replacement)
                    finally:
                        os.close(replacement)
                sync_directory(path.parent)
        except FileNotFoundError:
            pass
        except BaseException as cleanup_error:
            error.add_note('Receipt rollback incomplete: ' + str(cleanup_error))
        raise
    finally:
        if fd is not None:
            os.close(fd)


def exclusive_json(path, value):
    exclusive_bytes(path, (json.dumps(value, indent=2, sort_keys=True) + '\n').encode())


def exclusive_text(path, value):
    exclusive_bytes(path, value.encode())


def canonical_directory(path):
    path = Path(path).absolute()
    if not path.is_relative_to(BASE) or path.resolve() != path:
        raise ValidationFailure('State directory must be a canonical workspace directory')
    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir() or path.resolve(strict=True) != path:
        raise ValidationFailure('Unsafe state directory')
    return path


def wrapped_command(command, name, token):
    receipt_pattern(name, token)
    if not command.strip() or any(c in command for c in ('\n', '\r', '\0')):
        raise ValidationFailure('Expected one nonempty command line')
    wrapper = (
        'bash -o pipefail -c ' + shlex.quote(command)
        + '; ppp_command_exit=$?; printf '
        + shlex.quote('\nPPP_CMD_DONE_' + name + ' TOKEN=' + token + ' EXIT=%s\n')
        + ' "$ppp_command_exit"')
    # printf's format must contain escaped newlines, not physical TTY lines.
    wrapper = wrapper.replace('\n', r'\n')
    if len((wrapper + '\n').encode('utf-8')) > MAX_WIRE_BYTES:
        raise ValidationFailure('Wrapped command exceeds the bounded serial line budget')
    return wrapper


def read_request(path):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,96}', path.stem):
        raise ValidationFailure('Invalid command ID')
    if path.is_symlink() or path.resolve(strict=True) != path or not path.is_file():
        raise ValidationFailure('Command must be a canonical nonsymlink regular file')
    data = path.read_bytes()
    if len(data) > MAX_WIRE_BYTES:
        raise ValidationFailure('Command file exceeds serial budget')
    command = data.decode('utf-8').removesuffix('\n')
    wrapped_command(command, path.stem, '0' * 32)
    return command, hashlib.sha256(data).hexdigest()


def bootstrap_command(mode, metadata, session):
    steps = [
        'export PATH=' + STANDARD_PATH + ' LC_ALL=C',
        'mkdir -p /proc /sys /build',
        '(mountpoint -q /proc || mount -t proc proc /proc)',
        '[ "$(findmnt -n -o FSTYPE --target /proc)" = proc ]',
        '(mountpoint -q /sys || mount -t sysfs sysfs /sys)',
        '[ "$(findmnt -n -o FSTYPE --target /sys)" = sysfs ]',
        'modprobe 9pnet_virtio',
        '(mountpoint -q /build || mount -t 9p -o trans=virtio,version=9p2000.L build /build)',
        '[ "$(findmnt -n -o FSTYPE --target /build)" = 9p ]',
    ]
    if mode == 'offline':
        steps += [
            'ppp_source=; ppp_growth=; ppp_sources=0; ppp_targets=0; '
            'for p in /sys/block/vd*; do [ -r "$p/serial" ] || continue; '
            'case "$(cat "$p/serial")" in '
            'PPP_OFFLINE_SOURCE) ppp_source=/dev/"$(basename "$p")"; ppp_sources=$((ppp_sources+1));; '
            'PPP_GROWTH_TARGET) ppp_growth=/dev/"$(basename "$p")"; ppp_targets=$((ppp_targets+1));; esac; done',
            '[ "$ppp_sources" = 1 ] && [ "$ppp_targets" = 1 ] && [ "$ppp_source" != "$ppp_growth" ]',
            '[ "$(blockdev --getsize64 "$ppp_source")" = ' + str(metadata['source_bytes']) + ' ]',
            '[ "$(blockdev --getsize64 "$ppp_growth")" = 17179869184 ] && [ "$(blockdev --getss "$ppp_growth")" = 512 ]',
            '[ "$(blockdev --getro "$ppp_growth")" = 1 ]',
            '[ "$(findmnt -n -o FSTYPE --target /)" = btrfs ] && [ "$(findmnt -n -o FSROOT --target /)" = /root ]',
            '[ "$(findmnt -n -o UUID --target /)" = ' + shlex.quote(metadata['source_root_uuid']) + ' ]',
            # Btrfs subvolume MAJ:MIN is an anonymous device, not its partition.
            'printf "SOURCE_ROOT_DEVICE=%s\\n" "$(findmnt -rn --nofsroot -o SOURCE --target /)"; '
            '[ "$(readlink -f "$(findmnt -rn --nofsroot -o SOURCE --target /)")" = "$ppp_source"3 ]',
            'for d in "$ppp_growth" "$ppp_growth"1 "$ppp_growth"2 "$ppp_growth"3; do '
            '[ -z "$(findmnt -rn -S "$d")" ] || break; done; [ -z "$(findmnt -rn -S "$d")" ]',
            'export PPP_GROWTH_DEVICE="$ppp_growth" PPP_OFFLINE_SOURCE_DEVICE="$ppp_source"',
        ]
    else:
        size = 17179869184 if mode == 'growth' else 15032385536
        steps += [
            'ppp_disk=; ppp_disks=0; for p in /sys/block/vd*; do [ -r "$p/serial" ] || continue; '
            'if [ "$(cat "$p/serial")" = PPP_VERIFY_ROOT ]; then '
            'ppp_disk=/dev/"$(basename "$p")"; ppp_disks=$((ppp_disks+1)); fi; done',
            '[ "$ppp_disks" = 1 ] && [ "$(blockdev --getsize64 "$ppp_disk")" = ' + str(size) + ' ]',
            '[ "$(findmnt -n -o FSTYPE --target /)" = ext4 ]',
            '[ "$(findmnt -n -o UUID --target /)" = ' + shlex.quote(metadata['root_uuid']) + ' ]',
            '[ "$(readlink -f /dev/block/"$(findmnt -rn -o MAJ:MIN --target /)")" = "$ppp_disk"3 ]',
            'export PPP_VERIFY_DISK="$ppp_disk"',
        ]
    steps += ['stty -echo', 'set +e', 'export PS1="PPP_VALIDATION_PROMPT> "']
    script = ('if ' + ' && '.join("{ printf 'BOOTSTRAP_STEP_%02d\\n'; %s; }" % (index, x) for index, x in enumerate(steps, 1))
              + '; then printf "\\nPPP_BOOT_READY SESSION=' + session
              + '\\n"; ppp_bootstrap_exit=0; else ppp_bootstrap_exit=$?; fi; '
              + 'printf "\\nPPP_CMD_DONE_BOOTSTRAP TOKEN=' + session
              + ' EXIT=%s\\n" "$ppp_bootstrap_exit"')
    if len((script + '\n').encode()) > MAX_WIRE_BYTES:
        raise ValidationFailure('Bootstrap exceeds bounded serial line budget')
    return script


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('snapshot', 'growth', 'offline'), required=True)
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--overlay', type=Path, default=BASE / 'work/fedora-ppp-validation.qcow2')
    parser.add_argument('--source-disk', type=Path)
    parser.add_argument('--source-root-uuid')
    parser.add_argument('--source-bytes', type=int)
    parser.add_argument('--source-initramfs', type=Path, default=BASE / 'work/share/fedora-source-initramfs.img')
    parser.add_argument('--cpus', type=int, default=2)
    parser.add_argument('--memory-mib', type=int, default=1280)
    parser.add_argument('--boot-timeout', type=float, default=1800)
    parser.add_argument('--command-timeout', type=float, default=3600)
    parser.add_argument('--session-timeout', type=float, default=14400)
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    if any(not math.isfinite(x) or x <= 0 or x > 86400 for x in (args.boot_timeout, args.command_timeout, args.session_timeout)):
        parser.error('timeouts must be finite positive seconds, at most86400')
    if args.mode == 'offline' and any(x is None for x in (args.source_disk, args.source_root_uuid, args.source_bytes)):
        parser.error('offline mode requires explicit source disk, UUID and geometry')
    launcher = load_launcher(args.mode)
    command, environment, metadata = launcher.configuration(args)
    session = secrets.token_hex(16)
    bootstrap = bootstrap_command(args.mode, metadata, session)
    if not args.run:
        print(json.dumps({'preflight_passed': True, 'vm_launched': False, 'inputs': metadata}, indent=2))
        return 0
    state = canonical_directory(args.state_dir)
    if any(p.name != 'commands' for p in state.iterdir()):
        raise ValidationFailure('Use a fresh state directory; preserve all prior evidence')
    requests = canonical_directory(state / 'commands')
    if any(p.suffix != '.command' for p in requests.iterdir()):
        raise ValidationFailure('Fresh queue must contain command files only')
    for request in requests.glob('*.command'):
        read_request(request)
    lock_fd = os.open(state / 'controller.lock', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    selector = selectors.DefaultSelector()
    console = (state / 'console.log').open('xb', buffering=0)
    process = None
    active = active_log = None
    completed = set()
    failures = []
    ready = sent_bootstrap = saw_ready = False
    framing = CompleteLines()
    boot_pattern = receipt_pattern('BOOTSTRAP', session)
    ready_line = ('PPP_BOOT_READY SESSION=' + session).encode()
    tail = ''
    start = time.monotonic()
    result = 1
    old_handlers = {}

    def interrupted(signum, frame):
        raise ValidationFailure('Controller interrupted by signal ' + str(signum))

    def send(text):
        payload = (text + '\n').encode()
        while payload:
            written = os.write(process.stdin.fileno(), payload[:64])
            if not written:
                raise ValidationFailure('VM serial input closed')
            payload = payload[written:]
            if payload:
                time.sleep(0.05)

    try:
        launcher.prepare_runtime(metadata)
        exclusive_json(state / 'launch.json', {'session': session, 'mode': args.mode,
            'qemu_command': command, 'inputs': metadata, 'created_unix': time.time()})
        for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            old_handlers[signum] = signal.signal(signum, interrupted)
        blocked = signal.pthread_sigmask(signal.SIG_BLOCK, tuple(old_handlers))
        try:
            process = subprocess.Popen(command, env=environment, cwd=BASE, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0, start_new_session=True)
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, blocked)
        exclusive_text(state / 'vm.pid', str(process.pid) + '\n')
        exclusive_json(state / 'started.json', {'pid': process.pid, 'started_unix': time.time()})
        selector.register(process.stdout, selectors.EVENT_READ)
        print('VALIDATION_VM_STARTED mode=' + args.mode + ' pid=' + str(process.pid), flush=True)
        eof = False
        while not eof:
            now = time.monotonic()
            if now - start > args.session_timeout or (not ready and now - start > args.boot_timeout):
                raise ValidationFailure('VM session or boot deadline exceeded')
            if active and now - active['monotonic'] > args.command_timeout:
                raise ValidationFailure('Active command deadline exceeded')
            for key, _ in selector.select(timeout=0.5):
                data = os.read(key.fd, 65536)
                if not data:
                    selector.unregister(key.fileobj)
                    eof = True
                    break
                console.write(data)
                if active_log:
                    active_log.write(data)
                available = tail + ANSI.sub('', data.decode(errors='replace'))
                tail = available[-4096:]
                # Boot logs can share a >4KiB read with the early shell prompt.
                # Match the entire new chunk before bounding retained context.
                if not sent_bootstrap and re.search(r'(?:bash|sh)-[\d.]+# |\[root@[^\n]+\]# ', available):
                    send(bootstrap)
                    sent_bootstrap = True
                    tail = ''
                for line in framing.feed(data):
                    if not ready and line == ready_line:
                        saw_ready = True
                    status = parse_receipt(line, boot_pattern) if sent_bootstrap and not ready else None
                    if status is not None:
                        if status != 0 or not saw_ready:
                            raise ValidationFailure('Checked guest bootstrap did not pass')
                        ready = True
                        exclusive_json(state / 'boot-ready.json', {'session': session, 'observed_unix': time.time()})
                        print('VALIDATION_CONTROL_READY mode=' + args.mode, flush=True)
                    if active:
                        status = parse_receipt(line, active['pattern'])
                        if status is not None:
                            if read_request(active['path'])[1] != active['command_sha256']:
                                raise ValidationFailure('Active command file changed')
                            active_log.flush()
                            os.fsync(active_log.fileno())
                            active_log.close()
                            active_log = None
                            exclusive_json(requests / (active['name'] + '.result.json'), {
                                'name': active['name'], 'token': active['token'], 'exit': status,
                                'command_sha256': active['command_sha256'], 'complete_newline_receipt': True,
                                'started_unix': active['started_unix'], 'ended_unix': time.time()})
                            exclusive_text(requests / (active['name'] + '.status'), str(status) + '\n')
                            completed.add(active['name'])
                            print('VALIDATION_COMMAND_DONE name=' + active['name'] + ' exit=' + str(status), flush=True)
                            active = None
                            if status:
                                failures.append(status)
                                raise ValidationFailure('Validation command returned nonzero')
            if not eof and ready and active is None:
                for path in sorted(requests.glob('*.command')):
                    if path.stem in completed:
                        continue
                    if any((requests / (path.stem + suffix)).exists() for suffix in
                           ('.started.json', '.result.json', '.status', '.console.log', '.incomplete.json')):
                        raise ValidationFailure('Unexpected existing command receipt')
                    shell, digest = read_request(path)
                    token = secrets.token_hex(16)
                    started = time.time()
                    exclusive_json(requests / (path.stem + '.started.json'), {
                        'name': path.stem, 'token': token, 'started_unix': started, 'command_sha256': digest})
                    active_log = (requests / (path.stem + '.console.log')).open('xb', buffering=0)
                    active = {'name': path.stem, 'path': path, 'token': token, 'started_unix': started,
                        'monotonic': time.monotonic(), 'command_sha256': digest,
                        'pattern': receipt_pattern(path.stem, token)}
                    send(wrapped_command(shell, path.stem, token))
                    print('VALIDATION_COMMAND_STARTED name=' + path.stem, flush=True)
                    break
        pending = [p.stem for p in requests.glob('*.command') if p.stem not in completed]
        result = process.wait(timeout=30)
        if not ready or active or pending or failures:
            result = result or 1
    except Exception as error:
        result = failures[0] if failures else 1
        print('VALIDATION_CONTROL_FAILED: ' + str(error), file=sys.stderr, flush=True)
    finally:
        for signum in old_handlers:
            signal.signal(signum, signal.SIG_IGN)
        if active:
            try:
                if active_log:
                    active_log.flush()
                    os.fsync(active_log.fileno())
                    active_log.close()
                    active_log = None
                exclusive_json(requests / (active['name'] + '.incomplete.json'), {
                    'name': active['name'], 'token': active['token'], 'exit': None,
                    'complete_newline_receipt': False, 'reason': 'Controller failed or serial EOF before receipt'})
            except Exception as error:
                result = result or 1
                print('VALIDATION_INCOMPLETE_RECEIPT_WRITE_FAILED: ' + str(error), file=sys.stderr, flush=True)
        if process is not None and process.poll() is None:
            # Only this start_new_session process group is eligible for cleanup.
            try:
                os.write(process.stdin.fileno(), b'sync; systemctl poweroff || poweroff -f\n')
                wait_owned_exit(process, console, 30)
            except (OSError, subprocess.TimeoutExpired):
                for signum in (signal.SIGTERM, signal.SIGKILL):
                    try:
                        os.killpg(process.pid, signum)
                        process.wait(timeout=10)
                        break
                    except ProcessLookupError:
                        break
                    except subprocess.TimeoutExpired:
                        continue
            result = result or 1
        try:
            console.flush()
            os.fsync(console.fileno())
        except Exception as error:
            result = result or 1
            print('VALIDATION_CONSOLE_FLUSH_FAILED: ' + str(error), file=sys.stderr, flush=True)
        finally:
            console.close()
            selector.close()
        try:
            if process is not None:
                for stream in (process.stdin, process.stdout):
                    if stream:
                        stream.close()
            for signum, handler in old_handlers.items():
                signal.signal(signum, handler)
            os.close(lock_fd)
        except Exception as error:
            result = result or 1
            print('VALIDATION_RESOURCE_CLEANUP_FAILED: ' + str(error), file=sys.stderr, flush=True)
        # Publish the final exit evidence only after resource cleanup passed.
        try:
            if process is not None:
                exclusive_json(state / 'vm-exit.json', {'qemu_exit': process.poll(), 'ended_unix': time.time(),
                    'boot_ready_observed': ready, 'controller_exit': result})
        except Exception as error:
            result = result or 1
            print('VALIDATION_EXIT_RECEIPT_WRITE_FAILED: ' + str(error), file=sys.stderr, flush=True)
    return result


if __name__ == '__main__':
    raise SystemExit(main())
