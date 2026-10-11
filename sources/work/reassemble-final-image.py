#!/usr/bin/env python3
"""Verify downloaded image parts and decode directly to a new raw image.

Requires standard-library Python 3 with lzma (Linux/macOS). Verify the manifest's
delivery checksum first. Parts belong beside the manifest; no complete .xz is
created. This does not flash a device or establish physical-phone operation.
"""
import argparse
import hashlib
import json
import lzma
import os
from pathlib import Path
import re
import stat
import sys

IMAGE_NAME = 'Fedora-44-Plasma-Mobile-PinePhone-Pro-eMMC-20261010.img'
IMAGE_BYTES = 14 * 1024**3
MAX_PART_BYTES = 40 * 1024**2
CHUNK_BYTES = 1024**2


def require(condition, message):
    if not condition:
        raise ValueError(message)


def fingerprint(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def open_regular(path):
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode), 'Expected a nonsymlink regular file: ' + path.name)
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    try:
        require(fingerprint(os.fstat(fd)) == fingerprint(before), 'Input changed while opening: ' + path.name)
        return os.fdopen(fd, 'rb'), before
    except BaseException:
        os.close(fd)
        raise


def unchanged(path, handle, before):
    require(fingerprint(os.fstat(handle.fileno())) == fingerprint(before)
            and fingerprint(path.lstat()) == fingerprint(before), 'Input changed: ' + path.name)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Duplicate manifest key: ' + key)
        result[key] = value
    return result


def read_manifest(path, expected_size, expected_filename):
    handle, before = open_regular(path)
    with handle:
        require(0 < before.st_size <= 1024**2, 'Manifest is empty or exceeds 1 MiB.')
        raw = handle.read(1024**2 + 1)
        unchanged(path, handle, before)
    manifest = json.loads(raw, object_pairs_hook=unique_object)
    keys = {'format', 'status', 'output_filename', 'output_size_bytes', 'output_sha256',
            'part_size_bytes', 'source_filename', 'source_size_bytes', 'source_sha256',
            'physical_hardware_tested', 'parts'}
    require(isinstance(manifest, dict) and set(manifest) == keys, 'Unsupported manifest fields.')
    require(manifest['format'] == 'ordered-byte-parts-v1'
            and manifest['status'] == 'verified_image_compression_hardware_untested'
            and manifest['physical_hardware_tested'] is False, 'Manifest is not a finalized, hardware-untested delivery.')
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]*\.img', expected_filename) is not None,
            'Invalid expected raw filename.')
    require(manifest['source_filename'] == expected_filename
            and manifest['output_filename'] == expected_filename + '.xz', 'Image filenames differ from the expected delivery.')
    require(type(manifest['source_size_bytes']) is int and manifest['source_size_bytes'] == expected_size,
            'Raw image size differs from the expected delivery.')
    for key in ('source_sha256', 'output_sha256'):
        require(isinstance(manifest[key], str) and re.fullmatch(r'[0-9a-f]{64}', manifest[key]) is not None,
                'Invalid SHA256: ' + key)
    part_size = manifest['part_size_bytes']
    require(type(part_size) is int and 0 < part_size <= MAX_PART_BYTES, 'Part size must be at most 40 MiB.')
    parts = manifest['parts']
    require(isinstance(parts, list) and 0 < len(parts) <= 4096, 'Invalid part count.')
    offset = 0
    for index, part in enumerate(parts):
        require(isinstance(part, dict) and set(part) == {'index', 'filename', 'offset_bytes', 'size_bytes', 'sha256'},
                'Unsupported part record.')
        require(type(part['index']) is int and part['index'] == index
                and type(part['offset_bytes']) is int and part['offset_bytes'] == offset, 'Parts are out of order.')
        require(part['filename'] == f'{expected_filename}.xz.part{index:03d}', 'Unsafe or unexpected part basename.')
        size = part['size_bytes']
        require(type(size) is int and 0 < size <= part_size
                and (index == len(parts) - 1 or size == part_size), 'Invalid part length.')
        require(isinstance(part['sha256'], str) and re.fullmatch(r'[0-9a-f]{64}', part['sha256']) is not None,
                'Invalid part SHA256.')
        offset += size
    require(type(manifest['output_size_bytes']) is int and manifest['output_size_bytes'] == offset,
            'Compressed total length differs from the part inventory.')
    return manifest, raw, fingerprint(before)


