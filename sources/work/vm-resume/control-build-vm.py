#!/usr/bin/env python3
"""Serial-only build controller with exact complete-line stage receipts.

Queue one single-line command in STATE/commands/NAME.command. A process exit is
recorded only after its complete LF-terminated name/token-bound receipt. The
controller never synthesizes a successful command or stops an active VM.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import selectors
import shlex
import stat
import subprocess
import time
from urllib.parse import urlsplit

from receipts import CompleteLines, parse_receipt, receipt_pattern
from vm_launcher import WORKSPACE, add_arguments, configuration


def exclusive_json(path, value):
    encoded = (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def exclusive_text(path, value):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())


def state_directory(path):
    path = Path(path).absolute()
    if not path.is_relative_to(WORKSPACE) or path.resolve() != path:
        raise ValueError('Controller state must be a canonical workspace directory')
    path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir() or path.resolve(strict=True) != path:
        raise ValueError('Unsafe controller state directory')
    return path


def stage_live_network(share, state, *, local_direct=False):
    """Bind temporary guest proxy/trust to this exact execution namespace."""
    files = []
    if local_direct:
        script = ('# BUILD ONLY: direct local-host networking with Fedora system trust.\n'
                  + 'unset https_proxy http_proxy HTTPS_PROXY HTTP_PROXY all_proxy ALL_PROXY no_proxy NO_PROXY\n'
                  + 'cat /etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem > /run/ppp-build-ca-bundle.pem\n')
    else:
        proxy = urlsplit(os.environ.get('HTTPS_PROXY', os.environ.get('https_proxy', '')))
        if (proxy.scheme != 'http' or proxy.hostname not in ('127.0.0.1', 'localhost')
                or proxy.username is not None or proxy.password is not None
                or proxy.path not in ('', '/') or proxy.query or proxy.fragment
                or not proxy.port):
            raise ValueError('Expected the current execution namespace local HTTP proxy')
        certificate = Path(os.environ['CODEX_PROXY_CERT']).read_bytes()
        if (not 0 < len(certificate) <= 65536 or b'BEGIN CERTIFICATE' not in certificate
                or b'PRIVATE KEY' in certificate):
            raise ValueError('Build proxy CA must be a bounded public certificate')
        guest_proxy = 'http://10.0.2.2:' + str(proxy.port)
        script = ('# BUILD ONLY: generated in the actual VM execution namespace.\n'
                  + 'export https_proxy=' + shlex.quote(guest_proxy) + '\n'
                  + 'export http_proxy="$https_proxy" HTTPS_PROXY="$https_proxy" HTTP_PROXY="$https_proxy"\n'
                  + 'cat /etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem /build/build-ca.pem > /run/ppp-build-ca-bundle.pem\n')
        files.append(('build-ca.pem', certificate))
    script += 'export SSL_CERT_FILE=/run/ppp-build-ca-bundle.pem CURL_CA_BUNDLE=/run/ppp-build-ca-bundle.pem REQUESTS_CA_BUNDLE=/run/ppp-build-ca-bundle.pem\n'
    files.append(('live-build-network.sh', script.encode()))
    for name, contents in files:
        path = share / name
        if path.exists() or path.is_symlink():
            metadata = path.lstat()
            if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
                    or path.resolve() != path):
                raise ValueError('Unsafe existing build-only network file')
        temporary = share / (name + '.private-' + secrets.token_hex(8))
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(contents); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    exclusive_json(state / 'network-setup.json', {
        'generated_in_actual_vm_execution': True,
        'network_mode': 'local-direct' if local_direct else 'cloud-proxy',
        'temporary_build_only': True, 'tls_verification_enabled': True,
        'host_network_namespace': str(Path('/proc/self/ns/net').readlink()),
        'credentials_recorded': False,
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_arguments(parser)
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--local-direct-network', action='store_true',
                        help='Use QEMU user networking directly with the guest Fedora CA trust')
    parser.add_argument('--run', action='store_true', help='Explicitly start the VM; otherwise preflight only')
    args = parser.parse_args()
    session = secrets.token_hex(16)
    command, environment = configuration(args, session)
    if not args.run:
        print(json.dumps({'preflight_passed': True, 'vm_launched': False,
                          'qemu_command': command}, indent=2), flush=True)
        return 0
    state = state_directory(args.state_dir)
    lock = (state / 'controller.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if (state / 'launch.json').exists():
        raise ValueError('Use a fresh controller state directory for each actual VM launch')
    requests = state_directory(state / 'commands')
    stage_live_network(args.share, state, local_direct=args.local_direct_network)
    exclusive_json(state / 'launch.json', {'session': session, 'qemu_command': command,
                                          'created_unix': time.time(), 'vm_launched': False})
    process = subprocess.Popen(command, env=environment, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)
    exclusive_text(state / 'vm.pid', str(process.pid) + '\n')
    exclusive_json(state / 'started.json', {'pid': process.pid, 'started_unix': time.time()})
    print(f'BUILD_VM_STARTED pid={process.pid}', flush=True)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    framing = CompleteLines()
    ready_line = b'PPP_BOOT_READY SESSION=' + session.encode()
    ready = False
    active = None
    active_log = None
    console = (state / 'console.log').open('xb', buffering=0)
    eof = False

    def send(text):
        payload = (text + '\n').encode()
        offset = 0
        while offset < len(payload):
            offset += os.write(process.stdin.fileno(), payload[offset:])

    while not eof:
        for key, _ in selector.select(timeout=0.5):
            data = os.read(key.fd, 65536)
            if not data:
                selector.unregister(key.fd)
                eof = True
                break
            console.write(data)
            if active_log:
                active_log.write(data)
            for line in framing.feed(data):
                if not ready and line == ready_line:
                    ready = True
                    exclusive_json(state / 'boot-ready.json', {'session': session,
                                                               'observed_unix': time.time()})
                    print('BUILD_VM_CONTROL_READY', flush=True)
                if active:
                    status = parse_receipt(line, active['pattern'])
                    if status is not None:
                        name = active['name']
                        active_log.flush()
                        os.fsync(active_log.fileno())
                        active_log.close()
                        active_log = None
                        exclusive_json(requests / (name + '.result.json'), {
                            'name': name, 'token': active['token'], 'exit': status,
                            'complete_newline_receipt': True,
                            'started_unix': active['started'], 'ended_unix': time.time(),
                        })
                        exclusive_text(requests / (name + '.status'), str(status) + '\n')
                        print(f'BUILD_COMMAND_DONE name={name} exit={status}', flush=True)
                        active = None
        if not eof and ready and active is None:
            for request in sorted(requests.glob('*.command')):
                name = request.stem
                if (requests / (name + '.status')).exists():
                    continue
                if not re.fullmatch(r'[A-Za-z0-9_-]{1,96}', name):
                    raise ValueError('Invalid queued command ID')
                if request.is_symlink() or request.resolve(strict=True) != request or not request.is_file():
                    raise ValueError('Queued command must be a canonical regular file')
                if (requests / (name + '.started.json')).exists():
                    raise ValueError('Command was previously started without a receipt; inspect it and use a distinct ID')
                raw = request.read_bytes()
                if len(raw) > 16384:
                    raise ValueError('Queued command is too long')
                shell_command = raw.decode('utf-8').removesuffix('\n')
                if not shell_command or any(c in shell_command for c in ('\n', '\r', '\0')):
                    raise ValueError('Expected exactly one nonempty shell command line')
                token = secrets.token_hex(16)
                started = time.time()
                exclusive_json(requests / (name + '.started.json'), {
                    'name': name, 'token': token, 'started_unix': started,
                })
                active_log = (requests / (name + '.console.log')).open('xb', buffering=0)
                active = {'name': name, 'token': token, 'started': started,
                          'pattern': receipt_pattern(name, token)}
                wrapper = ("{ " + shell_command + "\n}; ppp_command_exit=$?; printf "
                           "'\\nPPP_CMD_DONE_" + name + " TOKEN=" + token
                           + " EXIT=%s\\n' \"$ppp_command_exit\"")
                send(wrapper)
                print(f'BUILD_COMMAND_STARTED name={name}', flush=True)
                break
    if active:
        active_log.flush()
        os.fsync(active_log.fileno())
        active_log.close()
        exclusive_json(requests / (active['name'] + '.incomplete.json'), {
            'name': active['name'], 'token': active['token'],
            'complete_newline_receipt': False, 'exit': None,
            'reason': 'VM serial EOF before complete command receipt',
        })
    console.flush()
    os.fsync(console.fileno())
    console.close()
    result = process.wait()
    exclusive_json(state / 'vm-exit.json', {'qemu_exit': result, 'ended_unix': time.time(),
                                           'boot_ready_observed': ready})
    print(f'BUILD_VM_EXIT={result}', flush=True)
    return result


if __name__ == '__main__':
    raise SystemExit(main())
