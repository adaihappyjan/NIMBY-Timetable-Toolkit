from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


BACKEND_PATH = Path(__file__).resolve().parents[1] / "toolkit_backend.py"
sys.path.insert(0, str(BACKEND_PATH.parent))
SPEC = importlib.util.spec_from_file_location("toolkit_backend", BACKEND_PATH)
assert SPEC and SPEC.loader
backend = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backend)
import toolkit_binary as binary


SERVICE_ID = "0x4000000000001"
DEPOT_ID = "0x4000000000002"
LINE_INFO = {
    SERVICE_ID: {"name": "Test Service", "stop_count": 10},
    DEPOT_ID: {"name": "Test Depot", "stop_count": 1},
}


def run(line_id: str, start: int) -> dict:
    return {
        "class": "Run",
        "idx": 0,
        "line_id": line_id,
        "enter_stop_idx": 0,
        "exit_stop_idx": 0,
        "arrival_departure": [start, start + 30],
    }


def schedule(name: str, shifts: list[dict]) -> dict:
    return {
        "class": "Schedule",
        "id": "0x6000000000001",
        "name": name,
        "trains": {f"train-{index}": [shift["id"]] for index, shift in enumerate(shifts)},
        "shifts": shifts,
    }


class ExportDiagnosticsTests(unittest.TestCase):
    def test_normal_daily_depot_is_not_reported_as_loop(self) -> None:
        shifts = []
        for shift_index in range(3):
            runs = []
            for day in range(7):
                base = day * backend.SECONDS_PER_DAY + 21_600 + shift_index * 300
                runs.extend([run(DEPOT_ID, base - 60), run(SERVICE_ID, base)])
            shifts.append({"id": f"0x{100 + shift_index:x}", "name": str(shift_index), "runs": runs})
        result = backend.schedule_export_diagnostics(schedule("Normal Daily", shifts), LINE_INFO)
        self.assertEqual(result["depot_lines"][0]["runs_per_shift"], 7)
        self.assertNotIn("DEPOT_CONTINUOUS_LOOP", {row["code"] for row in result["findings"]})

    def test_continuous_depot_loop_is_critical(self) -> None:
        runs = [run(DEPOT_ID, 10_000 + index * 30) for index in range(80)]
        runs.append(run(SERVICE_ID, 30_000))
        result = backend.schedule_export_diagnostics(
            schedule("Broken Daily", [{"id": "0x101", "name": "A", "runs": runs}]),
            LINE_INFO,
        )
        finding = next(row for row in result["findings"] if row["code"] == "DEPOT_CONTINUOUS_LOOP")
        self.assertEqual(finding["severity"], "critical")
        self.assertEqual(result["depot_lines"][0]["max_consecutive_runs"], 80)

    def test_loop_and_missing_days_share_one_repair_task(self) -> None:
        service_runs = [
            run(SERVICE_ID, day * backend.SECONDS_PER_DAY + 20_000 + trip * 900)
            for day in range(4)
            for trip in range(10)
        ]
        depot_runs = [run(DEPOT_ID, 60_000 + index * 30) for index in range(80)]
        shift = {"id": "0x181", "name": "A", "runs": [*service_runs, *depot_runs]}
        train = {"class": "Train", "id": "0x5000000000081", "name": "Train A"}
        objects = [
            {"class": "Line", "id": SERVICE_ID, "name": "Test Service", "stops": [{}, {}]},
            {"class": "Line", "id": DEPOT_ID, "name": "Test Depot", "stops": [{}]},
            train,
            {
                "class": "Schedule",
                "id": "0x6000000000081",
                "name": "Test Line Daily",
                "trains": {train["id"]: [shift["id"]]},
                "shifts": [shift],
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "export.json"
            path.write_text(json.dumps(objects), encoding="utf-8")
            result = backend.scan_export(path)
        task = next(row for row in result["repair_tasks"] if row["type"] == "depot_x1")
        self.assertEqual(task["schedule"], "Test Line Daily")
        self.assertEqual(
            task["resolves"],
            ["DEPOT_CONTINUOUS_LOOP", "DAILY_MISSING_DAYS"],
        )

    def test_daily_coverage_ignores_small_after_midnight_spill(self) -> None:
        shifts = []
        for shift_index in range(2):
            runs = []
            for day in range(4):
                for trip in range(10):
                    runs.append(
                        run(
                            SERVICE_ID,
                            day * backend.SECONDS_PER_DAY + 20_000 + trip * 1_000 + shift_index * 100,
                        )
                    )
            # A small spill into Friday must not make Friday look fully scheduled.
            runs.extend(
                [
                    run(SERVICE_ID, 4 * backend.SECONDS_PER_DAY + 100 + shift_index * 100),
                    run(SERVICE_ID, 4 * backend.SECONDS_PER_DAY + 1_100 + shift_index * 100),
                ]
            )
            shifts.append({"id": f"0x{200 + shift_index:x}", "name": str(shift_index), "runs": runs})
        result = backend.schedule_export_diagnostics(schedule("Week Test Daily", shifts), LINE_INFO)
        self.assertEqual(result["service_line"]["active_days"], [0, 1, 2, 3])
        finding = next(row for row in result["findings"] if row["code"] == "DAILY_MISSING_DAYS")
        self.assertIn("周五", finding["detail"])

    def test_identical_shift_starts_are_detected(self) -> None:
        shifts = [
            {"id": f"0x{300 + index:x}", "name": str(index), "runs": [run(SERVICE_ID, 20_000)]}
            for index in range(4)
        ]
        result = backend.schedule_export_diagnostics(schedule("Offsets Daily", shifts), LINE_INFO)
        self.assertEqual(result["phase"]["status"], "critical")
        self.assertIn("ZERO_OFFSETS", {row["code"] for row in result["findings"]})

    def test_spread_shift_starts_are_good(self) -> None:
        shifts = [
            {
                "id": f"0x{400 + index:x}",
                "name": str(index),
                "runs": [run(SERVICE_ID, 20_000 + index * 150)],
            }
            for index in range(4)
        ]
        result = backend.schedule_export_diagnostics(schedule("Offsets Daily", shifts), LINE_INFO)
        self.assertEqual(result["phase"]["status"], "good")
        self.assertEqual(result["phase"]["median_gap_seconds"], 150)

    def test_old_and_daily_schedule_fleet_overlap_is_critical(self) -> None:
        trains = [
            {"class": "Train", "id": f"0x50000000000{index + 1:x}", "name": f"Train {index}"}
            for index in range(3)
        ]
        line = {
            "class": "Line",
            "id": SERVICE_ID,
            "name": "Line A",
            "stops": [{}, {}],
        }
        source_shifts = [
            {"id": f"0x{500 + index:x}", "name": str(index), "runs": [run(SERVICE_ID, 20_000 + index * 100)]}
            for index in range(3)
        ]
        daily_shifts = [
            {"id": f"0x{600 + index:x}", "name": str(index), "runs": [run(SERVICE_ID, 30_000 + index * 100)]}
            for index in range(3)
        ]
        assignments = {train["id"]: [shift["id"]] for train, shift in zip(trains, source_shifts)}
        objects = [
            line,
            *trains,
            {
                "class": "Schedule",
                "id": "0x6000000000010",
                "name": "Line A",
                "trains": assignments,
                "shifts": source_shifts,
            },
            {
                "class": "Schedule",
                "id": "0x6000000000011",
                "name": "Line A Daily",
                "trains": {train["id"]: [shift["id"]] for train, shift in zip(trains, daily_shifts)},
                "shifts": daily_shifts,
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "export.json"
            path.write_text(json.dumps(objects), encoding="utf-8")
            result = backend.scan_export(path)
        overlaps = [row for row in result["findings"] if row["code"] == "OVERLAPPING_DAILY_FLEET"]
        self.assertEqual(len(overlaps), 1)
        self.assertTrue(all(row["severity"] == "critical" for row in overlaps))
        self.assertEqual(
            result["overlap_repairs"][0]["pair"],
            "Line A::Line A Daily",
        )

    def test_zero_shift_daily_is_recognized_but_not_writable(self) -> None:
        trains = [
            {"class": "Train", "id": f"0x50000000000{index + 1:x}", "name": f"TTC {index}"}
            for index in range(2)
        ]
        shifts = [
            {"id": f"0x{700 + index:x}", "name": str(index), "runs": [run(SERVICE_ID, 20_000 + index * 100)]}
            for index in range(2)
        ]
        objects = [
            {"class": "Line", "id": SERVICE_ID, "name": "TTC Bloor–Danforth", "stops": [{}, {}]},
            *trains,
            {
                "class": "Schedule",
                "id": "0x6000000000020",
                "name": "TTC Bloor–Danforth",
                "trains": {train["id"]: [shift["id"]] for train, shift in zip(trains, shifts)},
                "shifts": shifts,
            },
            {
                "class": "Schedule",
                "id": "0x6000000000021",
                "name": "TTC Line 2 Daily",
                "trains": {},
                "shifts": [],
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "export.json"
            path.write_text(json.dumps(objects), encoding="utf-8")
            result = backend.scan_export(path)
        pair = next(row for row in result["suggested_pairs"] if row["target"] == "TTC Line 2 Daily")
        self.assertEqual(pair["source"], "TTC Bloor–Danforth")
        self.assertFalse(pair["ready"])
        self.assertEqual(result["blank_template_count"], 0)
        self.assertEqual(result["empty_daily_target_count"], 1)


class BinaryRecordTests(unittest.TestCase):
    def test_last_empty_schedule_can_be_followed_by_unrelated_objects(self) -> None:
        item = {"id": "0x6000000000022", "name": "TTC Line 2 Daily"}
        name = item["name"].encode("utf-8")
        record = (
            binary.encoded_id(item["id"])
            + binary.uvarint(0)
            + binary.uvarint(len(name))
            + name
            + b"\x01\x02\x03\x04"
            + binary.EMPTY_SCHEDULE_ZERO_TAIL
        )
        raw = record + b"unrelated motion and script data" * 100
        logical_end = binary.validate_empty_schedule_record(raw, item, len(raw))
        self.assertEqual(logical_end, len(record))

    def test_nonempty_record_is_not_accepted_as_empty(self) -> None:
        item = {"id": "0x6000000000023", "name": "Not Empty Daily"}
        name = item["name"].encode("utf-8")
        raw = (
            binary.encoded_id(item["id"])
            + binary.uvarint(0)
            + binary.uvarint(len(name))
            + name
            + b"\x01\x02\x03\x04\x01\x02\x03"
        )
        with self.assertRaises(RuntimeError):
            binary.validate_empty_schedule_record(raw, item, len(raw))

    def test_empty_schedule_accepts_extended_zero_tail_without_legacy_prefix(self) -> None:
        item = {"id": "0x6000000000024", "name": "TTC Davisville Depot"}
        name = item["name"].encode("utf-8")
        record = (
            binary.encoded_id(item["id"])
            + binary.uvarint(0)
            + binary.uvarint(len(name))
            + name
            + b"\x01\x02\xa4"
            + b"\x00" * 48
        )
        raw = record + b"next schedule record"
        logical_end = binary.validate_empty_schedule_record(raw, item, len(record))
        self.assertEqual(logical_end, len(record))

    def test_extension_selection_uses_ids_when_train_names_are_duplicated(self) -> None:
        train_a = {"class": "Train", "id": "0x5000000000031", "name": "TTC 0162"}
        train_b = {"class": "Train", "id": "0x5000000000032", "name": "TTC 0162"}

        def train_record(train: dict) -> bytes:
            name = train["name"].encode("utf-8")
            return (
                binary.encoded_id(train["id"])
                + binary.uvarint(0)
                + binary.uvarint(len(name))
                + name
                + b"\x00"
            )

        raw = train_record(train_a) + train_record(train_b)
        patched, result = backend.ensure_extensions(
            raw, [train_a, train_b], {train_a["id"]}
        )
        self.assertEqual(result["target_train_count"], 1)
        self.assertEqual(result["changed_train_count"], 1)
        self.assertEqual(result["changed_train_names"], ["TTC 0162"])
        self.assertEqual(patched.count(binary.GARAGE_JOIN_VECTOR), 1)


class GameVersionDetectionTests(unittest.TestCase):
    def test_supported_version(self) -> None:
        info = backend.detect_game_version([{"class": "ExportMeta", "model_version": 230}])
        self.assertEqual(info["status"], "supported")
        self.assertTrue(info["safe_to_write"])

    def test_newer_version_is_compatible_but_flagged(self) -> None:
        info = backend.detect_game_version([{"class": "ExportMeta", "model_version": 999}])
        self.assertEqual(info["status"], "newer")
        self.assertFalse(info["safe_to_write"])

    def test_missing_meta_is_unknown(self) -> None:
        info = backend.detect_game_version([{"class": "Schedule", "id": "0x1"}])
        self.assertEqual(info["status"], "unknown")
        self.assertIsNone(info["model_version"])

    def test_outdated_version(self) -> None:
        info = backend.detect_game_version([{"class": "ExportMeta", "model_version": 100}])
        self.assertEqual(info["status"], "outdated")


if __name__ == "__main__":
    unittest.main()
