from __future__ import annotations

import io
import sys
import unittest
import zipfile
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from toolkit_scriptgen import (  # noqa: E402
    GARAGE_JOIN_SCRIPT_ID,
    build_mod_zip,
    build_script_source,
    safe_script_id,
    validate_script_source,
)


class ScriptGeneratorTests(unittest.TestCase):
    def test_safe_script_id(self) -> None:
        self.assertEqual(safe_script_id("  STM Rules 2026 "), "stm_rules_2026")
        self.assertEqual(safe_script_id("123"), "rules_123")

    def test_generated_source_uses_documented_event_signatures(self) -> None:
        source = build_script_source(
            {
                "garage_join": True,
                "arrival_hold": True,
                "hold_seconds": 45,
                "signal_speed_limit": True,
                "speed_kmh": 35,
            }
        )
        self.assertIn("TimetableGarageJoin::event_train_shift_setup", source)
        self.assertIn("ArrivalHold::event_line_stop", source)
        self.assertIn("sc.queue_train_stop_delay(train, self.hold_s);", source)
        self.assertIn("SignalSpeedLimit::event_signal_lookahead", source)
        self.assertIn("if train_distance <= self.apply_distance_m", source)
        self.assertIn("result.max_speed = self.max_speed_kmh / 3.6;", source)

    def test_validator_rejects_unbounded_lookahead_speed(self) -> None:
        source = """script meta { lang: nimbyscript.v1, api: nimbyrails.v1, }
pub struct Bad extend Signal {}
pub fn Bad::event_signal_lookahead(train_distance: f64) {
    result.max_speed = 10;
}
"""
        result = validate_script_source(source)
        self.assertFalse(result["valid"])
        self.assertIn("unbounded-lookahead-speed", {item["code"] for item in result["errors"]})

    def test_binary_binding_is_only_advertised_for_exact_pure_garage_mod(self) -> None:
        _, exact = build_mod_zip({"id": GARAGE_JOIN_SCRIPT_ID, "garage_join": True})
        _, combined = build_mod_zip(
            {"id": GARAGE_JOIN_SCRIPT_ID, "garage_join": True, "arrival_hold": True}
        )
        self.assertTrue(exact["binding"]["binary_write_supported"])
        self.assertFalse(combined["binding"]["binary_write_supported"])

    def test_zip_contains_complete_private_mod_folder(self) -> None:
        data, meta = build_mod_zip({"name": "My Rules", "garage_join": True})
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
        self.assertIn(f"{meta['folder']}/mod.txt", names)
        self.assertIn(f"{meta['folder']}/Operations_Rules.nimbyscript", names)


if __name__ == "__main__":
    unittest.main()
