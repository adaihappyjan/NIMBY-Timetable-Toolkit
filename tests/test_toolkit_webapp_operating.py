from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import toolkit_webapp as web  # noqa: E402


class OperatingRuleWebPayloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.old_save_dir = web.SAVE_DIR
        web.SAVE_DIR = Path(self.temp.name)
        self.addCleanup(setattr, web, "SAVE_DIR", self.old_save_dir)
        self.source = web.SAVE_DIR / "input.nimbyrails5"
        self.source.write_bytes(b"synthetic")
        self.output = web.SAVE_DIR / "output.nimbyrails5"

    def payload(self) -> dict:
        return {
            "save": str(self.source),
            "output": str(self.output),
            "schedule": "0x60000003b0001",
            "entries": [
                {
                    "index": 1,
                    "time_seconds": 28800,
                    "days_mask": 0x1F,
                    "offset_group_index": 1,
                    "repeat_is_max": False,
                    "repeat_count": 2,
                    "continue_into_next": False,
                }
            ],
            "distributions": [
                {
                    "group_index": 1,
                    "mode": "fixed",
                    "fixed_interval_seconds": 420,
                    "manual_duration_seconds": 3600,
                    "duration_line_id": "0x40000000d0001",
                }
            ],
        }

    def test_builds_full_custom_timetable_arguments(self) -> None:
        args = web.TaskManager()._build_args("operating-rule-write", self.payload())
        entry = json.loads(args[args.index("--entry-json") + 1])
        distribution = json.loads(args[args.index("--distribution-json") + 1])
        self.assertEqual(entry["offset_group_index"], 1)
        self.assertEqual(entry["repeat_count"], 2)
        self.assertFalse(entry["continue_into_next"])
        self.assertEqual(distribution["fixed_interval_seconds"], 420)
        self.assertEqual(distribution["duration_line_id"], "0x40000000d0001")

    def test_line_duration_requires_source_line(self) -> None:
        payload = self.payload()
        payload["distributions"][0]["mode"] = "line-duration"
        payload["distributions"][0]["duration_line_id"] = None
        with self.assertRaisesRegex(RuntimeError, "来源线路"):
            web.TaskManager()._build_args("operating-rule-write", payload)

    def test_builds_insert_and_stack_entry_plan(self) -> None:
        payload = self.payload()
        payload["entries"] = []
        payload["entry_plan"] = [{
            "order_id": 7488,
            "line_id": "0x40000000d0001",
            "time_seconds": 28800,
            "days_mask": 0x1F,
            "offset_group_index": 0,
            "repeat_is_max": True,
            "repeat_count": None,
            "continue_into_next": True,
            "timing_event": 2,
            "enter_selector": 1,
            "exit_selector": 1,
            "timing_selector": 1,
            "stacked_entries": [{
                "order_id": None,
                "line_id": "0x40000000d0001",
                "time_seconds": 29220,
                "days_mask": 0x1F,
                "offset_group_index": 0,
                "repeat_is_max": True,
                "repeat_count": None,
                "continue_into_next": True,
                "timing_event": 0,
                "enter_selector": 1,
                "exit_selector": 1,
                "timing_selector": 1,
            }],
        }]
        args = web.TaskManager()._build_args("operating-rule-write", payload)
        plan = json.loads(args[args.index("--entry-plan-json") + 1])
        self.assertEqual(plan[0]["order_id"], 7488)
        self.assertIsNone(plan[0]["stacked_entries"][0]["order_id"])
        self.assertEqual(plan[0]["stacked_entries"][0]["timing_event"], 0)


if __name__ == "__main__":
    unittest.main()
