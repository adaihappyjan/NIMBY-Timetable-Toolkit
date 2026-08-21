from __future__ import annotations

import argparse
import contextlib
import json
import mimetypes
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import webbrowser
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
BACKEND = ROOT / "toolkit_backend.py"
ASSET_VERSION = uuid.uuid4().hex[:8]
# NIMBY Rails stores saves under a "Saved Games/Weird and Wry/NIMBY Rails"
# folder, but the exact location differs per machine (OneDrive redirect, custom
# Steam library, Linux/Proton, macOS). SAVE_DIR is resolved at startup by
# resolve_save_dir(); this is only the last-resort default.
NIMBY_VENDOR = "Weird and Wry"
NIMBY_GAME = "NIMBY Rails"
NIMBY_STEAM_APPID = "1134710"
SAVE_DIR = Path.home() / "Saved Games" / NIMBY_VENDOR / NIMBY_GAME
def _default_config_root() -> Path:
    """A persistent, per-user config location for each OS (settings survive reboots)."""
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base)
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_CONFIG_HOME")
        if base:
            return Path(base)
        return Path.home() / ".config"
    return Path.home()


SETTINGS_DIR = _default_config_root() / "NIMBY_Timetable_Toolkit"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"
TASK_DIR = Path(tempfile.gettempdir()) / "NIMBY_Timetable_Toolkit_Web"
_DOWNLOADS = Path.home() / "Downloads"
EXPORT_DIR = (_DOWNLOADS if _DOWNLOADS.is_dir() else Path.home()) / "NIMBY 线路图导出"

sys.path.insert(0, str(ROOT))
from toolkit_cleanup import cleanup_preview, execute_cleanup  # noqa: E402
from toolkit_scriptgen import build_mod_zip  # noqa: E402
from toolkit_vehiclegen import build_vehicle_mod_zip  # noqa: E402


def read_settings() -> dict:
    defaults = {
        "enabled": True,
        "days": 14,
        "keep": 5,
        "workers": max(1, min(4, (os.cpu_count() or 2) - 1)),
        "save_dir": "",
    }
    try:
        stored = json.loads(SETTINGS_FILE.read_text(encoding="utf-8-sig"))
    except Exception:
        return defaults
    aliases = {
        "enabled": stored.get("enabled", stored.get("Enabled")),
        "days": stored.get("days", stored.get("Days")),
        "keep": stored.get("keep", stored.get("Keep")),
        "workers": stored.get("workers", stored.get("Workers")),
        "save_dir": stored.get("save_dir", stored.get("SaveDir")),
    }
    for key, value in aliases.items():
        if value is not None:
            defaults[key] = value
    defaults["enabled"] = bool(defaults["enabled"])
    defaults["days"] = max(1, min(365, int(defaults["days"])))
    defaults["keep"] = max(1, min(50, int(defaults["keep"])))
    defaults["workers"] = max(1, min(32, int(defaults["workers"])))
    defaults["save_dir"] = str(defaults.get("save_dir") or "")
    return defaults


def write_settings(settings: dict) -> dict:
    current = read_settings()
    for key in ("enabled", "days", "keep", "workers", "save_dir"):
        if key in settings:
            current[key] = settings[key]
    current["enabled"] = bool(current["enabled"])
    current["days"] = max(1, min(365, int(current["days"])))
    current["keep"] = max(1, min(50, int(current["keep"])))
    current["workers"] = max(1, min(32, int(current["workers"])))
    current["save_dir"] = str(current.get("save_dir") or "")
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    partial = SETTINGS_FILE.with_suffix(".json.partial")
    partial.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    partial.replace(SETTINGS_FILE)
    return current


def _win_saved_games_dir() -> Path | None:
    """Resolve the real Windows 'Saved Games' known folder (honours OneDrive)."""
    if not sys.platform.startswith("win"):
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8),
            ]

        # FOLDERID_SavedGames {4C5C32FF-BB9D-43b0-B5B4-2D72E54EAAA4}
        folderid = GUID(
            0x4C5C32FF, 0xBB9D, 0x43B0,
            (ctypes.c_ubyte * 8)(0xB5, 0xB4, 0x2D, 0x72, 0xE5, 0x4E, 0xAA, 0xA4),
        )
        ptr = ctypes.c_wchar_p()
        res = ctypes.windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(folderid), 0, None, ctypes.byref(ptr)
        )
        if res == 0 and ptr.value:
            path = Path(ptr.value)
            ctypes.windll.ole32.CoTaskMemFree(ptr)
            return path
    except Exception:
        return None
    return None


def candidate_save_dirs() -> list[Path]:
    """Likely NIMBY Rails save locations across OSes and install styles."""
    home = Path.home()
    tail = (NIMBY_VENDOR, NIMBY_GAME)
    cands: list[Path] = []
    known = _win_saved_games_dir()
    if known:
        cands.append(known.joinpath(*tail))
    # Windows default + common redirects.
    cands.append(home.joinpath("Saved Games", *tail))
    cands.append(home.joinpath("OneDrive", "Saved Games", *tail))
    cands.append(home.joinpath("Documents", "Saved Games", *tail))
    # macOS.
    cands.append(home.joinpath("Library", "Application Support", *tail))
    # Native Linux.
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        cands.append(Path(xdg).joinpath(*tail))
    cands.append(home.joinpath(".local", "share", *tail))
    # Linux/Steam Proton prefixes.
    steam_roots = [
        home / ".steam" / "steam",
        home / ".local" / "share" / "Steam",
        home / ".var" / "app" / "com.valvesoftware.Steam" / "data" / "Steam",
    ]
    for root in steam_roots:
        cands.append(
            root.joinpath(
                "steamapps", "compatdata", NIMBY_STEAM_APPID, "pfx",
                "drive_c", "users", "steamuser", "Saved Games", *tail,
            )
        )
    seen: set[str] = set()
    unique: list[Path] = []
    for cand in cands:
        key = str(cand)
        if key not in seen:
            seen.add(key)
            unique.append(cand)
    return unique


