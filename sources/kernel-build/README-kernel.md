# PinePhone Pro Fedora kernel source and build

Target: PINE64 PinePhone Pro (RK3399S, AArch64), release `7.2.9-jon-ppp`.

This is upstream Linux 7.2.9, authenticated by its detached Greg Kroah-Hartman signature, with the PinePhone Pro/Megi patch set and hardware configuration from postmarketOS pmaports commit `4b5d202c15567da82a2bcb2d580ec0845e63c1d5`. The source manifest records upstream URLs, checksums, signing fingerprint and patch checksums. One patch only commenting out Wi-Fi interrupts is already obsolete in upstream 7.2.9 and is skipped after verifying those properties are absent. `patch-rebase-notes.txt` records the reason.

`0091-fedora-eg25-manager-dts.patch` adapts DanctNIX's modem integration: userspace eg25-manager controls the EG25 modem GPIOs, both modem power rails remain always on, and a separate GPIO key handles the ring indicator wake interrupt. No modem firmware is flashed.

`fedora-security.config` preserves the hardware maintainer configuration, adds Fedora SELinux and auditing support, and keeps ext4 and Btrfs built into the kernel. Virtio and 9p support permit QEMU CPU/userspace validation. Build debug information and BTF are disabled to fit this builder's resources. This kernel has no Secure Boot signature.

Reconstruction requires Python 3.12+, GNU make, gcc/binutils for AArch64, flex, bison, m4, bc, native C compiler, libelf/libssl development headers, pkg-config and kmod. The build script uses private extracted Ubuntu tools in `tools/` when present. It runs four compilation jobs. Source preparation uses strict patches with zero fuzz and refuses to overwrite an existing source tree:

```sh
python3 prepare-kernel-source.py
bash build-kernel.sh
python3 verify-kernel.py
```

Verify the detached OpenPGP signature on the uncompressed tar archive before source preparation, using the known release-key fingerprint `647F28654894E3BD457199BE38DBBDC86092693E`. This build's successful verification is recorded in `logs/signature.log`.

The matching outputs are the raw ARM64 `Image`, PinePhone Pro DTB, configuration, System.map and complete modules tree with dependency indexes. The image builder must create a matching initramfs and boot configuration. Generic Fedora kernel updates do not contain this full downstream PinePhone Pro patch set; the explicit custom kernel paths must stay coherent until a replacement PPP kernel is built.

Compilation and static validation do not establish successful physical-device boot, modem calls, suspend, charging, audio, cameras or display operation. No PinePhone Pro hardware was available to this builder.
