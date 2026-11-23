import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent / "aios_rebuild"))

from main_core import main_core


class MainCoreWslGateTests(unittest.TestCase):
    def setUp(self):
        self.health = {"kernel": "healthy", "cores": {"security_core": {"status": "healthy"}}}
        self.resources = {
            "thermal_samples": [{"sensor_age_seconds": 1.25}],
            "requested_threads": 2,
        }
        self.allow = {
            "allowed": True,
            "disposition": "ALLOW_MIND_RUNTIME",
            "authority": "deterministic_aios_body_rust",
            "gate": "rust",
            "execution_boundary": "wsl_docker",
            "reasons": [],
            "stability_sn": 0.8,
            "requested_threads": 2,
        }

    def _kernel(self, root):
        kernel = object.__new__(main_core.UnifiedAIOSKernel)
        kernel.get_system_health = lambda: self.health
        return kernel

    def test_workspace_root_can_be_overridden_for_body_image(self):
        with patch.dict(main_core.os.environ, {"AIOS_WORKSPACE_ROOT": "/opt/aios_rebuild"}):
            self.assertEqual(main_core._configured_workspace(), Path("/opt/aios_rebuild"))

        with patch.dict(main_core.os.environ, {}, clear=True):
            self.assertEqual(main_core._configured_workspace(), main_core.DEFAULT_WORKSPACE)

    def test_workspace_core_inventory_matches_baked_body_manifest(self):
        manifest_path = (
            Path(__file__).parent / "aios_rebuild" / "body_runtime" / "core_manifest.json"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(
            main_core._expected_core_names(main_core.WORKSPACE),
            sorted(manifest["expected_cores"]),
        )

    def test_body_allow_routes_through_container_and_then_mints_bound_rust_permit(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            core_dir = root / "security_core"
            core_dir.mkdir()
            (core_dir / "security_core.py").write_text("", encoding="utf-8")
            kernel = self._kernel(root)
            permit_authority = Mock()
            permit_authority.issue_body_runtime_permit.return_value = "one-shot-permit"
            with patch.object(main_core, "WORKSPACE", root), \
                 patch.object(main_core, "collect_body_resources", return_value=self.resources), \
                 patch.object(main_core.body_runtime_client, "authorize", return_value=self.allow) as authorize, \
                 patch.object(kernel, "_get_rust_body_authority", return_value=permit_authority):
                decision = kernel.get_mind_runtime_gate(2, "candidate-run")

        self.assertTrue(decision["allowed"])
        self.assertEqual(decision["gate"], "rust")
        self.assertEqual(decision["execution_boundary"], "wsl_docker")
        self.assertEqual(decision["body_runtime_permit"], "one-shot-permit")
        request = authorize.call_args.args[0]
        self.assertEqual(request["candidate_run_id"], "candidate-run")
        self.assertEqual(request["body_resources"], self.resources)
        permit_authority.issue_body_runtime_permit.assert_called_once_with(
            0.8, 1.25, 2, "candidate-run")

    def test_body_hold_does_not_mint_permit(self):
        held = {"allowed": False, "disposition": "HOLD_MIND_RUNTIME",
                "authority": "deterministic_aios_body_rust", "reasons": ["thermal_hold"]}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            kernel = self._kernel(root)
            with patch.object(main_core, "WORKSPACE", root), \
                 patch.object(main_core, "collect_body_resources", return_value=self.resources), \
                 patch.object(main_core.body_runtime_client, "authorize", return_value=held), \
                 patch.object(kernel, "_get_rust_body_authority") as issue:
                decision = kernel.get_mind_runtime_gate(2, "candidate-run")
        self.assertFalse(decision["allowed"])
        issue.assert_not_called()

    def test_local_permit_failure_converts_body_allow_to_hold(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            kernel = self._kernel(root)
            permit_authority = Mock()
            permit_authority.issue_body_runtime_permit.side_effect = PermissionError("no permit")
            with patch.object(main_core, "WORKSPACE", root), \
                 patch.object(main_core, "collect_body_resources", return_value=self.resources), \
                 patch.object(main_core.body_runtime_client, "authorize", return_value=self.allow), \
                 patch.object(kernel, "_get_rust_body_authority", return_value=permit_authority):
                decision = kernel.get_mind_runtime_gate(2, "candidate-run")
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["disposition"], "HOLD_MIND_RUNTIME")
        self.assertIn("wsl_body_authority_or_permit_unavailable:PermissionError", decision["reasons"])


if __name__ == "__main__":
    unittest.main()
