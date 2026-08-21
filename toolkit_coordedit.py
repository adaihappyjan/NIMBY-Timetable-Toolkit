"""Read stations and edit their coordinates directly in the binary save.

This module is JSON-free: it reads station identity + Web Mercator coordinates
straight from the decompressed object stream, and can overwrite a station's
position in place (fixed 16-byte f64 pair, so payload length never changes).

Safety model (mirrors the rest of the toolkit):
  * never overwrites the input save; writes a brand-new file
  * only rewrites the exact 16 coordinate bytes per targeted station
  * re-compresses and verifies via reverse decompression before writing
  * refuses to write if a target station cannot be uniquely located
"""
from __future__ import annotations

import math
import re
import struct
from dataclasses import dataclass
from pathlib import Path

from toolkit_binary import Zstd, split_save, read_uvarint, uvarint

WGS84_R = 6378137.0
TYPE_STATION = 0x2
_HI = {0x40, 0x41, 0xC0, 0xC1}  # f64 high byte for continental Mercator magnitudes


def lonlat_to_mercator(lon: float, lat: float) -> tuple[float, float]:
    if not (-180.0 <= lon <= 180.0):
        raise ValueError(f"longitude out of range: {lon}")
    if not (-85.06 <= lat <= 85.06):
        raise ValueError(f"latitude out of range (Web Mercator limit): {lat}")
    x = WGS84_R * math.radians(lon)
    y = WGS84_R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
    return x, y


def mercator_to_lonlat(x: float, y: float) -> tuple[float, float]:
    lon = math.degrees(x / WGS84_R)
    lat = math.degrees(2 * math.atan(math.exp(y / WGS84_R)) - math.pi / 2)
    return lon, lat


def _try_uvarint(raw: bytes, off: int, max_bytes: int = 10):
    val = 0
    shift = 0
    for k in range(max_bytes):
        if off + k >= len(raw) or off + k < 0:
            return None
        b = raw[off + k]
        val |= (b & 0x7F) << shift
        if b < 0x80:
            return val, off + k + 1
        shift += 7
    return None


def _read_name(raw: bytes, off: int, min_len: int = 2, max_len: int = 80):
    r = _try_uvarint(raw, off)
    if not r:
        return None
    n, after = r
    if not (min_len <= n <= max_len) or after + n > len(raw):
        return None
    try:
        text = raw[after:after + n].decode("utf-8")
    except UnicodeDecodeError:
        return None
    if any(ord(c) < 0x20 and c != "\t" for c in text):
        return None
    return text, after + n


def _station_id_before(raw: bytes, coord_off: int):
    for back in range(1, 41):
        r = _try_uvarint(raw, coord_off - back)
        if not r:
            continue
        val, end = r
        if end > coord_off or (val & 1):
            continue
        ident = val >> 1
        if (ident >> 48) != TYPE_STATION:
            continue
        if ident & ((1 << 48) - 1) == 0:
            continue
        return ident
    return None


@dataclass
class StationRecord:
    id: str
    name: str
    lon: float
    lat: float
    coord_off: int  # byte offset of the f64 X within the decompressed payload


def read_stations_from_raw(raw: bytes) -> list[StationRecord]:
    """Enumerate every station (id + coords, plus name when stored) in the payload.

    A station record is ``[id(0x2)][4B meta][f64 x][f64 y]…``; the id sits exactly
    12 bytes before the coordinate pair. Stations the player named store the name
    inline right after the coordinates; stations that come from a real-network mod
    keep only id + coords + platform tracks (their display name lives in the mod, not
    the save), so we fall back to a stable id-based label for those.
    """
    out: dict[int, StationRecord] = {}
    n = len(raw)
    i = 0
    while i < n - 34:
        if raw[i + 7] in _HI and raw[i + 15] in _HI:
            x = struct.unpack_from("<d", raw, i)[0]
            y = struct.unpack_from("<d", raw, i + 8)[0]
            if -2.1e7 < x < 2.1e7 and 1.0e5 < y < 2.0e7 and abs(x) > 1.0e4:
                ident = _station_id_before(raw, i)
                if ident is not None and ident not in out:
                    lon, lat = mercator_to_lonlat(x, y)
                    if -180 <= lon <= 180 and -85 <= lat <= 85:
                        nm = _read_name(raw, i + 16)
                        name = nm[0] if nm else f"车站 {hex(ident)}"
                        out[ident] = StationRecord(
                            id=hex(ident), name=name, lon=lon, lat=lat, coord_off=i
                        )
                        i += 24
        i += 1
    return sorted(out.values(), key=lambda s: s.coord_off)


