# Fresh recovery recipe. Binary firmware pins are fresh, hardware-untested inputs.
Name:           pinephonepro-device-support
Version:        10
Release:        3%{?dist}
Summary:        PinePhone Pro device configuration and supplemental Bluetooth firmware
License:        MIT AND GPL-3.0-or-later AND LicenseRef-Broadcom-BlueZ
URL:            https://gitlab.postmarketos.org/postmarketOS/pmaports
Source0:        pinephonepro-device-support-10.tar.gz
BuildArch:      noarch
Requires:       eg25-manager >= 0.5.2
Requires:       alsa-ucm >= 1.2.6.2
Requires:       feedbackd
Requires:       bluez
Requires:       brcmfmac-firmware
# The unchanged pmaports udev rule invokes its setup script, which uses atinout.
Requires:       atinout
Requires:       /usr/bin/logger

%description
Pinned postmarketOS PinePhone Pro audio and modem rules, the genuine upstream
PinePhone Pro feedback theme, and supplemental BCM4345C0/C5 Bluetooth firmware.
Canonical Wi-Fi firmware and compressed NVRAM aliases come from Fedora's
brcmfmac-firmware package. This fresh package has not been tested on hardware.

%prep
%autosetup -n pinephonepro-device-support-10

%build
# Device data only.

%check
sha256sum --check --strict SHA256SUMS

%install
install -d %{buildroot}%{_datadir}/alsa/ucm2/PinePhonePro
install -m 0644 pmaports/ucm/HiFi.conf pmaports/ucm/VoiceCall.conf \
  pmaports/ucm/PINE64-PinePhonePro-.conf %{buildroot}%{_datadir}/alsa/ucm2/PinePhonePro/
install -d %{buildroot}%{_datadir}/alsa/ucm2/conf.d/simple-card
ln -s ../../PinePhonePro/PINE64-PinePhonePro-.conf \
  %{buildroot}%{_datadir}/alsa/ucm2/conf.d/simple-card/PINE64-PinePhonePro-.conf
# This second alias is the workaround explicitly present in the pinned APKBUILD.
ln -s ../../PinePhonePro/PINE64-PinePhonePro-.conf \
  %{buildroot}%{_datadir}/alsa/ucm2/conf.d/simple-card/simple-card.conf
install -D -m 0755 pmaports/setup-modem.sh %{buildroot}%{_bindir}/pinephone_setup-modem
install -D -m 0644 pmaports/90-modem-eg25.rules \
  %{buildroot}%{_prefix}/lib/udev/rules.d/90-modem-eg25.rules
install -D -m 0644 feedback/pine64,pinephone-pro.json \
  %{buildroot}%{_datadir}/feedbackd/themes/pine64,pinephone-pro.json
install -d %{buildroot}%{_prefix}/lib/firmware/brcm
install -m 0644 bluetooth/BCM4345C0.hcd bluetooth/BCM4345C5.hcd \
  %{buildroot}%{_prefix}/lib/firmware/brcm/

%files
%license feedback/COPYING bluetooth/BCM-LEGAL.txt bluetooth/copyright
%doc PROVENANCE.json pmaports/APKBUILD pmaports/source-manifest.json
%{_datadir}/alsa/ucm2/PinePhonePro/
%{_datadir}/alsa/ucm2/conf.d/simple-card/PINE64-PinePhonePro-.conf
%{_datadir}/alsa/ucm2/conf.d/simple-card/simple-card.conf
%{_bindir}/pinephone_setup-modem
%{_prefix}/lib/udev/rules.d/90-modem-eg25.rules
%{_datadir}/feedbackd/themes/pine64,pinephone-pro.json
%{_prefix}/lib/firmware/brcm/BCM4345C0.hcd
%{_prefix}/lib/firmware/brcm/BCM4345C5.hcd

%changelog
* Sat Oct 10 2026 Jon's Fedora PinePhone Pro build - 10-3
- Reconstruct device data from authenticated retained files and fresh pinned upstream inputs.
- Preserve upstream UCM aliases and modem rule; use signed Fedora Wi-Fi firmware provider.
