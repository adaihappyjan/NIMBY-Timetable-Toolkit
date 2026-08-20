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
VALID_GAUGE_TAGS = {"standard-gauge", "broad-gauge", "narrow-gauge", "meter-gauge"}
VALID_POWER_TAGS = {"electric", "diesel", "steam", "hydrogen", "battery", "cable"}


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


def render_top(length_m: float, width_m: float, window, door) -> bytes:
    """Non-colorizable detail layer: windows, doors and cab front."""
    c = _Canvas(TEX_W, TEX_H)
    px_len, y0, y1 = _unit_pixels(length_m, width_m)
    win_h = max(8, (y1 - y0) // 3)
    wy0 = y0 + (y1 - y0) // 4
    wy1 = wy0 + win_h
    # cab front (both ends darker)
    c.rect(2, y0 + 2, 10, y1 - 2, (40, 44, 52, 255))
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


def build_vehicle_mod_zip(options: dict) -> tuple[bytes, dict]:
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
