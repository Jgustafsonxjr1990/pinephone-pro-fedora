#!/usr/bin/env python3
"""Correct numeric findmnt output parsing in the stopped regular phone image."""
import datetime, fcntl, hashlib, json, os, shutil, subprocess, sys
from pathlib import Path
W = Path(__file__).resolve().parent
B = W / 'phone-root/var/tmp/fedora-ppp-build-20261011'
I = B / 'output/Fedora-44-Plasma-Mobile-PinePhone-Pro-eMMC-20261010.img.crdownload'
M = W / 'image-inspect'
sys.path.insert(0, str(B / 'work'))
from image_use_guard import project_qemu_inventory
def run(*args):
    return subprocess.check_output(args, stderr=subprocess.STDOUT, text=True)
assert os.geteuid() == 0 and I.is_file() and not I.is_symlink() and I.stat().st_size == 15032385536
assert not run('losetup', '-j', str(I)).strip()
assert subprocess.run(['mountpoint', '-q', str(M)]).returncode == 32
project_qemu_inventory(B, I)
fd = os.open(I, os.O_RDWR | os.O_NOFOLLOW)
fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
loop = None; mounted = False
try:
    loop = run('losetup', '--find', '--show', '--offset', str(5283840*512), '--sizelimit', str(24074240*512), str(I)).strip()
    assert run('blkid', '-s', 'UUID', '-o', 'value', loop).strip() == '1280988c-abb7-469f-9e79-aa1e683acaac'
    run('mount', '-o', 'rw,nosuid,nodev', loop, str(M)); mounted = True
    p = M / 'usr/sbin/pinephone-pro-grow-root'; old = p.read_bytes()
    assert old.count(b'findmnt -n -o MAJ:MIN') == 1
    new = old.replace(b'findmnt -n -o MAJ:MIN', b'findmnt -rn -o MAJ:MIN')
    assert new == (B / 'work/share/image-assembly/pinephone-pro-grow-root').read_bytes()
    backup = W / 'firstboot-config-before-repair/pinephone-pro-grow-root'
    assert not backup.exists(); shutil.copy2(p, backup)
    with p.open('wb') as out:
        out.write(new); out.flush(); os.fsync(out.fileno())
    assert p.stat().st_mode & 0o777 == 0o755
    assert (M / 'etc/machine-id').read_bytes() == b''
    run('sync', '-f', str(M)); run('umount', str(M)); mounted = False
    check = run('e2fsck', '-f', '-n', loop)
    run('mount', '-o', 'ro,noload,nosuid,nodev', loop, str(M)); mounted = True
    assert p.read_bytes() == new
    run('umount', str(M)); mounted = False
    run('losetup', '-d', loop); loop = None
    os.fsync(fd); project_qemu_inventory(B, I)
    report = {'status': 'numeric_device_mapping_repaired_and_ext4_checked',
              'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'change': 'Use raw findmnt output for MAJ:MIN so human column padding cannot corrupt /dev/block paths',
              'before_sha256': hashlib.sha256(old).hexdigest(), 'after_sha256': hashlib.sha256(new).hexdigest(),
              'e2fsck': check, 'physical_phone_changed': False}
    with (W / 'grow-device-image-repair.json').open('x') as out:
        json.dump(report, out, indent=2); out.write('\n'); out.flush(); os.fsync(out.fileno())
    print('GROW_DEVICE_MAPPING_REPAIR_VERIFIED')
finally:
    if mounted: run('umount', str(M))
    if loop: run('losetup', '-d', loop)
    os.close(fd)
