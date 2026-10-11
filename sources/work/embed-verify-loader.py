#!/usr/bin/env python3
"""Embed the reviewed loader into this build's exact regular image file only.

Run after guest assembly completes and QEMU stops. No phone/device path is accepted.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import sys
import uuid
import zlib

from image_use_guard import ImageUseGuard, ImageGuardError

BASE = Path(__file__).resolve().parent.parent
PUBLIC_IMAGE_NAME = 'Fedora-44-Plasma-Mobile-PinePhone-Pro-eMMC-20261010.img'
IMAGE = BASE / 'output' / (PUBLIC_IMAGE_NAME + '.crdownload')
LOADER = BASE / 'bootloader-build/output/u-boot-rockchip.bin'
ASSEMBLY = BASE / 'work/share/fedora-ppp-image-assembly.txt'
RECEIPT = BASE / 'output/boot-disk-verification.json'
LOADER_SHA256 = '8665b27f27b9caad6976e49c7fd800342726d4d627f95672dad798f6e048b000'
IMAGE_BYTES = 14 * 1024**3
SECTOR = 512
LOADER_OFFSET = 64 * SECTOR
FIRST_PARTITION = 65536
ZERO_GUID = str(uuid.UUID(int=0))
EFI_TYPE = 'c12a7328-f81f-11d2-ba4b-00a0c93ec93b'
LINUX_TYPE = '0fc63daf-8483-4772-8e79-3d69d8477de4'


class VerificationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def read_at(fd: int, offset: int, count: int) -> bytes:
    value = os.pread(fd, count, offset)
    require(len(value) == count, f'Short read at image offset {offset}.')
    return value


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def guid(value: bytes) -> str:
    return str(uuid.UUID(bytes_le=value))


def parse_gpt(fd: int, image_bytes: int) -> dict:
    require(image_bytes == IMAGE_BYTES, 'Image must be exactly 14 GiB.')
    sectors = image_bytes // SECTOR
    mbr = read_at(fd, 0, SECTOR)
    require(mbr[510:512] == b'\x55\xaa', 'Missing protective MBR signature.')
    rows = [mbr[446 + index * 16:462 + index * 16] for index in range(4)]
    require(rows[0][0] == 0 and rows[0][4] == 0xee, 'Protective MBR entry is incorrect.')
    start, length = struct.unpack_from('<II', rows[0], 8)
    require((start, length) == (1, min(sectors - 1, 0xffffffff)), 'Protective MBR range is incorrect.')
    require(all(row == bytes(16) for row in rows[1:]), 'Unexpected hybrid MBR entries.')

    def header(lba: int) -> dict:
        sector_data = read_at(fd, lba * SECTOR, SECTOR)
        fields = struct.unpack_from('<8sIIIIQQQQ16sQIII', sector_data)
        signature, revision, header_size, header_crc, reserved, current, alternate, first, last, disk_guid, entries_lba, entry_count, entry_size, entries_crc = fields
        require(signature == b'EFI PART' and revision == 0x00010000, 'Unexpected GPT signature/revision.')
        require(header_size == 92 and reserved == 0, 'Unexpected GPT header size/reserved field.')
        checked_header = bytearray(sector_data[:header_size])
        checked_header[16:20] = bytes(4)
        require(zlib.crc32(checked_header) == header_crc, f'GPT header CRC failed at LBA {lba}.')
        require(current == lba, 'GPT current-LBA mismatch.')
        require(entry_count == 128 and entry_size == 128, 'Unexpected GPT entry geometry.')
        require(first == FIRST_PARTITION and last == sectors - 34, 'Unexpected GPT usable-LBA range.')
        require(guid(disk_guid) != ZERO_GUID, 'GPT disk GUID is zero.')
        entries_bytes = entry_count * entry_size
        require(entries_lba >= 2 and entries_lba + entries_bytes // SECTOR <= sectors - 1, 'GPT entry array is outside the disk.')
        array = read_at(fd, entries_lba * SECTOR, entries_bytes)
        require(zlib.crc32(array) == entries_crc, f'GPT entry-array CRC failed at LBA {lba}.')
        return {'lba': current, 'alternate_lba': alternate, 'first_usable_lba': first,
                'last_usable_lba': last, 'disk_guid': guid(disk_guid),
                'entries_lba': entries_lba, 'entry_count': entry_count, 'entry_size': entry_size,
                'header_crc32': f'{header_crc:08x}', 'entries_crc32': f'{entries_crc:08x}',
                'sector': sector_data, 'array': array}

    primary = header(1)
    backup = header(sectors - 1)
    require(primary['alternate_lba'] == sectors - 1 and backup['alternate_lba'] == 1, 'GPT primary/backup pointers mismatch.')
    require(primary['entries_lba'] == 2 and backup['entries_lba'] == sectors - 33, 'Unexpected GPT array placement.')
    require(primary['disk_guid'] == backup['disk_guid'] and primary['array'] == backup['array'], 'GPT primary/backup identities or arrays differ.')
    require(LOADER_OFFSET >= (primary['entries_lba'] + 32) * SECTOR, 'Loader would overlap primary GPT metadata.')

    partitions = []
    for index in range(128):
        entry = primary['array'][index * 128:(index + 1) * 128]
        if entry[:16] == bytes(16):
            require(entry == bytes(128), 'Unused GPT entry contains nonzero data.')
            continue
        type_guid, part_guid, begin, end, attrs = struct.unpack_from('<16s16sQQQ', entry)
        name = entry[56:128].decode('utf-16le').split('\0', 1)[0]
        partitions.append({'number': index + 1, 'type_guid': guid(type_guid), 'partition_guid': guid(part_guid),
                           'start_lba': begin, 'end_lba': end, 'size_sectors': end - begin + 1,
                           'attributes': attrs, 'legacy_bios_bootable': bool(attrs & (1 << 2)), 'name': name})
    expected = [
        (1, FIRST_PARTITION, 1024000, EFI_TYPE, 'FEDORA_EFI', 4),
        (2, FIRST_PARTITION + 1024000, 4194304, LINUX_TYPE, 'FEDORA_BOOT', 4),
        # sfdisk ends its automatically sized partition at a MiB boundary.
        # This is also the exact 24074240-sector geometry required by the
        # independent 14-to-16 GiB growth test, leaving 2015 usable sectors.
        (3, FIRST_PARTITION + 1024000 + 4194304,
         ((primary['last_usable_lba'] + 1) // 2048 * 2048) - (FIRST_PARTITION + 1024000 + 4194304),
         LINUX_TYPE, 'FEDORA_ROOT', 0),
    ]
    require(len(partitions) == 3, 'Exactly three GPT partitions are required.')
    for actual, wanted in zip(partitions, expected):
        fields = ('number', 'start_lba', 'size_sectors', 'type_guid', 'name', 'attributes')
        require(tuple(actual[key] for key in fields) == wanted, f'Unexpected geometry/type/boot attributes for partition {actual["number"]}.')
        require(actual['partition_guid'] != ZERO_GUID, 'A partition GUID is zero.')
    identities = [primary['disk_guid'], *[part['partition_guid'] for part in partitions]]
    require(len(identities) == len(set(identities)), 'Disk and partition GUIDs are not unique.')
    metadata = mbr + primary['sector'] + primary['array'] + backup['array'] + backup['sector']
    return {'primary': primary, 'backup': backup, 'partitions': partitions,
            'metadata_sha256': sha(metadata), 'primary_metadata_end': (primary['entries_lba'] + 32) * SECTOR}


def parse_assembly(text: str) -> dict:
    require('TARGET=internal-eMMC' in text.splitlines(), 'Assembly report is not for internal eMMC.')
    require('IMAGE_BYTES=' + str(IMAGE_BYTES) in text.splitlines(), 'Assembly report image size mismatch.')
    require('FINAL_ROOT_FS=ext4' in text.splitlines(), 'Assembly report root filesystem is not ext4.')
    values = {}
    for key in ('ROOT_UUID', 'BOOT_UUID', 'EFI_UUID'):
        matches = re.findall(r'^' + key + r'=([^\n]+)$', text, re.M)
        require(len(matches) == 1, f'Assembly report lacks one unique {key}.')
        values[key] = matches[0].lower()
    disk_guid = re.findall(r'^label-id:\s*([^\n]+)$', text, re.M)
    require(len(disk_guid) == 1, 'Assembly report disk GUID is absent or duplicated.')
    values['disk_guid'] = str(uuid.UUID(disk_guid[0]))
    values['partitions'] = {}
    for number in (1, 2, 3):
        matches = re.findall(r'^/dev/vdb' + str(number) + r'\s*:\s*(.+)$', text, re.M)
        require(len(matches) == 1, f'Assembly report lacks one partition {number} row.')
        row = matches[0]
        result = {}
        for key in ('start', 'size', 'type', 'uuid'):
            match = re.search(r'\b' + key + r'\s*=\s*([^,\s]+)', row)
            require(match is not None, f'Assembly report partition {number} lacks {key}.')
            result[key] = match.group(1)
        values['partitions'][number] = {'start_lba': int(result['start']), 'size_sectors': int(result['size']),
                                       'type_guid': str(uuid.UUID(result['type'])), 'partition_guid': str(uuid.UUID(result['uuid']))}
    return values


def validate_filesystems(fd: int, gpt: dict, assembly: dict) -> list:
    require(gpt['primary']['disk_guid'] == assembly['disk_guid'], 'GPT disk GUID differs from the assembly report.')
    output = []
    for part in gpt['partitions']:
        number = part['number']
        for key, expected in assembly['partitions'][number].items():
            require(part[key] == expected, f'GPT partition {number} {key} differs from the assembly report.')
        start = part['start_lba'] * SECTOR
        if number == 1:
            bpb = read_at(fd, start, SECTOR)
            require(bpb[510:512] == b'\x55\xaa' and bpb[82:90] == b'FAT32   ', 'p1 is not a FAT32 boot filesystem.')
            require(struct.unpack_from('<H', bpb, 11)[0] == SECTOR and struct.unpack_from('<H', bpb, 22)[0] == 0, 'FAT32 BPB geometry mismatch.')
            require(0 < struct.unpack_from('<I', bpb, 32)[0] <= part['size_sectors'], 'FAT32 filesystem exceeds p1.')
            serial = struct.unpack_from('<I', bpb, 67)[0]
            fs_uuid = f'{serial >> 16:04x}-{serial & 0xffff:04x}'
            fs_type = 'vfat/FAT32'
            fs_label = bpb[71:82].decode('ascii').rstrip()
            require(fs_uuid == assembly['EFI_UUID'], 'FAT UUID differs from EFI_UUID.')
        else:
            sb = read_at(fd, start + 1024, 1024)
            require(struct.unpack_from('<H', sb, 56)[0] == 0xef53, f'p{number} has no ext filesystem magic.')
            fs_uuid = str(uuid.UUID(bytes=sb[104:120]))
            fs_type = 'ext4'
            fs_label = sb[120:136].split(b'\0', 1)[0].decode('ascii')
            blocks = struct.unpack_from('<I', sb, 4)[0]
            blocksize = 1024 << struct.unpack_from('<I', sb, 24)[0]
            require(blocksize == 4096 and blocks * blocksize <= part['size_sectors'] * SECTOR, f'p{number} filesystem exceeds its partition.')
            wanted = assembly['BOOT_UUID' if number == 2 else 'ROOT_UUID']
            require(fs_uuid == wanted, f'p{number} filesystem UUID differs from the assembly report.')
        require(fs_label == part['name'], f'p{number} filesystem label mismatch.')
        output.append({'partition': number, 'filesystem': fs_type, 'uuid': fs_uuid, 'label': fs_label})
    require(len({item['uuid'] for item in output}) == 3, 'Filesystem UUIDs must be unique.')
    return output


def embed(fd: int, loader: bytes, gpt: dict, image_guard: ImageUseGuard) -> tuple[bool, dict]:
    end = LOADER_OFFSET + len(loader)
    first_partition_offset = FIRST_PARTITION * SECTOR
    require(end < first_partition_offset, 'Loader exceeds the reserved pre-partition gap.')
    gap_start = gpt['primary_metadata_end']
    gap = read_at(fd, gap_start, first_partition_offset - gap_start)
    relative_start = LOADER_OFFSET - gap_start
    relative_end = end - gap_start
    identical = gap[relative_start:relative_end] == loader
    require(not any(gap[:relative_start]) and not any(gap[relative_end:]), 'Reserved gap contains unexpected nonzero data outside the reviewed loader.')
    require(identical or not any(gap), 'Reserved gap contains an existing or incomplete unrecognized loader; refusing to overwrite it.')
    boundaries = {
        'before_loader': (LOADER_OFFSET - 4096, 4096),
        'after_loader': (end, 4096),
        'p1_start': (first_partition_offset, 4096),
        'p2_start': (gpt['partitions'][1]['start_lba'] * SECTOR, 4096),
        'p3_start': (gpt['partitions'][2]['start_lba'] * SECTOR, 4096),
    }
    original = {name: read_at(fd, offset, length) for name, (offset, length) in boundaries.items()}
    if not identical:
        written = 0
        while written < len(loader):
            image_guard.check()
            count = os.pwrite(fd, loader[written:], LOADER_OFFSET + written)
            require(count > 0, 'Loader write made no progress.')
            written += count
        image_guard.check()
        os.fsync(fd)
        image_guard.check()
    require(read_at(fd, LOADER_OFFSET, len(loader)) == loader, 'Embedded loader differs byte-for-byte from the reviewed binary.')
    require(sha(read_at(fd, LOADER_OFFSET, len(loader))) == LOADER_SHA256, 'Embedded loader SHA256 mismatch.')
    for name, (offset, length) in boundaries.items():
        require(read_at(fd, offset, length) == original[name], f'Image boundary changed outside the loader: {name}.')
    fresh = parse_gpt(fd, os.fstat(fd).st_size)
    require(fresh['metadata_sha256'] == gpt['metadata_sha256'], 'GPT/MBR metadata changed during loader embedding.')
    return not identical, {name: {'offset': boundaries[name][0], 'bytes': len(value), 'sha256': sha(value)} for name, value in original.items()}


def main() -> None:
    require(len(sys.argv) == 2, f'Usage: embed-verify-loader.py {IMAGE.relative_to(BASE)}')
    requested = Path(sys.argv[1])
    require(not requested.is_symlink() and requested.resolve(strict=True) == IMAGE, 'Only the exact final build image path is accepted; symlinks/devices are forbidden.')
    require(not IMAGE.is_symlink() and IMAGE.is_file(), 'Target image must be a regular file.')
    loader = LOADER.read_bytes()
    require(len(loader) == 9524224 and sha(loader) == LOADER_SHA256, 'Reviewed loader binary size/hash mismatch.')
    subprocess.run([sys.executable, str(BASE / 'bootloader-build/verify-bootloader.py')], check=True, stdout=subprocess.DEVNULL)
    static = json.loads((BASE / 'bootloader-build/output/verification.json').read_text())
    require(static['artifacts']['u-boot-rockchip.bin']['sha256'] == LOADER_SHA256, 'Static loader verification receipt has a different hash.')
    assembly_bytes = ASSEMBLY.read_bytes()
    assembly = parse_assembly(assembly_bytes.decode())
    fd = os.open(IMAGE, os.O_RDWR | os.O_NOFOLLOW)
    try:
        image_stat = os.fstat(fd)
        require(stat.S_ISREG(image_stat.st_mode) and image_stat.st_size == IMAGE_BYTES, 'Target is not the expected regular 14 GiB image.')
        with ImageUseGuard(fd, IMAGE, BASE, write=True) as image_guard:
            gpt = parse_gpt(fd, image_stat.st_size)
            filesystems = validate_filesystems(fd, gpt, assembly)
            changed, boundary_hashes = embed(fd, loader, gpt, image_guard)
            validate_filesystems(fd, parse_gpt(fd, image_stat.st_size), assembly)
            report = {
                'verified_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'image': PUBLIC_IMAGE_NAME, 'image_bytes': image_stat.st_size,
                'target': 'PinePhone Pro internal eMMC disk image regular file',
                'loader': {'source': 'bootloader-build/output/u-boot-rockchip.bin', 'sha256': LOADER_SHA256,
                           'size_bytes': len(loader), 'offset_bytes': LOADER_OFFSET, 'end_bytes': LOADER_OFFSET + len(loader),
                           'byte_equality_verified': True, 'newly_embedded': changed},
                'reserved_gap_before_first_partition_bytes': FIRST_PARTITION * SECTOR,
                'gpt_first_usable_lba': FIRST_PARTITION,
                'gpt_crc_checks': 'primary/backup headers and both identical partition arrays passed',
                'gpt_and_mbr_metadata_sha256': gpt['metadata_sha256'],
                'gpt_disk_guid': gpt['primary']['disk_guid'], 'partitions': gpt['partitions'],
                'filesystems': filesystems, 'unchanged_boundaries': boundary_hashes,
                'assembly_report_sha256': sha(assembly_bytes), 'bootloader_static_verification': static,
                'qemu_target_use_guard_passed': True, 'exclusive_fcntl_lock_obtained': True,
                'image_use_guard': image_guard.receipt(),
                'outside_loader_write': False, 'device_write': False, 'spi_write': False,
                'physical_phone_boot_tested': False,
            }
            image_guard.publish_json(RECEIPT, report, replace=True)
    finally:
        os.close(fd)
    print(f'Loader {"embedded" if changed else "already identical"}; GPT, UUIDs and boundaries verified. Receipt: {RECEIPT.name}')


if __name__ == '__main__':
    try:
        main()
    except (VerificationError, ImageGuardError, OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(f'Loader embedding aborted: {error}') from error
