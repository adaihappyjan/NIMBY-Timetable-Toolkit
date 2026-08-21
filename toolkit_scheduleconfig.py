"""Read and safely edit persisted timetable operating rules.

The NIMBY Rails save stores an order list followed by offset-group settings::

    <Schedule id> ... <order-list name> <top-level order count>
      <time*2> <days_mask*2> <offset group*2> <order id> <Line id>
      <8 uvarint order parameters; parameter 7 = stacked child count>
      <complete child records immediately after the parent>
      ...
      <distribution mode> <fixed interval*2> <manual duration*2> <duration Line id>

Times and offsets use the game's half-second integer representation.  Day
masks are also stored doubled (``0xfe`` decodes to ``0x7f`` / every day).
Controlled BAND_A/B saves established fixed mode 0.  The installed game's own
UI strings and a persisted mode-4 Line id identify the remaining policies as
mode 2 ``manual duration`` and mode 4 ``line duration``.  The two numeric
fields are independent saved inputs, not lower/upper bounds.

This module deliberately accepts only the exact, experimentally verified
record signature.  Controlled insert/stack saves also established the global
even Order-id allocator and the route-local stop selector table.  Ambiguous or
structurally different records are ignored on read and rejected on write.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import toolkit_savereader as sr
from toolkit_binary import encoded_id, read_uvarint, uvarint


DEFAULT_GROUP_NAME = "默认"
ORDER_PARAMETER_COUNT = 8
OFFSET_GROUP_COUNT = 10
OFFSET_FIXED = 0
OFFSET_MANUAL_DURATION = 2
OFFSET_LINE_DURATION = 4
MAX_TIME_SECONDS = 172_800
MAX_INTERVAL_SECONDS = 86_400
TIMING_ARRIVE_EXACT = 0
TIMING_DEPART_EXACT = 2
TIMING_ARRIVE_BY = 4
TIMING_EVENTS = (TIMING_ARRIVE_EXACT, TIMING_DEPART_EXACT, TIMING_ARRIVE_BY)
MAX_STACKED_ENTRIES = 32


@dataclass(frozen=True)
class IntField:
    off: int
    length: int
    raw: int


@dataclass(frozen=True)
class OperatingEntry:
    line_id: str
    line_name: str | None
    time_seconds: float
    days_mask: int
    sequence: int
    parameters: tuple[int, ...]
    time_field: IntField
    days_field: IntField
    offset_group_field: IntField
    sequence_field: IntField
    line_field: IntField
    parameter_fields: tuple[IntField, ...]
    record_start: int
    record_end: int
    stacked_entries: tuple["OperatingEntry", ...] = ()

    @property
    def order_id(self) -> int:
        """Persisted identity of this order; it is not a scheduling setting."""
        return self.sequence

    @property
    def offset_group_index(self) -> int | None:
        """Zero-based order offset group; persisted as a doubled integer."""
        raw = self.offset_group_field.raw
        return raw // 2 if not raw & 1 else None

    @property
    def offset_group_number(self) -> int | None:
        index = self.offset_group_index
        return index + 1 if index is not None else None

    @property
    def repeat_count(self) -> int | None:
        """Finite repeat count, or ``None`` for the UI's Max/∞ setting."""
        raw = self.parameters[0]
        return raw // 2 if raw else None

    @property
    def repeat_is_max(self) -> bool:
        return self.parameters[0] == 0

    @property
    def continue_into_next(self) -> bool:
        return self.parameters[1] == 1

    @property
    def order_parameters(self) -> dict[str, int | bool | None]:
        """Expose the eight uvarints in their verified UI order.

        Parameter 7 is the number of complete order records stacked directly
        after this top-level record.  Controlled one- and two-child saves
        changed it from 0 -> 1 -> 2 while leaving the top-level count intact.
        """
        return {
            "repeat_raw": self.parameters[0],
            "repeat_count": self.repeat_count,
            "repeat_is_max": self.repeat_is_max,
            "continue_into_next": self.continue_into_next,
            "timing_event": self.parameters[2],
            "enter_selector": self.parameters[3],
            "exit_selector": self.parameters[4],
            "timing_selector": self.parameters[5],
            "timing_loop_bias": self.parameters[6],
            "stacked_count": self.parameters[7],
        }

    @property
    def stacked_count(self) -> int:
        return len(self.stacked_entries)


@dataclass(frozen=True)
class OffsetDistribution:
    group_index: int
    mode: int
    fixed_interval_seconds: float
    manual_duration_seconds: float
    duration_line_id: str | None
    mode_field: IntField
    fixed_interval_field: IntField
    manual_duration_field: IntField
    duration_line_field: IntField

    @property
    def group_number(self) -> int:
        return self.group_index + 1

    @property
    def mode_name(self) -> str:
        if self.mode == OFFSET_FIXED:
            return "fixed"
        if self.mode == OFFSET_MANUAL_DURATION:
            return "manual-duration"
        if self.mode == OFFSET_LINE_DURATION:
            return "line-duration"
        return f"unknown-{self.mode}"


@dataclass(frozen=True)
class OperatingGroup:
    schedule_id: str
    schedule_name: str
    group_name: str
    record_start: int
    group_start: int
    entries: tuple[OperatingEntry, ...]
    distributions: tuple[OffsetDistribution, ...]
    offset_mode: int
    offset_a_seconds: float
    offset_b_seconds: float
    group_line_id: str
    mode_field: IntField
    offset_a_field: IntField
    offset_b_field: IntField
    count_field: IntField
    entries_end: int

    @property
    def all_entries(self) -> tuple[OperatingEntry, ...]:
        """Top-level records followed by their persisted stacked children."""
        return tuple(
            item
            for entry in self.entries
            for item in (entry, *entry.stacked_entries)
        )

    @property
    def offset_mode_name(self) -> str:
        if self.offset_mode == OFFSET_FIXED:
            return "fixed"
        if self.offset_mode == OFFSET_MANUAL_DURATION:
            return "manual-duration"
        if self.offset_mode == OFFSET_LINE_DURATION:
            return "line-duration"
        return f"unknown-{self.offset_mode}"

    @property
    def fixed_interval_seconds(self) -> float:
        return self.offset_a_seconds

    @property
    def manual_duration_seconds(self) -> float:
        return self.offset_b_seconds

    @property
    def duration_line_id(self) -> str:
        return self.group_line_id


