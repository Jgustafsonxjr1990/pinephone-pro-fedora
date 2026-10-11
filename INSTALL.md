# Install to PinePhone Pro internal eMMC

Writing this image replaces the selected disk's partition table and operating system. Back up the phone's existing data first, and independently identify its **whole internal eMMC disk** before writing. The following Linux instructions use Bash, GNU coreutils, util-linux and XZ tools. Allow roughly 22 GiB of free host space to keep both parts, the joined XZ and the decoded image.

## 1. Join and verify the download

Put both release parts and `SHA256SUMS.parts` in an otherwise empty download directory. The parts are at most 1900 MiB each because [GitHub requires each release asset to be under 2 GiB](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases#storage-and-bandwidth-quotas).

Run in Bash from that directory:

```bash
set -euo pipefail
image=Fedora-44-Plasma-Mobile-PinePhone-Pro-eMMC-20261010.img.xz
raw=${image%.xz}
sha256sum --check SHA256SUMS.parts
test ! -e "$image"
( set -o noclobber; cat "$image.part01" "$image.part02" > "$image" )
test "$(stat -c %s "$image")" -eq 3348179812
printf '%s  %s\n' \
  a43eda1be8c9b67d032832cbf8ca64901bbdc27bcea360b2cd2b3918fe4cd634 \
  "$image" | sha256sum --check -
xz --test "$image"
xz --keep --decompress "$image"
test "$(stat -c %s "$raw")" -eq 15032385536
printf '%s  %s\n' \
  05a1555883c75a55fcf1b486616078132ab9b3a9f3e968f2cc0c009c786f65ab \
  "$raw" | sha256sum --check -
```

Each check must succeed. Do not decompress either part separately: they are pieces of a single compressed file.

## 2. Expose and identify the internal disk

With an already installed compatible Tow-Boot, hold **Volume Up** at startup before and during the second vibration. A blue LED indicates USB mass-storage mode. Connect the phone to the computer using a data-capable cable. See the [official PinePhone Pro Tow-Boot instructions](https://tow-boot.org/devices/pine64-pinephonePro.html#additional-features). This guide does not install or replace SPI firmware. If USB mass-storage mode is unavailable, resolve the phone's bootloader/recovery setup using its documentation before continuing.

Inspect the disks, including model, serial, size and mounts:

```bash
lsblk -o NAME,PATH,SIZE,MODEL,SERIAL,TRAN,TYPE,MOUNTPOINTS
ls -l /dev/disk/by-id/
```

Select the by-id link belonging to this phone's **whole eMMC disk**, not a numbered partition, SD card or computer disk. Unmount every filesystem on that disk, including any nested image/loop mounts; disable any swap on it. Confirm the disk identity again immediately before writing. A device name such as `/dev/sda` is not a stable identity.

The placeholder below is deliberately unusable. Replace it with the independently identified by-id path for your own phone:

```bash
target=/dev/disk/by-id/REPLACE_WITH_YOUR_PHONE_EMMC
test -b "$target"
test "$(lsblk -dn -o TYPE "$target")" = disk
test "$(sudo blockdev --getsize64 "$target")" -ge 15032385536
test "$(sudo blockdev --getss "$target")" -eq 512
lsblk -o NAME,PATH,SIZE,MODEL,SERIAL,TYPE,MOUNTPOINTS "$target"
```

The size/type checks alone do not identify a safe destination. Stop if any identity is uncertain or any descendant remains in use. This project does not supply a general-purpose automatic flasher; the original local writer was restricted to one specific development phone.

## 3. Write and verify all 14 GiB

Only after the checks above, write the decoded image to the selected whole disk:

```bash
sudo dd if="$raw" of="$target" bs=8M conv=fsync status=progress
sudo blockdev --flushbufs "$target"
sudo dd if="$target" bs=8M count=1792 iflag=fullblock status=progress | sha256sum
```

The final SHA256 must be exactly:

```text
05a1555883c75a55fcf1b486616078132ab9b3a9f3e968f2cc0c009c786f65ab
```

This reads back the entire written 14 GiB, including zero-filled areas. A mismatch or any I/O error means the installation is not verified. Do not boot the phone until it is resolved. Avoid sparse-copy options when following this exact full-image verification procedure.

On a larger eMMC, an initial warning that the backup GPT is not at the physical end is expected. The guarded first-boot growth service moves it while enlarging partition 3; no separate footer erase is required. Do not use partition tools to accept an unrelated old partition table.

## 4. First boot

After all writes and checks finish, disconnect USB. Hold Power until the phone turns off, release it, then start normally without either volume button or the RE button. Allow time for root expansion and Plasma's setup wizard; create your own account there.

The automatic growth service acts only on the expected PinePhone Pro internal-MMC layout. SD boot is outside this installation procedure and will not trigger that expansion. If setup or storage expansion fails, preserve the system journal and `/var/lib/pinephone-pro/root-growth.log` for diagnosis. Do not assume a successful boot proves that cellular calls, audio, suspend or other peripherals work.
