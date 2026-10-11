#!/usr/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# Run only inside the isolated ARM64 build VM. This creates its EMPTY vdb disk;
# it cannot target physical mmc, USB or host disks and never installs a loader.
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export LC_ALL=C
umask 022

fail() { printf 'Image assembly: %s\n' "$*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || fail 'root privileges are required inside the build VM.'
[[ $# -eq 1 && $1 =~ ^[0-9][A-Za-z0-9._+-]*-jon-ppp$ ]] || fail 'usage: assemble-fedora-ppp.sh KERNEL_RELEASE'
kernel_release=$1
disk=/dev/vdb
target=/mnt/fedora-ppp-image
report=/build/fedora-ppp-image-assembly.txt
expected_bytes=15032385536 # 14 GiB, independent of the later phone capacity.
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

for command in blockdev sfdisk wipefs lsblk udevadm passwd findmnt mount umount mountpoint mkfs.ext4 mkfs.vfat rsync blkid chroot setfiles e2fsck fsck.fat sha256sum python3 sort; do
  command -v "$command" >/dev/null || fail "missing build command: $command"
done
[[ $(uname -m) == aarch64 ]] || fail 'this script must run in the ARM64 build VM.'
[[ -b $disk && -e /sys/block/vdb ]] || fail 'the dedicated vdb target disk is missing.'
[[ $(readlink -f /sys/block/vdb/device/driver) == /sys/bus/virtio/drivers/virtio_blk ]] || fail 'vdb is not a VirtIO block disk.'
[[ $(blockdev --getsize64 "$disk") == "$expected_bytes" ]] || fail 'vdb is not exactly the expected empty 14 GiB virtual disk.'
[[ $(blockdev --getss "$disk") == 512 && $(blockdev --getro "$disk") == 0 ]] || fail 'target must be writable with 512-byte sectors.'
[[ $(lsblk -n -o TYPE "$disk") == disk ]] || fail 'target already contains partitions.'
[[ -z $(wipefs --no-act --noheadings --output TYPE "$disk") ]] || fail 'target has existing filesystem or partition signatures.'
[[ -z $(findmnt -rn -S "$disk") ]] || fail 'target disk is mounted.'
[[ $(findmnt -n -o SOURCE --target /) != "$disk"* ]] || fail 'source root unexpectedly belongs to the target.'
[[ $(findmnt -n -o FSTYPE --target /) == btrfs && $(findmnt -n -o FSROOT --target /) == /root ]] || fail 'source root must be the Fedora Btrfs root subvolume.'
for source_mount in /var /home /boot /boot/efi /build; do
  mountpoint -q "$source_mount" || fail "required source mount missing: $source_mount"
  [[ $(findmnt -n -o SOURCE --target "$source_mount") != "$disk"* ]] || fail 'source mount unexpectedly belongs to the target.'
done
[[ $(findmnt -n -o FSROOT --target /var) == /var && $(findmnt -n -o FSROOT --target /home) == /home ]] || fail 'the Fedora var/home subvolumes are not mounted correctly.'
[[ $(findmnt -n -o FSTYPE --target /boot) == ext4 && $(findmnt -n -o FSTYPE --target /boot/efi) == vfat ]] || fail 'source boot filesystems are incorrect.'
[[ -s /usr/share/pinephone-pro/kernel/$kernel_release/Image && -d /usr/lib/modules/$kernel_release ]] || fail 'the matching custom kernel RPM is not installed.'
[[ -x /usr/sbin/pinephone-pro-kernel-update ]] || fail 'custom boot updater is missing.'
[[ $(passwd -S root | awk '{print $2}') == L ]] || fail 'the image source must have a locked root account.'
[[ -z $(awk -F: '$3 >= 1000 && $3 < 65534 {print $1}' /etc/passwd) ]] || fail 'source has pre-created user accounts; preserve Fedora Plasma Setup instead.'
[[ -s $script_dir/pinephone-pro-grow-root && -s $script_dir/pinephone-pro-grow-root.service ]] || fail 'the reviewed growth script/unit are missing.'
for command in growpart sgdisk resize2fs partx flock; do command -v "$command" >/dev/null || fail "missing target growth command: $command"; done
[[ -s /etc/selinux/targeted/contexts/files/file_contexts ]] || fail 'targeted SELinux policy is missing.'

mkdir -p "$target"
[[ -z $(find "$target" -mindepth 1 -maxdepth 1 -print -quit) ]] || fail 'target staging directory is not empty.'
mounted=()
build_logging_dropin=$target/etc/dracut.conf.d/zzzz-pinephone-pro-build-logging.conf
build_logging_fd=
remove_build_logging_dropin() {
  [[ -n $build_logging_fd ]] || return 0
  # The open descriptor identifies our exclusive creation, even if interrupted
  # immediately after opening it. Never remove a replacement file or symlink.
  if [[ -L $build_logging_dropin || ! -f $build_logging_dropin ||
        ! $build_logging_dropin -ef /proc/$$/fd/$build_logging_fd ]]; then
    printf 'Build logging drop-in changed; preserve it and leave image incomplete.\n' >&2
    return 1
  fi
  rm -- "$build_logging_dropin" || return 1
  if [[ -e $build_logging_dropin || -L $build_logging_dropin ]]; then
    printf 'Build logging drop-in remains; image is incomplete.\n' >&2
    return 1
  fi
  exec {build_logging_fd}>&-
  build_logging_fd=
}
verify_build_logging_config() {
  python3 - "$1" "${build_logging_dropin##*/}" "$2" <<'LOGGING_PREFLIGHT'
import os
from pathlib import Path
import re
import subprocess
import sys

root, name = Path(sys.argv[1]), sys.argv[2]
controls = {'conffile', 'confdir', 'add_confdir', 'allowlocal', 'dracutbasedir',
            'dracutsysrootdir', 'sysroot_l', 'stdloglvl_l', 'maxloglvl', '__DRACUT_LOGGER__',
            'BASH_ENV', 'ENV', 'IFS', 'GLOBIGNORE'}
if any(os.environ.get(key) for key in controls):
    raise SystemExit('Nondefault inherited dracut controls prevent logging preflight.')
dirs = [root / 'etc/dracut.conf.d', root / 'usr/lib/dracut/dracut.conf.d']
effective = {}
for directory in dirs:
    if directory.is_symlink() or directory.resolve() != directory:
        raise SystemExit('Dracut configuration directory is not canonical.')
    proposed = directory / name
    if proposed.exists() or proposed.is_symlink():
        raise SystemExit('Build logging drop-in name already exists in a config directory.')
    if not directory.exists():
        continue
    if not directory.is_dir():
        raise SystemExit('Dracut configuration directory is not a directory.')
    for path in directory.iterdir():
        if path.name.endswith('.conf') and (path.exists() or path.is_symlink()):
            if re.fullmatch(r'[A-Za-z0-9._+-]+[.]conf', path.name) is None:
                raise SystemExit('Dracut config basename cannot be safely sorted.')
            effective.setdefault(path.name, path)
# Main config can redirect the search before expansion. Refuse executable or
# expanded syntax and control overrides instead of sourcing config a second time.
literal = re.compile(r'''\s*([A-Za-z_][A-Za-z0-9_]*)\+?=(?:'[^']*'|"[^"$`\\]*"|[A-Za-z0-9_./,:+%-]*)\s*(?:#.*)?''')
forbidden_keys = controls | {'LANG', 'verbosity_mod_l', 'PATH', 'SHELLOPTS', 'BASHOPTS', 'CDPATH'}
for path in [root / 'etc/dracut.conf', *effective.values()]:
    if not path.exists() and not path.is_symlink():
        continue
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise SystemExit('Dracut config is not a small regular file.')
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        match = literal.fullmatch(line)
        if match is None or match[1] in forbidden_keys or match[1].startswith('LC_'):
            raise SystemExit('Dracut config syntax cannot prove logging order and levels.')
ordered = subprocess.check_output(['sort', '-Vu'],
    input=('\n'.join([*effective, name]) + '\n').encode()).decode().splitlines()
if not ordered or ordered[-1] != name:
    raise SystemExit('Build logging drop-in is not last in dracut sort -Vu order.')
print('FEDORA_PPP_BUILD_LOGGING_ORDER_VERIFIED scope=' + sys.argv[3]
      + ' configs=' + str(len(effective)) + ' last=' + name)
LOGGING_PREFLIGHT
}
cleanup() {
  local result=$? index
  trap - EXIT
  if ! remove_build_logging_dropin; then
    printf 'Could not remove owned build logging drop-in before unmount.\n' >&2
    ((result != 0)) || result=1
  fi
  for ((index=${#mounted[@]}-1; index>=0; index--)); do
    if mountpoint -q "${mounted[index]}"; then
      umount -R "${mounted[index]}" || { printf 'Could not unmount %s; image is not ready.\n' "${mounted[index]}" >&2; result=1; }
    fi
  done
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Fail on unsupported source config before partitioning or copying the target.
verify_build_logging_config / source

# Keep every partition after the RK3399 loader reserve. Both boot filesystems
# carry the GPT legacy boot attribute so U-Boot can try ext4 as a FAT fallback.
sfdisk --wipe never --wipe-partitions never "$disk" <<'PARTITIONS'
label: gpt
unit: sectors
first-lba: 65536

start=65536, size=1024000, type=C12A7328-F81F-11D2-BA4B-00A0C93EC93B, name="FEDORA_EFI", attrs="LegacyBIOSBootable"
size=4194304, type=0FC63DAF-8483-4772-8E79-3D69D8477DE4, name="FEDORA_BOOT", attrs="LegacyBIOSBootable"
type=0FC63DAF-8483-4772-8E79-3D69D8477DE4, name="FEDORA_ROOT"
PARTITIONS
blockdev --rereadpt "$disk"
udevadm settle --timeout=30
for partition in "${disk}1" "${disk}2" "${disk}3"; do [[ -b $partition ]] || fail "missing partition node: $partition"; done
mkfs.vfat -F 32 -n FEDORA_EFI "${disk}1"
mkfs.ext4 -q -m 0 -L FEDORA_BOOT -E lazy_itable_init=0,lazy_journal_init=0 "${disk}2"
mkfs.ext4 -q -m 1 -L FEDORA_ROOT -E lazy_itable_init=0,lazy_journal_init=0 "${disk}3"
efi_uuid=$(blkid -s UUID -o value "${disk}1")
boot_uuid=$(blkid -s UUID -o value "${disk}2")
root_uuid=$(blkid -s UUID -o value "${disk}3")
[[ $root_uuid != "$(findmnt -n -o UUID --target /)" ]] || fail 'new root UUID must differ from the source image.'

mount "${disk}3" "$target"; mounted+=("$target")
rsync -aHAX --numeric-ids --one-file-system \
  --exclude=/boot/*** --exclude=/var/*** --exclude=/home/*** \
  --exclude=/proc/*** --exclude=/sys/*** --exclude=/dev/*** --exclude=/run/*** \
  --exclude=/tmp/*** --exclude=/build/*** --exclude=/mnt/*** \
  / "$target/"
mkdir -p "$target"/{var,home,boot/efi,proc,sys,dev,run,tmp,build,mnt}
chmod 1777 "$target/tmp"
rsync -aHAX --numeric-ids --one-file-system \
  --exclude='/cache/dnf/***' --exclude='/cache/libdnf5/***' --exclude='/tmp/*' \
  --exclude=/lib/systemd/random-seed --exclude=/lib/NetworkManager/secret_key \
  --exclude=/lib/NetworkManager/*lease* \
  /var/ "$target/var/"
rsync -aHAX --numeric-ids --one-file-system /home/ "$target/home/"
mkdir -p "$target/var"/{cache,log,tmp}
chmod 1777 "$target/var/tmp"
# Keep package-owned log directories/modes while clearing image-build logs.
find "$target/var/log" -type f -exec truncate -s 0 -- {} +
if [[ -d $target/var/log/journal ]]; then
  find "$target/var/log/journal" -type f -name '*.journal*' -delete
fi
mount "${disk}2" "$target/boot"; mounted+=("$target/boot")
# Retain kernel payloads, but omit cloned GRUB/BLS/extlinux menus and all EFI
# executables. The phone updater creates only the matching PPP boot entries.
rsync -aHAX --numeric-ids --one-file-system \
  --exclude=/efi/*** --exclude=/grub2/*** --exclude=/loader/*** \
  --exclude=/extlinux/*** --exclude=/.pinephone-pro-update.* \
  /boot/ "$target/boot/"
mkdir -p "$target/boot/efi"
mount -o umask=0077 "${disk}1" "$target/boot/efi"; mounted+=("$target/boot/efi")
# Deliberately copy no source EFI/BOOT loaders, stale UUIDs, or boot menus.

cat > "$target/etc/fstab" <<FSTAB
# Fedora PinePhone Pro internal eMMC image; every image has unique UUIDs.
UUID=$root_uuid / ext4 defaults 0 1
UUID=$boot_uuid /boot ext4 defaults 0 2
UUID=$efi_uuid /boot/efi vfat umask=0077,shortname=winnt 0 2
FSTAB
extra_args='console=tty0 console=ttyS2,115200n8 rootwait loglevel=4 brcmfmac.feature_disable=0x82000'
cat > "$target/etc/pinephone-pro/boot.conf" <<BOOTCONF
ROOT_UUID=$root_uuid
ROOT_FSTYPE=ext4
ROOT_FLAGS=
EXTRA_ARGS=$extra_args
BOOTCONF
mkdir -p "$target/etc/kernel"
printf 'root=UUID=%s rootfstype=ext4 rw %s\n' "$root_uuid" "$extra_args" > "$target/etc/kernel/cmdline"

# Preserve Fedora Plasma Setup's initial account creation. Never provision a
# shared password, logged-in root session, machine ID or SSH server identity.
# An empty file generates a unique ID without applying systemd first-boot
# presets or invoking the generic console wizard. Plasma Setup uses its own
# completion flag and remains enabled for graphical account creation.
: > "$target/etc/machine-id"
chmod 0444 "$target/etc/machine-id"
# This generic Linux-GPT/ext4 layout grows through the device-checked PPP
# service. Fedora's inherited Type=root repart definition is incompatible.
if [[ -e "$target/etc/repart.d/50-root.conf" ]]; then
  [[ $(cat "$target/etc/repart.d/50-root.conf") == $'[Partition]\nType=root' ]] || fail 'unexpected inherited repart configuration.'
  rm -- "$target/etc/repart.d/50-root.conf"
fi
mkdir -p "$target/var/lib/dbus"
ln -sfn /etc/machine-id "$target/var/lib/dbus/machine-id"
rm -f "$target"/etc/ssh/ssh_host_* "$target/var/lib/systemd/random-seed"
rm -f "$target/root/.bash_history" "$target/root/.lesshst" "$target/root/.wget-hsts"
rm -f "$target/var/lib/pinephone-pro/root-expanded"
ln -sfn ../run/NetworkManager/resolv.conf "$target/etc/resolv.conf"
install -D -m 0755 "$script_dir/pinephone-pro-grow-root" "$target/usr/sbin/pinephone-pro-grow-root"
install -D -m 0644 "$script_dir/pinephone-pro-grow-root.service" "$target/usr/lib/systemd/system/pinephone-pro-grow-root.service"
mkdir -p "$target/etc/systemd/system/multi-user.target.wants"
ln -sfn /usr/lib/systemd/system/pinephone-pro-grow-root.service "$target/etc/systemd/system/multi-user.target.wants/pinephone-pro-grow-root.service"

# Reject any persisted build-only trust or proxy settings in operational files.
if grep -REn '/build/build-ca\.pem|10\.0\.2\.2:[0-9]+|10\.0\.2\.3' \
    "$target/etc/dnf" "$target/etc/yum.repos.d" "$target/etc/environment" "$target/etc/profile.d" 2>/dev/null; then
  fail 'temporary build proxy/trust/DNS settings leaked into target configuration.'
fi

mount -t proc proc "$target/proc"; mounted+=("$target/proc")
mount --rbind /sys "$target/sys"; mounted+=("$target/sys")
mount --make-rslave "$target/sys"
mount --rbind /dev "$target/dev"; mounted+=("$target/dev")
mount --make-rslave "$target/dev"
mount -t tmpfs -o mode=0755,size=64m tmpfs "$target/run"; mounted+=("$target/run")
[[ $(chroot "$target" findmnt -n -o UUID --target /) == "$root_uuid" ]] || fail 'chroot mount table does not report the target root UUID.'
[[ $(chroot "$target" findmnt -n -o FSTYPE --target /) == ext4 ]] || fail 'chroot mount table does not report the target ext4 root.'
[[ $(chroot "$target" findmnt -n -o UUID --target /boot) == "$boot_uuid" && $(chroot "$target" findmnt -n -o FSTYPE --target /boot) == ext4 ]] || fail 'chroot boot mount does not match the target boot partition.'
[[ $(chroot "$target" findmnt -n -o UUID --target /boot/efi) == "$efi_uuid" && $(chroot "$target" findmnt -n -o FSTYPE --target /boot/efi) == vfat ]] || fail 'chroot FAT mount does not match the target EFI partition.'
chroot "$target" findmnt --verify --verbose --tab-file /etc/fstab
# Fedora 108's syslog debug level otherwise enables a full internal lsinitrd
# dump. This temporary target-only drop-in retains stderr info/errors; the
# updater's required archive listing and strict portability audit still run.
verify_build_logging_config "$target" target
mkdir -p "$target/etc/dracut.conf.d"
set -o noclobber
if exec {build_logging_fd}> "$build_logging_dropin"; then
  set +o noclobber
else
  set +o noclobber
  fail 'could not exclusively create build logging drop-in.'
fi
printf '%s\n' 'stdloglvl=4' 'sysloglvl=0' 'kmsgloglvl=0' 'fileloglvl=0' >&"$build_logging_fd"
chroot "$target" /usr/sbin/pinephone-pro-kernel-update "$kernel_release"
remove_build_logging_dropin || fail 'build logging drop-in removal failed.'
printf '%s\n' FEDORA_PPP_BUILD_LOGGING_DROPIN_REMOVED
chroot "$target" dnf check
[[ $(chroot "$target" passwd -S root | awk '{print $2}') == L ]] || fail 'target root account unexpectedly became unlocked.'
[[ $(chroot "$target" systemctl is-enabled plasmalogin.service) == enabled ]] || fail 'Plasma Login is not enabled.'
[[ $(chroot "$target" readlink -f /etc/systemd/system/display-manager.service) == /usr/lib/systemd/system/plasmalogin.service ]] || fail 'display manager alias is incorrect.'
[[ ! -e $target/boot/efi/EFI/BOOT ]] || fail 'an unverified generic EFI boot path was copied.'
[[ $(cat "$target/var/lib/pinephone-pro/default-kernel") == "$kernel_release" ]] || fail 'phone default kernel selection is incorrect.'
grep -Fq "root=UUID=$root_uuid rootfstype=ext4" "$target/boot/efi/extlinux/extlinux.conf" || fail 'phone boot menu does not select the target ext4 root.'

# Unmount pseudo filesystems before the offline SELinux walk. This prevents
# labeling the running VM's /dev, /sys or /proc through the temporary bindings.
for path in run dev sys proc; do umount -R "$target/$path"; done
setfiles -F -r "$target" -e "$target/boot/efi" \
  "$target/etc/selinux/targeted/contexts/files/file_contexts" "$target"
sync
{
  printf 'KERNEL_RELEASE=%s\nROOT_UUID=%s\nBOOT_UUID=%s\nEFI_UUID=%s\n' "$kernel_release" "$root_uuid" "$boot_uuid" "$efi_uuid"
  printf 'IMAGE_BYTES=%s\n' "$expected_bytes"
  printf 'SOURCE_ROOT_FS=btrfs\nFINAL_ROOT_FS=ext4\nTARGET=internal-eMMC\n'
  printf 'BOOT_PATH=explicit-PinePhone-Pro-extlinux\n'
  sfdisk --dump "$disk"
  chroot "$target" rpm -qa --qf '%{NAME}\t%{VERSION}-%{RELEASE}\t%{ARCH}\n' | sort
} > "$report"

# Complete filesystem verification only after all copied files are flushed and
# unmounted. A check failure leaves the image incomplete and must be resolved.
for ((index=${#mounted[@]}-1; index>=0; index--)); do
  mountpoint -q "${mounted[index]}" && umount -R "${mounted[index]}"
done
mounted=()
e2fsck -fn "${disk}2"
e2fsck -fn "${disk}3"
fsck.fat -n "${disk}1"
sfdisk --verify "$disk"
sync
printf 'FEDORA_PPP_IMAGE_ASSEMBLY_COMPLETE root=%s kernel=%s\n' "$root_uuid" "$kernel_release"
