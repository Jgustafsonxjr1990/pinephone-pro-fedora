#!/usr/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# Export the actually installed source-root dracut archive for offline VM checks.
set -euo pipefail
[[ $EUID == 0 && $(uname -m) == aarch64 && $(uname -r) == 7.2.9-jon-ppp ]]
[[ $(findmnt -n -o UUID --target /) == 6741cdec-fe58-4214-9fa9-3e8eaa52f476 ]]
[[ $(findmnt -n -o FSTYPE --target /build) == 9p ]]
python3 - <<'PY'
from pathlib import Path
import hashlib, json, os, stat
source = Path('/boot/initramfs-7.2.9-jon-ppp.img')
output = Path('/build/fedora-source-initramfs.img')
kernel = json.loads(Path('/build/fedora-kernel-install-report.json').read_text())
audit = json.loads(Path('/build/fedora-source-initramfs-portability.json').read_text())
state = json.loads(Path('/build/fresh-package-state.json').read_text())
assert kernel['status'] == 'kernel_release3_built_installed_verified'
assert state['status'] == 'fresh_phone_packages_verified' and audit['status'] == 'passed'
assert source.resolve(strict=True) == source and not source.is_symlink()
fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
with os.fdopen(fd, 'rb') as stream:
    before = os.fstat(stream.fileno())
    assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= 256 * 1024**2
    data = stream.read(256 * 1024**2 + 1)
    fp = lambda x: (x.st_dev,x.st_ino,x.st_size,x.st_mtime_ns,x.st_ctime_ns)
    assert fp(before) == fp(os.fstat(stream.fileno())) == fp(source.lstat())
digest = hashlib.sha256(data).hexdigest()
assert len(data) == before.st_size == kernel['initramfs_size_bytes'] == audit['archive_bytes'] == state['source_initramfs']['size_bytes']
assert digest == kernel['initramfs_sha256'] == audit['archive_sha256'] == state['source_initramfs']['sha256']
assert not output.exists() and not output.is_symlink()
with output.open('xb') as stream:
    stream.write(data); stream.flush(); os.fsync(stream.fileno())
with output.open('rb') as stream:
    assert hashlib.file_digest(stream, 'sha256').hexdigest() == digest
assert output.stat().st_size == len(data)
print('FRESH_FEDORA_SOURCE_INITRAMFS_EXPORTED sha256=' + digest + ' bytes=' + str(len(data)))
PY
