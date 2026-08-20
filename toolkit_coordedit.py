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
import struct
from dataclasses import dataclass
from pathlib import Path

from toolkit_binary import Zstd, split_save, read_uvarint

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
    """Enumerate every station definition (id + name + coords) in the payload."""
    out: dict[int, StationRecord] = {}
    n = len(raw)
    i = 0
    while i < n - 34:
        if raw[i + 7] in _HI and raw[i + 15] in _HI:
            x = struct.unpack_from("<d", raw, i)[0]
            y = struct.unpack_from("<d", raw, i + 8)[0]
            if -2.1e7 < x < 2.1e7 and 1.0e5 < y < 2.0e7 and abs(x) > 1.0e4:
                nm = _read_name(raw, i + 16)
                if nm:
                    name, _end = nm
                    lon, lat = mercator_to_lonlat(x, y)
                    if -180 <= lon <= 180 and -85 <= lat <= 85:
                        ident = _station_id_before(raw, i)
                        if ident is not None and ident not in out:
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

    args = parser.parse_args(argv)

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
