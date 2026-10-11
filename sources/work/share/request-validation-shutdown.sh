#!/bin/bash
# Return a receipt before the isolated VM begins its clean shutdown.
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
[[ $# == 1 && ( $1 == systemd || $1 == offline ) ]]
mode=$1
if [[ $mode == systemd ]]; then
  [[ $(readlink -f /proc/1/exe) == /usr/lib/systemd/systemd ]]
else
  [[ $(readlink -f /proc/1/exe) == /usr/bin/bash ]]
fi
(
  sleep 2
  if [[ $mode == systemd ]]; then
    exec systemctl poweroff
  else
    exec bash /build/shutdown-offline-validation.sh
  fi
) > "/build/validation-$mode-shutdown.log" 2>&1 &
printf 'VALIDATION_CLEAN_SHUTDOWN_REQUESTED mode=%s\n' "$mode"
