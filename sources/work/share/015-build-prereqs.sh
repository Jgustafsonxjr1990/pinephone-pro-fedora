#!/usr/bin/bash
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export LC_ALL=C
[[ $EUID == 0 && $(uname -m) == aarch64 && $(uname -r) == 7.2.9-jon-ppp ]]
source /build/live-build-network.sh
dnf5 --setopt=sslcacert=/run/ppp-build-ca-bundle.pem --setopt=proxy_sslcacert=/run/ppp-build-ca-bundle.pem install --assumeyes rpm-build gcc meson ninja-build pkgconf-pkg-config glib2-devel libgudev-devel libgpiod-devel libusb1-devel libcurl-devel ModemManager-glib-devel systemd-rpm-macros scdoc cpio gzip pigz python3 rsync dosfstools e2fsprogs cloud-utils-growpart gdisk btrfs-progs policycoreutils
printf 'FRESH_FEDORA_BUILD_PREREQS_VERIFIED\n'
