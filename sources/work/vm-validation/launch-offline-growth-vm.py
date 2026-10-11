#!/usr/bin/env python3
"""Offline checks of a readonly grown overlay from a disposable source snapshot.

No images are created, resized, committed or repaired by this launcher.
The guest controller must discover both serial identities before accepting READY.
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

BASE = Path('/path/to/workspace')
SHARE = BASE / 'work/share'
PUBLIC_IMAGE_NAME = 'Fedora-44-Plasma-Mobile-PinePhone-Pro-eMMC-20261010.img'
IMAGE = BASE / 'output' / (PUBLIC_IMAGE_NAME + '.crdownload')
GROWTH = BASE / 'work/fedora-ppp-validation.qcow2'
SOURCE = BASE / 'work/fedora44-rebuild.qcow2.crdownload'
SOURCE_BACKING = BASE / 'work/fedora44-base.raw.crdownload'
SOURCE_INITRAMFS = SHARE / 'fedora-source-initramfs.img'
SOURCE_STATE = SHARE / 'fresh-package-state.json'
SOURCE_AUDIT = SHARE / 'fedora-source-initramfs-portability.json'
KERNEL_REPORT = SHARE / 'fedora-kernel-install-report.json'
KERNEL = BASE / 'kernel-build/output/Image-7.2.9-jon-ppp'
QEMU = BASE / 'build-tools/host-qemu/usr/bin/qemu-system-aarch64'
QEMU_IMG = Path('/usr/bin/qemu-img')
QEMU_DATA = Path('/usr/share/qemu')
QEMU_MODULES = Path('/usr/lib64/qemu')
RAW_BYTES, GROWN_BYTES, SOURCE_BYTES = 14 * 1024**3, 16 * 1024**3, 12206473216


def fail(message):
    raise ValueError('Offline growth launcher: ' + message)


def regular(path, size=None):
    path = Path(path).absolute()
    if path.is_symlink() or path.resolve(strict=True) != path or not stat.S_ISREG(path.lstat().st_mode):
        fail('input must be a canonical nonsymlink regular file: ' + str(path))
    actual = path.lstat().st_size
    if not actual or (size is not None and actual != size):
        fail('input size differs: ' + str(path))
    return path


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def source_initramfs_evidence(initramfs, state_path=SOURCE_STATE, audit_path=SOURCE_AUDIT, kernel_path=KERNEL_REPORT):
    """Bind the exported source dracut archive to measured installed evidence."""
    records = []
    for path in (state_path, audit_path, kernel_path):
        regular(path)
        if path.stat().st_size > 8 * 1024**2:
            fail('source evidence exceeds its bounded metadata size')
        value = json.loads(path.read_text())
        if not isinstance(value, dict):
            fail('source evidence must be a JSON object')
        records.append(value)
    state, audit, kernel = records
    archive = state.get('source_initramfs', {})
    measured_audit = state.get('source_initramfs_audit', {})
    if not isinstance(archive, dict) or not isinstance(measured_audit, dict):
        fail('source aggregate archive records are missing')
    digest, size = sha256(initramfs), initramfs.stat().st_size
    audit_digest, audit_size = sha256(audit_path), audit_path.stat().st_size
    if (state.get('status') != 'fresh_phone_packages_verified'
            or archive.get('path') != '/boot/initramfs-7.2.9-jon-ppp.img'
            or archive.get('sha256') != digest or archive.get('size_bytes') != size
            or measured_audit.get('path') != '/build/fedora-source-initramfs-portability.json'
            or measured_audit.get('sha256') != audit_digest or measured_audit.get('size_bytes') != audit_size
            or audit.get('status') != 'passed' or audit.get('gzip_streams') != 1
            or audit.get('archive_sha256') != digest or audit.get('archive_bytes') != size
            or kernel.get('status') != 'kernel_release3_built_installed_verified'
            or kernel.get('initramfs_sha256') != digest or kernel.get('initramfs_size_bytes') != size
            or kernel.get('portable_initramfs_audit') != '/build/fedora-source-initramfs-portability.json'
            or kernel.get('portable_initramfs_audit_sha256') != audit_digest):
        fail('source initramfs does not match its installed aggregate, strict audit and kernel evidence')
    return {'source_state_sha256': sha256(state_path), 'source_audit_sha256': audit_digest,
            'source_kernel_report_sha256': sha256(kernel_path)}


def runtime_environment():
    """Use only the fixed, root-owned system runtime reviewed for this host."""
    for path in (QEMU_IMG, QEMU_DATA, QEMU_MODULES):
        metadata = path.lstat()
        correct_type = (stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1
                        and metadata.st_size > 0 and os.access(path, os.X_OK)
                        if path == QEMU_IMG else stat.S_ISDIR(metadata.st_mode))
        if (path.resolve(strict=True) != path or not correct_type
                or metadata.st_uid != 0 or metadata.st_mode & 0o022):
            fail('unexpected or writable system runtime path: ' + str(path))
    environment = os.environ.copy()
    environment.pop('LD_LIBRARY_PATH', None)
    environment.pop('LD_PRELOAD', None)
    environment['QEMU_MODULE_DIR'] = str(QEMU_MODULES)
    return environment


def backing_chain(overlay, backing, overlay_bytes, backing_bytes, environment):
    info = json.loads(subprocess.check_output(
        [str(QEMU_IMG), 'info', '--backing-chain', '--output=json', str(overlay)],
        env=environment, cwd=BASE, text=True, timeout=30))
    if not isinstance(info, list) or len(info) != 2 or not all(isinstance(x, dict) for x in info):
        fail('overlay must have exactly one raw backing file')
    top, raw = info
    names = [top.get('full-backing-filename') or top.get('backing-filename'), raw.get('filename')]
    if any(not isinstance(x, str) or not x for x in names):
        fail('backing chain filename is missing')
    paths = [Path(x) if Path(x).is_absolute() else overlay.parent / x for x in names]
    if (top.get('format') != 'qcow2' or top.get('virtual-size') != overlay_bytes
            or raw.get('format') != 'raw' or raw.get('virtual-size') != backing_bytes
            or any(x.absolute() != backing or x.resolve(strict=True) != backing for x in paths)
            or Path(top.get('filename', '')).absolute() != overlay
            or Path(top.get('filename', '')).absolute().resolve(strict=True) != overlay):
        fail('overlay format, geometry or backing identity differs')


def add_arguments(parser):
    parser.add_argument('--source-disk', type=Path, required=True)
    parser.add_argument('--source-root-uuid', required=True)
    parser.add_argument('--source-bytes', type=int, required=True)
    parser.add_argument('--source-initramfs', type=Path, default=SOURCE_INITRAMFS)
    parser.add_argument('--cpus', type=int, default=2)
    parser.add_argument('--memory-mib', type=int, default=1280)


def build_command(source, growth, source_uuid, initramfs, *, cpus=2, memory_mib=1280):
    # Actual MMIO discovery reversed the historical insertion order. Insert the
    # target first and source second, then still check serials inside the guest.
    if not 1 <= cpus <= 16 or not 1024 <= memory_mib <= 8192:
        fail('VM resource configuration is out of bounds')
    return [
        str(QEMU), '-L', str(QEMU_DATA),
        '-M', 'virt', '-cpu', 'cortex-a72', '-accel', 'tcg,thread=multi,tb-size=128',
        '-smp', str(cpus), '-m', str(memory_mib), '-nographic', '-monitor', 'none',
        '-kernel', str(KERNEL), '-initrd', str(initramfs),
        '-drive', f'file={growth},if=none,id=growthdisk,format=qcow2,readonly=on',
        '-device', 'virtio-blk-device,drive=growthdisk,serial=PPP_GROWTH_TARGET',
        '-drive', f'file={source},if=none,id=sourcedisk,format=qcow2,snapshot=on',
        '-device', 'virtio-blk-device,drive=sourcedisk,serial=PPP_OFFLINE_SOURCE',
        '-append', f'root=UUID={source_uuid} rootfstype=btrfs rootflags=subvol=root rw rootwait console=ttyAMA0,115200n8 plymouth.enable=0 init=/bin/bash quiet',
        '-netdev', 'user,id=net0,restrict=on', '-device', 'virtio-net-device,netdev=net0',
        '-fsdev', f'local,id=buildshare,path={SHARE},security_model=none',
        '-device', 'virtio-9p-device,fsdev=buildshare,mount_tag=build',
    ]


def configuration(args):
    source = Path(args.source_disk).absolute()
    if source != SOURCE or args.source_bytes != SOURCE_BYTES:
        fail('source must be the explicit fresh rebuild overlay and verified source geometry')
    if args.source_root_uuid != '6741cdec-fe58-4214-9fa9-3e8eaa52f476':
        fail('source UUID must match the explicitly verified fresh source')
    regular(IMAGE, RAW_BYTES)
    regular(GROWTH)
    regular(source)
    regular(SOURCE_BACKING, SOURCE_BYTES)
    regular(KERNEL)
    regular(QEMU)
    regular(QEMU_IMG)
    initramfs = regular(args.source_initramfs)
    if initramfs != SOURCE_INITRAMFS:
        fail('source initramfs must be the exact separately exported source-root dracut archive')
    source_evidence = source_initramfs_evidence(initramfs)
    with KERNEL.open('rb') as stream:
        header = stream.read(64)
    if len(header) != 64 or header[56:60] != b'ARM\x64':
        fail('kernel is not a raw ARM64 Image')
    with initramfs.open('rb') as stream:
        prefix = stream.read(6)
        # The exact SHA-verified audit above parses all concatenated members.
        # Fedora dracut may prepend an uncompressed early cpio to its gzip body.
        if not (prefix.startswith(b'\x1f\x8b') or prefix in (b'070701', b'070702')):
            fail('source initramfs lacks its audited cpio/gzip header')
    environment = runtime_environment()
    backing_chain(GROWTH, IMAGE, GROWN_BYTES, RAW_BYTES, environment)
    backing_chain(source, SOURCE_BACKING, SOURCE_BYTES, SOURCE_BYTES, environment)
    command = build_command(source, GROWTH, args.source_root_uuid, initramfs,
                            cpus=args.cpus, memory_mib=args.memory_mib)
    metadata = {
        'mode': 'offline', 'validation_status': 'unverified_launch',
        'delivered_image': str(IMAGE), 'public_image_name': PUBLIC_IMAGE_NAME,
        'growth_overlay': str(GROWTH), 'growth_bytes': GROWN_BYTES, 'growth_readonly': True,
        'source_disk': str(source), 'source_backing': str(SOURCE_BACKING),
        'source_bytes': SOURCE_BYTES, 'source_root_uuid': args.source_root_uuid,
        'source_disk_mode': 'snapshot', 'source_serial': 'PPP_OFFLINE_SOURCE',
        'growth_serial': 'PPP_GROWTH_TARGET', 'guest_mapping_requires_checked_serials': True,
        'kernel': str(KERNEL), 'kernel_sha256': sha256(KERNEL),
        'initramfs': str(initramfs), 'initramfs_sha256': sha256(initramfs),
        'qemu_command': command, 'virtio_transport': 'mmio',
        'graphics_tested': False, 'physical_hardware_tested': False,
        **source_evidence,
    }
    return command, environment, metadata


def prepare_runtime(metadata):
    marker = SHARE / 'ALLOW_DISPOSABLE_IMAGE_GROWTH_TEST'
    if marker.is_symlink() or not marker.is_file() or marker.read_text() != 'QEMU_OVERLAY_14GiB_TO_16GiB\n':
        fail('online growth-test permission marker is missing or conflicts')
    report = SHARE / 'vm-offline-growth-launch.json'
    if report.is_symlink():
        fail('offline launch metadata path is a symlink')
    report.write_text(json.dumps(metadata, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_arguments(parser)
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    command, environment, metadata = configuration(args)
    if not args.run:
        print(json.dumps({'preflight_passed': True, 'vm_launched': False, 'inputs': metadata}, indent=2))
        return 0
    prepare_runtime(metadata)
    return subprocess.run(command, env=environment, cwd=BASE).returncode


if __name__ == '__main__':
    raise SystemExit(main())
