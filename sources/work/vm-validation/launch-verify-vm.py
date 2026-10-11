#!/usr/bin/env python3
"""Headless systemd verification of the completed PinePhone Pro image.

snapshot: temporary QEMU writes over the original 14 GiB raw image.
growth: persistent writes ONLY to an existing 16 GiB disposable qcow2 overlay.
This launcher never creates, resizes or commits an image or writes SPI/USB/MMC.
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
import sys

BASE = Path('/path/to/workspace')
SHARE = BASE / 'work/share'
PUBLIC_IMAGE_NAME = 'Fedora-44-Plasma-Mobile-PinePhone-Pro-eMMC-20261010.img'
IMAGE = BASE / 'output' / (PUBLIC_IMAGE_NAME + '.crdownload')
KERNEL = BASE / 'kernel-build/output/Image-7.2.9-jon-ppp'
INITRAMFS = SHARE / 'ppp-final-initramfs.img'
ASSEMBLY_REPORT = SHARE / 'fedora-ppp-image-assembly.txt'
QEMU = BASE / 'build-tools/host-qemu/usr/bin/qemu-system-aarch64'
QEMU_IMG = Path('/usr/bin/qemu-img')
QEMU_DATA = Path('/usr/share/qemu')
QEMU_MODULES = Path('/usr/lib64/qemu')
ORIGINAL_BYTES = 14 * 1024**3
EXPANDED_BYTES = 16 * 1024**3


def fail(message: str) -> None:
    raise SystemExit(f'VM verification launcher: {message}')


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def report_value(key: str) -> str:
    values = [line[len(key) + 1:] for line in ASSEMBLY_REPORT.read_text().splitlines()
              if line.startswith(key + '=')]
    if len(values) != 1:
        fail(f'assembly report has missing or duplicate {key}.')
    return values[0]


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


def build_command(disk: Path, disk_format: str, kernel_arguments: str, mode: str,
                  *, cpus: int = 2, memory_mib: int = 1280) -> list[str]:
    """Construct explicit VirtIO MMIO devices for a CONFIG_PCI=n kernel."""
    if mode not in ('snapshot', 'growth') or disk_format not in ('raw', 'qcow2'):
        fail('invalid validation disk mode or format.')
    if not 1 <= cpus <= 16 or not 1024 <= memory_mib <= 8192:
        fail('VM resource configuration is out of bounds.')
    command = [
        str(QEMU), '-L', str(QEMU_DATA),
        '-M', 'virt', '-cpu', 'cortex-a72', '-accel', 'tcg,thread=multi,tb-size=128',
        '-smp', str(cpus), '-m', str(memory_mib), '-nographic', '-monitor', 'none',
        '-kernel', str(KERNEL), '-initrd', str(INITRAMFS),
        '-drive', f'file={disk},if=none,id=verifydisk,format={disk_format}',
        '-device', 'virtio-blk-device,drive=verifydisk,serial=PPP_VERIFY_ROOT',
        '-append', kernel_arguments,
        '-netdev', 'user,id=net0,restrict=on',
        '-device', 'virtio-net-device,netdev=net0',
        '-fsdev', f'local,id=buildshare,path={SHARE},security_model=none',
        '-device', 'virtio-9p-device,fsdev=buildshare,mount_tag=build',
    ]
    if mode == 'snapshot':
        command.append('-snapshot')
    return command


def add_arguments(parser):
    parser.add_argument('--mode', choices=('snapshot', 'growth'), default='snapshot')
    parser.add_argument('--overlay', type=Path, default=BASE / 'work/fedora-ppp-validation.qcow2')
    parser.add_argument('--cpus', type=int, default=2)
    parser.add_argument('--memory-mib', type=int, default=1280)


def configuration(args):
    for path in (IMAGE, KERNEL, INITRAMFS, ASSEMBLY_REPORT, QEMU, QEMU_IMG):
        if (path.is_symlink() or path.resolve(strict=True) != path or not path.is_file() or path.stat().st_size == 0):
            fail(f'required input must be canonical, nonsymlink and nonempty: {path}')
    if (IMAGE.is_symlink() or IMAGE.resolve(strict=True) != IMAGE
            or not stat.S_ISREG(IMAGE.lstat().st_mode)):
        fail('staged raw image must be the exact canonical nonsymlink regular file.')
    if IMAGE.lstat().st_size != ORIGINAL_BYTES:
        fail('delivered raw image is not exactly 14 GiB.')
    root_uuid = report_value('ROOT_UUID')
    if not re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', root_uuid):
        fail('assembly report root UUID is invalid.')
    if report_value('KERNEL_RELEASE') != '7.2.9-jon-ppp' or report_value('FINAL_ROOT_FS') != 'ext4':
        fail('assembly report is for a different kernel or root filesystem.')
    with KERNEL.open('rb') as handle:
        header = handle.read(64)
    if len(header) != 64 or header[56:60] != b'ARM\x64':
        fail('custom kernel is not a raw ARM64 Image.')
    with INITRAMFS.open('rb') as handle:
        if handle.read(2) != b'\x1f\x8b':
            fail('final portable initramfs is not gzip as specified by the updater.')

    environment = runtime_environment()
    if args.mode == 'growth':
        if args.overlay.is_symlink() or not args.overlay.is_file():
            fail(f'disposable growth overlay is missing or a symlink: {args.overlay}')
        disk = args.overlay.resolve(strict=True)
        if args.overlay.absolute() != disk or not stat.S_ISREG(args.overlay.lstat().st_mode):
            fail('growth overlay must be a canonical nonsymlink regular file.')
        if disk == IMAGE.resolve() or disk.suffix != '.qcow2' or not disk.is_relative_to(BASE / 'work'):
            fail('growth overlay must be a separate .qcow2 file under work/.')
        info = json.loads(subprocess.check_output(
            [str(QEMU_IMG), 'info', '--backing-chain', '--output=json', str(disk)],
            env=environment, cwd=BASE, text=True, timeout=30))
        if not isinstance(info, list) or len(info) != 2 or not all(isinstance(x, dict) for x in info):
            fail('growth overlay must have exactly one raw backing file.')
        overlay_info, backing_info = info
        backing_name = overlay_info.get('full-backing-filename') or overlay_info.get('backing-filename')
        if not backing_name:
            fail('growth overlay has no backing file.')
        backing_path = Path(backing_name)
        if not backing_path.is_absolute():
            backing_path = disk.parent / backing_path
        if (overlay_info.get('format') != 'qcow2'
                or overlay_info.get('virtual-size') != EXPANDED_BYTES
                or backing_info.get('format') != 'raw'
                or backing_info.get('virtual-size') != ORIGINAL_BYTES
                or backing_path.absolute() != IMAGE
                or backing_path.resolve(strict=True) != IMAGE
                or Path(backing_info['filename']).absolute() != IMAGE
                or Path(backing_info['filename']).resolve(strict=True) != IMAGE
                or Path(overlay_info.get('filename', '')).absolute() != disk):
            fail('overlay format/size/backing file does not match the finished image.')
        disk_format = 'qcow2'
    else:
        disk = IMAGE
        disk_format = 'raw'

    kernel_arguments = ' '.join([
        f'root=UUID={root_uuid}', 'rootfstype=ext4', 'rw', 'rootwait',
        'console=ttyAMA0,115200n8', 'systemd.unit=multi-user.target',
        'plymouth.enable=0', 'systemd.debug_shell=ttyAMA0', 'systemd.mask=serial-getty@ttyAMA0.service',
    ])
    command = build_command(disk, disk_format, kernel_arguments, args.mode,
                            cpus=args.cpus, memory_mib=args.memory_mib)
    # No graphics/virtio DRM device and no init=/bin/bash override. Temporary
    # debug-shell arguments exist only in this VM launch, not phone boot menus.
    metadata = {
        'mode': args.mode, 'disk': str(disk), 'delivered_image': str(IMAGE),
        'public_image_name': PUBLIC_IMAGE_NAME,
        'root_uuid': root_uuid, 'kernel': str(KERNEL), 'kernel_sha256': sha256(KERNEL),
        'initramfs': str(INITRAMFS), 'initramfs_sha256': sha256(INITRAMFS),
        'kernel_arguments': kernel_arguments, 'qemu_command': command,
        'graphics_tested': False, 'physical_hardware_tested': False,
        'validation_status': 'unverified_launch', 'virtio_transport': 'mmio',
        'guest_disk_serial': 'PPP_VERIFY_ROOT',
    }
    return command, environment, metadata


def prepare_runtime(metadata):
    if metadata['mode'] == 'growth':
        marker = SHARE / 'ALLOW_DISPOSABLE_IMAGE_GROWTH_TEST'
        if marker.is_symlink() or (marker.exists() and marker.read_text() != 'QEMU_OVERLAY_14GiB_TO_16GiB\n'):
            fail('growth-test permission marker conflicts with reviewed value.')
        marker.write_text('QEMU_OVERLAY_14GiB_TO_16GiB\n')
    report = SHARE / 'vm-verification-launch.json'
    if report.is_symlink():
        fail('launch metadata path is a symlink.')
    report.write_text(json.dumps(metadata, indent=2) + '\n')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_arguments(parser)
    parser.add_argument('--run', action='store_true', help='Start QEMU only when explicitly requested')
    args = parser.parse_args()
    command, environment, metadata = configuration(args)
    if not args.run:
        print(json.dumps({'preflight_passed': True, 'vm_launched': False, 'inputs': metadata}, indent=2), flush=True)
        return 0
    prepare_runtime(metadata)
    print(f'Launching normal systemd boot: {args.mode}; root UUID {metadata["root_uuid"]}', flush=True)
    try:
        return subprocess.run(command, env=environment, cwd=BASE).returncode
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    sys.exit(main())
