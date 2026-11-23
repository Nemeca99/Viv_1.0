import os
import tempfile
import json
from pathlib import Path
import unittest
from privacy_core import PrivacyCore


class TestPrivacyCore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_file = Path(self.temp_dir) / "config" / "privacy_settings.json"
        os.makedirs(Path(self.config_file).parent, exist_ok=True)

    def test_init_and_config_load(self):
        pc = PrivacyCore()
        self.assertIsNotNone(pc.config)
        self.assertIn("mode", pc.config)
        self.assertEqual(pc.config["mode"], "semi-auto")

    def test_save_config(self):
        pc = PrivacyCore()
        original_mode = pc.config.get("mode")
        pc.config["mode"] = "full-auto"
        pc._save_config()
        with open(pc.config_file, 'r') as f:
            saved = json.load(f)
        self.assertEqual(saved["mode"], "full-auto")

    def test_get_mode(self):
        pc = PrivacyCore()
        mode = pc.get_mode()
        self.assertIn(mode, ["semi-auto", "full-auto"])

    def test_set_semi_auto(self):
        pc = PrivacyCore()
        initial_mode = pc.get_mode()
        pc.set_semi_auto()
        self.assertEqual(pc.get_mode(), "semi-auto")

    def test_set_full_auto(self):
        pc = PrivacyCore()
        pc.set_full_auto()
        self.assertEqual(pc.get_mode(), "full-auto")

    def test_enable_full_auto(self):
        pc = PrivacyCore()
        pc.enable_full_auto(confirmed=True)
        self.assertEqual(pc.get_mode(), "full-auto")

    def test_authorize_file_write_allowed(self):
        allowed_dir = Path(self.temp_dir) / "allowed"
        os.makedirs(allowed_dir, exist_ok=True)
        pc = PrivacyCore()
        result = pc.authorize_file_write(str(allowed_dir / "test.txt"))
        self.assertTrue(result["allowed"])

    def test_authorize_file_write_blocked_extension(self):
        pc = PrivacyCore()
        result = pc.authorize_file_write("/tmp/test.exe")
        self.assertFalse(result["allowed"])
        self.assertIn("extension", result["reason"].lower())

    def test_authorize_file_write_path_traversal(self):
        pc = PrivacyCore()
        result = pc.authorize_file_write("/etc/passwd")
        self.assertFalse(result["allowed"])

    def test_write_text_allowed(self):
        pc = PrivacyCore()
        allowed_dir = Path(self.temp_dir) / "write"
        os.makedirs(allowed_dir, exist_ok=True)
        result = pc.authorize_file_write(str(allowed_dir))
        if result["allowed"]:
            pc.write_text(str(allowed_dir / "test.txt"), "Hello World")
            self.assertTrue(Path(allowed_dir / "test.txt").exists())

    def test_get_status(self):
        pc = PrivacyCore()
        status = pc.get_status()
        self.assertIsInstance(status, dict)
        self.assertIn("mode", status)


if __name__ == "__main__":
    unittest.main()