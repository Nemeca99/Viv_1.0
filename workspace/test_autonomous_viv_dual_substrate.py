import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aios_rebuild.main_core.mind_runtime_gate import BodyRuntimeHold
import run_autonomous_viv_dual_substrate as autonomous_viv


class AutonomousVivBodyGateTests(unittest.TestCase):
    def test_initial_body_hold_prevents_mind_loading_and_log_creation(self):
        hold = BodyRuntimeHold({
            "allowed": False,
            "disposition": "HOLD_MIND_RUNTIME",
            "authority": "deterministic_aios_body_rust",
            "reasons": ["privacy_core_unverified"],
        })
        with tempfile.TemporaryDirectory() as folder:
            log_path = Path(folder) / "autonomous_daemon.log"
            with patch.object(autonomous_viv, "LOG_FILE", log_path), \
                    patch.object(autonomous_viv, "require_body_runtime", side_effect=hold), \
                    patch.object(autonomous_viv, "_load_mind_stack") as load_mind_stack:
                autonomous_viv.run_autonomous_loop(max_cycles=1)
            load_mind_stack.assert_not_called()
            self.assertFalse(log_path.exists())

    def test_body_hold_at_commit_boundary_prevents_candidate_promotion(self):
        class Brain:
            promoted = False

            def promote_neologism_to_graph(self, word):
                self.promoted = True
                return {"word": word}

        brain = Brain()
        hold = BodyRuntimeHold({"allowed": False, "reasons": ["privacy_core_unverified"]})
        with patch.object(autonomous_viv, "require_body_runtime", side_effect=hold):
            with self.assertRaises(BodyRuntimeHold):
                autonomous_viv.promote_candidate_under_body_authority(brain, "novelword")
        self.assertFalse(brain.promoted)

    def test_body_authorized_commit_calls_candidate_promoter(self):
        class Brain:
            def promote_neologism_to_graph(self, word):
                return {"word": word}

        brain = Brain()
        with patch.object(autonomous_viv, "require_body_runtime", return_value={"allowed": True}) as authorize:
            result = autonomous_viv.promote_candidate_under_body_authority(brain, "novelword")
        authorize.assert_called_once_with()
        self.assertEqual(result, {"word": "novelword"})


if __name__ == "__main__":
    unittest.main()