def _dir_has_saves(path: Path) -> bool:
    try:
        if not path.is_dir():
            return False
        return any(path.glob("*.nimbyrails5")) or any(path.glob("*Timetable Export*.json"))
    except Exception:
        return False


def detect_save_dir() -> Path:
    """Best-effort auto-detection: a folder that actually holds saves wins."""
    cands = candidate_save_dirs()
    for cand in cands:
        if _dir_has_saves(cand):
            return cand
    for cand in cands:
        if cand.is_dir():
            return cand
    return cands[0] if cands else Path.home().joinpath("Saved Games", NIMBY_VENDOR, NIMBY_GAME)


def resolve_save_dir() -> Path:
    """Precedence: NIMBY_SAVE_DIR env → saved setting → auto-detection."""
    env = os.environ.get("NIMBY_SAVE_DIR")
    if env and env.strip():
        return Path(env).expanduser()
    stored = read_settings().get("save_dir")
    if stored and str(stored).strip():
        return Path(str(stored)).expanduser()
    return detect_save_dir()


def save_dir_info() -> dict:
    """Snapshot of the active save directory plus alternatives for the UI."""
    active = SAVE_DIR
    try:
        save_count = len(list(active.glob("*.nimbyrails5"))) if active.is_dir() else 0
        export_count = len(list(active.glob("*Timetable Export*.json"))) if active.is_dir() else 0
    except Exception:
        save_count = export_count = 0
    candidates = [
        {"path": str(cand), "exists": cand.is_dir(), "has_saves": _dir_has_saves(cand)}
        for cand in candidate_save_dirs()
    ]
    return {
        "save_dir": str(active),
        "exists": active.is_dir(),
        "has_saves": _dir_has_saves(active),
        "save_count": save_count,
        "export_count": export_count,
        "source": "env" if os.environ.get("NIMBY_SAVE_DIR") else (
            "custom" if (read_settings().get("save_dir") or "").strip() else "auto"
        ),
        "env_locked": bool(os.environ.get("NIMBY_SAVE_DIR")),
        "candidates": candidates,
    }


def set_save_dir(path_str: str) -> dict:
    """Persist a user-chosen save directory and switch to it immediately."""
    global SAVE_DIR
    if os.environ.get("NIMBY_SAVE_DIR"):
        raise RuntimeError("存档目录已由环境变量 NIMBY_SAVE_DIR 指定，请先清除该变量再修改。")
    raw = str(path_str or "").strip().strip('"')
    if not raw:
        raise RuntimeError("请填写存档目录路径。")
    path = Path(raw).expanduser()
    if not path.is_dir():
        raise RuntimeError(f"目录不存在：{path}")
    SAVE_DIR = path.resolve()
    write_settings({"save_dir": str(SAVE_DIR)})
    return save_dir_info()


def redetect_save_dir() -> dict:
    """Forget any saved override and re-run auto-detection."""
    global SAVE_DIR
    if os.environ.get("NIMBY_SAVE_DIR"):
        raise RuntimeError("存档目录已由环境变量 NIMBY_SAVE_DIR 指定，请先清除该变量再修改。")
    write_settings({"save_dir": ""})
    SAVE_DIR = detect_save_dir()
    return save_dir_info()


def file_info(path: Path) -> dict:
    stat = path.stat()
    return {
        "name": path.name,
        "path": str(path),
        "size": stat.st_size,
        "modified_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "tool_generated": any(
            marker in path.name for marker in ("_Toolkit_", "_Extension_", "_Recovery_", "_Repair_")
        ),
    }