@dataclass(frozen=True)
class SelectorOption:
    selector: int
    route_index: int
    station_id: str | None
    station_name: str


@dataclass(frozen=True)
class OperatingLine:
    line_id: str
    name: str
    route_schedule_id: str
    stop_count: int
    selectors: tuple[SelectorOption, ...]


def _field(raw: bytes, off: int) -> tuple[IntField, int]:
    value, end = read_uvarint(raw, off)
    return IntField(off=off, length=end - off, raw=value), end


def _all_schedule_names(raw: bytes) -> list[tuple[int, int, str, int]]:
    """Return every name-bearing Schedule occurrence, without id de-duplication."""
    out: list[tuple[int, int, str, int]] = []
    i = 0
    end = len(raw) - 12
    while i < end:
        if raw[i + 7] != sr.TYPE_SCHEDULE:
            i += 1
            continue
        record = sr._is_id(raw, i, {sr.TYPE_SCHEDULE})
        if record:
            ident, after_id = record
            name = sr._name_after_id(raw, after_id)
            if name:
                out.append((i, ident, name[0], name[1]))
                i = after_id
                continue
        i += 1
    return out


def _parse_entry_at(
    raw: bytes,
    start: int,
    *,
    allow_stacked: bool,
) -> tuple[OperatingEntry, int]:
    """Parse one complete persisted order record.

    A top-level record may announce N immediately-following stacked records in
    parameter 7.  A stacked record itself is required to have count zero; the
    game UI exposes one flat child list rather than recursively nested stacks.
    """
    p = start
    time_field, p = _field(raw, p)
    days_field, p = _field(raw, p)
    if time_field.raw > MAX_TIME_SECONDS * 2:
        raise ValueError("invalid operating time")
    if days_field.raw & 1:
        raise ValueError("day mask is not doubled")
    days_mask = days_field.raw >> 1
    if not 1 <= days_mask <= 0x7F:
        raise ValueError("invalid day mask")
    offset_group_field, p = _field(raw, p)
    if offset_group_field.raw & 1 or offset_group_field.raw // 2 >= OFFSET_GROUP_COUNT:
        raise ValueError("invalid operating-entry offset group")
    sequence_field, p = _field(raw, p)
    if sequence_field.raw <= 0 or sequence_field.raw & 1:
        raise ValueError("invalid operating Order id")
    line_start = p
    line = sr._is_id(raw, p, {sr.TYPE_LINE})
    if not line:
        raise ValueError("missing operating-entry Line id")
    line_id, p = line
    line_field = IntField(
        off=line_start,
        length=p - line_start,
        raw=line_id * 2,
    )
    parameter_fields: list[IntField] = []
    for _ in range(ORDER_PARAMETER_COUNT):
        parameter_field, p = _field(raw, p)
        parameter_fields.append(parameter_field)
    parameters = tuple(field.raw for field in parameter_fields)
    selectors = parameters[3:6]
    if (
        parameters[0] & 1
        or parameters[0] > 200
        or parameters[1] not in (0, 1)
        or parameters[2] not in TIMING_EVENTS
        or any(value < 1 or (value != 1 and value & 1) for value in selectors)
        or parameters[6] > 2
        or parameters[7] > MAX_STACKED_ENTRIES
        or (not allow_stacked and parameters[7] != 0)
    ):
        raise ValueError("unknown operating-entry parameters")
    return OperatingEntry(
        line_id=hex(line_id),
        line_name=None,
        time_seconds=time_field.raw / 2,
        days_mask=days_mask,
        sequence=sequence_field.raw,
        parameters=parameters,
        time_field=time_field,
        days_field=days_field,
        offset_group_field=offset_group_field,
        sequence_field=sequence_field,
        line_field=line_field,
        parameter_fields=tuple(parameter_fields),
        record_start=start,
        record_end=p,
    ), p


def _parse_group_at(
    raw: bytes,
    group_start: int,
    schedule_record: tuple[int, int, str, int],
) -> OperatingGroup:
    group = sr._read_name(raw, group_start, mn=1, mx=80)
    if not group:
        raise ValueError("invalid operating-group name")
    group_name, p = group
    count_field, p = _field(raw, p)
    if not 1 <= count_field.raw <= 32:
        raise ValueError("invalid operating-entry count")

    entries: list[OperatingEntry] = []
    for _ in range(count_field.raw):
        entry, p = _parse_entry_at(raw, p, allow_stacked=True)
        children: list[OperatingEntry] = []
        for _ in range(entry.parameters[7]):
            child, p = _parse_entry_at(raw, p, allow_stacked=False)
            children.append(child)
        entries.append(replace(entry, stacked_entries=tuple(children)))
    entries_end = p

    distributions: list[OffsetDistribution] = []
    for group_index in range(OFFSET_GROUP_COUNT):
        mode_field, p = _field(raw, p)
        fixed_interval_field, p = _field(raw, p)
        manual_duration_field, p = _field(raw, p)
        duration_line_field, p = _field(raw, p)
        if mode_field.raw not in (OFFSET_FIXED, OFFSET_MANUAL_DURATION, OFFSET_LINE_DURATION):
            raise ValueError("unknown offset distribution mode")
        if fixed_interval_field.raw & 1 or manual_duration_field.raw & 1:
            raise ValueError("offset is not stored in half-seconds")
        if max(fixed_interval_field.raw, manual_duration_field.raw) > MAX_INTERVAL_SECONDS * 2:
            raise ValueError("offset is out of range")
        duration_line_id = None
        if duration_line_field.raw:
            if duration_line_field.raw & 1:
                raise ValueError("duration line id is not doubled")
            ident = duration_line_field.raw >> 1
            if (ident >> 48) != sr.TYPE_LINE or not ident & ((1 << 48) - 1):
                raise ValueError("invalid duration line id")
            duration_line_id = hex(ident)
        distributions.append(
            OffsetDistribution(
                group_index=group_index,
                mode=mode_field.raw,
                fixed_interval_seconds=fixed_interval_field.raw / 2,
                manual_duration_seconds=manual_duration_field.raw / 2,
                duration_line_id=duration_line_id,
                mode_field=mode_field,
                fixed_interval_field=fixed_interval_field,
                manual_duration_field=manual_duration_field,
                duration_line_field=duration_line_field,
            )
        )
    primary = distributions[0]
    if primary.duration_line_id is None:
        raise ValueError("missing primary offset-group line id")

    record_start, schedule_id, schedule_name, _ = schedule_record
    return OperatingGroup(
        schedule_id=hex(schedule_id),
        schedule_name=schedule_name,
        group_name=group_name,
        record_start=record_start,
        group_start=group_start,
        entries=tuple(entries),
        distributions=tuple(distributions),
        offset_mode=primary.mode,
        offset_a_seconds=primary.fixed_interval_seconds,
        offset_b_seconds=primary.manual_duration_seconds,
        group_line_id=primary.duration_line_id,
        mode_field=primary.mode_field,
        offset_a_field=primary.fixed_interval_field,
        offset_b_field=primary.manual_duration_field,
        count_field=count_field,
        entries_end=entries_end,
    )


