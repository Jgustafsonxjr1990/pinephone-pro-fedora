# Fedora PinePhone Pro image assembly

These scripts run inside the isolated ARM64 QEMU build VM. They do not flash a
phone, write SPI flash, or access a host disk. Run only after Fedora updates and
the reviewed custom kernel/device-support RPMs are installed:

```sh
bash /build/image-assembly/assemble-fedora-ppp.sh 7.2.9-jon-ppp
```

The VM must have its source Fedora disk as `vda`, with `/var`, `/home`, `/boot`
and `/boot/efi` correctly mounted, and a separate completely empty 14 GiB
VirtIO disk as `vdb`. `/build` must be the shared build directory. The script
verifies these conditions before partitioning only `vdb`.

The result reserves the first 32 MiB for independently reviewed RK3399 loader
embedding. It creates a GPT FAT32 500 MiB boot partition, ext4 2 GiB `/boot`,
and unique-UUID ext4 root partition. Both boot partitions carry the legacy boot
attribute so U-Boot can try the ext4 extlinux menu if FAT is unreadable. Source
Btrfs `/var` and `/home` are copied
explicitly into the new root. A matching PPP kernel, DTB, portable initramfs
and dedicated extlinux menu are installed in fresh boot filesystems. Generic
EFI loaders and stale GRUB/BLS menus are omitted. Phone loader embedding is a
separate operation after the VM has stopped.

Locked root and Fedora Plasma Setup account creation are preserved. Machine ID,
SSH host identity, build DNS, caches and temporary build mounts are reset. The
targeted SELinux contexts are applied before read-only filesystem checks.

The first-boot growth unit runs before the display manager. It acts only when
the device tree identifies a PinePhone Pro and the matching image root is
partition 3 of a sysfs `MMC` device with the exact expected GPT layout. SD media
and VMs are skipped. Canonical `growpart` with explicit `sgdisk` resizing moves
the backup GPT header and enlarges only root partition 3, retaining its start
and GUID. `resize2fs` then enlarges the mounted ext4 filesystem. Table backups
and the operation log are retained under `/var/lib/pinephone-pro`.

Required guest packages include `cloud-utils-growpart`, `gdisk`, `e2fsprogs`,
`dosfstools`, `rsync`, `util-linux`, `policycoreutils`, and the usual Fedora
systemd/SELinux packages. Confirm the installed `growpart` implementation
matches the reviewed upstream behavior before execution.

Primary implementation references:

- https://github.com/canonical/cloud-utils/blob/main/bin/growpart
- https://man7.org/linux/man-pages/man8/resize2fs.8.html
- https://www.freedesktop.org/software/systemd/man/latest/machine-id.html

The scripts perform static image preparation and VM verification. Actual
display, touch, audio, modem, cameras and suspend require PinePhone Pro testing.

## Disposable growth validation

`test-virtual-root-growth.sh` is a separate validation script. Keep it outside
the shipped filesystem. The host must create a qcow2 overlay with the completed
14 GiB image as a read-only backing file, resize the overlay to exactly 16 GiB,
and confirm QEMU opens the overlay rather than the delivered image for writing.
The guest cannot inspect the host backing-file relationship.

Place `QEMU_OVERLAY_14GiB_TO_16GiB` in the external shared file
`/build/ALLOW_DISPOSABLE_IMAGE_GROWTH_TEST`. Boot that overlay with the custom
PPP kernel, mount the shared directory, then run:

```sh
bash /build/image-assembly/test-virtual-root-growth.sh grow-mounted-root /dev/vda
```

The test checks the exact original geometry, ext4 root UUID and custom kernel,
then exercises the same `growpart`/`resize2fs` operations online. It verifies
that root start/GUID/UUID and both boot partitions' starts, sizes, GUIDs and
attributes remain unchanged. Report files are written to the external share.

After cleanly stopping that VM, attach the same grown overlay as `vdb` to a
separate build VM whose root is `vda`. Leave every `vdb` partition unmounted:

```sh
bash /build/image-assembly/test-virtual-root-growth.sh check-unmounted-filesystems /dev/vdb
```

This phase verifies the prior report and runs read-only checks on all three
filesystems and the GPT. Neither phase modifies or weakens the production
PinePhone Pro + internal MMC guards.

## Normal systemd boot verification

`../work/launch-verify-vm.py` boots the final custom kernel and exported final
initramfs with systemd as PID 1. `--mode snapshot` uses temporary QEMU writes
over the original image; `--mode growth` requires an existing 16 GiB qcow2
overlay whose sole backing file is that original 14 GiB raw image. The launcher
checks this backing relationship and never creates, resizes or commits a disk.
The default overlay path is `work/fedora-ppp-validation.qcow2`.

Its serial debug shell and serial-getty mask are temporary VM kernel arguments.
Neither is written into the phone boot configuration. It supplies no graphics
or virtio DRM device and starts `multi-user.target` rather than the graphical
target. After the serial debug shell appears:

```sh
mkdir -p /build
modprobe 9pnet_virtio
mount -t 9p -o trans=virtio,version=9p2000.L build /build
bash /build/image-assembly/verify-fedora-ppp-vm.sh
```

The external report, `/build/fedora-ppp-vm-verification.txt`, checks normal
multi-user startup, Fedora 44 ARM64 and the custom running kernel, 28 core
packages plus the canonical 28-package phone runtime list, enforcing SELinux,
locked root and preserved first-login account creation, Plasma Mobile session
and keyboard defaults, matching ext4 root and boot filesystems, dedicated
extlinux menus, payload/module hashes, firmware/configuration files and DNF
dependency consistency. Hardware-service enablement is checked, while observed
service failures are recorded: QEMU has no phone modem, Bluetooth controller or
other peripherals. Graphical and physical phone behavior remains outside this
headless test.
