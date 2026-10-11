#!/usr/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# Future guest stage only; no kernel compilation or hardware operation.
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export LC_ALL=C
umask 022
[[ $EUID == 0 && $(uname -m) == aarch64 && $(uname -r) == 7.2.9-jon-ppp ]]
source /etc/os-release
[[ $ID == fedora && $VERSION_ID == 44 ]]
report=/build/fedora-native-compiler-report.json
[[ ! -e $report && ! -L $report ]]
for variable in GCC_EXEC_PREFIX COMPILER_PATH LIBRARY_PATH; do
  [[ -z ${!variable-} ]] || { printf 'Unexpected compiler control: %s\n' "$variable" >&2; exit 1; }
done
rpm --noscripts -V gcc cpp glibc
cc1=$(gcc -print-prog-name=cc1)
[[ $cc1 == /* && -f $cc1 && -x $cc1 ]]
fixture=$(mktemp -d /tmp/ppp-native-compiler.XXXXXXXX)
cleanup() { local result=$?; trap - EXIT INT TERM; rm -rf -- "$fixture" || result=1; exit "$result"; }
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
cat > "$fixture/smoke.c" <<'C_SOURCE'
#include <stdio.h>
int main(void) { return puts("FRESH_FEDORA_NATIVE_ARM_PROGRAM_OK") < 0; }
C_SOURCE
gcc -O2 -Wall -Wextra -Werror "$fixture/smoke.c" -o "$fixture/smoke"
python3 - "$fixture/smoke" <<'ELF_CHECK'
from pathlib import Path
import struct, sys
header = Path(sys.argv[1]).read_bytes()[:64]
assert header[:6] == b'\x7fELF\x02\x01' and struct.unpack_from('<H', header, 18)[0] == 183
ELF_CHECK
[[ $("$fixture/smoke") == FRESH_FEDORA_NATIVE_ARM_PROGRAM_OK ]]
python3 - "$report" "$cc1" "$fixture/smoke.c" "$fixture/smoke" <<'SAVE_REPORT'
import hashlib, json, os, subprocess, sys
from pathlib import Path
report, cc1, source, program = map(Path, sys.argv[1:])
value = {'status': 'native_arm_compiler_smoke_passed', 'architecture': 'aarch64',
         'gcc_version': subprocess.check_output(['gcc', '--version'], text=True).splitlines()[0],
         'compiler_packages': subprocess.check_output(['rpm', '-q', 'gcc', 'cpp', 'glibc'], text=True).splitlines(),
         'cc1': str(cc1), 'PATH': os.environ['PATH'],
         'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
         'program_sha256': hashlib.sha256(program.read_bytes()).hexdigest(),
         'program_marker': 'FRESH_FEDORA_NATIVE_ARM_PROGRAM_OK'}
with report.open('x') as stream:
    json.dump(value, stream, indent=2, sort_keys=True); stream.write('\n')
SAVE_REPORT
printf 'FRESH_FEDORA_COMPILER_SMOKE_PASSED\n'
