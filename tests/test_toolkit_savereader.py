"""Unit tests for the JSON-free network reader (stations/lines/signals)."""
from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import toolkit_coordedit as ce  # noqa: E402
import toolkit_savereader as sr  # noqa: E402
from toolkit_binary import Zstd, uvarint, ZSTD_MAGIC  # noqa: E402


def _id_varint(type_nibble: int, seq: int) -> bytes:
    return uvarint(((type_nibble << 48) | seq) * 2)


def _station_bytes(seq: int, lon: float, lat: float, name: str) -> bytes:
    x, y = ce.lonlat_to_mercator(lon, lat)
    return (_id_varint(sr.TYPE_STATION, seq) + b"\x84\xc0\x02\x01"
            + struct.pack("<dd", x, y) + uvarint(len(name.encode()))
            + name.encode() + b"\x00\x00\x00")


def _line_bytes(seq: int, name: str, code: str, color: int, station_seqs: list[int]) -> bytes:
    body = _id_varint(sr.TYPE_SCHEDULE, seq)
    body += uvarint(len(name.encode())) + name.encode()
    body += uvarint(len(code.encode())) + code.encode()
    body += b"\x00"                       # tag count 0
    body += uvarint(color)                # color uvarint
    body += uvarint(len(station_seqs))    # stop count
    for s in station_seqs:
        body += _id_varint(sr.TYPE_STATION, s)
    body += b"\x00" * 4
    return body


def _signal_bytes(seq: int, lon: float, lat: float) -> bytes:
    x, y = ce.lonlat_to_mercator(lon, lat)
    return _id_varint(sr.TYPE_SIGNAL, seq) + b"\x3a\x00\x00" + struct.pack("<dd", x, y)


def _make_save(tmp_path: Path, raw: bytes) -> Path:
    header = b"NMBY\x02\x00\x01\x00" + b"\x00" * 24
    assert ZSTD_MAGIC not in header
    save = tmp_path / "net.nimbyrails5"
    save.write_bytes(header + Zstd().compress(raw, 3))
    return save


def _make_raw() -> bytes:
    raw = b"\x11\x22\x33\x44" * 4
    raw += _station_bytes(0x1, -79.380311, 43.644512, "Union")
    raw += b"\x55" * 3
    raw += _station_bytes(0x20002, -79.418689, 43.636070, "Exhibition")
    raw += b"\x55" * 3
    raw += _station_bytes(0x30001, -79.496128, 43.617216, "Mimico")
    raw += b"\x66" * 5
    raw += _line_bytes(0x1, "Lakeshore West", "GO LW", 0xFF0000A9, [0x1, 0x20002, 0x30001])
    raw += b"\x77" * 5
    raw += _signal_bytes(0x1, -79.3801, 43.6446)
    raw += b"\x00" * 16
    return raw


def test_read_lines_stops_and_color(tmp_path):
    save = _make_save(tmp_path, _make_raw())
    lines = sr.read_lines_from_raw(Zstd().decompress(
        __import__("toolkit_binary").split_save(save)[1]))
    lake = next(ln for ln in lines if ln.name == "Lakeshore West")
    assert lake.code == "GO LW"
    assert lake.color == "0xff0000a9"
    expected = [hex((sr.TYPE_STATION << 48) | s) for s in (0x1, 0x20002, 0x30001)]
    assert lake.stops == expected


def test_read_signals(tmp_path):
    save = _make_save(tmp_path, _make_raw())
    raw = Zstd().decompress(__import__("toolkit_binary").split_save(save)[1])
    signals = sr.read_signals_from_raw(raw)
    assert len(signals) == 1
    s = signals[0]
    assert abs(s.lon - (-79.3801)) < 1e-4
    assert abs(s.lat - 43.6446) < 1e-4


def test_read_network(tmp_path):
    save = _make_save(tmp_path, _make_raw())
    net = sr.read_network(save)
    assert net["counts"]["stations"] == 3
    assert net["counts"]["lines"] == 1
    assert net["counts"]["signals"] == 1
    line = net["lines"][0]
    assert len(line["stops"]) == 3
    assert line["name"] == "Lakeshore West"
