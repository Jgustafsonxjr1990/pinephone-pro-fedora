#!/usr/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# Source only from the future kernel install stage. No updater/RPM source edits.
build_logging_dropin=/etc/dracut.conf.d/zzzz-pinephone-pro-build-logging.conf
build_logging_fd=
ppp_logging_preflight() {
  python3 - "${build_logging_dropin##*/}" <<'LOGGING_PREFLIGHT'
import os
from pathlib import Path
import re, subprocess, sys
name = sys.argv[1]
controls = {'conffile', 'confdir', 'add_confdir', 'allowlocal', 'dracutbasedir',
            'dracutsysrootdir', 'sysroot_l', 'stdloglvl_l', 'maxloglvl', '__DRACUT_LOGGER__',
            'BASH_ENV', 'ENV', 'IFS', 'GLOBIGNORE'}
if any(os.environ.get(key) for key in controls):
    raise SystemExit('Nondefault inherited dracut controls prevent logging preflight')
effective = {}
for directory in (Path('/etc/dracut.conf.d'), Path('/usr/lib/dracut/dracut.conf.d')):
    if directory.is_symlink() or directory.resolve() != directory:
        raise SystemExit('Dracut configuration directory is not canonical')
    proposed = directory / name
    if proposed.exists() or proposed.is_symlink():
        raise SystemExit('Owned logging name already exists')
    if not directory.exists():
        continue
    if not directory.is_dir():
        raise SystemExit('Dracut config directory is not a directory')
    for path in directory.iterdir():
        if path.name.endswith('.conf') and (path.exists() or path.is_symlink()):
            if re.fullmatch(r'[A-Za-z0-9._+-]+[.]conf', path.name) is None:
                raise SystemExit('Dracut config basename cannot be safely sorted')
            effective.setdefault(path.name, path)
literal = re.compile(r'''\s*([A-Za-z_][A-Za-z0-9_]*)\+?=(?:'[^']*'|"[^"$`\\]*"|[A-Za-z0-9_./,:+%-]*)\s*(?:#.*)?''')
forbidden = controls | {'LANG', 'verbosity_mod_l', 'PATH', 'SHELLOPTS', 'BASHOPTS', 'CDPATH'}
for path in (Path('/etc/dracut.conf'), *effective.values()):
    if not path.exists() and not path.is_symlink():
        continue
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise SystemExit('Dracut config is not a small regular file')
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        match = literal.fullmatch(line)
        if match is None or match[1] in forbidden or match[1].startswith('LC_'):
            raise SystemExit('Dracut config cannot prove logger routing and order')
ordered = subprocess.check_output(['sort', '-Vu'],
    input=('\n'.join([*effective, name]) + '\n').encode()).decode().splitlines()
if not ordered or ordered[-1] != name:
    raise SystemExit('Owned logging config is not last in dracut sort -Vu order')
print('FRESH_FEDORA_DRACUT_LOGGING_ORDER_VERIFIED configs=' + str(len(effective)))
LOGGING_PREFLIGHT
}
ppp_logging_begin() {
  ppp_logging_preflight || return 1
  mkdir -p /etc/dracut.conf.d || return 1
  set -o noclobber
  if exec {build_logging_fd}> "$build_logging_dropin"; then
    set +o noclobber
  else
    set +o noclobber
    return 1
  fi
  printf '%s\n' 'stdloglvl=4' 'sysloglvl=0' 'kmsgloglvl=0' 'fileloglvl=0' >&"$build_logging_fd"
}
ppp_logging_end() {
  [[ -n $build_logging_fd ]] || return 0
  if [[ -L $build_logging_dropin || ! -f $build_logging_dropin ||
        ! $build_logging_dropin -ef /proc/$$/fd/$build_logging_fd ]]; then
    printf 'Owned dracut logger changed; preserve evidence and stop.\n' >&2
    return 1
  fi
  rm -- "$build_logging_dropin" || return 1
  [[ ! -e $build_logging_dropin && ! -L $build_logging_dropin ]] || return 1
  exec {build_logging_fd}>&-
  build_logging_fd=
}
