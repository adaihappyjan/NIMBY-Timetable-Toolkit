from __future__ import annotations

import io
import re
import zipfile


SCRIPT_LANGUAGE = "nimbyscript.v1"
SCRIPT_API = "nimbyrails.v1"
GARAGE_JOIN_SCRIPT_ID = "stm_timetable_garage_join_1"

RULE_CATALOG = (
    {
        "id": "garage_join",
        "name": "时刻表车库接班",
        "target": "Train",
        "event": "event_train_shift_setup",
        "risk": "low",
        "description": "允许未分配列车从当前位置寻找下一班，不创建额外班次。",
    },
    {
        "id": "arrival_hold",
        "name": "到站追加停留",
        "target": "Line::Stop",
        "event": "event_line_stop",
        "risk": "low",
        "description": "到站后追加 0–3600 秒停留，不会让晚点列车提前发车。",
    },
    {
        "id": "signal_speed_limit",
        "name": "信号前分段限速",
        "target": "Signal",
        "event": "event_signal_lookahead",
        "risk": "medium",
        "description": "仅在距信号指定范围内限速，避免 15 km 前瞻范围内立即压速。",
    },
)


def safe_script_id(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip()).strip("_").lower()
    if not normalized:
        normalized = "nimby_ops_rules"
    if normalized[0].isdigit():
        normalized = "rules_" + normalized
    return normalized[:64]


def _enabled(options: dict, key: str, default: bool = False) -> bool:
    return bool(options[key]) if key in options else default


def enabled_rules(options: dict) -> list[str]:
    enabled = []
    for rule in RULE_CATALOG:
        if _enabled(options, rule["id"], rule["id"] == "garage_join"):
            enabled.append(str(rule["name"]))
    return enabled


def validate_script_source(source: str) -> dict:
    """Run conservative static checks before the game loads a generated mod."""

    errors: list[dict] = []
    warnings: list[dict] = []

    def add(target: list[dict], code: str, message: str, line: int | None = None):
        item: dict[str, object] = {"code": code, "message": message}
        if line is not None:
            item["line"] = line
        target.append(item)

    meta_matches = list(re.finditer(r"script\s+meta\s*\{(?P<body>.*?)\}", source, re.S))
    meta = meta_matches[0] if meta_matches else None
    if not meta:
        add(errors, "missing-meta", "缺少 script meta，游戏不会按 NimbyScript 模组加载。")
    else:
        body = meta.group("body")
        if f"lang: {SCRIPT_LANGUAGE}" not in body:
            add(errors, "wrong-language", f"lang 必须是 {SCRIPT_LANGUAGE}。")
        if f"api: {SCRIPT_API}" not in body:
            add(errors, "wrong-api", f"api 必须是 {SCRIPT_API}。")
        if len(meta_matches) > 1:
            add(errors, "multiple-meta", "一个源码文件只能声明一个 script meta。")

    balance = 0
    for line_no, line in enumerate(source.splitlines(), 1):
        balance += line.count("{") - line.count("}")
        if balance < 0:
            add(errors, "brace-underflow", "出现了多余的右花括号。", line_no)
            balance = 0
    if balance:
        add(errors, "brace-balance", "花括号没有闭合。")

    structs = re.findall(r"\bpub\s+struct\s+([A-Za-z_]\w*)\s+extend\s+([^\s{]+)", source)
    names = [name for name, _target in structs]
    for duplicate in sorted({name for name in names if names.count(name) > 1}):
        add(errors, "duplicate-struct", f"扩展结构 {duplicate} 重复声明。")

    callback_names = re.findall(r"\bpub\s+fn\s+([A-Za-z_]\w*)::(event_[A-Za-z_]\w*)\s*\(", source)
    for owner, event in callback_names:
        if owner not in names:
            add(errors, "unknown-callback-owner", f"回调 {owner}::{event} 没有对应的 pub struct。")

    for match in re.finditer(r"event_signal_(?:lookahead|check).*?\n\}", source, re.S):
        block = match.group(0)
        if re.search(r"\b(?:log|print)\s*\(", block):
            line_no = source[: match.start()].count("\n") + 1
            add(warnings, "hot-event-logging", "高频信号回调内含日志，可能严重拖慢模拟。", line_no)

    for match in re.finditer(r"event_signal_lookahead.*?\n\}", source, re.S):
        block = match.group(0)
        body = block.split(")", 1)[-1]
        before_speed = body.split("result.max_speed", 1)[0]
        distance_guard = re.search(
            r"\bif\b[^{}]*\btrain_distance\b\s*(?:<=|<|>=|>)", before_speed, re.S
        )
        if "result.max_speed" in body and not distance_guard:
            line_no = source[: match.start()].count("\n") + 1
            add(
                errors,
                "unbounded-lookahead-speed",
                "信号前瞻限速没有距离条件，会在完整前瞻范围内立即生效。",
                line_no,
            )

    event_counts: dict[str, int] = {}
    for _owner, event in callback_names:
        event_counts[event] = event_counts.get(event, 0) + 1
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "structs": [{"name": name, "target": target} for name, target in structs],
        "events": event_counts,
    }


