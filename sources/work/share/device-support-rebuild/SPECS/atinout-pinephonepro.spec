# Fresh supplemental source recipe for the retired Fedora atinout dependency.
Name:           atinout-pinephonepro
Version:        0.9.1
Release:        3%{?dist}
Summary:        AT command input/output utility for PinePhone Pro modem setup
License:        GPL-3.0-or-later
URL:            https://atinout.sourceforge.net/
Source0:        atinout-%{version}.tar.gz
BuildRequires:  gcc
Provides:       atinout = %{version}-%{release}

%description
Build the original upstream atinout release as a distinctly named local
supplement for the unchanged PinePhone Pro modem setup script. This package
is not an official Fedora atinout package or a modem hardware test.

%prep
%autosetup -n atinout-%{version}

%build
# The upstream Makefile builds this one C file. Retain Fedora compilation and
# linker flags, explicitly select GNU11 and provide the upstream VERSION define.
%{__cc} %{optflags} -std=gnu11 -DVERSION='"%{version}"' %{?build_ldflags} -o atinout atinout.c

%check
./atinout --version
./atinout --help > /dev/null

%install
install -D -m 0755 atinout %{buildroot}%{_bindir}/atinout
install -D -m 0644 atinout.1 %{buildroot}%{_mandir}/man1/atinout.1

%files
%license gplv3.txt
%doc README Changelog
%{_bindir}/atinout
%{_mandir}/man1/atinout.1*

%changelog
* Sat Oct 10 2026 Jon's Fedora PinePhone Pro build - 0.9.1-3
- Fresh distinctly named source recipe using the authenticated original release.
- Provide the atinout dependency without adding an external binary repository.
