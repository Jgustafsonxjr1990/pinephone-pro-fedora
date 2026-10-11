# Plasma Mobile on PinePhone Pro, based on Fedora 44

An independent community image for the **PINE64 PinePhone Pro (RK3399S)**, with Plasma Mobile 6.7.5 and a custom Linux `7.2.9-jon-ppp` kernel. This is not an official Fedora image or an endorsed Fedora release. It is intended for the phone's internal eMMC; it is not for the original PinePhone.

**Status, October 11, 2026:** the owner reports a successful boot on a physical PinePhone Pro after installation. Automated build and VM checks passed, and all 14 GiB written to the tested phone were independently read back and matched the image hash. Display, touch, wireless, cellular, audio, cameras, charging and suspend still need systematic hardware testing. A boot report does not establish that these functions all work.

[Installation and download verification](INSTALL.md) · [Source and reconstruction guide](REBUILD.md) · [Upstream notices](THIRD-PARTY-NOTICES.md)

## Download

Download the matching assets from the [Releases page](https://github.com/Jgustafsonxjr1990/pinephone-pro-fedora/releases). The first release is being prepared; use only a published release with its checksum files:

- `Fedora-44-Plasma-Mobile-PinePhone-Pro-eMMC-20261010.img.xz.part01` and `.part02`: two pieces of one XZ stream. Download both and join them in order.
- `SHA256SUMS.parts`: individual part checksums.
- `pinephone-pro-fedora-sources-20261011.tar.zst`: source archives, patches, configuration and reconstruction recipes.
- Matching custom binary RPMs, source RPMs, checksums and selected verification reports, as listed in the release.

The image filename retains its build identifier; final assembly and validation completed October 11. The reconstructed XZ is **3,348,179,812 bytes** and decodes to **15,032,385,536 bytes (14 GiB)**.

| File | SHA256 |
| --- | --- |
| Complete `.img.xz` | `a43eda1be8c9b67d032832cbf8ca64901bbdc27bcea360b2cd2b3918fe4cd634` |
| Decoded `.img` | `05a1555883c75a55fcf1b486616078132ab9b3a9f3e968f2cc0c009c786f65ab` |

## Included

- Fedora 44 Plasma Mobile base, refreshed from Fedora repositories during the build.
- PinePhone Pro kernel, matching DTB and 906 signed kernel modules; portable initramfs and explicit extlinux boot entries.
- SELinux enforcing, Plasma's account-creation setup and on-screen keyboard. Root is locked; there is no shared login password or pre-created personal account.
- Device configuration for modem management, audio, feedback and Bluetooth; Wi-Fi firmware supplied by Fedora's `brcmfmac-firmware` package.
- GPT with FAT32 boot, ext4 `/boot`, and ext4 root. First boot attempts guarded root expansion on internal eMMC.
- An eMMC user-area U-Boot/TF-A loader. Installation does not write SPI firmware. Existing compatible SPI firmware may take precedence over the embedded loader.

## Validation and maintenance

Verified before release: Fedora package/dependency checks; kernel/DTB/module consistency; initramfs portability; GPT and loader placement; filesystem checks; normal headless ARM64 systemd boot; disposable 14-to-16 GiB online root growth followed by offline filesystem checks; complete XZ decoding; and complete physical write/readback. These are separate from the owner's later physical boot report.

Fedora userspace updates use Fedora repositories. **There is no custom-kernel update repository supplied by this release.** Ordinary Fedora kernel updates do not replace the dedicated `*-jon-ppp` extlinux default. Future custom kernels require reviewed matching packages and phone testing. Kernel module signatures do not mean this kernel is signed for Fedora shim Secure Boot.

When reporting a problem, include the image identifier, `uname -r`, phone model, bootloader details if known, reproduction steps and a relevant log excerpt. Remove credentials, device identifiers and personal information from logs before posting.
