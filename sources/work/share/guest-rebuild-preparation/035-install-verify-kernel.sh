#!/usr/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# Future fresh source-VM stage; install packages and run their real posttrans.
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export LC_ALL=C
umask 022
recipe_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
[[ $EUID == 0 && $(uname -m) == aarch64 && $(uname -r) == 7.2.9-jon-ppp ]]
source /etc/os-release
[[ $ID == fedora && $VERSION_ID == 44 ]]
[[ $(findmnt -n -o FSTYPE --target /build) == 9p ]]
[[ $(findmnt -n -o UUID --target /) == 6741cdec-fe58-4214-9fa9-3e8eaa52f476 ]]
[[ $(findmnt -n -o FSTYPE --target /) == btrfs && $(findmnt -n -o FSROOT --target /) == /root ]]
for path in /var /home /boot /boot/efi; do mountpoint -q "$path"; done
[[ $(findmnt -n -o FSROOT --target /var) == /var && $(findmnt -n -o FSROOT --target /home) == /home ]]
[[ $(findmnt -n -o FSTYPE --target /boot) == ext4 && $(findmnt -n -o FSTYPE --target /boot/efi) == vfat ]]
for package in kernel-pinephone-pro pinephone-pro-kernel-tools; do
  if rpm -q "$package"; then
    printf 'Preserve existing custom package; this recipe is fresh-install only.\n' >&2
    exit 1
  fi
done
for file in /boot/initramfs-7.2.9-jon-ppp.img /boot/efi/pinephone-pro/7.2.9-jon-ppp/initramfs.img /build/fedora-kernel-install-report.json; do
  [[ ! -e $file && ! -L $file ]]
done
python3 - <<'CHECK_REPORTS'
from pathlib import Path
import hashlib, json
build = json.loads(Path('/build/fedora-kernel-package-build-report.json').read_text())
assert build['status'] == 'kernel_release3_packages_built_verified'
assert build['kernel_release'] == '7.2.9-jon-ppp' and build['compiled_module_count'] == 906
assert build['source_rpm_identity'] == 'kernel-pinephone-pro-7.2.9-3.fc44.src.rpm'
for entry in build['files']:
    path = Path(entry['path'])
    assert path.parent == Path('/build/packaged-rpms') and path.is_file() and not path.is_symlink()
    assert path.stat().st_size == entry['size_bytes']
    with path.open('rb') as stream:
        assert hashlib.file_digest(stream, 'sha256').hexdigest() == entry['sha256']
device = json.loads(Path('/build/fedora-device-support-install-report.json').read_text())
assert device['status'] == 'device_support_built_installed_verified'
assert set(device['installed_nevras']) == {
    'eg25-manager-0.5.2-3.fc44.aarch64', 'pinephonepro-device-support-10-3.fc44.noarch'}
CHECK_REPORTS
for package in bash coreutils grep util-linux kmod dracut btrfs-progs systemd pigz python3 e2fsprogs; do
  rpm -q "$package" >/dev/null
done
[[ $(rpm -q --qf '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\n' eg25-manager) == eg25-manager-0.5.2-3.fc44.aarch64 ]]
[[ $(rpm -q --qf '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\n' pinephonepro-device-support) == pinephonepro-device-support-10-3.fc44.noarch ]]
rpm --noscripts -V eg25-manager pinephonepro-device-support
source "$recipe_dir/dracut-build-logging.sh"
cleanup() {
  local result=$?
  trap - EXIT INT TERM
  if ! ppp_logging_end; then
    printf 'Owned build logging config could not be removed; preparation incomplete.\n' >&2
    ((result != 0)) || result=1
  fi
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
ppp_logging_begin
# Every dependency was prepared earlier. Preserve signature-check defaults;
# no repository access or duplicate build-only network setup is needed here.
dnf5 --disablerepo='*' install --assumeyes \
  /build/packaged-rpms/kernel-pinephone-pro-7.2.9-3.fc44.aarch64.rpm \
  /build/packaged-rpms/pinephone-pro-kernel-tools-7.2.9-3.fc44.noarch.rpm
ppp_logging_end
printf 'FRESH_FEDORA_DRACUT_BUILD_LOGGING_REMOVED\n'
# DNF may finish even when a scriptlet fails: inspect the real resulting boot
# artifacts and run the strict installed content validator before success.
python3 "$recipe_dir/verify-installed-kernel.py" "$recipe_dir/rebuild-inputs.json"
rpmdb --verifydb
dnf5 --disablerepo='*' check
python3 - <<'FINAL_REPORT'
from pathlib import Path
import json
path = Path('/build/fedora-kernel-install-report.json')
result = json.loads(path.read_text())
assert result['status'] == 'kernel_release3_payload_and_boot_verified'
assert result['installed_module_count'] == 906 and result['modules_signed'] is True
assert result['portable_initramfs_audit_status'] == 'passed'
result['status'] = 'kernel_release3_built_installed_verified'
result['rpmdb_verify_exit'] = 0
result['dnf5_check_exit'] = 0
temporary = path.with_name(path.name + '.completed')
with temporary.open('x') as stream:
    json.dump(result, stream, indent=2, sort_keys=True); stream.write('\n')
temporary.replace(path)
FINAL_REPORT
printf 'FRESH_FEDORA_KERNEL_PREPARATION_COMPLETE\n'
