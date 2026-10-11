# Public reconstruction sources for the PinePhone Pro image

This is the source and recipe companion to the independent Fedora 44 Plasma
Mobile PinePhone Pro image completed October 11, 2026. It is not an official
Fedora release or a turnkey, reproducible build system. The separate release
README, installation guide and verification reports describe the delivered
image and actual tests; old comments and manifests are not current test results.

## Sources and layout

- `kernel-build/sources/linux-7.2.9.tar.xz` is the full pinned Linux source.
  `source-manifest.json` gives the exact pmaports revision, patch order and
  hashes. All 91 listed patch/config inputs are present, including the recovered
  baseline config, plus the recorded local modem-DT patch. The obsolete Wi-Fi
  interrupt patch is retained as source but deliberately skipped by preparation.
  `final-config-7.2.9-jon-ppp` is the exact final configuration extracted from
  the released kernel SRPM payload. The original release-signature verification
  is recorded in the manifest; the detached Linux signature is not in this kit.
- `bootloader-build/sources/u-boot-v2026.10.tar.xz` and
  `trusted-firmware-a-v2.15.0.tar.xz` are the complete pinned upstream archives.
  Their manifests, release public keys and signed-tag records are retained.
  `build-bootloader.sh` records the defconfig and explicit modifications; an
  independently retained full final U-Boot `.config` is not provided.
- `work/share/fedora-kernel-packaging/` contains the actual kernel packaging
  recipes, compiled Source0 payload, tools and licenses. The kernel SRPM packages
  a compiled payload: rebuilding that SRPM alone does not compile Linux.
- `work/share/device-support-rebuild/` contains the actual device source inputs,
  Source0 archives, RPM specs, pmaports files and Broadcom notices.
  `srpm-inputs.json` maps every audited payload member of the four source RPMs
  to these retained files without storing duplicate source archives.
- `work/share/guest-rebuild-preparation/` and the standalone guest scripts
  document Fedora package installation, initramfs work and integration.
- `work/share/image-assembly/` contains the final corrected assembly and root
  growth recipes and their guest verification scripts. These are the current
  copies; older duplicate recipe trees and checkpoint records are excluded.
- `work/vm-resume/`, `work/vm-validation/` and the top-level `work/*.py` helpers
  are nonportable reference scripts. `reference/local-image-repairs/` preserves
  the two offline repairs made to the final image. No device-flashing helper is
  included. Use the separately published installation guide for installation.

## Local integration corrections

The final assembly leaves `/etc/machine-id` empty so systemd generates a unique
ID while avoiding generic interactive first-boot presets. Plasma Setup remains
enabled and no account or setup-complete flag is precreated. Assembly removes
only the inherited `/etc/repart.d/50-root.conf` containing the generic
`[Partition]` / `Type=root` recipe; the custom ext4 growth service owns growth.
The final growth helper and relevant validators use `findmnt -rn -o MAJ:MIN`
so human-readable column padding cannot break device identity checks.
The corresponding scripts and offline repair references preserve these fixes.

## Reconstruction limits

Read scripts before adapting them to a disposable build environment. Host and
cloud workspace locations were replaced with `/path/to/workspace`. Reference
scripts still encode original filesystem UUIDs, image names, layout, result
schemas and directory relationships. These are image/build guards, not a
general-purpose device selector. They must not be blindly run against disks.
Some bootstrap recipes expect a generated `/build/live-build-network.sh` and
build-specific CA setup, which are intentionally not distributed; configure
your own ordinary trusted repository access. Extracted build toolchains and
Fedora's base image/userspace source packages are not bundled in this archive.
Supply suitable documented toolchains and obtain exact Fedora package sources
using the release package inventory and Fedora repositories.

Original input manifests are retained for provenance and can contain historical
hashes: the final `findmnt -rn` repair changed the growth helper after
`guest-rebuild-preparation/finish-inputs.json` was written. Privacy replacement
of the maintainer changelog email also changes copied RPM spec hashes referenced
by older manifests. `PUBLIC-SOURCE-INVENTORY.json` is authoritative for the
contents of this public tree; old manifest hashes are not claimed to validate
later repaired or sanitized recipes. No private module-signing keys are
included; a new kernel build generates and uses its own signing key.

## Licenses and provenance

Upstream archives are byte-for-byte unchanged and include their full license
trees and per-file notices. Preserve the source headers and patch author
attribution. Device Source0 retains feedbackd COPYING and both Broadcom
`BCM-LEGAL.txt` and `debian/copyright`; a general GPL notice is not a substitute
for the firmware's specific distribution terms.

The pinned pmaports device APKBUILD declares MIT. Its device and UCM directories
contain no package-specific LICENSE/COPYING file. `notices/pmaports-LICENSE` is
the authentic pinned repository-root GPLv3 text, with retrieval provenance;
the upstream README does not clarify the scope relative to the MIT declaration.
It is retained as upstream context, not relabeled as a missing MIT notice.
This unresolved notice-scope detail should be resolved with upstream before
representing the device package notice set as complete.

Only the local maintainer's RPM changelog email was changed to a GitHub noreply
address; the name and all upstream author/copyright notices were preserved.
No blanket license is asserted over this aggregate. Consult the release's
third-party notice guide, source files and RPM license metadata.

## Inventory and exclusions

`PUBLIC-SOURCE-INVENTORY.json` records the size and SHA256 of every other file,
as well as documented path/email sanitizations. It does not hash itself.
The kit intentionally omits private or historical checkpoint records, local
run evidence/logs, fixed-phone flash/install scripts, credentials, private keys,
phone backups, virtual/raw disks, hidden Git directories and extracted host
tool binaries. The original private delivery and its source archive were not
modified. Public upstream distributions can contain upstream test fixtures;
their pinned archive hashes were independently rechecked during curation.
