from __future__ import annotations

import io
import re
import zipfile


def safe_script_id(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip()).strip("_").lower()
    if not normalized:
        normalized = "nimby_ops_rules"
    if normalized[0].isdigit():
        normalized = "rules_" + normalized
    return normalized[:64]


def build_script_source(options: dict) -> str:
    blocks = [
        """script meta {
    lang: nimbyscript.v1,
    api: nimbyrails.v1,
}
"""
    ]
    if options.get("garage_join", True):
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
    if options.get("arrival_hold"):
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
    if options.get("signal_speed_limit"):
        speed = max(1.0, min(500.0, float(options.get("speed_kmh", 40))))
        blocks.append(
            f"""// Applies a configurable lookahead speed limit before an extended signal.
pub struct SignalSpeedLimit extend Signal {{
    meta {{ label: "Signal speed limit", }},
    max_speed_kmh: f64 meta {{
        label: "Maximum speed (km/h)",
        default: {speed:g},
        min: 1,
        max: 500,
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
    result.max_speed = self.max_speed_kmh / 3.6;
}}
"""
        )
    if len(blocks) == 1:
        raise RuntimeError("请至少选择一条脚本规则")
    return "\n".join(blocks).rstrip() + "\n"


def build_mod_zip(options: dict) -> tuple[bytes, dict]:
    display_name = str(options.get("name") or "NIMBY operations rules").strip()[:100]
    script_id = safe_script_id(str(options.get("id") or display_name))
    source_name = "Operations_Rules.nimbyscript"
    folder = script_id
    source = build_script_source(options)
    mod_text = f"""[ModMeta]
schema=1
name={display_name}
author=Local toolbox
desc=Generated operational extensions for NIMBY Rails.
version=1.0.0
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
            "Unzip this folder into the NIMBY Rails private mods folder, then activate it in game.\n",
        )
    enabled = [
        label
        for key, label in (
            ("garage_join", "Timetable garage join"),
            ("arrival_hold", "Arrival hold"),
            ("signal_speed_limit", "Signal speed limit"),
        )
        if options.get(key)
    ]
    return buffer.getvalue(), {
        "script_id": script_id,
        "display_name": display_name,
        "folder": folder,
        "source": source,
        "enabled_rules": enabled,
    }