def read_stations(save_path: Path) -> list[StationRecord]:
    raw = Zstd().decompress(split_save(save_path)[1])
    return read_stations_from_raw(raw)


def set_station_coordinates(
    input_save: Path,
    output_save: Path,
    updates: dict[str, tuple[float, float]],
    level: int = 3,
) -> dict:
    """Overwrite coordinates for the given stations (keyed by id hex or exact name).

    updates: {station_id_or_name: (lon, lat)}
    Returns a manifest describing what changed.
    """
    input_save = Path(input_save)
    output_save = Path(output_save)
    if input_save.resolve() == output_save.resolve():
        raise RuntimeError("refusing to overwrite the input save")
    if output_save.exists():
        raise RuntimeError(f"output already exists: {output_save}")

    header, frame, frame_offset = split_save(input_save)
    raw = bytearray(Zstd().decompress(frame))
    stations = read_stations_from_raw(bytes(raw))

    by_id = {s.id: s for s in stations}
    by_name: dict[str, list[StationRecord]] = {}
    for s in stations:
        by_name.setdefault(s.name, []).append(s)

    resolved: list[tuple[StationRecord, float, float]] = []
    errors: list[str] = []
    for key, (lon, lat) in updates.items():
        target = None
        if key in by_id:
            target = by_id[key]
        else:
            matches = by_name.get(key, [])
            if len(matches) == 1:
                target = matches[0]
            elif len(matches) == 0:
                errors.append(f"未找到车站: {key}")
                continue
            else:
                errors.append(f"车站名不唯一（{len(matches)} 个同名），请用 id: {key}")
                continue
        try:
            x, y = lonlat_to_mercator(lon, lat)
        except ValueError as exc:
            errors.append(f"{key}: {exc}")
            continue
        resolved.append((target, x, y))

    if errors:
        raise RuntimeError("坐标写入被拒绝：" + "；".join(errors))
    if not resolved:
        raise RuntimeError("没有可写入的坐标更新")

    changes = []
    for st, x, y in resolved:
        off = st.coord_off
        old = bytes(raw[off:off + 16])
        new = struct.pack("<dd", x, y)
        raw[off:off + 16] = new
        changes.append(
            {
                "id": st.id,
                "name": st.name,
                "coord_off": off,
                "old_hex": old.hex(),
                "new_hex": new.hex(),
                "old_lonlat": [st.lon, st.lat],
                "new_lonlat": list(mercator_to_lonlat(x, y)),
            }
        )

    raw_after = bytes(raw)
    output = header + Zstd().compress(raw_after, level)
    readback = Zstd().decompress(output[frame_offset:])
    if readback != raw_after:
        raise RuntimeError("压缩输出未通过反向解压校验")

    output_save.parent.mkdir(parents=True, exist_ok=True)
    partial = output_save.with_name(output_save.name + ".partial")
    if partial.exists():
        raise RuntimeError(f"发现残留临时文件: {partial}")
    partial.write_bytes(output)
    partial.replace(output_save)

    return {
        "input_save": str(input_save),
        "output_save": str(output_save),
        "changed_count": len(changes),
        "changes": changes,
        "output_file_size": len(output),
        "reverse_decompress_verified": True,
    }


# ---------------------------------------------------------------------------
# Station names (JSON-free binary write)
# ---------------------------------------------------------------------------
#
# A station record stores its name right after the two f64 coordinates::
#
#     … [f64 x][f64 y] <namelen uvarint> <utf8 name> <flag> <b1> <b2> <plat_count> …
#
# ``flag`` is ``0x00`` when the player gave the station a custom name and
# ``0x01`` when it inherits the auto/mod label (shown in game as an id number).
# Renaming a station is therefore a variable-length rewrite of exactly
# ``<namelen><name><flag>``: write the UTF-8 name and force ``flag = 0x00``.
# Everything after the flag byte (b1/b2/platform tracks) is left byte-identical,
# so the platform layout is never disturbed. Ground-truth verified: rebuilding
# every station's original slot reproduces the input stream byte for byte.
_MAX_NAME_BYTES = 200


def _name_slot(raw: bytes, coord_off: int):
    """Return ``(namelen, name_bytes, flag, span_off, span_end)`` for a station.

    ``span`` = ``[span_off, span_end)`` covers ``<namelen uvarint><name><flag>``.
    Returns ``None`` if the slot does not parse (unexpected flag, truncation…).
    """
    span_off = coord_off + 16
    r = _try_uvarint(raw, span_off)
    if not r:
        return None
    namelen, after = r
    if not (0 <= namelen <= _MAX_NAME_BYTES) or after + namelen + 1 > len(raw):
        return None
    name_bytes = raw[after:after + namelen]
    flag = raw[after + namelen]
    if flag not in (0x00, 0x01):
        return None
    return namelen, name_bytes, flag, span_off, after + namelen + 1


