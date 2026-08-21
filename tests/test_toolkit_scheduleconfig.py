from __future__ import annotations

import difflib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from toolkit_binary import encoded_id, uvarint  # noqa: E402
import toolkit_scheduleconfig as sc  # noqa: E402


def _text(value: str) -> bytes:
    data = value.encode("utf-8")
    return uvarint(len(data)) + data


def _entry(
    time_seconds: float,
    days: int,
    sequence: int,
    line_id: str,
    repeat_raw: int,
    offset_group: int = 0,
    selectors: tuple[int, int] = (1, 1),
    timing_event: int = 2,
    timing_selector: int = 1,
    stacked_count: int = 0,
) -> bytes:
    parameters = (
        repeat_raw, 1, timing_event, selectors[0], selectors[1], timing_selector,
        0, stacked_count,
    )
    return (
        uvarint(round(time_seconds * 2))
        + uvarint(days * 2)
        + uvarint(offset_group * 2)
        + uvarint(sequence)
        + encoded_id(line_id)
        + b"".join(uvarint(value) for value in parameters)
    )


def _group(
    schedule_id: str,
    name: str,
    entries: list[bytes],
    group_line_id: str,
    mode: int = sc.OFFSET_LINE_DURATION,
    fixed_interval: float = 0,
    manual_duration: float = 0,
) -> bytes:
    return (
        encoded_id(schedule_id)
        + _text(name)
        + _text(sc.DEFAULT_GROUP_NAME)
        + uvarint(len(entries))
        + b"".join(entries)
        + uvarint(mode)
        + uvarint(round(fixed_interval * 2))
        + uvarint(round(manual_duration * 2))
        + encoded_id(group_line_id)
        + b"\x00" * 36
    )


AIRPORT = "0x40000000d0001"
DEPOT = "0x40000002d0001"
OTHER = "0x40000000e0001"
DAILY = "0x60000003b0001"


def _raw() -> bytes:
    route = _group(
        "0x60000000e0001",
        "OT Airport Link",
        [_entry(21600, 1, 200000, AIRPORT, 0)],
        AIRPORT,
    )
    daily = _group(
        DAILY,
        "OT Line 4 Daily",
        [
            _entry(1800, 0x7F, 7480, DEPOT, 2),
            _entry(19800, 0x7F, 7488, AIRPORT, 0, selectors=(3156, 3156)),
        ],
        AIRPORT,
    )
    collateral = _group(
        "0x60000003d0002",
        "TTC Line 1 Daily",
        [_entry(21600, 0x7F, 7512, OTHER, 0)],
        OTHER,
    )
    return b"\x11" * 32 + route + daily + collateral + b"\x00" * 32


def _raw_with_allocator() -> bytes:
    return (
        _raw()
        + uvarint(7512)
        + uvarint(123456)
        + uvarint(987654)
        + b"\x00\x00\x1e\x00\x09buildings\x00\x00"
    )


