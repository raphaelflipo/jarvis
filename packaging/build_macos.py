#!/usr/bin/env python3
"""Create a deterministic, source-only macOS installer without copying user state."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VERSION = "3.2.0-beta.1"
FIXED_DATE = (2026, 1, 1, 0, 0, 0)
# Deliberate public-source allowlist. Add new runtime modules here when needed;
# an untracked Python file must not become public just because of its extension.
RUNTIME_MODULES = """agenda app attach bench browser config core devices devtools diagnostics
engine files hub images jarvis llm mcp_client myfiles net_tools nightly office
projects push recipes registry research sandbox scheduler security server siri
tasks tools voice""".split()
WEB_ASSETS = ["index.html", "app.js", "style.css", "sw.js", "icon.png"]


def public_bytes(root: Path, path: Path) -> bytes:
    relative = path.relative_to(root)
    ancestors = [path, *list(path.parents)[:len(relative.parts) - 1]]
    if any(item.is_symlink() for item in ancestors) or not path.is_file():
        raise ValueError(f"Missing or unsafe source file: {relative}")
    return path.read_bytes()


def source_files(root: Path) -> dict[str, bytes]:
    # Runtime state is never included. In particular, do not archive a checkout
    # recursively: it can contain .env, models, logs, tokens or private workspaces.
    required = ["install.sh", "install.command", "uninstall.sh", "requirements.txt", "LICENSE",
                "macos/JarvisApp.swift", "macos/JarvisAgenda.swift", "assets/AppIcon.icns",
                "tests/test_offline.py", "tests/verifier.py"]
    candidates = [root / name for name in required]
    candidates += [root / "jarvis" / (name + ".py") for name in RUNTIME_MODULES]
    candidates += [root / "jarvis/web" / name for name in WEB_ASSETS]
    files = {}
    for path in candidates:
        files[path.relative_to(root).as_posix()] = public_bytes(root, path)
    if "jarvis/jarvis.py" not in files or "jarvis/web/index.html" not in files:
        raise ValueError("Incomplete Jarvis sources")
    return files


def build(root: Path, output: Path, version: str) -> Path:
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.]+)?", version):
        raise ValueError("Use a version such as 3.2.0-beta.1")
    payload = source_files(root)
    payload["VERSION"] = (version + "\n").encode()
    manifest = "".join(f"{hashlib.sha256(data).hexdigest()}  {name}\n"
                       for name, data in sorted(payload.items())).encode()
    payload["MANIFEST.sha256"] = manifest
    prefix = f"Jarvis-{version}-macOS-arm64/"
    app = prefix + "Installer Jarvis.app/Contents/"
    entries = {app + "Resources/payload/" + name: data for name, data in payload.items()}
    for name in ("Info.plist", "MacOS/Installer"):
        path = root / "packaging/Installer Jarvis.app/Contents" / name
        data = public_bytes(root, path)
        if name == "Info.plist":
            data = data.replace(b"3.2.0", version.split("-", 1)[0].encode())
        entries[app + name] = data
    entries[app + "Resources/AppIcon.icns"] = payload["assets/AppIcon.icns"]
    entries[prefix + "LIRE-MOI.txt"] = public_bytes(root, root / "packaging/MACOS-INSTALL.txt")
    entries[prefix + "LICENSE"] = payload["LICENSE"]
    output.mkdir(parents=True, exist_ok=True)
    target = output / f"Jarvis-v{version}-macOS-arm64.zip"
    # Replace only this named artifact. Never remove dist or other platforms.
    with tempfile.NamedTemporaryFile(prefix=".jarvis-macos-", suffix=".zip", dir=output, delete=False) as stream:
        temporary = Path(stream.name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, data in sorted(entries.items()):
                info = zipfile.ZipInfo(name, FIXED_DATE)
                info.create_system = 3
                executable = name.endswith(("/MacOS/Installer", "/install.sh", "/install.command", "/uninstall.sh"))
                info.external_attr = ((0o100755 if executable else 0o100644) << 16)
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, data)
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip() is not None:
                raise ValueError("ZIP integrity check failed")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix(target.suffix + ".sha256").write_text(f"{digest}  {target.name}\n")
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=DEFAULT_VERSION)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    print(build(ROOT, args.output, args.version))
