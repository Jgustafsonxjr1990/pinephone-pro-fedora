#!/usr/bin/bash
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C
[[ $EUID == 0 && $(uname -m) == aarch64 && $(uname -r) == 7.2.9-jon-ppp ]]
source /etc/os-release
[[ $ID == fedora && $VERSION_ID == 44 ]]
[[ $(findmnt -n -o UUID --target /) == 6741cdec-fe58-4214-9fa9-3e8eaa52f476 ]]
rpm -q plasma-setup
[[ ! -e /etc/plasma-setup-done ]]
[[ $(passwd -S root | awk '{print $2}') == L ]]
[[ -z $(awk -F: '$3 >= 1000 && $3 < 65534 {print $1}' /etc/passwd) ]]
getent passwd plasma-setup
[[ -s /usr/share/wayland-sessions/plasma.desktop ]]
[[ -s /usr/share/wayland-sessions/plasma-mobile.desktop ]]
state=$(systemctl --root=/ is-enabled plasma-setup.service || true)
case "$state" in
  enabled) ;;
  disabled) systemctl --root=/ enable plasma-setup.service ;;
  *) printf 'Unexpected Plasma Setup state: %s\n' "$state" >&2; exit 1 ;;
esac
[[ $(systemctl --root=/ is-enabled plasma-setup.service) == enabled ]]
[[ $(systemctl --root=/ get-default) == graphical.target ]]
printf 'FRESH_FEDORA_FIRST_USER_SETUP_VERIFIED\n'
