#!/usr/bin/env bash
set -euo pipefail
build_base=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
workspace_base=$(dirname -- "$build_base")
export PATH="$build_base/tools/usr/bin:$workspace_base/kernel-build/tools/usr/bin:$PATH"
export LD_LIBRARY_PATH="$workspace_base/kernel-build/tools/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
export BISON_PKGDATADIR="$workspace_base/kernel-build/tools/usr/share/bison"
export M4="$workspace_base/kernel-build/tools/usr/bin/m4"
export SWIG_LIB="$build_base/tools/usr/share/swig4.0"
export PYTHONPATH="$build_base/tools/python:${PYTHONPATH:-}"
export SOURCE_DATE_EPOCH=1791619200
export TZ=UTC
mkdir -p "$build_base/output" "$build_base/logs"

# Explicit BFD linker avoids the Debian/Ubuntu GCC-driver PMUSRAM overflow.
# Both signed upstream trees remain unmodified.
make -C "$build_base/trusted-firmware-a" -j2 \
 CROSS_COMPILE=aarch64-linux-gnu- LD=aarch64-linux-gnu-ld.bfd \
 PLAT=rk3399 bl31
bl31_path="$build_base/trusted-firmware-a/build/rk3399/release/bl31/bl31.elf"
test -s "$bl31_path"

make -C "$build_base/u-boot" CROSS_COMPILE=aarch64-linux-gnu- pinephone-pro-rk3399_defconfig
"$build_base/u-boot/scripts/config" --file "$build_base/u-boot/.config" \
 --disable ENV_IS_IN_SPI_FLASH --enable ENV_IS_NOWHERE \
 --disable ROCKCHIP_SPI_IMAGE --disable TOOLS_MKEFICAPSULE
# scripts/config's sed replacement does not escape ampersands in strings.
python3 - "$build_base/u-boot/.config" <<'PY'
from pathlib import Path
import sys
config_path = Path(sys.argv[1])
lines = config_path.read_text().splitlines()
replacement = 'CONFIG_BOOTCOMMAND="bootmeth order extlinux && bootflow scan -lb"'
assert sum(line.startswith('CONFIG_BOOTCOMMAND=') for line in lines) == 1
config_path.write_text('\n'.join(replacement if line.startswith('CONFIG_BOOTCOMMAND=') else line for line in lines) + '\n')
PY
make -C "$build_base/u-boot" CROSS_COMPILE=aarch64-linux-gnu- olddefconfig
make -C "$build_base/u-boot" -j2 CROSS_COMPILE=aarch64-linux-gnu- BL31="$bl31_path" \
 HOSTCFLAGS="-O2 -I$workspace_base/kernel-build/tools/usr/include" \
 HOSTLDFLAGS="-L$workspace_base/kernel-build/tools/usr/lib/x86_64-linux-gnu"

for artifact in u-boot-rockchip.bin idbloader.img u-boot.itb u-boot.bin u-boot.dtb; do
 cp "$build_base/u-boot/$artifact" "$build_base/output/$artifact"
done
cp "$bl31_path" "$build_base/output/bl31.elf"
cp "$build_base/u-boot/.config" "$build_base/output/u-boot.config"
cp "$build_base/u-boot/simple-bin.map" "$build_base/output/u-boot-rockchip.map"
printf '%s\n' 'Built eMMC/SD user-area loader only; no device or SPI writes were performed.'
