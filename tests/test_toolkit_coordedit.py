"""Unit tests for the JSON-free station reader + in-place coordinate editor."""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import toolkit_coordedit as ce  # noqa: E402
from toolkit_binary import Zstd, uvarint, ZSTD_MAGIC  # noqa: E402


def _station_bytes(station_id: int, lon: float, lat: float, name: str) -> bytes:
    """Build one Station record: [id][fields][f64 x][f64 y][namelen][name]."""
    x, y = ce.lonlat_to_mercator(lon, lat)
    idv = uvarint(station_id * 2)
    fields = b"\x84\xc0\x02\x01"  # small field block seen in real saves
    coords = struct.pack("<dd", x, y)
    nb = name.encode("utf-8")
    return idv + fields + coords + uvarint(len(nb)) + nb + b"\x00\x00\x00"


def _make_raw() -> bytes:
    body = b"\x11\x22\x33\x44" * 8  # some leading noise
    body += _station_bytes(0x2000000000001, -79.380311, 43.644512, "Toronto Union Station")
    body += b"\x55\x66" * 4
    body += _station_bytes(0x2000000010001, -79.449788, 43.656880, "Bloor GO")
    body += b"\x00" * 16
    return body


def _make_save(tmp_path: Path, raw: bytes) -> Path:
    # header must not itself contain the zstd magic before the frame
    header = b"NMBY\x02\x00\x01\x00" + b"\x00" * 24
    assert ZSTD_MAGIC not in header
    save = tmp_path / "synthetic.nimbyrails5"
    save.write_bytes(header + Zstd().compress(raw, 3))
    return save


def test_lonlat_mercator_roundtrip():
    for lon, lat in [(-79.38, 43.64), (0.0, 0.0), (139.69, 35.68), (-0.12, 51.5)]:
        x, y = ce.lonlat_to_mercator(lon, lat)
        rlon, rlat = ce.mercator_to_lonlat(x, y)
        assert abs(rlon - lon) < 1e-9
        assert abs(rlat - lat) < 1e-9


def test_lonlat_range_guard():
    with pytest.raises(ValueError):
        ce.lonlat_to_mercator(200.0, 0.0)
    with pytest.raises(ValueError):
        ce.lonlat_to_mercator(0.0, 89.0)


def test_read_stations(tmp_path):
    save = _make_save(tmp_path, _make_raw())
    stations = ce.read_stations(save)
    names = {s.name for s in stations}
    assert "Toronto Union Station" in names
    assert "Bloor GO" in names
    toronto = next(s for s in stations if s.name == "Toronto Union Station")
    assert abs(toronto.lon - (-79.380311)) < 1e-5
    assert abs(toronto.lat - 43.644512) < 1e-5
    assert toronto.id == hex(0x2000000000001)


def test_set_coordinates_only_touches_target(tmp_path):
    save = _make_save(tmp_path, _make_raw())
    out = tmp_path / "edited.nimbyrails5"
    new_lon, new_lat = -73.567256, 45.501689
    manifest = ce.set_station_coordinates(save, out, {"Bloor GO": (new_lon, new_lat)})
    assert manifest["changed_count"] == 1
    assert manifest["reverse_decompress_verified"] is True

    from toolkit_binary import split_save
    raw0 = Zstd().decompress(split_save(save)[1])
    raw1 = Zstd().decompress(split_save(out)[1])
    assert len(raw0) == len(raw1)
    diffs = [i for i in range(len(raw0)) if raw0[i] != raw1[i]]
    target = next(s for s in ce.read_stations(save) if s.name == "Bloor GO")
    assert diffs, "expected some bytes to change"
    assert min(diffs) >= target.coord_off
    assert max(diffs) < target.coord_off + 16

    edited = {s.name: s for s in ce.read_stations(out)}
    assert abs(edited["Bloor GO"].lon - new_lon) < 1e-6
    assert abs(edited["Bloor GO"].lat - new_lat) < 1e-6
    # other station intact
    assert abs(edited["Toronto Union Station"].lon - (-79.380311)) < 1e-5


def test_refuses_unknown_station(tmp_path):
    save = _make_save(tmp_path, _make_raw())
    out = tmp_path / "edited2.nimbyrails5"
    with pytest.raises(RuntimeError):
        ce.set_station_coordinates(save, out, {"Nonexistent Station": (0.0, 0.0)})
    assert not out.exists()


def test_refuses_overwrite_input(tmp_path):
    save = _make_save(tmp_path, _make_raw())
    with pytest.raises(RuntimeError):
        ce.set_station_coordinates(save, save, {"Bloor GO": (0.0, 0.0)})
