from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from toolkit_modcatalog import parse_mod_text  # noqa: E402


class VehicleModCatalogTests(unittest.TestCase):
    def test_repeated_compositions_and_variable_parts_are_imported(self) -> None:
        text = """[ModMeta]
schema=1
name=Catalog Test
author=Tester

[TrainUnit]
schema=2
id=head
name_en=Head
tags=control electric standard
length=20
power=1000
tex_base=missing.png

[TrainUnit]
schema=2
id=car
name_en=Car
tags=coach standard
length=20

[TrainMultipleUnit]
schema=2
id=test_mu
name_en=Test MU
tags=commuter electric standard mu
composition=short,Short,head,head flip
composition=long,Long,head,car 1 3 6,head flip
"""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "mod.txt"
            path.write_text(text, encoding="utf-8")
            result = parse_mod_text(text, path)
        self.assertEqual(len(result["units"]), 2)
        self.assertEqual(len(result["models"]), 1)
        self.assertEqual(len(result["models"][0]["compositions"]), 2)
        self.assertEqual(result["models"][0]["compositions"][1]["parts"][1]["default"], 3)
        self.assertIn("missing-texture", {item["code"] for item in result["issues"]})


if __name__ == "__main__":
    unittest.main()
