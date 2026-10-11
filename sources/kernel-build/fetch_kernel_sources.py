#!/usr/bin/env python3
"""Fetch pinned PPP kernel recipe and validate its files without executing it."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import re
import urllib.request

BASE = Path(__file__).resolve().parent
DEST = BASE / 'sources'
COMMIT = '4b5d202c15567da82a2bcb2d580ec0845e63c1d5'
VERSION = '7.2.9'
ROOT = f'https://gitlab.postmarketos.org/postmarketOS/pmaports/-/raw/{COMMIT}/device/community/linux-pine64-pinephonepro'
DEST.mkdir(parents=True, exist_ok=True)

def fetch(url, path):
    if path.exists() and path.stat().st_size:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.partial')
    with urllib.request.urlopen(url, timeout=120) as response, temporary.open('wb') as output:
        while data := response.read(1024 * 1024):
            output.write(data)
    temporary.rename(path)
    return path

recipe_path = fetch(ROOT + '/APKBUILD', DEST / 'APKBUILD')
recipe = recipe_path.read_text()
sources_match = re.search(r'^source="\n(.*?)\n\s*"', recipe, re.S | re.M)
hashes_match = re.search(r'^sha512sums="\n(.*?)\n"', recipe, re.S | re.M)
if not sources_match or not hashes_match:
    raise RuntimeError('Could not parse pinned APKBUILD source/checksum lists')
files = [line.strip().replace('$_flavor', 'pine64-pinephonepro') for line in sources_match.group(1).splitlines()]
hashes = dict((name, digest) for digest, name in (line.split(None, 1) for line in hashes_match.group(1).splitlines()))
files = [f for f in files if f and not f.startswith('https://')]

def recipe_file(name):
    path = fetch(ROOT + '/' + name, DEST / name)
    digest = hashlib.sha512(path.read_bytes()).hexdigest()
    if hashes.get(path.name) != digest:
        raise RuntimeError(f'SHA512 mismatch: {name}')
    return {'path': name, 'url': ROOT + '/' + name, 'sha512': digest}

with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
    verified = list(executor.map(recipe_file, files))
    kernel_tasks = [
        (f'https://cdn.kernel.org/pub/linux/kernel/v7.x/linux-{VERSION}.tar.xz', DEST / f'linux-{VERSION}.tar.xz'),
        (f'https://cdn.kernel.org/pub/linux/kernel/v7.x/linux-{VERSION}.tar.sign', DEST / f'linux-{VERSION}.tar.sign'),
        ('https://keys.openpgp.org/vks/v1/by-fingerprint/647F28654894E3BD457199BE38DBBDC86092693E', DEST / 'gregkh-release-key.asc'),
    ]
    list(executor.map(lambda args: fetch(*args), kernel_tasks))

tarball = DEST / f'linux-{VERSION}.tar.xz'
sha256 = hashlib.file_digest(tarball.open('rb'), 'sha256').hexdigest()
manifest = {'version': VERSION, 'ppp_recipe_commit': COMMIT, 'recipe_url': ROOT + '/APKBUILD',
            'recipe_sha256': hashlib.sha256(recipe_path.read_bytes()).hexdigest(),
            'source_sha256': sha256, 'source_url': kernel_tasks[0][0],
            'patches_and_config': verified,
            'upstream_release_key_fingerprint': '647F28654894E3BD457199BE38DBBDC86092693E'}
(BASE / 'source-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(f'Fetched kernel {VERSION}; validated {len(verified)} recipe files against pinned SHA512 checksums')
print('Kernel tarball SHA256:', sha256)
