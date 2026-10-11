#!/usr/bin/bash
# Isolated build VM only. This script never formats a disk or changes accounts.
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export LC_ALL=C
umask 022
root_uuid=6741cdec-fe58-4214-9fa9-3e8eaa52f476
kernel_release=7.2.9-jon-ppp
fail() { printf '\nPPP_BUILD_BOOTSTRAP_FAILED %s\n' "$*" >&2; exit 1; }
[[ $EUID == 0 && $(uname -m) == aarch64 && $(uname -r) == "$kernel_release" ]] || fail wrong-guest
[[ $$ == 1 ]] || fail bootstrap-must-be-pid1
for command in mount mountpoint findmnt blkid insmod sha256sum ip stty udevadm hwclock date; do
  command -v "$command" >/dev/null || fail "missing-$command"
done
session=
for argument in $(cat /proc/cmdline); do
  case $argument in pppbuild.session=*) session=${argument#pppbuild.session=};; esac
done
[[ $session =~ ^[0-9a-f]{32}$ ]] || fail missing-session-token
[[ $(findmnt -n -o FSTYPE --target /) == btrfs && $(findmnt -n -o FSROOT --target /) == /root ]] || fail wrong-root-mount
[[ $(blkid -s UUID -o value /dev/vda3) == "$root_uuid" ]] || fail wrong-source-uuid
[[ $(readlink -f /sys/block/vda/device/driver) == /sys/bus/virtio/drivers/virtio_blk ]] || fail wrong-source-driver
[[ $(findmnt -n -o FSTYPE --target /run) == tmpfs && $(findmnt -n -o FSTYPE --target /build) == 9p ]] || fail missing-runtime-mounts
[[ $(findmnt -n -o SOURCE --target /build) == build ]] || fail wrong-share

for subvolume in var home; do
  mkdir -p "/$subvolume"
  if ! mountpoint -q "/$subvolume"; then
    mount -t btrfs -o "subvol=$subvolume,rw" /dev/vda3 "/$subvolume"
  fi
  [[ $(findmnt -n -o FSTYPE --target "/$subvolume") == btrfs &&
     $(findmnt -n -o FSROOT --target "/$subvolume") == "/$subvolume" &&
     $(findmnt -n -o UUID --target "/$subvolume") == "$root_uuid" ]] || fail "wrong-$subvolume-mount"
done
mkdir -p /boot
mountpoint -q /boot || mount -t ext4 -o rw /dev/vda2 /boot
[[ $(findmnt -n -o FSTYPE --target /boot) == ext4 && $(findmnt -n -o SOURCE --target /boot) == /dev/vda2 ]] || fail wrong-boot-mount

# The default VFAT codepage is the only storage prerequisite not built in.
if [[ ! -d /sys/module/nls_cp437 ]]; then
  module=/build/build-kernel-modules/lib/modules/$kernel_release/kernel/fs/nls/nls_cp437.ko
  [[ -f $module && ! -L $module ]] || fail missing-verified-cp437-module
  [[ $(sha256sum "$module" | awk '{print $1}') == 6094b8f721581cd1debcebfc0ad9cf0ae4601932fd51c6ab1aae37678f05a6b6 ]] || fail wrong-cp437-module-hash
  insmod "$module"
fi
mkdir -p /boot/efi
mountpoint -q /boot/efi || mount -t vfat -o rw,codepage=437,iocharset=ascii /dev/vda1 /boot/efi
[[ $(findmnt -n -o FSTYPE --target /boot/efi) == vfat && $(findmnt -n -o SOURCE --target /boot/efi) == /dev/vda1 ]] || fail wrong-efi-mount
if [[ ! -d /sys/module/rtc_pl031 ]]; then
  module=/build/build-kernel-modules/lib/modules/$kernel_release/kernel/drivers/rtc/rtc-pl031.ko
  [[ -f $module && ! -L $module ]] || fail missing-verified-pl031-module
  [[ $(sha256sum "$module" | awk '{print $1}') == f70a8b5f682598254f0bd00e93bb673fcc58bb9ec9f018e892c9045c97538d79 ]] || fail wrong-pl031-module-hash
  insmod "$module"
fi
hwclock --hctosys --utc
[[ $(date +%Y) -ge 2026 ]] || fail invalid-guest-time
mkdir -p /dev/pts /dev/shm /run/udev /tmp
mountpoint -q /dev/pts || mount -t devpts -o gid=5,mode=0620 devpts /dev/pts
mountpoint -q /dev/shm || mount -t tmpfs -o mode=1777,nosuid,nodev tmpfs /dev/shm
[[ -x /usr/lib/systemd/systemd-udevd ]] || fail missing-udevd
/usr/lib/systemd/systemd-udevd --daemon
udevadm trigger --type=subsystems --action=add
udevadm trigger --type=devices --action=add
udevadm settle --timeout=60

# QEMU slirp/MMIO networking; proxy values, if required, are set by the owner
# later in the live shell and never serialized by this bootstrap.
interfaces=()
for interface in /sys/class/net/*; do
  [[ ${interface##*/} == lo ]] || interfaces+=("${interface##*/}")
done
[[ ${#interfaces[@]} == 1 ]] || fail unexpected-network-interfaces
ip link set lo up
ip link set "${interfaces[0]}" up
ip addr replace 10.0.2.15/24 dev "${interfaces[0]}"
ip route replace default via 10.0.2.2 dev "${interfaces[0]}"
# /run holds this resolver file even if /etc/resolv.conf is a symlink.
resolver=$(readlink -m /etc/resolv.conf)
case $resolver in /etc/resolv.conf|/run/*) ;; *) fail unexpected-resolver-target;; esac
mkdir -p "${resolver%/*}"
printf 'nameserver 10.0.2.3\n' > "$resolver"
printf '\nPPP_BUILD_SOURCE_MOUNTS_VERIFIED root=%s fs=btrfs subvol=/root boot=ext4 efi=vfat run=tmpfs share=9p\n' "$root_uuid"
stty -echo
export PS1='PPP_BUILD_PROMPT> '
printf '\nPPP_BOOT_READY SESSION=%s\n' "$session"
exec /usr/bin/bash --noprofile --norc -i
