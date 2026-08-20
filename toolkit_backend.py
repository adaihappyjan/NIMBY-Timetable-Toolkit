from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import hashlib
import json
import math
import os
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


import toolkit_binary as core  # noqa: E402
from toolkit_binary import (  # noqa: E402
    GARAGE_JOIN_VECTOR,
    Zstd,
    locate_train_record,
    split_save,
)


SECONDS_PER_DAY = 86_400
SECONDS_PER_WEEK = 7 * SECONDS_PER_DAY
DAY_NAMES_ZH = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
DEFAULT_WORKERS = max(1, min(4, (os.cpu_count() or 2) - 1))
_PROGRESS_FILE: Path | None = None


def configure_progress(path: Path | None) -> None:
    global _PROGRESS_FILE
    _PROGRESS_FILE = path
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")


def emit_progress(
    stage: str,
    current: int,
    total: int,
    message: str,
    **extra: Any,
) -> None:
    if _PROGRESS_FILE is None:
        return
    payload = {
        "stage": stage,
        "current": current,
        "total": max(1, total),
        "percent": max(0, min(100, round(current * 100 / max(1, total)))),
        "message": message,
        "time": datetime.now(timezone.utc).isoformat(),
        **extra,
    }
    with _PROGRESS_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        handle.flush()


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    partial.replace(path)


def percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def max_consecutive_line_runs(shift: dict, line_id: str) -> int:
    largest = current = 0
    for run in shift.get("runs") or []:
        if run.get("line_id") == line_id:
            current += 1
            largest = max(largest, current)
        else:
            current = 0
    return largest


