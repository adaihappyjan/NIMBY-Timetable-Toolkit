from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_portable import build_portable  # noqa: E402


class PortableReleaseTests(unittest.TestCase):
    def test_archive_contains_public_launcher_and_author_avatar(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive, checksum = build_portable("v-test", Path(temp_dir))
            with zipfile.ZipFile(archive) as bundle:
                names = set(bundle.namelist())
            prefix = "NIMBY-Timetable-Toolkit-v-test/"
            self.assertIn(prefix + "启动工具箱.cmd", names)
            self.assertIn(prefix + "launcher.bat", names)
            self.assertIn(prefix + "web/assets/author-adaihappyjan.png", names)
            self.assertTrue(checksum.read_text(encoding="utf-8").endswith(f" *{archive.name}\n"))

    def test_archive_excludes_blocked_or_nonportable_launchers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive, _ = build_portable("v-test", Path(temp_dir))
            with zipfile.ZipFile(archive) as bundle:
                suffixes = {Path(name).suffix.lower() for name in bundle.namelist()}
            self.assertTrue({".vbs", ".ps1", ".lnk", ".exe", ".msi"}.isdisjoint(suffixes))


if __name__ == "__main__":
    unittest.main()
