from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from toolkit_cleanup import cleanup_preview  # noqa: E402


NOW = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)


def touch(path: Path, age: timedelta, content: bytes = b"save") -> None:
    path.write_bytes(content)
    timestamp = (NOW - age).timestamp()
    os.utime(path, (timestamp, timestamp))


class CleanupPreviewTests(unittest.TestCase):
    def test_automatic_mode_keeps_recent_excess_copies(self) -> None:
        with tempfile.TemporaryDirectory() as directory_value:
            directory = Path(directory_value)
            for index in range(4):
                touch(
                    directory / f"Das Rails_Toolkit_20260819_12000{index}.nimbyrails5",
                    timedelta(minutes=index),
                )
            result = cleanup_preview(
                directory, days=14, keep=2, compact=False, now=NOW
            )
        self.assertEqual(result["completed_copy_count"], 4)
        self.assertEqual(result["excess_copy_count"], 2)
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["skipped_young_count"], 2)

    def test_compact_mode_retires_excess_copies_and_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as directory_value:
            directory = Path(directory_value)
            paths = []
            for index in range(4):
                path = directory / f"Das Rails_Extension_20260819_12000{index}.nimbyrails5"
                touch(path, timedelta(minutes=index))
                paths.append(path)
            manifest = paths[-1].with_suffix(".manifest.json")
            touch(manifest, timedelta(minutes=3), b"{}")
            result = cleanup_preview(
                directory, days=14, keep=2, compact=True, now=NOW
            )
        self.assertEqual(result["candidate_count"], 2)
        self.assertEqual(result["candidate_file_count"], 3)
        self.assertTrue(
            any(
                manifest.name in {Path(value).name for value in row["paths"]}
                for row in result["targets"]
            )
        )

    def test_stale_partial_is_always_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as directory_value:
            directory = Path(directory_value)
            partial = directory / "Das Rails_Repair_20260819_100000.nimbyrails5.partial"
            touch(partial, timedelta(hours=2))
            result = cleanup_preview(directory, days=30, keep=10, now=NOW)
        self.assertEqual(result["stale_partial_count"], 1)
        self.assertEqual(result["targets"][0]["kind"], "interrupted-partial")


if __name__ == "__main__":
    unittest.main()
