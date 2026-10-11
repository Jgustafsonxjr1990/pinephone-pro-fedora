# Packages a separately compiled, matching PinePhone Pro kernel payload.
# This does not recompile Linux or install an Arch/Manjaro package into Fedora.
%global kernel_release 7.2.9-jon-ppp
%global tools_name pinephone-pro-kernel-tools
%global debug_package %{nil}
# modules_install has already stripped and signed the modules. Altering the
# ELF files after signing invalidates their signatures.
%global __brp_strip %{nil}
%global __brp_strip_static_archive %{nil}
%global __brp_strip_comment_note %{nil}
%global __brp_strip_lto %{nil}
# This package contains one complete kernel and its matching signed modules,
# rather than modules intended for a separately installed Fedora kernel.
# Fedora's ksym generators classify /usr/lib/modules as external modules and
# consult an absent /usr/src/kernels/<release>/Module.symvers. Skip automatic
# dependencies only for this bundled module payload; retain the explicit
# kernel-uname-r capability and normal dependencies for the updater.
%global __requires_exclude_from ^/usr/lib/modules/%{kernel_release}/.*[.]ko$
%global __provides_exclude_from ^/usr/lib/modules/%{kernel_release}/.*[.]ko$

Name:           kernel-pinephone-pro
Version:        7.2.9
Release:        3%{?dist}
Summary:        PinePhone Pro RK3399 kernel and matching device tree
License:        GPL-2.0-only WITH Linux-syscall-note
URL:            https://www.kernel.org/
Source0:        kernel-pinephone-pro-%{version}.tar.gz
Source1:        pinephone-pro-kernel-update
Source2:        boot.conf
Source3:        README.md
Source4:        pinephone-pro-initramfs-verify
BuildArch:      aarch64
ExclusiveArch:  aarch64
Requires:       bash
Requires:       coreutils
Requires:       grep
Requires:       util-linux
Requires:       kmod
Requires:       dracut
Requires:       btrfs-progs
Requires:       systemd
Requires:       %{tools_name} >= %{version}-%{release}
Requires(posttrans): bash coreutils grep util-linux kmod dracut btrfs-progs
Requires(preun): bash coreutils
Provides:       kernel-uname-r(%{kernel_release})
Provides:       installonlypkg(kernel)

%description
A custom RK3399 PinePhone Pro kernel, matching modules and PinePhone Pro DTB,
built from upstream Linux and the recorded device support patch set.

The boot updater generates a Fedora dracut initramfs and explicit U-Boot
extlinux entries on the existing mounted boot filesystems. It does not
format partitions, write a bootloader, or modify SPI flash.
Tow-Boot or compatible U-Boot with extlinux support is required, either in
SPI flash or independently installed in the image's reserved boot area.

%package -n %{tools_name}
Summary:        Fedora boot updater for matching PinePhone Pro kernels
License:        GPL-2.0-only
BuildArch:      noarch
Requires:       bash
Requires:       coreutils
Requires:       grep
Requires:       util-linux
Requires:       kmod
Requires:       dracut
Requires:       pigz
Requires:       python3
Requires:       btrfs-progs
Requires:       e2fsprogs
Requires:       systemd

%description -n %{tools_name}
Shared Fedora dracut and extlinux boot updater for installed PinePhone Pro
kernels. The updater supports the source Btrfs build VM and the final
unique-UUID ext4 internal-eMMC image. This tools package updates normally;
the custom kernel package uses installonly semantics to retain older kernels.

%prep
%setup -q -n kernel-pinephone-pro-%{version}
test "$(cat kernelrelease)" = "%{kernel_release}"
test -s Image
test -s rk3399-pinephone-pro.dtb
test -s modules/%{kernel_release}/modules.builtin

%build
# The reviewed cross-compiled payload is installed verbatim.

%install
install -d %{buildroot}/usr/lib/modules
cp -a modules/%{kernel_release} %{buildroot}/usr/lib/modules/
install -d %{buildroot}%{_datadir}/pinephone-pro/kernel/%{kernel_release}
install -m 0644 Image config System.map kernelrelease source-manifest.json SHA256SUMS MODULES_SHA256SUMS \
  %{buildroot}%{_datadir}/pinephone-pro/kernel/%{kernel_release}/
install -m 0644 rk3399-pinephone-pro.dtb \
  %{buildroot}%{_datadir}/pinephone-pro/kernel/%{kernel_release}/rk3399-pinephone-pro.dtb
install -D -m 0755 %{SOURCE1} %{buildroot}%{_sbindir}/pinephone-pro-kernel-update
install -D -m 0755 %{SOURCE4} %{buildroot}%{_sbindir}/pinephone-pro-initramfs-verify
install -D -m 0644 %{SOURCE2} %{buildroot}%{_sysconfdir}/pinephone-pro/boot.conf
install -D -m 0644 %{SOURCE3} %{buildroot}%{_docdir}/%{tools_name}/README.md
install -d %{buildroot}%{_licensedir}/%{name}-%{kernel_release}
install -m 0644 COPYING GPL-2.0 Linux-syscall-note %{buildroot}%{_licensedir}/%{name}-%{kernel_release}/
install -D -m 0644 GPL-2.0 %{buildroot}%{_licensedir}/%{tools_name}/GPL-2.0

