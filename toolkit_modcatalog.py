"""Read-only discovery and import helpers for NIMBY Rails vehicle mods."""

from __future__ import annotations

import hashlib
import re
import struct
from pathlib import Path


def _value(value: str):
    text = value.strip()
    if text.lower() in {"true", "false"}:
        return text.lower() == "true"
    try:
        return int(text)
    except ValueError:
        try:
            return float(text)
        except ValueError:
            return text


def parse_mod_text(text: str, source: Path | None = None) -> dict:
    sections: list[dict] = []
    current: dict | None = None
    for raw_line in text.lstrip("\ufeff").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        match = re.fullmatch(r"\[([^]]+)]", line)
        if match:
            current = {"section": match.group(1), "_pairs": []}
            sections.append(current)
            continue
        if current is None or "=" not in line:
            continue
        key, value = line.split("=", 1)
        current["_pairs"].append((key.strip(), value.strip()))
        if key.strip() in current:
            old = current[key.strip()]
            current[key.strip()] = old + [value.strip()] if isinstance(old, list) else [old, value.strip()]
        else:
            current[key.strip()] = value.strip()

    meta = next((item for item in sections if item["section"] == "ModMeta"), {})
    units = []
    issues = []
    texture_fields = ("tex_base", "tex_top", "tex_decors")
    for item in sections:
        if item["section"] != "TrainUnit":
            continue
        unit = {key: _value(value) for key, value in item["_pairs"] if key not in texture_fields}
        unit["tags"] = [tag for tag in re.split(r"[\s,]+", str(item.get("tags") or "")) if tag]
        unit["name_en"] = str(item.get("name_en") or item.get("id") or "Unnamed unit")
        unit["id"] = str(item.get("id") or "")
        unit["cab_ends"] = "both" if "control" in unit["tags"] or "locomotive" in unit["tags"] else "none"
        textures = []
        for field in texture_fields:
            raw = item.get(field)
            values = raw if isinstance(raw, list) else [raw]
            for group in values:
                for name in str(group or "").split(","):
                    if name.strip():
                        textures.append({"field": field, "name": name.strip()})
        unit["textures"] = textures
        if not unit["id"]:
            issues.append({"level": "error", "code": "missing-unit-id", "message": "TrainUnit 缺少 id"})
        units.append(unit)

    known_ids = {unit["id"] for unit in units}
    compositions = []
    models = []
    for item in sections:
        if item["section"] != "TrainMultipleUnit":
            continue
        model_compositions = []
        raw_compositions = [value for key, value in item["_pairs"] if key == "composition"]
        for raw in raw_compositions:
            pieces = [piece.strip() for piece in raw.split(",")]
            if len(pieces) < 3:
                issues.append({"level": "error", "code": "bad-composition", "message": f"无法解析编组：{raw}"})
                continue
            comp = {"id": pieces[0], "name": pieces[1], "parts": []}
            for token in pieces[2:]:
                words = token.split()
                if not words:
                    continue
                part: dict[str, object] = {"unit_id": words[0]}
                if len(words) == 2 and words[1].lower() == "flip":
                    part["flip"] = True
                elif len(words) == 4 and all(re.fullmatch(r"\d+", word) for word in words[1:]):
                    part.update({"min": int(words[1]), "default": int(words[2]), "max": int(words[3])})
                elif len(words) > 1:
                    issues.append({"level": "warning", "code": "unknown-composition-token", "message": f"未识别的编组参数：{token}"})
                if part["unit_id"] not in known_ids:
                    issues.append({"level": "error", "code": "unknown-unit", "message": f"编组引用不存在的车辆：{part['unit_id']}"})
                comp["parts"].append(part)
            compositions.append(comp)
            model_compositions.append(comp)
        models.append({
            "id": str(item.get("id") or ""),
            "name": str(item.get("name_en") or item.get("id") or "Unnamed model"),
            "tags": [tag for tag in re.split(r"[\s,]+", str(item.get("tags") or "")) if tag],
            "year_introduced": _value(str(item.get("year_introduced") or "0")),
            "year_retired": _value(str(item.get("year_retired") or "0")),
            "countries_operated": str(item.get("countries_operated") or ""),
            "description": str(item.get("description_en") or ""),
            "default_code": str(item.get("default_code") or ""),
            "default_name": str(item.get("default_name") or ""),
            "compositions": model_compositions,
        })

    if source:
        for unit in units:
            for texture in unit["textures"]:
                target = source.parent / texture["name"]
                texture["exists"] = target.is_file()
                if not target.is_file():
                    issues.append({"level": "warning", "code": "missing-texture", "message": f"缺少纹理：{texture['name']}"})
                elif target.suffix.lower() == ".png":
                    try:
                        with target.open("rb") as stream:
                            header = stream.read(24)
                        if header[:8] == b"\x89PNG\r\n\x1a\n":
                            width, height = struct.unpack(">II", header[16:24])
                            texture["size"] = [width, height]
                            if (width, height) != (1024, 128):
                                issues.append({"level": "warning", "code": "texture-size", "message": f"纹理尺寸不是 1024×128：{texture['name']} ({width}×{height})"})
                    except OSError:
                        pass

    return {
        "meta": {
            "name": str(meta.get("name") or (source.parent.name if source else "Unknown mod")),
            "author": str(meta.get("author") or ""),
            "version": str(meta.get("version") or ""),
            "schema": _value(str(meta.get("schema") or "0")),
        },
        "units": units,
        "models": models,
        "compositions": compositions,
        "issues": issues,
    }