def read_operating_groups(raw: bytes) -> list[OperatingGroup]:
    """Read every operating group matching the verified save signature."""
    records = _all_schedule_names(raw)
    anchor = uvarint(len(DEFAULT_GROUP_NAME.encode("utf-8"))) + DEFAULT_GROUP_NAME.encode("utf-8")
    groups: list[OperatingGroup] = []
    q = 0
    while True:
        q = raw.find(anchor, q)
        if q < 0:
            break
        candidates = [r for r in records if r[3] <= q and q - r[3] <= 256]
        if candidates:
            schedule_record = max(candidates, key=lambda r: r[0])
            try:
                groups.append(_parse_group_at(raw, q, schedule_record))
            except (IndexError, ValueError):
                pass
        q += 1

    # A one-entry route definition gives us the physical Line-id -> human name
    # mapping needed to label the multi-entry Daily timetable groups.
    line_names: dict[str, str] = {}
    for group in groups:
        if len(group.entries) == 1 and group.entries[0].line_id == group.group_line_id:
            line_names[group.group_line_id] = group.schedule_name

    def label_entry(entry: OperatingEntry) -> OperatingEntry:
        return replace(
            entry,
            line_name=line_names.get(entry.line_id),
            stacked_entries=tuple(label_entry(child) for child in entry.stacked_entries),
        )

    return [
        replace(
            group,
            entries=tuple(label_entry(entry) for entry in group.entries),
        )
        for group in groups
    ]


def _selector_table_for_record(
    raw: bytes,
    start: int,
    end: int,
    stop_count: int,
) -> list[tuple[int, int]]:
    """Find the route's ``selector -> route index`` table.

    The verified structure is ``N`` followed by N pairs of an even local
    selector id and a doubled route index.  Pair order is not significant; the
    second values must be the exact permutation ``0,2,...,2(N-1)``.  Choosing
    the tail-most valid candidate handles the compact one-stop route variant.
    """
    if not 1 <= stop_count <= 256:
        return []
    expected = set(range(0, stop_count * 2, 2))
    best: list[tuple[int, int]] = []
    i = start
    while i < end:
        try:
            count, p = read_uvarint(raw, i)
        except (IndexError, ValueError):
            i += 1
            continue
        if count != stop_count:
            i += 1
            continue
        pairs: list[tuple[int, int]] = []
        ok = True
        try:
            for _ in range(count):
                selector, p = read_uvarint(raw, p)
                route_index, p = read_uvarint(raw, p)
                if selector <= 0 or selector & 1:
                    ok = False
                    break
                pairs.append((selector, route_index))
        except (IndexError, ValueError):
            ok = False
        if (
            ok
            and p <= end
            and len({selector for selector, _ in pairs}) == count
            and {route_index for _, route_index in pairs} == expected
        ):
            best = pairs
        i += 1
    return sorted(best, key=lambda pair: pair[1])


def read_operating_lines(
    raw: bytes,
    groups: list[OperatingGroup] | None = None,
) -> list[OperatingLine]:
    """Return safe Line choices plus their valid Enter/Exit selectors."""
    groups = groups if groups is not None else read_operating_groups(raw)
    route_groups: dict[str, OperatingGroup] = {}
    for group in groups:
        if len(group.entries) == 1 and group.entries[0].line_id == group.group_line_id:
            route_groups.setdefault(group.group_line_id, group)

    schedule_records = sorted(_all_schedule_names(raw), key=lambda record: record[0])
    next_start: dict[int, int] = {}
    for index, record in enumerate(schedule_records):
        next_start[record[0]] = (
            schedule_records[index + 1][0]
            if index + 1 < len(schedule_records)
            else len(raw)
        )
    route_templates = {line.id: line for line in sr.read_lines_from_raw(raw)}
    station_names = {station.id: station.name for station in sr.read_stations_from_raw(raw)}
    out: list[OperatingLine] = []
    for line_id, group in route_groups.items():
        template = route_templates.get(group.schedule_id)
        stops = template.stops if template else []
        # A route Schedule id occurs twice in current saves: first in the
        # route template (where the selector table lives), then in the later
        # operating-rule section parsed as ``group.record_start``.  Use the
        # nearest earlier occurrence of the same Schedule id.
        route_record = max(
            (
                record for record in schedule_records
                if hex(record[1]) == group.schedule_id
                and record[0] < group.record_start
            ),
            key=lambda record: record[0],
            default=None,
        )
        selector_start = route_record[0] if route_record else group.record_start
        pairs = _selector_table_for_record(
            raw,
            selector_start,
            next_start.get(selector_start, len(raw)),
            len(stops),
        )
        selectors: list[SelectorOption] = []
        for selector, doubled_index in pairs:
            route_index = doubled_index // 2
            station_id = stops[route_index] if route_index < len(stops) else None
            selectors.append(SelectorOption(
                selector=selector,
                route_index=route_index,
                station_id=station_id,
                station_name=(
                    station_names.get(station_id, station_id)
                    if station_id
                    else f"Stop {route_index + 1}"
                ),
            ))
        out.append(OperatingLine(
            line_id=line_id,
            name=group.schedule_name,
            route_schedule_id=group.schedule_id,
            stop_count=len(stops),
            selectors=tuple(selectors),
        ))
    known = {line.line_id for line in out}
    for group in groups:
        for entry in group.all_entries:
            if entry.line_id in known:
                continue
            out.append(OperatingLine(
                line_id=entry.line_id,
                name=entry.line_name or entry.line_id,
                route_schedule_id="",
                stop_count=0,
                selectors=(),
            ))
            known.add(entry.line_id)
    return sorted(out, key=lambda line: line.name.casefold())


