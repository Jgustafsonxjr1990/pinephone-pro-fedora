#!/usr/bin/bash
# Only the newly launched disposable source snapshot and readonly growth target.
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export LC_ALL=C
fail() { printf 'Offline validation shutdown: %s\n' "$*" >&2; exit 1; }
[[ $EUID == 0 && $(uname -m) == aarch64 ]] || fail 'requires the isolated ARM64 guest.'
[[ $(readlink -f /proc/1/exe) == /usr/bin/bash ]] || fail 'PID 1 is not the offline shell.'
source_disk=${PPP_OFFLINE_SOURCE_DEVICE:?checked source disk is required}
growth_disk=${PPP_GROWTH_DEVICE:?checked growth disk is required}
[[ ( $source_disk == /dev/vda || $source_disk == /dev/vdb ) &&
   ( $growth_disk == /dev/vda || $growth_disk == /dev/vdb ) &&
   $source_disk != "$growth_disk" ]] || fail 'disk identities are invalid.'
[[ $(cat "/sys/block/${source_disk##*/}/serial") == PPP_OFFLINE_SOURCE &&
   $(cat "/sys/block/${growth_disk##*/}/serial") == PPP_GROWTH_TARGET ]] || fail 'disk serial identities differ.'
[[ $(blockdev --getsize64 "$source_disk") == 12206473216 &&
   $(blockdev --getsize64 "$growth_disk") == 17179869184 &&
   $(blockdev --getro "$growth_disk") == 1 ]] || fail 'disk geometry or readonly target differs.'
[[ $(findmnt -n -o FSTYPE --target /) == btrfs &&
   $(findmnt -n -o FSROOT --target /) == /root &&
   $(findmnt -n -o UUID --target /) == 6741cdec-fe58-4214-9fa9-3e8eaa52f476 &&
   $(readlink -f "$(findmnt -rn --nofsroot -o SOURCE --target /)") == "${source_disk}3" ]] || fail 'mounted source root identity differs.'
for device in "$growth_disk" "${growth_disk}1" "${growth_disk}2" "${growth_disk}3"; do
  [[ -z $(findmnt -rn -S "$device") ]] || fail 'the readonly growth target is mounted.'
done
sync
# The offline bootstrap mounts only root; tolerate absent source data mounts.
for mount_path in /boot/efi /boot /home /var; do
  if findmnt -rn --mountpoint "$mount_path" >/dev/null; then
    umount "$mount_path"
    [[ -z $(findmnt -rn --mountpoint "$mount_path") ]] || fail 'a source data mount remains.'
  fi
done
sync
mount -o remount,ro /
[[ ,$(findmnt -n -o OPTIONS --target /), == *,ro,* ]] || fail 'source root remount is not readonly.'
printf '%s\n' OFFLINE_VALIDATION_FILESYSTEMS_FLUSHED
exec poweroff -f
