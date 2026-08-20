"""JSON-free network reader: parse the rail network straight from a save file.

Reads stations (id/name/coords), lines (id/name/code/color/ordered stops) and
signal/switch nodes (id/coords) directly from the decompressed object stream,
without needing the game's JSON export. Read-only.

Object type codes (top hex nibble of an id):
  1 Track   2 Station   3 Signal/switch node   4 Line
  5 Train   6 Schedule  7 script-ext def       8 script-ext binding
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

from toolkit_binary import Zstd, split_save
from toolkit_coordedit import (
    StationRecord,
    mercator_to_lonlat,
    read_stations_from_raw,
)

TYPE_TRACK = 0x1
TYPE_STATION = 0x2
TYPE_SIGNAL = 0x3
TYPE_LINE = 0x4
TYPE_TRAIN = 0x5
TYPE_SCHEDULE = 0x6
_HI = {0x40, 0x41, 0xC0, 0xC1}


def _try_uv(raw: bytes, off: int, mx: int = 10):
    val = 0
    shift = 0
    for k in range(mx):
        if off + k >= len(raw):
            return None
        b = raw[off + k]
        val |= (b & 0x7F) << shift
        if b < 0x80:
            return val, off + k + 1
        shift += 7
    return None


def _read_name(raw: bytes, off: int, mn: int = 1, mx: int = 90):
    r = _try_uv(raw, off)
    if not r:
        return None
    n, after = r
    if not (mn <= n <= mx) or after + n > len(raw):
        return None
    try:
        text = raw[after:after + n].decode("utf-8")
    except UnicodeDecodeError:
        return None
    if any(ord(c) < 0x20 and c != "\t" for c in text):
        return None
    return text, after + n


def _is_id(raw: bytes, i: int, nibbles: set[int]):
    r = _try_uv(raw, i)
    if not r:
        return None
    val, nxt = r
    if (val & 1) or (nxt - i < 7):
        return None
    ident = val >> 1
    # Real object ids are laid out type<<48 | major_index<<16 | small_subindex.
    # The sub-index (low 16 bits) is always tiny in practice (<=0x8 across every
    # class in real saves); a large value means we matched noise, not a real id.
    if (ident & 0xFFFF) > 0x100:
        return None
    if (ident >> 48) in nibbles and (ident & ((1 << 48) - 1)) != 0:
        return ident, nxt
    return None


def _uvarint_ending_at(raw: bytes, pos: int):
    if pos <= 0 or raw[pos - 1] & 0x80:
        return None
    start = pos - 1
    while start > 0 and raw[start - 1] & 0x80:
        start -= 1
    r = _try_uv(raw, start)
    if r and r[1] == pos:
        return r[0]
    return None


@dataclass
class LineRecord:
    id: str
    name: str
    code: str | None
    color: str | None
    stops: list[str] = field(default_factory=list)  # ordered station id hex


@dataclass
class SignalRecord:
    id: str
    lon: float
    lat: float


@dataclass
class TrainRecord:
    id: str
    name: str


@dataclass
class ScheduleRecord:
    id: str
    name: str
    color: str | None
    stop_count: int  # >=2 means it also carries a drawable route template


def _name_after_id(raw: bytes, end: int, skip: int = 2):
    """Read the record name, tolerating a few optional uvarint fields after the id.

    Two record variants exist: ``[id][namelen][name]`` (most objects) and
    ``[id][extra uvarint field][namelen][name]`` (e.g. some schedules). Try the
    name directly first, then skip up to ``skip`` leading uvarint fields.
    """
    p = end
    for _ in range(skip + 1):
        nm = _read_name(raw, p, mn=2, mx=80)
        if nm:
            return nm
        r = _try_uv(raw, p)
        if not r or r[1] == p:
            break
        p = r[1]
    return None


def _find_name_records(raw: bytes, type_nibble: int):
    recs = []
    seen: set[int] = set()
    n = len(raw)
    i = 0
    while i < n - 12:
        # Fast pre-filter: every object id is an 8-byte varint whose 8th byte
        # equals the type nibble (idx<2**48 never reaches that byte). This skips
        # the full uvarint decode on ~255/256 positions.
        if raw[i + 7] != type_nibble:
            i += 1
            continue
        r = _is_id(raw, i, {type_nibble})
        if r:
            ident, end = r
            nm = _name_after_id(raw, end)
            if nm and ident not in seen:
                seen.add(ident)
                recs.append((i, ident, nm[0], nm[1]))
                i = end
                continue
        i += 1
    recs.sort()
    return recs


def _collect_stops(raw: bytes, color_end: int, end: int) -> list[int]:
    first_id_pos = None
    i = color_end
    while i < end:
        if _is_id(raw, i, {TYPE_TRACK, TYPE_STATION}):
            first_id_pos = i
            break
        i += 1
    if first_id_pos is None:
        return []
    count = _uvarint_ending_at(raw, first_id_pos)
    stops: list[int] = []
    i = first_id_pos
    while i < end and (count is None or len(stops) < count):
        r = _is_id(raw, i, {TYPE_STATION})
        if r:
            ident, nxt = r
            if not stops or stops[-1] != ident:
                stops.append(ident)
            i = nxt
            continue
        r2 = _try_uv(raw, i)
        i = r2[1] if r2 else i + 1
    return stops


def read_lines_from_raw(raw: bytes) -> list[LineRecord]:
    """Lines are stored on the name-bearing (Schedule, 0x6) records with stops."""
    recs = _find_name_records(raw, TYPE_SCHEDULE)
    starts = [r[0] for r in recs]
    out: list[LineRecord] = []
    for idx, (start, ident, name, name_end) in enumerate(recs):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(raw)
        cur = name_end
        code = None
        cr = _read_name(raw, cur, mn=0, mx=40)
        if cr:
            code, cur = cr
        color = None
        color_end = cur
        if cur < end and raw[cur] == 0:  # tag count 0
            cv = _try_uv(raw, cur + 1)
            if cv:
                color = cv[0]
                color_end = cv[1]
        stops = _collect_stops(raw, color_end, end)
        out.append(LineRecord(
            id=hex(ident), name=name, code=code,
            color=("0x%08x" % color) if color else None,
            stops=[hex(s) for s in stops],
        ))
    return out


@dataclass
class TimetableStop:
    station_id: str
    arrival: int  # cumulative seconds from run start
    departure: int


@dataclass
class TimetableRecord:
    id: str
    name: str
    color: str | None
    cycle_seconds: int  # last stop departure = full one-run duration (JSON-free)
    stops: list[TimetableStop] = field(default_factory=list)


def _extract_stop_times(raw: bytes, start: int, end: int, max_stops: int):
    """Per-stop cumulative (arrival, departure) seconds from a route template.

    Each stop is stored as ``<idx=2k> 01 <leg*2> <arr*2> <dep*2> …`` where the
    counter idx increments by 2 and all times are in half-second units (value =
    seconds * 2). Validated exact-to-the-second against exports on 32/37 routes
    (regional + metro). The walk is bounded by ``max_stops`` so it never bleeds
    into the next line's template, which follows immediately in memory.
    """
    times: list[tuple[int, int]] = []
    first_leg = None
    i = start
    expected = 2
    prev_dep = -1
    want = max_stops - 1 if max_stops else None  # origin stop is prepended
    while i < end - 4:
        if want is not None and len(times) >= want:
            break
        r = _try_uv(raw, i)
        if not r:
            i += 1
            continue
        val, nxt = r
        if val == expected and nxt < end and raw[nxt] == 0x01:
            p = nxt + 1
            trip = []
            ok = True
            for _ in range(3):
                rr = _try_uv(raw, p)
                if not rr:
                    ok = False
                    break
                trip.append(rr[0])
                p = rr[1]
            if ok:
                leg2, arr2, dep2 = trip
                if (arr2 % 2 == 0 and dep2 % 2 == 0 and 0 <= dep2 - arr2 <= 3600
                        and arr2 // 2 > prev_dep - 1 and dep2 < 10 ** 7):
                    if first_leg is None:
                        first_leg = leg2 // 2
                    times.append((arr2 // 2, dep2 // 2))
                    prev_dep = dep2 // 2
                    expected += 2
                    i = p
                    continue
        i = nxt
    if times and first_leg is not None:
        origin_dep = times[0][0] - first_leg  # arr1 - leg1 == origin dwell end
        if origin_dep >= 0:
            times.insert(0, (0, origin_dep))
    return times


def read_line_timetables(raw: bytes) -> list[TimetableRecord]:
    """JSON-free per-line timetable: ordered stops with relative arr/dep + cycle.

    The timing template lives on the *route* object (e.g. ``TTC Yonge–University``,
    ``GO Kitchener Line``), not on the *service* schedule (``TTC Line 1 Daily``).
    ``cycle_seconds`` is the full one-run duration (time moving + dwelling); the
    per-train dispatch interval additionally includes turnaround/layover.
    """
    recs = _find_name_records(raw, TYPE_SCHEDULE)
    starts = [r[0] for r in recs]
    out: list[TimetableRecord] = []
    for idx, (start, ident, name, name_end) in enumerate(recs):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(raw)
        cur = name_end
        cr = _read_name(raw, cur, mn=0, mx=40)
        if cr:
            _code, cur = cr
        color = None
        color_end = cur
        if cur < end and raw[cur] == 0:
            cv = _try_uv(raw, cur + 1)
            if cv:
                color = cv[0]
                color_end = cv[1]
        stops = _collect_stops(raw, color_end, end)
        if len(stops) < 2:
            continue
        times = _extract_stop_times(raw, name_end, end, max_stops=len(stops))
        m = min(len(stops), len(times))
        stop_recs = [TimetableStop(station_id=hex(stops[k]),
                                   arrival=times[k][0], departure=times[k][1])
                     for k in range(m)]
        cycle = times[m - 1][1] if m else 0
        out.append(TimetableRecord(
            id=hex(ident), name=name,
            color=("0x%08x" % color) if color else None,
            cycle_seconds=cycle, stops=stop_recs,
        ))
    return out


@dataclass
class TagRecord:
    id: str
    name: str
    parent: str  # "0x0" for a top-level category


def _tag_at(raw: bytes, q: int):
    """Parse a tag body ``[id*2][id*2][parent*2][namelen][name]`` at offset q.

    Tag ids are small integers (not the ``type<<48`` object ids); the id is
    written twice, then the parent id, all doubled (LSB parity marker).
    """
    a = _try_uv(raw, q)
    if not a or a[0] == 0 or a[0] % 2:
        return None
    id1, p = a
    b = _try_uv(raw, p)
    if not b or b[0] != id1:
        return None
    p = b[1]
    c = _try_uv(raw, p)
    if not c or c[0] % 2:
        return None
    par, p = c
    nm = _read_name(raw, p, mn=1, mx=40)
    if not nm:
        return None
    return id1 // 2, par // 2, nm[0], nm[1]


def read_tags_from_raw(raw: bytes) -> list[TagRecord]:
    """Hierarchical tag taxonomy (train purpose / gauge / power / …).

    Definitions sit in one cluster; most are prefixed by the marker
    ``ff ff ff ff 0f 01 <cat> 00`` then the tag body. A few (first in a
    sub-group) lack the marker, so after locating the marker-anchored tags we
    sweep the bounded cluster for the ``[id][id][parent][name]`` body to pick up
    stragglers without risking false positives outside the tag region.
    Validated 64/64 (name + parent exact, 0 false positives) vs export.
    """
    MARK = b"\xff\xff\xff\xff\x0f"
    out: dict[int, TagRecord] = {}
    positions: list[int] = []
    n = len(raw)
    i = 0
    while True:
        p = raw.find(MARK, i)
        if p < 0:
            break
        i = p + 1
        q = p + 5
        if q + 3 >= n or raw[q] != 0x01 or raw[q + 2] != 0x00:
            continue
        t = _tag_at(raw, q + 3)
        if t and 0 < t[0] < 0x80000:
            out.setdefault(t[0], TagRecord(id=hex(t[0]), name=t[2], parent=hex(t[1])))
            positions.append(p)
    if positions:
        lo = max(0, min(positions) - 500)
        hi = min(n, max(positions) + 500)
        j = lo
        while j < hi:
            t = _tag_at(raw, j)
            if t and 0 < t[0] < 0x80000 and t[0] not in out:
                out[t[0]] = TagRecord(id=hex(t[0]), name=t[2], parent=hex(t[1]))
                j = t[3]
                continue
            j += 1
    return list(out.values())


def read_signals_from_raw(raw: bytes) -> list[SignalRecord]:
    """Type 0x3 positioned nodes (signals / switches) carrying Mercator coords."""
    out: dict[int, SignalRecord] = {}
    n = len(raw)
    i = 0
    while i < n - 24:
        if raw[i + 7] != TYPE_SIGNAL:
            i += 1
            continue
        r = _is_id(raw, i, {TYPE_SIGNAL})
        if r:
            ident, end = r
            found = None
            for k in range(0, 20):
                o = end + k
                if o + 16 <= n and raw[o + 7] in _HI and raw[o + 15] in _HI:
                    x = struct.unpack_from("<d", raw, o)[0]
                    y = struct.unpack_from("<d", raw, o + 8)[0]
                    if -2.1e7 < x < 2.1e7 and 1e5 < y < 2e7 and abs(x) > 1e4:
                        found = (x, y)
                        break
            if found and ident not in out:
                lon, lat = mercator_to_lonlat(*found)
                if -180 <= lon <= 180 and -85 <= lat <= 85:
                    out[ident] = SignalRecord(id=hex(ident), lon=lon, lat=lat)
            i = end
            continue
        i += 1
    return list(out.values())


def read_trains_from_raw(raw: bytes) -> list[TrainRecord]:
    """Train records: [id(0x5)][meta uvarint][namelen][name utf8]. Self-describing."""
    out: dict[int, TrainRecord] = {}
    n = len(raw)
    i = 0
    while i < n - 12:
        if raw[i + 7] != TYPE_TRAIN:
            i += 1
            continue
        r = _is_id(raw, i, {TYPE_TRAIN})
        if r:
            ident, end = r
            meta = _try_uv(raw, end)
            if meta:
                nm = _read_name(raw, meta[1], mn=1, mx=80)
                if nm and ident not in out:
                    out[ident] = TrainRecord(id=hex(ident), name=nm[0])
                    i = meta[1]
                    continue
        i += 1
    return list(out.values())


@dataclass
class AssignmentRecord:
    schedule_id: str
    train_ids: list[str]
    shift_ids: list[str]
    count: int


def _train_id_runs(raw: bytes):
    """Yield (run_start, length, [ids]) for maximal runs of adjacent 0x5 train ids."""
    n = len(raw)
    i = 0
    positions = []  # (start, ident, end)
    while i < n - 8:
        if raw[i + 7] == TYPE_TRAIN:
            r = _is_id(raw, i, {TYPE_TRAIN})
            if r:
                positions.append((i, r[0], r[1]))
                i = r[1]
                continue
        i += 1
    k = 0
    m = len(positions)
    while k < m:
        run = [positions[k]]
        j = k + 1
        while j < m and positions[j][0] == run[-1][2]:
            run.append(positions[j])
            j += 1
        yield run[0][0], len(run), [p[1] for p in run]
        k = j


def _shift_list_before(raw: bytes, count_pos: int, n: int):
    """Match [n][n uvarints] whose bytes end exactly at count_pos (train count byte)."""
    lo = max(0, count_pos - 2 - n * 5)
    for q in range(lo, count_pos):
        if raw[q] != n:
            continue
        j = q + 1
        vals = []
        ok = True
        for _ in range(n):
            r = _try_uv(raw, j)
            if not r or r[1] > count_pos:
                ok = False
                break
            vals.append(r[0])
            j = r[1]
        if ok and j == count_pos and len(vals) == n:
            return [v >> 1 for v in vals]
    return None


def read_schedule_assignments(raw: bytes) -> list[AssignmentRecord]:
    """Reconstruct schedule -> (assigned trains, shifts) from the config region.

    Each schedule config block ends with a self-validating pair
    ``[N][N shift ids][N][N train ids]``. Train ids and shift ids are recovered as
    sets/counts (validated 35/35 vs export); the 1:1 train<->shift pairing is stored
    by creation order elsewhere and is not reconstructed here.
    """
    # All 0x6 id+name positions WITHOUT dedup: a schedule is defined twice (route
    # region and config region), and each train run must attach to the config-region
    # head that immediately precedes it.
    heads = []
    n = len(raw)
    i = 0
    while i < n - 12:
        if raw[i + 7] == TYPE_SCHEDULE:
            r = _is_id(raw, i, {TYPE_SCHEDULE})
            if r:
                ident, end = r
                if _name_after_id(raw, end):
                    heads.append((i, ident))
                    i = end
                    continue
        i += 1
    if not heads:
        return []
    head_pos = [h[0] for h in heads]
    import bisect

    best: dict[int, AssignmentRecord] = {}
    for run_start, length, train_ids in _train_id_runs(raw):
        if length < 1 or length > 127:
            continue
        count_pos = run_start - 1
        if count_pos < 0 or raw[count_pos] != length:
            continue
        shifts = _shift_list_before(raw, count_pos, length)
        if shifts is None:
            continue
        idx = bisect.bisect_right(head_pos, run_start) - 1
        if idx < 0:
            continue
        sched_id = heads[idx][1]
        prev = best.get(sched_id)
        if prev is None or length > prev.count:
            best[sched_id] = AssignmentRecord(
                schedule_id=hex(sched_id),
                train_ids=[hex(t) for t in train_ids],
                shift_ids=[hex(s) for s in shifts],
                count=length,
            )
    return list(best.values())


def read_schedules_from_raw(raw: bytes) -> list[ScheduleRecord]:
    """Every Schedule (0x6) = timetable container: id + name + color.

    Schedules share the 0x6 name-record layout with route templates; those that
    also embed an ordered stop list (>=2 stops) are what gets drawn as a line on
    the map, while the rest are pure timetable containers referencing a route.
    """
    lines = read_lines_from_raw(raw)
    return [
        ScheduleRecord(id=ln.id, name=ln.name, color=ln.color, stop_count=len(ln.stops))
        for ln in lines
    ]


def read_network(
    save_path: Path,
    include_signals: bool = True,
    include_trains: bool = False,
) -> dict:
    raw = Zstd().decompress(split_save(Path(save_path))[1])
    stations = read_stations_from_raw(raw)
    lines = read_lines_from_raw(raw)
    drawable = [ln for ln in lines if len(ln.stops) >= 2]
    signals = read_signals_from_raw(raw) if include_signals else []
    trains = read_trains_from_raw(raw) if include_trains else []
    result = {
        "stations": [
            {"id": s.id, "name": s.name, "lon": s.lon, "lat": s.lat} for s in stations
        ],
        "lines": [
            {"id": ln.id, "name": ln.name, "code": ln.code,
             "color": ln.color, "stops": ln.stops}
            for ln in drawable
        ],
        "signals": [{"id": s.id, "lon": s.lon, "lat": s.lat} for s in signals],
        "counts": {
            "stations": len(stations),
            "lines": len(drawable),
            "signals": len(signals),
            "schedules": len(lines),
        },
    }
    if include_trains:
        result["trains"] = [{"id": t.id, "name": t.name} for t in trains]
        result["counts"]["trains"] = len(trains)
    return result


def _cli(argv: list[str]) -> int:
    import argparse
    import json
    import sys

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="JSON-free 直读存档路网（站/线/信号）")
    ap.add_argument("save", type=Path)
    ap.add_argument("--no-signals", action="store_true")
    ap.add_argument("--json", action="store_true", help="输出完整 JSON")
    args = ap.parse_args(argv)

    net = read_network(args.save, include_signals=not args.no_signals)
    if args.json:
        print(json.dumps(net, ensure_ascii=False, indent=2))
    else:
        c = net["counts"]
        print(
            f"车站 {c['stations']}  线路 {c['lines']}  信号/道岔 {c['signals']}"
            f"  时刻表 {c.get('schedules', 0)}"
        )
        for ln in net["lines"][:15]:
            print(f"  {ln['name']:<32} {ln['code'] or '':<8} {ln['color'] or '':<12} {len(ln['stops'])} 站")
    return 0


if __name__ == "__main__":
    import sys as _sys

    raise SystemExit(_cli(_sys.argv[1:]))