def get_operating_group(raw: bytes, key: str) -> OperatingGroup:
    matches = [
        group for group in read_operating_groups(raw)
        if group.schedule_id == key or group.schedule_name == key
    ]
    if not matches:
        raise ValueError(f"operating timetable not found: {key}")
    if len(matches) != 1:
        raise ValueError(f"operating timetable is ambiguous ({len(matches)} matches): {key}")
    return matches[0]


def _apply_spans(raw: bytes, edits: list[tuple[int, int, bytes]]) -> bytes:
    out = bytearray(raw)
    last = len(raw) + 1
    for start, length, replacement in sorted(edits, reverse=True):
        if start + length > last:
            raise ValueError("overlapping operating-rule edits")
        out[start:start + length] = replacement
        last = start
    return bytes(out)


def _snapshot(group: OperatingGroup) -> tuple:
    return (
        group.schedule_id,
        group.schedule_name,
        group.group_name,
        tuple(
            (
                e.line_id, e.time_seconds, e.days_mask, e.offset_group_field.raw,
                e.sequence, e.parameters,
                tuple(
                    (
                        child.line_id, child.time_seconds, child.days_mask,
                        child.offset_group_field.raw, child.sequence, child.parameters,
                    )
                    for child in e.stacked_entries
                ),
            )
            for e in group.entries
        ),
        group.offset_mode,
        group.offset_a_seconds,
        group.offset_b_seconds,
        group.group_line_id,
        tuple(
            (
                d.group_index, d.mode, d.fixed_interval_seconds,
                d.manual_duration_seconds, d.duration_line_id,
            )
            for d in group.distributions
        ),
    )


def roundtrip_identity(raw: bytes, group: OperatingGroup | str) -> bool:
    target = group if isinstance(group, OperatingGroup) else get_operating_group(raw, group)
    fields = [
        field
        for distribution in target.distributions
        for field in (
            distribution.mode_field,
            distribution.fixed_interval_field,
            distribution.manual_duration_field,
            distribution.duration_line_field,
        )
    ]
    for entry in target.all_entries:
        fields.extend(
            (
                entry.time_field,
                entry.days_field,
                entry.offset_group_field,
                entry.sequence_field,
                entry.line_field,
                *entry.parameter_fields,
            )
        )
    edits = [(f.off, f.length, uvarint(f.raw)) for f in fields]
    return _apply_spans(raw, edits) == raw


def _half_seconds(value: float, maximum: int, label: str) -> int:
    half = int(round(float(value) * 2))
    if abs(half / 2 - float(value)) > 1e-9 or not 0 <= half <= maximum * 2:
        raise ValueError(f"{label} must be a 0.5-second value in range 0–{maximum}")
    return half


def _mode_value(value: str | int) -> int:
    if isinstance(value, int):
        mode = value
    else:
        modes = {
            "fixed": OFFSET_FIXED,
            "manual-duration": OFFSET_MANUAL_DURATION,
            "line-duration": OFFSET_LINE_DURATION,
            "automatic": OFFSET_LINE_DURATION,
        }
        if value not in modes:
            raise ValueError(
                "offset mode must be fixed, manual-duration, or line-duration"
            )
        mode = modes[value]
    if mode not in (OFFSET_FIXED, OFFSET_MANUAL_DURATION, OFFSET_LINE_DURATION):
        raise ValueError("unknown offset distribution mode")
    return mode


def _duration_line_raw(value: str | int | None) -> int:
    """Encode the Line selector stored by an offset distribution."""
    if value in (None, "", 0, "0", "0x0"):
        return 0
    try:
        ident = int(value, 0) if isinstance(value, str) else int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid duration Line id: {value}") from exc
    if (ident >> 48) != sr.TYPE_LINE or not ident & ((1 << 48) - 1):
        raise ValueError(f"invalid duration Line id: {value}")
    return ident * 2


def _line_id_value(value: str | int) -> tuple[str, int]:
    try:
        ident = int(value, 0) if isinstance(value, str) else int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid Line id: {value}") from exc
    if (ident >> 48) != sr.TYPE_LINE or not ident & ((1 << 48) - 1):
        raise ValueError(f"invalid Line id: {value}")
    return hex(ident), ident


def _selector_value(value: int | str, label: str) -> int:
    try:
        selector = int(value, 0) if isinstance(value, str) else int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {label} selector: {value}") from exc
    if selector < 1 or (selector != 1 and selector & 1):
        raise ValueError(f"invalid {label} selector: {value}")
    return selector


def _selector_is_valid(line: OperatingLine | None, selector: int) -> bool:
    return selector == 1 or bool(
        line and any(option.selector == selector for option in line.selectors)
    )