def schedule_export_diagnostics(
    schedule: dict,
    line_info: dict[str, dict],
) -> dict:
    shifts = schedule.get("shifts") or []
    assignments = schedule.get("trains") or {}
    line_runs: dict[str, list[tuple[int, int]]] = {}
    local_counts_by_shift: list[dict[str, int]] = []
    line_max_consecutive: dict[str, int] = {}
    for shift_index, shift in enumerate(shifts):
        local_counts: dict[str, int] = {}
        for run in shift.get("runs") or []:
            line_id = run.get("line_id")
            times = run.get("arrival_departure") or []
            if not line_id or not times:
                continue
            start = int(times[0])
            line_runs.setdefault(line_id, []).append((shift_index, start))
            local_counts[line_id] = local_counts.get(line_id, 0) + 1
        local_counts_by_shift.append(local_counts)
        for line_id in local_counts:
            line_max_consecutive[line_id] = max(
                line_max_consecutive.get(line_id, 0),
                max_consecutive_line_runs(shift, line_id),
            )

    line_health: list[dict] = []
    for line_id, rows in line_runs.items():
        info = line_info.get(line_id, {"name": line_id, "stop_count": 0})
        counts = [counts.get(line_id, 0) for counts in local_counts_by_shift]
        day_run_counts = [0] * 7
        for _, start in rows:
            day_run_counts[(start // SECONDS_PER_DAY) % 7] += 1
        active_threshold = max(1, math.ceil(max(day_run_counts, default=0) * 0.5))
        active_days = [
            day for day, count in enumerate(day_run_counts) if count >= active_threshold
        ]
        line_health.append(
            {
                "id": line_id,
                "name": info["name"],
                "stop_count": info["stop_count"],
                "run_count": len(rows),
                "runs_per_shift": round(len(rows) / max(1, len(shifts)), 2),
                "min_runs_per_shift": min(counts) if counts else 0,
                "max_runs_per_shift": max(counts) if counts else 0,
                "max_consecutive_runs": line_max_consecutive.get(line_id, 0),
                "active_days": active_days,
                "active_day_names": [DAY_NAMES_ZH[index] for index in active_days],
                "day_run_counts": day_run_counts,
            }
        )
    line_health.sort(key=lambda row: (-row["stop_count"], row["name"].casefold()))
    service_lines = [row for row in line_health if row["stop_count"] > 1]
    depot_lines = [row for row in line_health if row["stop_count"] <= 1]
    service_line = max(service_lines, key=lambda row: row["run_count"], default=None)

    phase = {
        "status": "not_applicable",
        "line": service_line["name"] if service_line else None,
        "sample_day": None,
        "sample_count": 0,
        "unique_start_count": 0,
        "duplicate_start_count": 0,
        "min_gap_seconds": None,
        "median_gap_seconds": None,
        "p90_gap_seconds": None,
    }
    if service_line and len(shifts) > 1:
        by_day: dict[int, list[int]] = {}
        for shift_index, shift in enumerate(shifts):
            first_by_day: dict[int, int] = {}
            for run in shift.get("runs") or []:
                if run.get("line_id") != service_line["id"]:
                    continue
                times = run.get("arrival_departure") or []
                if not times:
                    continue
                start = int(times[0])
                day = (start // SECONDS_PER_DAY) % 7
                first_by_day[day] = min(first_by_day.get(day, start), start)
            for day, start in first_by_day.items():
                by_day.setdefault(day, []).append(start)
        if by_day:
            sample_day, starts = max(by_day.items(), key=lambda item: len(item[1]))
            starts = sorted(starts)
            unique = sorted(set(starts))
            gaps = [right - left for left, right in zip(unique, unique[1:])]
            duplicate_count = len(starts) - len(unique)
            if len(starts) >= 2 and len(unique) == 1:
                status = "critical"
            elif duplicate_count:
                status = "warning"
            elif len(starts) >= 2:
                status = "good"
            else:
                status = "insufficient_data"
            phase = {
                "status": status,
                "line": service_line["name"],
                "sample_day": sample_day,
                "sample_day_name": DAY_NAMES_ZH[sample_day],
                "sample_count": len(starts),
                "unique_start_count": len(unique),
                "duplicate_start_count": duplicate_count,
                "min_gap_seconds": min(gaps) if gaps else None,
                "median_gap_seconds": round(statistics.median(gaps)) if gaps else None,
                "p90_gap_seconds": percentile(gaps, 0.9),
            }

    # Read-only operational metrics (service window, headway, coverage) derived
    # purely from the export JSON; never used to modify a save.
    all_run_starts = [start for rows in line_runs.values() for _, start in rows]
    times_of_day = sorted(start % SECONDS_PER_DAY for start in all_run_starts)
    operations = {
        "run_total": len(all_run_starts),
        "service_start_seconds": times_of_day[0] if times_of_day else None,
        "service_end_seconds": times_of_day[-1] if times_of_day else None,
        "service_span_seconds": (
            times_of_day[-1] - times_of_day[0] if len(times_of_day) >= 2 else None
        ),
        "headway_min_seconds": phase.get("min_gap_seconds"),
        "headway_median_seconds": phase.get("median_gap_seconds"),
        "headway_p90_seconds": phase.get("p90_gap_seconds"),
        "phase_status": phase.get("status"),
        "service_line": service_line["name"] if service_line else None,
        "service_line_run_count": service_line["run_count"] if service_line else 0,
        "service_day_count": len(service_line["active_days"]) if service_line else 0,
        "service_day_names": service_line["active_day_names"] if service_line else [],
        "service_line_count": len(service_lines),
        "depot_line_count": len(depot_lines),
    }

    findings: list[dict] = []

    def finding(severity: str, code: str, title: str, detail: str, action: str) -> None:
        findings.append(
            {
                "severity": severity,
                "code": code,
                "schedule": schedule.get("name", ""),
                "title": title,
                "detail": detail,
                "action": action,
            }
        )

    name = schedule.get("name", "")
    if shifts and not assignments:
        finding(
            "critical",
            "NO_TRAINS",
            "班次没有可用列车",
            f"{len(shifts)} 个班次均未分配列车，调度不会启动。",
            "在游戏中分配列车，或使用模板恢复功能重建车队。",
        )
    elif shifts and len(assignments) < len(shifts):
        finding(
            "warning",
            "FEWER_TRAINS_THAN_SHIFTS",
            "列车少于班次",
            f"{len(shifts)} 个班次仅有 {len(assignments)} 列车；动态调度允许这种配置，但并非每班都有保证。",
            "确认这是有意的动态调度；若不是，请补齐列车许可。",
        )
    if "daily" in name.casefold() and service_line:
        active = service_line["active_days"]
        if len(active) < 7:
            missing = [DAY_NAMES_ZH[index] for index in range(7) if index not in active]
            finding(
                "critical",
                "DAILY_MISSING_DAYS",
                "Daily 表没有覆盖整周",
                "缺少：" + "、".join(missing),
                "在游戏的指令页补齐缺失日期，再重新导出检查。",
            )
    if phase["status"] == "critical":
        finding(
            "critical",
            "ZERO_OFFSETS",
            "所有列车同一时刻启动",
            f"{phase['sample_day_name']}检测到 {phase['sample_count']} 个班次只有 1 个不同起点。",
            "在偏移页启用自动分组，并按服务线路运行时长平均分配。",
        )
    elif phase["status"] == "warning":
        finding(
            "warning",
            "DUPLICATE_OFFSETS",
            "部分列车相位重叠",
            f"{phase['sample_day_name']}有 {phase['duplicate_start_count']} 个重复起点。",
            "检查班次自动分组是否全部启用，以及分组除数是否正确。",
        )
    for depot in depot_lines:
        if depot["max_consecutive_runs"] > 3 or depot["runs_per_shift"] > 21:
            finding(
                "critical",
                "DEPOT_CONTINUOUS_LOOP",
                "车库线路正在连续循环",
                f"{depot['name']} 平均每班 {depot['runs_per_shift']} 段，最长连续 {depot['max_consecutive_runs']} 段。",
                "把车库指令的重复方式改为 x1；工具可在新存档中安全修复。",
            )
    if any(row["code"] == "DEPOT_CONTINUOUS_LOOP" for row in findings):
        for row in findings:
            if row["code"] == "DAILY_MISSING_DAYS":
                row["action"] = (
                    "先用工具把同表的车库循环修复为 x1 并重新加载；"
                    "若复检仍缺日，再检查游戏中的日期设置。"
                )

    severity_rank = {"critical": 3, "warning": 2, "info": 1}
    highest = max((severity_rank.get(row["severity"], 0) for row in findings), default=0)
    risk_level = {3: "critical", 2: "warning", 1: "info", 0: "good"}[highest]
    return {
        "line_health": line_health,
        "service_line": service_line,
        "depot_lines": depot_lines,
        "phase": phase,
        "operations": operations,
        "findings": findings,
        "risk_level": risk_level,
    }


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_objects(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def schedule_record_boundaries(
    raw: bytes,
    objects: list[dict],
    extra_record_starts: list[int] | None = None,
) -> tuple[dict[str, int], dict[str, int], dict[str, str]]:
    positions: list[tuple[int, int, str]] = []
    errors: dict[str, str] = {}
    for schedule in (obj for obj in objects if obj.get("class") == "Schedule"):
        try:
            record_start, name_pos = core.locate_schedule_record(raw, schedule)
            positions.append((record_start, name_pos, schedule["name"]))
        except Exception as exc:
            errors[schedule["name"]] = str(exc)
    positions.sort()
    all_starts = sorted(
        {record_start for record_start, _, _ in positions}
        | set(extra_record_starts or [])
    )
    ends: dict[str, int] = {}
    starts: dict[str, int] = {}
    for record_start, _, name in positions:
        starts[name] = record_start
        ends[name] = next(
            (candidate for candidate in all_starts if candidate > record_start),
            len(raw),
        )
    return ends, starts, errors


def validate_save_export(raw: bytes, objects: list[dict]) -> dict:
    trains = [obj for obj in objects if obj.get("class") == "Train"]
    train_positions: list[int] = []
    train_errors: list[str] = []
    emit_progress("preflight", 5, 100, "正在执行写入前全量校验…")
    for train_index, train in enumerate(trains, 1):
        try:
            train_positions.append(locate_train_record(raw, train))
        except Exception as exc:
            train_errors.append(f"{train.get('name', train['id'])}: {exc}")
        if train_index % 50 == 0:
            emit_progress(
                "preflight",
                5 + round(30 * train_index / max(1, len(trains))),
                100,
                f"写入前核对列车 {train_index}/{len(trains)}…",
            )
    schedule_ends, schedule_starts, boundary_errors = schedule_record_boundaries(
        raw, objects, train_positions
    )
    schedule_errors: list[str] = []
    schedules = [obj for obj in objects if obj.get("class") == "Schedule"]
    for schedule_index, schedule in enumerate(schedules, 1):
        name = schedule["name"]
        try:
            if name in boundary_errors:
                raise RuntimeError(boundary_errors[name])
            if schedule.get("shifts"):
                core.schedule_layout(raw, schedule, schedule_ends.get(name))
            else:
                core.validate_empty_schedule_record(
                    raw, schedule, schedule_ends.get(name)
                )
        except Exception as exc:
            schedule_errors.append(f"{name}: {exc}")
        if schedule_index % 8 == 0:
            emit_progress(
                "preflight",
                35 + round(20 * schedule_index / max(1, len(schedules))),
                100,
                f"写入前核对时刻表 {schedule_index}/{len(schedules)}…",
            )
    if train_errors or schedule_errors:
        details = [*schedule_errors[:8], *train_errors[:8]]
        remaining = len(schedule_errors) + len(train_errors) - len(details)
        suffix = f"；另有 {remaining} 项" if remaining > 0 else ""
        raise RuntimeError(
            "存档与导出 JSON 未完全匹配，已禁止写入："
            + "；".join(details)
            + suffix
        )
    emit_progress("preflight", 55, 100, "写入前全量校验通过")
    return {
        "schedule_count": len(schedules),
        "train_count": len(trains),
        "all_schedule_records_verified": True,
        "all_train_records_verified": True,
    }


# Game format auto-adaptation. Instead of hard-coding a single version, the
# toolkit reads ExportMeta.model_version and classifies it. Known versions are
# fully supported; newer versions run in a compatible mode (read-only features
# are safe, writes are surfaced with a warning); older versions are flagged.
# To adapt to a future release, usually only KNOWN_MODEL_VERSIONS needs a value.
KNOWN_MODEL_VERSIONS = {224, 225, 226, 227, 228, 229, 230}
MIN_COMPATIBLE_MODEL_VERSION = 210


def detect_game_version(objects: list[dict]) -> dict:
    meta = next((o for o in objects if o.get("class") == "ExportMeta"), {})
    version = meta.get("model_version")
    latest_known = max(KNOWN_MODEL_VERSIONS)
    if version is None:
        status = "unknown"
        note = "导出文件未包含版本信息，已按只读安全模式处理，写入前请谨慎核对。"
    elif version in KNOWN_MODEL_VERSIONS:
        status = "supported"
        note = f"已适配游戏版本（model {version}）。"
    elif version > latest_known:
        status = "newer"
        note = (
            f"检测到更新的游戏版本（model {version}，已知最新 {latest_known}）。"
            "核心结构通常兼容，只读分析可放心使用；写入类操作请先用“存档差分实验室”复核一次。"
        )
    elif version >= MIN_COMPATIBLE_MODEL_VERSION:
        status = "compatible"
        note = f"检测到较早但兼容的游戏版本（model {version}）。"
    else:
        status = "outdated"
        note = f"检测到过旧的游戏版本（model {version}），建议在游戏内重新导出后再处理。"
    return {
        "model_version": version,
        "company_name": meta.get("company_name"),
        "clock_epoch_s": meta.get("clock_epoch_s"),
        "status": status,
        "note": note,
        "safe_to_write": status in ("supported", "compatible"),
        "known_versions": sorted(KNOWN_MODEL_VERSIONS),
        "latest_known_version": latest_known,
    }


def scan_export(path: Path) -> dict:
    emit_progress("export", 2, 100, "正在读取时刻表导出文件…")
    objects = load_objects(path)
    game_version = detect_game_version(objects)
    line_info = {
        obj["id"]: {
            "name": obj.get("name", obj["id"]),
            "stop_count": len(obj.get("stops") or []),
        }
        for obj in objects
        if obj.get("class") == "Line"
    }
    schedules = []
    schedule_objects = [obj for obj in objects if obj.get("class") == "Schedule"]
    for schedule_index, obj in enumerate(schedule_objects):
        if obj.get("class") != "Schedule":
            continue
        shifts = obj.get("shifts") or []
        trains = obj.get("trains") or {}
        used_lines: list[str] = []
        line_details: list[dict] = []
        line_run_counts: dict[str, int] = {}
        seen: set[str] = set()
        for shift in shifts:
            for run in shift.get("runs") or []:
                line_id = run.get("line_id")
                if line_id:
                    line_run_counts[line_id] = line_run_counts.get(line_id, 0) + 1
                if line_id and line_id not in seen:
                    info = line_info.get(
                        line_id, {"name": line_id, "stop_count": 0}
                    )
                    used_lines.append(info["name"])
                    line_details.append({**info, "id": line_id})
                    seen.add(line_id)
        for detail in line_details:
            detail["run_count"] = line_run_counts.get(detail["id"], 0)
        diagnostics = schedule_export_diagnostics(obj, line_info)
        schedules.append(
            {
                "id": obj["id"],
                "name": obj["name"],
                "shift_count": len(shifts),
                "train_count": len(trains),
                "is_source": bool(shifts and trains),
                "is_blank_template": len(shifts) == 1 and not trains,
                "is_empty_daily_target": (
                    not shifts
                    and not trains
                    and "daily" in obj["name"].casefold()
                ),
                "lines": used_lines,
                "line_details": line_details,
                "service_line": diagnostics["service_line"],
                "depot_lines": diagnostics["depot_lines"],
                "phase": diagnostics["phase"],
                "operations": diagnostics["operations"],
                "findings": diagnostics["findings"],
                "risk_level": diagnostics["risk_level"],
            }
        )
        if schedule_index % 8 == 0:
            emit_progress(
                "export",
                5 + round(25 * (schedule_index + 1) / max(1, len(schedule_objects))),
                100,
                f"正在分析时刻表 {schedule_index + 1}/{len(schedule_objects)}…",
            )
    schedules.sort(key=lambda item: item["name"].casefold())
    schedule_by_name = {item["name"]: item for item in schedules}
    shift_owners: dict[str, set[str]] = {}
    for schedule in schedule_objects:
        for shift in schedule.get("shifts") or []:
            shift_owners.setdefault(shift["id"], set()).add(schedule["name"])
    duplicate_pairs: dict[tuple[str, ...], list[str]] = {}
    for shift_id, owners in shift_owners.items():
        if len(owners) > 1:
            duplicate_pairs.setdefault(tuple(sorted(owners)), []).append(shift_id)
    for owners, shift_ids in duplicate_pairs.items():
        detail = (
            f"{len(shift_ids)} 个班次 ID 同时出现在："
            + "、".join(owners)
            + "。这通常表示旧来源表没有真正清空。"
        )
        for owner in owners:
            item = schedule_by_name[owner]
            item["findings"].append(
                {
                    "severity": "critical",
                    "code": "DUPLICATE_SHIFT_IDS",
                    "schedule": owner,
                    "title": "班次同时存在于多张时刻表",
                    "detail": detail,
                    "action": "不要继续写入；回到两份文件完全匹配的存档和 JSON，再重建目标表。",
                    "related_schedules": list(owners),
                    "duplicate_shift_count": len(shift_ids),
                }
            )
            item["risk_level"] = "critical"
    train_owners: dict[str, set[str]] = {}
    for schedule in schedule_objects:
        for train_id in (schedule.get("trains") or {}):
            train_owners.setdefault(train_id, set()).add(schedule["name"])
    train_overlap_pairs: dict[tuple[str, str], int] = {}
    for owners in train_owners.values():
        ordered_owners = sorted(owners)
        for left_index, left in enumerate(ordered_owners):
            for right in ordered_owners[left_index + 1 :]:
                key = (left, right)
                train_overlap_pairs[key] = train_overlap_pairs.get(key, 0) + 1
    for (left_name, right_name), overlap_count in train_overlap_pairs.items():
        left = schedule_by_name[left_name]
        right = schedule_by_name[right_name]
        smaller_fleet = min(left["train_count"], right["train_count"])
        if not smaller_fleet:
            continue
        overlap_ratio = overlap_count / smaller_fleet
        line_overlap = set(left["lines"]).intersection(right["lines"])
        linked_daily_pair = (
            "daily" in left_name.casefold() or "daily" in right_name.casefold()
        ) and (
            left_name in right["lines"]
            or right_name in left["lines"]
            or bool(line_overlap)
        )
        if overlap_ratio < 0.8 or not linked_daily_pair:
            continue
        detail = (
            f"{overlap_count} 列车同时被 {left_name} 和 {right_name} 许可，"
            f"占较小车队的 {round(overlap_ratio * 100)}%。动态调度允许这样做，"
            "但旧表迁移到 Daily 表后通常不应保留。"
        )
        for owner, related in ((left_name, right_name), (right_name, left_name)):
            item = schedule_by_name[owner]
            item["findings"].append(
                {
                    "severity": "critical",
                    "code": "OVERLAPPING_DAILY_FLEET",
                    "schedule": owner,
                    "title": "同一车队同时属于旧表和 Daily 表",
                    "detail": detail,
                    "action": "若不是有意的动态调度，请清空旧来源表，只保留 Daily 表。",
                    "related_schedule": related,
                    "overlap_train_count": overlap_count,
                }
            )
            item["risk_level"] = "critical"
    sources = [item for item in schedules if item["is_source"]]
    targets = [item for item in schedules if item["is_blank_template"]]
    empty_daily_targets = [
        item for item in schedules if item["is_empty_daily_target"]
    ]
    target_candidates = [*targets, *empty_daily_targets]

    numbered_line_aliases = {
        "1": ("yonge", "university", "green", "confederation"),
        "2": ("bloor", "danforth", "orange", "trillium"),
        "4": ("sheppard", "yellow", "airport"),
        "5": ("eglinton", "blue"),
        "6": ("finch west",),
    }

    def operator_token(name: str) -> str:
        return name.strip().casefold().split(maxsplit=1)[0] if name.strip() else ""

    def line_number(name: str) -> str | None:
        match = re.search(r"(?i)\bline\s*(\d+)\b", name)
        return match.group(1) if match else None

    suggestions = []
    for target in target_candidates:
        ranked = []
        target_lines = set(target["lines"])
        for source in sources:
            score = 0
            reasons = []
            if source["name"] in target_lines:
                score += 100
                reasons.append("模板使用的线路名与来源时刻表同名")
            overlap = target_lines.intersection(source["lines"])
            if overlap:
                score += 40 + len(overlap)
                reasons.append("使用相同线路：" + "、".join(sorted(overlap)))
            source_key = source["name"].casefold().replace(" daily", "")
            target_key = target["name"].casefold().replace(" daily", "")
            if source_key and source_key in target_key:
                score += 20
                reasons.append("名称相近")
            number = line_number(target["name"])
            if (
                not target_lines
                and number
                and operator_token(source["name"]) == operator_token(target["name"])
                and any(
                    alias in source["name"].casefold()
                    for alias in numbered_line_aliases.get(number, ())
                )
            ):
                score += 90
                reasons.append(f"运营方和 Line {number} 的线路别名相符")
            if score:
                ranked.append((score, source, reasons))
        if ranked:
            score, source, reasons = max(ranked, key=lambda row: row[0])
            suggestions.append(
                {
                    "source": source["name"],
                    "target": target["name"],
                    "fleet_size": source["train_count"],
                    "confidence": (
                        "高" if score >= 100 else "中"
                    ) if target["is_blank_template"] else "待补模板",
                    "reason": "；".join(
                        [
                            *reasons,
                            *(
                                ["已识别为完全空的 Daily 表；请先建立 1 个未分配模板班次"]
                                if target["is_empty_daily_target"]
                                else []
                            ),
                        ]
                    ),
                    "ready": target["is_blank_template"],
                }
            )
    findings = []
    seen_overlap_pairs: set[tuple[str, str]] = set()
    seen_duplicate_groups: set[tuple[str, ...]] = set()
    overlap_repairs = []
    for item in schedules:
        for finding in item["findings"]:
            if finding["code"] == "DUPLICATE_SHIFT_IDS":
                group_key = tuple(
                    sorted(
                        finding.get("related_schedules", [finding["schedule"]]),
                        key=str.casefold,
                    )
                )
                if group_key in seen_duplicate_groups:
                    continue
                seen_duplicate_groups.add(group_key)
            if finding["code"] == "OVERLAPPING_DAILY_FLEET":
                pair_key = tuple(
                    sorted(
                        (finding["schedule"], finding["related_schedule"]),
                        key=str.casefold,
                    )
                )
                if pair_key in seen_overlap_pairs:
                    continue
                seen_overlap_pairs.add(pair_key)
                left, right = pair_key
                left_daily = "daily" in left.casefold()
                right_daily = "daily" in right.casefold()
                if left_daily != right_daily:
                    source = right if left_daily else left
                    keep = left if left_daily else right
                    overlap_repairs.append(
                        {
                            "source": source,
                            "keep": keep,
                            "pair": f"{source}::{keep}",
                            "overlap_train_count": finding["overlap_train_count"],
                            "label": (
                                f"清空 {source}  →  保留 {keep} "
                                f"（{finding['overlap_train_count']} 列车）"
                            ),
                        }
                    )
            findings.append(finding)
    # Map each schedule to the set of schedules it shares duplicate shift IDs
    # with. Clearing an old source (retire_overlap) removes its shift records, so
    # a retire task also resolves DUPLICATE_SHIFT_IDS when the retired source is
    # the one holding the duplicates. This is safe: retire only zeroes the old
    # source's own vector, it never touches the Daily table being kept.
    duplicate_related: dict[str, set[str]] = {}
    for item in schedules:
        for row in item["findings"]:
            if row["code"] == "DUPLICATE_SHIFT_IDS":
                duplicate_related.setdefault(item["name"], set()).update(
                    name for name in row.get("related_schedules", []) if name != item["name"]
                )
    repair_tasks = []
    for repair in overlap_repairs:
        resolves = ["OVERLAPPING_DAILY_FLEET"]
        label = repair["label"]
        if repair["keep"] in duplicate_related.get(repair["source"], set()):
            resolves.append("DUPLICATE_SHIFT_IDS")
            label += "（同时清除重复班次 ID）"
        repair_tasks.append(
            {
                "id": f"overlap:{repair['pair']}",
                "type": "retire_overlap",
                "label": label,
                "pair": repair["pair"],
                "schedule": repair["source"],
                "resolves": resolves,
                "selected_by_default": True,
            }
        )
    for item in schedules:
        item_codes = {row["code"] for row in item["findings"]}
        if "DEPOT_CONTINUOUS_LOOP" not in item_codes:
            continue
        depot_names = [
            line["name"]
            for line in item["depot_lines"]
            if line["max_consecutive_runs"] > 3 or line["runs_per_shift"] > 21
        ]
        resolves = ["DEPOT_CONTINUOUS_LOOP"]
        suffix = ""
        if "DAILY_MISSING_DAYS" in item_codes:
            resolves.append("DAILY_MISSING_DAYS")
            suffix = "；修复后重新加载以恢复后续日期"
        repair_tasks.append(
            {
                "id": f"depot-x1:{item['name']}",
                "type": "depot_x1",
                "label": (
                    f"{item['name']}："
                    + "、".join(depot_names)
                    + f" 连续循环 → x1{suffix}"
                ),
                "schedule": item["name"],
                "resolves": resolves,
                "selected_by_default": True,
            }
        )
    severity_counts = {
        severity: sum(row["severity"] == severity for row in findings)
        for severity in ("critical", "warning", "info")
    }
    health_score = max(
        0,
        100 - severity_counts["critical"] * 8 - severity_counts["warning"] * 3,
    )
    service_schedules = [
        item for item in schedules if item["operations"]["service_line"]
    ]
    service_starts = [
        item["operations"]["service_start_seconds"]
        for item in service_schedules
        if item["operations"]["service_start_seconds"] is not None
    ]
    service_ends = [
        item["operations"]["service_end_seconds"]
        for item in service_schedules
        if item["operations"]["service_end_seconds"] is not None
    ]
    risk_distribution = {
        level: sum(item["risk_level"] == level for item in schedules)
        for level in ("critical", "warning", "info", "good")
    }
    analytics = {
        "total_shifts": sum(item["shift_count"] for item in schedules),
        "unique_train_count": len(train_owners),
        "assigned_train_slots": sum(item["train_count"] for item in schedules),
        "total_runs": sum(item["operations"]["run_total"] for item in schedules),
        "service_schedule_count": len(service_schedules),
        "depot_schedule_count": sum(
            1 for item in schedules if item["operations"]["depot_line_count"]
        ),
        "earliest_service_seconds": min(service_starts) if service_starts else None,
        "latest_service_seconds": max(service_ends) if service_ends else None,
        "risk_distribution": risk_distribution,
    }
    return {
        "export": str(path),
        "export_file_size": path.stat().st_size,
        "export_modified_utc": datetime.fromtimestamp(
            path.stat().st_mtime, timezone.utc
        ).isoformat(),
        "schedule_count": len(schedules),
        "source_count": len(sources),
        "blank_template_count": len(targets),
        "empty_daily_target_count": len(empty_daily_targets),
        "empty_daily_targets": [item["name"] for item in empty_daily_targets],
        "schedules": schedules,
        "suggested_pairs": suggestions,
        "overlap_repairs": overlap_repairs,
        "repair_tasks": repair_tasks,
        "findings": findings,
        "severity_counts": severity_counts,
        "health_score": health_score,
        "analytics": analytics,
        "game_version": game_version,
    }


def analyze_save(save_path: Path, export_path: Path) -> dict:
    emit_progress("analyze", 1, 100, "正在载入导出数据…")
    objects = load_objects(export_path)
    scan = scan_export(export_path)
    emit_progress("analyze", 30, 100, "正在解压并核对存档…")
    header, frame, frame_offset = split_save(save_path)
    raw = Zstd().decompress(frame)
    trains = [obj for obj in objects if obj.get("class") == "Train"]
    train_names = {obj["id"]: obj.get("name", obj["id"]) for obj in trains}
    starts = []
    unreadable_trains = []
    for train_index, train in enumerate(trains):
        try:
            starts.append((locate_train_record(raw, train), train))
        except Exception:
            unreadable_trains.append(train.get("name", train["id"]))
        if train_index and train_index % 50 == 0:
            emit_progress(
                "analyze",
                30 + round(30 * train_index / max(1, len(trains))),
                100,
                f"正在核对列车 {train_index}/{len(trains)}…",
            )
    starts.sort(key=lambda row: row[0])
    schedule_ends, schedule_starts, schedule_boundary_errors = schedule_record_boundaries(
        raw, objects, [position for position, _ in starts]
    )
    extension_state: dict[str, bool | None] = {}
    for index, (start, train) in enumerate(starts):
        if index + 1 >= len(starts):
            extension_state[train["id"]] = None
            continue
        end = starts[index + 1][0]
        extension_state[train["id"]] = raw[start:end].endswith(GARAGE_JOIN_VECTOR)

    schedule_objects = {
        obj["name"]: obj for obj in objects if obj.get("class") == "Schedule"
    }
    health_schedules = []
    compatible = 0
    warnings = []
    save_findings: list[dict] = []
    for schedule_index, item in enumerate(scan["schedules"]):
        schedule = schedule_objects[item["name"]]
        ids = list((schedule.get("trains") or {}).keys())
        enabled = sum(extension_state.get(train_id) is True for train_id in ids)
        unknown = sum(extension_state.get(train_id) is None for train_id in ids)
        record_ok = None
        record_error = None
        try:
            if item["name"] in schedule_boundary_errors:
                raise RuntimeError(schedule_boundary_errors[item["name"]])
            if item["shift_count"]:
                core.schedule_layout(raw, schedule, schedule_ends.get(item["name"]))
            else:
                core.validate_empty_schedule_record(
                    raw, schedule, schedule_ends.get(item["name"])
                )
            record_ok = True
            compatible += 1
        except Exception as exc:
            record_ok = False
            record_error = str(exc)
        risks = [finding["title"] for finding in item.get("findings", [])]
        if item["is_blank_template"]:
            risks.append("空白模板，尚未分配列车")
        if any(line["stop_count"] <= 1 for line in item["line_details"]):
            risks.append("包含单站车库线路，需确认车库进出路径")
        looping_depots = [
            line
            for line in item.get("depot_lines", [])
            if line.get("max_consecutive_runs", 0) > 3
            or line.get("runs_per_shift", 0) > 21
        ]
        if looping_depots:
            risks.append(
                "车库线路疑似被设为连续循环："
                + "、".join(
                    f"{line['name']}（每班 {line['runs_per_shift']} 段）"
                    for line in looping_depots
                )
            )
        if record_ok is False:
            risks.append("导出表与存档中的记录不一致")
        health_schedules.append(
            {
                **item,
                "garage_enabled": enabled,
                "garage_disabled": max(0, len(ids) - enabled - unknown),
                "garage_unknown": unknown,
                "save_record_ok": record_ok,
                "save_record_error": record_error,
                "risks": risks,
            }
        )
        if schedule_index % 8 == 0:
            emit_progress(
                "analyze",
                62 + round(25 * (schedule_index + 1) / max(1, len(scan["schedules"]))),
                100,
                f"正在核对时刻表 {schedule_index + 1}/{len(scan['schedules'])}…",
            )

    expected_records = len(scan["schedules"])
    if unreadable_trains:
        warnings.append(f"有 {len(unreadable_trains)} 列车无法在存档中定位，导出文件可能不是这份存档的")
    looping_schedule_names = [
        item["name"]
        for item in health_schedules
        if any("连续循环" in risk for risk in item["risks"])
    ]
    if looping_schedule_names:
        warnings.append(
            "检测到单站车库线路连续循环："
            + "、".join(looping_schedule_names)
            + "；已加入可勾选修复任务，可与旧表抢班一起生成一个修复存档"
        )
    if compatible != expected_records:
        warnings.append(
            f"仅核对成功 {compatible}/{expected_records} 个时刻表；请重新从当前存档导出 JSON"
        )
        save_findings.append(
            {
                "severity": "critical",
                "code": "SAVE_EXPORT_MISMATCH",
                "schedule": "",
                "title": "存档与导出文件不匹配",
                "detail": f"仅核对成功 {compatible}/{expected_records} 个非空时刻表。",
                "action": "从这份存档重新导出时刻表 JSON，再开始修改。",
            }
        )
    if not scan["blank_template_count"]:
        if scan["empty_daily_target_count"]:
            warnings.append(
                "没有可直接迁移的模板班次；发现完全空的 Daily 表："
                + "、".join(scan["empty_daily_targets"])
                + "。工具已给出智能匹配，但需先在游戏里建立 1 个未分配模板班次"
            )
    spaced_names = [
        item["name"] for item in scan["schedules"] if item["name"] != item["name"].strip()
    ]
    if spaced_names:
        warnings.append(
            "发现名称前后带隐藏空格的时刻表："
            + "、".join(repr(name) for name in spaced_names)
            + "；工具会自动兼容，建议以后在游戏中删掉空格"
        )
    if not warnings:
        warnings.append("存档和导出文件基本匹配，可以开始操作")
    enabled_total = sum(state is True for state in extension_state.values())
    all_findings = [*scan.get("findings", []), *save_findings]
    severity_counts = {
        severity: sum(row["severity"] == severity for row in all_findings)
        for severity in ("critical", "warning", "info")
    }
    health_score = max(
        0,
        100 - severity_counts["critical"] * 8 - severity_counts["warning"] * 3,
    )
    emit_progress("analyze", 100, 100, "体检完成")
    return {
        **scan,
        "save": str(save_path),
        "save_file_size": save_path.stat().st_size,
        "raw_size": len(raw),
        "zstd_frame_offset": frame_offset,
        "train_count": len(trains),
        "located_train_count": len(starts),
        "garage_enabled_total": enabled_total,
        "garage_unknown_total": sum(state is None for state in extension_state.values()),
        "compatible_schedule_count": compatible,
        "expected_schedule_count": expected_records,
        "health_schedules": health_schedules,
        "warnings": warnings,
        "findings": all_findings,
        "severity_counts": severity_counts,
        "health_score": health_score,
        "worker_processes": DEFAULT_WORKERS,
        "save_format_version_hint": list(header[8:12]) if len(header) >= 12 else [],
    }


def inventory_export_worker(path_value: str) -> dict:
    path = Path(path_value)
    started = time.perf_counter()
    try:
        scan = scan_export(path)
        sources = [
            {
                "name": item["name"],
                "train_count": item["train_count"],
                "shift_count": item["shift_count"],
                "lines": item["lines"],
                "risk_level": item["risk_level"],
            }
            for item in scan["schedules"]
            if item["is_source"]
        ]
        return {
            "ok": True,
            "path": str(path),
            "name": path.name,
            "file_size": path.stat().st_size,
            "modified_utc": datetime.fromtimestamp(
                path.stat().st_mtime, timezone.utc
            ).isoformat(),
            "modified_timestamp": path.stat().st_mtime,
            "schedule_count": scan["schedule_count"],
            "source_count": scan["source_count"],
            "blank_template_count": scan["blank_template_count"],
            "health_score": scan["health_score"],
            "severity_counts": scan["severity_counts"],
            "critical_schedules": sorted(
                {
                    row["schedule"]
                    for row in scan["findings"]
                    if row["severity"] == "critical" and row["schedule"]
                }
            ),
            "sources": sources,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }
    except Exception as exc:
        return {
            "ok": False,
            "path": str(path),
            "name": path.name,
            "file_size": path.stat().st_size if path.exists() else 0,
            "modified_timestamp": path.stat().st_mtime if path.exists() else 0,
            "error": str(exc),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }


def command_inventory(args: argparse.Namespace) -> dict:
    started = time.perf_counter()
    directory = args.directory.resolve()
    if not directory.is_dir():
        raise RuntimeError(f"目录不存在：{directory}")
    exports = sorted(
        directory.glob("*Timetable Export*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )[: args.limit]
    saves = sorted(
        directory.glob("*.nimbyrails5"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )[: args.limit]
    workers = max(1, min(args.workers, len(exports) or 1))
    emit_progress(
        "inventory",
        1,
        max(1, len(exports)),
        f"正在用 {workers} 个后台进程检查 {len(exports)} 份导出…",
    )
    export_results: list[dict] = []
    if workers == 1:
        for index, path in enumerate(exports, 1):
            export_results.append(inventory_export_worker(str(path)))
            emit_progress(
                "inventory", index, len(exports), f"已检查 {index}/{len(exports)} 份导出"
            )
    else:
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(inventory_export_worker, str(path)): path for path in exports
            }
            for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
                export_results.append(future.result())
                emit_progress(
                    "inventory", index, len(exports), f"已检查 {index}/{len(exports)} 份导出"
                )
    export_results.sort(key=lambda row: row.get("modified_timestamp", 0), reverse=True)

    save_results = []
    for save in saves:
        nearest = None
        valid_exports = [row for row in export_results if row.get("ok")]
        if valid_exports:
            nearest = min(
                valid_exports,
                key=lambda row: abs(row["modified_timestamp"] - save.stat().st_mtime),
            )
        save_results.append(
            {
                "path": str(save),
                "name": save.name,
                "file_size": save.stat().st_size,
                "modified_utc": datetime.fromtimestamp(
                    save.stat().st_mtime, timezone.utc
                ).isoformat(),
                "modified_timestamp": save.stat().st_mtime,
                "nearest_export": nearest["path"] if nearest else None,
                "nearest_export_gap_seconds": round(
                    abs(nearest["modified_timestamp"] - save.stat().st_mtime)
                )
                if nearest
                else None,
                "tool_created": bool(
                    "_Toolkit_" in save.name
                    or "_Extension_" in save.name
                    or "_Recovery_" in save.name
                    or "_Repair_" in save.name
                ),
            }
        )

    partials = sorted(directory.glob("*.partial"))
    manifests = sorted(directory.glob("*.manifest.json"))
    manifest_health = []
    for manifest_path in manifests:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            output_path = Path(manifest.get("output_save", ""))
            manifest_health.append(
                {
                    "path": str(manifest_path),
                    "output": str(output_path),
                    "output_exists": output_path.exists(),
                    "verified": bool(
                        manifest.get("compressed_readback_verified")
                        and manifest.get("atomic_write_verified")
                    ),
                }
            )
        except Exception as exc:
            manifest_health.append(
                {"path": str(manifest_path), "output_exists": False, "verified": False, "error": str(exc)}
            )
    emit_progress("inventory", len(exports), max(1, len(exports)), "历史文件盘点完成")
    return {
        "action": "inventory",
        "directory": str(directory),
        "logical_cpu_count": os.cpu_count() or 1,
        "workers_requested": args.workers,
        "workers_used": workers,
        "parallel": workers > 1,
        "exports": export_results,
        "saves": save_results,
        "partial_files": [str(path) for path in partials],
        "manifest_health": manifest_health,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def haversine_meters(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    radius = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(a)))


def extract_network(objects: list[dict]) -> tuple[list[dict], dict[str, dict]]:
    """Pull lines (ordered station id sequence + colour) and stations
    (name + lon/lat) out of a timetable export. Read-only."""
    stations: dict[str, dict] = {}
    for obj in objects:
        if obj.get("class") != "Station":
            continue
        lonlat = obj.get("lonlat")
        if not lonlat or len(lonlat) != 2:
            continue
        stations[obj["id"]] = {
            "name": obj.get("name", obj["id"]),
            "lon": float(lonlat[0]),
            "lat": float(lonlat[1]),
        }
    lines: list[dict] = []
    for obj in objects:
        if obj.get("class") != "Line":
            continue
        stops = [
            stop.get("station_id")
            for stop in (obj.get("stops") or [])
            if stop.get("station_id")
        ]
        lines.append(
            {
                "id": obj["id"],
                "name": obj.get("name", obj["id"]),
                "code": obj.get("code", ""),
                "color": obj.get("color", ""),
                "stops": stops,
                "stop_count": len(stops),
            }
        )
    lines.sort(key=lambda row: (-row["stop_count"], row["name"].casefold()))
    return lines, stations


def command_map_data(args: argparse.Namespace) -> dict:
    emit_progress("map", 1, 2, "正在读取线路与车站坐标…")
    objects = load_objects(args.export)
    lines, stations = extract_network(objects)
    referenced = {sid for line in lines for sid in line["stops"]}
    stations = {sid: data for sid, data in stations.items() if sid in referenced}
    emit_progress("map", 2, 2, "线路数据就绪")
    return {
        "action": "map-data",
        "export": str(args.export),
        "lines": lines,
        "stations": stations,
        "line_count": len(lines),
        "station_count": len(stations),
    }


def command_save_overview(args: argparse.Namespace) -> dict:
    """JSON-free structural overview read straight from a save (no export needed).

    Every number here comes from the binary object stream, validated against real
    exports (stations 411/411, schedules 70/70, trains 393/393). Read-only.
    """
    import toolkit_savereader as savereader
    from toolkit_binary import Zstd, split_save

    path = Path(args.save)
    emit_progress("overview", 1, 3, "正在解压并直读存档结构…")
    header, frame, _offset = split_save(path)
    raw = Zstd().decompress(frame)
    stations = savereader.read_stations_from_raw(raw)
    schedules = savereader.read_schedules_from_raw(raw)
    signals = savereader.read_signals_from_raw(raw)
    trains = savereader.read_trains_from_raw(raw)
    assignments = savereader.read_schedule_assignments(raw)
    emit_progress("overview", 2, 3, "正在归类线路与时刻表…")

    assign_by_id = {a.schedule_id: a for a in assignments}
    routes = [s for s in schedules if s.stop_count >= 2]
    containers = [s for s in schedules if s.stop_count < 2]
    named_stations = sum(1 for s in stations if not s.name.startswith("车站 "))
    total_shifts = sum(a.count for a in assignments)
    assigned_train_ids = {t for a in assignments for t in a.train_ids}

    def _row(s, with_stops):
        a = assign_by_id.get(s.id)
        row = {
            "id": s.id, "name": s.name, "color": s.color,
            "train_count": a.count if a else 0,
            "shift_count": a.count if a else 0,
        }
        if with_stops:
            row["stop_count"] = s.stop_count
        return row

    route_rows = sorted(
        (_row(s, True) for s in routes),
        key=lambda r: (-r["stop_count"], r["name"].casefold()),
    )
    container_rows = sorted(
        (_row(s, False) for s in containers),
        key=lambda r: (-r["train_count"], r["name"].casefold()),
    )

    stat = path.stat()
    emit_progress("overview", 3, 3, "结构总览就绪")
    return {
        "action": "save-overview",
        "save": str(path),
        "save_name": path.name,
        "file_size": stat.st_size,
        "modified_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "save_format_version_hint": list(header[8:12]) if len(header) >= 12 else [],
        "counts": {
            "stations": len(stations),
            "named_stations": named_stations,
            "routes": len(routes),
            "schedules": len(schedules),
            "active_schedules": len(assignments),
            "signals": len(signals),
            "trains": len(trains),
            "assigned_trains": len(assigned_train_ids),
            "total_shifts": total_shifts,
        },
        "routes": route_rows,
        "containers": container_rows,
    }


def command_network_read(args: argparse.Namespace) -> dict:
    """JSON-free: read the rail network (lines/stations/signals) from a save."""
    import toolkit_savereader as savereader

    include_signals = not getattr(args, "no_signals", False)
    emit_progress("network", 1, 3, "正在解压并直读存档路网…")
    net = savereader.read_network(
        args.save, include_signals=include_signals, include_trains=True
    )
    emit_progress("network", 2, 3, "正在整理线路、车站与车队…")
    stations = {
        s["id"]: {"name": s["name"], "lon": s["lon"], "lat": s["lat"]}
        for s in net["stations"]
    }
    lines = [
        {
            "id": ln["id"],
            "name": ln["name"],
            "code": ln["code"] or "",
            "color": ln["color"] or "",
            "stops": ln["stops"],
            "stop_count": len(ln["stops"]),
        }
        for ln in net["lines"]
    ]
    lines.sort(key=lambda row: (-row["stop_count"], row["name"].casefold()))
    referenced = {sid for line in lines for sid in line["stops"]}
    map_stations = {sid: data for sid, data in stations.items() if sid in referenced}
    emit_progress("network", 3, 3, "路网数据就绪")
    return {
        "action": "network-read",
        "save": str(args.save),
        "lines": lines,
        "stations": map_stations,
        "all_stations": stations,
        "signals": net["signals"],
        "trains": net.get("trains", []),
        "line_count": len(lines),
        "station_count": len(stations),
        "signal_count": len(net["signals"]),
        "train_count": len(net.get("trains", [])),
        "schedule_count": net["counts"].get("schedules", len(lines)),
    }


def command_align_coords(args: argparse.Namespace) -> dict:
    """Overwrite station coordinates in place, producing a new save."""
    import toolkit_coordedit as coordedit

    updates: dict[str, tuple[float, float]] = {}
    for item in args.update or []:
        if "=" not in item:
            raise RuntimeError(f"坐标更新格式错误（缺少 =）：{item}")
        key, coords = item.split("=", 1)
        try:
            lon_s, lat_s = coords.split(",")
            updates[key.strip()] = (float(lon_s), float(lat_s))
        except ValueError as exc:
            raise RuntimeError(f"坐标格式错误（应为 lon,lat）：{item}") from exc
    if not updates:
        raise RuntimeError("没有要写入的坐标更新")
    emit_progress("align", 10, 100, "正在写入车站坐标并校验…")
    manifest = coordedit.set_station_coordinates(args.save, args.output, updates)
    emit_progress("align", 100, 100, "坐标对齐完成")
    return {"action": "align-coords", **manifest}


def command_network_diff(args: argparse.Namespace) -> dict:
    emit_progress("netdiff", 1, 3, "正在读取较早的导出…")
    before_lines, before_stations = extract_network(load_objects(args.before))
    emit_progress("netdiff", 2, 3, "正在读取较新的导出…")
    after_lines, after_stations = extract_network(load_objects(args.after))

    def station_label(sid: str) -> str:
        data = after_stations.get(sid) or before_stations.get(sid)
        return data["name"] if data else sid

    station_changes: list[dict] = []
    for sid in before_stations.keys() | after_stations.keys():
        old = before_stations.get(sid)
        new = after_stations.get(sid)
        if old is None:
            station_changes.append({"change": "added", "name": new["name"]})
        elif new is None:
            station_changes.append({"change": "removed", "name": old["name"]})
        else:
            if old["name"] != new["name"]:
                station_changes.append(
                    {"change": "renamed", "name": new["name"], "detail": f"{old['name']} → {new['name']}"}
                )
            moved_m = haversine_meters(old["lon"], old["lat"], new["lon"], new["lat"])
            if moved_m > 5:
                station_changes.append(
                    {"change": "moved", "name": new["name"], "detail": f"移动约 {round(moved_m)} 米"}
                )
    station_changes.sort(key=lambda row: (row["change"], row["name"].casefold()))

    before_line_map = {line["id"]: line for line in before_lines}
    after_line_map = {line["id"]: line for line in after_lines}
    line_changes: list[dict] = []
    for lid in before_line_map.keys() | after_line_map.keys():
        old = before_line_map.get(lid)
        new = after_line_map.get(lid)
        if old is None:
            line_changes.append({"change": "added", "name": new["name"], "detail": f"{new['stop_count']} 站"})
            continue
        if new is None:
            line_changes.append({"change": "removed", "name": old["name"], "detail": f"{old['stop_count']} 站"})
            continue
        fields = []
        if old["color"] != new["color"]:
            fields.append("颜色变化")
        if old["code"] != new["code"]:
            fields.append(f"代码 {old['code'] or '—'} → {new['code'] or '—'}")
        old_set, new_set = set(old["stops"]), set(new["stops"])
        added_stops = [station_label(s) for s in new["stops"] if s not in old_set]
        removed_stops = [station_label(s) for s in old["stops"] if s not in new_set]
        if added_stops:
            fields.append("新增站：" + "、".join(added_stops[:6]) + ("…" if len(added_stops) > 6 else ""))
        if removed_stops:
            fields.append("移除站：" + "、".join(removed_stops[:6]) + ("…" if len(removed_stops) > 6 else ""))
        if not added_stops and not removed_stops and old["stops"] != new["stops"]:
            fields.append("站序调整")
        if fields:
            line_changes.append(
                {"change": "modified", "name": new["name"], "detail": "；".join(fields)}
            )
    line_changes.sort(key=lambda row: (row["change"], row["name"].casefold()))

    emit_progress("netdiff", 3, 3, "网络差分完成")
    return {
        "action": "network-diff",
        "before": str(args.before),
        "after": str(args.after),
        "line_change_count": len(line_changes),
        "station_change_count": len(station_changes),
        "line_changes": line_changes,
        "station_changes": station_changes,
        "before_summary": {"lines": len(before_lines), "stations": len(before_stations)},
        "after_summary": {"lines": len(after_lines), "stations": len(after_stations)},
    }


def command_compare(args: argparse.Namespace) -> dict:
    emit_progress("compare", 1, 3, "正在读取较早的导出…")
    before = scan_export(args.before)
    emit_progress("compare", 2, 3, "正在读取较新的导出…")
    after = scan_export(args.after)
    before_map = {item["name"]: item for item in before["schedules"]}
    after_map = {item["name"]: item for item in after["schedules"]}
    changes = []
    for name in sorted(before_map.keys() | after_map.keys(), key=str.casefold):
        old = before_map.get(name)
        new = after_map.get(name)
        if old is None:
            changes.append({"schedule": name, "change": "added"})
            continue
        if new is None:
            changes.append({"schedule": name, "change": "removed"})
            continue
        fields = {}
        for field in ("shift_count", "train_count", "risk_level"):
            if old[field] != new[field]:
                fields[field] = {"before": old[field], "after": new[field]}
        old_days = (old.get("service_line") or {}).get("active_days", [])
        new_days = (new.get("service_line") or {}).get("active_days", [])
        if old_days != new_days:
            fields["active_days"] = {"before": old_days, "after": new_days}
        old_phase = old.get("phase", {}).get("status")
        new_phase = new.get("phase", {}).get("status")
        if old_phase != new_phase:
            fields["phase_status"] = {"before": old_phase, "after": new_phase}
        old_runs = {line["name"]: line["run_count"] for line in old["line_details"]}
        new_runs = {line["name"]: line["run_count"] for line in new["line_details"]}
        if old_runs != new_runs:
            fields["line_run_counts"] = {"before": old_runs, "after": new_runs}
        if fields:
            changes.append({"schedule": name, "change": "modified", "fields": fields})
    emit_progress("compare", 3, 3, "对比完成")
    return {
        "action": "compare",
        "before": str(args.before),
        "after": str(args.after),
        "before_health_score": before["health_score"],
        "after_health_score": after["health_score"],
        "change_count": len(changes),
        "changes": changes,
        "new_findings": [
            finding
            for finding in after["findings"]
            if (finding["code"], finding["schedule"])
            not in {(row["code"], row["schedule"]) for row in before["findings"]}
        ],
        "resolved_findings": [
            finding
            for finding in before["findings"]
            if (finding["code"], finding["schedule"])
            not in {(row["code"], row["schedule"]) for row in after["findings"]}
        ],
    }


def command_find_reference(args: argparse.Namespace) -> dict:
    current_scan = scan_export(args.current_export)
    target_matches = [
        item
        for item in current_scan["schedules"]
        if item["name"].strip().casefold() == args.target.strip().casefold()
    ]
    if len(target_matches) != 1:
        raise RuntimeError(f"无法唯一确定当前目标表：{args.target!r}")
    target = target_matches[0]
    target_lines = set(target["lines"])
    exports = sorted(
        (
            path
            for path in args.directory.glob("*Timetable Export*.json")
            if path.resolve() != args.current_export.resolve()
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )[: args.limit]
    workers = max(1, min(args.workers, len(exports) or 1))
    results: list[dict] = []
    if workers == 1:
        for index, path in enumerate(exports, 1):
            results.append(inventory_export_worker(str(path)))
            emit_progress("reference", index, len(exports), f"正在查找历史车队 {index}/{len(exports)}")
    else:
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(inventory_export_worker, str(path)) for path in exports]
            for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
                results.append(future.result())
                emit_progress("reference", index, len(exports), f"正在查找历史车队 {index}/{len(exports)}")
    candidates = []
    for result in results:
        if not result.get("ok"):
            continue
        for source in result["sources"]:
            overlap = target_lines.intersection(source["lines"])
            score = 0
            reasons = []
            if source["name"] in target_lines:
                score += 100
                reasons.append("来源表名称与目标服务线路相同")
            if overlap:
                score += 50 + len(overlap)
                reasons.append("共同使用：" + "、".join(sorted(overlap)))
            if source["name"].casefold().replace(" daily", "") in target["name"].casefold():
                score += 20
                reasons.append("名称相近")
            if score:
                candidates.append(
                    {
                        "score": score,
                        "export": result["path"],
                        "export_modified_timestamp": result["modified_timestamp"],
                        "source": source["name"],
                        "train_count": source["train_count"],
                        "reason": "；".join(reasons),
                    }
                )
    candidates.sort(key=lambda row: (row["score"], row["export_modified_timestamp"]), reverse=True)
    if not candidates:
        raise RuntimeError("最近的历史导出中没有找到与目标模板匹配的车队")
    return {
        "action": "find-reference",
        "target": target["name"],
        "workers_used": workers,
        "best": candidates[0],
        "candidates": candidates[:20],
    }


def clone_template_shift_record(
    template_record: bytes,
    template_shift_id: str,
    new_shift_id: str,
    new_name: str,
) -> bytes:
    old_id = core.encoded_id(template_shift_id)
    if not template_record.startswith(old_id * 2):
        raise RuntimeError("template shift record ID header is invalid")
    cursor = len(old_id) * 2
    tag_count, after_tags = core.read_uvarint(template_record, cursor)
    if tag_count != 0:
        raise RuntimeError("template shift tags are not supported")
    old_name_len, old_name_start = core.read_uvarint(template_record, after_tags)
    after_name = old_name_start + old_name_len
    if template_record[after_name : after_name + 3] != b"\x01\x00\x01":
        raise RuntimeError("template shift metadata is unsupported")
    after_metadata = after_name + 3
    inner_a, after_inner_a = core.read_uvarint(template_record, after_metadata)
    inner_b, after_inner_b = core.read_uvarint(template_record, after_inner_a)
    expected_inner = (int(template_shift_id, 16) + 1) * 2
    if inner_a != inner_b or inner_a != expected_inner:
        raise RuntimeError("template shift inner IDs are invalid")

    new_id = core.encoded_id(new_shift_id)
    new_inner = core.uvarint((int(new_shift_id, 16) + 1) * 2)
    name_bytes = new_name.encode("utf-8")
    return (
        new_id
        + new_id
        + core.uvarint(0)
        + core.uvarint(len(name_bytes))
        + name_bytes
        + template_record[after_name:after_metadata]
        + new_inner
        + new_inner
        + template_record[after_inner_b:]
    )


def one_stop_line_repeat_fields(
    raw: bytes,
    objects: list[dict],
    schedule: dict,
    layout: core.ScheduleLayout,
) -> list[dict]:
    lines = {
        obj["id"]: obj for obj in objects if obj.get("class") == "Line"
    }
    used_line_ids: list[str] = []
    for shift in schedule.get("shifts") or []:
        for run in shift.get("runs") or []:
            line_id = run.get("line_id")
            if line_id and line_id not in used_line_ids:
                used_line_ids.append(line_id)
    fields = []
    for line_id in used_line_ids:
        line = lines.get(line_id)
        if not line or len(line.get("stops") or []) > 1:
            continue
        position = core.repeat_field_position(
            raw,
            line_id,
            layout.name_pos,
            layout.vector_start,
            f"{schedule['name']} / {line.get('name', line_id)}",
        )
        fields.append(
            {
                "line_id": line_id,
                "line_name": line.get("name", line_id),
                "position": position,
                "before": raw[position],
            }
        )
    return fields


def resolve_schedule_names(objects: list[dict], requested_names: list[str]) -> list[str]:
    available = {
        obj["name"]: obj for obj in objects if obj.get("class") == "Schedule"
    }
    resolved = []
    for requested in requested_names:
        if requested in available:
            resolved.append(requested)
            continue
        normalized = requested.strip().casefold()
        matches = [
            name for name in available if name.strip().casefold() == normalized
        ]
        if len(matches) != 1:
            raise RuntimeError(f"无法唯一确定时刻表：{requested!r}")
        resolved.append(matches[0])
    return resolved


def repair_depot_repeats(
    raw: bytes,
    objects: list[dict],
    schedule_names: list[str],
    severe_only: bool,
) -> tuple[bytes, dict]:
    schedules = {
        obj["name"]: obj for obj in objects if obj.get("class") == "Schedule"
    }
    line_info = {
        obj["id"]: {
            "name": obj.get("name", obj["id"]),
            "stop_count": len(obj.get("stops") or []),
        }
        for obj in objects
        if obj.get("class") == "Line"
    }
    schedule_ends, _, boundary_errors = schedule_record_boundaries(raw, objects)
    replacements: list[tuple[int, int, bytes]] = []
    changes = []
    skipped = []
    for index, schedule_name in enumerate(schedule_names, 1):
        schedule = schedules[schedule_name]
        if not (schedule.get("shifts") or []):
            skipped.append({"schedule": schedule_name, "reason": "没有班次"})
            continue
        diagnostics = schedule_export_diagnostics(schedule, line_info)
        severe_ids = {
            line["id"]
            for line in diagnostics["depot_lines"]
            if line["max_consecutive_runs"] > 3 or line["runs_per_shift"] > 21
        }
        if schedule_name in boundary_errors:
            raise RuntimeError(boundary_errors[schedule_name])
        layout = core.schedule_layout(raw, schedule, schedule_ends.get(schedule_name))
        fields = one_stop_line_repeat_fields(raw, objects, schedule, layout)
        for field in fields:
            if severe_only and field["line_id"] not in severe_ids:
                skipped.append(
                    {
                        "schedule": schedule_name,
                        "line": field["line_name"],
                        "reason": "导出数据未显示连续循环",
                    }
                )
                continue
            if field["before"] == 2:
                skipped.append(
                    {
                        "schedule": schedule_name,
                        "line": field["line_name"],
                        "reason": "已经是 x1",
                    }
                )
                continue
            replacements.append((field["position"], field["position"] + 1, b"\x02"))
            changes.append(
                {
                    "schedule": schedule_name,
                    "line": field["line_name"],
                    "before_repeat_byte": field["before"],
                    "after_repeat_byte": 2,
                }
            )
        emit_progress(
            "repair",
            10 + round(55 * index / max(1, len(schedule_names))),
            100,
            f"正在检查车库指令 {index}/{len(schedule_names)}…",
        )
    positions = [start for start, _, _ in replacements]
    if len(positions) != len(set(positions)):
        raise RuntimeError("多个修复目标指向同一存档位置，已停止以避免重复修改")
    patched = raw
    for start, end, data in sorted(replacements, reverse=True):
        patched = patched[:start] + data + patched[end:]
    for start, _, _ in replacements:
        if patched[start] != 2:
            raise RuntimeError("车库 x1 修复后的校验失败")
    return patched, {
        "action": "depot-repeat-x1",
        "severe_only": severe_only,
        "selected_schedule_count": len(schedule_names),
        "changed_count": len(changes),
        "changes": changes,
        "skipped": skipped,
        "verified": True,
    }


def migrate_schedule(
    raw: bytes,
    objects: list[dict],
    source_name: str,
    target_name: str,
    schedule_ends: dict[str, int] | None = None,
) -> tuple[bytes, dict, list[str]]:
    schedules = {
        obj["name"]: obj for obj in objects if obj.get("class") == "Schedule"
    }
    trains = {
        obj["id"]: obj.get("name", obj["id"])
        for obj in objects
        if obj.get("class") == "Train"
    }
    def resolve_name(requested: str) -> str:
        if requested in schedules:
            return requested
        normalized = requested.strip().casefold()
        matches = [name for name in schedules if name.strip().casefold() == normalized]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise RuntimeError(f"时刻表不存在于导出文件中：{requested!r}")
        raise RuntimeError(f"多个时刻表去除空格后同名，无法确定：{requested!r}")

    source_name = resolve_name(source_name)
    target_name = resolve_name(target_name)
    if source_name == target_name:
        raise RuntimeError("source and target schedules must be different")

    source = schedules[source_name]
    target = schedules[target_name]
    source_shifts = source.get("shifts") or []
    target_shifts = target.get("shifts") or []
    source_assignments = source.get("trains") or {}
    target_assignments = target.get("trains") or {}
    fleet_size = len(source_shifts)
    if fleet_size == 0 or len(source_assignments) != fleet_size:
        raise RuntimeError(
            f"{source_name} must have one assigned train per shift; "
            f"shifts={fleet_size}, trains={len(source_assignments)}"
        )
    if len(target_shifts) != 1 or target_assignments:
        raise RuntimeError(
            f"{target_name} must contain exactly one unassigned template shift"
        )

    if schedule_ends is None:
        schedule_ends, _, boundary_errors = schedule_record_boundaries(raw, objects)
        if source_name in boundary_errors:
            raise RuntimeError(boundary_errors[source_name])
        if target_name in boundary_errors:
            raise RuntimeError(boundary_errors[target_name])
    source_layout = core.schedule_layout(raw, source, schedule_ends.get(source_name))
    target_layout = core.schedule_layout(raw, target, schedule_ends.get(target_name))
    if source_layout.assignment_counts != [fleet_size] * 4:
        raise RuntimeError(
            f"invalid source assignment blocks: {source_layout.assignment_counts}"
        )
    if target_layout.assignment_counts != [0, 0, 0, 0]:
        raise RuntimeError(
            f"target template is not empty: {target_layout.assignment_counts}"
        )

    template_shift_id = target_shifts[0]["id"]
    template_record = target_layout.records[template_shift_id]
    _, _, target_group_reference = core.shift_group_span(
        template_record, template_shift_id
    )
    shift_ids = [shift["id"] for shift in source_shifts]
    shift_to_train: dict[str, str] = {}
    for train_id, assigned_shift_ids in source_assignments.items():
        if len(assigned_shift_ids) != 1:
            raise RuntimeError(f"train {trains[train_id]} has multiple shifts")
        shift_id = assigned_shift_ids[0]
        if shift_id in shift_to_train:
            raise RuntimeError(f"duplicate source shift assignment: {shift_id}")
        shift_to_train[shift_id] = train_id
    if set(shift_to_train) != set(shift_ids):
        raise RuntimeError("source train-to-shift mapping is incomplete")
    train_ids = [shift_to_train[shift_id] for shift_id in shift_ids]
    train_names = [trains[train_id] for train_id in train_ids]

    shift_objects = {shift["id"]: shift for shift in source_shifts}
    cloned_records: list[bytes] = []
    for shift_id in source_layout.record_order:
        source_shift = shift_objects[shift_id]
        cloned_records.append(
            clone_template_shift_record(
                template_record,
                template_shift_id,
                shift_id,
                source_shift.get("name") or trains[shift_to_train[shift_id]],
            )
        )

    target_vectors = (
        core.uvarint(fleet_size)
        + b"".join(cloned_records)
        + core.ordered_shift_block(target, shift_ids)
        + core.assignment_bytes(train_ids, shift_ids)
    )
    replacements = [
        (
            source_layout.vector_start,
            source_layout.after_assignments,
            b"\x00\x00\x00\x00\x00\x00",
        ),
        (
            target_layout.vector_start,
            target_layout.after_assignments,
            target_vectors,
        ),
    ]
    depot_repeat_fields = one_stop_line_repeat_fields(
        raw, objects, target, target_layout
    )
    for field in depot_repeat_fields:
        if field["before"] != 2:
            replacements.append(
                (field["position"], field["position"] + 1, b"\x02")
            )
    replacements.sort()
    for left, right in zip(replacements, replacements[1:]):
        if left[1] > right[0]:
            raise RuntimeError("source and target schedule ranges overlap")

    def mapped_position(position: int) -> int:
        return position + sum(
            len(data) - (end - start)
            for start, end, data in replacements
            if end <= position
        )

    patched = raw
    for start, end, data in reversed(replacements):
        patched = patched[:start] + data + patched[end:]

    source_vector_after = mapped_position(source_layout.vector_start)
    target_vector_after = mapped_position(target_layout.vector_start)
    if patched[source_vector_after : source_vector_after + 6] != b"\x00" * 6:
        raise RuntimeError("post-patch source schedule was not emptied")
    if patched[target_vector_after : target_vector_after + len(core.uvarint(fleet_size))] != core.uvarint(fleet_size):
        raise RuntimeError("post-patch target shift vector count is invalid")
    for field in depot_repeat_fields:
        if patched[mapped_position(field["position"])] != 2:
            raise RuntimeError(
                f"post-patch depot repeat is not x1: {field['line_name']}"
            )

    new_order = core.ordered_shift_block(target, shift_ids)
    new_order_pos = (
        target_vector_after
        + len(core.uvarint(fleet_size))
        + sum(len(record) for record in cloned_records)
    )
    if patched[new_order_pos : new_order_pos + len(new_order)] != new_order:
        raise RuntimeError("rebuilt target shift order was not found")
    assignment_counts, _ = core.parse_assignment_blocks(
        patched, new_order_pos + len(new_order)
    )
    if assignment_counts != [fleet_size] * 4:
        raise RuntimeError(f"post-patch assignments invalid: {assignment_counts}")
    for shift_id in shift_ids:
        marker = core.encoded_id(shift_id) * 2 + b"\x00"
        if patched.count(marker) != 1:
            raise RuntimeError(f"shift {shift_id} does not occur exactly once")
    if core.encoded_id(template_shift_id) * 2 + b"\x00" in patched:
        raise RuntimeError("blank target template shift remains after migration")

    headway = None
    cycle = None
    first_runs = source_shifts[0].get("runs") or [] if source_shifts else []
    if len(first_runs) >= 2:
        candidate_cycle = (
            first_runs[1]["arrival_departure"][0]
            - first_runs[0]["arrival_departure"][0]
        )
        # Only report a cycle/headway when the first two runs give a positive
        # span; a zero or negative delta (e.g. a depot leg departing at the same
        # second) would make the modulo below crash or produce nonsense.
        if candidate_cycle > 0:
            cycle = candidate_cycle
            phases = sorted(
                shift["runs"][0]["arrival_departure"][0] % cycle
                for shift in source_shifts
                if shift.get("runs")
            )
            if len(phases) >= 2:
                gaps = [right - left for left, right in zip(phases, phases[1:])]
                gaps.append(phases[0] + cycle - phases[-1])
                if len(set(gaps)) == 1:
                    headway = gaps[0]

    return patched, {
        "source_schedule": source_name,
        "target_schedule": target_name,
        "fleet_size": fleet_size,
        "source_shift_count_after": 0,
        "target_shift_count_after": fleet_size,
        "assignment_counts": assignment_counts,
        "train_names": train_names,
        "cycle_seconds": cycle,
        "uniform_headway_seconds": headway,
        "template_shift_removed": template_shift_id,
        "migration_mode": "clone-target-template",
        "source_first_shift_run_count": len(source_shifts[0].get("runs") or []),
        "target_template_run_count": len(target_shifts[0].get("runs") or []),
        "target_group_reference_hex": target_group_reference.hex(),
        "offset_recalculation_requires_game": fleet_size > 1,
        "post_load_checks": [
            "打开时刻表偏移页，确认服务分组不是全部 0:00:00",
            "确认车库指令显示 x1 而不是连续循环",
            "重新导出 JSON 并运行工具箱体检，确认七天覆盖和相位状态",
        ],
        "depot_lines_forced_to_x1": [
            field["line_name"] for field in depot_repeat_fields
        ],
        "source_empty_verified": True,
        "target_vector_verified": True,
    }, train_ids


def train_ids_for_schedules(objects: list[dict], schedule_names: list[str]) -> list[str]:
    schedules = {
        obj["name"]: obj for obj in objects if obj.get("class") == "Schedule"
    }
    known_train_ids = {
        obj["id"] for obj in objects if obj.get("class") == "Train"
    }
    train_ids: list[str] = []
    seen: set[str] = set()
    for schedule_name in schedule_names:
        if schedule_name not in schedules:
            raise RuntimeError(f"schedule not found: {schedule_name}")
        for train_id in (schedules[schedule_name].get("trains") or {}).keys():
            if train_id not in known_train_ids:
                raise RuntimeError(f"train ID missing from export: {train_id}")
            if train_id not in seen:
                train_ids.append(train_id)
                seen.add(train_id)
    if not train_ids:
        raise RuntimeError("the selected schedule has no assigned trains")
    return train_ids


def train_names_for_schedules(objects: list[dict], schedule_names: list[str]) -> list[str]:
    """Return display names while preserving duplicates from distinct train IDs."""
    names = {
        obj["id"]: obj.get("name", obj["id"])
        for obj in objects
        if obj.get("class") == "Train"
    }
    return [names[train_id] for train_id in train_ids_for_schedules(objects, schedule_names)]


def extension_record_bounds(
    raw: bytes, objects: list[dict], target_train_ids: set[str]
) -> tuple[list[dict], dict[str, int], dict[str, int]]:
    trains = [obj for obj in objects if obj.get("class") == "Train"]
    selected = [train for train in trains if train["id"] in target_train_ids]
    found_ids = {train["id"] for train in selected}
    missing_ids = sorted(target_train_ids - found_ids)
    if missing_ids:
        raise RuntimeError(f"train IDs missing from export: {missing_ids}")
    starts = {train["id"]: locate_train_record(raw, train) for train in trains}
    ordered = sorted((position, train_id) for train_id, position in starts.items())
    ends = {
        train_id: ordered[index + 1][0]
        for index, (_, train_id) in enumerate(ordered[:-1])
    }
    for train in selected:
        if train["id"] not in ends:
            raise RuntimeError(f"cannot determine record end for {train['name']}")
    return selected, starts, ends


def ensure_extensions(
    raw: bytes, objects: list[dict], target_train_ids: set[str]
) -> tuple[bytes, dict]:
    selected, starts, ends = extension_record_bounds(raw, objects, target_train_ids)
    replacements = []
    already_enabled: list[str] = []
    changed: list[str] = []
    for train in selected:
        start = starts[train["id"]]
        end = ends[train["id"]]
        record = raw[start:end]
        if record.endswith(GARAGE_JOIN_VECTOR):
            already_enabled.append(train["name"])
            continue
        if record[-1:] != b"\x00":
            raise RuntimeError(
                f"unsupported extension vector on {train['name']}: "
                f"{record[-16:].hex()}"
            )
        replacements.append((end - 1, end, GARAGE_JOIN_VECTOR))
        changed.append(train["name"])
    patched = raw
    for start, end, data in sorted(replacements, reverse=True):
        patched = patched[:start] + data + patched[end:]

    def mapped_position(position: int) -> int:
        return position + sum(
            len(data) - (end - start)
            for start, end, data in replacements
            if end <= position
        )

    for train in selected:
        record = patched[
            mapped_position(starts[train["id"]]) : mapped_position(ends[train["id"]])
        ]
        if not record.endswith(GARAGE_JOIN_VECTOR):
            raise RuntimeError(f"post-patch extension missing on {train['name']}")
    return patched, {
        "extension": "Timetable garage join",
        "action": "add",
        "target_train_count": len(selected),
        "changed_train_count": len(changed),
        "already_enabled_count": len(already_enabled),
        "changed_train_names": changed,
        "already_enabled_train_names": already_enabled,
    }


def remove_extensions(
    raw: bytes, objects: list[dict], target_train_ids: set[str]
) -> tuple[bytes, dict]:
    selected, starts, ends = extension_record_bounds(raw, objects, target_train_ids)
    replacements = []
    changed: list[str] = []
    already_disabled: list[str] = []
    for train in selected:
        start = starts[train["id"]]
        end = ends[train["id"]]
        record = raw[start:end]
        if record.endswith(GARAGE_JOIN_VECTOR):
            replacements.append((end - len(GARAGE_JOIN_VECTOR), end, b"\x00"))
            changed.append(train["name"])
        elif record[-1:] == b"\x00":
            already_disabled.append(train["name"])
        else:
            raise RuntimeError(
                f"unsupported extension vector on {train['name']}: "
                f"{record[-16:].hex()}"
            )
    patched = raw
    for start, end, data in sorted(replacements, reverse=True):
        patched = patched[:start] + data + patched[end:]

    def mapped_position(position: int) -> int:
        return position + sum(
            len(data) - (end - start)
            for start, end, data in replacements
            if end <= position
        )

    for train in selected:
        record = patched[
            mapped_position(starts[train["id"]]) : mapped_position(ends[train["id"]])
        ]
        if record.endswith(GARAGE_JOIN_VECTOR) or record[-1:] != b"\x00":
            raise RuntimeError(f"post-patch extension removal failed on {train['name']}")
    return patched, {
        "extension": "Timetable garage join",
        "action": "remove",
        "target_train_count": len(selected),
        "changed_train_count": len(changed),
        "already_disabled_count": len(already_disabled),
        "changed_train_names": changed,
        "already_disabled_train_names": already_disabled,
    }


def write_output(
    input_save: Path,
    output_save: Path,
    header: bytes,
    raw_before: bytes,
    raw_after: bytes,
    manifest: dict,
    frame_offset: int,
    level: int,
) -> dict:
    if input_save.resolve() == output_save.resolve():
        raise RuntimeError("refusing to overwrite the input save")
    if output_save.exists():
        raise RuntimeError(f"output already exists: {output_save}")
    emit_progress("write", 82, 100, "正在压缩新存档…")
    output = header + Zstd().compress(raw_after, level)
    emit_progress("write", 90, 100, "正在反向解压校验…")
    readback = Zstd().decompress(output[frame_offset:])
    if readback != raw_after:
        raise RuntimeError("compressed output failed read-back verification")
    output_save.parent.mkdir(parents=True, exist_ok=True)
    partial_save = output_save.with_name(output_save.name + ".partial")
    if partial_save.exists():
        raise RuntimeError(f"stale partial output exists: {partial_save}")
    try:
        partial_save.write_bytes(output)
        if sha256(partial_save.read_bytes()) != sha256(output):
            raise RuntimeError("temporary output file failed checksum verification")
        partial_save.replace(output_save)
    except PermissionError as exc:
        raise RuntimeError(
            "当前后台进程没有存档目录的写入权限。请关闭所有旧工具箱窗口，"
            "再从资源管理器重新双击“启动工具箱.vbs”。无法写入："
            f"{partial_save}"
        ) from exc
    finally:
        try:
            if partial_save.exists():
                partial_save.unlink()
        except PermissionError:
            pass
    result = {
        **manifest,
        "input_save": str(input_save),
        "output_save": str(output_save),
        "zstd_frame_offset": frame_offset,
        "raw_size_before": len(raw_before),
        "raw_size_after": len(raw_after),
        "raw_before_sha256": sha256(raw_before),
        "raw_after_sha256": sha256(raw_after),
        "output_file_size": len(output),
        "output_file_sha256": sha256(output),
        "compressed_readback_verified": True,
        "atomic_write_verified": True,
    }
    manifest_path = output_save.with_suffix(".manifest.json")
    partial_manifest = manifest_path.with_name(manifest_path.name + ".partial")
    partial_manifest.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    partial_manifest.replace(manifest_path)
    result["manifest_path"] = str(manifest_path)
    emit_progress("write", 100, 100, "新存档已安全写入")
    return result


def command_migrate(args: argparse.Namespace) -> dict:
    emit_progress("migrate", 2, 100, "正在读取文件…")
    objects = load_objects(args.export)
    header, frame, frame_offset = split_save(args.save)
    raw = Zstd().decompress(frame)
    preflight = validate_save_export(raw, objects)
    emit_progress("migrate", 60, 100, "正在重建目标时刻表…")
    patched, migration, train_ids = migrate_schedule(
        raw, objects, args.source, args.target
    )
    extension = None
    if args.garage_join:
        patched, extension = ensure_extensions(patched, objects, set(train_ids))
    return write_output(
        args.save,
        args.output,
        header,
        raw,
        patched,
        {"action": "migrate", "preflight": preflight, "migration": migration, "extension": extension},
        frame_offset,
        args.level,
    )


def command_batch_migrate(args: argparse.Namespace) -> dict:
    pairs = []
    used_sources: set[str] = set()
    used_targets: set[str] = set()
    for value in args.pair:
        if "::" not in value:
            raise RuntimeError(f"invalid pair: {value}")
        source, target = value.split("::", 1)
        if not source.strip() or not target.strip():
            raise RuntimeError(f"invalid pair: {value}")
        if source in used_sources:
            raise RuntimeError(f"source schedule selected more than once: {source}")
        if target in used_targets:
            raise RuntimeError(f"target template selected more than once: {target}")
        used_sources.add(source)
        used_targets.add(target)
        pairs.append((source, target))

    emit_progress("migrate", 2, 100, "正在读取文件…")
    objects = load_objects(args.export)
    header, frame, frame_offset = split_save(args.save)
    raw = Zstd().decompress(frame)
    preflight = validate_save_export(raw, objects)
    patched = raw
    migrations = []
    all_train_ids: set[str] = set()
    for index, (source, target) in enumerate(pairs, 1):
        patched, migration, train_ids = migrate_schedule(
            patched, objects, source, target
        )
        migrations.append(migration)
        all_train_ids.update(train_ids)
        emit_progress(
            "migrate",
            55 + round(25 * index / max(1, len(pairs))),
            100,
            f"已重建 {index}/{len(pairs)} 组时刻表",
        )
    extension = None
    if args.garage_join:
        patched, extension = ensure_extensions(patched, objects, all_train_ids)
    return write_output(
        args.save,
        args.output,
        header,
        raw,
        patched,
        {
            "action": "batch-migrate",
            "preflight": preflight,
            "migration_count": len(migrations),
            "migrations": migrations,
            "extension": extension,
        },
        frame_offset,
        args.level,
    )


def retire_overlapping_sources(
    raw: bytes,
    objects: list[dict],
    pairs: list[tuple[str, str]],
) -> tuple[bytes, dict]:
    schedules = {
        obj["name"]: obj for obj in objects if obj.get("class") == "Schedule"
    }
    schedule_ends, _, boundary_errors = schedule_record_boundaries(raw, objects)
    replacements: list[tuple[int, int, bytes]] = []
    retired = []
    used_sources: set[str] = set()
    for requested_source, requested_keep in pairs:
        source_name, keep_name = resolve_schedule_names(
            objects, [requested_source, requested_keep]
        )
        if source_name == keep_name:
            raise RuntimeError("旧来源表与保留表不能相同")
        if source_name in used_sources:
            raise RuntimeError(f"旧来源表重复选择：{source_name}")
        used_sources.add(source_name)
        source = schedules[source_name]
        keep = schedules[keep_name]
        if "daily" not in keep_name.casefold():
            raise RuntimeError(f"保留表不是 Daily 表：{keep_name}")
        if not source.get("shifts") or not source.get("trains"):
            raise RuntimeError(f"旧来源表已经为空：{source_name}")
        if not keep.get("shifts") or not keep.get("trains"):
            raise RuntimeError(f"保留的 Daily 表没有完整车队：{keep_name}")
        source_trains = set(source["trains"])
        keep_trains = set(keep["trains"])
        overlap = source_trains.intersection(keep_trains)
        ratio = len(overlap) / min(len(source_trains), len(keep_trains))
        source_lines = {
            run.get("line_id")
            for shift in source.get("shifts") or []
            for run in shift.get("runs") or []
            if run.get("line_id")
        }
        keep_lines = {
            run.get("line_id")
            for shift in keep.get("shifts") or []
            for run in shift.get("runs") or []
            if run.get("line_id")
        }
        if ratio < 0.8 or not source_lines.intersection(keep_lines):
            raise RuntimeError(
                f"{source_name} 与 {keep_name} 不符合高重叠旧表规则，已拒绝自动清空"
            )
        if source_name in boundary_errors:
            raise RuntimeError(boundary_errors[source_name])
        layout = core.schedule_layout(raw, source, schedule_ends.get(source_name))
        replacements.append(
            (layout.vector_start, layout.after_assignments, b"\x00" * 6)
        )
        retired.append(
            {
                "source_schedule": source_name,
                "kept_schedule": keep_name,
                "source_shift_count_before": len(source["shifts"]),
                "source_train_count_before": len(source["trains"]),
                "overlap_train_count": len(overlap),
                "overlap_ratio": round(ratio, 4),
            }
        )
    replacements.sort()
    for left, right in zip(replacements, replacements[1:]):
        if left[1] > right[0]:
            raise RuntimeError("要清空的旧来源表在存档中发生重叠")

    def mapped_position(position: int) -> int:
        return position + sum(
            len(data) - (end - start)
            for start, end, data in replacements
            if end <= position
        )

    patched = raw
    for start, end, data in reversed(replacements):
        patched = patched[:start] + data + patched[end:]
    for start, _, _ in replacements:
        mapped = mapped_position(start)
        if patched[mapped : mapped + 6] != b"\x00" * 6:
            raise RuntimeError("旧来源表清空后的校验失败")
    return patched, {
        "action": "retire-overlapping-sources",
        "retired_count": len(retired),
        "retired": retired,
        "source_empty_vectors_verified": True,
    }


def command_retire_overlaps(args: argparse.Namespace) -> dict:
    pairs = []
    for value in args.pair:
        if "::" not in value:
            raise RuntimeError(f"无效旧表配对：{value}")
        source, keep = value.split("::", 1)
        pairs.append((source, keep))
    objects = load_objects(args.export)
    header, frame, frame_offset = split_save(args.save)
    raw = Zstd().decompress(frame)
    preflight = validate_save_export(raw, objects)
    emit_progress("retire", 60, 100, "正在清空重叠的旧来源表…")
    patched, retired = retire_overlapping_sources(raw, objects, pairs)
    return write_output(
        args.save,
        args.output,
        header,
        raw,
        patched,
        {"action": "retire-overlaps", "preflight": preflight, "retired": retired},
        frame_offset,
        args.level,
    )


def clone_from_reference(
    raw: bytes,
    current_objects: list[dict],
    reference_objects: list[dict],
    reference_source_name: str,
    target_name: str,
) -> tuple[bytes, dict, list[str]]:
    current_schedules = {
        obj["name"]: obj for obj in current_objects if obj.get("class") == "Schedule"
    }
    reference_schedules = {
        obj["name"]: obj
        for obj in reference_objects
        if obj.get("class") == "Schedule"
    }

    def resolve(mapping: dict[str, dict], requested: str) -> str:
        if requested in mapping:
            return requested
        matches = [
            name
            for name in mapping
            if name.strip().casefold() == requested.strip().casefold()
        ]
        if len(matches) != 1:
            raise RuntimeError(f"无法唯一确定时刻表：{requested!r}")
        return matches[0]

    reference_source_name = resolve(reference_schedules, reference_source_name)
    target_name = resolve(current_schedules, target_name)
    source = reference_schedules[reference_source_name]
    target = current_schedules[target_name]
    source_shifts = source.get("shifts") or []
    source_assignments = source.get("trains") or {}
    target_shifts = target.get("shifts") or []
    if not source_shifts or len(source_assignments) != len(source_shifts):
        raise RuntimeError("历史来源表必须每个班次都有一列已分配列车")
    if len(target_shifts) != 1 or (target.get("trains") or {}):
        raise RuntimeError("当前目标表必须只有一个未分配模板班次")

    old_train_names = {
        obj["id"]: obj.get("name", obj["id"])
        for obj in reference_objects
        if obj.get("class") == "Train"
    }
    current_train_ids = {
        obj.get("name", obj["id"]): obj["id"]
        for obj in current_objects
        if obj.get("class") == "Train"
    }
    shift_to_old_train: dict[str, str] = {}
    for old_train_id, assigned_shift_ids in source_assignments.items():
        if len(assigned_shift_ids) != 1:
            raise RuntimeError("历史来源表含多班次列车，暂不支持")
        shift_to_old_train[assigned_shift_ids[0]] = old_train_id
    phase_shift_ids = [shift["id"] for shift in source_shifts]
    if set(phase_shift_ids) != set(shift_to_old_train):
        raise RuntimeError("历史来源表的列车与班次映射不完整")
    train_names = [old_train_names[shift_to_old_train[sid]] for sid in phase_shift_ids]
    missing = [name for name in train_names if name not in current_train_ids]
    if missing:
        raise RuntimeError("当前存档缺少历史车队列车：" + "、".join(missing))
    current_train_order = [current_train_ids[name] for name in train_names]

    for shift_id in phase_shift_ids:
        marker = core.encoded_id(shift_id) * 2 + b"\x00"
        if marker in raw:
            raise RuntimeError(f"历史班次 ID 仍在当前存档中，不能安全复用：{shift_id}")

    schedule_ends, _, boundary_errors = schedule_record_boundaries(raw, current_objects)
    if target_name in boundary_errors:
        raise RuntimeError(boundary_errors[target_name])
    target_layout = core.schedule_layout(raw, target, schedule_ends.get(target_name))
    if target_layout.assignment_counts != [0, 0, 0, 0]:
        raise RuntimeError("当前目标模板已有列车分配")
    template_shift = target_shifts[0]
    template_record = target_layout.records[template_shift["id"]]
    _, _, target_group_reference = core.shift_group_span(
        template_record, template_shift["id"]
    )
    shift_by_id = {shift["id"]: shift for shift in source_shifts}
    cloned_records = [
        clone_template_shift_record(
            template_record,
            template_shift["id"],
            shift_id,
            shift_by_id[shift_id].get("name") or train_names[index],
        )
        for index, shift_id in enumerate(phase_shift_ids)
    ]
    fleet_size = len(phase_shift_ids)
    target_vectors = (
        core.uvarint(fleet_size)
        + b"".join(cloned_records)
        + core.ordered_shift_block(target, phase_shift_ids)
        + core.assignment_bytes(current_train_order, phase_shift_ids)
    )
    depot_repeat_fields = one_stop_line_repeat_fields(
        raw, current_objects, target, target_layout
    )
    replacements = [
        (
            target_layout.vector_start,
            target_layout.after_assignments,
            target_vectors,
        )
    ]
    for field in depot_repeat_fields:
        if field["before"] != 2:
            replacements.append(
                (field["position"], field["position"] + 1, b"\x02")
            )
    replacements.sort()

    def mapped_position(position: int) -> int:
        return position + sum(
            len(data) - (end - start)
            for start, end, data in replacements
            if end <= position
        )

    patched = raw
    for start, end, data in reversed(replacements):
        patched = patched[:start] + data + patched[end:]
    target_vector_after = mapped_position(target_layout.vector_start)
    order_pos = (
        target_vector_after
        + len(core.uvarint(fleet_size))
        + sum(len(record) for record in cloned_records)
    )
    order = core.ordered_shift_block(target, phase_shift_ids)
    if patched[order_pos : order_pos + len(order)] != order:
        raise RuntimeError("恢复后的目标班次顺序校验失败")
    counts, _ = core.parse_assignment_blocks(patched, order_pos + len(order))
    if counts != [fleet_size] * 4:
        raise RuntimeError(f"恢复后的列车分配校验失败：{counts}")
    if core.encoded_id(template_shift["id"]) * 2 + b"\x00" in patched:
        raise RuntimeError("恢复后空白模板班次仍然存在")
    for field in depot_repeat_fields:
        if patched[mapped_position(field["position"])] != 2:
            raise RuntimeError(f"车库线路未成功设为 x1：{field['line_name']}")
    return patched, {
        "migration_mode": "clone-current-template-with-reference-roster",
        "reference_source_schedule": reference_source_name,
        "target_schedule": target_name,
        "fleet_size": fleet_size,
        "target_template_run_count": len(template_shift.get("runs") or []),
        "target_group_reference_hex": target_group_reference.hex(),
        "offset_recalculation_requires_game": fleet_size > 1,
        "post_load_checks": [
            "打开时刻表偏移页，确认服务分组不是全部 0:00:00",
            "确认车库指令显示 x1 而不是连续循环",
            "重新导出 JSON 并运行工具箱体检，确认七天覆盖和相位状态",
        ],
        "depot_lines_forced_to_x1": [
            field["line_name"] for field in depot_repeat_fields
        ],
        "assignment_counts": counts,
        "template_shift_removed": template_shift["id"],
        "target_vector_verified": True,
        "train_names": train_names,
    }, current_train_order


def command_recover_template(args: argparse.Namespace) -> dict:
    emit_progress("recover", 2, 100, "正在读取当前与历史导出…")
    current_objects = load_objects(args.export)
    reference_objects = load_objects(args.reference_export)
    header, frame, frame_offset = split_save(args.save)
    raw = Zstd().decompress(frame)
    preflight = validate_save_export(raw, current_objects)
    emit_progress("recover", 60, 100, "正在用当前模板重建车队…")
    patched, migration, train_ids = clone_from_reference(
        raw,
        current_objects,
        reference_objects,
        args.reference_source,
        args.target,
    )
    extension = None
    if args.garage_join:
        patched, extension = ensure_extensions(patched, current_objects, set(train_ids))
    return write_output(
        args.save,
        args.output,
        header,
        raw,
        patched,
        {"action": "recover-template", "preflight": preflight, "migration": migration, "extension": extension},
        frame_offset,
        args.level,
    )


def command_extension(args: argparse.Namespace) -> dict:
    emit_progress("extension", 2, 100, "正在读取并定位列车…")
    objects = load_objects(args.export)
    train_ids = train_ids_for_schedules(objects, args.schedule)
    header, frame, frame_offset = split_save(args.save)
    raw = Zstd().decompress(frame)
    preflight = validate_save_export(raw, objects)
    emit_progress("extension", 60, 100, "正在修改车库接班扩展…")
    if args.mode == "add":
        patched, extension = ensure_extensions(raw, objects, set(train_ids))
    else:
        patched, extension = remove_extensions(raw, objects, set(train_ids))
    return write_output(
        args.save,
        args.output,
        header,
        raw,
        patched,
        {"action": "extension", "preflight": preflight, "extension": extension},
        frame_offset,
        args.level,
    )


def command_fix_tasks(args: argparse.Namespace) -> dict:
    pair_values = list(args.pair or [])
    depot_values = list(args.depot_schedule or [])
    if not pair_values and not depot_values:
        raise RuntimeError("请至少选择一个可修复任务")
    pairs: list[tuple[str, str]] = []
    for value in pair_values:
        if "::" not in value:
            raise RuntimeError(f"无效的旧表/Daily 修复组：{value}")
        source, keep = value.split("::", 1)
        if not source.strip() or not keep.strip():
            raise RuntimeError(f"无效的旧表/Daily 修复组：{value}")
        pairs.append((source, keep))

    objects = load_objects(args.export)
    depot_names = (
        resolve_schedule_names(objects, depot_values) if depot_values else []
    )
    header, frame, frame_offset = split_save(args.save)
    emit_progress("fix", 1, 100, "正在解压并执行全量安全核对…")
    raw = Zstd().decompress(frame)
    preflight = validate_save_export(raw, objects)
    patched = raw
    retired = None
    depot = None
    if pairs:
        emit_progress("fix", 58, 100, "正在清空勾选的重叠旧表…")
        patched, retired = retire_overlapping_sources(patched, objects, pairs)
    if depot_names:
        emit_progress("fix", 70, 100, "正在把严重车库循环改为 x1…")
        patched, depot = repair_depot_repeats(
            patched, objects, depot_names, severe_only=True
        )
    emit_progress("fix", 88, 100, "正在压缩并反向校验修复存档…")
    result = write_output(
        args.save,
        args.output,
        header,
        raw,
        patched,
        {
            "action": "selected-fix-tasks",
            "preflight": preflight,
            "selected_overlap_count": len(pairs),
            "selected_depot_schedule_count": len(depot_names),
            "retired": retired,
            "depot": depot,
            "post_load_note": (
                "车库循环修复后请加载新存档，让游戏重建时刻表；"
                "随后重新导出 JSON 复检七天覆盖。"
            ),
        },
        frame_offset,
        args.level,
    )
    emit_progress("fix", 100, 100, "所选问题已写入一个新存档")
    return result


def command_repair(args: argparse.Namespace) -> dict:
    if not args.depot_x1 and not args.garage_join:
        raise RuntimeError("至少选择一种修复：车库 x1 或 Timetable garage join")
    objects = load_objects(args.export)
    schedule_names = resolve_schedule_names(objects, args.schedule)
    header, frame, frame_offset = split_save(args.save)
    emit_progress("repair", 1, 100, "正在解压存档…")
    raw = Zstd().decompress(frame)
    preflight = validate_save_export(raw, objects)
    patched = raw
    depot = None
    extension = None
    if args.depot_x1:
        patched, depot = repair_depot_repeats(
            patched, objects, schedule_names, args.severe_only
        )
    if args.garage_join:
        train_ids = train_ids_for_schedules(objects, schedule_names)
        emit_progress("repair", 72, 100, "正在核对车库接班扩展…")
        patched, extension = ensure_extensions(patched, objects, set(train_ids))
    emit_progress("repair", 88, 100, "正在压缩并反向校验新存档…")
    result = write_output(
        args.save,
        args.output,
        header,
        raw,
        patched,
        {
            "action": "safe-repair",
            "preflight": preflight,
            "schedules": schedule_names,
            "depot": depot,
            "extension": extension,
        },
        frame_offset,
        args.level,
    )
    emit_progress("repair", 100, 100, "安全修复完成")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-file", type=Path)
    parser.add_argument("--progress-file", type=Path)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan")
    scan.add_argument("--export", type=Path, required=True)
    analyze = sub.add_parser("analyze")
    analyze.add_argument("--save", type=Path, required=True)
    analyze.add_argument("--export", type=Path, required=True)
    migrate = sub.add_parser("migrate")
    migrate.add_argument("--save", type=Path, required=True)
    migrate.add_argument("--export", type=Path, required=True)
    migrate.add_argument("--source", required=True)
    migrate.add_argument("--target", required=True)
    migrate.add_argument("--output", type=Path, required=True)
    migrate.add_argument("--garage-join", action="store_true")
    migrate.add_argument("--level", type=int, default=3)
    batch = sub.add_parser("batch-migrate")
    batch.add_argument("--save", type=Path, required=True)
    batch.add_argument("--export", type=Path, required=True)
    batch.add_argument("--pair", action="append", required=True)
    batch.add_argument("--output", type=Path, required=True)
    batch.add_argument("--garage-join", action="store_true")
    batch.add_argument("--level", type=int, default=3)
    retire = sub.add_parser("retire-overlaps")
    retire.add_argument("--save", type=Path, required=True)
    retire.add_argument("--export", type=Path, required=True)
    retire.add_argument("--pair", action="append", required=True)
    retire.add_argument("--output", type=Path, required=True)
    retire.add_argument("--level", type=int, default=3)
    fix_tasks = sub.add_parser("fix-tasks")
    fix_tasks.add_argument("--save", type=Path, required=True)
    fix_tasks.add_argument("--export", type=Path, required=True)
    fix_tasks.add_argument("--pair", action="append", default=[])
    fix_tasks.add_argument("--depot-schedule", action="append", default=[])
    fix_tasks.add_argument("--output", type=Path, required=True)
    fix_tasks.add_argument("--level", type=int, default=3)
    recover = sub.add_parser("recover-template")
    recover.add_argument("--save", type=Path, required=True)
    recover.add_argument("--export", type=Path, required=True)
    recover.add_argument("--reference-export", type=Path, required=True)
    recover.add_argument("--reference-source", required=True)
    recover.add_argument("--target", required=True)
    recover.add_argument("--output", type=Path, required=True)
    recover.add_argument("--garage-join", action="store_true")
    recover.add_argument("--level", type=int, default=3)
    extension = sub.add_parser("extension")
    extension.add_argument("--save", type=Path, required=True)
    extension.add_argument("--export", type=Path, required=True)
    extension.add_argument("--schedule", action="append", required=True)
    extension.add_argument("--mode", choices=("add", "remove"), required=True)
    extension.add_argument("--output", type=Path, required=True)
    extension.add_argument("--level", type=int, default=3)
    repair = sub.add_parser("repair")
    repair.add_argument("--save", type=Path, required=True)
    repair.add_argument("--export", type=Path, required=True)
    repair.add_argument("--schedule", action="append", required=True)
    repair.add_argument("--depot-x1", action="store_true")
    repair.add_argument("--garage-join", action="store_true")
    repair.add_argument("--severe-only", action="store_true")
    repair.add_argument("--output", type=Path, required=True)
    repair.add_argument("--level", type=int, default=3)
    inventory = sub.add_parser("inventory")
    inventory.add_argument("--directory", type=Path, required=True)
    inventory.add_argument("--limit", type=int, default=12)
    compare = sub.add_parser("compare")
    compare.add_argument("--before", type=Path, required=True)
    compare.add_argument("--after", type=Path, required=True)
    map_data = sub.add_parser("map-data")
    map_data.add_argument("--export", type=Path, required=True)
    network_read = sub.add_parser("network-read")
    network_read.add_argument("--save", type=Path, required=True)
    network_read.add_argument("--no-signals", action="store_true")
    save_overview = sub.add_parser("save-overview")
    save_overview.add_argument("--save", type=Path, required=True)
    align_coords = sub.add_parser("align-coords")
    align_coords.add_argument("--save", type=Path, required=True)
    align_coords.add_argument("--output", type=Path, required=True)
    align_coords.add_argument("--update", action="append", default=[])
    network_diff = sub.add_parser("network-diff")
    network_diff.add_argument("--before", type=Path, required=True)
    network_diff.add_argument("--after", type=Path, required=True)
    reference = sub.add_parser("find-reference")
    reference.add_argument("--directory", type=Path, required=True)
    reference.add_argument("--current-export", type=Path, required=True)
    reference.add_argument("--target", required=True)
    reference.add_argument("--limit", type=int, default=15)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.workers = max(1, min(32, args.workers))
    configure_progress(args.progress_file)
    try:
        if args.command == "scan":
            result = scan_export(args.export)
        elif args.command == "analyze":
            result = analyze_save(args.save, args.export)
        elif args.command == "migrate":
            result = command_migrate(args)
        elif args.command == "batch-migrate":
            result = command_batch_migrate(args)
        elif args.command == "retire-overlaps":
            result = command_retire_overlaps(args)
        elif args.command == "fix-tasks":
            result = command_fix_tasks(args)
        elif args.command == "recover-template":
            result = command_recover_template(args)
        elif args.command == "extension":
            result = command_extension(args)
        elif args.command == "repair":
            result = command_repair(args)
        elif args.command == "inventory":
            result = command_inventory(args)
        elif args.command == "compare":
            result = command_compare(args)
        elif args.command == "map-data":
            result = command_map_data(args)
        elif args.command == "save-overview":
            result = command_save_overview(args)
        elif args.command == "network-read":
            result = command_network_read(args)
        elif args.command == "align-coords":
            result = command_align_coords(args)
        elif args.command == "network-diff":
            result = command_network_diff(args)
        else:
            result = command_find_reference(args)
        payload = {"ok": True, **result}
        if args.result_file:
            atomic_json(args.result_file, payload)
            print(json.dumps({"ok": True, "result_file": str(args.result_file)}, ensure_ascii=False))
        else:
            print(json.dumps(payload, ensure_ascii=False))
    except Exception as exc:
        payload = {"ok": False, "error": str(exc), "command": args.command}
        with contextlib.suppress(Exception):
            emit_progress("error", 100, 100, f"失败：{exc}")
        if args.result_file:
            with contextlib.suppress(Exception):
                atomic_json(args.result_file, payload)
        print(json.dumps(payload, ensure_ascii=False))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
