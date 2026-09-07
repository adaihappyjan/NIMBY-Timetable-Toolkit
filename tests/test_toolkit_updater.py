from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import toolkit_updater as updater  # noqa: E402
from build_portable import build_portable  # noqa: E402


def _release_payload(version: str = "1.5.0", size: int = 1234) -> dict:
    tag = f"v{version}"
    base = f"https://github.com/{updater.REPOSITORY}/releases/download/{tag}"
    archive_name = updater.ARCHIVE_NAME_TEMPLATE.format(tag=tag)
    return {
        "tag_name": tag,
        "name": tag,
        "published_at": "2026-08-21T00:00:00Z",
        "body": "安全自动更新",
        "html_url": f"https://github.com/{updater.REPOSITORY}/releases/tag/{tag}",
        "draft": False,
        "prerelease": False,
        "assets": [
            {"name": archive_name, "browser_download_url": f"{base}/{archive_name}", "size": size},
            {"name": updater.CHECKSUM_ASSET_NAME, "browser_download_url": f"{base}/{updater.CHECKSUM_ASSET_NAME}", "size": 110},
        ],
    }


class UpdaterTests(unittest.TestCase):
    def test_version_comparison_is_numeric(self) -> None:
        self.assertTrue(updater.is_newer_version("1.10.0", "1.9.9"))
        self.assertFalse(updater.is_newer_version("v1.5.0", "1.5.0"))
        with self.assertRaisesRegex(RuntimeError, "版本号"):
            updater.normalize_version("latest")

    def test_release_metadata_requires_exact_official_assets(self) -> None:
        release = updater.parse_release_metadata(_release_payload())
        self.assertEqual(release["version"], "1.5.0")
        self.assertEqual(release["archive_size"], 1234)
        bad = _release_payload()
        bad["assets"][0]["browser_download_url"] = "https://example.com/update.zip"
        with self.assertRaisesRegex(RuntimeError, "官方 GitHub"):
            updater.parse_release_metadata(bad)

    def test_auto_check_uses_validated_cache(self) -> None:
        payload = json.dumps(_release_payload()).encode()
        calls = []

        def fetcher(url: str, _limit: int) -> bytes:
            calls.append(url)
            return payload

        with tempfile.TemporaryDirectory() as temp_dir:
            first = updater.check_for_updates("1.4.3", Path(temp_dir), fetcher=fetcher)
            second = updater.check_for_updates(
                "1.4.3", Path(temp_dir), fetcher=lambda *_: (_ for _ in ()).throw(AssertionError("cache missed"))
            )
        self.assertTrue(first["available"])
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(calls, [updater.LATEST_RELEASE_API])

    def test_extract_verified_archive_checks_manifest_and_every_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            archive, _ = build_portable("v1.5.0", temp / "dist")
            data = archive.read_bytes()
            package, manifest = updater.extract_verified_archive(
                data, hashlib.sha256(data).hexdigest(), "1.5.0", temp / "stage"
            )
            self.assertEqual(updater.read_current_version(package), "1.5.0")
            self.assertTrue(updater.ESSENTIAL_FILES.issubset(manifest["files"]))
            self.assertTrue((package / updater.MANIFEST_NAME).is_file())

    def test_prepare_update_downloads_and_verifies_complete_release_chain(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            old_archive, _ = build_portable("v1.5.0", temp / "old-dist")
            new_archive, _ = build_portable("v1.5.1", temp / "new-dist")
            old_data, new_data = old_archive.read_bytes(), new_archive.read_bytes()
            old_package, _ = updater.extract_verified_archive(
                old_data, hashlib.sha256(old_data).hexdigest(), "1.5.0", temp / "old-stage"
            )
            target = temp / "installed"
            shutil.copytree(old_package, target)
            payload = _release_payload("1.5.1", len(new_data))
            release = updater.parse_release_metadata(payload)
            checksum = f"{hashlib.sha256(new_data).hexdigest()} *{release['archive_name']}\n".encode()

            def fetcher(url: str, _limit: int) -> bytes:
                if url == updater.LATEST_RELEASE_API:
                    return json.dumps(payload).encode()
                if url == release["checksum_url"]:
                    return checksum
                if url == release["archive_url"]:
                    return new_data
                raise AssertionError(url)

            prepared = updater.prepare_update(
                target,
                temp / "settings",
                "1.5.0",
                expected_version="1.5.1",
                fetcher=fetcher,
            )
            self.assertEqual(prepared["to_version"], "1.5.1")
            self.assertEqual(prepared["archive_size"], len(new_data))
            updater.validate_staged_package(Path(prepared["package_root"]), "1.5.1")

    def test_extract_rejects_hash_mismatch_and_zip_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            archive, _ = build_portable("v1.5.0", temp / "dist")
            with self.assertRaisesRegex(RuntimeError, "SHA-256"):
                updater.extract_verified_archive(archive.read_bytes(), "0" * 64, "1.5.0", temp / "bad-hash")

            crafted = temp / "traversal.zip"
            with zipfile.ZipFile(crafted, "w") as bundle:
                bundle.writestr("root/../escape.txt", b"bad")
                bundle.writestr("root/.toolkit-manifest.json", b"{}")
            data = crafted.read_bytes()
            with self.assertRaisesRegex(RuntimeError, "不安全路径"):
                updater.extract_verified_archive(data, hashlib.sha256(data).hexdigest(), "1.5.0", temp / "bad-path")
            self.assertFalse((temp / "escape.txt").exists())

    def test_apply_failure_rolls_back_every_changed_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            old_archive, _ = build_portable("v1.4.9", temp / "old-dist")
            new_archive, _ = build_portable("v1.5.0", temp / "new-dist")
            old_data, new_data = old_archive.read_bytes(), new_archive.read_bytes()
            old_package, _ = updater.extract_verified_archive(
                old_data, hashlib.sha256(old_data).hexdigest(), "1.4.9", temp / "old-stage"
            )
            new_package, _ = updater.extract_verified_archive(
                new_data, hashlib.sha256(new_data).hexdigest(), "1.5.0", temp / "new-stage"
            )
            target = temp / "installed"
            shutil.copytree(old_package, target)
            before = (target / "VERSION").read_bytes()
            original_replace = updater._replace_from
            call_count = 0

            def fail_after_one(source: Path, destination: Path) -> None:
                nonlocal call_count
                call_count += 1
                if call_count == 2:
                    raise OSError("simulated locked file")
                original_replace(source, destination)

            result_file = temp / "result.json"
            with mock.patch.object(updater, "_replace_from", side_effect=fail_after_one):
                ok = updater.apply_prepared_update(
                    target, new_package, result_file, "1.4.9", "1.5.0", restart=False
                )
            self.assertFalse(ok)
            self.assertEqual((target / "VERSION").read_bytes(), before)
            self.assertEqual(updater.read_current_version(target), "1.4.9")
            result = json.loads(result_file.read_text(encoding="utf-8"))
            self.assertFalse(result["ok"])
            self.assertIn("simulated locked file", result["error"])

    def test_apply_success_installs_manifest_and_new_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            old_archive, _ = build_portable("v1.4.9", temp / "old-dist")
            new_archive, _ = build_portable("v1.5.0", temp / "new-dist")
            old_data, new_data = old_archive.read_bytes(), new_archive.read_bytes()
            old_package, _ = updater.extract_verified_archive(
                old_data, hashlib.sha256(old_data).hexdigest(), "1.4.9", temp / "old-stage"
            )
            new_package, new_manifest = updater.extract_verified_archive(
                new_data, hashlib.sha256(new_data).hexdigest(), "1.5.0", temp / "new-stage"
            )
            target = temp / "installed"
            shutil.copytree(old_package, target)
            result_file = temp / "result.json"
            ok = updater.apply_prepared_update(
                target, new_package, result_file, "1.4.9", "1.5.0", restart=False
            )
            self.assertTrue(ok)
            self.assertEqual(updater.read_current_version(target), "1.5.0")
            self.assertEqual(
                updater.validate_staged_package(target, "1.5.0")["files"],
                new_manifest["files"],
            )
            result = json.loads(result_file.read_text(encoding="utf-8"))
            self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main()