def _order_counter_field(raw: bytes, expected: int) -> IntField:
    """Locate the global order-id allocator beside the root ``buildings`` tag.

    Controlled insertion saves changed exactly the inserted record plus this
    field.  The allocator is followed by two unrelated uvarints and the fixed
    four-byte prefix immediately before ``\x09buildings``.  Walking the three
    uvarints instead of relying on a fixed byte offset remains valid when any
    of their encoded lengths changes.
    """
    anchor = b"\x09buildings"
    candidates: list[IntField] = []
    q = 0
    while True:
        q = raw.find(anchor, q)
        if q < 0:
            break
        chain_end = q - 4
        if chain_end > 0 and raw[chain_end:q] == b"\x00\x00\x1e\x00":
            for start in range(max(0, chain_end - 48), chain_end):
                if start and raw[start - 1] & 0x80:
                    continue
                try:
                    first, end1 = read_uvarint(raw, start)
                    _second, end2 = read_uvarint(raw, end1)
                    _third, end3 = read_uvarint(raw, end2)
                except (IndexError, ValueError):
                    continue
                if first == expected and end3 == chain_end:
                    candidates.append(IntField(start, end1 - start, first))
        q += 1
    unique = {(field.off, field.length, field.raw): field for field in candidates}
    if len(unique) != 1:
        raise ValueError(
            f"global Order id allocator is ambiguous ({len(unique)} matches)"
        )
    return next(iter(unique.values()))


def _entry_signature(entry: OperatingEntry) -> tuple:
    return (
        entry.order_id,
        entry.line_id,
        entry.time_seconds,
        entry.days_mask,
        entry.offset_group_index,
        entry.parameters,
    )


def _plan_record(
    spec: dict,
    base: OperatingEntry | None,
    order_id: int,
    line_catalog: dict[str, OperatingLine],
    stacked_count: int,
) -> tuple[bytes, tuple]:
    if not isinstance(spec, dict):
        raise ValueError("operating entry plan records must be objects")
    default_line = base.line_id if base else None
    if not spec.get("line_id") and not default_line:
        raise ValueError("new operating entries require a Line")
    line_id, _line_ident = _line_id_value(spec.get("line_id", default_line))
    if line_id not in line_catalog:
        raise ValueError(f"Line is not available to operating rules: {line_id}")
    line_changed = bool(base and line_id != base.line_id)

    time_seconds = float(spec.get("time_seconds", base.time_seconds if base else 0))
    time_raw = _half_seconds(time_seconds, MAX_TIME_SECONDS, "time")
    days_mask = int(spec.get("days_mask", base.days_mask if base else 0x7F))
    if not 1 <= days_mask <= 0x7F:
        raise ValueError("days mask must be in range 1–127")
    offset_group = int(spec.get(
        "offset_group_index",
        base.offset_group_index if base and base.offset_group_index is not None else 0,
    ))
    if not 0 <= offset_group < OFFSET_GROUP_COUNT:
        raise ValueError("offset group index must be in range 0–9")

    repeat_is_max = bool(spec.get("repeat_is_max", base.repeat_is_max if base else True))
    repeat_value = spec.get("repeat_count", base.repeat_count if base else None)
    if repeat_is_max or repeat_value in (None, 0, ""):
        repeat_raw = 0
    else:
        repeat_count = int(repeat_value)
        if not 1 <= repeat_count <= 100:
            raise ValueError("repeat count must be Max or in range 1–100")
        repeat_raw = repeat_count * 2
    continue_into_next = spec.get(
        "continue_into_next", base.continue_into_next if base else True,
    )
    if continue_into_next not in (True, False, 0, 1):
        raise ValueError("continue-into-next must be boolean")
    timing_event = int(spec.get(
        "timing_event", base.parameters[2] if base else TIMING_DEPART_EXACT,
    ))
    if timing_event not in TIMING_EVENTS:
        raise ValueError("Timing event must be 0, 2, or 4")

    selector_values: list[int] = []
    for field_name, parameter_index, label in (
        ("enter_selector", 3, "Enter"),
        ("exit_selector", 4, "Exit"),
        ("timing_selector", 5, "Timing"),
    ):
        original = base.parameters[parameter_index] if base else 1
        explicit = field_name in spec
        selector = _selector_value(spec.get(field_name, original), label)
        if not _selector_is_valid(line_catalog.get(line_id), selector):
            if base and not line_changed and selector == original:
                # Preserve a stale source selector when the Line is untouched.
                pass
            elif not explicit:
                # A clone whose Line changed may omit the inherited selectors.
                # Reset those implicit values to the documented sentinel.
                selector = 1
            else:
                raise ValueError(
                    f"{label} selector {selector} does not belong to {line_id}"
                )
        selector_values.append(selector)
    loop_bias = base.parameters[6] if base else 0
    if "timing_loop_bias" in spec and int(spec["timing_loop_bias"]) != loop_bias:
        raise ValueError("Timing loop bias remains read-only")
    parameters = (
        repeat_raw,
        int(bool(continue_into_next)),
        timing_event,
        *selector_values,
        loop_bias,
        stacked_count,
    )
    record = (
        uvarint(time_raw)
        + uvarint(days_mask * 2)
        + uvarint(offset_group * 2)
        + uvarint(order_id)
        + encoded_id(line_id)
        + b"".join(uvarint(value) for value in parameters)
    )
    signature = (
        order_id,
        line_id,
        time_raw / 2,
        days_mask,
        offset_group,
        parameters,
    )
    return record, signature