def default_mod_files() -> list[tuple[str, Path]]:
    files: list[tuple[str, Path]] = []
    home = Path.home()
    private_root = home / "Saved Games" / "Weird and Wry" / "NIMBY Rails" / "mods"
    if private_root.is_dir():
        files.extend(("private", path) for path in private_root.glob("*/mod.txt"))
    for drive in "CDEFG":
        steam = Path(f"{drive}:/SteamLibrary/steamapps")
        built_in = steam / "common" / "NIMBY Rails" / "resources" / "trains" / "mod.txt"
        if built_in.is_file():
            files.append(("built-in", built_in))
        workshop = steam / "workshop" / "content" / "1134710"
        if workshop.is_dir():
            files.extend(("workshop", path) for path in workshop.glob("*/mod.txt"))
    unique: dict[str, tuple[str, Path]] = {}
    for kind, path in files:
        unique[str(path.resolve()).lower()] = (kind, path)
    return sorted(unique.values(), key=lambda item: (item[0], str(item[1]).lower()))


def _read_mod_file(path: Path) -> str:
    data = path.read_bytes()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def scan_vehicle_mods(include_definitions: bool = False) -> dict:
    mods = []
    totals = {"mods": 0, "units": 0, "models": 0, "compositions": 0, "warnings": 0, "errors": 0, "duplicate_ids": 0}
    for kind, path in default_mod_files():
        try:
            parsed = parse_mod_text(_read_mod_file(path), path)
        except OSError as exc:
            continue
        if not parsed["units"] and not parsed["models"]:
            continue
        token = hashlib.sha256(str(path.resolve()).lower().encode("utf-8")).hexdigest()[:16]
        item = {
            "token": token,
            "kind": kind,
            "path": str(path),
            "name": parsed["meta"]["name"],
            "author": parsed["meta"]["author"],
            "version": parsed["meta"]["version"],
            "unit_count": len(parsed["units"]),
            "model_count": len(parsed["models"]),
            "composition_count": len(parsed["compositions"]),
            "issues": parsed["issues"],
            "_unit_ids": [unit["id"] for unit in parsed["units"] if unit["id"]],
            "_model_ids": [model["id"] for model in parsed["models"] if model["id"]],
        }
        if include_definitions:
            item["units"] = parsed["units"]
            item["models"] = parsed["models"]
        mods.append(item)
        totals["mods"] += 1
        totals["units"] += item["unit_count"]
        totals["models"] += item["model_count"]
        totals["compositions"] += item["composition_count"]
        totals["warnings"] += sum(issue["level"] == "warning" for issue in item["issues"])
        totals["errors"] += sum(issue["level"] == "error" for issue in item["issues"])
    for field, label in (("_unit_ids", "TrainUnit"), ("_model_ids", "TrainMultipleUnit")):
        owners: dict[str, list[dict]] = {}
        for mod in mods:
            for object_id in set(mod[field]):
                owners.setdefault(object_id, []).append(mod)
        for object_id, matched in owners.items():
            if len(matched) < 2:
                continue
            totals["duplicate_ids"] += 1
            names = "、".join(str(mod["name"]) for mod in matched)
            for mod in matched:
                mod["issues"].append({
                    "level": "warning",
                    "code": "duplicate-id-global",
                    "message": f"{label} ID {object_id} 同时出现在：{names}",
                })
                totals["warnings"] += 1
    for mod in mods:
        mod.pop("_unit_ids", None)
        mod.pop("_model_ids", None)
    return {"totals": totals, "mods": mods}


def get_vehicle_mod(token: str) -> dict:
    for kind, path in default_mod_files():
        current = hashlib.sha256(str(path.resolve()).lower().encode("utf-8")).hexdigest()[:16]
        if current == token:
            parsed = parse_mod_text(_read_mod_file(path), path)
            parsed.update({"token": current, "kind": kind, "path": str(path)})
            return parsed
    raise RuntimeError("车辆模组不存在或已经移动，请重新扫描")
