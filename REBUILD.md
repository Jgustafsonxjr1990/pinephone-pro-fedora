# Sources and reconstruction

The release source asset is `pinephone-pro-fedora-sources-20261011.tar.zst`. Verify it against the release checksums before extraction. Its member inventory and component manifests identify the provided inputs; the matching source RPMs accompany the custom binary RPMs.

This is a reconstruction kit and a record of the tested build, **not a one-command reproducible image builder**. Some recipes originated in an earlier build environment. Historical checkpoints describe their own stage, not the final release status. Adapt toolchain locations and isolated VM paths, and inspect dependencies before running scripts. Do not run historical host/device helpers as installation instructions.

## What was built

The base was `Fedora-KDE-Mobile-Disk-44-1.7.aarch64.raw.xz`, authenticated against Fedora's signed checksum manifest. The guest was updated through Fedora repositories, then received locally built device packages and RPMs packaging the retained compiled kernel. Kernel RPM packaging on the final builder did **not** recompile Linux.

| Input | Recorded version or immutable revision |
| --- | --- |
| Fedora base | 44-1.7, KDE Mobile Disk, aarch64 |
| Linux | 7.2.9, release `7.2.9-jon-ppp` |
| postmarketOS PinePhone Pro patches/configuration | pmaports `4b5d202c15567da82a2bcb2d580ec0845e63c1d5` |
| DanctNIX modem DT adaptation | `6a38917f6664eb490f4d02d524c926cc9c2c0c93` |
| U-Boot | 2026.10, `5508406582f6f7120dce0c4b3059819a41788db2` |
| Trusted Firmware-A | 2.15.0, `da738d5eae93af342fdc4995dd3c05acb4c9d757` |
| eg25-manager | 0.5.2, `2d8a19bfd7a4575489f1cb5adab042ad49ffec88` |
| feedbackd device theme | `2f9d81c968764f8f640f20b96be2d1777027e089` |
| Supplemental Bluetooth firmware | RPi-Distro/bluez-firmware `6851250bf9d51ff50e3c5b2cf2111e2419d4335b` |
| atinout | 0.9.1 |

The five custom binary packages are `kernel-pinephone-pro-7.2.9-3.fc44`, `pinephone-pro-kernel-tools-7.2.9-3.fc44`, `pinephonepro-device-support-10-3.fc44`, `eg25-manager-0.5.2-3.fc44`, and `atinout-pinephonepro-0.9.1-3.fc44`. The two kernel packages share `kernel-pinephone-pro-7.2.9-3.fc44.src.rpm`. The kernel SRPM packages compiled payloads; rebuilding it alone does not compile the kernel sources.

## Reconstruction sequence

1. **Authenticate the base and upstream inputs.** Obtain the [Fedora 44 base](https://download.fedoraproject.org/pub/fedora/linux/releases/44/Spins/aarch64/images/Fedora-KDE-Mobile-Disk-44-1.7.aarch64.raw.xz), [signed checksum manifest](https://dl.fedoraproject.org/pub/fedora/linux/releases/44/Spins/aarch64/images/Fedora-Spins-44-1.7-aarch64-CHECKSUM) and Fedora release keys. Check the manifest signature using an independently authenticated key, then the base hash. The recorded Fedora signer fingerprint is `36F612DCF27F7D1A48A835E4DBFCF71C6D9F90A6`; the compressed base hash is `e09f24daa40d2e0e1331dddd28e6af4e97784fea87005fb74759523dce6a475a`.
2. **Rebuild the matching kernel when required.** Start with `kernel-build/source-manifest.json`, `README-kernel.md`, `prepare-kernel-source.py`, `build-kernel.sh` and `verify-kernel.py`. Source preparation applies 89 pmaports patches plus `0091-fedora-eg25-manager-dts.patch`; one obsolete Wi-Fi interrupt patch is explicitly skipped. Preserve the Fedora security configuration, matching DTB and complete module tree. The recipes assume an AArch64 GCC/binutils cross-toolchain and extracted host tools that must be supplied or their paths adapted. A new build needs its own module-signing key; no private signing key is distributed.
3. **Rebuild the bootloader if changing it.** Follow `bootloader-build/source-manifest.json` and `build-bootloader.sh`. Build TF-A for `rk3399` with the recorded BFD linker option, then U-Boot's PinePhone Pro configuration. Preserve the extlinux-only automatic boot command, nonpersistent environment, and disabled SPI-image output. This release embeds the merged 9,524,224-byte loader at byte 32,768 within the eMMC image. Its first partition starts at 32 MiB. Optional OP-TEE is absent. The embedded mainline loader does not itself provide Tow-Boot's volume-button USB flashing interface.
4. **Prepare a Fedora 44 ARM64 build guest.** Use an isolated VM with its source filesystems correctly mounted and a shared build directory. Resolve Fedora build dependencies, compile the device packages from `work/share/device-support-rebuild/`, and package/install the coherent kernel payload through `work/share/fedora-kernel-packaging/`. Its companion guest recipes and manifests document the actual inputs. Replace any environment-specific network bootstrap with your own ordinary trusted repository access; no build-network credentials are supplied.
5. **Assemble a new disposable disk.** `work/share/image-assembly/assemble-fedora-ppp.sh` expects source `/dev/vda` and a separate empty 14 GiB VirtIO target `/dev/vdb`. Those are VM-only assumptions, not host disk suggestions. It copies the Btrfs source into the final ext4 layout, installs matching boot files and resets machine/account identity. Apply the final recorded first-boot corrections: empty `/etc/machine-id`, remove the inherited `/etc/repart.d/50-root.conf`, and use raw `findmnt -rn -o MAJ:MIN` output in the root-growth device lookup. Embed and verify the loader only after the VM stops.
6. **Repeat verification before distribution.** Check GPT/loader bounds, all filesystems, portable initramfs contents and matching kernel/DTB/modules. Boot the final image with normal systemd in a headless ARM64 VM. Test growth using a disposable 16 GiB overlay backed by the 14 GiB image, then cleanly stop it and check the grown filesystems offline. These tests must not write to the release image. Finally compress, decode the complete stream again, and record raw/compressed sizes and hashes. Physical phone testing remains a separate step.

## Reproducibility limits

The kit preserves source provenance, configuration and recipes, but does not pin every Fedora repository snapshot or supply the original extracted toolchain installation. Fedora package updates, filesystem UUIDs/timestamps, RPM metadata and newly generated signing keys can change output bytes. A fresh end-to-end rebuild from the public kit has not been demonstrated to reproduce the published image hash.

Device-support release 3 uses newly fetched pinned inputs; it is not a claim to have recovered every byte of an older lost release. The release evidence identifies those replacements. The original kernel-module signing private key is intentionally absent; generating a new key and compiling a matching kernel/module set is the correct route for a new kernel build.

Historical VM launchers, checkpoints and collectors may refer to unavailable build paths or helper dependencies. Treat them as technical evidence to adapt. The release's successful headless VM and filesystem tests establish the delivered artifact's tested state, not a portable unattended rebuild pipeline or full phone functionality.
