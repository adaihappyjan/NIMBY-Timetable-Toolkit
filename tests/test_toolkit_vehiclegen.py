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
        self.assertIn("standard-gauge", meta["tags"])
        self.assertIn("electric", meta["tags"])


if __name__ == "__main__":
    unittest.main()
