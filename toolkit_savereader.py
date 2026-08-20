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


def _find_name_records(raw: bytes, type_nibble: int):
    recs = []
    n = len(raw)
    i = 0
    while i < n - 12:
        r = _is_id(raw, i, {type_nibble})
        if r:
            ident, end = r
            nm = _read_name(raw, end, mn=2, mx=80)
            if nm:
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


def read_signals_from_raw(raw: bytes) -> list[SignalRecord]:
    """Type 0x3 positioned nodes (signals / switches) carrying Mercator coords."""
    out: dict[int, SignalRecord] = {}
    n = len(raw)
    i = 0
    while i < n - 24:
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
        print(f"车站 {c['stations']}  线路 {c['lines']}  信号/道岔 {c['signals']}")
        for ln in net["lines"][:15]:
            print(f"  {ln['name']:<32} {ln['code'] or '':<8} {ln['color'] or '':<12} {len(ln['stops'])} 站")
    return 0


if __name__ == "__main__":
    import sys as _sys

    raise SystemExit(_cli(_sys.argv[1:]))
