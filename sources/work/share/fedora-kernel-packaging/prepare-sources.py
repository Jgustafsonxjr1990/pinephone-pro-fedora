#!/usr/bin/env python3
"""Stage and validate a matching precompiled kernel for the Fedora RPM build."""

import argparse
import gzip
import hashlib
import json
import re
import shutil
import struct
import tarfile
import tempfile
from pathlib import Path


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        result = hashlib.file_digest(stream, "sha256")
    return result.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kernel-output", type=Path, required=True)
    parser.add_argument("--linux-source", type=Path, required=True)
    parser.add_argument("--version", default="7.2.9")
    parser.add_argument("--release", default="7.2.9-jon-ppp")
    # Conservative RK3399 address gap: 0x06000000 - 0x02080000.
    # Raise only after checking the actual intended bootloader environment.
    parser.add_argument("--max-image-bytes", type=int, default=0x03F80000)
    args = parser.parse_args()
    output = args.kernel_output.resolve()
    linux_source = args.linux_source.resolve()
    if not re.fullmatch(r"[0-9][A-Za-z0-9._+-]*-jon-ppp", args.release):
        raise SystemExit("Invalid custom kernel release")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", args.version):
        raise SystemExit("Invalid upstream kernel version")
    release_path = output / "kernelrelease"
    if release_path.read_text().strip() != args.release:
        raise SystemExit("kernelrelease differs from requested release")
    files = {
        "Image": output / f"Image-{args.release}",
        "config": output / f"config-{args.release}",
        "System.map": output / f"System.map-{args.release}",
        "kernelrelease": release_path,
        "rk3399-pinephone-pro.dtb": output / "rk3399-pinephone-pro.dtb",
        "COPYING": linux_source / "COPYING",
        "GPL-2.0": linux_source / "LICENSES/preferred/GPL-2.0",
        "Linux-syscall-note": linux_source / "LICENSES/exceptions/Linux-syscall-note",
    }
    for file_path in files.values():
        if not file_path.is_file() or file_path.stat().st_size == 0:
            raise SystemExit(f"Missing or empty compiled payload: {file_path}")
    image = files["Image"]
    with image.open("rb") as stream:
        image_header = stream.read(64)
    if len(image_header) != 64 or image_header[56:60] != b"ARM\x64":
        raise SystemExit("Not a raw ARM64 Linux Image")
    # ARM64 image_size can reserve more RAM than the on-disk Image uses.
    memory_image_size = struct.unpack_from("<Q", image_header, 16)[0]
    required_image_size = max(image.stat().st_size, memory_image_size)
    if required_image_size >= args.max_image_bytes:
        raise SystemExit(
            f"Kernel requires {required_image_size} bytes; exceeds verified "
            f"kernel-to-initrd address gap ({args.max_image_bytes} bytes). "
            "Confirm and adjust the actual firmware load addresses first."
        )
    dtb = files["rk3399-pinephone-pro.dtb"].read_bytes()
    if dtb[:4] != bytes.fromhex("d00dfeed"):
        raise SystemExit("Device tree blob has invalid magic")
    config = files["config"].read_text()
    for required in (
        "CONFIG_BLK_DEV_INITRD=y", "CONFIG_RD_GZIP=y", "CONFIG_MODULES=y",
        "CONFIG_OF=y", "CONFIG_MMC_DW_ROCKCHIP=y", "CONFIG_MMC_SDHCI_OF_ARASAN=y",
        "CONFIG_BTRFS_FS=y", "CONFIG_EXT4_FS=y", "CONFIG_SECURITY_SELINUX=y",
        "CONFIG_DRM_ROCKCHIP=y", "CONFIG_DRM_PANEL_HIMAX_HX8394=y",
    ):
        if required not in config.splitlines():
            raise SystemExit(f"Required PPP/Fedora config missing: {required}")
    module_source = output / "modules-root/lib/modules" / args.release
    if not module_source.is_dir():
        module_source = output / "modules-root/usr/lib/modules" / args.release
    if not module_source.is_dir():
        raise SystemExit("Matching modules_install directory is missing")
    for filename in ("modules.order", "modules.builtin", "modules.builtin.modinfo"):
        if not (module_source / filename).is_file():
            raise SystemExit(f"Missing module metadata: {filename}")
    modules = sorted(module_source.rglob("*.ko"))
    if not modules:
        raise SystemExit("No installed kernel modules")
    signed_modules = "CONFIG_MODULE_SIG_ALL=y" in config.splitlines()
    module_hashes = {}
    for module in modules:
        data = module.read_bytes()
        if data[:5] != b"\x7fELF\x02" or data[5] != 1 or struct.unpack_from("<H", data, 18)[0] != 183:
            raise SystemExit(f"Module is not a little-endian ARM64 ELF: {module}")
        vermagic = re.search(rb"(?:^|\0)vermagic=([^\0]+)\0", data)
        if not vermagic or vermagic.group(1).split(b" ")[0].decode() != args.release:
            raise SystemExit(f"Module vermagic mismatch: {module}")
        if signed_modules and not data.endswith(b"~Module signature appended~\n"):
            raise SystemExit(f"Expected signed module has no signature: {module}")
        module_hashes[str(module.relative_to(module_source))] = digest(module)
    manifest_candidates = [output.parent / "source-manifest.json", output / "device-config/source-manifest.json"]
    manifest_path = next((p for p in manifest_candidates if p.is_file()), None)
    if manifest_path is None:
        raise SystemExit("Kernel source/patch provenance manifest is missing")
    provenance = json.loads(manifest_path.read_text())
    package_dir = Path(__file__).resolve().parent
    sources_dir = package_dir / "SOURCES"
    sources_dir.mkdir(parents=True, exist_ok=True)
    archive_name = f"kernel-pinephone-pro-{args.version}"
    with tempfile.TemporaryDirectory(prefix="ppp-rpm-sources-") as temporary:
        staged = Path(temporary) / archive_name
        staged.mkdir()
        for name, source in files.items():
            shutil.copyfile(source, staged / name)
        shutil.copytree(module_source, staged / "modules" / args.release, symlinks=True)
        for name in ("build", "source"):
            link = staged / "modules" / args.release / name
            if link.is_symlink():
                link.unlink()
            elif link.exists():
                raise SystemExit(f"Unexpected bundled {name} directory; review before packaging")
        # Regenerate binary/text dependency indexes with the target Fedora
        # kmod. Keep source-generated modules.order/builtin/builtin.modinfo.
        generated_indexes = (
            "modules.alias", "modules.alias.bin", "modules.builtin.alias.bin",
            "modules.builtin.bin", "modules.dep", "modules.dep.bin",
            "modules.devname", "modules.softdep", "modules.symbols",
            "modules.symbols.bin", "modules.weakdep",
        )
        for name in generated_indexes:
            index = staged / "modules" / args.release / name
            if index.is_file():
                index.unlink()
        for entry in staged.rglob("*"):
            if entry.is_symlink():
                raise SystemExit(f"Unexpected payload symlink: {entry}")
        source_manifest = {
            "package": "kernel-pinephone-pro", "version": args.version,
            "kernel_release": args.release, "architecture": "aarch64",
            "module_count": len(modules), "modules_signed": signed_modules,
            "image_file_bytes": image.stat().st_size,
            "image_reserved_memory_bytes": memory_image_size,
            "max_verified_image_bytes": args.max_image_bytes,
            "source_provenance": provenance, "module_sha256": module_hashes,
        }
        (staged / "source-manifest.json").write_text(json.dumps(source_manifest, indent=2, sort_keys=True) + "\n")
        (staged / "MODULES_SHA256SUMS").write_text("".join(f"{hash_value}  {filename}\n" for filename, hash_value in sorted(module_hashes.items())))
        payload_names = ["Image", "config", "System.map", "kernelrelease", "rk3399-pinephone-pro.dtb", "source-manifest.json", "MODULES_SHA256SUMS"]
        (staged / "SHA256SUMS").write_text("".join(f"{digest(staged / name)}  {name}\n" for name in payload_names))
        def normalize(info: tarfile.TarInfo) -> tarfile.TarInfo:
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            info.mtime = 1791619200  # 2026-10-10 08:00:00 UTC
            return info
        archive = sources_dir / f"{archive_name}.tar.gz"
        with archive.open("wb") as archive_stream:
            with gzip.GzipFile(filename="", fileobj=archive_stream, mode="wb", compresslevel=6, mtime=0) as gzip_stream:
                with tarfile.open(fileobj=gzip_stream, mode="w") as package_tar:
                    package_tar.add(staged, arcname=archive_name, filter=normalize)
    result = {"archive": str(archive), "sha256": digest(archive), "kernel_release": args.release,
              "module_count": len(modules), "image_required_bytes": required_image_size}
    (package_dir / "prepared-sources.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
