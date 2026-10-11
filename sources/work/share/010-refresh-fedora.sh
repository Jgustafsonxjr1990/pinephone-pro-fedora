#!/usr/bin/bash
# Fresh rebuild only: signed Fedora package refresh inside the disposable VM.
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export LC_ALL=C
trap 'ppp_stage_exit=$?; printf "FRESH_REFRESH_EXIT=%s LINE=%s\n" "$ppp_stage_exit" "$LINENO"' EXIT
[[ $EUID == 0 && $(uname -m) == aarch64 && $(uname -r) == 7.2.9-jon-ppp ]]
source /etc/os-release
[[ $ID == fedora && $VERSION_ID == 44 ]]
[[ $(findmnt -n -o UUID --target /) == 6741cdec-fe58-4214-9fa9-3e8eaa52f476 && $(findmnt -n -o FSTYPE --target /) == btrfs && $(findmnt -n -o FSROOT --target /) == /root ]]
source /build/live-build-network.sh
dnf_build() {
  dnf5 --setopt=sslcacert=/run/ppp-build-ca-bundle.pem \
    --setopt=proxy_sslcacert=/run/ppp-build-ca-bundle.pem "$@"
}
printf 'FRESH_FEDORA_REFRESH_STARTED UTC=%s\n' "$(date -u +%FT%TZ)"
printf 'FRESH_RPMDB_VERIFY_STARTED\n'
rpmdb --verifydb
printf 'FRESH_RPMDB_VERIFY_PASSED\n'
dnf_build --disablerepo='*' check
printf 'FRESH_SIGNED_UPGRADE_STARTED\n'
dnf_build --refresh upgrade --assumeyes
printf 'FRESH_RPMDB_VERIFY_STARTED\n'
rpmdb --verifydb
printf 'FRESH_RPMDB_VERIFY_PASSED\n'
dnf_build --disablerepo='*' check
dnf_build --refresh check-upgrade > /build/fedora-fresh-check-upgrade.txt
printf 'FRESH_FEDORA_UPDATE_VERIFIED UTC=%s\n' "$(date -u +%FT%TZ)"