def part_stream(directory, parts, fingerprints, first_pass=False):
    for part in parts:
        path = directory / part['filename']
        handle, before = open_regular(path)
        with handle:
            require(before.st_size == part['size_bytes'], 'Wrong part size: ' + path.name)
            if not first_pass:
                require(fingerprint(before) == fingerprints[path.name], 'Part changed between passes: ' + path.name)
            digest = hashlib.sha256()
            total = 0
            while block := handle.read(CHUNK_BYTES):
                total += len(block)
                require(total <= part['size_bytes'], 'Part grew while reading: ' + path.name)
                digest.update(block)
                yield block
            unchanged(path, handle, before)
            require(total == part['size_bytes'] and digest.hexdigest() == part['sha256'], 'Part SHA256/size mismatch: ' + path.name)
            if first_pass:
                fingerprints[path.name] = fingerprint(before)


def decode_parts(blocks, target, manifest):
    decoder = lzma.LZMADecompressor(format=lzma.FORMAT_XZ, memlimit=256 * 1024**2)
    compressed, raw_hash = hashlib.sha256(), hashlib.sha256()
    compressed_bytes = raw_bytes = 0
    for block in blocks:
        compressed.update(block)
        compressed_bytes += len(block)
        require(not decoder.eof, 'Additional data or concatenated XZ stream is forbidden.')
        while True:
            decoded = decoder.decompress(block, max_length=CHUNK_BYTES)
            block = b''
            raw_bytes += len(decoded)
            require(raw_bytes <= manifest['source_size_bytes'], 'Decoded image exceeds the expected raw size.')
            raw_hash.update(decoded)
            target.write(decoded)
            if decoder.eof:
                require(not decoder.unused_data, 'Additional data or concatenated XZ stream is forbidden.')
                break
            if decoder.needs_input:
                break
    require(decoder.eof, 'Truncated XZ stream.')
    require(compressed_bytes == manifest['output_size_bytes']
            and compressed.hexdigest() == manifest['output_sha256'], 'Compressed stream changed during decoding.')
    require(raw_bytes == manifest['source_size_bytes'] and raw_hash.hexdigest() == manifest['source_sha256'],
            'Decoded raw size or SHA256 mismatch.')


def remove_owned(path, identity, preserve_foreign=False):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    owned = stat.S_ISREG(info.st_mode) and (info.st_dev, info.st_ino) == identity
    if preserve_foreign and not owned:
        return
    require(owned, 'Cleanup refuses a replaced file: ' + path.name)
    path.unlink()


def verify_written_output(path, identity, manifest):
    handle, before = open_regular(path)
    with handle:
        require((before.st_dev, before.st_ino) == identity, 'Published output was replaced before readback.')
        require(before.st_size == manifest['source_size_bytes'], 'Written raw length differs during readback.')
        digest, total = hashlib.sha256(), 0
        while block := handle.read(CHUNK_BYTES):
            total += len(block)
            require(total <= manifest['source_size_bytes'], 'Written output grew during readback.')
            digest.update(block)
        unchanged(path, handle, before)
        require(total == manifest['source_size_bytes'] and digest.hexdigest() == manifest['source_sha256'],
                'Written raw size or SHA256 mismatch during readback.')


