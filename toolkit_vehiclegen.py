"""Generate loadable NIMBY Rails vehicle mods (mod.txt schema=2 + placeholder textures).

This module never touches the player's save files. It only produces a self
contained mod folder (returned as a zip) that the user can drop into the game's
private mods folder. Textures are generated procedurally so the mod loads and
renders immediately; the user is expected to replace them with real art later.

Format reference: NIMBY Rails "Mod development guide" (schema=2 TrainUnit /
TrainMultipleUnit sections, 1024x128 RGBA textures, 34.13 px per meter).
"""

from __future__ import annotations

import io
import re
import struct
import zlib
import zipfile

PX_PER_M = 34.13
TEX_W = 1024
TEX_H = 128

VALID_ROLE_TAGS = {
    "metro", "commuter", "intercity", "high-speed", "tram", "light-rail",
    "regional", "long-distance", "shuttle", "people-mover",
}
VALID_GAUGE_TAGS = {"minimum-gauge", "narrow", "standard", "broad", "monorail", "maglev", "tyres"}
VALID_POWER_TAGS = {"steam", "turbine", "diesel", "electric"}
VALID_CAR_TAGS = {
    "coach", "baggage", "cable-car", "end-of-train", "railbus", "locomotive",
    "tank", "tender", "generator", "brake", "autorack", "battery", "control",
}
VALID_INTERIOR_TAGS = {
    "restaurant", "bar", "lounge", "observation", "sleeper", "sitting", "standing",
    "compartments", "open-coach", "couchette", "kitchen", "vending", "toilet",
}
VALID_MISC_TAGS = {
    "linear-induction", "third-rail", "cable", "heritage", "prototype", "fantasy",
    "concept", "private", "hotel", "tilting", "mu", "push-pull",
}
VALID_TAGS = VALID_ROLE_TAGS | VALID_GAUGE_TAGS | VALID_POWER_TAGS | VALID_CAR_TAGS | VALID_INTERIOR_TAGS | VALID_MISC_TAGS

LEGACY_GAUGES = {
    "standard-gauge": "standard",
    "broad-gauge": "broad",
    "narrow-gauge": "narrow",
    "meter-gauge": "narrow",
}


def safe_mod_id(value: str, fallback: str = "custom_train") -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", (value or "").strip()).strip("_").lower()
    if not normalized:
        normalized = fallback
    if normalized[0].isdigit():
        normalized = "t_" + normalized
    return normalized[:48]


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


def _hex_to_rgb(value: str, default=(180, 180, 190)):
    value = (value or "").strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        return default
    try:
        return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# Minimal PNG writer (RGBA, 8-bit) — avoids any third party image dependency.
# ---------------------------------------------------------------------------

class _Canvas:
    def __init__(self, width: int, height: int):
        self.w = width
        self.h = height
        self.buf = bytearray(width * height * 4)  # transparent by default

    def px(self, x: int, y: int, rgba):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 4
            self.buf[i : i + 4] = bytes(rgba)

    def rect(self, x0: int, y0: int, x1: int, y1: int, rgba):
        x0, x1 = sorted((int(x0), int(x1)))
        y0, y1 = sorted((int(y0), int(y1)))
        for y in range(max(0, y0), min(self.h, y1)):
            row = (y * self.w) * 4
            for x in range(max(0, x0), min(self.w, x1)):
                i = row + x * 4
                self.buf[i : i + 4] = bytes(rgba)

    def to_png(self) -> bytes:
        def chunk(typ: bytes, data: bytes) -> bytes:
            return (
                struct.pack(">I", len(data))
                + typ
                + data
                + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)
            )

        raw = bytearray()
        stride = self.w * 4
        for y in range(self.h):
            raw.append(0)  # filter type 0 (none)
            raw.extend(self.buf[y * stride : (y + 1) * stride])
        sig = b"\x89PNG\r\n\x1a\n"
        ihdr = struct.pack(">IIBBBBB", self.w, self.h, 8, 6, 0, 0, 0)
        idat = zlib.compress(bytes(raw), 9)
        return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def _unit_pixels(length_m: float, width_m: float):
    px_len = int(_clamp(round(length_m * PX_PER_M), 12, TEX_W))
    px_wid = int(_clamp(round(width_m * PX_PER_M), 12, TEX_H))
    y0 = (TEX_H - px_wid) // 2
    return px_len, y0, y0 + px_wid


