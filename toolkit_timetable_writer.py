"""Write custom timetables into a NEW save by editing the stored timing inputs.

Ground truth
------------
Everything below was established from a controlled before/after pair produced by
the game itself (``DIFF_A`` = default stop time 30s, ``DIFF_B`` = 59s, saved back
to back with the simulation paused) and cross-checked against the official wiki.

- The *displayed* timetable is *not* stored. The wiki is explicit that line
  timings are recomputed on load ("initializing timetables"). The cumulative
  ``arr/dep`` board in the save is a derived cache, and rewriting it alone has no
  effect in game (verified experimentally).
- The stored **inputs** are what matter. Per line record the layout is::

      per stop      <leg_distance f32> <leg_speed f32> <accel f32> <brake f32> <stop_time>
      line defaults <cruise_speed f32> <accel f32> <brake f32> <ref_train id 0x5> <stop_time>

  ``accel``/``brake`` are ``0.0`` on stops that inherit the line defaults, which
  matches the wiki's "Default timings" panel (reference train, cruise speed,
  max acceleration, max braking, default stop time).
- ``stop_time`` is a uvarint in **half-seconds**: the ground-truth pair moves
  every one of these fields from ``60`` (30s) to ``118`` (59s).
- Critically, the wiki defines the line default as "the stop time that will be
  assigned to every stop when not changed manually". The game therefore writes
  the default *and* every per-stop copy together, and re-applies the default on
  load. Editing only the per-stop copies is silently reverted (verified
  experimentally). **Both must be written.**
- The save header carries a hash of the game data but it is not enforced on
  local load (existing coordinate/migration writes keep the header verbatim and
  load fine), so the object stream may be rewritten as long as it stays
  structurally valid.

This module never touches the original save; callers pass the decompressed
``raw`` and get a new ``raw`` back, then write it through
``toolkit_backend.write_output`` (header verbatim + zstd + read-back verify).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

import toolkit_savereader as sr
from toolkit_binary import uvarint

# Maximum plausible stop time, in half-seconds (2h). Used to reject false hits.
MAX_STOP_TIME_HALF = 2 * 3600
_ZERO8 = b"\x00" * 8

# The 8-byte "mode" region between <leg_speed f32> and <stop_time uvarint>.
# Ground truth (FLAG_A inherit -> FLAG_B one stop set to a custom time):
#   inherit : 00*8
#   manual  : 00 | <f32 1.0> | 00 00 | 02   == 00 00 00 80 3f 00 00 02
# The f32 1.0 lives at mode[1:5] (byte L+9), the trailing 0x02 at mode[7] (L+15).
INHERIT_MODE = _ZERO8
MANUAL_MODE = bytes.fromhex("000000803f000002")


@dataclass
class StopTiming:
    idx: int                    # the stored 2k counter
    leg_off: int                # byte offset of the leg uvarint
    leg_len: int
    arr_off: int
    arr_len: int
    dep_off: int
    dep_len: int
    leg: int                    # half-second values (as stored)
    arr: int
    dep: int


@dataclass
class RouteTiming:
    id: str
    name: str
    name_end: int
    region_end: int
    origin_dep_half: int        # implicit origin departure (half-seconds)
    stops: list[StopTiming] = field(default_factory=list)


def _uv_span(raw: bytes, off: int) -> tuple[int, int]:
    """Return (value, byte_length) of the uvarint at ``off``."""
    r = sr._try_uv(raw, off)
    if not r:
        raise ValueError(f"bad uvarint at {off}")
    return r[0], r[1] - off


def extract_route_timing(raw: bytes, start: int, end: int, max_stops: int,
                         ident: str, name: str) -> RouteTiming | None:
    """Offset-aware twin of ``toolkit_savereader._extract_stop_times``.

    Walks the exact same validated pattern but records the byte spans of each
    ``leg/arr/dep`` uvarint so they can be rewritten. Returns ``None`` if fewer
    than one timed stop is found.
    """
    stops: list[StopTiming] = []
    first_leg = None
    i = start
    expected = 2
    prev_dep = -1
    want = max_stops - 1 if max_stops else None
    while i < end - 4:
        if want is not None and len(stops) >= want:
            break
        r = sr._try_uv(raw, i)
        if not r:
            i += 1
            continue
        val, nxt = r
        if val == expected and nxt < end and raw[nxt] == 0x01:
            p = nxt + 1
            spans = []
            ok = True
            for _ in range(3):
                rr = sr._try_uv(raw, p)
                if not rr:
                    ok = False
                    break
                spans.append((rr[0], p, rr[1] - p))
                p = rr[1]
            if ok:
                (leg2, leg_off, leg_len), (arr2, arr_off, arr_len), (dep2, dep_off, dep_len) = spans
                if (arr2 % 2 == 0 and dep2 % 2 == 0 and 0 <= dep2 - arr2 <= 3600
                        and arr2 // 2 > prev_dep - 1 and dep2 < 10 ** 7):
                    if first_leg is None:
                        first_leg = leg2 // 2
                    stops.append(StopTiming(
                        idx=val, leg_off=leg_off, leg_len=leg_len,
                        arr_off=arr_off, arr_len=arr_len,
                        dep_off=dep_off, dep_len=dep_len,
                        leg=leg2, arr=arr2, dep=dep2,
                    ))
                    prev_dep = dep2 // 2
                    expected += 2
                    i = p
                    continue
        i = nxt
    if not stops or first_leg is None:
        return None
    origin_dep_half = stops[0].arr - stops[0].leg  # arr1 - leg1 (half-seconds)
    return RouteTiming(id=ident, name=name, name_end=start, region_end=end,
                       origin_dep_half=max(0, origin_dep_half), stops=stops)


def find_route_timings(raw: bytes) -> list[RouteTiming]:
    """All route templates with editable per-stop timing, with byte offsets."""
    recs = sr._find_name_records(raw, sr.TYPE_SCHEDULE)
    starts = [r[0] for r in recs]
    out: list[RouteTiming] = []
    for idx, (start, ident, name, name_end) in enumerate(recs):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(raw)
        stops_ids = sr._collect_stops(raw, name_end, end)
        if len(stops_ids) < 2:
            continue
        rt = extract_route_timing(raw, name_end, end, len(stops_ids), hex(ident), name)
        if rt and rt.stops:
            out.append(rt)
    return out


def get_route_timing(raw: bytes, route_id: str) -> RouteTiming | None:
    for rt in find_route_timings(raw):
        if rt.id == route_id or rt.name == route_id:
            return rt
    return None


def _apply_spans(raw: bytes, edits: list[tuple[int, int, bytes]]) -> bytes:
    """Rebuild ``raw`` replacing (offset, old_len, new_bytes) spans.

    Spans must be non-overlapping. Lengths may change (varints re-encode); the
    object stream is parsed sequentially so shifting later bytes is safe.
    """
    edits = sorted(edits, key=lambda e: e[0])
    out = bytearray()
    cur = 0
    for off, old_len, new_bytes in edits:
        if off < cur:
            raise ValueError("overlapping edit spans")
        out += raw[cur:off]
        out += new_bytes
        cur = off + old_len
    out += raw[cur:]
    return bytes(out)


def roundtrip_identity(raw: bytes, route_id: str) -> bool:
    """Re-encode a route's timing varints unchanged; result must equal ``raw``.

    Correctness gate: proves we locate the exact bytes and encode them
    canonically before doing any real edit.
    """
    rt = get_route_timing(raw, route_id)
    if not rt:
        raise ValueError(f"route not found: {route_id}")
    edits: list[tuple[int, int, bytes]] = []
    for s in rt.stops:
        edits.append((s.leg_off, s.leg_len, uvarint(s.leg)))
        edits.append((s.arr_off, s.arr_len, uvarint(s.arr)))
        edits.append((s.dep_off, s.dep_len, uvarint(s.dep)))
    rebuilt = _apply_spans(raw, edits)
    return rebuilt == raw


# --------------------------------------------------------------------------
# Stop time inputs (the fields the game actually reads back on load)
# --------------------------------------------------------------------------


@dataclass
class StopTimeField:
    """One stored stop-time uvarint, in half-seconds, plus its mode region."""

    off: int                    # offset of the stop_time uvarint (== leg L + 16)
    length: int
    half: int                   # stored value (seconds * 2)
    leg_distance: float | None = None
    leg_speed: float | None = None
    mode_off: int | None = None  # offset of the 8-byte mode region (L + 8)
    is_manual: bool = False      # True when this stop overrides the line default
    is_default: bool = False     # True for the line-level default field (no mode)

    @property
    def seconds(self) -> float:
        return self.half / 2.0


@dataclass
class LineTiming:
    """Editable stop-time inputs of a single line record."""

    id: str
    name: str
    start: int
    end: int
    stops: list[StopTimeField] = field(default_factory=list)
    default: StopTimeField | None = None

    @property
    def fields(self) -> list[StopTimeField]:
        """Every stop-time field, defaults first, in file order."""
        out = list(self.stops)
        if self.default is not None:
            out.append(self.default)
        return sorted(out, key=lambda f: f.off)


def _f32(raw: bytes, off: int) -> float | None:
    try:
        value = struct.unpack_from("<f", raw, off)[0]
    except struct.error:
        return None
    return value if value == value else None  # reject NaN


def _mode_is_manual(mode: bytes) -> bool:
    """True if the 8-byte mode region marks a manual per-stop override."""
    return len(mode) == 8 and mode[0:3] == b"\x00\x00\x00" and abs((
        struct.unpack_from("<f", mode, 1)[0]) - 1.0) < 1e-6


def _find_stop_time_fields(raw: bytes, start: int, end: int) -> list[StopTimeField]:
    """Locate per-stop stop-time uvarints inside one line record.

    Anchored on ``<leg_distance f32> <leg_speed f32> <mode 8B> <stop_time>``. The
    mode region is either all-zero (stop inherits the line default) or carries the
    manual-override marker (f32 1.0 at byte 1, 0x02 at byte 7).
    """
    out: list[StopTimeField] = []
    i = start
    while i < end - 17:
        mode = raw[i + 8:i + 16]
        manual = _mode_is_manual(mode)
        if mode != _ZERO8 and not manual:
            i += 1
            continue
        distance = _f32(raw, i)
        speed = _f32(raw, i + 4)
        if distance is None or speed is None:
            i += 1
            continue
        if not (1.0 < distance < 2_000_000.0) or not (0.5 < speed < 1500.0):
            i += 1
            continue
        r = sr._try_uv(raw, i + 16)
        if not r or not (0 < r[0] <= MAX_STOP_TIME_HALF):
            i += 1
            continue
        out.append(StopTimeField(off=i + 16, length=r[1] - (i + 16), half=r[0],
                                 leg_distance=distance, leg_speed=speed,
                                 mode_off=i + 8, is_manual=manual))
        i = r[1]
    return out


def _find_default_stop_time(raw: bytes, start: int, end: int) -> StopTimeField | None:
    """Locate the line-level default stop time (follows the reference train id)."""
    i = start
    while i < end - 9:
        if raw[i + 7] == sr.TYPE_TRAIN and sr._is_id(raw, i, {sr.TYPE_TRAIN}):
            r = sr._try_uv(raw, i + 8)
            if r and 0 < r[0] <= MAX_STOP_TIME_HALF:
                return StopTimeField(off=i + 8, length=r[1] - (i + 8), half=r[0],
                                     is_default=True)
        i += 1
    return None


def find_line_timings(raw: bytes) -> list[LineTiming]:
    """Every line record that exposes editable stop-time inputs."""
    recs = sr._find_name_records(raw, sr.TYPE_SCHEDULE)
    starts = [r[0] for r in recs]
    out: list[LineTiming] = []
    for idx, (start, ident, name, name_end) in enumerate(recs):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(raw)
        stops = _find_stop_time_fields(raw, name_end, end)
        if not stops:
            continue
        out.append(LineTiming(id=hex(ident), name=name, start=start, end=end,
                              stops=stops, default=_find_default_stop_time(raw, name_end, end)))
    return out


def get_line_timing(raw: bytes, key: str) -> LineTiming | None:
    for lt in find_line_timings(raw):
        if lt.id == key or lt.name == key:
            return lt
    return None


def stop_time_roundtrip_identity(raw: bytes, key: str | LineTiming) -> bool:
    """Re-encode a line's stop-time varints unchanged; result must equal ``raw``.

    Correctness gate: proves the exact bytes are located and encoded canonically
    before any real edit is attempted. Accepts an already-resolved ``LineTiming``
    so callers can avoid rescanning the whole object stream.
    """
    lt = key if isinstance(key, LineTiming) else get_line_timing(raw, key)
    if not lt:
        raise ValueError(f"line not found: {key}")
    edits = [(f.off, f.length, uvarint(f.half)) for f in lt.fields]
    return _apply_spans(raw, edits) == raw


def set_line_stop_time(raw: bytes, key: str | LineTiming, seconds: float,
                       ) -> tuple[bytes, LineTiming, int]:
    """Set the stop time of a whole line, exactly the way the game does it.

    Writes the line-level default *and* every per-stop copy, because the game
    re-applies the default to inheriting stops on load; changing only the
    per-stop copies is silently reverted.

    Returns ``(new_raw, before, fields_written)``.
    """
    lt = key if isinstance(key, LineTiming) else get_line_timing(raw, key)
    if not lt:
        raise ValueError(f"line not found: {key}")
    half = int(round(seconds * 2))
    if not (0 < half <= MAX_STOP_TIME_HALF):
        raise ValueError(f"stop time out of range: {seconds}s")
    if not stop_time_roundtrip_identity(raw, lt):
        raise ValueError(f"round-trip identity failed for {lt.name}; refusing to write")
    edits = [(f.off, f.length, uvarint(half)) for f in lt.fields]
    return _apply_spans(raw, edits), lt, len(edits)


def set_stop_times(raw: bytes, key: str | LineTiming,
                   seconds: list[float | None],
                   default_seconds: float | None = None,
                   ) -> tuple[bytes, LineTiming, int]:
    """Set individual per-stop stop times, marking overridden stops as manual.

    ``seconds`` is aligned to ``lt.stops`` (file order). ``None`` for a stop means
    "inherit the line default"; a number marks that stop as a manual override
    (writes the manual mode template + value), exactly as the game does when the
    player edits a single stop's custom stop time.

    ``default_seconds`` optionally rewrites the line-level default (which the game
    re-applies to every inheriting stop on load). If omitted, the current default
    is kept. Returns ``(new_raw, before, fields_written)``.
    """
    lt = key if isinstance(key, LineTiming) else get_line_timing(raw, key)
    if not lt:
        raise ValueError(f"line not found: {key}")
    if len(seconds) != len(lt.stops):
        raise ValueError(f"expected {len(lt.stops)} stop values, got {len(seconds)}")
    if not stop_time_roundtrip_identity(raw, lt):
        raise ValueError(f"round-trip identity failed for {lt.name}; refusing to write")

    def _half(sec: float) -> int:
        h = int(round(sec * 2))
        if not (0 < h <= MAX_STOP_TIME_HALF):
            raise ValueError(f"stop time out of range: {sec}s")
        return h

    default_half = lt.default.half if lt.default else None
    if default_seconds is not None:
        default_half = _half(default_seconds)

    edits: list[tuple[int, int, bytes]] = []
    written = 0
    for field_, sec in zip(lt.stops, seconds):
        if field_.mode_off is None:
            continue
        if sec is None:
            edits.append((field_.mode_off, 8, INHERIT_MODE))
            if default_half is not None:
                edits.append((field_.off, field_.length, uvarint(default_half)))
        else:
            edits.append((field_.mode_off, 8, MANUAL_MODE))
            edits.append((field_.off, field_.length, uvarint(_half(sec))))
        written += 1
    if lt.default is not None and default_half is not None:
        edits.append((lt.default.off, lt.default.length, uvarint(default_half)))
    return _apply_spans(raw, edits), lt, written