def _build_entry_plan(
    raw: bytes,
    groups: list[OperatingGroup],
    before: OperatingGroup,
    plan: list[dict],
    line_catalog: dict[str, OperatingLine],
) -> tuple[bytes, list[tuple], IntField | None, int]:
    if not isinstance(plan, list) or not 1 <= len(plan) <= 32:
        raise ValueError("entry plan must contain 1–32 top-level instructions")
    for spec in plan:
        if not isinstance(spec, dict):
            raise ValueError("operating entry plan records must be objects")
        stacks = spec.get("stacked_entries", spec.get("stacked", [])) or []
        if not isinstance(stacks, list) or len(stacks) > MAX_STACKED_ENTRIES:
            raise ValueError("each instruction may have at most 32 stacked children")
        if any(not isinstance(child, dict) for child in stacks):
            raise ValueError("stacked operating entry records must be objects")
    existing_top = {entry.order_id: entry for entry in before.entries}
    if len(existing_top) != len(before.entries):
        raise ValueError("target timetable has duplicate top-level Order ids")
    seen_top: set[int] = set()
    new_count = sum(1 for spec in plan if spec.get("order_id") in (None, "", 0))
    for spec in plan:
        stacks = spec.get("stacked_entries", spec.get("stacked", [])) or []
        new_count += sum(1 for child in stacks if child.get("order_id") in (None, "", 0))
    if sum(1 + len(spec.get("stacked_entries", spec.get("stacked", [])) or []) for spec in plan) > 128:
        raise ValueError("entry plan may contain at most 128 total records")

    allocator_field: IntField | None = None
    allocated_ids = [
        entry.order_id
        for group in groups
        for entry in group.all_entries
        if entry.order_id != 200000
    ]
    if new_count and not allocated_ids:
        raise ValueError("cannot establish the global Order id allocator")
    current_counter = max(allocated_ids, default=0)
    next_order = current_counter
    if new_count:
        allocator_field = _order_counter_field(raw, current_counter)

    encoded = bytearray(uvarint(len(plan)))
    expected: list[tuple] = []
    for spec in plan:
        raw_order = spec.get("order_id")
        if raw_order in (None, "", 0):
            base = None
            next_order += 2
            order_id = next_order
        else:
            order_id = int(raw_order)
            base = existing_top.get(order_id)
            if base is None or order_id in seen_top:
                raise ValueError(f"unknown or duplicate top-level Order id: {order_id}")
            seen_top.add(order_id)
        stack_specs = spec.get("stacked_entries", spec.get("stacked", [])) or []
        record, signature = _plan_record(
            spec, base, order_id, line_catalog, len(stack_specs),
        )
        encoded.extend(record)
        child_expected: list[tuple] = []
        existing_children = {
            child.order_id: child for child in (base.stacked_entries if base else ())
        }
        seen_children: set[int] = set()
        for child_spec in stack_specs:
            child_raw_order = child_spec.get("order_id")
            if child_raw_order in (None, "", 0):
                child_base = None
                next_order += 2
                child_order_id = next_order
            else:
                child_order_id = int(child_raw_order)
                child_base = existing_children.get(child_order_id)
                if child_base is None or child_order_id in seen_children:
                    raise ValueError(
                        f"unknown, moved, or duplicate stacked Order id: {child_order_id}"
                    )
                seen_children.add(child_order_id)
            child_record, child_signature = _plan_record(
                child_spec, child_base, child_order_id, line_catalog, 0,
            )
            encoded.extend(child_record)
            child_expected.append(child_signature)
        if base and seen_children != set(existing_children):
            raise ValueError("existing stacked instructions cannot be deleted")
        expected.append((*signature, tuple(child_expected)))
    if seen_top != set(existing_top):
        raise ValueError("existing top-level instructions cannot be deleted")
    return bytes(encoded), expected, allocator_field, next_order