def build_script_source(options: dict) -> str:
    blocks = [
        f"""script meta {{
    lang: {SCRIPT_LANGUAGE},
    api: {SCRIPT_API},
}}
"""
    ]
    if _enabled(options, "garage_join", True):
        blocks.append(
            """// Lets an unassigned train search for its next timetable shift from
// its current garage position. It does not create runs or bypass track occupancy.
pub struct TimetableGarageJoin extend Train {
    meta { label: "Timetable garage join", },
}

pub fn TimetableGarageJoin::event_train_shift_setup(
    self: &TimetableGarageJoin,
    ctx: &EventCtx,
    train: &Train,
    motion: &Motion,
    ss: &mut ShiftSetup
) {
    ss.match_pos = false;
}
"""
        )
    if _enabled(options, "arrival_hold"):
        hold_s = max(0, min(3600, int(options.get("hold_seconds", 30))))
        blocks.append(
            f"""// Adds a configurable extra hold after arrival at an extended line stop.
pub struct ArrivalHold extend Line::Stop {{
    meta {{ label: "Arrival hold", }},
    hold_s: i64 meta {{
        label: "Extra hold (seconds)",
        description: "Adds delay after arrival. It cannot make a late train depart early.",
        default: {hold_s},
        min: 0,
        max: 3600,
    }},
}}

pub fn ArrivalHold::event_line_stop(
    self: &ArrivalHold,
    ctx: &EventCtx,
    line: &Line,
    stop: &Line::Stop,
    train: &Train,
    motion: &Motion,
    ev: LineStopEvent,
    sc: &mut SimController
) {{
    if ev == LineStopEvent::Arrive {{
        sc.queue_train_stop_delay(train, self.hold_s);
    }}
}}
"""
        )
    if _enabled(options, "signal_speed_limit"):
        speed = max(1.0, min(500.0, float(options.get("speed_kmh", 40))))
        distance = max(1.0, min(15000.0, float(options.get("speed_distance_m", 800))))
        blocks.append(
            f"""// Applies a speed limit only inside the configured distance before a signal.
// max_speed in this event takes effect at the train's current position.
pub struct SignalSpeedLimit extend Signal {{
    meta {{ label: "Signal speed limit", }},
    max_speed_kmh: f64 meta {{
        label: "Maximum speed (km/h)",
        default: {speed:g},
        min: 1,
        max: 500,
    }},
    apply_distance_m: f64 meta {{
        label: "Apply inside distance (m)",
        description: "Limits speed only after the train enters this distance from the signal.",
        default: {distance:g},
        min: 1,
        max: 15000,
    }},
}}

pub fn SignalSpeedLimit::event_signal_lookahead(
    self: &SignalSpeedLimit,
    ctx: &EventCtx,
    train: &Train,
    motion: &Motion,
    signal: &Signal,
    train_distance: f64,
    check: SignalCheck,
    sc: &mut SimpleSimController,
    result: &mut SignalLookaheadResult
) {{
    if train_distance <= self.apply_distance_m {{
        result.max_speed = self.max_speed_kmh / 3.6;
    }}
}}
"""
        )
    if len(blocks) == 1:
        raise RuntimeError("请至少选择一条脚本规则")
    source = "\n".join(blocks).rstrip() + "\n"
    validation = validate_script_source(source)
    if not validation["valid"]:
        messages = "；".join(item["message"] for item in validation["errors"])
        raise RuntimeError(f"生成的脚本没有通过安全校验：{messages}")
    return source


def build_mod_zip(options: dict) -> tuple[bytes, dict]:
    display_name = str(options.get("name") or "NIMBY operations rules").strip()[:100]
    script_id = safe_script_id(str(options.get("id") or display_name))
    source_name = "Operations_Rules.nimbyscript"
    folder = script_id
    source = build_script_source(options)
    validation = validate_script_source(source)
    mod_text = f"""[ModMeta]
schema=1
name={display_name}
author=adaihappyjan / NIMBY Timetable Toolkit
desc=Generated operational extensions for NIMBY Rails.
version=2.0.0
signature=0

[Script]
id={script_id}
name={display_name}
source={source_name}
"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{folder}/mod.txt", mod_text)
        archive.writestr(f"{folder}/{source_name}", source)
        archive.writestr(
            f"{folder}/README.txt",
            "NIMBY Rails operational rules generated locally.\n\n"
            "Unzip the contained folder into Saved Games/Weird and Wry/NIMBY Rails/mods, "
            "enable it, then extend only the objects that need each rule. Keep a save backup.\n",
        )
    rules = enabled_rules(options)
    return buffer.getvalue(), {
        "script_id": script_id,
        "display_name": display_name,
        "folder": folder,
        "source": source,
        "enabled_rules": rules,
        "validation": validation,
        "rule_catalog": list(RULE_CATALOG),
        "binding": {
            "binary_write_supported": script_id == GARAGE_JOIN_SCRIPT_ID
            and _enabled(options, "garage_join", True)
            and len(rules) == 1,
            "required_script_id": GARAGE_JOIN_SCRIPT_ID,
            "reason": "存档批量绑定目前只支持已验证的车库接班扩展向量；其他规则请在游戏内绑定。",
        },
    }
