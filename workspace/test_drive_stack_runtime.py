from __future__ import annotations

import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from aios_rebuild.main_core.mind_runtime_gate import BodyRuntimeHold

from swarm_adapters.drive_stacks import runtime
from swarm_adapters.drive_stacks.runtime import resolve_stack


class DriveStackRuntimeTests(unittest.TestCase):
    def test_l_master_resolves_with_its_tool_scheme_and_identity_adapter(self):
        stack = resolve_stack("L:")
        self.assertTrue(stack["ready"])
        self.assertEqual(stack["scheme"]["drive"], "L")
        self.assertTrue(stack["scheme"]["master_dispatcher"])
        self.assertEqual(stack["expert_loading"], "dynamic_unmerged_lora_per_task")
        self.assertEqual(stack["scheme_sha256"],
                         json.loads(runtime.REGISTRY_PATH.read_text(encoding="utf-8"))
                         ["drives"]["L"]["tool_scheme_sha256"])
        self.assertEqual([item["id"] for item in stack["adapters"]],
                         ["viv-swarm-default-v2"])
        self.assertFalse(stack["coordinator_adapter"])
        self.assertIn("Qwen3-8B remains the coordinator", stack["runtime_note"])

    def test_non_l_drive_requires_its_own_adapter(self):
        for drive in ("C", "D", "E", "F"):
            with self.subTest(drive=drive):
                original_is_file = Path.is_file
                registry = json.loads(runtime.REGISTRY_PATH.read_text(encoding="utf-8"))
                missing = (runtime.STACK_ROOT / registry["drives"][drive]["adapter_path"] / "adapter_config.json").resolve()
                with patch.object(Path, "is_file", lambda path: False if path.resolve() == missing else original_is_file(path)):
                    stack = resolve_stack(drive)
                self.assertFalse(stack["ready"])
                self.assertEqual(stack["scheme"]["drive"], drive)
                self.assertTrue(stack["scheme"]["permissions"]["filesystem"] == "read_only")
                self.assertEqual(stack["expert_loading"], "dynamic_unmerged_lora_per_task")
                self.assertIn("drive LoRA has not been trained", stack["reason"])
                self.assertFalse(stack["coordinator_adapter"])

    def test_unregistered_drive_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "No Architect-approved tool scheme"):
            resolve_stack("G:")

    def test_modified_tool_scheme_is_rejected(self):
        registry = json.loads(runtime.REGISTRY_PATH.read_text(encoding="utf-8"))
        registry["drives"]["L"]["tool_scheme_sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "registry.json"
            path.write_text(json.dumps(registry), encoding="utf-8")
            with patch.object(runtime, "REGISTRY_PATH", path):
                with self.assertRaisesRegex(ValueError, "integrity hash"):
                    resolve_stack("L")

    def test_body_hold_prevents_drive_model_loading(self):
        guard = Mock()
        guard.check.side_effect = BodyRuntimeHold({"allowed": False})
        with patch.object(runtime, "resolve_stack", return_value={"ready": True}), \
             patch.object(runtime, "_body_runtime_guard", return_value=guard), \
             patch.dict("sys.modules", {"torch": None, "peft": None, "transformers": None}):
            with self.assertRaises(BodyRuntimeHold):
                runtime.generate_for_drive("L", [{"role": "user", "content": "test"}])


if __name__ == "__main__":
    unittest.main(verbosity=2)