def _apply_spans(raw: bytes, edits: list[tuple[int, int, bytes]]) -> bytes:
    """Rebuild ``raw`` replacing non-overlapping ``(offset, old_len, new)`` spans."""
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


def set_station_names(
    input_save: Path,
    output_save: Path,
    names: dict[str, str],
    only_unnamed: bool = True,
    level: int = 3,
) -> dict:
    """Write real station names into a NEW save (JSON-free binary edit).

    ``names`` maps station id (hex) or current name -> new display name.
    ``only_unnamed`` skips stations that already carry a custom name (flag 0).
    Never touches the input save; verifies via reverse decompression.
    """
    input_save = Path(input_save)
    output_save = Path(output_save)
    if input_save.resolve() == output_save.resolve():
        raise RuntimeError("refusing to overwrite the input save")
    if output_save.exists():
        raise RuntimeError(f"output already exists: {output_save}")

    header, frame, frame_offset = split_save(input_save)
    raw = Zstd().decompress(frame)
    stations = read_stations_from_raw(raw)
    by_id = {s.id: s for s in stations}
    by_name: dict[str, list[StationRecord]] = {}
    for s in stations:
        by_name.setdefault(s.name, []).append(s)

    edits: list[tuple[int, int, bytes]] = []
    changes: list[dict] = []
    skipped: list[dict] = []
    errors: list[str] = []
    seen_offsets: set[int] = set()

    for key, new_name in names.items():
        target = by_id.get(key)
        if target is None:
            matches = by_name.get(key, [])
            if len(matches) == 1:
                target = matches[0]
            elif not matches:
                continue  # id not present in this save; silently skip
            else:
                errors.append(f"车站名不唯一（{len(matches)} 个同名），请用 id: {key}")
                continue
        if target.coord_off in seen_offsets:
            continue
        slot = _name_slot(raw, target.coord_off)
        if slot is None:
            errors.append(f"无法定位站名槽位: {target.id}")
            continue
        namelen, name_bytes, flag, span_off, span_end = slot
        # Correctness gate: re-encoding the original slot must reproduce it.
        original = uvarint(namelen) + name_bytes + bytes([flag])
        if raw[span_off:span_end] != original:
            errors.append(f"站名槽位回环校验失败: {target.id}")
            continue
        if only_unnamed and flag == 0x00:
            skipped.append({"id": target.id, "reason": "already named",
                            "name": target.name})
            continue
        nb = new_name.encode("utf-8")
        if not (1 <= len(nb) <= _MAX_NAME_BYTES):
            errors.append(f"站名长度非法（1..{_MAX_NAME_BYTES} 字节）: {target.id}")
            continue
        if nb == name_bytes and flag == 0x00:
            skipped.append({"id": target.id, "reason": "unchanged",
                            "name": target.name})
            continue
        new_slot = uvarint(len(nb)) + nb + b"\x00"
        edits.append((span_off, span_end - span_off, new_slot))
        seen_offsets.add(target.coord_off)
        changes.append({
            "id": target.id,
            "old_name": target.name,
            "new_name": new_name,
            "was_unnamed": flag == 0x01,
        })

    if errors:
        raise RuntimeError("站名写入被拒绝：" + "；".join(errors))
    if not edits:
        raise RuntimeError("没有可写入的站名（可能都已命名或存档中不存在对应 id）")

    raw_after = _apply_spans(raw, edits)
    # Re-parse and confirm the intended names now read back from the new stream.
    reparsed = {s.id: s for s in read_stations_from_raw(raw_after)}
    for ch in changes:
        got = reparsed.get(ch["id"])
        if got is None or got.name != ch["new_name"]:
            raise RuntimeError(
                f"写入后复读校验失败: {ch['id']} 期望 {ch['new_name']!r} 实得 "
                f"{None if got is None else got.name!r}")

    output = header + Zstd().compress(raw_after, level)
    if Zstd().decompress(output[frame_offset:]) != raw_after:
        raise RuntimeError("压缩输出未通过反向解压校验")

    output_save.parent.mkdir(parents=True, exist_ok=True)
    partial = output_save.with_name(output_save.name + ".partial")
    if partial.exists():
        raise RuntimeError(f"发现残留临时文件: {partial}")
    partial.write_bytes(output)
    partial.replace(output_save)

    return {
        "input_save": str(input_save),
        "output_save": str(output_save),
        "changed_count": len(changes),
        "skipped_count": len(skipped),
        "changes": changes,
        "skipped": skipped[:50],
        "output_file_size": len(output),
        "size_delta": len(raw_after) - len(raw),
        "reverse_decompress_verified": True,
    }


