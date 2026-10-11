#!/usr/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# Inspect a normally booted QEMU snapshot/disposable overlay. This script does
# not exercise a graphical session, change phone boot menus or control hardware.
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export LC_ALL=C
umask 077
fail() { printf 'Fedora PPP VM verification: %s\n' "$*" >&2; exit 1; }
[[ $EUID -eq 0 && $(uname -m) == aarch64 ]] || fail 'requires root in the isolated ARM64 VM.'
[[ -r /proc/device-tree/compatible ]] || fail 'VM device tree unavailable.'
tr '\0' '\n' < /proc/device-tree/compatible | grep -Fxq linux,dummy-virt || fail 'this report is only for QEMU virt.'
mountpoint -q /build || fail 'mount the external 9p report share at /build first.'
verify_disk=${PPP_VERIFY_DISK:?fresh serial-checked controller disk is required}
[[ ( $verify_disk == /dev/vda || $verify_disk == /dev/vdb ) && -b $verify_disk ]] || fail 'checked root disk is invalid.'
[[ $(cat "/sys/block/${verify_disk##*/}/serial") == PPP_VERIFY_ROOT &&
   $(blockdev --getsize64 "$verify_disk") == 15032385536 &&
   $(readlink -f "/dev/block/$(findmnt -rn -o MAJ:MIN --target /)") == "${verify_disk}3" ]] || fail 'normal root disk serial, geometry or mapping differs.'
report=/build/fedora-ppp-vm-verification.txt
[[ ! -e $report ]] || fail 'an existing report must be preserved or moved before repeating verification.'
exec > >(tee "$report") 2>&1
trap 'result=$?; if ((result)); then printf "VERIFICATION_FAILED status=%s line=%s\n" "$result" "$LINENO"; fi' EXIT
printf 'VERIFICATION_TYPE=normal-systemd-boot-headless-QEMU\n'
printf 'AS_OF_UTC=%s\n' "$(date -u +%FT%TZ)"
[[ $(readlink -f /proc/1/exe) == /usr/lib/systemd/systemd ]] || fail 'PID 1 is not systemd.'
# The debug shell starts early. Wait for normal multi-user startup rather than
# reporting a partially completed boot as successful.
for ((attempt=0; attempt<900; attempt++)); do
  systemctl is-active --quiet multi-user.target && break
  sleep 1
done
systemctl is-active --quiet multi-user.target || fail 'normal multi-user startup did not complete within 15 minutes.'
[[ ! -e /etc/repart.d/50-root.conf ]] || fail 'incompatible inherited repart configuration remains.'
[[ $(systemctl show systemd-firstboot.service -p ConditionResult --value) == no ]] || fail 'generic console firstboot was not skipped.'
[[ $(systemctl show systemd-repart.service -p ConditionResult --value) == no ]] || fail 'generic repart was not skipped.'
[[ $(cat /etc/machine-id) =~ ^[[:xdigit:]]{32}$ ]] || fail 'a unique machine ID was not generated.'
source /etc/os-release
[[ $ID == fedora && $VERSION_ID == 44 ]] || fail 'system is not Fedora 44.'
printf 'DISTRO=%s\nARCH=%s\nKERNEL=%s\nPID1=%s\n' "$PRETTY_NAME" "$(uname -m)" "$(uname -r)" "$(readlink -f /proc/1/exe)"
[[ $(uname -r) == 7.2.9-jon-ppp ]] || fail 'the running kernel is not the reviewed PPP build.'
[[ $(cat /var/lib/pinephone-pro/default-kernel) == "$(uname -r)" ]] || fail 'running and selected phone kernel differ.'

