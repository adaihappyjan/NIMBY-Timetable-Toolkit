from __future__ import annotations

import ctypes
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable


TOOL_COPY_RE = re.compile(
    r"_(Toolkit|Extension|Recovery|Repair|Workspace|Autotrack|Names|StopTime|StopTimes|GarageJoin|Align)_(\d{8}_\d{6})\.nimbyrails5$",
    re.IGNORECASE,
)
TOOL_PARTIAL_RE = re.compile(
    r"_(Toolkit|Extension|Recovery|Repair|Workspace|Autotrack)_(\d{8}_\d{6})\.nimbyrails5\.partial$",
    re.IGNORECASE,
)


def _utc_timestamp(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


def _manifest_for(save_path: Path) -> Path:
    return save_path.with_suffix(".manifest.json")


def _recognized_copy(path: Path) -> bool:
    match = TOOL_COPY_RE.search(path.name)
    if not match:
        return False
    if path.is_symlink() or path.with_suffix('.keep').exists():
        return False
    # A player may load and subsequently save over an experimental copy. Never
    # auto-retire that newer work, nor a manually named lookalike without proof.
    try:
        manifest = json.loads(_manifest_for(path).read_text('utf-8'))
        if Path(manifest['output_save']).resolve() != path.resolve():
            return False
        hasher = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024*1024), b''):
                hasher.update(block)
        return hasher.hexdigest() == (manifest.get('output_sha256') or manifest.get('output_file_sha256'))
    except (OSError, ValueError, KeyError, TypeError):
        return False


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
            if path.is_file() and _recognized_copy(path)
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

    copies = [
        {'name': p.name, 'path': str(p), 'pinned': p.with_suffix('.keep').exists(),
         'eligible': p in completed}
        for p in directory.iterdir() if p.is_file() and TOOL_COPY_RE.search(p.name)
    ]
    token = hashlib.sha256(json.dumps([
        (str(p), p.stat().st_size, p.stat().st_mtime_ns)
        for item in targets for p in map(Path, item['paths'])
    ], sort_keys=True).encode()).hexdigest()
    return {
        "token": token,
        "copies": sorted(copies, key=lambda x: x['name']),
        "unverified_or_pinned_count": len(copies) - len(completed),
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
    # Do not act on an old preview if a player saved, pinned, or renamed a file.
    current = cleanup_preview(directory, days=preview['days'], keep=preview['keep'],
                              compact=preview.get('mode') == 'compact')
    if current['token'] != preview.get('token'):
        raise RuntimeError('清理列表已变化，未执行清理。请重新预览并确认。')
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


def set_copy_protection(directory: Path, name: str, protected: bool) -> None:
    directory = directory.resolve()
    path = (directory / name).resolve()
    if path.parent != directory or not TOOL_COPY_RE.search(path.name) or not path.is_file():
        raise RuntimeError('请选择当前存档目录中列出的工具副本。')
    marker = path.with_suffix('.keep')
    if protected:
        marker.write_text('NIMBY Toolkit: exclude this save from cleanup.\n', encoding='utf-8')
    elif marker.is_file():
        marker.unlink()
