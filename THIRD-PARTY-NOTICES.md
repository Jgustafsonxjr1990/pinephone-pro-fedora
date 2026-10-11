# Upstream notices and source references

This image combines separately licensed software and firmware. This repository does not relicense upstream components under a single blanket license. Preserve the accompanying source headers, copyright notices, `COPYING`/`LICENSES` files and package license texts. Fedora packages retain their own licensing and source provenance; installed RPM metadata and `/usr/share/licenses` identify their notices.

## Kernel and boot chain

- **Linux 7.2.9:** [kernel.org source](https://cdn.kernel.org/pub/linux/kernel/v7.x/linux-7.2.9.tar.xz), SHA256 `b4c5dfbe51a364a6c7f03869200f88c8e1f77403539005f14b7fc6bc91b8d8ba`. Linux's top-level `COPYING`, `LICENSES/` and individual SPDX headers apply; the syscall exception applies where indicated. The retained manifest records verification of the detached release signature with fingerprint `647F28654894E3BD457199BE38DBBDC86092693E`.
- **PinePhone Pro kernel patches/configuration:** [postmarketOS pmaports](https://gitlab.postmarketos.org/postmarketOS/pmaports/-/tree/4b5d202c15567da82a2bcb2d580ec0845e63c1d5/device/community/linux-pine64-pinephonepro), including work from Megi and other credited upstream contributors. Preserve patch attribution and per-file terms.
- **Modem device-tree adaptation:** derived from [DanctNIX patches](https://github.com/dreemurrs-embedded/danctnix-packages/tree/6a38917f6664eb490f4d02d524c926cc9c2c0c93/pine64/linux-megi). Exact source files and hashes appear in the kernel manifest.
- **U-Boot 2026.10:** [upstream repository](https://git.u-boot-project.org/u-boot/u-boot.git), commit `5508406582f6f7120dce0c4b3059819a41788db2`. Preserve its `Licenses/` tree and per-file notices. The retained source archive hash is `91931ff90002020b31f953e9c0526c4909765d4d4e0d280e40dbd2ddec232f47`.
- **Trusted Firmware-A 2.15.0:** [upstream repository](https://github.com/TrustedFirmware-A/trusted-firmware-a/tree/da738d5eae93af342fdc4995dd3c05acb4c9d757), with upstream `license.rst` and applicable component notices. The retained source archive hash is `436fbe5f3771edf84b77ca4efb8c2ed0211845e91d8538243b920f2327f82fdb`.

## Device support

| Component | Source and retained notice |
| --- | --- |
| eg25-manager 0.5.2 | [Mobian commit `2d8a19b…`](https://gitlab.com/mobian1/eg25-manager/-/tree/2d8a19bfd7a4575489f1cb5adab042ad49ffec88); source `COPYING`, packaged as GPL-3.0-or-later |
| atinout 0.9.1 | [upstream project](https://atinout.sourceforge.net/); `gplv3.txt` and source headers, GPL-3.0-or-later |
| PinePhone Pro UCM, aliases and modem setup | [pmaports device package](https://gitlab.postmarketos.org/postmarketOS/pmaports/-/tree/4b5d202c15567da82a2bcb2d580ec0845e63c1d5/device/community/device-pine64-pinephonepro); device-package recipe declares MIT; preserve original file notices and provenance |
| feedbackd PinePhone Pro theme | [device-theme commit `2f9d81c…`](https://gitlab.freedesktop.org/feedbackd/feedbackd-device-themes/-/tree/2f9d81c968764f8f640f20b96be2d1777027e089); accompanying `COPYING`, packaged as GPL-3.0-or-later |
| Supplemental Broadcom Bluetooth HCD files | [RPi-Distro/bluez-firmware commit `6851250…`](https://github.com/RPi-Distro/bluez-firmware/tree/6851250bf9d51ff50e3c5b2cf2111e2419d4335b); retain **both** `broadcom/BCM-LEGAL.txt` and `debian/copyright` |

The Bluetooth blobs are `BCM4345C0.hcd` and `BCM4345C5.hcd`. Their source provenance explicitly uses the distribution-permission record in `debian/copyright` together with the Broadcom notice; **the repository's general GPL text must not be represented as licensing these blobs**. The device RPM records `MIT AND GPL-3.0-or-later AND LicenseRef-Broadcom-BlueZ` and installs the accompanying notices.

Wi-Fi firmware comes from Fedora's `brcmfmac-firmware` package, not a replacement copy in the custom device RPM. The reference NVRAM alias was checked against [linux-firmware commit `2424705…`](https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/tree/?id=24247053afda2bab6b4ace42402dbf9f3b1305d6); retain its `WHENCE`, applicable firmware licenses and package notices. Firmware components can have different terms from the GPL-licensed NVRAM text.

Custom kernel-updater, initramfs-validator and image-assembly scripts retain their own SPDX/license declarations. See the source RPM specifications and per-file headers. The release includes the custom packages' source RPMs plus the separately preserved full kernel/bootloader sources and patches; the kernel SRPM alone contains packaged compiled payloads.

Fedora, KDE, PINE64, postmarketOS, Mobian, Megi, DanctNIX, U-Boot, Trusted Firmware and other upstream names identify the projects whose work this build uses. This independent image makes no claim of their endorsement.
