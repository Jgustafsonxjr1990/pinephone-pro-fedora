#!/usr/bin/bash
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C
[[ $EUID == 0 && $(uname -m) == aarch64 && $(uname -r) == 7.2.9-jon-ppp ]]
[[ $(findmnt -n -o UUID --target /) == 6741cdec-fe58-4214-9fa9-3e8eaa52f476 ]]
[[ $(findmnt -n -o FSTYPE --target /dev) == devtmpfs ]]
[[ $(findmnt -n -o FSTYPE --target /proc) == proc ]]
if [[ ! -e /dev/fd && ! -L /dev/fd ]]; then
  ln -s /proc/self/fd /dev/fd
fi
[[ -L /dev/fd && $(readlink /dev/fd) == /proc/self/fd && -d /dev/fd ]]
mapfile -t runtime_test < <(printf '%s\n' process-substitution-works)
[[ ${#runtime_test[@]} == 1 && ${runtime_test[0]} == process-substitution-works ]]
printf 'BUILD_RUNTIME_DEV_FD_REPAIRED_AND_VERIFIED\n'
exec bash /build/guest-rebuild-preparation/040-finish-phone.sh
