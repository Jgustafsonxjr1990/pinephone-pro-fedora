#!/usr/bin/env python3
"""Validate the built eMMC/SD loader and its FIT payloads without device access."""
from pathlib import Path
import hashlib
import json
import struct
import sys

BASE = Path(__file__).resolve().parent
OUT = BASE / 'output'
sys.path.insert(0, str(BASE / 'u-boot/scripts/dtc/pylibfdt'))
import libfdt


def rc4(data, key):
    state = list(range(256))
    j = 0
    for i in range(256):
        j = (j + state[i] + key[i % len(key)]) % 256
        state[i], state[j] = state[j], state[i]
    i = j = 0
    result = bytearray()
    for value in data:
        i = (i + 1) % 256
        j = (j + state[i]) % 256
        state[i], state[j] = state[j], state[i]
        result.append(value ^ state[(state[i] + state[j]) % 256])
    return bytes(result)


def sha256(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def prop(fdt, node, name):
    return bytes(fdt.getprop(node, name))


def u32(fdt, node, name):
    return struct.unpack('>I', prop(fdt, node, name))[0]


config = (OUT / 'u-boot.config').read_text()
for required in (
    'CONFIG_TARGET_PINEPHONE_PRO_RK3399=y',
    'CONFIG_TPL=y',
    'CONFIG_RAM_ROCKCHIP_LPDDR4=y',
    'CONFIG_ENV_IS_NOWHERE=y',
    'CONFIG_EFI_LOADER=y',
    'CONFIG_BOOTMETH_EXTLINUX=y',
    'CONFIG_CMD_BOOTI=y',
    'CONFIG_MMC_DW_ROCKCHIP=y',
    'CONFIG_MMC_SDHCI_ROCKCHIP=y',
    'CONFIG_SYS_MMCSD_RAW_MODE_U_BOOT_SECTOR=0x4000',
    'CONFIG_BOOTCOMMAND="bootmeth order extlinux && bootflow scan -lb"',
):
    assert required in config.splitlines(), required
assert '# CONFIG_ENV_IS_IN_SPI_FLASH is not set' in config
assert '# CONFIG_ROCKCHIP_SPI_IMAGE is not set' in config

loader = (OUT / 'u-boot-rockchip.bin').read_bytes()
idb = (OUT / 'idbloader.img').read_bytes()
fit = (OUT / 'u-boot.itb').read_bytes()
idb_offset = 64 * 512
fit_absolute_offset = 16384 * 512
fit_relative_offset = fit_absolute_offset - idb_offset
assert loader[:len(idb)] == idb
assert loader[fit_relative_offset:fit_relative_offset + len(fit)] == fit
assert len(loader) + idb_offset < 32 * 1024 * 1024
assert all(value == 0xff for value in loader[len(idb):fit_relative_offset])

# Decode the BootROM ID-block header using the public U-Boot Rockchip key.
key = bytes([124, 78, 3, 4, 85, 5, 9, 7, 45, 44, 123, 56, 23, 13, 23, 17])
header = rc4(idb[:512], key)
magic = struct.unpack_from('<I', header, 0)[0]
disable_rc4 = struct.unpack_from('<I', header, 8)[0]
init_offset = struct.unpack_from('<H', header, 12)[0]
init_size, init_boot_size = struct.unpack_from('<HH', header, 506)
assert magic == 0x0ff0aa55
assert disable_rc4 == 1
assert init_offset == 4
assert idb[init_offset * 512:init_offset * 512 + 4] == b'RK33'
assert (init_offset + init_boot_size) * 512 == len(idb)
assert init_boot_size > init_size > 0

fdt = libfdt.Fdt(fit)
images = fdt.path_offset('/images')
node = fdt.first_subnode(images)
fit_payloads = []
while node >= 0:
    name = fdt.get_name(node)
    size = u32(fdt, node, 'data-size')
    offset = fdt.totalsize() + u32(fdt, node, 'data-offset')
    data = fit[offset:offset + size]
    assert len(data) == size, name
    expected = prop(fdt, fdt.subnode_offset(node, 'hash'), 'value')
    assert expected == hashlib.sha256(data).digest(), name
    fit_payloads.append({'name': name, 'size': size, 'sha256': expected.hex()})
    if name == 'fdt-1':
        board_fdt = libfdt.Fdt(data)
        compatible = prop(board_fdt, board_fdt.path_offset('/'), 'compatible').split(b'\0')
        assert b'pine64,pinephone-pro' in compatible
        assert b'rockchip,rk3399' in compatible
    node = fdt.next_subnode(node, quiet=(libfdt.NOTFOUND,))
configuration = fdt.path_offset('/configurations/config-1')
assert prop(fdt, configuration, 'firmware') == b'atf-1\0'
assert b'u-boot' in prop(fdt, configuration, 'loadables').split(b'\0')

binary = (OUT / 'u-boot.bin').read_bytes()
environment = {}
for name, expected in (
    ('kernel_addr_r', '0x02000000'),
    ('fdt_addr_r', '0x12000000'),
    ('ramdisk_addr_r', '0x12180000'),
    ('fdtfile', 'rockchip/rk3399-pinephone-pro.dtb'),
    ('bootcmd', 'bootmeth order extlinux && bootflow scan -lb'),
):
    assert (name + '=' + expected + '\0').encode() in binary
    environment[name] = expected

report = {
    'idblock': {
        'medium': 'eMMC user area or SD; not eMMC boot partitions or SPI',
        'disk_offset_bytes': idb_offset,
        'bootrom_magic': hex(magic),
        'soc_payload_magic': 'RK33',
        'init_size_bytes': init_size * 512,
        'boot_size_bytes': (init_boot_size - init_size) * 512,
    },
    'fit': {'disk_offset_bytes': fit_absolute_offset, 'payloads': fit_payloads},
    'image_size_bytes': len(loader),
    'image_end_if_embedded_bytes': idb_offset + len(loader),
    'fits_before_partition_1_at_32MiB': True,
    'environment': environment,
    'spi_environment_storage': False,
    'spi_image_produced': False,
    'optional_optee_included': False,
    'hardware_boot_tested': False,
    'artifacts': {path.name: {'bytes': path.stat().st_size, 'sha256': sha256(path)}
                  for path in sorted(OUT.iterdir()) if path.is_file() and path.suffix != '.json'},
}
(OUT / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({key: report[key] for key in ('idblock', 'image_size_bytes', 'image_end_if_embedded_bytes', 'environment')}, indent=2))
