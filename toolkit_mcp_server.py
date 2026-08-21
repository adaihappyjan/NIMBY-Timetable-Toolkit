"""Local MCP server for the NIMBY Rails Timetable Toolkit.

The server deliberately uses stdio only. Read tools can inspect saves, exports,
vehicle mods and NimbyScript. Write tools either create a ZIP or a brand-new
save beside the input; no tool can overwrite an input save.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import toolkit_scheduleconfig as scheduleconfig
from toolkit_backend import Zstd, analyze_save, split_save, write_output
from toolkit_modcatalog import get_vehicle_mod, scan_vehicle_mods
from toolkit_scriptgen import build_mod_zip, validate_script_source
from toolkit_vehiclegen import build_vehicle_mod_zip


SERVER_NAME = "nimby-rails-toolkit"
SERVER_VERSION = "1.4.0"


def order_structure_schema() -> dict:
    """Return the experimentally verified persisted Order hierarchy."""

    return {
        "status": "verified-from-controlled-saves",
        "hierarchy": {
            "schedule": {
                "has_object_id": True,
                "id_family": "0x6 Schedule",
                "children": "ten inline Order/offset groups",
            },
            "order_list_group": {
                "has_independent_object_id_observed": False,
                "identity": "Schedule id + inline group/list position and name",
                "is_stackable_order_record": False,
                "note": "No independent globally allocated ID has been observed for the list container.",
            },
            "top_level_order": {
                "has_order_id": True,
                "id_rules": "positive even value allocated by the global Order allocator",
                "counts_toward_top_level_count": True,
                "may_have_stacked_children": True,
            },
            "stacked_order": {
                "has_order_id": True,
                "id_rules": "same global allocator as a top-level Order",
                "counts_toward_top_level_count": False,
                "may_have_stacked_children": False,
            },
        },
        "binary_layout": [
            "Schedule id and fields",
            "Order-list/group name",
            "top-level Order count",
            "top-level Order record",
            "N complete stacked child records immediately following the parent",
            "next top-level Order record",
            "ten offset distribution records",
        ],
        "order_record": {
            "fields": [
                "time_seconds encoded as half-seconds ×2",
                "weekday mask ×2",
                "offset group index ×2",
                "unique positive-even Order ID",
                "Line object ID",
                "eight uvarint parameters",
            ],
            "parameters": {
                "0": "repeat",
                "1": "continue into next instruction",
                "2": "Timing event: arrive-exact/depart-exact/arrive-by",
                "3": "Enter selector",
                "4": "Exit selector",
                "5": "Timing selector",
                "6": "Timing loop bias",
                "7": "number of complete stacked child Order records that follow",
            },
        },
        "invariants": [
            "Every top-level and stacked Order has its own ID.",
            "A stacked child has parameter 7 equal to zero; nested stacks are not supported.",
            "The parent stack count changes without changing the top-level Order count.",
            "Existing Order IDs must be preserved; new records receive fresh IDs.",
        ],
    }


def _require_file(value: str, suffix: str) -> Path:
    path = Path(value).expanduser().resolve()
    if path.suffix.lower() != suffix.lower() or not path.is_file():
        raise ValueError(f"Expected an existing {suffix} file: {path}")
    return path


def _load_save(value: str) -> tuple[Path, bytes, bytes, int]:
    path = _require_file(value, ".nimbyrails5")
    header, frame, frame_offset = split_save(path)
    raw = Zstd().decompress(frame)
    return path, header, raw, frame_offset


def _new_output_path(value: str, suffix: str, *, input_path: Path | None = None) -> Path:
    path = Path(value).expanduser().resolve()
    if path.suffix.lower() != suffix.lower():
        raise ValueError(f"Output must use the {suffix} suffix")
    if path.exists():
        raise ValueError(f"Refusing to overwrite existing output: {path}")
    if input_path is not None:
        if path == input_path:
            raise ValueError("Refusing to overwrite the input save")
        if path.parent != input_path.parent:
            raise ValueError("A generated save must stay beside its input save")
    elif not path.parent.is_dir():
        raise ValueError(f"Output directory does not exist: {path.parent}")
    return path


def _write_new_file(path: Path, data: bytes) -> dict:
    partial = path.with_name(path.name + ".partial")
    if partial.exists():
        raise ValueError(f"Stale partial output exists: {partial}")
    try:
        partial.write_bytes(data)
        if partial.read_bytes() != data:
            raise RuntimeError("Temporary output failed read-back verification")
        partial.replace(path)
    finally:
        if partial.exists():
            partial.unlink()
    return {
        "output": str(path),
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "atomic_write_verified": True,
    }


def inspect_order_lists(save_path: str, schedule: str | None = None) -> dict:
    """Read persisted Order Lists, preserving parent/stacked Order identities."""

    _path, _header, raw, _offset = _load_save(save_path)
    groups = scheduleconfig.read_operating_groups(raw)
    if schedule:
        groups = [scheduleconfig.get_operating_group(raw, schedule)]
    rows = [scheduleconfig.group_to_dict(group) for group in groups if group.entries]
    return {
        "save": str(Path(save_path).expanduser().resolve()),
        "structure": order_structure_schema(),
        "group_count": len(rows),
        "top_level_order_count": sum(len(group["entries"]) for group in rows),
        "total_order_count": sum(
            1 + len(entry["stacked_entries"])
            for group in rows
            for entry in group["entries"]
        ),
        "groups": rows,
    }


def _distribution_map(updates: list[dict[str, Any]] | None) -> dict[int, dict[str, Any]]:
    mapped: dict[int, dict[str, Any]] = {}
    for raw in updates or []:
        item = dict(raw)
        if "group_index" not in item:
            raise ValueError("Each distribution update needs group_index 0–9")
        index = int(item.pop("group_index"))
        if not 0 <= index < scheduleconfig.OFFSET_GROUP_COUNT or index in mapped:
            raise ValueError("Distribution group_index must be unique and between 0 and 9")
        mapped[index] = item
    return mapped


def preview_order_plan(
    save_path: str,
    schedule: str,
    entry_plan: list[dict[str, Any]],
    distribution_updates: list[dict[str, Any]] | None = None,
) -> dict:
    """Apply a complete Order plan in memory and return the verified before/after model."""

    _path, _header, raw, _offset = _load_save(save_path)
    new_raw, before, after, fields = scheduleconfig.set_operating_group(
        raw,
        schedule,
        entry_plan=entry_plan,
        distribution_updates=_distribution_map(distribution_updates),
    )
    return {
        "writes_file": False,
        "schedule_id": before.schedule_id,
        "schedule_name": before.schedule_name,
        "fields_changed": fields,
        "raw_size_before": len(raw),
        "raw_size_after": len(new_raw),
        "before": scheduleconfig.group_to_dict(before),
        "after": scheduleconfig.group_to_dict(after),
        "structural_readback_verified": True,
    }


def write_order_plan_new_save(
    save_path: str,
    output_path: str,
    schedule: str,
    entry_plan: list[dict[str, Any]],
    distribution_updates: list[dict[str, Any]] | None = None,
) -> dict:
    """Write a verified Order plan to a NEW save beside the input save."""

    input_path, header, raw, frame_offset = _load_save(save_path)
    output = _new_output_path(output_path, ".nimbyrails5", input_path=input_path)
    new_raw, before, after, fields = scheduleconfig.set_operating_group(
        raw,
        schedule,
        entry_plan=entry_plan,
        distribution_updates=_distribution_map(distribution_updates),
    )
    manifest = {
        "action": "mcp-order-plan-write",
        "schedule_id": before.schedule_id,
        "schedule_name": before.schedule_name,
        "fields_written": fields,
        "before": scheduleconfig.group_to_dict(before),
        "after": scheduleconfig.group_to_dict(after),
        "order_identity_verified": True,
        "stack_structure_verified": True,
        "collateral_groups_changed": 0,
    }
    return write_output(
        input_path, output, header, raw, new_raw, manifest, frame_offset, 3
    )


def analyze_save_with_export(save_path: str, export_path: str) -> dict:
    """Run the existing read-only save/export health analysis."""

    save = _require_file(save_path, ".nimbyrails5")
    export = _require_file(export_path, ".json")
    return analyze_save(save, export)


def preview_script_mod(options: dict[str, Any]) -> dict:
    """Generate a NimbyScript mod in memory and return source, checks and metadata."""

    _data, meta = build_mod_zip(options)
    return meta


def write_script_mod(options: dict[str, Any], output_path: str) -> dict:
    """Generate a NimbyScript mod ZIP at a new explicit path."""

    data, meta = build_mod_zip(options)
    output = _new_output_path(output_path, ".zip")
    return {**_write_new_file(output, data), "meta": meta}


def preview_vehicle_mod(options: dict[str, Any]) -> dict:
    """Generate a vehicle mod in memory and return schema, physics and diagnostics."""

    _data, meta = build_vehicle_mod_zip(options)
    return meta


def write_vehicle_mod(options: dict[str, Any], output_path: str) -> dict:
    """Generate a vehicle mod ZIP at a new explicit path."""

    data, meta = build_vehicle_mod_zip(options)
    output = _new_output_path(output_path, ".zip")
    return {**_write_new_file(output, data), "meta": meta}


def create_mcp_server():
    """Create the official Python SDK v2 MCPServer instance."""

    try:
        from mcp.server import MCPServer
    except ImportError as exc:
        raise RuntimeError(
            "The MCP Python SDK is not installed. Run: python -m pip install -r requirements.txt"
        ) from exc

    server = MCPServer(
        name=SERVER_NAME,
        version=SERVER_VERSION,
        instructions=(
            "Local NIMBY Rails toolkit. Inspect first, preview Order plans before writing, "
            "and only use write_order_plan_new_save with a new path beside the input save."
        ),
    )

    server.tool()(order_structure_schema)
    server.tool()(inspect_order_lists)
    server.tool()(preview_order_plan)
    server.tool()(write_order_plan_new_save)
    server.tool()(analyze_save_with_export)
    server.tool()(scan_vehicle_mods)
    server.tool()(get_vehicle_mod)
    server.tool()(validate_script_source)
    server.tool()(preview_script_mod)
    server.tool()(write_script_mod)
    server.tool()(preview_vehicle_mod)
    server.tool()(write_vehicle_mod)

    @server.resource("nimby://schema/orders")
    def order_schema_resource() -> str:
        """Verified persisted Schedule/Order/stack hierarchy as JSON."""

        return json.dumps(order_structure_schema(), ensure_ascii=False, indent=2)

    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="NIMBY Rails Timetable Toolkit MCP Server")
    parser.add_argument(
        "--describe",
        action="store_true",
        help="print the verified Order schema instead of starting stdio",
    )
    args = parser.parse_args()
    if args.describe:
        print(json.dumps(order_structure_schema(), ensure_ascii=False, indent=2))
        return
    create_mcp_server().run(transport="stdio")


if __name__ == "__main__":
    main()