def render_base(length_m: float, width_m: float) -> bytes:
    """Grayscale body (colorizable by the player via multiply)."""
    c = _Canvas(TEX_W, TEX_H)
    px_len, y0, y1 = _unit_pixels(length_m, width_m)
    body = px_len - 2
    c.rect(1, y0, body, y1, (208, 208, 210, 255))          # body
    c.rect(1, y0, body, y0 + max(6, (y1 - y0) // 6), (150, 150, 154, 255))  # roof shade
    c.rect(1, y1 - max(6, (y1 - y0) // 7), body, y1, (96, 96, 100, 255))    # skirt
    c.rect(1, y0, body, y0 + 1, (60, 60, 64, 255))         # outline top
    c.rect(1, y1 - 1, body, y1, (60, 60, 64, 255))         # outline bottom
    return c.to_png()


def render_stripe(length_m: float, width_m: float, color) -> bytes:
    """A single colorizable decor stripe (players can tint with the line color)."""
    c = _Canvas(TEX_W, TEX_H)
    px_len, y0, y1 = _unit_pixels(length_m, width_m)
    band = max(6, (y1 - y0) // 8)
    cy = (y0 + y1) // 2
    c.rect(2, cy - band // 2, px_len - 3, cy + band // 2, (*color, 255))
    return c.to_png()


def render_top(length_m: float, width_m: float, window, door, cab_ends: str = "both") -> bytes:
    """Non-colorizable detail layer: windows, doors and cab front."""
    c = _Canvas(TEX_W, TEX_H)
    px_len, y0, y1 = _unit_pixels(length_m, width_m)
    win_h = max(8, (y1 - y0) // 3)
    wy0 = y0 + (y1 - y0) // 4
    wy1 = wy0 + win_h
    # Cab fronts are optional; intermediate coaches should not look like cabs.
    if cab_ends in {"front", "both"}:
        c.rect(2, y0 + 2, 10, y1 - 2, (40, 44, 52, 255))
    if cab_ends in {"back", "both"}:
        c.rect(px_len - 11, y0 + 2, px_len - 3, y1 - 2, (40, 44, 52, 255))
    # window strip with segmented panes
    x = 16
    seg = 0
    while x < px_len - 16:
        w = 26
        if seg % 4 == 3:  # a door every few panes
            c.rect(x, y0 + 2, x + 12, y1 - 2, (*door, 255))
            x += 18
        else:
            c.rect(x, wy0, x + w, wy1, (*window, 255))
            x += w + 6
        seg += 1
    return c.to_png()


def _fmt(value: float) -> str:
    """Plain decimal, never scientific notation (the INI parser is literal)."""
    text = f"{float(value):.4f}".rstrip("0").rstrip(".")
    return text or "0"


def _build_vehicle_mod_zip_legacy(options: dict) -> tuple[bytes, dict]:
    mod_name = str(options.get("mod_name") or options.get("model_name") or "Custom Train").strip()[:80]
    author = str(options.get("author") or "Local toolbox").strip()[:60]
    version = str(options.get("version") or "1.0.0").strip()[:20]

    model_name = str(options.get("model_name") or mod_name).strip()[:80]
    base_id = safe_mod_id(options.get("model_id") or model_name)

    role = str(options.get("role") or "commuter").strip().lower()
    if role not in VALID_ROLE_TAGS:
        role = "commuter"
    gauge = str(options.get("gauge") or "standard-gauge").strip().lower()
    if gauge not in VALID_GAUGE_TAGS:
        gauge = "standard-gauge"
    power_tag = str(options.get("power_type") or "electric").strip().lower()
    if power_tag not in VALID_POWER_TAGS:
        power_tag = "electric"

    year = int(_clamp(int(options.get("year_introduced") or 2000), 1800, 2100))
    country = re.sub(r"[^A-Za-z]", "", str(options.get("country") or "")).upper()[:2]

    body_color = _hex_to_rgb(options.get("body_color"), (170, 30, 40))
    window_color = _hex_to_rgb(options.get("window_color"), (36, 44, 60))
    door_color = _hex_to_rgb(options.get("door_color"), (60, 66, 78))

    def read_car(prefix: str, defaults: dict) -> dict:
        return {
            "length": _clamp(float(options.get(f"{prefix}_length", defaults["length"])), 1.0, 30.0),
            "width": _clamp(float(options.get(f"{prefix}_width", defaults["width"])), 1.0, 3.75),
            "max_speed": _clamp(float(options.get(f"{prefix}_max_speed", defaults["max_speed"])), 10.0, 10000.0),
            "power": _clamp(float(options.get(f"{prefix}_power", defaults["power"])), 0.0, 100000.0),
            "empty_mass": _clamp(float(options.get(f"{prefix}_empty_mass", defaults["empty_mass"])), 1000.0, 100000000.0),
            "price": _clamp(float(options.get(f"{prefix}_price", defaults["price"])), 0.0, 1000000000.0),
            "max_pax": int(_clamp(int(options.get(f"{prefix}_max_pax", defaults["max_pax"])), 0, 1000)),
            "standing_pax": int(_clamp(int(options.get(f"{prefix}_standing_pax", defaults["standing_pax"])), 0, 1000)),
            "cost_per_km_per_pax": _clamp(float(options.get(f"{prefix}_cost_km", defaults["cost_km"])), 0.0, 1000.0),
            "cost_per_day": _clamp(float(options.get(f"{prefix}_cost_day", defaults["cost_day"])), 0.0, 100000.0),
        }

    head = read_car("head", {
        "length": 20.0, "width": 2.9, "max_speed": 120.0, "power": 1200.0,
        "empty_mass": 42000.0, "price": 2500000.0, "max_pax": 180, "standing_pax": 120,
        "cost_km": 0.02, "cost_day": 400.0,
    })
    has_middle = bool(options.get("middle_enabled", True))
    middle = read_car("middle", {
        "length": 20.0, "width": 2.9, "max_speed": 120.0, "power": 0.0,
        "empty_mass": 34000.0, "price": 1800000.0, "max_pax": 220, "standing_pax": 150,
        "cost_km": 0.02, "cost_day": 300.0,
    }) if has_middle else None

    two_cabs = bool(options.get("two_cabs", True))
    mid_min = int(_clamp(int(options.get("middle_min", 1)), 0, 30))
    mid_def = int(_clamp(int(options.get("middle_def", 2)), mid_min, 30))
    mid_max = int(_clamp(int(options.get("middle_max", 6)), max(1, mid_def), 30))

    folder = base_id
    files: dict[str, bytes] = {}

    def emit_unit(unit_id: str, name: str, car: dict, unit_tags: str) -> str:
        base_png = render_base(car["length"], car["width"])
        top_png = render_top(car["length"], car["width"], window_color, door_color)
        stripe_png = render_stripe(car["length"], car["width"], body_color)
        files[f"tex/{unit_id}_base.png"] = base_png
        files[f"tex/{unit_id}_top.png"] = top_png
        files[f"tex/{unit_id}_decor.png"] = stripe_png
        lines = [
            "[TrainUnit]",
            "schema=2",
            f"id={unit_id}",
            f"name_en={name}",
            f"tags={unit_tags}",
            f"length={_fmt(car['length'])}",
            f"width={_fmt(car['width'])}",
            f"max_speed={_fmt(car['max_speed'])}",
            f"power={_fmt(car['power'])}",
            f"empty_mass={_fmt(car['empty_mass'])}",
            f"price={_fmt(car['price'])}",
            f"max_pax={car['max_pax']}",
        ]
        if car["standing_pax"] > 0:
            lines.append(f"standing_pax={car['standing_pax']}")
        lines += [
            f"cost_per_km_per_pax={_fmt(car['cost_per_km_per_pax'])}",
            f"cost_per_day={_fmt(car['cost_per_day'])}",
            f"tex_base=tex/{unit_id}_base.png",
            f"tex_top=tex/{unit_id}_top.png",
            f"tex_decors=tex/{unit_id}_decor.png",
            "tex_m_width=30",
            "tex_m_height=3.75",
            "recolor_base=true",
            "recolor_decor=true",
        ]
        return "\n".join(lines) + "\n"

    head_id = f"{base_id}_cab"
    control_tags = f"control {power_tag} {gauge}".strip()
    car_tags = f"coach {gauge}".strip()
    sections = [emit_unit(head_id, f"{model_name} cab car", head, control_tags)]

    comp_units = [head_id]
    if has_middle and middle:
        mid_id = f"{base_id}_car"
        sections.append(emit_unit(mid_id, f"{model_name} car", middle, car_tags))
        comp_units.append(f"{mid_id} {mid_min} {mid_def} {mid_max}")
    if two_cabs:
        comp_units.append(f"{head_id} flip")

    mu_tags = f"{role} {power_tag} {gauge}".strip()
    default_code = str(options.get("default_code") or "").strip()[:12]
    default_name = str(options.get("default_name") or model_name).strip()[:40]
    description = str(options.get("description") or f"{model_name} generated with the NIMBY Timetable Toolkit.").strip()[:300]

    mu_lines = [
        "[TrainMultipleUnit]",
        "schema=2",
        f"id={base_id}",
        f"name_en={model_name}",
        f"tags={mu_tags}",
        f"description_en={description}",
        f"year_introduced={year}",
    ]
    if country:
        mu_lines.append(f"countries_operated={country}")
        mu_lines.append(f"countries_built={country}")
    if default_code:
        mu_lines.append(f"default_code={default_code}")
    mu_lines.append(f"default_name={default_name}")
    comp_name = f"{model_name} ({'2+' if has_middle else ''}{'1' if not has_middle else ''})".strip()
    mu_lines.append(f"composition={base_id}_compo,{model_name},{','.join(comp_units)}")
    sections.append("\n".join(mu_lines) + "\n")

    mod_text = (
        "[ModMeta]\n"
        "schema=1\n"
        f"name={mod_name}\n"
        f"author={author}\n"
        "desc=Custom rolling stock generated by the NIMBY Timetable Toolkit.\n"
        f"version={version}\n"
        "signature=0\n\n"
        + "\n".join(sections)
    )

    files[f"{folder}/mod.txt"] = mod_text.encode("utf-8")
    for name, data in list(files.items()):
        if not name.startswith(folder + "/"):
            files[f"{folder}/{name}"] = data
            del files[name]
    files[f"{folder}/README.txt"] = (
        "Custom train mod generated locally.\n\n"
        "1) Copy this folder into your NIMBY Rails private mods folder\n"
        "   (Saved Games/Weird and Wry/NIMBY Rails/mods).\n"
        "2) Enable the mod in the game main menu.\n"
        "3) The textures (tex/*.png) are placeholders — replace them with your\n"
        "   own 1024x128 RGBA art (34.13 px per meter) any time.\n"
    ).encode("utf-8")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)

    meta = {
        "mod_id": base_id,
        "mod_name": mod_name,
        "model_name": model_name,
        "folder": folder,
        "units": len(comp_units),
        "has_middle": has_middle,
        "two_cabs": two_cabs,
        "tags": mu_tags,
        "composition": ",".join(comp_units),
        "mod_text": mod_text,
    }
    return buffer.getvalue(), meta


# ---------------------------------------------------------------------------
# Schema-driven generator. The legacy builder above is intentionally retained
# as a readable migration reference; this implementation accepts both the old
# two-car form and the new arbitrary units/compositions form.
# ---------------------------------------------------------------------------

TRAIN_UNIT_FIELDS = (
    "year_introduced", "year_retired", "length", "width",
    "max_speed", "max_acceleration", "max_regular_braking", "max_emergency_braking",
    "max_tractive_effort", "power", "empty_mass", "price", "max_pax", "standing_pax",
    "pax_doors_per_side", "allow_player_composition", "cost_per_km",
    "cost_per_km_per_pax", "cost_per_day", "tex_m_width", "tex_m_height",
    "recolor_base", "recolor_decor", "front_coupler", "front_coupler_mandatory",
    "back_coupler", "back_coupler_mandatory",
)


def _number(value, default: float, lo: float, hi: float) -> float:
    try:
        return float(_clamp(float(value), lo, hi))
    except (TypeError, ValueError):
        return float(default)


def _integer(value, default: int, lo: int, hi: int) -> int:
    try:
        return int(_clamp(int(value), lo, hi))
    except (TypeError, ValueError):
        return default


def _boolean(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _tags(value, fallback: list[str]) -> tuple[list[str], list[str]]:
    raw = value if isinstance(value, list) else re.split(r"[\s,]+", str(value or ""))
    tags: list[str] = []
    custom: list[str] = []
    for item in raw:
        tag = str(item).strip().lower()
        if not tag or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", tag):
            continue
        if tag not in tags:
            tags.append(tag)
            if tag not in VALID_TAGS:
                custom.append(tag)
    return (tags or fallback), custom


def _legacy_vehicle_spec(options: dict, base_id: str, model_name: str) -> tuple[list[dict], list[dict]]:
    gauge = LEGACY_GAUGES.get(str(options.get("gauge") or "standard").lower(), str(options.get("gauge") or "standard").lower())
    if gauge not in VALID_GAUGE_TAGS:
        gauge = "standard"
    power_tag = str(options.get("power_type") or "electric").lower()
    if power_tag not in VALID_POWER_TAGS:
        power_tag = "electric"

    def car(prefix: str, defaults: dict, kind: str) -> dict:
        return {
            "id": f"{base_id}_{'cab' if prefix == 'head' else 'car'}",
            "name_en": f"{model_name} {'cab car' if prefix == 'head' else 'car'}",
            "category": model_name,
            "tags": [kind, "sitting", gauge] + ([power_tag] if _number(options.get(f"{prefix}_power"), defaults["power"], 0, 100000) > 0 else []),
            "length": options.get(f"{prefix}_length", defaults["length"]),
            "width": options.get(f"{prefix}_width", defaults["width"]),
            "max_speed": options.get(f"{prefix}_max_speed", defaults["max_speed"]),
            "max_acceleration": options.get(f"{prefix}_max_acceleration", 1.0),
            "max_regular_braking": options.get(f"{prefix}_max_regular_braking", 1.0),
            "max_emergency_braking": options.get(f"{prefix}_max_emergency_braking", 1.4),
            "max_tractive_effort": options.get(f"{prefix}_max_tractive_effort", 0),
            "power": options.get(f"{prefix}_power", defaults["power"]),
            "empty_mass": options.get(f"{prefix}_empty_mass", defaults["empty_mass"]),
            "price": options.get(f"{prefix}_price", defaults["price"]),
            "max_pax": options.get(f"{prefix}_max_pax", defaults["max_pax"]),
            "standing_pax": options.get(f"{prefix}_standing_pax", defaults["standing_pax"]),
            "pax_doors_per_side": options.get(f"{prefix}_doors", 2),
            "allow_player_composition": True,
            "cost_per_km": options.get(f"{prefix}_cost_per_km", 0),
            "cost_per_km_per_pax": options.get(f"{prefix}_cost_km", defaults["cost_km"]),
            "cost_per_day": options.get(f"{prefix}_cost_day", defaults["cost_day"]),
            "cab_ends": "both" if prefix == "head" else "none",
        }

    head = car("head", {
        "length": 20, "width": 2.9, "max_speed": 120, "power": 1200,
        "empty_mass": 42000, "price": 2500000, "max_pax": 180,
        "standing_pax": 120, "cost_km": 0.02, "cost_day": 400,
    }, "control")
    units = [head]
    parts = [{"unit_id": head["id"]}]
    if _boolean(options.get("middle_enabled"), True):
        middle = car("middle", {
            "length": 20, "width": 2.9, "max_speed": 120, "power": 0,
            "empty_mass": 34000, "price": 1800000, "max_pax": 220,
            "standing_pax": 150, "cost_km": 0.02, "cost_day": 300,
        }, "coach")
        units.append(middle)
        minimum = _integer(options.get("middle_min"), 1, 0, 30)
        default = _integer(options.get("middle_def"), 2, minimum, 30)
        maximum = _integer(options.get("middle_max"), 6, default, 30)
        parts.append({"unit_id": middle["id"], "min": minimum, "default": default, "max": maximum})
    if _boolean(options.get("two_cabs"), True):
        parts.append({"unit_id": head["id"], "flip": True})
    return units, [{"id": f"{base_id}_compo", "name": model_name, "parts": parts}]


def _normalize_unit(raw: dict, fallback_id: str, fallback_name: str) -> tuple[dict, list[str]]:
    unit_id = safe_mod_id(str(raw.get("id") or fallback_id), fallback_id)
    tags, custom = _tags(raw.get("tags"), ["coach", "standard"])
    unit = {
        "id": unit_id,
        "name_en": str(raw.get("name_en") or raw.get("name") or fallback_name).strip()[:100],
        "name_loc": str(raw.get("name_loc") or "").strip()[:100],
        "category": str(raw.get("category") or "").strip()[:80],
        "description": str(raw.get("description") or "").replace("\n", " ").strip()[:300],
        "tags": tags,
        "year_introduced": _integer(raw.get("year_introduced"), 0, 0, 9999),
        "year_retired": _integer(raw.get("year_retired"), 0, 0, 9999),
        "length": _number(raw.get("length"), 20, 1, 30),
        "width": _number(raw.get("width"), 2.9, 1, 3.75),
        "max_speed": _number(raw.get("max_speed"), 120, 1, 10000),
        "max_acceleration": _number(raw.get("max_acceleration"), 1, 0.01, 20),
        "max_regular_braking": _number(raw.get("max_regular_braking"), 1, 0.01, 20),
        "max_emergency_braking": _number(raw.get("max_emergency_braking"), 1.4, 0.01, 30),
        "max_tractive_effort": _number(raw.get("max_tractive_effort"), 0, 0, 100000000),
        "power": _number(raw.get("power"), 0, 0, 100000),
        "empty_mass": _number(raw.get("empty_mass"), 40000, 1000, 100000000),
        "price": _number(raw.get("price"), 0, 0, 1000000000),
        "max_pax": _integer(raw.get("max_pax"), 0, 0, 10000),
        "standing_pax": _integer(raw.get("standing_pax"), 0, 0, 10000),
        "pax_doors_per_side": _integer(raw.get("pax_doors_per_side"), 0, 0, 100),
        "allow_player_composition": _boolean(raw.get("allow_player_composition"), True),
        "cost_per_km": _number(raw.get("cost_per_km"), 0, 0, 1000000),
        "cost_per_km_per_pax": _number(raw.get("cost_per_km_per_pax"), 0, 0, 1000),
        "cost_per_day": _number(raw.get("cost_per_day"), 0, 0, 10000000),
        "tex_m_width": _number(raw.get("tex_m_width"), 30, 1, 100),
        "tex_m_height": _number(raw.get("tex_m_height"), 3.75, 1, 20),
        "recolor_base": _boolean(raw.get("recolor_base"), True),
        "recolor_decor": _boolean(raw.get("recolor_decor"), True),
        "front_coupler": _boolean(raw.get("front_coupler"), True),
        "front_coupler_mandatory": _boolean(raw.get("front_coupler_mandatory"), False),
        "back_coupler": _boolean(raw.get("back_coupler"), True),
        "back_coupler_mandatory": _boolean(raw.get("back_coupler_mandatory"), False),
        "cab_ends": str(raw.get("cab_ends") or ("both" if "control" in tags else "none")),
    }
    return unit, custom


def _normalize_compositions(raw_compositions, units: list[dict], base_id: str, model_name: str) -> tuple[list[dict], list[dict]]:
    known = {unit["id"] for unit in units}
    result: list[dict] = []
    issues: list[dict] = []
    for index, raw in enumerate(raw_compositions if isinstance(raw_compositions, list) else []):
        if not isinstance(raw, dict):
            continue
        parts = []
        for part_index, source in enumerate(raw.get("parts") or []):
            if isinstance(source, str):
                source = {"unit_id": source}
            if not isinstance(source, dict):
                continue
            unit_id = safe_mod_id(str(source.get("unit_id") or source.get("id") or ""), "missing_unit")
            if unit_id not in known:
                issues.append({"level": "error", "code": "unknown-unit", "message": f"编组 {index + 1} 第 {part_index + 1} 项引用了不存在的车辆 {unit_id}"})
                continue
            flip = _boolean(source.get("flip"), False)
            item: dict[str, object] = {"unit_id": unit_id}
            if flip:
                item["flip"] = True
            elif any(key in source for key in ("min", "default", "max")):
                minimum = _integer(source.get("min"), 1, 0, 99)
                default = _integer(source.get("default"), minimum, minimum, 99)
                maximum = _integer(source.get("max"), default, default, 99)
                item.update({"min": minimum, "default": default, "max": maximum})
            parts.append(item)
        if parts:
            result.append({
                "id": safe_mod_id(str(raw.get("id") or f"{base_id}_compo_{index + 1}")),
                "name": str(raw.get("name") or f"{model_name} {index + 1}").replace(",", " ").strip()[:100],
                "parts": parts,
            })
    if not result and units:
        result = [{"id": f"{base_id}_compo", "name": model_name, "parts": [{"unit_id": units[0]["id"]}]}]
    return result, issues


def composition_physics(units: list[dict], composition: dict, passenger_mass_kg: float = 75) -> dict:
    by_id = {unit["id"]: unit for unit in units}
    expanded: list[dict] = []
    for part in composition.get("parts", []):
        unit = by_id.get(part.get("unit_id"))
        if not unit:
            continue
        count = int(part.get("default", 1))
        expanded.extend([unit] * max(0, count))
    if not expanded:
        return {"cars": 0}
    mass_empty = sum(float(unit["empty_mass"]) for unit in expanded)
    pax = sum(int(unit["max_pax"]) for unit in expanded)
    loaded_mass = mass_empty + pax * max(0, passenger_mass_kg)
    power_kw = sum(float(unit["power"]) for unit in expanded)
    max_te = sum(float(unit["max_tractive_effort"]) for unit in expanded if float(unit["power"]) > 0)
    accel_cap = min(float(unit["max_acceleration"]) for unit in expanded)

    def accel_at(speed_kmh: float) -> float:
        speed_ms = max(speed_kmh / 3.6, 0.1)
        power_force = 0.75 * power_kw * 1000 / speed_ms
        effort = min(power_force, max_te) if max_te > 0 else power_force
        return min(effort / loaded_mass if loaded_mass else 0, accel_cap)

    return {
        "cars": len(expanded),
        "length_m": round(sum(float(unit["length"]) for unit in expanded), 3),
        "empty_mass_kg": round(mass_empty, 1),
        "loaded_mass_kg": round(loaded_mass, 1),
        "max_pax": pax,
        "standing_pax": sum(int(unit["standing_pax"]) for unit in expanded),
        "power_kw": round(power_kw, 3),
        "max_tractive_effort_n": round(max_te, 3),
        "max_speed_kmh": min(float(unit["max_speed"]) for unit in expanded),
        "max_acceleration_mps2": accel_cap,
        "regular_braking_mps2": min(float(unit["max_regular_braking"]) for unit in expanded),
        "price": round(sum(float(unit["price"]) for unit in expanded), 2),
        "acceleration_curve": [
            {"speed_kmh": speed, "acceleration_mps2": round(accel_at(speed), 4)}
            for speed in (5, 20, 40, 80, 120, 160, 240, 320)
            if speed <= min(float(unit["max_speed"]) for unit in expanded)
        ],
    }


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def build_vehicle_mod_zip(options: dict) -> tuple[bytes, dict]:
    mod_name = str(options.get("mod_name") or options.get("model_name") or "Custom Train").strip()[:80]
    model_name = str(options.get("model_name") or mod_name).strip()[:80]
    base_id = safe_mod_id(str(options.get("model_id") or model_name))
    author = str(options.get("author") or "adaihappyjan / NIMBY Timetable Toolkit").replace("\n", " ").strip()[:80]
    version = str(options.get("version") or "1.0.0").strip()[:20]
    issues: list[dict] = []

    raw_units = options.get("units")
    if isinstance(raw_units, list) and raw_units:
        source_units = raw_units
        raw_compositions = options.get("compositions")
    else:
        source_units, raw_compositions = _legacy_vehicle_spec(options, base_id, model_name)

    units: list[dict] = []
    for index, raw in enumerate(source_units):
        if not isinstance(raw, dict):
            continue
        unit, custom_tags = _normalize_unit(raw, f"{base_id}_unit_{index + 1}", f"{model_name} unit {index + 1}")
        if unit["id"] in {item["id"] for item in units}:
            issues.append({"level": "error", "code": "duplicate-unit-id", "message": f"车辆 ID 重复：{unit['id']}"})
            continue
        for tag in custom_tags:
            issues.append({"level": "warning", "code": "custom-tag", "message": f"{unit['id']} 使用非官方推荐标签：{tag}"})
        if unit["standing_pax"] > unit["max_pax"]:
            issues.append({"level": "warning", "code": "standing-over-capacity", "message": f"{unit['id']} 的站席数大于总容量"})
        units.append(unit)
    if not units:
        raise RuntimeError("至少需要一个有效的 TrainUnit")

    compositions, comp_issues = _normalize_compositions(raw_compositions, units, base_id, model_name)
    issues.extend(comp_issues)
    errors = [item for item in issues if item["level"] == "error"]
    if errors:
        raise RuntimeError("；".join(str(item["message"]) for item in errors))

    body_color = _hex_to_rgb(options.get("body_color"), (170, 30, 40))
    window_color = _hex_to_rgb(options.get("window_color"), (36, 44, 60))
    door_color = _hex_to_rgb(options.get("door_color"), (60, 66, 78))
    files: dict[str, bytes] = {}
    sections: list[str] = []
    bool_fields = {
        "allow_player_composition", "recolor_base", "recolor_decor", "front_coupler",
        "front_coupler_mandatory", "back_coupler", "back_coupler_mandatory",
    }
    int_fields = {"year_introduced", "year_retired", "max_pax", "standing_pax", "pax_doors_per_side"}

    for unit in units:
        uid = unit["id"]
        files[f"tex/{uid}_base.png"] = render_base(unit["length"], unit["width"])
        files[f"tex/{uid}_top.png"] = render_top(unit["length"], unit["width"], window_color, door_color, unit["cab_ends"])
        files[f"tex/{uid}_decor.png"] = render_stripe(unit["length"], unit["width"], body_color)
        lines = ["[TrainUnit]", "schema=2", f"id={uid}"]
        if unit["name_loc"]:
            lines.append(f"name_loc={unit['name_loc']}")
        lines += [f"name_en={unit['name_en']}"]
        if unit["category"]:
            lines.append(f"category={unit['category']}")
        if unit["description"]:
            lines.append(f"description={unit['description']}")
        lines.append(f"tags={' '.join(unit['tags'])}")
        for field in TRAIN_UNIT_FIELDS:
            value = unit[field]
            if field in {"year_introduced", "year_retired"} and not value:
                continue
            if field in bool_fields:
                lines.append(f"{field}={_bool_text(bool(value))}")
            elif field in int_fields:
                lines.append(f"{field}={int(value)}")
            else:
                lines.append(f"{field}={_fmt(value)}")
        lines += [
            f"tex_base=tex/{uid}_base.png",
            f"tex_top=tex/{uid}_top.png",
            f"tex_decors=tex/{uid}_decor.png",
        ]
        sections.append("\n".join(lines) + "\n")

    role = str(options.get("role") or "commuter").strip().lower()
    if role not in VALID_ROLE_TAGS:
        role = "commuter"
    gauge = LEGACY_GAUGES.get(str(options.get("gauge") or "standard").lower(), str(options.get("gauge") or "standard").lower())
    if gauge not in VALID_GAUGE_TAGS:
        gauge = "standard"
    power = str(options.get("power_type") or "electric").lower()
    if power not in VALID_POWER_TAGS:
        power = "electric"
    mu_tags, custom_mu_tags = _tags(options.get("tags"), [role, power, gauge, "mu"])
    for tag in custom_mu_tags:
        issues.append({"level": "warning", "code": "custom-tag", "message": f"车型使用非官方推荐标签：{tag}"})
    country = re.sub(r"[^A-Za-z,]", "", str(options.get("country") or "")).lower()[:80]
    year = _integer(options.get("year_introduced"), 2000, 0, 9999)
    retired = _integer(options.get("year_retired"), 0, 0, 9999)
    description = str(options.get("description") or f"{model_name} generated with the NIMBY Timetable Toolkit.").replace("\n", " ").strip()[:500]
    mu_lines = [
        "[TrainMultipleUnit]", "schema=2", f"id={base_id}", f"name_en={model_name}",
        f"tags={' '.join(mu_tags)}", f"description_en={description}", f"year_introduced={year}",
    ]
    if retired:
        mu_lines.append(f"year_retired={retired}")
    if country:
        mu_lines += [f"countries_operated={country}", f"countries_built={country}"]
    photo = str(options.get("photo") or "").strip()
    if photo:
        mu_lines.append(f"photo={photo}")
    default_code = str(options.get("default_code") or "").strip()[:40]
    default_name = str(options.get("default_name") or model_name).strip()[:80]
    if default_code:
        mu_lines.append(f"default_code={default_code}")
    mu_lines.append(f"default_name={default_name}")
    for composition in compositions:
        tokens = []
        for part in composition["parts"]:
            token = str(part["unit_id"])
            if part.get("flip"):
                token += " flip"
            elif "default" in part:
                token += f" {part['min']} {part['default']} {part['max']}"
            tokens.append(token)
        mu_lines.append(f"composition={composition['id']},{composition['name']},{','.join(tokens)}")
    sections.append("\n".join(mu_lines) + "\n")

    mod_text = (
        "[ModMeta]\n"
        "schema=1\n"
        f"name={mod_name}\n"
        f"author={author}\n"
        "desc=Custom rolling stock generated by the NIMBY Timetable Toolkit.\n"
        f"version={version}\n"
        "signature=0\n\n"
        + "\n".join(sections)
    )
    folder = base_id
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{folder}/mod.txt", mod_text)
        for name, data in files.items():
            archive.writestr(f"{folder}/{name}", data)
        archive.writestr(
            f"{folder}/README.txt",
            "Vehicle mod generated locally. Copy this folder into the NIMBY Rails private mods folder.\n"
            "Textures are 1024x128 RGBA placeholders at 34.13 pixels per meter.\n",
        )

    physics = [
        {"id": comp["id"], "name": comp["name"], **composition_physics(units, comp)}
        for comp in compositions
    ]
    return buffer.getvalue(), {
        "mod_id": base_id,
        "mod_name": mod_name,
        "model_name": model_name,
        "folder": folder,
        "unit_definitions": len(units),
        "units": sum(item.get("cars", 0) for item in physics[:1]),
        "has_middle": len(units) > 1,
        "two_cabs": any(part.get("flip") for comp in compositions for part in comp["parts"]),
        "tags": " ".join(mu_tags),
        "composition": "; ".join(comp["name"] for comp in compositions),
        "compositions": compositions,
        "normalized_units": units,
        "physics": physics,
        "issues": issues,
        "mod_text": mod_text,
    }