runtime_packages=(
  kernel-pinephone-pro pinephone-pro-kernel-tools pinephonepro-device-support eg25-manager
  plasma-mobile plasma-workspace plasma-login-manager plasma-setup plasma-keyboard kwin
  NetworkManager ModemManager bluez brcmfmac-firmware alsa-ucm alsa-utils
  pipewire wireplumber feedbackd iio-sensor-proxy powerdevil plasma-nm plasma-pa
  spacebar plasma-dialer plasma-phonebook dracut selinux-policy-targeted
)
[[ ${#runtime_packages[@]} == 28 ]] || fail 'runtime package check list has changed unexpectedly.'
printf '%s\n' CORE_RUNTIME_PACKAGES_BEGIN
rpm -q --qf '%{NAME}\t%{VERSION}-%{RELEASE}\t%{ARCH}\n' "${runtime_packages[@]}"
printf '%s\n' CORE_RUNTIME_PACKAGES_END
[[ -s /build/essential-runtime-packages.txt ]] || fail 'canonical essential runtime package list is missing.'
mapfile -t essential_packages < <(sed -E '/^[[:space:]]*(#|$)/d' /build/essential-runtime-packages.txt)
[[ ${#essential_packages[@]} == 28 ]] || fail 'canonical essential package list must contain 28 packages.'
for package in "${essential_packages[@]}"; do
  [[ $package =~ ^[A-Za-z0-9][A-Za-z0-9+_.-]*$ ]] || fail 'canonical essential package list has an invalid name.'
done
[[ $(printf '%s\n' "${essential_packages[@]}" | sort -u | wc -l) == 28 ]] || fail 'canonical essential package list contains duplicates.'
printf '%s\n' ESSENTIAL_RUNTIME_PACKAGES_BEGIN
rpm -q --qf '%{NAME}\t%{VERSION}-%{RELEASE}\t%{ARCH}\n' "${essential_packages[@]}"
printf '%s\n' ESSENTIAL_RUNTIME_PACKAGES_END
rpm -q cloud-utils-growpart gdisk e2fsprogs
[[ $(getenforce) == Enforcing ]] || fail 'SELinux is not enforcing in the normal systemd boot.'
sestatus
if [[ -r /sys/kernel/security/lsm ]]; then
  printf 'ACTIVE_LSM=%s\n' "$(cat /sys/kernel/security/lsm)"
  tr ',' '\n' < /sys/kernel/security/lsm | grep -Fxq selinux || fail 'active LSM list does not include SELinux.'
fi
[[ $(passwd -S root | awk '{print $2}') == L ]] || fail 'root account is not locked.'
[[ -z $(awk -F: '$3 >= 1000 && $3 < 65534 {print $1}' /etc/passwd) ]] || fail 'a normal user account was created before Fedora Plasma Setup.'
[[ $(systemctl is-enabled plasmalogin.service) == enabled ]] || fail 'Plasma Login is not enabled.'
[[ $(readlink -f /etc/systemd/system/display-manager.service) == /usr/lib/systemd/system/plasmalogin.service ]] || fail 'display-manager alias is incorrect.'
[[ $(kreadconfig6 --file /etc/plasmalogin.conf.d/90-pinephonepro.conf --group Greeter --key PreselectedSession) == plasma-mobile.desktop ]] || fail 'Plasma Mobile is not preselected.'
[[ -s /usr/share/wayland-sessions/plasma-mobile.desktop ]] || fail 'Plasma Mobile Wayland session is absent.'
[[ $(kreadconfig6 --file /etc/xdg/kwinrc --group Wayland --key InputMethod) == /usr/share/applications/org.kde.plasma.keyboard.desktop ]] || fail 'Plasma Keyboard is not configured.'
[[ $(kreadconfig6 --file /etc/xdg/kwinrc --group Wayland --key VirtualKeyboardEnabled) == true ]] || fail 'virtual keyboard is not enabled.'
[[ -s /usr/share/applications/org.kde.plasma.keyboard.desktop ]] || fail 'Plasma Keyboard launcher is absent.'
for unit in eg25-manager.service ModemManager.service NetworkManager.service bluetooth.service pinephone-pro-grow-root.service; do
  systemctl is-enabled --quiet "$unit" || fail "required service is not enabled: $unit"
  printf 'SERVICE_STATE %s %s\n' "$unit" "$(systemctl is-active "$unit" || true)"
done
systemctl is-active --quiet NetworkManager.service || fail 'NetworkManager is not running.'
systemctl is-active --quiet dbus.service || fail 'D-Bus is not running.'

configured_uuid=$(sed -n 's/^ROOT_UUID=//p' /etc/pinephone-pro/boot.conf)
[[ $configured_uuid =~ ^[[:xdigit:]]{8}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{12}$ ]] || fail 'phone root UUID is invalid.'
[[ $(findmnt -n -o UUID --target /) == "$configured_uuid" && $(findmnt -n -o FSTYPE --target /) == ext4 && $(findmnt -n -o FSROOT --target /) == / ]] || fail 'running root does not match phone boot configuration.'
grep -Fxq ROOT_FSTYPE=ext4 /etc/pinephone-pro/boot.conf || fail 'phone boot configuration is not ext4.'
grep -Fxq ROOT_FLAGS= /etc/pinephone-pro/boot.conf || fail 'phone boot configuration retains source subvolume flags.'
for path in /boot /boot/efi; do mountpoint -q "$path" || fail "boot filesystem is not mounted: $path"; done
[[ $(findmnt -n -o FSTYPE --target /boot) == ext4 && $(findmnt -n -o FSTYPE --target /boot/efi) == vfat ]] || fail 'boot filesystem types differ.'
findmnt -rn -o TARGET,SOURCE,FSTYPE,UUID,FSROOT --target /
findmnt -rn -o TARGET,SOURCE,FSTYPE,UUID,FSROOT --target /boot
findmnt -rn -o TARGET,SOURCE,FSTYPE,UUID,FSROOT --target /boot/efi
findmnt --verify --verbose --tab-file /etc/fstab
grep -Fq "root=UUID=$configured_uuid rootfstype=ext4" /boot/efi/extlinux/extlinux.conf || fail 'FAT extlinux root selection differs.'
grep -Fq "root=UUID=$configured_uuid rootfstype=ext4" /boot/extlinux/extlinux.conf || fail 'ext4 extlinux root selection differs.'
if grep -E 'systemd\.debug_shell|systemd\.mask=|init=/bin/bash' /boot/efi/extlinux/extlinux.conf /boot/extlinux/extlinux.conf /etc/kernel/cmdline; then
  fail 'temporary VM shell arguments were persisted in phone boot settings.'
fi
[[ ! -e /boot/efi/EFI/BOOT ]] || fail 'generic EFI boot trap is present.'

release=$(uname -r)
payload=/usr/share/pinephone-pro/kernel/$release
printf '%s\n' MATCHING_KERNEL_PAYLOAD_CHECK_BEGIN
(cd "$payload"; sha256sum --check --strict SHA256SUMS)
(cd "/usr/lib/modules/$release"; sha256sum --check --strict --quiet "$payload/MODULES_SHA256SUMS")
cmp -s "$payload/Image" "/boot/vmlinuz-$release" || fail 'ext4 phone Image differs from RPM payload.'
cmp -s "$payload/Image" "/boot/efi/pinephone-pro/$release/Image" || fail 'FAT phone Image differs from RPM payload.'
cmp -s "$payload/rk3399-pinephone-pro.dtb" "/boot/efi/pinephone-pro/$release/rk3399-pinephone-pro.dtb" || fail 'phone DTB differs from RPM payload.'
cmp -s "/boot/initramfs-$release.img" "/boot/efi/pinephone-pro/$release/initramfs.img" || fail 'FAT and ext4 initramfs differ.'
printf '%s\n' MATCHING_KERNEL_PAYLOAD_CHECK_END
rpm -V eg25-manager pinephonepro-device-support
for path in /usr/lib/firmware/brcm/BCM4345C0.hcd /usr/lib/firmware/brcm/BCM4345C5.hcd \
  /usr/share/alsa/ucm2/PinePhonePro/PINE64-PinePhonePro-.conf \
  /usr/share/feedbackd/themes/pine64,pinephone-pro.json \
  /usr/share/eg25-manager/pine64,pinephone-pro.toml; do
  [[ -s $path ]] || fail "phone support input missing: $path"
done
for path in /usr/lib/firmware/brcm/brcmfmac43455-sdio.bin \
  /usr/lib/firmware/brcm/brcmfmac43455-sdio.clm_blob \
  /usr/lib/firmware/brcm/brcmfmac43455-sdio.pine64,pinephone-pro.txt; do
  [[ -s $path || -s $path.xz || -s $path.zst ]] || fail "Fedora Wi-Fi support input missing: $path"
done
dnf check
printf '%s\n' FAILED_UNITS_OBSERVED_BEGIN
systemctl --failed --no-pager --no-legend
printf '%s\n' FAILED_UNITS_OBSERVED_END
printf '%s\n' 'LIMITATION=Headless VM does not validate graphical login, on-screen keyboard interaction, modem, audio, Wi-Fi, Bluetooth, cameras, charging or suspend on PinePhone Pro hardware.'
printf '%s\n' FEDORA_PPP_NORMAL_SYSTEMD_BOOT_VERIFIED
