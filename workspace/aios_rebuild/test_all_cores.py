"""
Master Universal Test Suite for All Rebuilt AIOS Viv Core Templates.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent
REFERENCE_DIR = ROOT / "reference"

CORE_TEMPLATES = [
    "fixture_brainstem.py",
    "fixture_carma.py",
    "fixture_dream.py",
    "fixture_game.py",
    "fixture_luna.py",
    "fixture_rag.py",
    "fixture_security.py",
    "fixture_data.py",
    "fixture_infra.py",
    "fixture_fractal.py",
    "fixture_utils.py",
    "fixture_main.py",
    "fixture_backup.py",
    "fixture_privacy.py",
    "fixture_ecosystem.py",
]


class MasterCoreRebuildTests(unittest.TestCase):
    def test_all_reference_templates_exist_and_conform_to_ast_contract(self):
        for filename in CORE_TEMPLATES:
            path = REFERENCE_DIR / filename
            self.assertTrue(path.exists(), f"Missing template: {filename}")
            text = path.read_text(encoding="utf-8")

            # Assert AST structural invariants
            self.assertIn("import copy", text, f"{filename} missing 'import copy'")
            self.assertIn("# TEMPLATE VARIABLES BEGIN\n", text, f"{filename} missing VARIABLES header")
            self.assertIn("# TEMPLATE VARIABLES END\n", text, f"{filename} missing VARIABLES footer")
            self.assertIn("def main(context, variables):", text, f"{filename} missing main signature")
            self.assertIn("def sub_main_", text, f"{filename} missing submain stages")

    def test_all_templates_execute_cleanly(self):
        for filename in CORE_TEMPLATES:
            path = REFERENCE_DIR / filename
            namespace: dict = {}
            exec(path.read_text(encoding="utf-8"), namespace)

            main = namespace["main"]
            variables = namespace["VARIABLES"]

            res = main({}, variables)
            self.assertTrue(res["ok"], f"{filename} execution failed: {res}")
            self.assertEqual(res["identity"], "Viv", f"{filename} wrong identity: {res.get('identity')}")


if __name__ == "__main__":
    unittest.main()