def set_operating_group(
    raw: bytes,
    key: str,
    entry_updates: dict[int, dict[str, float | int | bool | str | None]] | None = None,
    entry_plan: list[dict] | None = None,
    distribution_updates: dict[int, dict[str, float | int | str | None]] | None = None,
    offset_mode: str | None = None,
    fixed_interval_seconds: float | None = None,
    manual_duration_seconds: float | None = None,
) -> tuple[bytes, OperatingGroup, OperatingGroup, int]:
    """Edit one timetable group and return ``(raw, before, after, fields)``.

    ``entry_updates`` keys are zero-based top-level entry indexes.  In addition
    to time/days/repeat/offset fields, controlled saves verify Line, Timing and
    Enter/Exit/Timing selectors.  An incompatible selector is reset to the
    game's sentinel value 1 when changing Line.

    ``entry_plan`` replaces the target group's complete top-level instruction
    block.  Existing Order ids must be retained exactly; records with a null
    Order id are inserted with ids from the verified global allocator.  A
    top-level record may contain a flat ``stacked_entries`` list.  Deletion of
    persisted top-level or stacked records is deliberately rejected.

    ``distribution_updates`` addresses any of the ten offset groups and may
    update its mode, fixed interval, manual duration and duration-source Line.
    The legacy top-level offset arguments remain as a group-1 convenience for
    CLI callers created before all ten distributions were decoded.
    """
    before_groups = read_operating_groups(raw)
    before = get_operating_group(raw, key)
    if not roundtrip_identity(raw, before):
        raise ValueError(f"round-trip identity failed for {before.schedule_name}")
    if entry_updates and entry_plan is not None:
        raise ValueError("use either entry updates or an entry plan, not both")

    edits: list[tuple[int, int, bytes]] = []

    def queue(field: IntField, value: int) -> None:
        if field.raw != value:
            edits.append((field.off, field.length, uvarint(value)))

    allowed_entry_fields = {
        "time_seconds", "days_mask", "offset_group_index", "repeat_count",
        "repeat_is_max", "continue_into_next", "line_id", "timing_event",
        "enter_selector", "exit_selector", "timing_selector",
    }
    line_catalog = {line.line_id: line for line in read_operating_lines(raw, before_groups)}
    expected_entry_plan: list[tuple] | None = None
    if entry_plan is not None:
        replacement, expected_entry_plan, allocator_field, final_counter = _build_entry_plan(
            raw, before_groups, before, entry_plan, line_catalog,
        )
        edits.append((
            before.count_field.off,
            before.entries_end - before.count_field.off,
            replacement,
        ))
        if allocator_field is not None and allocator_field.raw != final_counter:
            edits.append((
                allocator_field.off,
                allocator_field.length,
                uvarint(final_counter),
            ))
    for index, values in (entry_updates or {}).items():
        if not 0 <= int(index) < len(before.entries):
            raise ValueError(f"operating-entry index out of range: {index}")
        unknown = set(values) - allowed_entry_fields
        if unknown:
            raise ValueError(f"unverified operating-entry fields: {sorted(unknown)}")
        entry = before.entries[int(index)]
        target_line_id = entry.line_id
        line_changed = False
        if "line_id" in values:
            target_line_id, target_line_ident = _line_id_value(values["line_id"])
            if target_line_id not in line_catalog:
                raise ValueError(f"Line is not available to operating rules: {target_line_id}")
            line_changed = target_line_id != entry.line_id
            queue(entry.line_field, target_line_ident * 2)
        if "time_seconds" in values:
            half = _half_seconds(float(values["time_seconds"]), MAX_TIME_SECONDS, "time")
            queue(entry.time_field, half)
        if "days_mask" in values:
            mask = int(values["days_mask"])
            if not 1 <= mask <= 0x7F:
                raise ValueError("days mask must be in range 1–127")
            queue(entry.days_field, mask * 2)
        if "offset_group_index" in values:
            group_index = int(values["offset_group_index"])
            if not 0 <= group_index < OFFSET_GROUP_COUNT:
                raise ValueError("offset group index must be in range 0–9")
            queue(entry.offset_group_field, group_index * 2)
        if "repeat_is_max" in values or "repeat_count" in values:
            repeat_is_max = bool(values.get("repeat_is_max", False))
            repeat_value = values.get("repeat_count")
            if repeat_is_max or repeat_value in (None, 0, ""):
                repeat_raw = 0
            else:
                repeat_count = int(repeat_value)
                if not 1 <= repeat_count <= 100:
                    raise ValueError("repeat count must be Max or in range 1–100")
                repeat_raw = repeat_count * 2
            queue(entry.parameter_fields[0], repeat_raw)
        if "continue_into_next" in values:
            value = values["continue_into_next"]
            if value not in (True, False, 0, 1):
                raise ValueError("continue-into-next must be boolean")
            queue(entry.parameter_fields[1], int(bool(value)))
        if "timing_event" in values:
            timing_event = int(values["timing_event"])
            if timing_event not in TIMING_EVENTS:
                raise ValueError("Timing event must be 0, 2, or 4")
            queue(entry.parameter_fields[2], timing_event)
        target_line = line_catalog.get(target_line_id)
        for field_name, parameter_index, label in (
            ("enter_selector", 3, "Enter"),
            ("exit_selector", 4, "Exit"),
            ("timing_selector", 5, "Timing"),
        ):
            explicit = field_name in values
            selector = (
                _selector_value(values[field_name], label)
                if explicit
                else entry.parameters[parameter_index]
            )
            if not _selector_is_valid(target_line, selector):
                if line_changed and not explicit:
                    selector = 1
                elif not line_changed and not explicit:
                    # Preserve a stale selector already present in the source.
                    continue
                else:
                    raise ValueError(
                        f"{label} selector {selector} does not belong to {target_line_id}"
                    )
            queue(entry.parameter_fields[parameter_index], selector)

    normalized_distributions = {
        int(index): dict(values) for index, values in (distribution_updates or {}).items()
    }

    if offset_mode is not None:
        if offset_mode == "fixed":
            if fixed_interval_seconds is None or float(fixed_interval_seconds) <= 0:
                raise ValueError("fixed offset mode requires a positive interval")
            interval = _half_seconds(
                float(fixed_interval_seconds), MAX_INTERVAL_SECONDS, "fixed interval"
            )
            legacy = {
                "mode": "fixed",
                "fixed_interval_seconds": interval / 2,
                "manual_duration_seconds": interval / 2,
            }
        elif offset_mode == "manual-duration":
            if manual_duration_seconds is None or float(manual_duration_seconds) <= 0:
                raise ValueError("manual-duration mode requires a positive duration")
            duration = _half_seconds(
                float(manual_duration_seconds), MAX_INTERVAL_SECONDS, "manual duration"
            )
            legacy = {
                "mode": "manual-duration",
                "manual_duration_seconds": duration / 2,
            }
        elif offset_mode in ("line-duration", "automatic"):
            # ``automatic`` remains a read-compatible alias for callers created
            # before the mode-4 parameter was identified.  Preserve both saved
            # numeric inputs: they are inactive in line-duration mode.
            legacy = {"mode": "line-duration"}
        else:
            raise ValueError(
                "offset mode must be fixed, manual-duration, or line-duration"
            )
        existing = normalized_distributions.setdefault(0, {})
        for name, value in legacy.items():
            if name in existing and existing[name] != value:
                raise ValueError(f"conflicting group-1 offset value: {name}")
            existing[name] = value

    allowed_distribution_fields = {
        "mode", "fixed_interval_seconds", "manual_duration_seconds",
        "duration_line_id",
    }
    for group_index, values in normalized_distributions.items():
        if not 0 <= group_index < OFFSET_GROUP_COUNT:
            raise ValueError("offset distribution index must be in range 0–9")
        unknown = set(values) - allowed_distribution_fields
        if unknown:
            raise ValueError(f"unverified offset-distribution fields: {sorted(unknown)}")
        distribution = before.distributions[group_index]
        mode = _mode_value(values.get("mode", distribution.mode))
        fixed_raw = distribution.fixed_interval_field.raw
        manual_raw = distribution.manual_duration_field.raw
        line_raw = distribution.duration_line_field.raw
        if "fixed_interval_seconds" in values:
            fixed_raw = _half_seconds(
                float(values["fixed_interval_seconds"]), MAX_INTERVAL_SECONDS,
                "fixed interval",
            )
        if "manual_duration_seconds" in values:
            manual_raw = _half_seconds(
                float(values["manual_duration_seconds"]), MAX_INTERVAL_SECONDS,
                "manual duration",
            )
        if "duration_line_id" in values:
            line_raw = _duration_line_raw(values["duration_line_id"])
        if group_index == 0 and line_raw == 0:
            raise ValueError("primary offset group requires a duration-source Line")
        if mode == OFFSET_LINE_DURATION and line_raw == 0:
            raise ValueError(
                f"offset group {group_index + 1} line-duration mode requires a Line"
            )
        queue(distribution.mode_field, mode)
        queue(distribution.fixed_interval_field, fixed_raw)
        queue(distribution.manual_duration_field, manual_raw)
        queue(distribution.duration_line_field, line_raw)
    if not edits:
        raise ValueError("no operating-rule changes requested")

    new_raw = _apply_spans(raw, edits)
    after_groups = read_operating_groups(new_raw)
    after = get_operating_group(new_raw, before.schedule_id)

    before_other = {
        (g.schedule_id, g.schedule_name, g.group_start): _snapshot(g)
        for g in before_groups if g.schedule_id != before.schedule_id
    }
    # Variable-length writes shift later offsets, so compare all non-target
    # groups in stable file order rather than using their absolute positions.
    after_other = [_snapshot(g) for g in after_groups if g.schedule_id != before.schedule_id]
    if list(before_other.values()) != after_other:
        raise ValueError("operating-rule edit changed another timetable")

    if expected_entry_plan is not None:
        actual_entry_plan = [
            (
                *_entry_signature(entry),
                tuple(_entry_signature(child) for child in entry.stacked_entries),
            )
            for entry in after.entries
        ]
        if actual_entry_plan != expected_entry_plan:
            raise ValueError("entry-plan write failed structural read-back")

    for index, values in (entry_updates or {}).items():
        entry = after.entries[int(index)]
        if "time_seconds" in values and entry.time_seconds != float(values["time_seconds"]):
            raise ValueError("time write failed structural read-back")
        if "days_mask" in values and entry.days_mask != int(values["days_mask"]):
            raise ValueError("day-mask write failed structural read-back")
        if "offset_group_index" in values and entry.offset_group_index != int(values["offset_group_index"]):
            raise ValueError("offset-group assignment failed structural read-back")
        if "repeat_is_max" in values or "repeat_count" in values:
            wanted_max = bool(values.get("repeat_is_max", False)) or values.get("repeat_count") in (None, 0, "")
            if entry.repeat_is_max != wanted_max:
                raise ValueError("repeat write failed structural read-back")
            if not wanted_max and entry.repeat_count != int(values["repeat_count"]):
                raise ValueError("repeat-count write failed structural read-back")
        if "continue_into_next" in values and entry.continue_into_next != bool(values["continue_into_next"]):
            raise ValueError("continue-into-next write failed structural read-back")
        if "line_id" in values and entry.line_id != _line_id_value(values["line_id"])[0]:
            raise ValueError("Line write failed structural read-back")
        if "timing_event" in values and entry.parameters[2] != int(values["timing_event"]):
            raise ValueError("Timing event write failed structural read-back")
        for field_name, parameter_index, label in (
            ("enter_selector", 3, "Enter"),
            ("exit_selector", 4, "Exit"),
            ("timing_selector", 5, "Timing"),
        ):
            if field_name in values and entry.parameters[parameter_index] != _selector_value(values[field_name], label):
                raise ValueError(f"{label} selector write failed structural read-back")

    for group_index, values in normalized_distributions.items():
        distribution = after.distributions[group_index]
        if "mode" in values and distribution.mode != _mode_value(values["mode"]):
            raise ValueError("offset mode write failed structural read-back")
        if (
            "fixed_interval_seconds" in values
            and distribution.fixed_interval_seconds != float(values["fixed_interval_seconds"])
        ):
            raise ValueError("fixed interval write failed structural read-back")
        if (
            "manual_duration_seconds" in values
            and distribution.manual_duration_seconds != float(values["manual_duration_seconds"])
        ):
            raise ValueError("manual duration write failed structural read-back")
        if "duration_line_id" in values:
            wanted = None if values["duration_line_id"] in (None, "", 0, "0", "0x0") else hex(int(values["duration_line_id"], 0) if isinstance(values["duration_line_id"], str) else int(values["duration_line_id"]))
            if distribution.duration_line_id != wanted:
                raise ValueError("duration Line write failed structural read-back")
    return new_raw, before, after, len(edits)


