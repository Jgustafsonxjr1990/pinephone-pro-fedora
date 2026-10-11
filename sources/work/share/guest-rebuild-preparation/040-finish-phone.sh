#!/usr/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# Future final source-VM preparation. Enable units; do not start hardware services.
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export LC_ALL=C
umask 022
recipe_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
[[ $EUID == 0 && $(uname -m) == aarch64 && $(uname -r) == 7.2.9-jon-ppp ]]
source /etc/os-release
[[ $ID == fedora && $VERSION_ID == 44 && $(findmnt -n -o FSTYPE --target /build) == 9p ]]
for report in /build/fresh-package-state.json /build/fedora-custom-package-sources.tsv; do
  [[ ! -e $report && ! -L $report ]]
done
python3 - "$recipe_dir/finish-inputs.json" <<'FINISH_PREFLIGHT'
from pathlib import Path
import hashlib, json, sys
for name, record in json.loads(Path(sys.argv[1]).read_text())['files'].items():
    path = Path(name)
    assert path.is_file() and not path.is_symlink() and path.resolve() == path
    assert path.stat().st_size == record['size_bytes']
    assert hashlib.sha256(path.read_bytes()).hexdigest() == record['sha256']
kernel = json.loads(Path('/build/fedora-kernel-install-report.json').read_text())
device = json.loads(Path('/build/fedora-device-support-install-report.json').read_text())
assert kernel['status'] == 'kernel_release3_built_installed_verified'
assert kernel['installed_module_count'] == 906 and kernel['modules_signed'] is True
assert kernel['portable_initramfs_audit_status'] == 'passed'
assert device['status'] == 'device_support_built_installed_verified'
FINISH_PREFLIGHT
runtime_packages=(
  kernel-pinephone-pro pinephone-pro-kernel-tools pinephonepro-device-support eg25-manager
  plasma-mobile plasma-workspace plasma-login-manager plasma-setup plasma-keyboard kwin
  NetworkManager ModemManager bluez brcmfmac-firmware alsa-ucm alsa-utils
  pipewire wireplumber feedbackd iio-sensor-proxy powerdevil plasma-nm plasma-pa
  spacebar plasma-dialer plasma-phonebook dracut selinux-policy-targeted
)
[[ ${#runtime_packages[@]} == 28 ]]
mapfile -t canonical < <(sed -E '/^[[:space:]]*(#|$)/d' /build/essential-runtime-packages.txt)
[[ ${#canonical[@]} == 28 && $(printf '%s\n' "${canonical[@]}") == "$(printf '%s\n' "${runtime_packages[@]}")" ]]
source /build/live-build-network.sh
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export LC_ALL=C
[[ -s /run/ppp-build-ca-bundle.pem ]]
dnf_options=(--setopt=sslcacert=/run/ppp-build-ca-bundle.pem --setopt=proxy_sslcacert=/run/ppp-build-ca-bundle.pem)
# Four custom packages are installed and verified by their owning stages.
dnf5 "${dnf_options[@]}" install --assumeyes "${runtime_packages[@]:4}" cloud-utils-growpart gdisk e2fsprogs
rpm -q --qf '%{NAME}\t%{VERSION}-%{RELEASE}\t%{ARCH}\n' "${runtime_packages[@]}" cloud-utils-growpart gdisk e2fsprogs
for program in kreadconfig6 kwriteconfig6 systemctl growpart sgdisk resize2fs partx flock; do
  command -v "$program" >/dev/null
done
[[ $(passwd -S root | awk '{print $2}') == L ]]
[[ -z $(awk -F: '$3 >= 1000 && $3 < 65534 {print $1}' /etc/passwd) ]]
[[ -s /usr/share/wayland-sessions/plasma-mobile.desktop && -s /usr/share/applications/org.kde.plasma.keyboard.desktop ]]
[[ ! -L /etc/plasmalogin.conf.d && ! -L /etc/xdg/kwinrc ]]
mkdir -p /etc/plasmalogin.conf.d
[[ ! -e /etc/plasmalogin.conf.d/90-pinephonepro.conf && ! -L /etc/plasmalogin.conf.d/90-pinephonepro.conf ]]
set -o noclobber
printf '%s\n' '[Greeter]' 'PreselectedSession=plasma-mobile.desktop' > /etc/plasmalogin.conf.d/90-pinephonepro.conf
set +o noclobber
kwriteconfig6 --file /etc/xdg/kwinrc --group Wayland --key InputMethod /usr/share/applications/org.kde.plasma.keyboard.desktop
kwriteconfig6 --file /etc/xdg/kwinrc --group Wayland --key VirtualKeyboardEnabled true
[[ $(kreadconfig6 --file /etc/plasmalogin.conf.d/90-pinephonepro.conf --group Greeter --key PreselectedSession) == plasma-mobile.desktop ]]
[[ $(kreadconfig6 --file /etc/xdg/kwinrc --group Wayland --key InputMethod) == /usr/share/applications/org.kde.plasma.keyboard.desktop ]]
[[ $(kreadconfig6 --file /etc/xdg/kwinrc --group Wayland --key VirtualKeyboardEnabled) == true ]]
install -D -m 0755 /build/image-assembly/pinephone-pro-grow-root /usr/sbin/pinephone-pro-grow-root
install -D -m 0644 /build/image-assembly/pinephone-pro-grow-root.service /usr/lib/systemd/system/pinephone-pro-grow-root.service
systemctl --root=/ enable --force plasmalogin.service
systemctl --root=/ set-default graphical.target
systemctl --root=/ enable pinephone-pro-grow-root.service
for unit in plasmalogin.service eg25-manager.service ModemManager.service NetworkManager.service bluetooth.service pinephone-pro-grow-root.service; do
  systemctl --root=/ is-enabled --quiet "$unit"
done
[[ $(readlink -f /etc/systemd/system/display-manager.service) == /usr/lib/systemd/system/plasmalogin.service ]]
[[ $(systemctl --root=/ get-default) == graphical.target ]]
for path in /usr/lib/firmware/brcm/BCM4345C0.hcd /usr/lib/firmware/brcm/BCM4345C5.hcd \
  /usr/share/alsa/ucm2/PinePhonePro/PINE64-PinePhonePro-.conf \
  /usr/share/feedbackd/themes/pine64,pinephone-pro.json /usr/share/eg25-manager/pine64,pinephone-pro.toml; do
  [[ -s $path ]]
done
for path in /usr/lib/firmware/brcm/brcmfmac43455-sdio.bin /usr/lib/firmware/brcm/brcmfmac43455-sdio.clm_blob \
  /usr/lib/firmware/brcm/brcmfmac43455-sdio.pine64,pinephone-pro.txt; do
  [[ -s $path || -s $path.xz || -s $path.zst ]]
done
[[ -x /usr/bin/atinout ]]
rpm -q --whatprovides atinout
python3 "$recipe_dir/write-fresh-package-state.py" "$recipe_dir/finish-inputs.json"
printf 'FRESH_FEDORA_PHONE_PREPARATION_COMPLETE\n'
