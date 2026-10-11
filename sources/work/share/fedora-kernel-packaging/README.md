# Packaging a prebuilt PPP kernel for Fedora 44

Prepare only after the cross compilation has completed successfully:

```bash
python3 prepare-sources.py \
  --kernel-output /path/to/workspace/kernel-build/output \
  --linux-source /path/to/workspace/kernel-build/linux-7.2.9
```

Preparation checks ARM64 Image/DTB headers, reserved image memory size,
essential PPP and Fedora configuration, every module's architecture and
vermagic, signatures when enabled, complete module metadata, and source
provenance. Build/source symlinks back into the host tree are removed.

Copy this entire directory into the target aarch64 Fedora 44 build system.
Build only the reviewed installed payload; no second kernel compilation:

```bash
dnf install -y rpm-build
rpmbuild --define '_topdir /build/fedora-kernel-packaging' \
  --target aarch64 -bb /build/fedora-kernel-packaging/SPECS/kernel-pinephone-pro.spec
```

Adjust `_topdir` to the actual directory in that guest. Dependencies needed
for installation are `bash coreutils grep util-linux kmod dracut pigz btrfs-progs
e2fsprogs systemd`. Install both local RPMs (kernel and tools) with DNF while the image's `/boot` and
`/boot/efi` are mounted. Do not disable repository signature checks. The
locally built RPM has its file digests; it has no distribution RPM signing
key. Record its checksum separately.

The spec filters automatic dependencies only for its bundled `.ko` files.
The full matching kernel and modules share one package, with an explicit
`kernel-uname-r` capability. Inspect the built RPM's Requires list to ensure
it has no separate `kernel(...)`, `ksym(...)`, or `kernel-uname-r` requirement;
see `review/README.md` for the Fedora 44 generator review and exact checks.

Fedora dracut 108 uses installed pigz automatically for the updater's
`--gzip` option. The tools RPM requires pigz for parallel compression while
retaining the kernel's verified gzip initramfs format. See
`review/dracut-compression.md` for the exact Fedora 108-8 source review.

Required post-install verification:

- `rpm -q --provides kernel-pinephone-pro` includes exact `kernel-uname-r`.
- `rpm -V kernel-pinephone-pro` passes for packaged payload/modules.
- `modinfo -k 7.2.9-jon-ppp -F vermagic brcmfmac` starts with the exact release.
- `modinfo -k 7.2.9-jon-ppp -F signer brcmfmac` matches built kernel signer.
- Generated `modules.dep`, `modules.alias` and other depmod indexes exist.
- `lsinitrd` shows `/init`, Btrfs support, and no embedded QEMU root cmdline
  or builder `/etc/fstab`.
- `/boot/efi/extlinux/extlinux.conf` selects `DEFAULT fedora-ppp`; every
  LINUX, INITRD and FDT path exists within that FAT filesystem.
- Both boot menus carry the actual root UUID, filesystem and matching flags.
  The Btrfs build VM uses `rootflags=subvol=root`; final internal eMMC ext4
  boot has no subvolume flags.
- The FAT partition has sufficient free space for kernel, initramfs, DTB,
  temporary copies, and any retained earlier release.
- Check Image and initramfs loading ranges against actual phone firmware.
- Ordinary stock kernel updates leave the dedicated phone extlinux default
  and selected payload unchanged.

Static/RPM/QEMU checks establish build consistency. They cannot certify
physical PinePhone Pro functions without testing the actual phone.
