#!/usr/bin/env python3
"""Preflight and command construction for the resumed isolated Fedora VM.

This module creates no disks and starts no VM when imported. Root owns all
downloads, authenticated source verification, overlays and final image files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

WORKSPACE = Path('/path/to/workspace')
KERNEL_SHA = '7798442dabf187b3a7da5e2cd1fe0b1acdf6b70cf0def331d16f5dac5cf9f8dc'
CONFIG_SHA = '888eb1e305d0bf9b07452f3b8edb4a4204833c39eb36042dc1efc6b0dec8a71d'
SOURCE_BYTES = 12206473216
TARGET_BYTES = 14 * 1024**3
ROOT_UUID = '6741cdec-fe58-4214-9fa9-3e8eaa52f476'


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def canonical_file(path, *, size=None):
    path = Path(path).absolute()
    metadata = path.lstat()
    if (not path.is_relative_to(WORKSPACE) or path.resolve(strict=True) != path
            or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
            or metadata.st_size <= 0 or (size is not None and metadata.st_size != size)):
        raise ValueError(f'Input must be a canonical, nonempty, single-link regular workspace file: {path}')
    return path


def canonical_directory(path):
    path = Path(path).absolute()
    if not path.is_relative_to(WORKSPACE) or path.resolve(strict=True) != path or not path.is_dir():
        raise ValueError(f'Input must be a canonical workspace directory: {path}')
    return path


def host_runtime_path(path, expected, *, directory=False):
    """Allow only the exact, root-owned system paths reviewed for this host."""
    path = Path(path).absolute()
    metadata = path.lstat()
    correct_type = (stat.S_ISDIR(metadata.st_mode) if directory else
                    stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1
                    and metadata.st_size > 0 and os.access(path, os.X_OK))
    if (path != Path(expected) or path.resolve(strict=True) != path
            or not correct_type or metadata.st_uid != 0
            or metadata.st_mode & 0o022):
        raise ValueError(f'Unexpected or writable host QEMU runtime path: {path}')
    return path


def add_arguments(parser):
    parser.add_argument('--qemu', type=Path, required=True)
    parser.add_argument('--qemu-img', type=Path, required=True)
    parser.add_argument('--qemu-data', type=Path, required=True)
    parser.add_argument('--library-dir', type=Path, required=True)
    parser.add_argument('--host-runtime', action='store_true',
                        help='Use the staged openSUSE ARM QEMU with the exact reviewed system runtime paths')
    parser.add_argument('--base', type=Path, required=True, help='Verified original official raw source, unchanged')
    parser.add_argument('--overlay', type=Path, required=True, help='Existing disposable qcow2 overlay over the verified base')
    parser.add_argument('--kernel', type=Path, required=True)
    parser.add_argument('--kernel-config', type=Path, required=True)
    parser.add_argument('--initrd', type=Path, required=True, help='Build-only initramfs generated from authenticated ARM64 static BusyBox')
    parser.add_argument('--initrd-sha256', required=True)
    parser.add_argument('--share', type=Path, required=True)
    parser.add_argument('--target', type=Path, help='Optional existing dedicated empty nonsymlink 14 GiB raw image')
    parser.add_argument('--cpus', type=int, default=8)
    parser.add_argument('--memory-mib', type=int, default=3072)


def configuration(args, session):
    if not re.fullmatch(r'[0-9a-f]{32}', session):
        raise ValueError('Invalid boot session token')
    if not re.fullmatch(r'[0-9a-f]{64}', args.initrd_sha256):
        raise ValueError('Invalid expected build initrd digest')
    if not 1 <= args.cpus <= 16 or not 1024 <= args.memory_mib <= 8192:
        raise ValueError('VM resource configuration is out of bounds')
    qemu = canonical_file(args.qemu)
    if args.host_runtime:
        if (qemu != WORKSPACE / 'build-tools/host-qemu/usr/bin/qemu-system-aarch64'
                or not os.access(qemu, os.X_OK)):
            raise ValueError('Host runtime requires the exact staged openSUSE ARM QEMU executable')
        qemu_img = host_runtime_path(args.qemu_img, '/usr/bin/qemu-img')
        qemu_data = host_runtime_path(args.qemu_data, '/usr/share/qemu', directory=True)
        library_dir = host_runtime_path(args.library_dir, '/usr/lib64', directory=True)
    else:
        qemu_img = canonical_file(args.qemu_img)
        qemu_data, library_dir = canonical_directory(args.qemu_data), canonical_directory(args.library_dir)
    base = canonical_file(args.base, size=SOURCE_BYTES)
    overlay = canonical_file(args.overlay)
    kernel, config, initrd = map(canonical_file, (args.kernel, args.kernel_config, args.initrd))
    share = canonical_directory(args.share)
    if ',' in ''.join(str(path) for path in (base, overlay, share)):
        raise ValueError('QEMU option paths cannot contain commas')
    if overlay == base or not (overlay.name.endswith('.qcow2') or overlay.name.endswith('.qcow2.crdownload')):
        raise ValueError('Source overlay must be a distinct existing qcow2 file')
    if sha256(kernel) != KERNEL_SHA or sha256(config) != CONFIG_SHA or sha256(initrd) != args.initrd_sha256:
        raise ValueError('Kernel/config/initrd full hash mismatch')
    config_text = config.read_text()
    builtins = ('VIRTIO', 'VIRTIO_MMIO', 'VIRTIO_BLK', 'VIRTIO_NET', 'NET_9P',
                'NET_9P_VIRTIO', '9P_FS', 'BTRFS_FS', 'EXT4_FS', 'VFAT_FS',
                'DEVTMPFS', 'TMPFS', 'BLK_DEV_INITRD', 'RD_GZIP', 'SERIAL_AMBA_PL011_CONSOLE')
    if any(f'CONFIG_{key}=y\n' not in config_text for key in builtins):
        raise ValueError('Build boot requires all MMIO/storage/share/serial drivers built in')
    if '# CONFIG_PCI is not set\n' not in config_text:
        raise ValueError('Reviewed device mapping is for the pinned no-PCI kernel')
    with kernel.open('rb') as handle:
        if handle.read(64)[56:60] != b'ARM\x64':
            raise ValueError('Kernel is not a raw ARM64 Image')
    with initrd.open('rb') as handle:
        if handle.read(2) != b'\x1f\x8b':
            raise ValueError('Build initrd must be gzip')
    for filename in ('bootstrap-build.sh',):
        canonical_file(share / filename)
    environment = os.environ.copy()
    if args.host_runtime:
        environment.pop('LD_LIBRARY_PATH', None)
        environment.pop('LD_PRELOAD', None)
        environment['QEMU_MODULE_DIR'] = str(host_runtime_path(
            library_dir / 'qemu', '/usr/lib64/qemu', directory=True))
    else:
        environment['LD_LIBRARY_PATH'] = str(library_dir) + ':' + str(canonical_directory(library_dir.parents[2] / 'lib/x86_64-linux-gnu'))
        environment['QEMU_MODULE_DIR'] = str(canonical_directory(library_dir / 'qemu'))
    chain = json.loads(subprocess.check_output(
        [str(qemu_img), 'info', '--backing-chain', '--output=json', str(overlay)],
        env=environment, text=True))
    if len(chain) != 2:
        raise ValueError('Source overlay must have exactly one raw backing file')
    head, backing = chain
    backing_name = head.get('full-backing-filename') or head.get('backing-filename')
    if not backing_name:
        raise ValueError('Source overlay has no backing file')
    path = Path(backing_name)
    if not path.is_absolute():
        path = overlay.parent / path
    if (head.get('format') != 'qcow2' or head.get('virtual-size') != SOURCE_BYTES
            or backing.get('format') != 'raw' or backing.get('virtual-size') != SOURCE_BYTES
            or path.resolve() != base or Path(backing['filename']).resolve() != base):
        raise ValueError('Overlay/backing format, size or path disagrees with the official source')
    command = [str(qemu), '-L', str(qemu_data), '-M', 'virt', '-cpu', 'cortex-a72',
               '-accel', 'tcg,thread=multi', '-smp', str(args.cpus), '-m', str(args.memory_mib),
               '-nodefaults', '-display', 'none', '-serial', 'stdio', '-monitor', 'none',
               '-rtc', 'base=utc,clock=host', '-kernel', str(kernel), '-initrd', str(initrd),
               '-drive', f'file={overlay},if=none,id=source,format=qcow2',
               '-device', 'virtio-blk-device,drive=source',
               '-append', f'root=UUID={ROOT_UUID} rootflags=subvol=root rw console=ttyAMA0,115200n8 pppbuild.session={session}',
               '-netdev', 'user,id=net0', '-device', 'virtio-net-device,netdev=net0',
               '-fsdev', f'local,id=buildfs,path={share},security_model=none',
               '-device', 'virtio-9p-device,fsdev=buildfs,mount_tag=build']
    if args.target:
        target = canonical_file(args.target, size=TARGET_BYTES)
        if target in (base, overlay, kernel, config, initrd) or ',' in str(target):
            raise ValueError('Invalid dedicated target file')
        if not target.name.endswith('.img.crdownload'):
            raise ValueError('Target must use excluded .img.crdownload staging name')
        # Observed QEMU virt MMIO block devices enumerate in reverse creation order.
        # Put target before source so the verified source becomes vda, target vdb.
        insert_at = command.index('-drive')
        command[insert_at:insert_at] = ['-drive', f'file={target},if=none,id=target,format=raw',
                                      '-device', 'virtio-blk-device,drive=target']
    return command, environment


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    add_arguments(parser)
    parser.add_argument('--session', required=True)
    args = parser.parse_args()
    command, _ = configuration(args, args.session)
    print(json.dumps({'preflight_passed': True, 'qemu_command': command,
                      'vm_launched': False, 'physical_hardware_tested': False}, indent=2))
