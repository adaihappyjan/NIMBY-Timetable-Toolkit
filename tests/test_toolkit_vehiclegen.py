from __future__ import annotations

import io
import struct
import sys
import unittest
import zipfile
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from toolkit_vehiclegen import (  # noqa: E402
    build_vehicle_mod_zip,
    render_base,
    safe_mod_id,
)


def _png_size(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", data[16:24])
    return width, height


class VehicleGeneratorTests(unittest.TestCase):
    def test_safe_mod_id(self) -> None:
        self.assertEqual(safe_mod_id("  CR 200J! "), "cr_200j")
        self.assertEqual(safe_mod_id("400 series"), "t_400_series")
        self.assertEqual(safe_mod_id(""), "custom_train")

    def test_png_is_valid_1024x128(self) -> None:
        png = render_base(20.0, 2.9)
        self.assertEqual(_png_size(png), (1024, 128))

    def test_no_scientific_notation_in_mod_text(self) -> None:
        _, meta = build_vehicle_mod_zip({"head_price": 2500000, "head_empty_mass": 42000})
        self.assertNotIn("e+", meta["mod_text"].lower())
        self.assertIn("price=2500000", meta["mod_text"])

    def test_zip_has_modtxt_and_textures(self) -> None:
        data, meta = build_vehicle_mod_zip(
            {
                "mod_name": "Test Pack",
                "model_name": "Test EMU",
                "model_id": "test_emu",
                "role": "metro",
                "middle_enabled": True,
                "two_cabs": True,
            }
        )
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
            mod_text = archive.read(f"{meta['folder']}/mod.txt").decode("utf-8")
        self.assertIn(f"{meta['folder']}/mod.txt", names)
        self.assertTrue(any(n.endswith("_base.png") for n in names))
        self.assertIn("[ModMeta]", mod_text)
        self.assertIn("[TrainMultipleUnit]", mod_text)
        self.assertIn("schema=2", mod_text)
        self.assertIn("composition=", mod_text)
        self.assertIn("flip", mod_text)  # two cabs -> flipped end unit

    def test_single_unit_when_middle_disabled(self) -> None:
        _, meta = build_vehicle_mod_zip({"middle_enabled": False, "two_cabs": False})
        self.assertFalse(meta["has_middle"])
        self.assertEqual(meta["units"], 1)

    def test_invalid_tags_fall_back_to_valid_defaults(self) -> None:
        _, meta = build_vehicle_mod_zip({"role": "spaceship", "gauge": "weird", "power_type": "warp"})
        self.assertIn("commuter", meta["tags"])
        self.assertIn("standard", meta["tags"])
        self.assertIn("electric", meta["tags"])

    def test_advanced_units_compositions_and_physics(self) -> None:
        _, meta = build_vehicle_mod_zip(
            {
                "model_id": "flex_train",
                "model_name": "Flex Train",
                "units": [
                    {
                        "id": "motor", "name_en": "Motor", "tags": ["control", "electric", "standard"],
                        "length": 18, "width": 2.8, "max_speed": 160, "power": 1000,
                        "empty_mass": 40000, "max_pax": 100, "max_acceleration": 1.2,
                        "max_regular_braking": 1.1, "max_emergency_braking": 1.5,
                        "max_tractive_effort": 180000, "pax_doors_per_side": 2,
                    },
                    {"id": "trailer", "name_en": "Trailer", "tags": ["coach", "standard"], "length": 20, "empty_mass": 30000, "max_pax": 150},
                ],
                "compositions": [
                    {"id": "short", "name": "Short", "parts": [{"unit_id": "motor"}, {"unit_id": "trailer", "min": 1, "default": 2, "max": 4}, {"unit_id": "motor", "flip": True}]},
                    {"id": "single", "name": "Single", "parts": [{"unit_id": "motor"}]},
                ],
            }
        )
        self.assertEqual(meta["unit_definitions"], 2)
        self.assertEqual(len(meta["compositions"]), 2)
        self.assertEqual(meta["physics"][0]["cars"], 4)
        self.assertEqual(meta["physics"][0]["power_kw"], 2000)
        self.assertIn("max_tractive_effort=180000", meta["mod_text"])
        self.assertIn("composition=short,Short,motor,trailer 1 2 4,motor flip", meta["mod_text"])


if __name__ == "__main__":
    unittest.main()
