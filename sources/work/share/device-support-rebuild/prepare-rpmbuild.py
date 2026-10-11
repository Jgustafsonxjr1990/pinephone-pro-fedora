#!/usr/bin/env python3
"""Verify this frozen source inventory and copy inputs to a fresh RPM topdir.

This does not download, build, install, enable services, or execute source code.
Failed partial staging is preserved; the destination must not already exist.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat


def read_regular(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ValueError(f"unsafe source: {path}")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(8 * 1024 * 1024 + 1)
        after = os.fstat(fd)
        named = path.lstat()
        fingerprint = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if len(data) > 8 * 1024 * 1024 or fingerprint(before) != fingerprint(after) or fingerprint(after) != fingerprint(named):
            raise ValueError(f"changed or oversized source: {path}")
        return data
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="new absolute RPM topdir")
    args = parser.parse_args()
    base = Path(__file__).absolute().parent
    if base.resolve() != base:
        raise ValueError("source kit path must be canonical")
    destination = args.destination
    if not destination.is_absolute() or destination.parent.resolve() != destination.parent:
        raise ValueError("destination parent must be an existing canonical directory")
    inventory = json.loads(read_regular(base / "rpmbuild-inputs.json"))
    staged = []
    for row in inventory["files"]:
        relative = Path(row["path"])
        if relative.is_absolute() or len(relative.parts) != 2 or relative.parts[0] not in {"SOURCES", "SPECS"} or ".." in relative.parts:
            raise ValueError("invalid fixed inventory path")
        if (base / relative).parent.resolve() != (base / relative).parent:
            raise ValueError("source ancestor symlink")
        content = read_regular(base / relative)
        if len(content) != row["size"] or hashlib.sha256(content).hexdigest() != row["sha256"]:
            raise ValueError(f"source pin mismatch: {relative}")
        staged.append((relative, content))
    destination.mkdir(mode=0o700)
    for name in ["SOURCES", "SPECS", "BUILD", "BUILDROOT", "RPMS", "SRPMS"]:
        (destination / name).mkdir(mode=0o700)
    for relative, content in staged:
        with (destination / relative).open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    print(json.dumps({"status": "source_inputs_staged", "topdir": str(destination), "files": len(staged), "build_executed": False, "install_executed": False}))


if __name__ == "__main__":
    main()
