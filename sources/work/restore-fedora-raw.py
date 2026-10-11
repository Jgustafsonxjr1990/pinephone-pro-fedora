#!/usr/bin/env python3
"""Verify the official Fedora XZ and restore its bytes to a new sparse raw file."""
import argparse
import hashlib
import json
import lzma
import os
from pathlib import Path
import stat

EXPECTED_XZ_SHA = 'e09f24daa40d2e0e1331dddd28e6af4e97784fea87005fb74759523dce6a475a'
EXPECTED_XZ_BYTES = 2799988792
EXPECTED_RAW_BYTES = 12206473216
CHUNK = 1024 * 1024
ZERO_BLOCK = bytes(65536)

def fingerprint(s):
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)

def write_sparse(stream, data):
    for offset in range(0, len(data), len(ZERO_BLOCK)):
        block = data[offset:offset + len(ZERO_BLOCK)]
        if not any(block):
            stream.seek(len(block), 1)
        else:
            stream.write(block)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--xz', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args()
    root = Path('/path/to/workspace')
    for path in (args.xz, args.output, args.receipt):
        if not path.is_absolute() or path.resolve() != path or not path.is_relative_to(root):
            raise SystemExit('Use canonical workspace paths')
    if args.output.exists() or args.receipt.exists() or not args.output.name.endswith('.raw.crdownload'):
        raise SystemExit('Preserve existing outputs; new raw requires excluded staging suffix')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    with args.xz.open('rb') as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size != EXPECTED_XZ_BYTES:
            raise SystemExit('Source is not the exact single-link official XZ size')
        xz_sha = hashlib.file_digest(source, 'sha256').hexdigest()
        if xz_sha != EXPECTED_XZ_SHA or fingerprint(os.fstat(source.fileno())) != fingerprint(before):
            raise SystemExit('Official XZ hash or stability check failed')
        source.seek(0)
        decoder = lzma.LZMADecompressor(format=lzma.FORMAT_XZ, memlimit=512 * CHUNK)
        raw_sha = hashlib.sha256()
        total = 0
        next_progress = 1024 * CHUNK
        with args.output.open('xb') as target:
            while not decoder.eof:
                data = source.read(CHUNK) if decoder.needs_input else b''
                if decoder.needs_input and not data:
                    raise SystemExit('Truncated XZ stream; partial output preserved')
                expanded = decoder.decompress(data, max_length=CHUNK)
                total += len(expanded)
                if total > EXPECTED_RAW_BYTES:
                    raise SystemExit('Raw output exceeds expected size; partial preserved')
                raw_sha.update(expanded)
                write_sparse(target, expanded)
                if total >= next_progress:
                    print('RAW_RESTORED_BYTES=' + str(total), flush=True)
                    next_progress += 1024 * CHUNK
            if decoder.unused_data or source.read(1) or total != EXPECTED_RAW_BYTES:
                raise SystemExit('Unexpected XZ tail or raw size; partial preserved')
            target.truncate(total)
            target.flush()
            os.fsync(target.fileno())
        if fingerprint(os.fstat(source.fileno())) != fingerprint(before):
            raise SystemExit('Compressed source changed; no success receipt')
    with args.output.open('rb') as check:
        actual = hashlib.file_digest(check, 'sha256').hexdigest()
    if actual != raw_sha.hexdigest():
        raise SystemExit('Restored raw readback hash mismatch')
    result = {'status': 'official_xz_and_sparse_raw_verified', 'compressed_sha256': xz_sha,
              'compressed_bytes': EXPECTED_XZ_BYTES, 'raw_sha256': actual, 'raw_bytes': total,
              'raw_allocated_bytes': args.output.stat().st_blocks * 512,
              'physical_hardware_tested': False, 'vm_started': False}
    with args.receipt.open('x') as output:
        json.dump(result, output, indent=2, sort_keys=True)
        output.write('\n')
    print(json.dumps(result, sort_keys=True), flush=True)

if __name__ == '__main__':
    main()
