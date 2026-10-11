#!/usr/bin/env bash
set -euo pipefail
build_base=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
export PATH="$build_base/tools/usr/bin:$PATH"
export LD_LIBRARY_PATH="$build_base/tools/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
cd "$build_base/linux-7.2.9"
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- rockchip/rk3399-pinephone-pro.dtb
release=$(make -s ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- kernelrelease)
cp arch/arm64/boot/Image "$build_base/output/Image-$release"
cp arch/arm64/boot/dts/rockchip/rk3399-pinephone-pro.dtb "$build_base/output/rk3399-pinephone-pro.dtb"
cp .config "$build_base/output/config-$release"
cp System.map "$build_base/output/System.map-$release"
printf '%s\n' "$release" > "$build_base/output/kernelrelease"
rm -f -- "$build_base/output/modules-root/lib/modules/$release/build" \
 "$build_base/output/modules-root/lib/modules/$release/source"
depmod -b "$build_base/output/modules-root" "$release"
python3 "$build_base/verify-kernel.py"