def reassemble(manifest_path, output_directory=None, *, expected_size=IMAGE_BYTES, expected_filename=IMAGE_NAME):
    """The CLI fixes the production identity; small disposable fixtures use this core."""
    manifest_path = Path(manifest_path).absolute()
    manifest, original_manifest, manifest_identity = read_manifest(manifest_path, expected_size, expected_filename)
    directory = manifest_path.parent
    destination = Path(output_directory).resolve(strict=True) if output_directory is not None else directory
    require(destination.is_dir(), 'Output directory must already exist.')
    output = destination / manifest['source_filename']
    temporary = destination / (manifest['source_filename'] + '.assembling')
    for path in (output, temporary):
        require(not path.exists() and not path.is_symlink(), 'Output or temporary already exists; preserve it: ' + path.name)
    fingerprints, whole = {}, hashlib.sha256()
    for block in part_stream(directory, manifest['parts'], fingerprints, first_pass=True):
        whole.update(block)
    require(whole.hexdigest() == manifest['output_sha256'], 'Compressed stream SHA256 mismatch.')
    directory_fd = os.open(destination, os.O_RDONLY | os.O_DIRECTORY)
    identity = None
    try:
        with temporary.open('xb') as target:
            info = os.fstat(target.fileno())
            identity = (info.st_dev, info.st_ino)
            decode_parts(part_stream(directory, manifest['parts'], fingerprints), target, manifest)
            target.flush()
            os.fsync(target.fileno())
            require(os.fstat(target.fileno()).st_size == expected_size, 'Written raw length differs.')
            _, current_bytes, current_identity = read_manifest(manifest_path, expected_size, expected_filename)
            require(current_bytes == original_manifest and current_identity == manifest_identity,
                    'Manifest changed during reconstruction.')
            current_temp = temporary.lstat()
            require((current_temp.st_dev, current_temp.st_ino) == identity
                    and stat.S_ISREG(current_temp.st_mode), 'Temporary output was replaced.')
            os.link(temporary, output, follow_symlinks=False)
            linked = output.lstat()
            require(stat.S_ISREG(linked.st_mode) and (linked.st_dev, linked.st_ino) == identity,
                    'Published output does not match the verified temporary inode.')
            os.fsync(directory_fd)
            remove_owned(temporary, identity)
            os.fsync(directory_fd)
        verify_written_output(output, identity, manifest)
        return {'filename': str(output), 'bytes': expected_size, 'sha256': manifest['source_sha256'],
                'part_count': len(manifest['parts']), 'physical_hardware_tested': False}
    except BaseException as error:
        cleanup_errors = []
        if identity is not None:
            # The link may have succeeded immediately before an interruption.
            # Infer ownership from the inode, not a flag set after publication.
            for path, preserve_foreign in ((output, True), (temporary, False)):
                try:
                    remove_owned(path, identity, preserve_foreign)
                except BaseException as cleanup_error:
                    cleanup_errors.append(str(cleanup_error) or type(cleanup_error).__name__)
            try:
                os.fsync(directory_fd)
            except BaseException as cleanup_error:
                cleanup_errors.append(str(cleanup_error) or type(cleanup_error).__name__)
        if cleanup_errors:
            raise RuntimeError(f'{type(error).__name__}: {error}; cleanup incomplete: ' + '; '.join(cleanup_errors)) from error
        raise
    finally:
        os.close(directory_fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', nargs='?', default='image-parts-manifest.json')
    parser.add_argument('--output-dir', help='Existing destination directory; defaults to the manifest directory.')
    args = parser.parse_args()
    result = reassemble(args.manifest, args.output_dir)
    print('RAW_IMAGE_REASSEMBLED_AND_VERIFIED ' + result['filename'])
    print('BYTES=' + str(result['bytes']) + '\nSHA256=' + result['sha256'])
    print('Physical PinePhone Pro operation remains untested. No device was flashed.')


if __name__ == '__main__':
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        print('Final image reassembly failed: ' + (str(error) or type(error).__name__), file=sys.stderr)
        sys.exit(1)
