#!/usr/bin/env python3
"""Reconstruct the exact build tree from the authenticated upstream source and pinned patches."""
import hashlib
import json
import subprocess
import tarfile
from pathlib import Path

base = Path(__file__).resolve().parent
manifest = json.loads((base / 'source-manifest.json').read_text())
archive = base / 'sources' / f"linux-{manifest['version']}.tar.xz"
assert hashlib.sha256(archive.read_bytes()).hexdigest() == manifest['source_sha256']
source = base / f"linux-{manifest['version']}"
if source.exists():
    raise SystemExit(f'Refusing to overwrite existing source tree: {source}')
with tarfile.open(archive, 'r:xz') as tar:
    tar.extractall(base, filter='data')
skipped = 'megi_patches/0060-arm64-dts-rockchip-rk3399-pinephone-pro-Disable-inte.patch'
for item in manifest['patches_and_config']:
    path = base / 'sources' / item['path']
    assert hashlib.sha512(path.read_bytes()).hexdigest() == item['sha512']
    if path.suffix != '.patch':
        continue
    if item['path'] == skipped:
        dts = (source / 'arch/arm64/boot/dts/rockchip/rk3399-pinephone-pro.dts').read_text()
        assert 'brcmf: wifi@1' not in dts and 'interrupt-names = "host-wake"' not in dts
        print(f'Already absent upstream: {skipped}')
        continue
    with path.open('rb') as inp:
        subprocess.run(['patch', '--batch', '--forward', '--fuzz=0', '-p1'], cwd=source, stdin=inp, check=True)
local_patch = base / 'sources/0091-fedora-eg25-manager-dts.patch'
assert hashlib.sha256(local_patch.read_bytes()).hexdigest() == manifest['additional_patches'][0]['sha256']
with local_patch.open('rb') as inp:
    subprocess.run(['patch', '--batch', '--forward', '--fuzz=0', '-p1'], cwd=source, stdin=inp, check=True)
print(f'Prepared {source}')
