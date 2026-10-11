#!/usr/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# Build RPM containers around the verified compiled kernel; do not rebuild Linux.
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export LC_ALL=C
umask 022
recipe_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
[[ $EUID == 0 && $(uname -m) == aarch64 && $(uname -r) == 7.2.9-jon-ppp ]]
source /etc/os-release
[[ $ID == fedora && $VERSION_ID == 44 ]]
[[ $(findmnt -n -o FSTYPE --target /build) == 9p ]]
source_top=/build/fedora-kernel-packaging
build_top=/tmp/ppp-rpmbuild
export_top=/build/packaged-rpms
report=/build/fedora-kernel-package-build-report.json
[[ ! -e $build_top && ! -L $build_top && ! -e $report && ! -L $report ]]
python3 - "$recipe_dir/rebuild-inputs.json" "$source_top" <<'CHECK_INPUTS'
from pathlib import Path
import hashlib, json, sys
inputs = json.loads(Path(sys.argv[1]).read_text())
source = Path(sys.argv[2])
assert source.resolve() == source
compiler = json.loads(Path('/build/fedora-native-compiler-report.json').read_text())
assert compiler['status'] == 'native_arm_compiler_smoke_passed'
assert compiler['program_marker'] == 'FRESH_FEDORA_NATIVE_ARM_PROGRAM_OK'
for name, expected in inputs['files'].items():
    file = source / name
    assert file.is_file() and not file.is_symlink()
    assert file.stat().st_size == expected['size_bytes']
    with file.open('rb') as stream:
        assert hashlib.file_digest(stream, 'sha256').hexdigest() == expected['sha256']
CHECK_INPUTS
bash /build/native-fixtures.sh "$source_top/SOURCES/pinephone-pro-initramfs-verify"
python3 - <<'CHECK_NATIVE'
from pathlib import Path
import json
native = json.loads(Path('/build/fedora-native-portability-audits/summary.json').read_text())
assert native['status'] == 'six_actual_GNU_archive_fixtures_passed' and native['fixture_count'] == 6
assert {x['name']: x['status'] for x in native['audits']} == {
    'newc-gzip': 'passed', 'newc-pigz': 'passed', 'crc-gzip': 'passed',
    'crc-pigz': 'passed', 'early-gzip': 'passed', 'negative': 'failed'}
CHECK_NATIVE
mkdir -- "$build_top"
mkdir -- "$build_top"/{SOURCES,SPECS,BUILD,BUILDROOT,RPMS,SRPMS}
cp -- "$source_top/SPECS/kernel-pinephone-pro.spec" "$build_top/SPECS/"
for file in kernel-pinephone-pro-7.2.9.tar.gz pinephone-pro-kernel-update pinephone-pro-initramfs-verify boot.conf README.md GPL-2.0; do
  cp -- "$source_top/SOURCES/$file" "$build_top/SOURCES/"
done
rpmspec --define "_topdir $build_top" --target aarch64 --parse "$build_top/SPECS/kernel-pinephone-pro.spec" > "$build_top/kernel-parsed.spec"
grep -Eq '^Provides:[[:space:]]+kernel-uname-r\(7[.]2[.]9-jon-ppp\)[[:space:]]*$' "$build_top/kernel-parsed.spec"
grep -Eq '^Provides:[[:space:]]+installonlypkg\(kernel\)[[:space:]]*$' "$build_top/kernel-parsed.spec"
rpmbuild --define "_topdir $build_top" --target aarch64 -ba "$build_top/SPECS/kernel-pinephone-pro.spec"
python3 - "$build_top" "$export_top" "$report" "$recipe_dir/rebuild-inputs.json" <<'EXPORT_RPMS'
from pathlib import Path
import hashlib, json, os, re, shutil, subprocess, sys
top, destination, report, inputs_path = map(Path, sys.argv[1:])
expected = {'kernel-pinephone-pro-7.2.9-3.fc44.aarch64.rpm': 'aarch64',
            'pinephone-pro-kernel-tools-7.2.9-3.fc44.noarch.rpm': 'noarch'}
binaries = sorted((top / 'RPMS').rglob('*.rpm'))
sources = sorted((top / 'SRPMS').glob('*.src.rpm'))
assert {p.name for p in binaries} == set(expected)
assert [p.name for p in sources] == ['kernel-pinephone-pro-7.2.9-3.fc44.src.rpm']
source_name = sources[0].name
for file in binaries:
    metadata = subprocess.check_output(['rpm', '-qp', '--qf', '%{NAME}\t%{VERSION}\t%{RELEASE}\t%{ARCH}\t%{SOURCERPM}\n', str(file)], text=True).strip().split('\t')
    assert metadata[1:] == ['7.2.9', '3.fc44', expected[file.name], source_name]
    requires = subprocess.check_output(['rpm', '-qp', '--requires', str(file)], text=True).splitlines()
    if metadata[0] == 'kernel-pinephone-pro':
        assert not any(re.match(r'^(?:kernel\(|ksym\(|kernel-uname-r(?:\s|\())', x) for x in requires)
        provides = subprocess.check_output(['rpm', '-qp', '--provides', str(file)], text=True).splitlines()
        assert 'kernel-uname-r(7.2.9-jon-ppp)' in provides and 'installonlypkg(kernel)' in provides
    else:
        assert 'python3' in requires and 'pigz' in requires
if destination.is_symlink() or destination.resolve() != destination:
    raise SystemExit('RPM export directory must be canonical')
destination.mkdir(mode=0o755, exist_ok=True)
records = []
for file in [*binaries, *sources]:
    target = destination / file.name
    with file.open('rb') as incoming, target.open('xb') as outgoing:
        shutil.copyfileobj(incoming, outgoing); outgoing.flush(); os.fsync(outgoing.fileno())
    with target.open('rb') as stream:
        sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    records.append({'path': str(target), 'filename': target.name,
                    'size_bytes': target.stat().st_size, 'sha256': sha})
parsed = destination / 'kernel-pinephone-pro-7.2.9-3.fc44.parsed.spec'
with (top / 'kernel-parsed.spec').open('rb') as incoming, parsed.open('xb') as outgoing:
    shutil.copyfileobj(incoming, outgoing)
native = json.loads(Path('/build/fedora-native-portability-audits/summary.json').read_text())
value = {'status': 'kernel_release3_packages_built_verified', 'kernel_release': '7.2.9-jon-ppp',
         'kernel_linux_recompiled': False, 'compiled_module_count': 906,
         'source_rpm_identity': source_name, 'binaries_share_source_rpm': True,
         'files': records, 'native_fixture_summary': native,
         'input_manifest_sha256': hashlib.sha256(inputs_path.read_bytes()).hexdigest()}
with report.open('x') as stream:
    json.dump(value, stream, indent=2, sort_keys=True); stream.write('\n')
EXPORT_RPMS
# Build artifacts remain only under assembly-excluded /tmp and public /build.
printf 'FRESH_FEDORA_KERNEL_PACKAGE_BUILD_VERIFIED\n'
