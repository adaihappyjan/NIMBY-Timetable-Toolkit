from __future__ import annotations

import ctypes
import ctypes.util
import os
import sys
from dataclasses import dataclass
from pathlib import Path


ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
ZSTD_CONTENTSIZE_UNKNOWN = (1 << 64) - 1
ZSTD_CONTENTSIZE_ERROR = (1 << 64) - 2
GARAGE_JOIN_VECTOR = bytes.fromhex(
    "01"
    "8280808080808007"
    "dedceebcf08cfdee5b00008fd2e2ee97b1b4907d"
)
EMPTY_SCHEDULE_ZERO_TAIL = b"\x00" * 43


def find_zstd_library() -> str:
    # An explicit override always wins, so users can point at any copy of the DLL.
    override = os.environ.get("NIMBY_LIBZSTD")
    if override and Path(override).is_file():
        return override

    candidates: list[Path] = []
    if os.name == "nt":
        here = Path(__file__).resolve().parent
        user_profile = Path(os.environ.get("USERPROFILE", str(Path.home())))
        program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        program_files_x86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        candidates = [
            # Every official Windows portable release ships this verified AMD64 DLL.
            here / "libzstd.dll",
            Path(sys.executable).resolve().parent / "libzstd.dll",
            user_profile
            / ".cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/mingw64/bin/libzstd.dll",
            Path(sys.executable).resolve().parents[1] / "native/git/mingw64/bin/libzstd.dll",
            program_files / "Git/mingw64/bin/libzstd.dll",
            program_files / "Git/usr/bin/libzstd.dll",
            program_files_x86 / "Git/mingw64/bin/libzstd.dll",
            program_files_x86 / "Git/usr/bin/libzstd.dll",
        ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    discovered = ctypes.util.find_library("zstd") or ctypes.util.find_library("libzstd")
    if discovered:
        return discovered
    if os.name == "nt":
        raise RuntimeError(
            "未找到 libzstd.dll。官方便携包应当自带此文件；请重新下载完整 ZIP、完整解压，"
            "并保持 libzstd.dll 与 toolkit_binary.py 在同一目录。高级用户也可设置 "
            "NIMBY_LIBZSTD 指向兼容的 64 位运行库。"
        )
    raise RuntimeError(
        "未找到系统 zstd 共享库。请通过系统包管理器安装 libzstd，或设置环境变量 "
        "NIMBY_LIBZSTD 指向兼容的共享库。"
    )


class Zstd:
    def __init__(self, dll_path: str | Path | None = None) -> None:
        selected = str(dll_path or find_zstd_library())
        try:
            self.lib = ctypes.CDLL(selected)
        except OSError as exc:
            hint = (
                "请确认正在使用 64 位 Python，并重新下载、完整解压官方便携包。"
                if os.name == "nt"
                else "请安装与当前系统架构匹配的 libzstd。"
            )
            raise RuntimeError(f"无法加载 zstd 运行库 {selected}。{hint}") from exc
        self.lib.ZSTD_getFrameContentSize.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        self.lib.ZSTD_getFrameContentSize.restype = ctypes.c_ulonglong
        self.lib.ZSTD_decompress.argtypes = [
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_void_p,
            ctypes.c_size_t,
        ]
        self.lib.ZSTD_decompress.restype = ctypes.c_size_t
        self.lib.ZSTD_compressBound.argtypes = [ctypes.c_size_t]
        self.lib.ZSTD_compressBound.restype = ctypes.c_size_t
        self.lib.ZSTD_compress.argtypes = [
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_int,
        ]
        self.lib.ZSTD_compress.restype = ctypes.c_size_t
        self.lib.ZSTD_isError.argtypes = [ctypes.c_size_t]
        self.lib.ZSTD_isError.restype = ctypes.c_uint
        self.lib.ZSTD_getErrorName.argtypes = [ctypes.c_size_t]
        self.lib.ZSTD_getErrorName.restype = ctypes.c_char_p

    def _check(self, code: int) -> int:
        if self.lib.ZSTD_isError(code):
            name = self.lib.ZSTD_getErrorName(code).decode("utf-8", "replace")
            raise RuntimeError(f"zstd error: {name}")
        return code

    def decompress(self, frame: bytes) -> bytes:
        source = ctypes.create_string_buffer(frame)
        size = int(self.lib.ZSTD_getFrameContentSize(source, len(frame)))
        if size in (ZSTD_CONTENTSIZE_UNKNOWN, ZSTD_CONTENTSIZE_ERROR):
            raise RuntimeError(f"zstd frame content size unavailable: {size}")
        target = ctypes.create_string_buffer(size)
        actual = self._check(
            self.lib.ZSTD_decompress(target, size, source, len(frame))
        )
        return target.raw[:actual]

    def compress(self, data: bytes, level: int = 3) -> bytes:
        source = ctypes.create_string_buffer(data)
        capacity = int(self.lib.ZSTD_compressBound(len(data)))
        target = ctypes.create_string_buffer(capacity)
        actual = self._check(
            self.lib.ZSTD_compress(target, capacity, source, len(data), level)
        )
        return target.raw[:actual]


def split_save(path: Path) -> tuple[bytes, bytes, int]:
    data = path.read_bytes()
    offset = data.find(ZSTD_MAGIC)
    if offset < 0:
        raise RuntimeError("zstd frame magic not found")
    return data[:offset], data[offset:], offset


def uvarint(value: int) -> bytes:
    if value < 0:
        raise ValueError("uvarint cannot encode a negative value")
    out = bytearray()
    while value >= 0x80:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def read_uvarint(raw: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        byte = raw[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7


def encoded_id(value: str) -> bytes:
    return uvarint(int(value, 16) * 2)


@dataclass(frozen=True)
class ScheduleLayout:
    name_pos: int
    vector_start: int
    order_pos: int
    after_order: int
    after_assignments: int
    assignment_counts: list[int]
    record_order: list[str]
    records: dict[str, bytes]


def ordered_shift_block(schedule: dict, shift_ids: list[str] | None = None) -> bytes:
    ids = shift_ids
    if ids is None:
        ids = [shift["id"] for shift in schedule.get("shifts") or []]
    return uvarint(len(ids)) + b"".join(encoded_id(value) for value in ids)


def parse_assignment_blocks(raw: bytes, offset: int) -> tuple[list[int], int]:
    counts: list[int] = []
    cursor = offset
    for item_width in (1, 1, 2, 2):
        count, cursor = read_uvarint(raw, cursor)
        if count > 100_000:
            raise RuntimeError(f"unreasonable assignment count: {count}")
        counts.append(count)
        for _ in range(count * item_width):
            _, cursor = read_uvarint(raw, cursor)
    return counts, cursor


def locate_schedule_record(raw: bytes, schedule: dict) -> tuple[int, int]:
    expected_id = int(schedule["id"], 16) * 2
    records: list[tuple[int, int]] = []
    for name_variant in {schedule["name"], schedule["name"].strip()}:
        name_bytes = name_variant.encode("utf-8")
        cursor = 0
        while True:
            found = raw.find(name_bytes, cursor)
            if found < 0:
                break
            for record_start in range(max(0, found - 32), found):
                try:
                    encoded_schedule_id, after_id = read_uvarint(raw, record_start)
                    _, after_meta = read_uvarint(raw, after_id)
                    name_len, after_len = read_uvarint(raw, after_meta)
                except IndexError:
                    continue
                if (
                    encoded_schedule_id == expected_id
                    and name_len == len(name_bytes)
                    and after_len == found
                ):
                    records.append((record_start, found))
                    break
            cursor = found + 1
    records = sorted(set(records))
    if len(records) != 1:
        raise RuntimeError(
            f"expected one ID-validated schedule record for {schedule['name']}, "
            f"found {len(records)}"
        )
    return records[0]


def locate_schedule_name(raw: bytes, schedule: dict) -> int:
    return locate_schedule_record(raw, schedule)[1]


def validate_empty_schedule_record(
    raw: bytes,
    schedule: dict,
    record_end: int | None = None,
) -> int:
    """Validate an exported empty schedule without trusting the next record boundary.

    The schedule collection can be followed by objects which are not present as named
    records in the timetable export (notably Motion records).  Consequently, the last
    schedule cannot be validated by checking the end of the next known schedule/train
    range.  Empty schedules have a stable run of at least 43 zero bytes at the end of
    their compact record.  Older records use exactly 43 zero bytes preceded by a ``4``
    field value, while newer records can use a longer zero run (48 bytes has been
    observed when code/meta fields are present).  Find that run close to the
    ID-validated name instead.
    """
    record_start, name_pos = locate_schedule_record(raw, schedule)
    name_end = name_pos + len(schedule["name"].encode("utf-8"))
    search_end = min(len(raw), record_end or len(raw), record_start + 512)
    if search_end <= name_end:
        raise RuntimeError(f"empty schedule record is truncated: {schedule['name']}")
    tail_pos = raw.find(EMPTY_SCHEDULE_ZERO_TAIL, name_end, search_end)
    if tail_pos < 0:
        raise RuntimeError(
            f"empty schedule field tail not found near record: {schedule['name']}"
        )
    logical_end = tail_pos + len(EMPTY_SCHEDULE_ZERO_TAIL)
    while logical_end < search_end and raw[logical_end] == 0:
        logical_end += 1
    if logical_end - record_start > 512:
        raise RuntimeError(f"empty schedule record is unreasonably large: {schedule['name']}")
    return logical_end


def locate_schedule(
    raw: bytes,
    schedule: dict,
    record_end: int | None = None,
) -> tuple[int, int, int]:
    name_pos = locate_schedule_name(raw, schedule)
    order_block = ordered_shift_block(schedule)
    expected_assignments = len(schedule.get("trains") or {})
    candidates: list[int] = []
    cursor = name_pos
    search_end = min(len(raw), record_end or (name_pos + 8_000_000))
    while True:
        found = raw.find(order_block, cursor, search_end)
        if found < 0:
            break
        try:
            counts, _ = parse_assignment_blocks(raw, found + len(order_block))
        except (IndexError, RuntimeError):
            counts = []
        if counts == [expected_assignments] * 4:
            candidates.append(found)
        cursor = found + 1
    if len(candidates) != 1:
        raise RuntimeError(
            f"expected one validated ordered shift block for {schedule['name']}, "
            f"found {len(candidates)}"
        )
    order_pos = candidates[0]
    return name_pos, order_pos, order_pos + len(order_block)


def find_shift_record_starts(
    raw: bytes,
    schedule: dict,
    name_pos: int,
    order_pos: int,
) -> dict[str, int]:
    starts: dict[str, int] = {}
    for shift in schedule.get("shifts") or []:
        shift_id = shift["id"]
        marker = encoded_id(shift_id) * 2 + b"\x00"
        positions: list[int] = []
        cursor = name_pos
        while True:
            found = raw.find(marker, cursor, order_pos)
            if found < 0:
                break
            positions.append(found)
            cursor = found + 1
        if len(positions) != 1:
            raise RuntimeError(
                f"expected one shift record for {schedule['name']} {shift_id}, "
                f"found {len(positions)}"
            )
        starts[shift_id] = positions[0]
    return starts


def schedule_layout(
    raw: bytes,
    schedule: dict,
    record_end: int | None = None,
) -> ScheduleLayout:
    shifts = schedule.get("shifts") or []
    if not shifts:
        raise RuntimeError(f"schedule has no shifts: {schedule['name']}")
    name_pos, order_pos, after_order = locate_schedule(raw, schedule, record_end)
    assignment_counts, after_assignments = parse_assignment_blocks(raw, after_order)
    starts = find_shift_record_starts(raw, schedule, name_pos, order_pos)
    sorted_starts = sorted(starts.values())
    vector_count = uvarint(len(shifts))
    vector_start = sorted_starts[0] - len(vector_count)
    if raw[vector_start : sorted_starts[0]] != vector_count:
        raise RuntimeError(f"shift vector count not found: {schedule['name']}")
    id_by_start = {position: shift_id for shift_id, position in starts.items()}
    records: dict[str, bytes] = {}
    record_order: list[str] = []
    for index, start in enumerate(sorted_starts):
        end = sorted_starts[index + 1] if index + 1 < len(sorted_starts) else order_pos
        shift_id = id_by_start[start]
        record_order.append(shift_id)
        records[shift_id] = raw[start:end]
    return ScheduleLayout(
        name_pos=name_pos,
        vector_start=vector_start,
        order_pos=order_pos,
        after_order=after_order,
        after_assignments=after_assignments,
        assignment_counts=assignment_counts,
        record_order=record_order,
        records=records,
    )


def assignment_bytes(train_ids: list[str], shift_ids: list[str]) -> bytes:
    if len(train_ids) != len(shift_ids):
        raise RuntimeError("train and shift counts differ")
    count = uvarint(len(train_ids))
    train_values = b"".join(encoded_id(value) for value in train_ids)
    forward = b"".join(
        encoded_id(train_id) + encoded_id(shift_id)
        for train_id, shift_id in zip(train_ids, shift_ids)
    )
    reverse = b"".join(
        encoded_id(shift_id) + encoded_id(train_id)
        for train_id, shift_id in zip(train_ids, shift_ids)
    )
    return count + train_values + count + train_values + count + forward + count + reverse


def shift_group_span(record: bytes, shift_id: str) -> tuple[int, int, bytes]:
    cursor = len(encoded_id(shift_id)) * 2
    tag_count, cursor = read_uvarint(record, cursor)
    if tag_count != 0:
        raise RuntimeError(f"shift {shift_id} unexpectedly has tags")
    name_len, cursor = read_uvarint(record, cursor)
    cursor += name_len
    if record[cursor : cursor + 3] != b"\x01\x00\x01":
        raise RuntimeError(f"unexpected shift metadata for {shift_id}")
    cursor += 3
    inner_a, cursor = read_uvarint(record, cursor)
    inner_b, cursor = read_uvarint(record, cursor)
    if inner_a != inner_b:
        raise RuntimeError(f"shift inner IDs differ for {shift_id}")
    group_start = cursor
    _, group_end = read_uvarint(record, cursor)
    return group_start, group_end, record[group_start:group_end]


def repeat_field_position(
    raw: bytes,
    line_id: str,
    start: int,
    end: int,
    label: str,
) -> int:
    line_marker = encoded_id(line_id)
    candidates: list[int] = []
    for current_repeat in (0, 2):
        marker = line_marker + bytes((current_repeat, 1, 2))
        cursor = start
        while True:
            found = raw.find(marker, cursor, end)
            if found < 0:
                break
            candidates.append(found + len(line_marker))
            cursor = found + 1
    candidates = sorted(set(candidates))
    if len(candidates) != 1:
        raise RuntimeError(f"expected one repeat field for {label}, found {len(candidates)}")
    return candidates[0]


def locate_train_record(raw: bytes, train: dict) -> int:
    marker = encoded_id(train["id"])
    name = train["name"].encode("utf-8")
    candidates: list[int] = []
    cursor = 0
    while True:
        found = raw.find(marker, cursor)
        if found < 0:
            break
        probe = found + len(marker)
        try:
            _, probe = read_uvarint(raw, probe)
            name_len, probe = read_uvarint(raw, probe)
        except IndexError:
            break
        if name_len == len(name) and raw[probe : probe + name_len] == name:
            candidates.append(found)
        cursor = found + 1
    if len(candidates) != 1:
        raise RuntimeError(
            f"expected one train record for {train['name']}, found {len(candidates)}"
        )
    return candidates[0]
