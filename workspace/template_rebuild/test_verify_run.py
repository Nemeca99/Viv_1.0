"""Negative checks for the rebuilt template's source boundary."""

from __future__ import annotations

from pathlib import Path
import hashlib
import json
import shutil
import tempfile
import unittest

from verify_run import verify
from runtime import TemplateRuntime, TemplateRuntimeError


ROOT = Path(__file__).resolve().parent
REFERENCE = ROOT / "reference" / "fixture_echo.py"
PASS_RUN = ROOT / "runs" / "1790639286606457600"


class RebuildVerificationTests(unittest.TestCase):
    def test_live_rebuild_passes(self) -> None:
        self.assertEqual(verify(PASS_RUN, REFERENCE)["status"], "PASS")

    def test_runtime_loads_then_executes_declared_variables(self) -> None:
        runtime = TemplateRuntime(PASS_RUN, REFERENCE)
        self.assertIsNone(runtime._module)
        output = runtime.execute({"probe": 1}, {"message": "rebuilt"})
        self.assertEqual(output["message"], "rebuilt")
        self.assertEqual(output["suffix"], "txt")
        self.assertEqual(output["context_keys"], ["probe"])
        with self.assertRaisesRegex(TemplateRuntimeError, "undeclared"):
            runtime.execute({}, {"new_key": "no"})

    def test_changed_function_body_holds(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp)
            for name in ("fixture_echo.py", "registry.json"):
                shutil.copy2(PASS_RUN / name, run / name)
            artifact = run / "fixture_echo.py"
            artifact.write_text(
                artifact.read_text(encoding="utf-8").replace(
                    '"ok": True', '"ok": False'
                ),
                encoding="utf-8",
            )
            registry_path = run / "registry.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["templates"][0]["source_sha256"] = hashlib.sha256(
                artifact.read_bytes()
            ).hexdigest()
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "non-variable source span changed"):
                verify(run, REFERENCE)


if __name__ == "__main__":
    unittest.main()
