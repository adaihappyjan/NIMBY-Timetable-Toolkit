import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import toolkit_webapp as t  # noqa: E402


class SaveDirTests(unittest.TestCase):
    def setUp(self):
        self._orig_save = t.SAVE_DIR
        self._orig_settings_file = t.SETTINGS_FILE
        self._orig_settings_dir = t.SETTINGS_DIR
        self._orig_env = os.environ.get("NIMBY_SAVE_DIR")
        os.environ.pop("NIMBY_SAVE_DIR", None)

    def tearDown(self):
        t.SAVE_DIR = self._orig_save
        t.SETTINGS_FILE = self._orig_settings_file
        t.SETTINGS_DIR = self._orig_settings_dir
        if self._orig_env is None:
            os.environ.pop("NIMBY_SAVE_DIR", None)
        else:
            os.environ["NIMBY_SAVE_DIR"] = self._orig_env

    def _isolate_settings(self, tmp: Path):
        t.SETTINGS_DIR = tmp
        t.SETTINGS_FILE = tmp / "settings.json"

    def test_candidates_are_deduped_and_nonempty(self):
        cands = t.candidate_save_dirs()
        self.assertTrue(cands)
        self.assertEqual(len(cands), len({str(c) for c in cands}))

    def test_dir_has_saves(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)
            self.assertFalse(t._dir_has_saves(path))
            (path / "City.nimbyrails5").write_text("x", encoding="utf-8")
            self.assertTrue(t._dir_has_saves(path))

    def test_set_save_dir_persists_and_switches(self):
        import tempfile
        with tempfile.TemporaryDirectory() as settings, tempfile.TemporaryDirectory() as saves:
            self._isolate_settings(Path(settings))
            (Path(saves) / "A.nimbyrails5").write_text("x", encoding="utf-8")
            info = t.set_save_dir(saves)
            self.assertEqual(Path(info["save_dir"]), Path(saves).resolve())
            self.assertTrue(info["has_saves"])
            self.assertEqual(t.read_settings()["save_dir"], str(Path(saves).resolve()))

    def test_set_save_dir_rejects_missing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as settings:
            self._isolate_settings(Path(settings))
            with self.assertRaises(RuntimeError):
                t.set_save_dir(str(Path(settings) / "nope"))

    def test_env_var_takes_precedence(self):
        import tempfile
        with tempfile.TemporaryDirectory() as settings, tempfile.TemporaryDirectory() as envdir:
            self._isolate_settings(Path(settings))
            t.write_settings({"save_dir": settings})
            os.environ["NIMBY_SAVE_DIR"] = envdir
            self.assertEqual(t.resolve_save_dir(), Path(envdir))

    def test_env_lock_blocks_set(self):
        import tempfile
        with tempfile.TemporaryDirectory() as settings, tempfile.TemporaryDirectory() as saves:
            self._isolate_settings(Path(settings))
            os.environ["NIMBY_SAVE_DIR"] = saves
            with self.assertRaises(RuntimeError):
                t.set_save_dir(saves)


if __name__ == "__main__":
    unittest.main()
