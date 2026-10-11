#!/usr/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# Inspect the actual owning repositories/packages before choosing local recipes.
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C
[[ $EUID == 0 && $(uname -m) == aarch64 && $(rpm -E '%{fedora}') == 44 ]]
[[ $(findmnt -n -o FSTYPE --target /build) == 9p ]]
source /build/live-build-network.sh
python3 - <<'PY'
from pathlib import Path
import datetime, json, os, subprocess
report = Path('/build/fedora-device-provider-inspection.json')
assert not report.exists() and not report.is_symlink()
command = ['dnf5', '--quiet', '--setopt=sslcacert=/run/ppp-build-ca-bundle.pem',
           '--setopt=proxy_sslcacert=/run/ppp-build-ca-bundle.pem',
           'repoquery', '--whatprovides', 'atinout', '--queryformat', '%{name}\n']
result = subprocess.run(command, capture_output=True, text=True, check=True)
providers = sorted(set(result.stdout.splitlines()))
assert all(x and all(c.isalnum() or c in '+_.-' for c in x) for x in providers)
paths = ['/usr/share/alsa/ucm2/PinePhonePro/HiFi.conf',
 '/usr/share/alsa/ucm2/PinePhonePro/VoiceCall.conf',
 '/usr/share/alsa/ucm2/PinePhonePro/PINE64-PinePhonePro-.conf',
 '/usr/share/alsa/ucm2/conf.d/simple-card/PINE64-PinePhonePro-.conf',
 '/usr/share/alsa/ucm2/conf.d/simple-card/simple-card.conf',
 '/usr/bin/pinephone_setup-modem', '/usr/lib/udev/rules.d/90-modem-eg25.rules',
 '/usr/share/feedbackd/themes/pine64,pinephone-pro.json',
 '/usr/lib/firmware/brcm/BCM4345C0.hcd', '/usr/lib/firmware/brcm/BCM4345C5.hcd',
 '/usr/bin/atinout']
ownership = []
for name in paths:
    path = Path(name)
    query = subprocess.run(['rpm','-qf','--qf','%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\n',name],
                           capture_output=True,text=True)
    assert query.returncode in (0,1)
    ownership.append({'path':name, 'exists':path.exists(), 'symlink':path.is_symlink(),
                      'rpm_query_exit':query.returncode,
                      'owners':query.stdout.splitlines() if query.returncode == 0 else []})
payload = {'status':'device_provider_ownership_inspection_complete',
 'completed_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'atinout_repository_providers':providers, 'atinout_repoquery_exit':result.returncode,
 'paths':ownership, 'hardware_verified':False}
with report.open('x') as stream:
    json.dump(payload,stream,indent=2,sort_keys=True); stream.write('\n')
    stream.flush(); os.fsync(stream.fileno())
print(json.dumps(payload,indent=2,sort_keys=True))
print('FRESH_FEDORA_DEVICE_PROVIDER_INSPECTION_COMPLETE')
PY