%posttrans
# Fail visibly if dracut or boot installation fails; never claim a usable
# boot configuration merely because the RPM payload was installed.
%{_sbindir}/pinephone-pro-kernel-update %{kernel_release}

%preun
if [ "$1" -eq 0 ]; then
  if [ "$(uname -r)" = "%{kernel_release}" ]; then
    printf '%s\n' 'Refusing to remove the running PinePhone Pro kernel.' >&2
    exit 1
  fi
  if [ -f /var/lib/pinephone-pro/default-kernel ] && \
     [ "$(cat /var/lib/pinephone-pro/default-kernel)" = "%{kernel_release}" ]; then
    printf '%s\n' 'Select another installed PinePhone Pro kernel with pinephone-pro-kernel-update before removing this default kernel.' >&2
    exit 1
  fi
fi

%files
%license %{_licensedir}/%{name}-%{kernel_release}
%{_datadir}/pinephone-pro/kernel/%{kernel_release}
/usr/lib/modules/%{kernel_release}
%ghost %attr(0644,root,root) /usr/lib/modules/%{kernel_release}/modules.alias
%ghost %attr(0644,root,root) /usr/lib/modules/%{kernel_release}/modules.alias.bin
%ghost %attr(0644,root,root) /usr/lib/modules/%{kernel_release}/modules.builtin.alias.bin
%ghost %attr(0644,root,root) /usr/lib/modules/%{kernel_release}/modules.builtin.bin
%ghost %attr(0644,root,root) /usr/lib/modules/%{kernel_release}/modules.dep
%ghost %attr(0644,root,root) /usr/lib/modules/%{kernel_release}/modules.dep.bin
%ghost %attr(0644,root,root) /usr/lib/modules/%{kernel_release}/modules.devname
%ghost %attr(0644,root,root) /usr/lib/modules/%{kernel_release}/modules.softdep
%ghost %attr(0644,root,root) /usr/lib/modules/%{kernel_release}/modules.symbols
%ghost %attr(0644,root,root) /usr/lib/modules/%{kernel_release}/modules.symbols.bin
%ghost %attr(0644,root,root) /usr/lib/modules/%{kernel_release}/modules.weakdep
%ghost %attr(0644,root,root) /boot/vmlinuz-%{kernel_release}
%ghost %attr(0644,root,root) /boot/config-%{kernel_release}
%ghost %attr(0644,root,root) /boot/System.map-%{kernel_release}
%ghost %attr(0600,root,root) /boot/initramfs-%{kernel_release}.img
%ghost %dir %attr(0755,root,root) /boot/dtb-%{kernel_release}
%ghost %dir %attr(0755,root,root) /boot/dtb-%{kernel_release}/rockchip
%ghost %attr(0644,root,root) /boot/dtb-%{kernel_release}/rockchip/rk3399-pinephone-pro.dtb
%ghost %attr(0644,root,root) /boot/loader/entries/pinephone-pro-%{kernel_release}.conf
# FAT modes reflect mount masks rather than POSIX file metadata.
%ghost %dir %attr(0755,root,root) %verify(not mode) /boot/efi/pinephone-pro/%{kernel_release}
%ghost %attr(0644,root,root) %verify(not mode) /boot/efi/pinephone-pro/%{kernel_release}/Image
%ghost %attr(0644,root,root) %verify(not mode) /boot/efi/pinephone-pro/%{kernel_release}/initramfs.img
%ghost %attr(0644,root,root) %verify(not mode) /boot/efi/pinephone-pro/%{kernel_release}/rk3399-pinephone-pro.dtb

%files -n %{tools_name}
%license %{_licensedir}/%{tools_name}/GPL-2.0
%doc %{_docdir}/%{tools_name}/README.md
%{_sbindir}/pinephone-pro-kernel-update
%{_sbindir}/pinephone-pro-initramfs-verify
%config(noreplace) %{_sysconfdir}/pinephone-pro/boot.conf

%changelog
* Sat Oct 10 2026 Jon <Jgustafsonxjr1990@users.noreply.github.com> - 7.2.9-3
- Freshly rebuild tools and transparent content-aware portability audit.
- Preserve kernel release, signed module bytes and unversioned uname capability.

* Sat Oct 10 2026 Jon <Jgustafsonxjr1990@users.noreply.github.com> - 7.2.9-1
- Package matching PinePhone Pro kernel, modules and DTB for Fedora.
- Generate portable dracut and explicit phone extlinux boot entries.
