"""Boundary checks for staged file preparation."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from prepare import ROOT, prepare, sha256


class PrepareTests(unittest.TestCase):
    def test_formats_staged_copy_without_changing_source(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "hive_quality") as folder:
            source = Path(folder) / "sample.py"
            original = b"value='ready'\n"
            source.write_bytes(original)
            receipt = prepare(str(source))
            self.assertEqual(receipt["status"], "PASS")
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(receipt["source_sha256"], sha256(original))
            self.assertNotEqual(receipt["prepared_sha256"], receipt["source_sha256"])
            self.assertIn('value = "ready"', Path(receipt["prepared"]).read_text())
            self.assertTrue(Path(receipt["diff"]).read_text())

    def test_unused_import_holds_and_keeps_receipt(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "hive_quality") as folder:
            source = Path(folder) / "unused.py"
            source.write_text("import os\n", encoding="utf-8")
            receipt = prepare(str(source))
            self.assertEqual(receipt["status"], "HOLD")
            self.assertEqual(receipt["checks"]["ruff"]["exit_code"], 1)
            saved = Path(receipt["prepared"]).parent / "receipt.json"
            self.assertEqual(json.loads(saved.read_text())["status"], "HOLD")


if __name__ == "__main__":
    unittest.main()
