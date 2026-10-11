#!/usr/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# Run inside the fresh Fedora source VM, where GNU cpio/gzip/pigz are installed.
# Writes only its disposable mktemp directory; never extracts CPIO contents.
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export LC_ALL=C
[[ $# -eq 1 ]] || { printf '%s\n' 'usage: native-fixtures.sh VALIDATOR'; exit 1; }
validator=$(realpath "$1")
[[ -f $validator && ! -L $validator ]] || exit 1
for program in python3 find sort cpio gzip pigz sha256sum mktemp; do command -v "$program" >/dev/null; done
cpio --version | grep -q 'GNU cpio'
before=$(sha256sum "$validator" | awk '{print $1}')
fixture=$(mktemp -d /tmp/ppp-portability-native.XXXXXXXX)
cleanup() { rm -rf -- "$fixture"; }
trap cleanup EXIT
mkdir -p "$fixture/main/etc/cmdline.d" "$fixture/early"
printf '%s\n' '#!/bin/sh' 'exit 0' > "$fixture/main/init"
chmod 0755 "$fixture/main/init"
printf ' rd.driver.pre=btrfs\n' > "$fixture/main/etc/cmdline.d/00-btrfs.conf"
: > "$fixture/main/etc/machine-id"
printf '1' > "$fixture/early/early_cpio"
for format in newc crc; do
  (cd "$fixture/main"; find . -print0 | sort -z | cpio --null --create --format="$format" --quiet) > "$fixture/main-$format.cpio"
  for compressor in gzip pigz; do
    "$compressor" -c "$fixture/main-$format.cpio" > "$fixture/$format-$compressor.img"
    python3 "$validator" "$fixture/$format-$compressor.img" --audit-json "$fixture/$format-$compressor.json"
  done
done
(cd "$fixture/early"; find . -print0 | sort -z | cpio --null --create --format=newc --quiet) > "$fixture/early.cpio"
cat "$fixture/early.cpio" "$fixture/newc-pigz.img" > "$fixture/early-gzip.img"
python3 "$validator" "$fixture/early-gzip.img" --audit-json "$fixture/early-gzip.json"
printf 'root=/dev/vda3\n' > "$fixture/main/etc/cmdline.d/95root-dev.conf"
(cd "$fixture/main"; find . -print0 | sort -z | cpio --null --create --format=newc --quiet) |
  gzip -c > "$fixture/negative.img"
if python3 "$validator" "$fixture/negative.img" --audit-json "$fixture/negative.json"; then
  printf '%s\n' 'FRESH_NATIVE_NEGATIVE_UNEXPECTEDLY_PASSED'; exit 1
fi
python3 - "$fixture" <<'PY'
import json
from pathlib import Path
import sys
root = Path(sys.argv[1])
for variant in ('newc-gzip','newc-pigz','crc-gzip','crc-pigz','early-gzip'):
    result = json.loads((root / (variant + '.json')).read_text())
    assert result['status'] == 'passed' and result['gzip_streams'] == 1
    assert result['cpio_containers'] == (2 if variant == 'early-gzip' else 1)
    entries = {entry['name']: entry for entry in result['protected_entries']}
    assert entries['etc/cmdline.d/00-btrfs.conf']['exact_generic_btrfs'] is True
    assert entries['etc/cmdline.d/00-btrfs.conf']['size'] == 21
    assert entries['etc/machine-id']['size'] == 0
result = json.loads((root / 'negative.json').read_text())
assert result['status'] == 'failed' and result['reason'] == 'unexpected_protected_field'
PY
after=$(sha256sum "$validator" | awk '{print $1}')
[[ $before == "$after" ]] || exit 1
# Keep the six actual GNU archive audits before disposable fixture cleanup.
python3 - "$fixture" "$validator" "$after" <<'SAVE_NATIVE_AUDITS'
from pathlib import Path
import hashlib, json, subprocess, sys
fixture, validator, sha = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
destination = Path('/build/fedora-native-portability-audits')
if destination.resolve() != destination or destination.exists():
    raise SystemExit('Preserve existing native audits; use a fresh verified destination')
destination.mkdir(mode=0o755)
results = []
for name in ('newc-gzip','newc-pigz','crc-gzip','crc-pigz','early-gzip','negative'):
    raw = (fixture / (name + '.json')).read_bytes()
    parsed = json.loads(raw)
    expected = 'failed' if name == 'negative' else 'passed'
    assert parsed['status'] == expected
    (destination / (name + '.json')).write_bytes(raw)
    results.append({'name': name, 'status': parsed['status'], 'sha256': hashlib.sha256(raw).hexdigest()})
result = {'status': 'six_actual_GNU_archive_fixtures_passed', 'fixture_count': 6,
          'validator_path': str(validator), 'validator_sha256': sha, 'audits': results,
          'versions': {p: subprocess.check_output([p, '--version'], text=True).splitlines()[0]
                       for p in ('cpio', 'gzip', 'pigz')}}
(destination / 'summary.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
SAVE_NATIVE_AUDITS
printf 'FRESH_FEDORA_NATIVE_PORTABILITY_FIXTURES_PASSED count=6 validator_sha256=%s\n' "$after"