class OperatingRuleTests(unittest.TestCase):
    def test_reads_times_days_lines_and_offset(self):
        raw = _raw()
        group = sc.get_operating_group(raw, "OT Line 4 Daily")
        self.assertEqual(group.schedule_id, DAILY)
        self.assertEqual([e.time_seconds for e in group.entries], [1800, 19800])
        self.assertEqual([e.days_mask for e in group.entries], [0x7F, 0x7F])
        self.assertEqual(group.entries[1].line_name, "OT Airport Link")
        self.assertEqual(group.offset_mode_name, "line-duration")
        self.assertEqual(group.entries[0].offset_group_number, 1)
        self.assertEqual(group.entries[1].offset_group_number, 1)
        self.assertEqual(group.entries[1].order_parameters, {
            "repeat_raw": 0,
            "repeat_count": None,
            "repeat_is_max": True,
            "continue_into_next": True,
            "timing_event": 2,
            "enter_selector": 3156,
            "exit_selector": 3156,
            "timing_selector": 1,
            "timing_loop_bias": 0,
            "stacked_count": 0,
        })
        self.assertEqual(group.entries[0].repeat_count, 1)
        self.assertFalse(group.entries[0].repeat_is_max)
        self.assertEqual(len(group.distributions), 10)
        self.assertTrue(sc.roundtrip_identity(raw, group))

    def test_band_ab_changes_decode_exactly(self):
        raw = _raw()
        changed, before, after, fields = sc.set_operating_group(
            raw,
            DAILY,
            entry_updates={
                0: {"time_seconds": 3600},
                1: {"time_seconds": 28800, "days_mask": 0x1F},
            },
            offset_mode="fixed",
            fixed_interval_seconds=420,
        )
        self.assertEqual(fields, 6)
        self.assertEqual([e.time_seconds for e in before.entries], [1800, 19800])
        self.assertEqual([e.time_seconds for e in after.entries], [3600, 28800])
        self.assertEqual([e.days_mask for e in after.entries], [0x7F, 0x1F])
        self.assertEqual(after.offset_mode_name, "fixed")
        self.assertEqual((after.offset_a_seconds, after.offset_b_seconds), (420, 420))
        self.assertEqual(len(changed), len(raw) + 1)

        changes = [op for op in difflib.SequenceMatcher(a=raw, b=changed, autojunk=False).get_opcodes()
                   if op[0] != "equal"]
        self.assertEqual(len(changes), 4)
        self.assertEqual(sc.get_operating_group(changed, "TTC Line 1 Daily").entries[0].time_seconds,
                         21600)

    def test_line_duration_preserves_inactive_numeric_inputs(self):
        raw, _, fixed, _ = sc.set_operating_group(
            _raw(), DAILY, offset_mode="fixed", fixed_interval_seconds=420,
        )
        restored, _, after, _ = sc.set_operating_group(
            raw, DAILY, offset_mode="line-duration"
        )
        self.assertEqual((after.offset_mode, after.offset_a_seconds, after.offset_b_seconds),
                         (sc.OFFSET_LINE_DURATION, 420, 420))
        self.assertTrue(sc.roundtrip_identity(restored, after))

    def test_manual_duration_updates_only_its_own_input(self):
        raw, _, after, _ = sc.set_operating_group(
            _raw(), DAILY, offset_mode="manual-duration", manual_duration_seconds=3600,
        )
        self.assertEqual(after.offset_mode, sc.OFFSET_MANUAL_DURATION)
        self.assertEqual(after.fixed_interval_seconds, 0)
        self.assertEqual(after.manual_duration_seconds, 3600)
        self.assertTrue(sc.roundtrip_identity(raw, after))

    def test_rejects_invalid_day_mask(self):
        with self.assertRaises(ValueError):
            sc.set_operating_group(_raw(), DAILY, entry_updates={1: {"days_mask": 0}})

    def test_custom_editor_updates_verified_order_fields_and_group_two(self):
        changed, before, after, fields = sc.set_operating_group(
            _raw(),
            DAILY,
            entry_updates={
                1: {
                    "time_seconds": 28800,
                    "days_mask": 0x1F,
                    "offset_group_index": 1,
                    "repeat_is_max": False,
                    "repeat_count": 3,
                    "continue_into_next": False,
                },
            },
            distribution_updates={
                1: {
                    "mode": "fixed",
                    "fixed_interval_seconds": 420,
                    "manual_duration_seconds": 3600,
                    "duration_line_id": AIRPORT,
                },
            },
        )
        entry = after.entries[1]
        self.assertEqual(entry.time_seconds, 28800)
        self.assertEqual(entry.days_mask, 0x1F)
        self.assertEqual(entry.offset_group_number, 2)
        self.assertEqual(entry.repeat_count, 3)
        self.assertFalse(entry.repeat_is_max)
        self.assertFalse(entry.continue_into_next)
        # Timing and stop selectors remain unchanged when they are not edited.
        self.assertEqual(entry.parameters[2:], before.entries[1].parameters[2:])
        group_two = after.distributions[1]
        self.assertEqual(group_two.mode_name, "fixed")
        self.assertEqual(group_two.fixed_interval_seconds, 420)
        self.assertEqual(group_two.manual_duration_seconds, 3600)
        self.assertEqual(group_two.duration_line_id, AIRPORT)
        self.assertGreaterEqual(fields, 8)
        self.assertTrue(sc.roundtrip_identity(changed, after))

    def test_allows_line_duration_on_any_offset_group(self):
        changed, _, after, _ = sc.set_operating_group(
            _raw(),
            DAILY,
            distribution_updates={
                4: {"mode": "line-duration", "duration_line_id": AIRPORT},
            },
        )
        self.assertEqual(after.distributions[4].mode_name, "line-duration")
        self.assertEqual(after.distributions[4].duration_line_id, AIRPORT)
        self.assertTrue(sc.roundtrip_identity(changed, after))

    def test_updates_verified_line_timing_and_selectors(self):
        changed, _, after, _ = sc.set_operating_group(
            _raw(),
            DAILY,
            entry_updates={
                0: {"line_id": AIRPORT},
                1: {"timing_event": sc.TIMING_ARRIVE_EXACT},
            },
        )
        self.assertEqual(after.entries[0].line_id, AIRPORT)
        self.assertEqual(after.entries[0].parameters[3:6], (1, 1, 1))
        self.assertEqual(after.entries[1].parameters[2], sc.TIMING_ARRIVE_EXACT)
        self.assertTrue(sc.roundtrip_identity(changed, after))

    def test_parses_flat_stacked_children_without_changing_top_count(self):
        parent = _entry(28800, 0x1F, 7520, AIRPORT, 0, stacked_count=2)
        child_a = _entry(29400, 0x1F, 7522, AIRPORT, 0)
        child_b = _entry(30000, 0x1F, 7524, AIRPORT, 0)
        raw = b"\x11" * 32 + _group(
            DAILY, "Stacked", [parent + child_a + child_b], AIRPORT,
        ) + b"\x00" * 32
        group = sc.get_operating_group(raw, "Stacked")
        self.assertEqual(len(group.entries), 1)
        self.assertEqual([child.order_id for child in group.entries[0].stacked_entries],
                         [7522, 7524])
        self.assertEqual(group.entries[0].parameters[7], 2)
        self.assertTrue(sc.roundtrip_identity(raw, group))

    def test_entry_plan_inserts_top_and_stacked_records_and_updates_allocator(self):
        raw = _raw_with_allocator()
        before = sc.get_operating_group(raw, DAILY)
        first, second = before.entries
        plan = [
            sc.group_to_dict(before)["entries"][0],
            sc.group_to_dict(before)["entries"][1],
            {
                "order_id": None,
                "line_id": AIRPORT,
                "time_seconds": 28800,
                "days_mask": 0x1F,
                "offset_group_index": 0,
                "repeat_is_max": True,
                "continue_into_next": True,
                "timing_event": sc.TIMING_DEPART_EXACT,
                "enter_selector": 1,
                "exit_selector": 1,
                "timing_selector": 1,
                "stacked_entries": [{
                    "order_id": None,
                    "line_id": AIRPORT,
                    "time_seconds": 29220,
                    "days_mask": 0x1F,
                    "offset_group_index": 0,
                    "repeat_is_max": True,
                    "continue_into_next": True,
                    "timing_event": sc.TIMING_DEPART_EXACT,
                    "enter_selector": 1,
                    "exit_selector": 1,
                    "timing_selector": 1,
                }],
            },
        ]
        changed, _, after, _ = sc.set_operating_group(
            raw, DAILY, entry_plan=plan,
        )
        self.assertEqual([entry.order_id for entry in after.entries[:2]],
                         [first.order_id, second.order_id])
        self.assertEqual(after.entries[2].order_id, 7514)
        self.assertEqual(after.entries[2].stacked_entries[0].order_id, 7516)
        self.assertEqual(sc._order_counter_field(changed, 7516).raw, 7516)
        self.assertEqual(sc.get_operating_group(changed, "TTC Line 1 Daily").entries[0].order_id,
                         7512)
        self.assertTrue(sc.roundtrip_identity(changed, after))

    def test_primary_offset_group_keeps_required_line_reference(self):
        with self.assertRaisesRegex(ValueError, "primary offset group"):
            sc.set_operating_group(
                _raw(),
                DAILY,
                distribution_updates={
                    0: {"mode": "fixed", "duration_line_id": None},
                },
            )


if __name__ == "__main__":
    unittest.main()
