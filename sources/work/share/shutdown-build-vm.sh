#!/bin/bash
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export LC_ALL=C
touch /build/STOP_FEDORA_BUILD_MONITOR
[[ -z $(findmnt -rn -S /dev/vdb1) && -z $(findmnt -rn -S /dev/vdb2) && -z $(findmnt -rn -S /dev/vdb3) ]]
sync
umount /boot/efi
umount /boot
umount /home
umount /var
sync
mount -o remount,ro /
printf '%s\n' FEDORA_BUILD_FILESYSTEMS_FLUSHED
poweroff -f
