# Source only in the isolated build VM PID1 shell after final image checks.
reexec_build_shell() {
  [[ $$ == 1 && $EUID == 0 && $(uname -m) == aarch64 ]] || return 1
  [[ $(findmnt -n -o UUID --target /) == 6741cdec-fe58-4214-9fa9-3e8eaa52f476 ]] || return 1
  [[ $(cat /proc/138/comm) == systemd-udevd ]] || return 1
  [[ $(findmnt -n -o FSTYPE --target /build) == 9p ]] || return 1
  kill -TERM 138 || return 1
  trap 'exec /usr/bin/bash --noprofile --norc -i' USR1
  (sleep 3; kill -USR1 1) > /build/build-shell-reexec.log 2>&1 < /dev/null &
  printf 'BUILD_PID1_REEXEC_REQUESTED\n'
}
reexec_build_shell
