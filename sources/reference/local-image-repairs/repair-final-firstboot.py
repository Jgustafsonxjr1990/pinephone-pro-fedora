#!/usr/bin/env python3
"""Repair the stopped regular image's first-start policy, preserving evidence."""
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

WORK = Path(__file__).resolve().parent
BASE = WORK / 'phone-root/var/tmp/fedora-ppp-build-20261011'
IMAGE = BASE / 'output/Fedora-44-Plasma-Mobile-PinePhone-Pro-eMMC-20261010.img.crdownload'
MOUNT = WORK / 'image-inspect'
BACKUP = WORK / 'firstboot-config-before-repair'
sys.path.insert(0, str(BASE / 'work'))
from image_use_guard import project_qemu_inventory

def run(*args):
    return subprocess.run(args, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT).stdout

assert os.geteuid() == 0
assert IMAGE.is_file() and not IMAGE.is_symlink() and IMAGE.stat().st_size == 15032385536
assert not run('losetup', '-j', str(IMAGE)).strip()
assert subprocess.run(['mountpoint', '-q', str(MOUNT)]).returncode == 32
inventory = project_qemu_inventory(BASE, IMAGE)
BACKUP.mkdir(mode=0o700, exist_ok=False)
fd = os.open(IMAGE, os.O_RDWR | os.O_NOFOLLOW)
fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
loop = None
mounted = False
try:
    loop = run('losetup', '--find', '--show', '--offset', str(5283840*512), '--sizelimit', str(24074240*512), str(IMAGE)).strip()
    assert run('blkid', '-s', 'UUID', '-o', 'value', loop).strip() == '1280988c-abb7-469f-9e79-aa1e683acaac'
    before_fsck = run('e2fsck', '-f', '-n', loop)
    run('mount', '-o', 'rw,nosuid,nodev', loop, str(MOUNT)); mounted = True
    mid = MOUNT / 'etc/machine-id'
    repart = MOUNT / 'etc/repart.d/50-root.conf'
    assert mid.read_bytes() == b'uninitialized\n'
    assert repart.read_bytes() == b'[Partition]\nType=root\n'
    assert not (MOUNT / 'usr/lib/repart.d').exists()
    assert 'ConditionFirstBoot' not in (MOUNT / 'usr/lib/systemd/system/plasma-setup.service').read_text()
    assert not (MOUNT / 'etc/plasma-setup-done').exists()
    assert (MOUNT / 'etc/systemd/system/multi-user.target.wants/pinephone-pro-grow-root.service').is_symlink()
    for source, name in ((mid, 'machine-id'), (repart, '50-root.conf')):
        shutil.copy2(source, BACKUP / name)
    # Empty still generates a unique ID; unlike "uninitialized", it preserves
    # explicit service selections and avoids the generic console setup wizard.
    with mid.open('wb') as stream:
        stream.flush(); os.fsync(stream.fileno())
    assert mid.stat().st_mode & 0o777 == 0o444
    # Fedora's architecture-specific Type=root cannot match this image's
    # generic ext4 GPT type. The device-checked PPP service owns root growth.
    repart.unlink()
    run('sync', '-f', str(MOUNT))
    run('umount', str(MOUNT)); mounted = False
    after_fsck = run('e2fsck', '-f', '-n', loop)
    run('mount', '-o', 'ro,noload,nosuid,nodev', loop, str(MOUNT)); mounted = True
    assert mid.read_bytes() == b'' and not repart.exists()
    for unit in ('eg25-manager.service', 'pinephone-pro-grow-root.service', 'plasma-setup.service'):
        assert (MOUNT / 'etc/systemd/system/multi-user.target.wants' / unit).is_symlink(), unit
    assert os.readlink(MOUNT / 'etc/systemd/system/default.target') == '/usr/lib/systemd/system/graphical.target'
    run('umount', str(MOUNT)); mounted = False
    run('losetup', '-d', loop); loop = None
    os.fsync(fd)
    inventory_after = project_qemu_inventory(BASE, IMAGE)
    for item in (inventory, inventory_after):
        item['scope'] = 'Visible process inventory; repair used a POSIX whole-file write lock and loop mount, without a file lease'

    receipt = {
        'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'status': 'offline_firstboot_policy_repaired_and_ext4_checked',
        'image_bytes': IMAGE.stat().st_size,
        'changes': {'etc/machine-id': 'empty; retains mode and SELinux label',
                    'etc/repart.d/50-root.conf': 'removed inherited architecture-specific root growth config'},
        'plasma_setup_and_phone_services_preserved': True,
        'before_ext4_check': before_fsck, 'after_ext4_check': after_fsck,
        'project_qemu_before': inventory, 'project_qemu_after': inventory_after,
        'backup': [{'file': p.name, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(BACKUP.iterdir())],
        'physical_phone_changed': False,
    }
    with (WORK / 'firstboot-image-repair.json').open('x') as stream:
        json.dump(receipt, stream, indent=2); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    print('OFFLINE_FIRSTBOOT_REPAIR_VERIFIED', flush=True)
finally:
    if mounted:
        run('umount', str(MOUNT))
    if loop:
        run('losetup', '-d', loop)
    os.close(fd)
