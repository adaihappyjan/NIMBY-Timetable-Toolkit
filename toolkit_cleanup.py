from __future__ import annotations

import ctypes
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable


TOOL_COPY_RE = re.compile(
    r"_(Toolkit|Extension|Recovery|Repair|Workspace|Autotrack|Names|StopTime(?:s|\d+s)?|GarageJoin|Align)_(\d{8}_\d{6})\.nimbyrails5$",
    re.IGNORECASE,
)
TOOL_PARTIAL_RE = re.compile(
    r"_(Toolkit|Extension|Recovery|Repair|Workspace|Autotrack|Names|StopTime(?:s|\d+s)?|GarageJoin|Align)_(\d{8}_\d{6})\.nimbyrails5\.partial$",
    re.IGNORECASE,
)
TIMETABLE_RE = re.compile(r'^(.+) Timetable Export (\d{8}T\d{6}Z)\.json$', re.IGNORECASE)


def _file_digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            hasher.update(block)
    return hasher.hexdigest()


def _export_group(path: Path, *, timetable: bool, maps: bool):
    """Recognize formats for explicit manual review, not automatic deletion."""
    if path.is_symlink() or path.suffix.lower() != '.json' or path.stat().st_size > 50_000_000:
        return None
    match = TIMETABLE_RE.fullmatch(path.name) if timetable else None
    if not maps and not match: return None
    try:
        data = json.loads(path.read_text('utf-8-sig'))
        if match and isinstance(data, list) and all(isinstance(o, dict) for o in data):
            datetime.strptime(match[2], '%Y%m%dT%H%M%SZ')
            classes = {o.get('class') for o in data if isinstance(o.get('class'), str)}
            if {'Line', 'Schedule'} <= classes:
                return 'timetable-json', match[1].casefold(), '游戏时刻表导出 JSON'
        if maps and isinstance(data, dict) and data.get('schema') == 'nimby-toolkit-line-map.v1':
            lines = data.get('lines'); stations = data.get('stations')
            if isinstance(lines, list) and lines and isinstance(stations, dict):
                # Keep separate line selections/styles; don't retire an unrelated map.
                group = json.dumps({'lines': sorted((str(l['id']), str(l.get('name', ''))) for l in lines),
                                    'drawing': data.get('drawing', {})}, sort_keys=True, ensure_ascii=False)
                return 'map-json', group, '工具箱线路图 JSON'
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def _utc_timestamp(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


def _copy_project(path: Path) -> str:
    name = path.name
    while match := TOOL_COPY_RE.search(name):
        name = name[:match.start()]+'.nimbyrails5'
    return name.casefold()


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
    include_maps: bool = False,
    include_timetables: bool = False,
    export_directory: Path | None = None,
    protected_paths: Iterable[str] = (),
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
    protected_paths = sorted({str(Path(p).resolve()) for p in protected_paths if p})
    protected_set = set(protected_paths)

    completed = sorted(
        (
            path
            for path in directory.iterdir()
            if path.is_file() and _recognized_copy(path)
        ),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
        reverse=True,
    )
    partials = sorted(
        (
            path
            for path in directory.iterdir()
            if path.is_file() and not path.is_symlink() and TOOL_PARTIAL_RE.search(path.name)
            and not path.with_suffix('.keep').exists()
        ),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
        reverse=True,
    )

    targets: list[dict] = []
    copy_groups = defaultdict(list)
    for path in completed:
        copy_groups[_copy_project(path)].append(path)
    protected = [p for group in copy_groups.values() for p in group[:keep]]
    excess = [p for group in copy_groups.values() for p in group[keep:]]
    skipped_young = 0
    for save_path in excess:
        if str(save_path) in protected_set: continue
        modified = datetime.fromtimestamp(save_path.stat().st_mtime, timezone.utc)
        if not compact and modified >= cutoff:
            skipped_young += 1
            continue
        companion = _manifest_for(save_path)
        paths = [save_path]
        if companion.exists() and companion.is_file() and not companion.is_symlink():
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
        if str(partial) in protected_set: continue
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

    export_groups = defaultdict(list)
    roots = {directory}
    if export_directory is not None: roots.add(Path(export_directory).resolve())
    export_count = 0
    if include_maps or include_timetables:
        for root in sorted(roots):
            if not root.is_dir(): continue
            for path in root.iterdir():
                if not path.is_file(): continue
                info = _export_group(path, timetable=include_timetables and root == directory, maps=include_maps)
                if info:
                    kind, group, label = info
                    export_groups[(str(root), kind, group, label)].append(path)
                    export_count += 1
        for (_, kind, _, label), group in export_groups.items():
            group.sort(key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True)
            for path in group[keep:]:
                if str(path) in protected_set or path.with_suffix('.keep').exists(): continue
                if not compact and datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) >= cutoff: continue
                targets.append({'kind': kind, 'name': path.name, 'path': str(path), 'paths': [str(path)],
                                'modified_utc': _utc_timestamp(path), 'bytes': path.stat().st_size,
                                'reason': f'{label}：同项目/同线路选择保留最新 {keep} 份后的旧文件；'
                                          + ('不限天数，需人工确认' if compact else f'超过 {days} 天，需人工确认')})

    copies = [
        {'name': p.name, 'path': str(p), 'pinned': p.with_suffix('.keep').exists(),
         'eligible': p in completed}
        for p in directory.iterdir() if p.is_file() and TOOL_COPY_RE.search(p.name)
    ]
    targets.sort(key=lambda item: (item['kind'], item['path']))
    snapshot = [
        (str(p), p.stat().st_size, p.stat().st_mtime_ns, _file_digest(p))
        for item in targets for p in map(Path, item['paths'])
    ]
    token = hashlib.sha256(json.dumps([snapshot, days, keep, compact, bool(include_maps), bool(include_timetables),
                                      sorted(map(str, roots)), protected_paths], sort_keys=True).encode()).hexdigest()
    return {
        "token": token,
        "copies": sorted(copies, key=lambda x: x['name']),
        "include_maps": bool(include_maps), "include_timetables": bool(include_timetables),
        "protected_paths": protected_paths, "export_count": export_count,
        "export_directory": str(Path(export_directory).resolve()) if export_directory is not None else None,
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


def _validate_targets(directory: Path, paths: Iterable[str], export_directory: Path | None = None) -> list[Path]:
    directory = directory.resolve()
    roots = {directory}
    if export_directory is not None: roots.add(Path(export_directory).resolve())
    validated: list[Path] = []
    for value in paths:
        if Path(value).is_symlink(): raise RuntimeError('不清理符号链接')
        path = Path(value).resolve()
        if path.parent not in roots:
            raise RuntimeError(f"清理目标不在指定目录中：{path}")
        if not (
            TOOL_COPY_RE.search(path.name)
            or TOOL_PARTIAL_RE.search(path.name)
            or path.name.lower().endswith(".manifest.json")
            or path.suffix.lower() == '.json'
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


def execute_cleanup(directory: Path, preview: dict, *, export_directory: Path | None = None,
                    selected: list[str] | None = None) -> dict:
    # Do not act on an old preview if a player saved, pinned, or renamed a file.
    current = cleanup_preview(directory, days=preview['days'], keep=preview['keep'],
                              compact=preview.get('mode') == 'compact',
                              include_maps=preview.get('include_maps', False),
                              include_timetables=preview.get('include_timetables', False),
                              export_directory=export_directory, protected_paths=preview.get('protected_paths', ()))
    if current['token'] != preview.get('token'):
        raise RuntimeError('清理列表已变化，未执行清理。请重新预览并确认。')
    if preview.get('targets') != current['targets']:
        raise RuntimeError('清理目标与重新核对的列表不符，请重新预览')
    groups = {item['path']: item for item in current['targets']}
    if selected is None: selected = list(groups)
    if not isinstance(selected, list) or any(not isinstance(p, str) or p not in groups for p in selected):
        raise RuntimeError('所选文件不在当前清理候选中，请重新预览')
    chosen = [groups[p] for p in dict.fromkeys(selected)]
    requested = [path for item in chosen for path in item['paths']]
    paths = _validate_targets(directory, requested, export_directory)
    bytes_before = sum(path.stat().st_size for path in paths)
    _recycle_windows(paths)
    remaining = [str(path) for path in paths if path.exists()]
    if remaining:
        raise RuntimeError("以下文件未能移入回收站：" + "、".join(remaining))
    return {
        "moved_file_count": len(paths),
        "moved_group_count": len(chosen),
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
