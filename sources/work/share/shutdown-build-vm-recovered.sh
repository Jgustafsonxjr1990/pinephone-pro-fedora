#!/bin/bash
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export LC_ALL=C
[[ $EUID == 0 && $(uname -m) == aarch64 ]]
[[ $(readlink -f /proc/1/exe) == /usr/bin/bash ]]
[[ $(findmnt -n -o UUID --target /) == 6741cdec-fe58-4214-9fa9-3e8eaa52f476 ]]
[[ -z $(awk '/deleted/' /proc/1/maps) ]]
[[ ! -e /proc/138/maps ]]
for part in /dev/vdb1 /dev/vdb2 /dev/vdb3; do [[ -z $(findmnt -rn -S "$part") ]]; done
for path in /boot/efi /boot /home /var; do ! mountpoint -q "$path"; done
sync
mount -o remount,ro /
[[ ,$(findmnt -n -o OPTIONS --target /), == *,ro,* ]]
printf 'BUILD_SOURCE_OLD_MAPPINGS_RELEASED\n'
printf 'FEDORA_BUILD_FILESYSTEMS_FLUSHED\n'
exec poweroff -f
