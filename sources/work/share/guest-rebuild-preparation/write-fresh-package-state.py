#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Future source-VM aggregate. Publish only after actual package/audit checks."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

CORE = ('kernel-pinephone-pro', 'pinephone-pro-kernel-tools', 'pinephonepro-device-support', 'eg25-manager')
EXPECTED = ('kernel-pinephone-pro-7.2.9-3.fc44.aarch64', 'pinephone-pro-kernel-tools-7.2.9-3.fc44.noarch',
            'pinephonepro-device-support-10-3.fc44.noarch', 'eg25-manager-0.5.2-3.fc44.aarch64')


def require(condition, reason):
    if not condition:
        raise SystemExit(reason)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def output(*args):
    return subprocess.check_output(args, text=True).strip()


def record(path):
    require(path.is_file() and not path.is_symlink(), 'Required regular evidence missing: ' + str(path))
    return {'path': str(path), 'size_bytes': path.stat().st_size, 'sha256': digest(path)}


def publish(path, data):
    temporary = path.with_name(path.name + '.unfinalized-' + uuid.uuid4().hex)
    try:
        with temporary.open('xb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.link(temporary, path, follow_symlinks=False)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    require(len(sys.argv) == 2 and os.geteuid() == 0 and output('uname', '-m') == 'aarch64', 'Wrong guest/interface')
    report = Path('/build/fresh-package-state.json')
    tsv = Path('/build/fedora-custom-package-sources.tsv')
    require(not report.exists() and not report.is_symlink() and not tsv.exists() and not tsv.is_symlink(), 'Preserve prior aggregate')
    finish_inputs = json.loads(Path(sys.argv[1]).read_text())
    for name, expected in finish_inputs['files'].items():
        path = Path(name)
        require(record(path)['sha256'] == expected['sha256'] and path.stat().st_size == expected['size_bytes'], 'Finish input changed')
    runtime = [line for line in Path('/build/essential-runtime-packages.txt').read_text().splitlines()
               if line.strip() and not line.lstrip().startswith('#')]
    require(len(runtime) == 28 and len(set(runtime)) == 28 and tuple(runtime[:4]) == CORE, 'Canonical runtime list differs')
    runtime_rows = output('rpm', '-q', '--qf', '%{NAME}\t%{VERSION}-%{RELEASE}\t%{ARCH}\n', *runtime).splitlines()
    require(len(runtime_rows) == 28, 'Runtime inventory has missing/duplicate package records')
    require(tuple(output('rpm', '-q', '--qf', '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\n', *CORE).splitlines()) == EXPECTED,
            'Installed custom package identities differ')
    optional = []
    present = subprocess.run(['rpm', '-q', 'atinout-pinephonepro'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    if present:
        require(output('rpm', '-q', '--qf', '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}', 'atinout-pinephonepro')
                == 'atinout-pinephonepro-0.9.1-3.fc44.aarch64', 'Supplemental package identity differs')
        require('atinout = 0.9.1-3.fc44' in output('rpm', '-q', '--provides', 'atinout-pinephonepro').splitlines(),
                'Supplemental atinout capability missing')
        optional = ['atinout-pinephonepro']
    names = [*CORE, *optional]
    subprocess.run(['rpm', '--noscripts', '-V', *names], check=True)
    require(output('rpm', '-qf', '--qf', '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}',
                   '/usr/share/pinephone-pro/kernel/7.2.9-jon-ppp/Image') == EXPECTED[0], 'Kernel payload owner differs')
    kernel_path = Path('/build/fedora-kernel-install-report.json')
    device_path = Path('/build/fedora-device-support-install-report.json')
    kernel, device = json.loads(kernel_path.read_text()), json.loads(device_path.read_text())
    require(kernel['status'] == 'kernel_release3_built_installed_verified' and kernel['installed_module_count'] == 906,
            'Kernel completion evidence missing')
    require(device['status'] == 'device_support_built_installed_verified', 'Device completion evidence missing')
    for helper in kernel['installed_helper_exports']:
        measured, installed = Path(helper['path']), Path(helper['installed_path'])
        require(record(measured)['sha256'] == helper['sha256'] == digest(installed), 'Measured installed helper changed')
    audit_path = Path(kernel['portable_initramfs_audit'])
    audit = json.loads(audit_path.read_text())
    initramfs = Path('/boot/initramfs-7.2.9-jon-ppp.img')
    require(audit['status'] == 'passed' and digest(audit_path) == kernel['portable_initramfs_audit_sha256']
            and audit['archive_sha256'] == digest(initramfs) == kernel['initramfs_sha256']
            and audit['archive_bytes'] == initramfs.stat().st_size, 'Source initramfs/audit changed')
    native_path = Path('/build/fedora-native-portability-audits/summary.json')
    native = json.loads(native_path.read_text())
    require(native['status'] == 'six_actual_GNU_archive_fixtures_passed' and native['fixture_count'] == 6,
            'Native fixtures missing')
    require({entry['name']: entry['status'] for entry in native['audits']} == {
        'newc-gzip': 'passed', 'newc-pigz': 'passed', 'crc-gzip': 'passed',
        'crc-pigz': 'passed', 'early-gzip': 'passed', 'negative': 'failed'}
        and len(native['audits']) == 6, 'Native fixture set differs')
    validator = next((item for item in kernel['installed_helper_exports']
                      if Path(item['installed_path']).name == 'pinephone-pro-initramfs-verify'), None)
    require(validator is not None and native['validator_sha256'] == validator['source_sha256'],
            'Native fixtures used a different validator source')
    for item in native['audits']:
        path = native_path.parent / (item['name'] + '.json')
        require(record(path)['sha256'] == item['sha256'], 'Native fixture audit changed')
        require(json.loads(path.read_text())['status'] == ('failed' if item['name'] == 'negative' else 'passed'), 'Native fixture status differs')
    artifacts = []
    for parent in (json.loads(Path('/build/fedora-kernel-package-build-report.json').read_text())['files'], device['artifacts']):
        for item in parent:
            path = Path(item['path'])
            require(path.parent == Path('/build/packaged-rpms') and record(path)['sha256'] == item['sha256'], 'RPM/SRPM export changed')
            require(path.stat().st_size == item.get('size_bytes', item.get('size')), 'RPM/SRPM export size differs')
            artifacts.append(record(path))
    packages, rows = [], []
    for name in names:
        fields = output('rpm', '-q', '--qf', '%{NAME}\t%{VERSION}-%{RELEASE}\t%{ARCH}\t%{SOURCERPM}', name).split('\t')
        require(len(fields) == 4 and all('\n' not in field for field in fields), 'Package source identity ambiguous')
        binary = next((item for item in artifacts if Path(item['path']).name == fields[0] + '-' + fields[1] + '.' + fields[2] + '.rpm'), None)
        source = next((item for item in artifacts if Path(item['path']).name == fields[3]), None)
        require(binary is not None and source is not None, 'Installed package lacks matching binary/source artifact proof')
        packages.append({'name': fields[0], 'version_release': fields[1], 'architecture': fields[2], 'source_rpm': fields[3],
                         'requires': output('rpm', '-q', '--requires', name).splitlines(),
                         'provides': output('rpm', '-q', '--provides', name).splitlines(),
                         'binary_artifact': binary, 'source_artifact': source})
        rows.append('\t'.join(fields))
    require(output('passwd', '-S', 'root').split()[1] == 'L', 'Root account is unlocked')
    import pwd
    require(not any(1000 <= row.pw_uid < 65534 for row in pwd.getpwall()), 'Normal user pre-created before Plasma Setup')
    require(output('kreadconfig6', '--file', '/etc/plasmalogin.conf.d/90-pinephonepro.conf', '--group', 'Greeter', '--key', 'PreselectedSession')
            == 'plasma-mobile.desktop', 'Plasma Mobile selection differs')
    require(output('kreadconfig6', '--file', '/etc/xdg/kwinrc', '--group', 'Wayland', '--key', 'InputMethod')
            == '/usr/share/applications/org.kde.plasma.keyboard.desktop', 'Keyboard input method differs')
    require(output('kreadconfig6', '--file', '/etc/xdg/kwinrc', '--group', 'Wayland', '--key', 'VirtualKeyboardEnabled') == 'true', 'Virtual keyboard disabled')
    units = ('plasmalogin.service', 'eg25-manager.service', 'ModemManager.service', 'NetworkManager.service',
             'bluetooth.service', 'pinephone-pro-grow-root.service')
    for unit in units:
        subprocess.run(['systemctl', '--root=/', 'is-enabled', '--quiet', unit], check=True)
    require(Path('/etc/systemd/system/display-manager.service').resolve()
            == Path('/usr/lib/systemd/system/plasmalogin.service'), 'Display-manager alias differs')
    require(output('systemctl', '--root=/', 'get-default') == 'graphical.target', 'Default target differs')
    for program in ('growpart', 'sgdisk', 'resize2fs', 'partx', 'flock'):
        require(shutil.which(program) is not None, 'Root-growth tool missing')
    for source, installed in (('/build/image-assembly/pinephone-pro-grow-root', '/usr/sbin/pinephone-pro-grow-root'),
                              ('/build/image-assembly/pinephone-pro-grow-root.service', '/usr/lib/systemd/system/pinephone-pro-grow-root.service')):
        require(record(Path(source))['sha256'] == record(Path(installed))['sha256'], 'Installed growth recipe differs')
    atinout_provider_rows = output('rpm', '-q', '--whatprovides', 'atinout', '--qf',
                                  '%{NAME}\t%{VERSION}-%{RELEASE}\t%{ARCH}\t%{SOURCERPM}\n').splitlines()
    atinout_owner = output('rpm', '-qf', '--qf', '%{NAME}\t%{VERSION}-%{RELEASE}\t%{ARCH}\t%{SOURCERPM}', '/usr/bin/atinout')
    require(atinout_owner in atinout_provider_rows, 'Atinout binary owner differs from installed capability provider')
    subprocess.run(['rpmdb', '--verifydb'], check=True)
    subprocess.run(['dnf5', '--setopt=sslcacert=/run/ppp-build-ca-bundle.pem',
                    '--setopt=proxy_sslcacert=/run/ppp-build-ca-bundle.pem', 'check'], check=True)
    payload = {'schema_version': 1, 'status': 'fresh_phone_packages_verified',
               'completed_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
               'rpm_integrity_exit': 0, 'rpm_integrity_scope': names, 'dnf_check_exit': 0, 'rpmdb_verify_exit': 0,
               'single_custom_kernel_owner': True, 'essential_runtime_packages_verified': 28,
               'essential_runtime_inventory': runtime_rows, 'supplemental_custom_packages': optional,
               'atinout_provider_inventory': atinout_provider_rows, 'atinout_binary_owner': atinout_owner,
               'custom_packages': packages, 'installed_helper_exports': kernel['installed_helper_exports'],
               'kernel_install_report': record(kernel_path), 'device_support_install_report': record(device_path),
               'native_fixture_summary': record(native_path), 'native_fixture_count': 6,
               'source_initramfs_audit': record(audit_path), 'source_initramfs': record(initramfs),
               'source_tsv_path': str(tsv), 'services_enabled': list(units), 'services_started_claimed': False,
               'plasma_setup_preserved': True, 'root_locked': True, 'normal_users_created': False,
               'physical_hardware_tested': False, 'graphical_interaction_tested': False}
    publish(tsv, ('\n'.join(rows) + '\n').encode())
    payload['source_tsv_sha256'] = digest(tsv)
    publish(report, (json.dumps(payload, indent=2, sort_keys=True) + '\n').encode())


if __name__ == '__main__':
    main()