_STATION_RE = re.compile(
    r'"class"\s*:\s*"Station"\s*,\s*"id"\s*:\s*"(0x[0-9a-fA-F]+)"\s*,\s*'
    r'"name"\s*:\s*("(?:[^"\\]|\\.)*")'
)


def station_names_from_export(export_path: Path) -> dict[str, str]:
    """Extract ``{station_id_hex: name}`` from a game Timetable Export JSON.

    Streams the (potentially huge) export line by line; no full JSON parse.
    """
    import json as _json

    out: dict[str, str] = {}
    with open(export_path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"class":"Station"' not in line and '"class" : "Station"' not in line:
                continue
            for m in _STATION_RE.finditer(line):
                sid = m.group(1)
                try:
                    name = _json.loads(m.group(2))
                except ValueError:
                    continue
                if name:
                    out[sid] = name
    return out


def _cli(argv: list[str]) -> int:
    import argparse
    import json
    import sys

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(
        description="直接读取/编辑 NIMBY Rails 存档中的车站坐标（JSON-free，就地覆盖）"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="列出存档中的所有车站（id / 名称 / 经纬度）")
    p_list.add_argument("save", type=Path)
    p_list.add_argument("--json", action="store_true", help="以 JSON 输出")

    p_set = sub.add_parser("set", help="把车站改写为真实经纬度，写入新存档")
    p_set.add_argument("input", type=Path)
    p_set.add_argument("output", type=Path)
    p_set.add_argument(
        "updates",
        nargs="+",
        help='形如 "站名=lon,lat" 或 "0x2000000000001=lon,lat"',
    )
    p_set.add_argument("--level", type=int, default=3, help="zstd 压缩级别（默认 3）")

    p_name = sub.add_parser(
        "set-names",
        help="把真实站名写入新存档（游戏内显示名称而非编号）",
    )
    p_name.add_argument("input", type=Path)
    p_name.add_argument("output", type=Path)
    p_name.add_argument(
        "--from-export", type=Path,
        help="从游戏导出的 Timetable Export JSON 读取每个车站的真实名称",
    )
    p_name.add_argument(
        "pairs", nargs="*",
        help='额外/覆盖用的名称，形如 "0x2000000370001=Barrie South"',
    )
    p_name.add_argument(
        "--all", action="store_true",
        help="连已命名的车站一起覆盖（默认只补写未命名/编号车站）",
    )
    p_name.add_argument("--level", type=int, default=3, help="zstd 压缩级别（默认 3）")

    args = parser.parse_args(argv)

    if args.cmd == "set-names":
        names: dict[str, str] = {}
        if args.from_export:
            names.update(station_names_from_export(args.from_export))
        for item in args.pairs:
            if "=" not in item:
                parser.error(f'名称项格式错误（缺少 =）：{item}')
            key, val = item.split("=", 1)
            names[key.strip()] = val
        if not names:
            parser.error("没有提供任何站名来源（--from-export 或 id=名称）")
        manifest = set_station_names(
            args.input, args.output, names,
            only_unnamed=not args.all, level=args.level,
        )
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "list":
        stations = read_stations(args.save)
        if args.json:
            print(json.dumps(
                [{"id": s.id, "name": s.name, "lon": s.lon, "lat": s.lat} for s in stations],
                ensure_ascii=False, indent=2,
            ))
        else:
            print(f"共 {len(stations)} 个车站：")
            for s in stations:
                print(f"  {s.id:<18} {s.name:<32} {s.lon:.6f}, {s.lat:.6f}")
        return 0

    if args.cmd == "set":
        updates: dict[str, tuple[float, float]] = {}
        for item in args.updates:
            if "=" not in item:
                parser.error(f'更新项格式错误（缺少 =）：{item}')
            key, coords = item.split("=", 1)
            try:
                lon_s, lat_s = coords.split(",")
                updates[key.strip()] = (float(lon_s), float(lat_s))
            except ValueError:
                parser.error(f'坐标格式错误（应为 lon,lat）：{item}')
        manifest = set_station_coordinates(args.input, args.output, updates, level=args.level)
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    import sys as _sys

    raise SystemExit(_cli(_sys.argv[1:]))
