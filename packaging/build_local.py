#!/usr/bin/env python3
"""Build the static Jarvis Local release with Python's standard library only.

Run from any directory: python3 packaging/build_local.py
SOURCE_DATE_EPOCH optionally controls ZIP timestamps (UTC; dates before 1980
use ZIP's earliest supported date). Without it, a fixed timestamp is used.
Unchanged payload bytes and the same Python/zlib toolchain produce the same
archive. No dependency installation or model download occurs during packaging.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path, PurePosixPath
import stat
import tempfile
import zipfile


VERSION = "3.3.0-rc.1"
REPOSITORY = Path(__file__).resolve().parents[1]
SOURCE = REPOSITORY / "local-app"
ARCHIVE_ROOT = f"Jarvis-Local-{VERSION}"
ARCHIVE_NAME = f"{ARCHIVE_ROOT}.zip"
DEFAULT_EPOCH = 946684800  # 2000-01-01 UTC, independent of checkout/build time.

# This is intentionally an explicit allowlist. Local caches, node_modules,
# package locks, editor files, source maps and temporary files are never added.
REQUIRED_FILES = frozenset({
    "LICENSE",
    "README.md",
    "THIRD-PARTY-NOTICES.txt",
    "app.js",
    "apple-touch-icon.png",
    "icon-192.png",
    "icon-512.png",
    "index.html",
    "inference-worker.js",
    "manifest.webmanifest",
    "models.js",
    "package.json",
    "styles.css",
    "sw.js",
    "vendor/LICENSE-jinja",
    "vendor/LICENSE-onnxruntime",
    "vendor/LICENSE-transformers",
    "vendor/README-onnxruntime.md",
    "vendor/ThirdPartyNotices-onnxruntime.txt",
    "vendor/ort-wasm-simd-threaded.jsep.mjs",
    "vendor/ort-wasm-simd-threaded.jsep.wasm",
    "vendor/transformers.min.js",
})
OPTIONAL_FILES = frozenset({"VERIFICATION.md"})


def zip_timestamp() -> tuple[int, int, int, int, int, int]:
    """Return a deterministic UTC timestamp supported by the ZIP format."""
    try:
        epoch = int(os.environ.get("SOURCE_DATE_EPOCH", str(DEFAULT_EPOCH)))
    except ValueError as exc:
        raise ValueError("SOURCE_DATE_EPOCH must be an integer UTC timestamp") from exc
    if epoch < 0:
        raise ValueError("SOURCE_DATE_EPOCH must not be negative")
    earliest = 315532800  # 1980-01-01 UTC.
    latest = 4354819199  # 2107-12-31 23:59:59 UTC.
    if epoch > latest:
        raise ValueError("SOURCE_DATE_EPOCH exceeds ZIP's maximum year (2107)")
    dt = datetime.fromtimestamp(max(epoch, earliest), timezone.utc)
    return dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second - dt.second % 2


def read_component(source: Path, relative: str) -> bytes:
    """Read only regular allowlisted files, never traversing a symlink."""
    parts = PurePosixPath(relative).parts
    if not parts or relative.startswith("/") or any(p in ("", ".", "..") for p in parts):
        raise ValueError(f"Invalid archive member: {relative!r}")
    current = source
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"Refusing symlink in release payload: {relative}")
    metadata = current.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"Release component is not a regular file: {relative}")
    # O_NOFOLLOW closes the final-component symlink race on systems that offer it.
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(current, flags), "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError(f"Release component changed type: {relative}")
        return stream.read()


def collect_payload(source: Path) -> dict[str, bytes]:
    if source.is_symlink() or not source.is_dir():
        raise ValueError("local-app must be a real directory, not a symlink")
    missing = sorted(name for name in REQUIRED_FILES if not (source / name).exists())
    if missing:
        raise ValueError("Missing required release files: " + ", ".join(missing))
    names = REQUIRED_FILES | {name for name in OPTIONAL_FILES if (source / name).exists()}
    payload = {name: read_component(source, name) for name in sorted(names)}
    sums = "".join(f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in payload.items())
    payload["SHA256SUMS.txt"] = sums.encode("utf-8")
    return payload


def archive_info(relative: str, timestamp: tuple[int, ...]) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(f"{ARCHIVE_ROOT}/{relative}", timestamp)
    info.create_system = 3  # Stable Unix metadata regardless of build host.
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    info.internal_attr = 0
    info.extra = b""
    info.comment = b""
    return info


def build(output: Path, source: Path = SOURCE) -> tuple[Path, str, int]:
    payload = collect_payload(source)
    timestamp = zip_timestamp()
    if output.is_symlink():
        raise ValueError("The output directory must not be a symlink")
    output.mkdir(parents=True, exist_ok=True)
    destination = output / ARCHIVE_NAME
    sidecar = output / f"{ARCHIVE_NAME}.sha256"
    if destination.is_symlink() or sidecar.is_symlink():
        raise ValueError("Refusing to replace a release output that is a symlink")
    temporary: Path | None = None
    sidecar_temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".jarvis-local-", suffix=".zip.tmp", dir=output, delete=False) as file:
            temporary = Path(file.name)
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name in sorted(payload):
                archive.writestr(archive_info(name, timestamp), payload[name], compresslevel=9)
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip() is not None:
                raise ValueError("The generated ZIP failed its integrity check")
        digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
        with tempfile.NamedTemporaryFile(prefix=".jarvis-local-", suffix=".sha256.tmp", dir=output, delete=False) as file:
            sidecar_temporary = Path(file.name)
            file.write(f"{digest}  {ARCHIVE_NAME}\n".encode("ascii"))
        os.chmod(temporary, 0o644)
        os.chmod(sidecar_temporary, 0o644)
        temporary.replace(destination)
        sidecar_temporary.replace(sidecar)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        if sidecar_temporary is not None:
            sidecar_temporary.unlink(missing_ok=True)
    return destination, digest, len(payload) - 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=REPOSITORY / "dist", help="Output directory (default: repository/dist)")
    arguments = parser.parse_args()
    try:
        path, digest, count = build(arguments.output_dir)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        parser.exit(1, f"Release build failed: {exc}\n")
    print(f"Built {path}\n{count} component files + SHA256SUMS.txt\nSHA256 {digest}")


if __name__ == "__main__":
    main()
