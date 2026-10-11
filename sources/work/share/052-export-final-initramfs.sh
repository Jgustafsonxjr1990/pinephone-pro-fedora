#!/usr/bin/bash
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C
[[ $EUID == 0 && $(uname -m) == aarch64 && $(uname -r) == 7.2.9-jon-ppp ]]
[[ $(findmnt -n -o UUID --target /) == 6741cdec-fe58-4214-9fa9-3e8eaa52f476 ]]
[[ $(findmnt -n -o FSTYPE --target /build) == 9p ]]
[[ $(blockdev --getsize64 /dev/vdb) == 15032385536 ]]
report=/build/fedora-ppp-image-assembly.txt
boot_uuid=$(sed -n 's/^BOOT_UUID=//p' "$report")
[[ -n $boot_uuid && $(blkid -s UUID -o value /dev/vdb2) == "$boot_uuid" ]]
[[ $(blkid -s TYPE -o value /dev/vdb2) == ext4 ]]
! findmnt -rn -S /dev/vdb2
target=$(mktemp -d /run/ppp-final-boot.XXXXXX)
trap 'mountpoint -q "$target" && umount "$target"; rmdir "$target"' EXIT
mount -t ext4 -o ro,noload /dev/vdb2 "$target"
source="$target/initramfs-7.2.9-jon-ppp.img"
destination=/build/ppp-final-initramfs.img
[[ -s $source && ! -L $source && ! -e $destination && ! -L $destination ]]
python3 - "$source" "$destination" <<'PY'
import hashlib, os, pathlib, sys
source, destination = map(pathlib.Path, sys.argv[1:])
data = source.read_bytes()
assert 0 < len(data) <= 256 * 1024**2
with destination.open('xb') as stream:
    stream.write(data); stream.flush(); os.fsync(stream.fileno())
assert hashlib.sha256(destination.read_bytes()).digest() == hashlib.sha256(data).digest()
print('Final initramfs SHA256:', hashlib.sha256(data).hexdigest())
PY
/usr/sbin/pinephone-pro-initramfs-verify "$destination" --audit-json /build/fedora-final-initramfs-portability.json
umount "$target"
rmdir "$target"
trap - EXIT
printf 'FEDORA_PPP_FINAL_INITRAMFS_EXPORTED\n'
