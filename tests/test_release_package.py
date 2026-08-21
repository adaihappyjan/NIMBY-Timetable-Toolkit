from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
import hashlib
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_portable import ZSTD_DLL_SHA256, build_portable, validate_zstd_runtime  # noqa: E402


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
            self.assertIn(prefix + "libzstd.dll", names)
            self.assertIn(prefix + "third_party/zstd/LICENSE", names)
            self.assertIn(prefix + "third_party/zstd/SOURCE.md", names)
            self.assertTrue(checksum.read_text(encoding="utf-8").endswith(f" *{archive.name}\n"))

    def test_archive_contains_verified_amd64_zstd_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive, _ = build_portable("v-test", Path(temp_dir))
            with zipfile.ZipFile(archive) as bundle:
                data = bundle.read(
                    "NIMBY-Timetable-Toolkit-v-test/libzstd.dll"
                )
            self.assertEqual(hashlib.sha256(data).hexdigest(), ZSTD_DLL_SHA256)
            pe_offset = int.from_bytes(data[0x3C:0x40], "little")
            machine = int.from_bytes(data[pe_offset + 4:pe_offset + 6], "little")
            self.assertEqual(machine, 0x8664)

    def test_release_builder_rejects_unverified_zstd_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_dll = Path(temp_dir) / "libzstd.dll"
            fake_dll.write_bytes(b"MZ" + b"\0" * 126)
            with self.assertRaisesRegex(RuntimeError, "SHA-256"):
                validate_zstd_runtime(fake_dll)

    @unittest.skipUnless(os.name == "nt", "bundled runtime is for Windows")
    def test_bundled_zstd_runtime_loads_and_round_trips(self) -> None:
        sys.path.insert(0, str(ROOT))
        from toolkit_binary import Zstd, find_zstd_library

        self.assertEqual(Path(find_zstd_library()).resolve(), ROOT / "libzstd.dll")
        payload = (b"NIMBY Rails portable zstd runtime\0" * 128)
        zstd = Zstd()
        self.assertEqual(zstd.decompress(zstd.compress(payload)), payload)

    def test_archive_excludes_blocked_or_nonportable_launchers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive, _ = build_portable("v-test", Path(temp_dir))
            with zipfile.ZipFile(archive) as bundle:
                suffixes = {Path(name).suffix.lower() for name in bundle.namelist()}
            self.assertTrue({".vbs", ".ps1", ".lnk", ".exe", ".msi"}.isdisjoint(suffixes))


if __name__ == "__main__":
    unittest.main()
