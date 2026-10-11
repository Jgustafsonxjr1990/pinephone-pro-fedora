# Fresh recovery recipe. This is not the lost Release2 spec or a build receipt.
%global source_commit 2d8a19bfd7a4575489f1cb5adab042ad49ffec88

Name:           eg25-manager
Version:        0.5.2
Release:        3%{?dist}
Summary:        Quectel EG25 management daemon for PinePhone devices
License:        GPL-3.0-or-later
URL:            https://gitlab.com/mobian1/eg25-manager
Source0:        eg25-manager-%{source_commit}.tar.gz

BuildRequires:  gcc
BuildRequires:  meson >= 0.58.0
BuildRequires:  ninja-build
BuildRequires:  pkgconf-pkg-config
BuildRequires:  pkgconfig(glib-2.0)
BuildRequires:  pkgconfig(gio-unix-2.0)
BuildRequires:  pkgconfig(gudev-1.0)
BuildRequires:  pkgconfig(libgpiod) >= 2.0
BuildRequires:  pkgconfig(libusb-1.0)
BuildRequires:  pkgconfig(libcurl)
# Upstream makes this optional; require it so ModemManager support is compiled.
BuildRequires:  pkgconfig(mm-glib)
BuildRequires:  scdoc
BuildRequires:  systemd-rpm-macros
Requires:       ModemManager
%{?systemd_requires}

%description
Manage EG25 modem power, configuration and suspend integration using the
upstream PinePhone Pro device configuration and ModemManager support.

%prep
%autosetup -n eg25-manager-%{source_commit}

%build
%meson
%meson_build

%install
%meson_install

%post
%systemd_post eg25-manager.service

%preun
%systemd_preun eg25-manager.service

%postun
%systemd_postun_with_restart eg25-manager.service

%files
%license COPYING
%doc README.md
%{_bindir}/eg25-manager
%{_datadir}/eg25-manager/
%{_unitdir}/eg25-manager.service
%{_udevrulesdir}/80-modem-eg25.rules
%{_mandir}/man5/eg25-manager.5*
%{_mandir}/man8/eg25-manager.8*

%changelog
* Sat Oct 10 2026 Jon's Fedora PinePhone Pro build - 0.5.2-3
- Fresh recovery recipe using the independently reacquired pinned upstream commit.
- Require ModemManager support and generated manpages; retain upstream config and unit.
