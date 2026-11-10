"""Contained public-release checks: no model download or profile installation."""
import hashlib
import importlib.util
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("build_macos", ROOT / "packaging/build_macos.py")
packager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packager)


class MacReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="jarvis-package-test-")
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.checkout = self.folder / "source"
        # A source fixture, never any user's ~/.jarvis directory.
        shutil.copytree(ROOT, self.checkout, ignore=shutil.ignore_patterns(".git", "dist", ".venv", "__pycache__", "local-app"))

    def archive(self):
        return packager.build(self.checkout, self.folder / "out", "3.2.0-beta.1")

    def test_deterministic_and_preserves_other_downloads(self):
        output = self.folder / "out"
        output.mkdir()
        untouched = output / "windows-release.zip"
        untouched.write_bytes(b"unrelated artifact")
        first = self.archive().read_bytes()
        (self.checkout / "install.sh").touch()
        second = self.archive().read_bytes()
        self.assertEqual(first, second)
        self.assertEqual(untouched.read_bytes(), b"unrelated artifact")
        checksum = (output / "Jarvis-v3.2.0-beta.1-macOS-arm64.zip.sha256").read_text().split()[0]
        self.assertEqual(checksum, hashlib.sha256(second).hexdigest())

    def test_private_and_unlisted_files_cannot_enter_release(self):
        for name in (".env", "config.json", "jarvis/server_token", "jarvis/personal.py", "jarvis/web/private.js", "models/weights.bin"):
            file = self.checkout / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("PRIVATE_RELEASE_TEST_MARKER")
        with zipfile.ZipFile(self.archive()) as archive:
            for info in archive.infolist():
                self.assertNotIn(b"PRIVATE_RELEASE_TEST_MARKER", archive.read(info))
                self.assertNotIn("..", Path(info.filename).parts)
            self.assertFalse(any(".git/" in name or "__pycache__/" in name for name in archive.namelist()))

    def test_manifest_and_bundle(self):
        with zipfile.ZipFile(self.archive()) as archive:
            prefix = "Jarvis-3.2.0-beta.1-macOS-arm64/Installer Jarvis.app/Contents/"
            payload = prefix + "Resources/payload/"
            info = plistlib.loads(archive.read(prefix + "Info.plist"))
            self.assertEqual(info["CFBundleShortVersionString"], "3.2.0")
            self.assertEqual(info["LSMinimumSystemVersion"], "14.0")
            self.assertIn(prefix + "Resources/AppIcon.icns", archive.namelist())
            manifest = archive.read(payload + "MANIFEST.sha256").decode().splitlines()
            for line in manifest:
                digest, name = line.split("  ", 1)
                self.assertEqual(digest, hashlib.sha256(archive.read(payload + name)).hexdigest())
            expected = {payload + line.split("  ", 1)[1] for line in manifest}
            actual = {name for name in archive.namelist() if name.startswith(payload)}
            self.assertEqual(actual, expected | {payload + "MANIFEST.sha256"})
            for name in (prefix + "MacOS/Installer", payload + "install.sh", payload + "install.command", payload + "uninstall.sh"):
                self.assertEqual((archive.getinfo(name).external_attr >> 16) & 0o777, 0o755)

    def test_symlinked_runtime_is_rejected(self):
        path = self.checkout / "jarvis/config.py"
        path.unlink()
        path.symlink_to(self.checkout / "jarvis/jarvis.py")
        with self.assertRaisesRegex(ValueError, "unsafe"):
            self.archive()

    def test_symlinked_source_directory_is_rejected(self):
        source = self.checkout / "jarvis"
        outside = self.folder / "outside"
        source.rename(outside)
        source.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "unsafe"):
            self.archive()

    def test_incomplete_sources_and_invalid_version_fail(self):
        (self.checkout / "macos/JarvisAgenda.swift").unlink()
        with self.assertRaises(ValueError):
            self.archive()
        with self.assertRaises(ValueError):
            packager.build(self.checkout, self.folder / "out", "../../escape")
        self.assertFalse((self.folder / "out").exists())

    def test_shell_syntax_and_non_mutating_help(self):
        names = ["install.sh", "install.command", "uninstall.sh", "packaging/build.sh", "packaging/Installer Jarvis.app/Contents/MacOS/Installer"]
        for name in names:
            subprocess.run(["/bin/bash", "-n", str(self.checkout / name)], check=True)
        result = subprocess.run(["/bin/bash", str(self.checkout / "install.sh"), "--help"], text=True, capture_output=True, check=True)
        self.assertIn("sans écriture ni téléchargement", result.stdout)
        self.assertNotIn("xattr -", (self.checkout / "install.sh").read_text())


if __name__ == "__main__":
    unittest.main()
