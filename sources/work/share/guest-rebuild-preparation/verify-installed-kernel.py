#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Future Fedora source-VM payload/boot verification and measured helper export."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

RELEASE = '7.2.9-jon-ppp'
SOURCE_RPM = 'kernel-pinephone-pro-7.2.9-3.fc44.src.rpm'
ROOT_UUID = '6741cdec-fe58-4214-9fa9-3e8eaa52f476'


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def regular(path):
    require(path.is_file() and not path.is_symlink(), 'Required regular file missing: ' + str(path))


def main():
    require(len(sys.argv) == 2 and os.geteuid() == 0, 'usage: verify-installed-kernel.py INPUT_MANIFEST (root)')
    inputs_path = Path(sys.argv[1])
    inputs = json.loads(inputs_path.read_text())
    require(command('uname', '-m') == 'aarch64' and command('uname', '-r') == RELEASE, 'Wrong guest kernel/architecture')
    report = Path('/build/fedora-kernel-install-report.json')
    require(not report.exists() and not report.is_symlink(), 'Preserve previous installed-kernel report')
    package_names = ('kernel-pinephone-pro', 'pinephone-pro-kernel-tools')
    expected = ('kernel-pinephone-pro-7.2.9-3.fc44.aarch64', 'pinephone-pro-kernel-tools-7.2.9-3.fc44.noarch')
    actual = command('rpm', '-q', '--qf', '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\n', *package_names).splitlines()
    require(tuple(actual) == expected, 'Unexpected installed kernel/tools NEVRA')
    source_ids = command('rpm', '-q', '--qf', '%{SOURCERPM}\n', *package_names).splitlines()
    require(source_ids == [SOURCE_RPM, SOURCE_RPM], 'Installed kernel/tools source RPM identity differs')
    subprocess.run(['rpm', '--noscripts', '-V', *package_names], check=True)
    provides = command('rpm', '-q', '--provides', package_names[0]).splitlines()
    require('kernel-uname-r(' + RELEASE + ')' in provides and 'installonlypkg(kernel)' in provides,
            'Literal uname capability or installonly capability missing')
    requires = command('rpm', '-q', '--requires', package_names[0]).splitlines()
    require(not any(re.match(r'^(?:kernel\(|ksym\(|kernel-uname-r(?:\s|\())', x) for x in requires),
            'Unexpected external module/kernel ABI requirement')
    payload = Path('/usr/share/pinephone-pro/kernel') / RELEASE
    modules = Path('/usr/lib/modules') / RELEASE
    subprocess.run(['sha256sum', '--check', '--strict', 'SHA256SUMS'], cwd=payload, check=True)
    manifest = json.loads((payload / 'source-manifest.json').read_text())
    require(manifest['kernel_release'] == RELEASE and manifest['module_count'] == 906
            and manifest['modules_signed'] is True, 'Compiled payload identity differs')
    hashes = manifest['module_sha256']
    found = {p.relative_to(modules).as_posix(): p for p in modules.rglob('*.ko')}
    require(len(found) == 906 and set(found) == set(hashes), 'Installed module inventory differs')
    for name, path in found.items():
        regular(path)
        data = path.read_bytes()
        require(hashlib.sha256(data).hexdigest() == hashes[name], 'Installed signed module hash differs: ' + name)
        require(data[:6] == b'\x7fELF\x02\x01' and struct.unpack_from('<H', data, 18)[0] == 183,
                'Installed module architecture differs: ' + name)
        magic = re.search(rb'(?:^|\0)vermagic=([^\0]+)\0', data)
        require(magic is not None and magic[1].split(b' ')[0] == RELEASE.encode(), 'Module vermagic differs: ' + name)
        require(data.endswith(b'~Module signature appended~\n'), 'Signed module trailer missing: ' + name)
    subprocess.run(['sha256sum', '--check', '--strict', '--quiet', str(payload / 'MODULES_SHA256SUMS')], cwd=modules, check=True)
    for name in ('modules.alias', 'modules.alias.bin', 'modules.dep', 'modules.dep.bin',
                 'modules.builtin', 'modules.builtin.modinfo', 'modules.order'):
        regular(modules / name)
    with (payload / 'Image').open('rb') as stream:
        header = stream.read(64)
    require(header[56:60] == b'ARM\x64' and struct.unpack_from('<Q', header, 16)[0] == inputs['payload']['image_reserved_memory_bytes'],
            'ARM64 Image header differs')
    require((payload / 'Image').stat().st_size == inputs['payload']['image_file_bytes'], 'Image file size differs')
    require((payload / 'rk3399-pinephone-pro.dtb').read_bytes()[:4] == bytes.fromhex('d00dfeed'), 'Invalid DTB header')
    destination = Path('/build/fedora-installed-kernel-tools')
    require(destination.resolve() == destination and not destination.exists() and not destination.is_symlink(),
            'Preserve prior installed helper export')
    destination.mkdir(mode=0o755)
    helper_records = []
    for name in ('pinephone-pro-kernel-update', 'pinephone-pro-initramfs-verify'):
        installed = Path('/usr/sbin') / name
        source = Path('/build/fedora-kernel-packaging/SOURCES') / name
        regular(installed); regular(source)
        source_bytes, installed_bytes = source.read_bytes(), installed.read_bytes()
        require(command('rpm', '-qf', '--qf', '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}', str(installed)) == expected[1],
                'Installed helper has unexpected owner')
        if name == 'pinephone-pro-kernel-update':
            require(source_bytes == installed_bytes, 'Updater changed after RPM build')
        else:
            source_line, source_body = source_bytes.split(b'\n', 1)
            installed_line, installed_body = installed_bytes.split(b'\n', 1)
            require(source_body == installed_body and installed_line.split()[0] == b'#!/usr/bin/python3',
                    'Validator differs beyond the RPM-owned Python shebang')
        target = destination / name
        with target.open('xb') as stream:
            stream.write(installed_bytes); stream.flush(); os.fsync(stream.fileno())
        target.chmod(0o755)
        helper_records.append({'path': str(target), 'installed_path': str(installed),
                               'size_bytes': len(installed_bytes), 'sha256': digest(target),
                               'source_sha256': hashlib.sha256(source_bytes).hexdigest(),
                               'source_shebang': source_bytes.split(b'\n', 1)[0].decode('ascii'),
                               'installed_shebang': installed_bytes.split(b'\n', 1)[0].decode('ascii'),
                               'body_equivalent': source_bytes.split(b'\n', 1)[1] == installed_bytes.split(b'\n', 1)[1]})
    initrd = Path('/boot/initramfs-' + RELEASE + '.img')
    fat = Path('/boot/efi/pinephone-pro') / RELEASE
    boot_pairs = ((payload / 'Image', Path('/boot/vmlinuz-' + RELEASE)),
                  (payload / 'Image', fat / 'Image'),
                  (payload / 'config', Path('/boot/config-' + RELEASE)),
                  (payload / 'System.map', Path('/boot/System.map-' + RELEASE)),
                  (payload / 'rk3399-pinephone-pro.dtb', Path('/boot/dtb-' + RELEASE + '/rockchip/rk3399-pinephone-pro.dtb')),
                  (payload / 'rk3399-pinephone-pro.dtb', fat / 'rk3399-pinephone-pro.dtb'),
                  (initrd, fat / 'initramfs.img'))
    for left, right in boot_pairs:
        regular(left); regular(right)
        require(left.stat().st_size > 0 and left.stat().st_size == right.stat().st_size and digest(left) == digest(right),
                'Published boot artifact differs: ' + str(right))
    require(command('findmnt', '-n', '-o', 'UUID', '--target', '/') == ROOT_UUID, 'Mounted root UUID differs')
    require(Path('/var/lib/pinephone-pro/default-kernel').read_text() == RELEASE + '\n', 'Wrong default kernel')
    root_args = 'root=UUID=' + ROOT_UUID + ' rootfstype=btrfs rootflags=subvol=root rw '
    for menu, prefix in ((Path('/boot/extlinux/extlinux.conf'), ''), (Path('/boot/efi/extlinux/extlinux.conf'), '/pinephone-pro/' + RELEASE)):
        regular(menu)
        lines = menu.read_text().splitlines()
        require('DEFAULT fedora-ppp' in lines and 'LABEL fedora-ppp' in lines, 'Dedicated phone menu/default missing')
        expected_paths = (('  LINUX ' + prefix + '/Image', '  INITRD ' + prefix + '/initramfs.img',
                           '  FDT ' + prefix + '/rk3399-pinephone-pro.dtb') if prefix else
                          ('  LINUX /vmlinuz-' + RELEASE, '  INITRD /initramfs-' + RELEASE + '.img',
                           '  FDT /dtb-' + RELEASE + '/rockchip/rk3399-pinephone-pro.dtb'))
        require(all(line in lines for line in expected_paths), 'Phone menu uses unexpected boot paths')
        require(any(line.startswith('  APPEND ' + root_args) for line in lines), 'Phone menu root configuration differs')
    audit_path = Path('/build/fedora-source-initramfs-portability.json')
    require(not audit_path.exists() and not audit_path.is_symlink(), 'Preserve existing source initramfs audit')
    # Direct execution checks the actual installed/RPM-mangled interpreter line.
    subprocess.run(['/usr/sbin/pinephone-pro-initramfs-verify', str(initrd), '--audit-json', str(audit_path)], check=True)
    audit = json.loads(audit_path.read_text())
    require(audit['status'] == 'passed' and audit['archive_bytes'] == initrd.stat().st_size
            and audit['archive_sha256'] == digest(initrd), 'Installed initramfs portability audit failed or differs')
    result = {'status': 'kernel_release3_payload_and_boot_verified', 'kernel_release': RELEASE,
              'installed_nevras': actual, 'source_rpm_identities': source_ids,
              'installed_module_count': 906, 'modules_signed': True,
              'brcmfmac_vermagic': command('modinfo', '-k', RELEASE, '-F', 'vermagic', 'brcmfmac'),
              'brcmfmac_signer': command('modinfo', '-k', RELEASE, '-F', 'signer', 'brcmfmac'),
              'installed_helper_exports': helper_records, 'source_root_uuid': ROOT_UUID,
              'initramfs_size_bytes': initrd.stat().st_size, 'initramfs_sha256': digest(initrd),
              'portable_initramfs_audit': str(audit_path), 'portable_initramfs_audit_sha256': digest(audit_path),
              'portable_initramfs_audit_status': audit['status'], 'physical_hardware_tested': False}
    with report.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True); stream.write('\n')
    print('FRESH_FEDORA_KERNEL_PAYLOAD_AND_BOOT_VERIFIED modules=906')


if __name__ == '__main__':
    main()
