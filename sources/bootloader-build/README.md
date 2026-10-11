# PinePhone Pro eMMC/SD bootloader build

Built October 10, 2026 from unmodified signed upstream trees:

- U-Boot **2026.10**, commit `5508406582f6f7120dce0c4b3059819a41788db2`.
- Trusted Firmware-A **2.15.0**, commit `da738d5eae93af342fdc4995dd3c05acb4c9d757`, platform `rk3399`.

The final merged loader is `output/u-boot-rockchip.bin`, 9,524,224 bytes.
SHA256: `8665b27f27b9caad6976e49c7fd800342726d4d627f95672dad798f6e048b000`.

## Disk image placement

This is a loader for the eMMC **user area**, with the same format supported on SD.
It is not a SPI image or an eMMC boot-partition image.

| Component | Offset within merged binary | Offset within final disk image |
| --- | ---: | ---: |
| RK3399 ID block, LPDDR4 TPL, SPL | 0 | 32,768 bytes, sector 64 |
| FIT containing U-Boot, TF-A and PPP bootloader DTB | 8,355,840 bytes (`0x7f8000`) | 8,388,608 bytes, sector 16,384 |
| End of merged loader | 9,524,224 bytes | 9,556,992 bytes |

The final image's first partition must start beyond the end of this loader.
A 32 MiB pre-partition gap leaves ample space and keeps the ordinary GPT
metadata before sector 64. The merged file includes its own padding; do not
write the FIT a second time when embedding the merged binary.

The RK3399 BootROM searches SPI first. If existing SPI firmware is active, it
normally loads the operating system from the image's boot partition and the
embedded loader is unused. The embedded mainline loader provides a separate
boot chain if SPI is absent or bypassed. This build does not modify SPI.

## Boot configuration

The upstream `pinephone-pro-rk3399_defconfig` enables LPDDR4 training through
U-Boot TPL, both eMMC/SD controllers, extlinux, FAT/ext filesystems, ARM64 `booti`
and EFI. The compiled environment contains:

| Variable | Value |
| --- | --- |
| `kernel_addr_r` | `0x02000000` |
| `fdt_addr_r` | `0x12000000` |
| `ramdisk_addr_r` | `0x12180000` |
| `fdtfile` | `rockchip/rk3399-pinephone-pro.dtb` |
| `boot_targets` | `mmc1 mmc0 nvme scsi usb pxe dhcp spi` |

Older Tow-Boot/rk2aw configurations can use different load addresses. Use
an explicit kernel-matching DTB in extlinux, and retain the kernel size check
for compatibility with those existing SPI bootloaders.

Four configuration changes from the upstream defconfig were applied:

- Disable `ENV_IS_IN_SPI_FLASH`, enable `ENV_IS_NOWHERE`: use the compiled
  defaults without reading or saving persistent SPI environment data.
- Disable `ROCKCHIP_SPI_IMAGE`: produce only the eMMC/SD merged loader.
- Disable `TOOLS_MKEFICAPSULE`: omit an unused host utility; normal runtime EFI
  and extlinux boot remain enabled.
- Set `BOOTCOMMAND` to `bootmeth order extlinux && bootflow scan -lb`: automatic
  boot selects only the PPP extlinux path. This prevents the global EFI boot
  manager from choosing a generic Fedora ARM kernel before extlinux. EFI remains
  available for explicit use. The verified Hush command separator stops scanning
  if setting the method order fails.

Optional OP-TEE is omitted. Binman explicitly reports the resulting image is
functional without it. The mainline defconfig does not enable USB gadget,
Tow-Boot volume-button USB storage mode, or its phone-specific graphical
firmware interface. Future USB flashing must use the actual inspected SPI
firmware or a separately verified recovery loader.

## Verification and provenance

`verify-bootloader.py` decoded the RK3399 BootROM ID-block header, checked the
`RK33` marker, compared both component files with their bytes inside the merged
image, verified all seven FIT payload SHA256 hashes, checked the PPP DTB's
compatibility strings, and inspected the compiled configuration/environment.
The detailed results are in `output/verification.json`.

Both annotated release tag signatures verify cryptographically. Signer
fingerprints, public-key retrieval URLs, pinned commits, generated source
archive hashes and build options are in `source-manifest.json`. Verification
logs and signed tag text are retained in `logs/` and `sources/`.

TF-A was built with the explicit upstream `LD=aarch64-linux-gnu-ld.bfd` option.
This avoids the Debian/Ubuntu GCC-driver PMUSRAM overflow described in Debian
bug 1118651 without modifying TF-A source or increasing hardware memory limits.
The linked PMUSRAM payload is 8,024 bytes within the 8,192-byte reserved region.

`build-bootloader.sh` records the build commands and uses at most two jobs.
It reuses the neighboring kernel build's private AArch64 tools. Additional
private tools are Ubuntu `gcc-arm-none-eabi` 13.2.rel1, binutils 2.42, SWIG 4.2,
and pyelftools 0.33. Source trees and tools must be present before rerunning it.

No physical phone boot, peripheral test, SPI write, or device write occurred.
Successful compilation and file checks establish the artifact's structure;
PinePhone Pro boot/display/suspend behavior still requires physical validation.

## Primary references

- https://docs.u-boot.org/en/stable/board/rockchip/rockchip.html
- https://docs.u-boot.org/en/stable/develop/distro.html
- https://pine64.org/documentation/General/RK3399_boot_sequence/
- https://pine64.org/documentation/PinePhone_Pro/Software/Multi-distribution_image/
- https://www.trustedfirmware.org/blog/tf-a-v2_15/
- https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=1118651
