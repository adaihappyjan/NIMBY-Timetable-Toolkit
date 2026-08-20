from __future__ import annotations

import ctypes
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable


TOOL_COPY_RE = re.compile(
    r"_(Toolkit|Extension|Recovery|Repair)_(\d{8}_\d{6})\.nimbyrails5$",
    re.IGNORECASE,
)
TOOL_PARTIAL_RE = re.compile(
    r"_(Toolkit|Extension|Recovery|Repair)_(\d{8}_\d{6})\.nimbyrails5\.partial$",
    re.IGNORECASE,
)


def _utc_timestamp(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


def _manifest_for(save_path: Path) -> Path:
    return save_path.with_suffix(".manifest.json")


def cleanup_preview(
    directory: Path,
    *,
    days: int = 14,
    keep: int = 5,
    compact: bool = False,
    now: datetime | None = None,
) -> dict:
    """Return exact recoverable cleanup targets without changing the filesystem.

    Normal automatic cleanup keeps the newest ``keep`` completed copies and only
    retires older excess copies.  Compact mode is an explicit user action and
    retires every excess copy regardless of age.  Interrupted ``.partial`` files
    older than one hour are always eligible because they cannot be loaded by the
    game.
    """

    directory = directory.resolve()
    days = max(1, min(3650, int(days)))
    keep = max(1, min(100, int(keep)))
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    partial_cutoff = now - timedelta(hours=1)

    completed = sorted(
        (
            path
            for path in directory.iterdir()
            if path.is_file() and TOOL_COPY_RE.search(path.name)
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    partials = sorted(
        (
            path
            for path in directory.iterdir()
            if path.is_file() and TOOL_PARTIAL_RE.search(path.name)
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    targets: list[dict] = []
    protected = completed[:keep]
    excess = completed[keep:]
    skipped_young = 0
    for save_path in excess:
        modified = datetime.fromtimestamp(save_path.stat().st_mtime, timezone.utc)
        if not compact and modified >= cutoff:
            skipped_young += 1
            continue
        companion = _manifest_for(save_path)
        paths = [save_path]
        if companion.exists() and companion.is_file():
            paths.append(companion)
        targets.append(
            {
                "kind": "completed-copy",
                "name": save_path.name,
                "path": str(save_path),
                "paths": [str(path) for path in paths],
                "modified_utc": _utc_timestamp(save_path),
                "bytes": sum(path.stat().st_size for path in paths),
                "reason": (
                    f"超出保留的最新 {keep} 份"
                    if compact
                    else f"超出保留的最新 {keep} 份，且已超过 {days} 天"
                ),
            }
        )

    stale_partials = 0
    for partial in partials:
        modified = datetime.fromtimestamp(partial.stat().st_mtime, timezone.utc)
        if modified >= partial_cutoff:
            continue
        stale_partials += 1
        targets.append(
            {
                "kind": "interrupted-partial",
                "name": partial.name,
                "path": str(partial),
                "paths": [str(partial)],
                "modified_utc": _utc_timestamp(partial),
                "bytes": partial.stat().st_size,
                "reason": "未完成的临时文件，且已超过 1 小时",
            }
        )

    return {
        "directory": str(directory),
        "days": days,
        "keep": keep,
        "mode": "compact" if compact else "automatic",
        "completed_copy_count": len(completed),
        "protected_copy_count": len(protected),
        "excess_copy_count": len(excess),
        "skipped_young_count": skipped_young,
        "partial_count": len(partials),
        "stale_partial_count": stale_partials,
        "candidate_count": len(targets),
        "candidate_file_count": sum(len(item["paths"]) for item in targets),
        "candidate_bytes": sum(item["bytes"] for item in targets),
        "targets": targets,
    }


def _validate_targets(directory: Path, paths: Iterable[str]) -> list[Path]:
    directory = directory.resolve()
    validated: list[Path] = []
    for value in paths:
        path = Path(value).resolve()
        if path.parent != directory:
            raise RuntimeError(f"清理目标不在存档目录中：{path}")
        if not (
            TOOL_COPY_RE.search(path.name)
            or TOOL_PARTIAL_RE.search(path.name)
            or path.name.lower().endswith(".manifest.json")
        ):
            raise RuntimeError(f"拒绝清理无法识别的文件：{path.name}")
        if path.exists() and path.is_file():
            validated.append(path)
    return validated


def _recycle_windows(paths: list[Path]) -> None:
    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", ctypes.c_void_p),
            ("wFunc", ctypes.c_uint),
            ("pFrom", ctypes.c_wchar_p),
            ("pTo", ctypes.c_wchar_p),
            ("fFlags", ctypes.c_ushort),
            ("fAnyOperationsAborted", ctypes.c_int),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", ctypes.c_wchar_p),
        ]

    if not paths:
        return
    source = "\0".join(str(path) for path in paths) + "\0\0"
    operation = SHFILEOPSTRUCTW()
    operation.wFunc = 3  # FO_DELETE
    operation.pFrom = source
    operation.fFlags = 0x0040 | 0x0010 | 0x0004  # undo, no confirmation, silent
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
    if result != 0 or operation.fAnyOperationsAborted:
        raise RuntimeError(f"移入回收站失败（Windows 错误 {result}）")


def execute_cleanup(directory: Path, preview: dict) -> dict:
    requested = [path for item in preview.get("targets", []) for path in item["paths"]]
    paths = _validate_targets(directory, requested)
    bytes_before = sum(path.stat().st_size for path in paths)
    _recycle_windows(paths)
    remaining = [str(path) for path in paths if path.exists()]
    if remaining:
        raise RuntimeError("以下文件未能移入回收站：" + "、".join(remaining))
    return {
        "moved_file_count": len(paths),
        "moved_group_count": len(preview.get("targets", [])),
        "reclaimed_bytes": bytes_before,
        "recoverable": True,
    }
