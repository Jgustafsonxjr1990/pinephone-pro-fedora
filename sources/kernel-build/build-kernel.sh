#!/usr/bin/env bash
set -euo pipefail
build_base=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
export PATH="$build_base/tools/usr/bin:$PATH"
export LD_LIBRARY_PATH="$build_base/tools/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
export BISON_PKGDATADIR="$build_base/tools/usr/share/bison"
export M4="$build_base/tools/usr/bin/m4"
export KBUILD_BUILD_USER=jon
export KBUILD_BUILD_HOST=pinephone-pro-image-builder
export KBUILD_BUILD_TIMESTAMP='Sat Oct 10 08:00:00 UTC 2026'
cd "$build_base/linux-7.2.9"
cp "$build_base/sources/config-pine64-pinephonepro.aarch64" .config
scripts/kconfig/merge_config.sh -m .config "$build_base/fedora-security.config"
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- \
 HOSTCFLAGS="-O2 -I$build_base/tools/usr/include" \
 HOSTLDFLAGS="-L$build_base/tools/usr/lib/x86_64-linux-gnu" olddefconfig
for required in CONFIG_SECURITY_SELINUX=y CONFIG_SECURITY_NETWORK=y CONFIG_EXT4_FS_SECURITY=y CONFIG_MMC_DW_ROCKCHIP=y CONFIG_DRM_ROCKCHIP=y CONFIG_CHARGER_RK818=y; do
  if ! grep -qx -- "$required" .config; then
    printf 'Required config missing: %s\n' "$required" >&2
    exit 1
  fi
done
cp .config "$build_base/output/config-7.2.9-jon-ppp"
make -j4 ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- \
 HOSTCFLAGS="-O2 -I$build_base/tools/usr/include" \
 HOSTLDFLAGS="-L$build_base/tools/usr/lib/x86_64-linux-gnu" \
 Image modules rockchip/rk3399-pinephone-pro.dtb
# Keep the final DTB synchronized when platform integration changes during compilation.
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- rockchip/rk3399-pinephone-pro.dtb
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- \
 INSTALL_MOD_PATH="$build_base/output/modules-root" \
 INSTALL_MOD_STRIP=1 DEPMOD=true modules_install
cp arch/arm64/boot/Image "$build_base/output/Image-7.2.9-jon-ppp"
cp arch/arm64/boot/dts/rockchip/rk3399-pinephone-pro.dtb "$build_base/output/rk3399-pinephone-pro.dtb"
cp System.map "$build_base/output/System.map-7.2.9-jon-ppp"
make -s ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- kernelrelease > "$build_base/output/kernelrelease"
release=$(cat "$build_base/output/kernelrelease")
# Build-directory symlinks are irrelevant on the phone; source is provided separately.
rm -f -- "$build_base/output/modules-root/lib/modules/$release/build" \
 "$build_base/output/modules-root/lib/modules/$release/source"
depmod -b "$build_base/output/modules-root" "$release"
printf 'Built matching Image, modules, PPP DTB, config and System.map.\n'
