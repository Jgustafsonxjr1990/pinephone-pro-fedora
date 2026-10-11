#!/usr/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# TEST ONLY: run in QEMU on a disposable 16 GiB qcow2 overlay backed by the
# finished 14 GiB image. Never include this script in the shipped filesystem.
# The host launch must prove overlay provenance; the guest sees only VirtIO.
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export LC_ALL=C
umask 077
fail() { printf 'Virtual image growth test: %s\n' "$*" >&2; exit 1; }
[[ $EUID -eq 0 && $(uname -m) == aarch64 ]] || fail 'requires root in the isolated ARM64 VM.'
[[ $# -eq 2 && ( $1 == grow-mounted-root || $1 == check-unmounted-filesystems ) && ( $2 == /dev/vda || $2 == /dev/vdb ) ]] || fail 'usage: test-virtual-root-growth.sh {grow-mounted-root|check-unmounted-filesystems} {/dev/vda|/dev/vdb}'
mode=$1
disk=$2
disk_name=${disk##*/}
if [[ $mode == grow-mounted-root ]]; then
  [[ $disk == "${PPP_VERIFY_DISK:?fresh serial-checked root disk is required}" &&
     $(cat "/sys/block/$disk_name/serial") == PPP_VERIFY_ROOT &&
     $(blockdev --getro "$disk") == 0 ]] || fail 'online disk serial, mapping or write mode differs.'
else
  [[ $disk == "${PPP_GROWTH_DEVICE:?fresh serial-checked growth disk is required}" &&
     $(cat "/sys/block/$disk_name/serial") == PPP_GROWTH_TARGET &&
     $(blockdev --getro "$disk") == 1 ]] || fail 'offline disk serial, mapping or readonly mode differs.'
fi
report=/build/fedora-ppp-growth-test.txt
[[ -r /proc/device-tree/compatible ]] || fail 'QEMU device tree is missing.'
tr '\0' '\n' < /proc/device-tree/compatible | grep -Fxq linux,dummy-virt || fail 'device tree is not QEMU virt.'
mountpoint -q /build || fail 'the external test/report share is not mounted.'
[[ -f /build/ALLOW_DISPOSABLE_IMAGE_GROWTH_TEST && $(cat /build/ALLOW_DISPOSABLE_IMAGE_GROWTH_TEST) == QEMU_OVERLAY_14GiB_TO_16GiB ]] || fail 'explicit host test marker is missing.'
[[ -b $disk && $(readlink -f "/sys/block/$disk_name/device/driver") == /sys/bus/virtio/drivers/virtio_blk ]] || fail 'test disk is not VirtIO.'
[[ $(blockdev --getsize64 "$disk") == 17179869184 && $(blockdev --getss "$disk") == 512 ]] || fail 'test disk must be exactly 16 GiB with 512-byte sectors.'
[[ $(blkid -s PTTYPE -o value "$disk") == gpt ]] || fail 'test disk is not GPT.'
[[ $(lsblk -rn -o TYPE "$disk" | awk '$1 == "part" {n++} END {print n+0}') == 3 ]] || fail 'test disk must have three partitions.'
[[ $(sfdisk --part-label "$disk" 1) == FEDORA_EFI && $(sfdisk --part-label "$disk" 2) == FEDORA_BOOT && $(sfdisk --part-label "$disk" 3) == FEDORA_ROOT ]] || fail 'test image partition labels differ.'
[[ $(cat "/sys/class/block/${disk_name}1/start") == 65536 && $(cat "/sys/class/block/${disk_name}1/size") == 1024000 ]] || fail 'FAT partition geometry differs.'
[[ $(cat "/sys/class/block/${disk_name}2/start") == 1089536 && $(cat "/sys/class/block/${disk_name}2/size") == 4194304 ]] || fail 'boot partition geometry differs.'
[[ $(cat "/sys/class/block/${disk_name}3/start") == 5283840 ]] || fail 'root partition start differs.'
[[ $(sfdisk --part-type "$disk" 3 | tr '[:upper:]' '[:lower:]') == 0fc63daf-8483-4772-8e79-3d69d8477de4 ]] || fail 'root partition type differs.'
for command in growpart sgdisk resize2fs partx flock tune2fs e2fsck fsck.fat; do command -v "$command" >/dev/null || fail "missing test command: $command"; done

boot_partition_metadata() {
  sfdisk --dump "$disk" | awk -v first="${disk}1" -v second="${disk}2" '$1 == first || $1 == second { $1="PART" substr($1,length($1)); print }'
}
fs_bytes() {
  tune2fs -l "${disk}3" | awk -F: '/^Block count:/ { count=$2+0 } /^Block size:/ { size=$2+0 } END { printf "%.0f\n",count*size }'
}

if [[ $mode == grow-mounted-root ]]; then
  [[ $(findmnt -n -o FSTYPE --target /) == ext4 && $(findmnt -n -o FSROOT --target /) == / ]] || fail 'mounted test root is not ext4.'
  root_dev=$(readlink -f "/dev/block/$(findmnt -rn -o MAJ:MIN --target /)")
  [[ $root_dev == "${disk}3" ]] || fail 'test disk is not the mounted root disk.'
  root_uuid=$(sed -n 's/^ROOT_UUID=//p' /etc/pinephone-pro/boot.conf)
  [[ $root_uuid =~ ^[[:xdigit:]]{8}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{12}$ ]] || fail 'configured root UUID is invalid.'
  [[ $(findmnt -n -o UUID --target /) == "$root_uuid" && $(blkid -s UUID -o value "$root_dev") == "$root_uuid" ]] || fail 'configured root UUID differs from mounted root.'
  grep -Fxq ROOT_FSTYPE=ext4 /etc/pinephone-pro/boot.conf || fail 'configured root filesystem differs.'
  grep -Fxq ROOT_FLAGS= /etc/pinephone-pro/boot.conf || fail 'root configuration has unexpected flags.'
  [[ $(uname -r) == "$(cat /var/lib/pinephone-pro/default-kernel)" && $(uname -r) == *-jon-ppp ]] || fail 'test must run with the installed custom PPP kernel.'
  [[ $(cat "/sys/class/block/${disk_name}3/size") == 24074240 ]] || fail 'root partition does not retain the original 14 GiB image geometry.'
  [[ ! -e $report ]] || fail 'a prior growth report exists; preserve it or use a fresh external test directory.'
  boot_before=$(boot_partition_metadata)
  guid_before=$(blkid -s PARTUUID -o value "$root_dev")
  size_before=$(fs_bytes)
  {
    printf 'TEST=disposable-QEMU-overlay\nROOT_UUID=%s\nROOT_PARTUUID=%s\n' "$root_uuid" "$guid_before"
    printf 'CUSTOM_KERNEL=%s\nFS_BYTES_BEFORE=%s\n' "$(uname -r)" "$size_before"
    printf '%s\n' BOOT_PARTITIONS_BEFORE "$boot_before" BOOT_PARTITIONS_BEFORE_END
    printf '%s\n' GROWPART_IMPLEMENTATION
    sha256sum "$(command -v growpart)"
  } > "$report"
  sfdisk --dump "$disk" > /build/fedora-ppp-growth-test.before.sfdisk
  sgdisk --backup=/build/fedora-ppp-growth-test.before.gpt "$disk"
  # Production still requires PPP + internal MMC. This separate test invokes
  # exactly the same two resize operations on the disposable virtual root.
  GROWPART_RESIZER=sgdisk growpart --update=on "$disk" 3 2>&1 | tee -a "$report"
  udevadm settle --timeout=30
  [[ $(cat "/sys/class/block/${disk_name}3/start") == 5283840 ]] || fail 'root start moved.'
  [[ $(blkid -s PARTUUID -o value "$root_dev") == "$guid_before" ]] || fail 'root partition GUID changed.'
  [[ $(blkid -s UUID -o value "$root_dev") == "$root_uuid" ]] || fail 'root filesystem UUID changed.'
  [[ $(boot_partition_metadata) == "$boot_before" ]] || fail 'boot partition starts, ends, GUIDs or attributes changed.'
  resize2fs "$root_dev" 2>&1 | tee -a "$report"
  size_after=$(fs_bytes)
  (( size_after >= size_before + 1073741824 )) || fail 'online ext4 expansion did not add at least 1 GiB.'
  part_bytes=$(blockdev --getsize64 "$root_dev")
  (( size_after <= part_bytes && part_bytes-size_after < 4096 )) || fail 'ext4 size does not fill its new partition.'
  sfdisk --verify "$disk" 2>&1 | tee -a "$report"
  sync -f /
  {
    printf 'FS_BYTES_AFTER=%s\nROOT_PARTITION_BYTES_AFTER=%s\n' "$size_after" "$part_bytes"
    printf '%s\n' BOOT_PARTITIONS_AFTER "$(boot_partition_metadata)" BOOT_PARTITIONS_AFTER_END
    printf '%s\n' GROWTH_TEST_ONLINE_COMPLETE
  } >> "$report"
  cat "$report"
else
  [[ -f $report ]] && grep -Fxq GROWTH_TEST_ONLINE_COMPLETE "$report" || fail 'successful online growth report is missing.'
  for device in "$disk" "${disk}1" "${disk}2" "${disk}3"; do
    [[ -z $(findmnt -rn -S "$device") ]] || fail "filesystem still mounted: $device"
  done
  root_uuid=$(sed -n 's/^ROOT_UUID=//p' "$report")
  root_guid=$(sed -n 's/^ROOT_PARTUUID=//p' "$report")
  expected_fs_bytes=$(sed -n 's/^FS_BYTES_AFTER=//p' "$report")
  [[ $(blkid -s UUID -o value "${disk}3") == "$root_uuid" && $(blkid -s PARTUUID -o value "${disk}3") == "$root_guid" ]] || fail 'offline image identities differ from the online-tested image.'
  [[ $(fs_bytes) == "$expected_fs_bytes" ]] || fail 'offline filesystem size differs from online growth report.'
  boot_expected=$(awk '/^BOOT_PARTITIONS_BEFORE$/ { active=1; next } /^BOOT_PARTITIONS_BEFORE_END$/ { active=0 } active { print }' "$report")
  [[ $(boot_partition_metadata) == "$boot_expected" ]] || fail 'offline boot partition metadata differs.'
  e2fsck -fn "${disk}2" 2>&1 | tee -a "$report"
  e2fsck -fn "${disk}3" 2>&1 | tee -a "$report"
  fsck.fat -n "${disk}1" 2>&1 | tee -a "$report"
  sfdisk --verify "$disk" 2>&1 | tee -a "$report"
  printf '%s\n' GROWTH_TEST_OFFLINE_FILESYSTEM_CHECKS_COMPLETE | tee -a "$report"
fi
