# Fedora PinePhone Pro kernel package

This package owns one matching ARM64 kernel, module tree, RK3399 PinePhone Pro
DTB, config and System.map. It generates its initramfs with Fedora dracut in
the target Fedora system. The payload is custom built; it is not a Fedora
Project supported kernel and is not signed with Fedora's Secure Boot key.
Module signatures use the compiled kernel's own key.
The updater selects gzip initramfs compression, supported by this kernel.
Its tools package requires pigz; Fedora dracut automatically uses that
parallel compressor for the gzip option without changing the archive format.

The phone boot path is extlinux on the existing FAT boot partition mounted
at `/boot/efi`. All paths in that menu are relative to that partition. A
second extlinux menu on the separate `/boot` partition uses its own relative
paths. Both explicitly load the device tree matching this kernel. The root
UUID and filesystem in `/etc/pinephone-pro/boot.conf` must match the mounted
root. Btrfs source builds use `ROOT_FLAGS=subvol=root`; the final ext4 image
for internal eMMC uses `ROOT_FSTYPE=ext4` and an empty `ROOT_FLAGS=`.
The updater refuses inconsistent layouts. UUID boot arguments avoid dependence
on SD/eMMC device numbering and collisions with a different installed image.

The image requires working Tow-Boot or compatible U-Boot that scans the
medium and supports ARM64 `Image` and extlinux. The bootloader may reside
in existing SPI flash or in the image's reserved boot area. The package
does not install firmware or change partitions. The kernel and initramfs
must also fit the firmware's actual RAM load addresses. Source preparation
checks the conservative 63.5 MiB kernel-to-initrd address gap.

The BLS entry on `/boot/loader/entries` is fallback metadata for Fedora's
EFI/GRUB chain. Some Fedora GRUB implementations ignore its `devicetree`
key. It is not sufficient to establish that EFI boot works on this phone,
and the custom unsigned kernel will not pass Fedora shim Secure Boot.

Ordinary Fedora updates remain on their official repositories. The dedicated
extlinux default always selects an installed `*-jon-ppp` kernel. Stock kernel
updates do not publish a kernel to that phone menu. `installonlypkg(kernel)`
allows custom kernel versions to coexist. The running/default custom kernel
is protected from final RPM removal. To select another installed custom
kernel, run `pinephone-pro-kernel-update` with its exact release.
The separate `pinephone-pro-kernel-tools` RPM owns the shared updater and
configuration so retaining earlier kernel RPMs does not cause file conflicts
when the updater is improved later.

This build does not provide a remote update repository for future custom
kernel releases. Future releases must be rebuilt, reviewed and installed
as new matching RPMs. Physical phone testing is still required for screen,
touch, modem, audio, charging, suspend and cameras.
