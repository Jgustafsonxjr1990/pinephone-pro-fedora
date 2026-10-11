#!/usr/bin/env python3
"""Verify ARM64 image, PPP device tree, required configuration and matching modules."""
import hashlib
import json
import os
import re
import struct
import subprocess
from pathlib import Path

base = Path(__file__).resolve().parent
out = base / 'output'
release = (out / 'kernelrelease').read_text().strip()
assert release == '7.2.9-jon-ppp', release
image = out / f'Image-{release}'
with image.open('rb') as inp:
    header = inp.read(64)
assert header[56:60] == b'ARM\x64', header[56:60]
text_offset, image_size, flags = struct.unpack('<QQQ', header[8:32])
config = (out / f'config-{release}').read_text()
required = [
    'CONFIG_ARCH_ROCKCHIP=y', 'CONFIG_SECURITY=y', 'CONFIG_SECURITY_SELINUX=y',
    'CONFIG_SECURITY_NETWORK=y', 'CONFIG_AUDIT=y', 'CONFIG_AUDITSYSCALL=y',
    'CONFIG_EXT4_FS=y', 'CONFIG_EXT4_FS_SECURITY=y', 'CONFIG_BTRFS_FS=y',
    'CONFIG_VIRTIO_BLK=y', 'CONFIG_VIRTIO_NET=y', 'CONFIG_9P_FS=y',
    'CONFIG_MMC_DW_ROCKCHIP=y', 'CONFIG_MMC_SDHCI_OF_ARASAN=y',
    'CONFIG_DRM_ROCKCHIP=y', 'CONFIG_DRM_PANFROST=y',
    'CONFIG_DRM_PANEL_HIMAX_HX8394=y', 'CONFIG_CHARGER_RK818=y',
    'CONFIG_REGULATOR_RK808=y', 'CONFIG_TOUCHSCREEN_GOODIX=m',
    'CONFIG_BRCMFMAC=m', 'CONFIG_BRCMFMAC_SDIO=y',
    'CONFIG_BT_HCIUART_BCM=y', 'CONFIG_SND_SOC_RT5640=m',
    'CONFIG_SND_SIMPLE_CARD=m', 'CONFIG_USB_NET_QMI_WWAN=m',
    'CONFIG_USB_SERIAL_OPTION=m', 'CONFIG_USB_DWC3_DUAL_ROLE=y',
]
for line in required:
    assert line in config.splitlines(), f'Required configuration missing: {line}'
assert 'selinux' in re.search(r'^CONFIG_LSM="(.*)"$', config, re.M).group(1).split(',')
dtb = out / 'rk3399-pinephone-pro.dtb'
assert struct.unpack('>I', dtb.read_bytes()[:4])[0] == 0xd00dfeed
dts = subprocess.check_output([str(base / 'linux-7.2.9/scripts/dtc/dtc'), '-I', 'dtb', '-O', 'dts', str(dtb)], stderr=subprocess.DEVNULL, text=True)
assert 'pine64,pinephone-pro' in dts and 'rockchip,rk3399' in dts
assert 'quectel,eg25' not in dts
assert 'ring-indicator' in dts and 'wakeup-source' in dts
for node in ('regulator-vcc-4g', 'regulator-vcc-4g-5v'):
    block = re.search(r'\b' + node + r'\s*\{(.*?)\n\t\};', dts, re.S)
    assert block and 'regulator-always-on' in block.group(1), f'{node} not always-on'
modules_dir = out / 'modules-root/lib/modules' / release
modules = sorted(modules_dir.rglob('*.ko'))
assert modules
for module in modules:
    data = module.read_bytes()
    assert struct.unpack('<H', data[18:20])[0] == 183, f'Non-AArch64 module: {module}'
    vermagic = re.search(rb'\x00vermagic=([^\x00]+)\x00', data)
    assert vermagic and vermagic.group(1).startswith((release + ' ').encode()), f'Wrong module release: {module}'
    assert data.endswith(b'~Module signature appended~\n'), f'Module signature missing: {module}'
for index in ('modules.dep', 'modules.dep.bin', 'modules.alias', 'modules.alias.bin'):
    assert (modules_dir / index).stat().st_size > 0, f'Missing module index: {index}'
checks = {'kernel_release': release, 'architecture': 'AArch64', 'arm64_header': {'text_offset': text_offset, 'image_size': image_size, 'flags': flags}, 'module_count': len(modules), 'selinux_enabled': True, 'ext4_builtin': True, 'btrfs_builtin': True, 'eg25_manager_gpio_integration': True, 'hardware_tested': False, 'artifacts': {}}
for path in (image, dtb, out / f'config-{release}', out / f'System.map-{release}'):
    checks['artifacts'][path.name] = {'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
(out / 'verification.json').write_text(json.dumps(checks, indent=2) + '\n')
print(json.dumps(checks, indent=2))
