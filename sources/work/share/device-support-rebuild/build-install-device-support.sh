#!/usr/bin/env bash
# Fresh future guest recipe. This file is source, not a successful execution record.
set -Eeuo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
export LC_ALL=C
trap 'result=$?; printf "DEVICE_SUPPORT_REBUILD_FAILED exit=%s line=%s\n" "$result" "$LINENO" >&2; exit "$result"' ERR
[[ $EUID == 0 && $(uname -m) == aarch64 && $(uname -r) == 7.2.9-jon-ppp && $(rpm -E '%{fedora}') == 44 ]]
[[ $(findmnt -n -o FSTYPE --target /build) == 9p ]]
[[ $# == 1 || ( $# == 2 && $2 == --build-atinout-supplement ) ]]
[[ $1 == /* && -d $1 && ! -L $1 && $(readlink -f -- "$1") == "$1" ]]
kit=$1
build_atinout=0
[[ $# == 1 ]] || build_atinout=1
[[ -s /build/live-build-network.sh && -s /run/ppp-build-ca-bundle.pem ]]
source /build/live-build-network.sh
dnf_options=(--setopt=sslcacert=/run/ppp-build-ca-bundle.pem --setopt=proxy_sslcacert=/run/ppp-build-ca-bundle.pem)
topdir=/tmp/ppp-device-support-rpmbuild
exports=/build/packaged-rpms
report=/build/fedora-device-support-install-report.json
[[ ! -e $topdir && ! -L $topdir && ! -e $report && ! -L $report ]]
[[ ! -L $exports ]]
mkdir -p -- "$exports"
[[ $(readlink -f -- "$exports") == "$exports" ]]
for name in eg25-manager-0.5.2-3.fc44.aarch64.rpm eg25-manager-0.5.2-3.fc44.src.rpm \
  pinephonepro-device-support-10-3.fc44.noarch.rpm pinephonepro-device-support-10-3.fc44.src.rpm \
  atinout-pinephonepro-0.9.1-3.fc44.aarch64.rpm atinout-pinephonepro-0.9.1-3.fc44.src.rpm; do
  [[ ! -e $exports/$name && ! -L $exports/$name ]]
done
python3 "$kit/prepare-rpmbuild.py" "$topdir"
# Use the owning Fedora44 repository/signature configuration without adding repos.
atinout_dependency=()
(( build_atinout == 1 )) || atinout_dependency=(atinout)
dnf "${dnf_options[@]}" -y install rpm-build gcc meson ninja-build pkgconf-pkg-config glib2-devel \
  libgudev-devel libgpiod-devel libusb1-devel libcurl-devel ModemManager-glib-devel \
  scdoc systemd-rpm-macros alsa-ucm feedbackd bluez brcmfmac-firmware ModemManager NetworkManager "${atinout_dependency[@]}"
if (( build_atinout == 1 )); then
  if rpm -qf -- /usr/bin/atinout >/dev/null 2>&1 || [[ -e /usr/bin/atinout || -L /usr/bin/atinout ]]; then
    printf 'ATINOUT_SUPPLEMENT_OWNERSHIP_CONFLICT /usr/bin/atinout\n' >&2
    exit 1
  fi
  rpmbuild --define "_topdir $topdir" --define 'debug_package %{nil}' \
    -ba "$topdir/SPECS/atinout-pinephonepro.spec"
  supplemental=$topdir/RPMS/aarch64/atinout-pinephonepro-0.9.1-3.fc44.aarch64.rpm
  [[ $(rpm -qp --qf '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}' "$supplemental") == atinout-pinephonepro-0.9.1-3.fc44.aarch64 ]]
  dnf "${dnf_options[@]}" -y install "$supplemental"
  [[ $(rpm -q --qf '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}' atinout-pinephonepro) == atinout-pinephonepro-0.9.1-3.fc44.aarch64 ]]
  rpm -V atinout-pinephonepro
fi
[[ -x /usr/bin/atinout ]]
/usr/bin/atinout --version
# Never replace a signed Fedora file or a preexisting unowned input. The actual
# resolved package inventory takes precedence over the observed public file list.
for path in /usr/share/alsa/ucm2/PinePhonePro/HiFi.conf \
  /usr/share/alsa/ucm2/PinePhonePro/VoiceCall.conf \
  /usr/share/alsa/ucm2/PinePhonePro/PINE64-PinePhonePro-.conf \
  /usr/share/alsa/ucm2/conf.d/simple-card/PINE64-PinePhonePro-.conf \
  /usr/share/alsa/ucm2/conf.d/simple-card/simple-card.conf \
  /usr/bin/pinephone_setup-modem /usr/lib/udev/rules.d/90-modem-eg25.rules \
  /usr/share/feedbackd/themes/pine64,pinephone-pro.json \
  /usr/lib/firmware/brcm/BCM4345C0.hcd /usr/lib/firmware/brcm/BCM4345C5.hcd; do
  if rpm -qf -- "$path" >/dev/null 2>&1 || [[ -e $path || -L $path ]]; then
    printf 'DEVICE_SUPPORT_OWNERSHIP_CONFLICT %s\n' "$path" >&2
    exit 1
  fi
done
rpmbuild --define "_topdir $topdir" --define 'debug_package %{nil}' \
  -ba "$topdir/SPECS/eg25-manager.spec"
rpmbuild --define "_topdir $topdir" --define 'debug_package %{nil}' \
  -ba "$topdir/SPECS/pinephonepro-device-support.spec"
eg25=$topdir/RPMS/aarch64/eg25-manager-0.5.2-3.fc44.aarch64.rpm
device=$topdir/RPMS/noarch/pinephonepro-device-support-10-3.fc44.noarch.rpm
[[ $(rpm -qp --qf '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}' "$eg25") == eg25-manager-0.5.2-3.fc44.aarch64 ]]
[[ $(rpm -qp --qf '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}' "$device") == pinephonepro-device-support-10-3.fc44.noarch ]]
dnf "${dnf_options[@]}" -y install "$eg25" "$device"
[[ $(rpm -q --qf '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}' eg25-manager) == eg25-manager-0.5.2-3.fc44.aarch64 ]]
[[ $(rpm -q --qf '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}' pinephonepro-device-support) == pinephonepro-device-support-10-3.fc44.noarch ]]
rpm -V eg25-manager pinephonepro-device-support
# These four actual upstream units have install targets; no daemon start is claimed.
systemctl --root=/ enable eg25-manager.service ModemManager.service NetworkManager.service bluetooth.service
for unit in eg25-manager.service ModemManager.service NetworkManager.service bluetooth.service; do
  systemctl --root=/ is-enabled --quiet "$unit"
done
for path in /usr/lib/firmware/brcm/BCM4345C0.hcd /usr/lib/firmware/brcm/BCM4345C5.hcd \
  /usr/share/alsa/ucm2/PinePhonePro/PINE64-PinePhonePro-.conf \
  /usr/share/feedbackd/themes/pine64,pinephone-pro.json \
  /usr/share/eg25-manager/pine64,pinephone-pro.toml; do
  [[ -s $path ]]
done
for path in /usr/lib/firmware/brcm/brcmfmac43455-sdio.bin \
  /usr/lib/firmware/brcm/brcmfmac43455-sdio.clm_blob \
  /usr/lib/firmware/brcm/brcmfmac43455-sdio.pine64,pinephone-pro.txt; do
  [[ -s $path || -s $path.xz || -s $path.zst ]]
done
dnf "${dnf_options[@]}" check
python3 - "$topdir" "$exports" "$report" "$kit/rpmbuild-inputs.json" "$build_atinout" <<'PY'
import datetime, hashlib, json, os, pathlib, stat, subprocess, sys, uuid
top, exports, report, source_inventory = map(pathlib.Path, sys.argv[1:5])
build_atinout = sys.argv[5] == '1'
paths = [top/'RPMS/aarch64/eg25-manager-0.5.2-3.fc44.aarch64.rpm',
         top/'SRPMS/eg25-manager-0.5.2-3.fc44.src.rpm',
         top/'RPMS/noarch/pinephonepro-device-support-10-3.fc44.noarch.rpm',
         top/'SRPMS/pinephonepro-device-support-10-3.fc44.src.rpm']
supplemental_nevras = []
if build_atinout:
    supplemental_nevras = subprocess.check_output(['rpm','-q','--qf','%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\n','atinout-pinephonepro'], text=True).splitlines()
    assert supplemental_nevras == ['atinout-pinephonepro-0.9.1-3.fc44.aarch64']
    subprocess.run(['rpm','-V','atinout-pinephonepro'], check=True)
    paths += [top/'RPMS/aarch64/atinout-pinephonepro-0.9.1-3.fc44.aarch64.rpm',
              top/'SRPMS/atinout-pinephonepro-0.9.1-3.fc44.src.rpm']
artifacts = []
for source in paths:
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= 8*1024*1024
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            data = stream.read(8*1024*1024+1)
        after = os.fstat(fd)
        fp = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        assert fp(before) == fp(after) == fp(source.lstat()) and len(data) == before.st_size
    finally:
        os.close(fd)
    destination = exports/source.name
    with destination.open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    assert destination.read_bytes() == data
    artifacts.append({'filename':source.name, 'path':str(destination), 'size':len(data), 'sha256':hashlib.sha256(data).hexdigest()})
nevras = subprocess.check_output(['rpm','-q','--qf','%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\n', 'eg25-manager','pinephonepro-device-support'], text=True).splitlines()
assert nevras == ['eg25-manager-0.5.2-3.fc44.aarch64','pinephonepro-device-support-10-3.fc44.noarch']
subprocess.run(['rpm','-V','eg25-manager','pinephonepro-device-support'], check=True)
payload = {'schema_version':1, 'status':'device_support_built_installed_verified',
           'completed_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
           'fresh_release3_recipes':True, 'installed_nevras':nevras,
           'rpm_verify_passed':True, 'dnf_check_passed':True,
           'services_enabled':['eg25-manager.service','ModemManager.service','NetworkManager.service','bluetooth.service'],
           'services_started_claimed':False, 'hardware_verified':False,
           'supplemental_nevras':supplemental_nevras,
           'source_inputs_sha256':hashlib.sha256(source_inventory.read_bytes()).hexdigest(), 'artifacts':artifacts}
temporary = report.with_name(report.name+'.unfinalized-'+uuid.uuid4().hex)
with temporary.open('xb') as stream:
    stream.write((json.dumps(payload,indent=2)+'\n').encode())
    stream.flush()
    os.fsync(stream.fileno())
os.link(temporary,report,follow_symlinks=False)
temporary.unlink()
PY
printf '%s\n' FEDORA_DEVICE_SUPPORT_RELEASE3_BUILT_INSTALLED_VERIFIED