def group_to_dict(group: OperatingGroup) -> dict:
    timing_names = {
        TIMING_ARRIVE_EXACT: "arrive-exact",
        TIMING_DEPART_EXACT: "depart-exact",
        TIMING_ARRIVE_BY: "arrive-by",
    }

    def entry_dict(entry: OperatingEntry, index: int) -> dict:
        return {
            "index": index,
            "line_id": entry.line_id,
            "line_name": entry.line_name,
            "order_id": entry.order_id,
            "time_seconds": entry.time_seconds,
            "days_mask": entry.days_mask,
            "offset_group_index": entry.offset_group_index,
            "offset_group_number": entry.offset_group_number,
            "repeat_count": entry.repeat_count,
            "repeat_is_max": entry.repeat_is_max,
            "continue_into_next": entry.continue_into_next,
            "timing_event": entry.parameters[2],
            "timing_event_name": timing_names.get(entry.parameters[2], "unknown"),
            "enter_selector": entry.parameters[3],
            "exit_selector": entry.parameters[4],
            "timing_selector": entry.parameters[5],
            "timing_loop_bias": entry.parameters[6],
            "stacked_count": len(entry.stacked_entries),
            "stacked_entries": [
                entry_dict(child, child_index)
                for child_index, child in enumerate(entry.stacked_entries)
            ],
            "order_parameters": entry.order_parameters,
            "order_parameters_hex": " ".join(
                uvarint(value).hex(" ") for value in entry.parameters
            ),
        }

    return {
        "schedule_id": group.schedule_id,
        "schedule_name": group.schedule_name,
        "group_name": group.group_name,
        "order_list_name": group.group_name,
        "entries": [entry_dict(entry, index) for index, entry in enumerate(group.entries)],
        "offset_mode": group.offset_mode_name,
        "offset_a_seconds": group.offset_a_seconds,
        "offset_b_seconds": group.offset_b_seconds,
        "fixed_interval_seconds": group.fixed_interval_seconds,
        "manual_duration_seconds": group.manual_duration_seconds,
        "duration_line_id": group.duration_line_id,
        "offset_distributions": [
            {
                "group_index": distribution.group_index,
                "group_number": distribution.group_number,
                "mode": distribution.mode_name,
                "fixed_interval_seconds": distribution.fixed_interval_seconds,
                "manual_duration_seconds": distribution.manual_duration_seconds,
                "duration_line_id": distribution.duration_line_id,
            }
            for distribution in group.distributions
        ],
        "editable": group.offset_mode in (
            OFFSET_FIXED, OFFSET_MANUAL_DURATION, OFFSET_LINE_DURATION,
        ),
    }