def recent_files() -> dict:
    if not SAVE_DIR.is_dir():
        # Don't create an empty folder in the wrong place on other machines;
        # the UI will prompt the user to pick the real save directory.
        return {"saves": [], "exports": []}
    saves = sorted(SAVE_DIR.glob("*.nimbyrails5"), key=lambda path: path.stat().st_mtime, reverse=True)
    exports = sorted(
        SAVE_DIR.glob("*Timetable Export*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return {
        "saves": [file_info(path) for path in saves[:40]],
        "exports": [file_info(path) for path in exports[:40]],
    }


def _safe_export_name(value: str, default: str, suffix: str) -> str:
    stem = str(value or "").strip()
    if stem.lower().endswith(suffix):
        stem = stem[: -len(suffix)]
    cleaned = "".join(
        ch for ch in stem if ch not in '<>:"/\\|?*' and ord(ch) >= 32
    ).strip().strip(".")
    if not cleaned:
        cleaned = default
    return cleaned[:80] + suffix


def save_map_export(payload: dict) -> Path:
    """Write a client-generated map (SVG/text) into a discoverable folder."""
    content = payload.get("svg")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("没有可导出的内容")
    if len(content) > 20_000_000:
        raise RuntimeError("导出内容过大")
    suffix = ".svg" if str(payload.get("format", "svg")).lower() == "svg" else ".txt"
    default = f"线路图_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    name = _safe_export_name(payload.get("filename", ""), default, suffix)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = EXPORT_DIR / name
    if path.exists():
        path = EXPORT_DIR / f"{path.stem}_{uuid.uuid4().hex[:6]}{suffix}"
    path.write_text(content, encoding="utf-8")
    return path


def validate_input_path(value: str, suffix: str) -> Path:
    path = Path(value).resolve()
    if path.parent != SAVE_DIR.resolve() or not path.is_file() or not path.name.lower().endswith(suffix):
        raise RuntimeError(f"文件无效或不在 NIMBY Rails 存档目录中：{path}")
    return path


def ensure_directory_writable(directory: Path) -> None:
    """Verify that this server instance can create output in the save folder."""
    probe: Path | None = None
    try:
        descriptor, probe_name = tempfile.mkstemp(
            prefix=".nimby_toolkit_write_test_",
            dir=str(directory),
        )
        os.close(descriptor)
        probe = Path(probe_name)
        probe.unlink()
    except PermissionError as exc:
        if probe is not None:
            try:
                probe.unlink(missing_ok=True)
            except OSError:
                pass
        raise RuntimeError(
            "当前工具箱后台进程没有存档目录的写入权限。请关闭所有旧的工具箱窗口，"
            "然后从资源管理器重新双击“启动工具箱.vbs”。存档目录："
            f"{directory}"
        ) from exc
    except OSError as exc:
        if probe is not None:
            try:
                probe.unlink(missing_ok=True)
            except OSError:
                pass
        raise RuntimeError(f"无法在存档目录创建输出文件：{directory}（{exc}）") from exc


def validate_output_path(value: str) -> Path:
    path = Path(value).resolve()
    if path.parent != SAVE_DIR.resolve() or path.suffix.lower() != ".nimbyrails5":
        raise RuntimeError("新存档必须保存在 NIMBY Rails 存档目录中")
    ensure_directory_writable(path.parent)
    if path.exists():
        raise RuntimeError("输出文件已经存在，请换一个名称")
    return path


class TaskManager:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.task: dict | None = None

    def _build_args(self, action: str, payload: dict) -> list[str]:
        if action == "inventory":
            limit = max(1, min(60, int(payload.get("limit", 12))))
            return [
                "inventory",
                "--directory",
                str(SAVE_DIR.resolve()),
                "--limit",
                str(limit),
            ]
        if action == "compare":
            before = validate_input_path(payload.get("before", ""), ".json")
            after = validate_input_path(payload.get("after", ""), ".json")
            if before == after:
                raise RuntimeError("请选择两份不同的导出进行对比")
            return ["compare", "--before", str(before), "--after", str(after)]
        if action == "map-data":
            export = validate_input_path(payload.get("export", ""), ".json")
            return ["map-data", "--export", str(export)]
        if action == "network-diff":
            before = validate_input_path(payload.get("before", ""), ".json")
            after = validate_input_path(payload.get("after", ""), ".json")
            if before == after:
                raise RuntimeError("请选择两份不同的导出进行对比")
            return ["network-diff", "--before", str(before), "--after", str(after)]
        if action == "find-reference":
            current = validate_input_path(payload.get("export", ""), ".json")
            target = str(payload.get("target", "")).strip()
            if not target:
                raise RuntimeError("请指定要恢复的目标时刻表")
            if len(target) > 500:
                raise RuntimeError("时刻表名称无效")
            limit = max(1, min(60, int(payload.get("limit", 15))))
            return [
                "find-reference",
                "--directory",
                str(SAVE_DIR.resolve()),
                "--current-export",
                str(current),
                "--target",
                target,
                "--limit",
                str(limit),
            ]
        if action == "network-read":
            save = validate_input_path(payload.get("save", ""), ".nimbyrails5")
            args = ["network-read", "--save", str(save)]
            if payload.get("no_signals"):
                args.append("--no-signals")
            return args
        if action == "save-overview":
            save = validate_input_path(payload.get("save", ""), ".nimbyrails5")
            return ["save-overview", "--save", str(save)]
        if action == "save-health":
            save = validate_input_path(payload.get("save", ""), ".nimbyrails5")
            args = ["save-health", "--save", str(save)]
            target = payload.get("target_headway")
            if target not in (None, "", 0):
                target_int = int(target)
                if not (10 <= target_int <= 86400):
                    raise RuntimeError("目标班距需在 10–86400 秒之间")
                args += ["--target-headway", str(target_int)]
            return args
        if action == "line-timetable":
            save = validate_input_path(payload.get("save", ""), ".nimbyrails5")
            return ["line-timetable", "--save", str(save)]
        if action == "operating-rules":
            save = validate_input_path(payload.get("save", ""), ".nimbyrails5")
            return ["operating-rules", "--save", str(save)]
        if action == "operating-rule-write":
            save = validate_input_path(payload.get("save", ""), ".nimbyrails5")
            output = validate_output_path(payload.get("output", ""))
            schedule = str(payload.get("schedule", "")).strip()
            if not schedule or len(schedule) > 500:
                raise RuntimeError("请提供有效的运营时刻表 id 或名称")
            entries = payload.get("entries") or []
            if not isinstance(entries, list) or len(entries) > 32:
                raise RuntimeError("运营规则项数量无效")
            entry_plan = payload.get("entry_plan")
            if entry_plan is not None and entries:
                raise RuntimeError("不能同时提交局部运营项和完整指令计划")
            args = [
                "operating-rule-write", "--save", str(save), "--output", str(output),
                "--schedule", schedule,
            ]
            if entry_plan is not None:
                if not isinstance(entry_plan, list) or not 1 <= len(entry_plan) <= 32:
                    raise RuntimeError("完整指令计划需包含 1–32 条顶层指令")
                total_records = 0

                def validate_plan_record(item: object, *, stacked: bool) -> dict:
                    nonlocal total_records
                    if not isinstance(item, dict):
                        raise RuntimeError("完整指令计划中的记录格式无效")
                    total_records += 1
                    if total_records > 128:
                        raise RuntimeError("完整指令计划最多包含 128 条记录")
                    order_id = item.get("order_id")
                    if order_id in (None, "", 0):
                        order_id = None
                    else:
                        order_id = int(order_id)
                        if order_id <= 0 or order_id & 1:
                            raise RuntimeError("Order ID 必须为空或为正偶数")
                    line_id = str(item.get("line_id", "")).strip()
                    if not re.fullmatch(r"0x4[0-9a-fA-F]{12}", line_id):
                        raise RuntimeError("Line ID 格式无效")
                    seconds = float(item.get("time_seconds"))
                    if not 0 <= seconds <= 172800 or seconds * 2 != round(seconds * 2):
                        raise RuntimeError("指令时间需为 0–48 小时内的 0.5 秒值")
                    days = int(item.get("days_mask"))
                    offset_group = int(item.get("offset_group_index", 0))
                    if not 1 <= days <= 0x7F or not 0 <= offset_group < 10:
                        raise RuntimeError("指令星期或偏移组范围无效")
                    repeat_is_max = item.get("repeat_is_max", False)
                    if not isinstance(repeat_is_max, bool):
                        raise RuntimeError("重复 Max 标记必须为布尔值")
                    repeat_count = item.get("repeat_count")
                    if not repeat_is_max:
                        repeat_count = int(repeat_count)
                        if not 1 <= repeat_count <= 100:
                            raise RuntimeError("重复次数需在 1–100 之间")
                    continue_into_next = item.get("continue_into_next", True)
                    if not isinstance(continue_into_next, bool):
                        raise RuntimeError("继续下一指令标记必须为布尔值")
                    timing_event = int(item.get("timing_event", 2))
                    if timing_event not in (0, 2, 4):
                        raise RuntimeError("Timing 事件无效")
                    selectors: dict[str, int] = {}
                    for name in ("enter_selector", "exit_selector", "timing_selector"):
                        value = int(item.get(name, 1))
                        if value < 1 or (value != 1 and value & 1):
                            raise RuntimeError(f"{name} 无效")
                        selectors[name] = value
                    loop_bias = int(item.get("timing_loop_bias", 0))
                    if not 0 <= loop_bias <= 2:
                        raise RuntimeError("Timing loop bias 无效")
                    children = item.get("stacked_entries", []) or []
                    if stacked and children:
                        raise RuntimeError("堆积子指令不能再次嵌套")
                    if not isinstance(children, list) or len(children) > 32:
                        raise RuntimeError("每条指令最多可堆积 32 条子指令")
                    normalized = {
                        "order_id": order_id,
                        "line_id": line_id,
                        "time_seconds": seconds,
                        "days_mask": days,
                        "offset_group_index": offset_group,
                        "repeat_is_max": repeat_is_max,
                        "repeat_count": None if repeat_is_max else repeat_count,
                        "continue_into_next": continue_into_next,
                        "timing_event": timing_event,
                        **selectors,
                        "timing_loop_bias": loop_bias,
                        "stacked_entries": [
                            validate_plan_record(child, stacked=True) for child in children
                        ],
                    }
                    return normalized

                normalized_plan = [
                    validate_plan_record(item, stacked=False) for item in entry_plan
                ]
                args += [
                    "--entry-plan-json",
                    json.dumps(normalized_plan, ensure_ascii=True, separators=(",", ":")),
                ]
            for item in entries:
                if not isinstance(item, dict):
                    raise RuntimeError("运营规则项格式无效")
                index = int(item.get("index"))
                seconds = float(item.get("time_seconds"))
                days = int(item.get("days_mask"))
                if not (0 <= index < 32 and 0 <= seconds <= 172800 and 1 <= days <= 0x7F):
                    raise RuntimeError("运营时间或日期范围无效")
                offset_group = int(item.get("offset_group_index", 0))
                if not 0 <= offset_group < 10:
                    raise RuntimeError("运营项偏移组需在 1–10 之间")
                repeat_is_max = item.get("repeat_is_max", False)
                if not isinstance(repeat_is_max, bool):
                    raise RuntimeError("重复 Max 标记必须为布尔值")
                repeat_count = item.get("repeat_count")
                if not repeat_is_max:
                    repeat_count = int(repeat_count)
                    if not 1 <= repeat_count <= 100:
                        raise RuntimeError("重复次数需在 1–100 之间")
                continue_into_next = item.get("continue_into_next", True)
                if not isinstance(continue_into_next, bool):
                    raise RuntimeError("继续下一指令标记必须为布尔值")
                entry = {
                    "index": index,
                    "time_seconds": seconds,
                    "days_mask": days,
                    "offset_group_index": offset_group,
                    "repeat_is_max": repeat_is_max,
                    "repeat_count": None if repeat_is_max else repeat_count,
                    "continue_into_next": continue_into_next,
                }
                args += [
                    "--entry-json",
                    json.dumps(entry, ensure_ascii=True, separators=(",", ":")),
                ]
            distributions = payload.get("distributions") or []
            if not isinstance(distributions, list) or len(distributions) > 10:
                raise RuntimeError("偏移组数量无效")
            seen_groups: set[int] = set()
            for item in distributions:
                if not isinstance(item, dict):
                    raise RuntimeError("偏移组格式无效")
                group_index = int(item.get("group_index"))
                if not 0 <= group_index < 10 or group_index in seen_groups:
                    raise RuntimeError("偏移组索引无效或重复")
                seen_groups.add(group_index)
                group_mode = str(item.get("mode", "")).strip()
                if group_mode not in ("fixed", "manual-duration", "line-duration"):
                    raise RuntimeError("偏移组模式无效")
                fixed = float(item.get("fixed_interval_seconds", 0))
                manual = float(item.get("manual_duration_seconds", 0))
                if not (0 <= fixed <= 86400 and 0 <= manual <= 86400):
                    raise RuntimeError("偏移间隔或均分时长范围无效")
                duration_line = item.get("duration_line_id")
                if duration_line not in (None, ""):
                    duration_line = str(duration_line).strip()
                    if not re.fullmatch(r"0x[0-9a-fA-F]+", duration_line):
                        raise RuntimeError("偏移组时长来源 Line id 无效")
                if group_mode == "line-duration" and not duration_line:
                    raise RuntimeError(f"偏移组 {group_index + 1} 需要选择时长来源线路")
                distribution = {
                    "group_index": group_index,
                    "mode": group_mode,
                    "fixed_interval_seconds": fixed,
                    "manual_duration_seconds": manual,
                    "duration_line_id": duration_line or None,
                }
                args += [
                    "--distribution-json",
                    json.dumps(distribution, ensure_ascii=True, separators=(",", ":")),
                ]
            mode = str(payload.get("offset_mode", "")).strip()
            if mode:
                if mode not in ("fixed", "manual-duration", "line-duration"):
                    raise RuntimeError("偏移模式无效")
                args += ["--offset-mode", mode]
                if mode == "fixed":
                    interval = float(payload.get("fixed_interval_seconds"))
                    if not (0 < interval <= 86400):
                        raise RuntimeError("固定间隔需在 0–86400 秒之间")
                    args += ["--fixed-interval", str(interval)]
                elif mode == "manual-duration":
                    duration = float(payload.get("manual_duration_seconds"))
                    if not (0 < duration <= 86400):
                        raise RuntimeError("手动总时长需在 0–86400 秒之间")
                    args += ["--manual-duration", str(duration)]
            if entry_plan is None and not entries and not distributions and not mode:
                raise RuntimeError("没有要写入的运营规则")
            return args
        if action == "timetable-write":
            save = validate_input_path(payload.get("save", ""), ".nimbyrails5")
            output = validate_output_path(payload.get("output", ""))
            route = str(payload.get("route", "")).strip()
            if not route or len(route) > 500:
                raise RuntimeError("请提供有效的线路 id 或名称")
            args = ["timetable-write", "--save", str(save), "--output", str(output),
                    "--route", route]
            dwell = payload.get("dwell")
            scale = payload.get("dwell_scale")
            dwell_list = payload.get("dwell_list")
            if isinstance(dwell_list, list) and dwell_list:
                if len(dwell_list) > 500:
                    raise RuntimeError("停站数量过多")
                parts = []
                for v in dwell_list:
                    if v in (None, "", "-", "*", "inherit"):
                        parts.append("-")
                        continue
                    vf = float(v)
                    if not (1.0 <= vf <= 3600.0):
                        raise RuntimeError("逐站停站时间需在 1–3600 秒之间")
                    parts.append(str(vf))
                args += ["--dwell-list", ",".join(parts)]
            elif dwell not in (None, "", 0):
                dwell_f = float(dwell)
                if not (1.0 <= dwell_f <= 7200.0):
                    raise RuntimeError("停站时间需在 1–7200 秒之间")
                args += ["--dwell", str(dwell_f)]
            elif scale not in (None, "", 0):
                scale_f = float(scale)
                if not (0.05 <= scale_f <= 100.0):
                    raise RuntimeError("缩放倍数需在 0.05–100 之间")
                args += ["--dwell-scale", str(scale_f)]
            else:
                raise RuntimeError("请提供停站时间(秒)或缩放倍数")
            return args
        if action == "station-name-write":
            save = validate_input_path(payload.get("save", ""), ".nimbyrails5")
            output = validate_output_path(payload.get("output", ""))
            args = ["station-name-write", "--save", str(save), "--output", str(output)]
            export_value = str(payload.get("export", "")).strip()
            if export_value:
                export = validate_input_path(export_value, ".json")
                args += ["--export", str(export)]
            pairs = payload.get("pairs") or []
            if isinstance(pairs, list):
                if len(pairs) > 5000:
                    raise RuntimeError("站名数量过多")
                for item in pairs:
                    if not isinstance(item, str) or "=" not in item or len(item) > 300:
                        raise RuntimeError(f"站名项无效：{item!r}")
                    args += ["--pair", item]
            if payload.get("all"):
                args.append("--all")
            if not export_value and not pairs:
                raise RuntimeError("请提供真实站名来源（导出 JSON 或手动 id=名称）")
            return args
        if action == "track-geometry":
            save = validate_input_path(payload.get("save", ""), ".nimbyrails5")
            return ["track-geometry", "--save", str(save)]
        if action == "ops-analyze":
            save = validate_input_path(payload.get("save", ""), ".nimbyrails5")
            args = ["ops-analyze", "--save", str(save)]
            export_value = str(payload.get("export", "")).strip()
            if export_value:
                export = validate_input_path(export_value, ".json")
                args += ["--export", str(export)]
            target = payload.get("target_headway")
            if target not in (None, "", 0):
                target_int = int(target)
                if not (10 <= target_int <= 86400):
                    raise RuntimeError("目标班距需在 10–86400 秒之间")
                args += ["--target-headway", str(target_int)]
            return args
        if action == "align-coords":
            save = validate_input_path(payload.get("save", ""), ".nimbyrails5")
            output = validate_output_path(payload.get("output", ""))
            updates = payload.get("updates") or []
            if not isinstance(updates, list) or not updates:
                raise RuntimeError("请至少提供一个车站坐标更新")
            if len(updates) > 2000:
                raise RuntimeError("坐标更新数量过多")
            args = ["align-coords", "--save", str(save), "--output", str(output)]
            for item in updates:
                if not isinstance(item, str) or "=" not in item or len(item) > 200:
                    raise RuntimeError(f"坐标更新项无效：{item!r}")
                args += ["--update", item]
            return args
        save = validate_input_path(payload.get("save", ""), ".nimbyrails5")
        export = validate_input_path(payload.get("export", ""), ".json")
        if action == "analyze":
            return ["analyze", "--save", str(save), "--export", str(export)]
        output = validate_output_path(payload.get("output", ""))
        if action == "recover-template":
            reference_export = validate_input_path(
                payload.get("reference_export", ""), ".json"
            )
            reference_source = str(payload.get("reference_source", "")).strip()
            target = str(payload.get("target", "")).strip()
            if not reference_source or not target:
                raise RuntimeError("请先选择历史来源车队和目标模板")
            if len(reference_source) > 500 or len(target) > 500:
                raise RuntimeError("时刻表名称无效")
            args = [
                "recover-template",
                "--save",
                str(save),
                "--export",
                str(export),
                "--reference-export",
                str(reference_export),
                "--reference-source",
                reference_source,
                "--target",
                target,
                "--output",
                str(output),
            ]
            if payload.get("garage_join", True):
                args.append("--garage-join")
            return args
        if action == "fix-tasks":
            pairs = payload.get("pairs") or []
            depots = payload.get("depot_schedules") or []
            if not pairs and not depots:
                raise RuntimeError("请至少选择一个可修复任务")
            args = [
                "fix-tasks",
                "--save",
                str(save),
                "--export",
                str(export),
                "--output",
                str(output),
            ]
            for pair in pairs:
                if "::" not in pair or len(pair) > 500:
                    raise RuntimeError("修复配对格式无效")
                args.extend(("--pair", pair))
            for depot in depots:
                if len(str(depot)) > 500:
                    raise RuntimeError("时刻表名称无效")
                args.extend(("--depot-schedule", str(depot)))
            return args
        if action == "batch-migrate":
            pairs = payload.get("pairs") or []
            if not pairs:
                raise RuntimeError("请至少选择一组时刻表")
            args = [
                "batch-migrate",
                "--save",
                str(save),
                "--export",
                str(export),
                "--output",
                str(output),
            ]
            for pair in pairs:
                if "::" not in pair or len(pair) > 500:
                    raise RuntimeError("时刻表配对格式无效")
                args.extend(("--pair", pair))
            if payload.get("garage_join", True):
                args.append("--garage-join")
            return args
        if action == "extension":
            schedules = payload.get("schedules") or []
            if not schedules:
                raise RuntimeError("请至少选择一张时刻表")
            mode = payload.get("mode")
            if mode not in ("add", "remove"):
                raise RuntimeError("扩展操作无效")
            args = [
                "extension",
                "--save",
                str(save),
                "--export",
                str(export),
                "--output",
                str(output),
                "--mode",
                mode,
            ]
            for schedule in schedules:
                args.extend(("--schedule", str(schedule)))
            return args
        raise RuntimeError("尚未开放的操作")

    def start(self, action: str, payload: dict, workers: int) -> dict:
        with self.lock:
            if self.task and self.task["process"].poll() is None:
                raise RuntimeError("已有任务正在处理，请等待完成或先取消")
            args = self._build_args(action, payload)
            TASK_DIR.mkdir(parents=True, exist_ok=True)
            token = uuid.uuid4().hex
            result_path = TASK_DIR / f"{token}.result.json"
            progress_path = TASK_DIR / f"{token}.progress.jsonl"
            command = [
                sys.executable,
                str(BACKEND),
                "--workers",
                str(max(1, min(32, workers))),
                "--result-file",
                str(result_path),
                "--progress-file",
                str(progress_path),
                *args,
            ]
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            process = subprocess.Popen(
                command,
                cwd=str(ROOT),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=flags,
            )
            self.task = {
                "id": token,
                "action": action,
                "process": process,
                "result_path": result_path,
                "progress_path": progress_path,
                "started": time.time(),
            }
            return {"task_id": token, "action": action}

    def status(self) -> dict:
        with self.lock:
            if not self.task:
                return {"state": "idle"}
            task = self.task
            process = task["process"]
            progress = None
            try:
                lines = task["progress_path"].read_text(encoding="utf-8").splitlines()
                if lines:
                    progress = json.loads(lines[-1])
            except Exception:
                pass
            if process.poll() is None:
                return {
                    "state": "running",
                    "task_id": task["id"],
                    "action": task["action"],
                    "progress": progress,
                }
            try:
                result = json.loads(task["result_path"].read_text(encoding="utf-8"))
            except Exception:
                result = {"ok": False, "error": f"后台任务没有返回结果（代码 {process.returncode}）"}
            return {
                "state": "complete" if result.get("ok") else "failed",
                "task_id": task["id"],
                "action": task["action"],
                "progress": progress,
                "result": result,
            }

    def cancel(self) -> dict:
        with self.lock:
            if not self.task or self.task["process"].poll() is not None:
                return {"cancelled": False}
            self.task["process"].kill()
            return {"cancelled": True}

    def is_running(self) -> bool:
        with self.lock:
            return bool(self.task and self.task["process"].poll() is None)


TASKS = TaskManager()
LAST_PING = time.monotonic()
HAD_CLIENT = False
STARTUP_CLEANUP: dict | None = None


CAPABILITIES = [
    {"rank": 1, "name": "时刻表健康与安全修复", "status": "available", "detail": "存档匹配、缺日、循环、车队与相位诊断"},
    {"rank": 2, "name": "智能迁移与车库接班", "status": "available", "detail": "按唯一 ID 迁移车队并批量绑定扩展"},
    {"rank": 3, "name": "时刻表编排器", "status": "available", "detail": "计算高峰/平峰间隔、均匀相位、跨午夜班次和最低车数"},
    {"rank": 4, "name": "NimbyScript 规则生成器", "status": "available", "detail": "生成车库接班、到站等待和信号限速 private mod"},
    {"rank": 5, "name": "运营分析与运营报告", "status": "available", "detail": "服务时段、班距均匀度、覆盖天数、车队规模 KPI，导出 CSV/JSON"},
    {"rank": 6, "name": "车辆与资产模组制作器", "status": "available", "detail": "按官方 schema=2 生成可加载车辆模组（mod.txt + 占位贴图），含编组与参数"},
    {"rank": 7, "name": "一键线路图", "status": "available", "detail": "按经纬度绘制单/多线路网图，支持八向示意图风格与 SVG 导出"},
    {"rank": 8, "name": "现实路网参考图", "status": "available", "detail": "叠加 OpenRailwayMap 与游戏路网，规划针本地存储、导出 GeoJSON/CSV"},
    {"rank": 9, "name": "存档差分实验室", "status": "available", "detail": "逐项对比两份导出的线路、车站、站序与坐标变化"},
    {"rank": 10, "name": "批量扩展绑定器", "status": "available", "detail": "批量为线路/信号/车队生成运营扩展 mod 与逐对象启用清单，并可把已校验的车库接班批量写入新存档"},
    {"rank": 11, "name": "现实路网导入向导", "status": "available", "detail": "从 OSM 拉取真实线路与站序，生成复刻对照清单并导出 JSON/CSV，一键把站点加入规划针"},
]


class Handler(BaseHTTPRequestHandler):
    server_version = "NIMBYToolkit/2"

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def send_json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(data)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_000_000:
            raise RuntimeError("请求过大")
        return json.loads(self.rfile.read(length).decode("utf-8")) if length else {}

    def same_origin(self) -> bool:
        """Reject cross-site requests so other local pages cannot drive the toolkit."""
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        host = self.headers.get("Host", "")
        return origin in (f"http://{host}", f"https://{host}")

    def do_GET(self) -> None:  # noqa: N802
        global HAD_CLIENT, LAST_PING
        route = urlparse(self.path).path
        try:
            if route == "/api/bootstrap":
                files = recent_files()
                settings = read_settings()
                preview = (
                    cleanup_preview(SAVE_DIR, days=settings["days"], keep=settings["keep"])
                    if SAVE_DIR.is_dir()
                    else {"groups": [], "total_files": 0}
                )
                self.send_json(
                    {
                        "ok": True,
                        "save_dir": str(SAVE_DIR),
                        "save_status": save_dir_info(),
                        "files": files,
                        "settings": settings,
                        "cleanup": preview,
                        "startup_cleanup": STARTUP_CLEANUP,
                        "capabilities": CAPABILITIES,
                    }
                )
                return
            if route == "/api/task/status":
                self.send_json({"ok": True, **TASKS.status()})
                return
            if route.startswith("/downloads/") and route.endswith(".zip"):
                token = Path(route).name
                path = (TASK_DIR / token).resolve()
                if path.parent != TASK_DIR.resolve() or not path.is_file():
                    raise RuntimeError("下载文件已经过期")
                data = path.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", f'attachment; filename="{token}"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if route == "/api/ping":
                HAD_CLIENT = True
                LAST_PING = time.monotonic()
                self.send_json({"ok": True})
                return
            self.serve_static(route)
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        try:
            if not self.same_origin():
                self.send_json({"ok": False, "error": "跨站请求已被拒绝"}, HTTPStatus.FORBIDDEN)
                return
            payload = self.read_json()
            if route == "/api/task/start":
                settings = read_settings()
                result = TASKS.start(str(payload.get("action")), payload, settings["workers"])
                self.send_json({"ok": True, **result})
                return
            if route == "/api/task/cancel":
                self.send_json({"ok": True, **TASKS.cancel()})
                return
            if route == "/api/settings":
                self.send_json({"ok": True, "settings": write_settings(payload)})
                return
            if route == "/api/config/save-dir":
                if payload.get("detect"):
                    status = redetect_save_dir()
                else:
                    status = set_save_dir(str(payload.get("path", "")))
                self.send_json({"ok": True, "save_status": status, "files": recent_files()})
                return
            if route == "/api/cleanup/preview":
                result = cleanup_preview(
                    SAVE_DIR,
                    days=int(payload.get("days", 14)),
                    keep=int(payload.get("keep", 5)),
                    compact=bool(payload.get("compact", False)),
                )
                self.send_json({"ok": True, "cleanup": result})
                return
            if route == "/api/cleanup/execute":
                preview = cleanup_preview(
                    SAVE_DIR,
                    days=int(payload.get("days", 14)),
                    keep=int(payload.get("keep", 5)),
                    compact=bool(payload.get("compact", False)),
                )
                result = execute_cleanup(SAVE_DIR, preview)
                self.send_json({"ok": True, "result": result, "files": recent_files()})
                return
            if route == "/api/script/generate":
                data, meta = build_mod_zip(payload)
                TASK_DIR.mkdir(parents=True, exist_ok=True)
                filename = f"{meta['script_id']}_{uuid.uuid4().hex[:8]}.zip"
                path = TASK_DIR / filename
                path.write_bytes(data)
                self.send_json(
                    {
                        "ok": True,
                        "download_url": f"/downloads/{filename}",
                        "meta": meta,
                    }
                )
                return
            if route == "/api/vehicle/generate":
                data, meta = build_vehicle_mod_zip(payload)
                TASK_DIR.mkdir(parents=True, exist_ok=True)
                filename = f"{meta['mod_id']}_{uuid.uuid4().hex[:8]}.zip"
                path = TASK_DIR / filename
                path.write_bytes(data)
                self.send_json(
                    {
                        "ok": True,
                        "download_url": f"/downloads/{filename}",
                        "meta": meta,
                    }
                )
                return
            if route == "/api/map/export":
                path = save_map_export(payload)
                self.send_json({"ok": True, "path": str(path), "dir": str(path.parent)})
                return
            raise RuntimeError("未知操作")
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def serve_static(self, route: str) -> None:
        relative = "index.html" if route in ("", "/") else unquote(route.lstrip("/"))
        path = (WEB_ROOT / relative).resolve()
        if WEB_ROOT.resolve() not in path.parents and path != WEB_ROOT.resolve():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not path.is_file():
            path = WEB_ROOT / "index.html"
        data = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.name == "index.html":
            html = data.decode("utf-8")
            html = html.replace('href="/styles.css"', f'href="/styles.css?v={ASSET_VERSION}"')
            html = html.replace('src="/app.js"', f'src="/app.js?v={ASSET_VERSION}"')
            html = html.replace("仅在本机运行", f"仅在本机运行 · v{ASSET_VERSION}")
            data = html.encode("utf-8")
        if content_type.startswith("text/") or content_type in ("application/javascript", "application/json"):
            content_type += "; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(data)


def open_app(url: str) -> None:
    candidates = [
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
    ]
    edge = next((path for path in candidates if path.is_file()), None)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if edge:
        subprocess.Popen(
            [
                str(edge),
                f"--app={url}",
                "--start-maximized",
                # Keep polling alive when the game takes focus / covers the window,
                # otherwise Chromium throttles setTimeout to ~1/min and the task
                # dock appears frozen even though the backend already finished.
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
                "--disable-backgrounding-occluded-windows",
                "--disk-cache-size=1",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
    else:
        webbrowser.open(url)


def idle_monitor(server: ThreadingHTTPServer) -> None:
    """Fallback shutdown for browser mode only.

    Never fires while a background task is running (so a save write is never
    killed), and uses a generous timeout so that a throttled background tab does
    not trigger a false shutdown.
    """
    while True:
        time.sleep(10)
        if TASKS.is_running():
            continue
        if HAD_CLIENT and time.monotonic() - LAST_PING > 180:
            server.shutdown()
            return


def run_startup_cleanup() -> dict | None:
    settings = read_settings()
    if not settings["enabled"]:
        return None
    if not SAVE_DIR.is_dir():
        return None
    preview = cleanup_preview(SAVE_DIR, days=settings["days"], keep=settings["keep"])
    if not preview["candidate_count"]:
        return {"preview": preview, "result": None}
    return {"preview": preview, "result": execute_cleanup(SAVE_DIR, preview)}


def safe_startup_cleanup() -> dict | None:
    """Startup cleanup must never crash the app or block the window from opening."""
    try:
        return run_startup_cleanup()
    except Exception as exc:
        return {"preview": None, "result": None, "error": str(exc)}


def purge_stale_task_files(max_age_seconds: int = 86_400) -> None:
    """Remove leftover result/progress/download files from previous sessions."""
    if not TASK_DIR.exists():
        return
    cutoff = time.time() - max_age_seconds
    for path in TASK_DIR.iterdir():
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            pass


def make_server() -> ThreadingHTTPServer:
    """Bind to an ephemeral loopback port so we never clash with other apps."""
    return ThreadingHTTPServer(("127.0.0.1", 0), Handler)


def run_desktop_window(app_url: str, server: ThreadingHTTPServer) -> bool:
    """Host the app in a native window. Returns False if pywebview is unavailable."""
    # Must be set before the WebView2 environment is created: stop Chromium from
    # throttling background timers when NIMBY Rails grabs focus, and disable the
    # disk cache so a stale app.js can never be reused.
    os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = (
        "--disable-background-timer-throttling "
        "--disable-renderer-backgrounding "
        "--disable-backgrounding-occluded-windows "
        "--disk-cache-size=1"
    )
    try:
        import webview
    except Exception:
        return False

    def _shutdown() -> None:
        with contextlib.suppress(Exception):
            TASKS.cancel()
        with contextlib.suppress(Exception):
            server.shutdown()

    try:
        window = webview.create_window(
            "NIMBY Rails 运营工作台",
            app_url,
            width=1280,
            height=860,
            min_size=(1024, 720),
        )
        window.events.closed += _shutdown
        webview.start()
    except Exception:
        return False
    return True


def main() -> None:
    global STARTUP_CLEANUP
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--headless", action="store_true", help="仅运行本地服务，不打开任何窗口")
    args = parser.parse_args()
    global SAVE_DIR
    SAVE_DIR = resolve_save_dir()
    purge_stale_task_files()
    STARTUP_CLEANUP = safe_startup_cleanup()

    server = make_server()
    actual_port = int(server.server_address[1])
    app_url = f"http://127.0.0.1:{actual_port}/"
    serve_thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.5}, daemon=True
    )
    serve_thread.start()

    try:
        if args.headless:
            serve_thread.join()
        elif run_desktop_window(app_url, server):
            pass  # window closed -> _shutdown already stopped the server
        else:
            threading.Thread(target=idle_monitor, args=(server,), daemon=True).start()
            if not args.no_browser:
                threading.Timer(0.4, open_app, args=(app_url,)).start()
            serve_thread.join()
    except KeyboardInterrupt:
        pass
    finally:
        with contextlib.suppress(Exception):
            TASKS.cancel()
        with contextlib.suppress(Exception):
            server.shutdown()
        with contextlib.suppress(Exception):
            server.server_close()


if __name__ == "__main__":
    main()
