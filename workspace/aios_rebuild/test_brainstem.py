"""
Test suite and verification engine for the AIOS Biological Brainstem & RID Stability Rebuild.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent
REFERENCE = ROOT / "reference" / "fixture_brainstem.py"
REFERENCE_SHA256 = "aea0aa39ca4fb1d82f0e80a454a5de43954559e1618fddd5b528c8f1e345e592"


class BrainstemTemplateTests(unittest.TestCase):
    def test_reference_hash_and_structure(self):
        raw = REFERENCE.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), REFERENCE_SHA256)
        text = raw.decode("utf-8")
        self.assertIn("# TEMPLATE VARIABLES BEGIN\n", text)
        self.assertIn("# TEMPLATE VARIABLES END\n", text)
        self.assertIn("def main(context, variables):", text)

    def test_execution_homeostasis(self):
        namespace: dict = {}
        exec(REFERENCE.read_text(encoding="utf-8"), namespace)
        main = namespace["main"]
        defaults = namespace["VARIABLES"]

        # Nominal healthy context
        context = {
            "stm_count": 20,
            "structural_load": 1.0,
            "drift_distance": 0.05,
        }
        res = main(context, defaults)
        self.assertTrue(res["ok"])
        self.assertEqual(res["identity"], "Viv")
        self.assertEqual(res["scalars"]["rsr"], 0.95)
        self.assertEqual(res["scalars"]["ltp"], 1.0)
        self.assertEqual(res["scalars"]["rle"], 0.8)
        self.assertAlmostEqual(res["scalars"]["s_n"], 0.76, places=2)
        self.assertEqual(res["recommended_action"], "HOMEOSTASIS")

    def test_drift_triggers_soul_anchor(self):
        namespace: dict = {}
        exec(REFERENCE.read_text(encoding="utf-8"), namespace)
        main = namespace["main"]
        defaults = namespace["VARIABLES"]

        # High drift: RSR falls below 0.90
        context = {
            "stm_count": 20,
            "structural_load": 1.0,
            "drift_distance": 0.15,  # RSR = 0.85 < 0.90
        }
        res = main(context, defaults)
        self.assertEqual(res["scalars"]["rsr"], 0.85)
        self.assertFalse(res["stable"])
        self.assertEqual(res["recommended_action"], "SOUL_ANCHOR")

    def test_memory_saturation_triggers_distill_context(self):
        namespace: dict = {}
        exec(REFERENCE.read_text(encoding="utf-8"), namespace)
        main = namespace["main"]
        defaults = namespace["VARIABLES"]

        # STM capacity saturated: RLE falls below 0.60
        context = {
            "stm_count": 50,  # capacity 100 -> RLE = 0.50 < 0.60
            "structural_load": 1.0,
            "drift_distance": 0.02,
        }
        res = main(context, defaults)
        self.assertEqual(res["scalars"]["rle"], 0.50)
        self.assertFalse(res["stable"])
        self.assertEqual(res["recommended_action"], "DISTILL_CONTEXT")


if __name__ == "__main__":
    unittest.main()
