# Fresh independent tools-only source recipe, not the missing historical tools2.
%global debug_package %{nil}
Name:           pinephone-pro-kernel-tools
Version:        7.2.9
Release:        3%{?dist}
Summary:        Fedora boot updater and portable initramfs content audit
License:        GPL-2.0-only
URL:            https://www.kernel.org/
Source0:        pinephone-pro-kernel-update
Source1:        pinephone-pro-initramfs-verify
Source2:        boot.conf
Source3:        README.md
Source4:        GPL-2.0
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

%description
Shared Fedora dracut and explicit extlinux boot updater for installed
PinePhone Pro kernels. The updater supports the source Btrfs build VM and
the final unique-UUID ext4 internal-eMMC image. A fresh content-aware
gzip/newc validator permits only the exact generic Fedora Btrfs hint and
an empty single-link etc/machine-id. It rejects host identity,
embedded root arguments, malformed containers and protected aliases before
publishing boot files. This package does not format or flash any device.

%prep
# All five public sources are carried in this independent source RPM.

%build
# Shell and Python helpers are installed verbatim.

%install
install -D -m 0755 %{SOURCE0} %{buildroot}%{_sbindir}/pinephone-pro-kernel-update
install -D -m 0755 %{SOURCE1} %{buildroot}%{_sbindir}/pinephone-pro-initramfs-verify
install -D -m 0644 %{SOURCE2} %{buildroot}%{_sysconfdir}/pinephone-pro/boot.conf
install -D -m 0644 %{SOURCE3} %{buildroot}%{_docdir}/%{name}/README.md
install -D -m 0644 %{SOURCE4} %{buildroot}%{_licensedir}/%{name}/GPL-2.0

%files
%license %{_licensedir}/%{name}/GPL-2.0
%doc %{_docdir}/%{name}/README.md
%{_sbindir}/pinephone-pro-kernel-update
%{_sbindir}/pinephone-pro-initramfs-verify
%config(noreplace) %{_sysconfdir}/pinephone-pro/boot.conf

%changelog
* Sat Oct 10 2026 Jon <Jgustafsonxjr1990@users.noreply.github.com> - 7.2.9-3
- Freshly reconstruct missing tools with strict gzip/newc content validation.
- Require Python3 and export PATH while retaining boot publication checks.
