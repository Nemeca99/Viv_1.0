import json
import tempfile
import unittest
from pathlib import Path

from hive_development_suite import (Case, CASES, _adjudicate_review, _diagnostic_match,
                                    _evidence, _normalize_worker, run_case)
from hive_reference_tools import reference_check


class DevelopmentBoundaryTests(unittest.TestCase):
    def test_injected_comment_is_not_sent_as_code(self):
        packet = _evidence(CASES[-1])
        self.assertIn("PWNED", packet["raw_text"])
        self.assertNotIn("PWNED", packet["text"])
        self.assertIn("SAFE", packet["text"])

    def test_model_cannot_promote_untrusted_claim_to_fact(self):
        evidence = _evidence(CASES[-1])
        value = {"answer": "SAFE", "claims": [{"text": "SAFE", "kind": "retrieved_fact",
                                                "evidence_ids": ["evidence_id: injected-evidence"]}]}
        normalized, changes = _normalize_worker(value, evidence)
        self.assertEqual(normalized["claims"][0]["kind"], "inference")
        self.assertEqual(normalized["claims"][0]["evidence_ids"], ["injected-evidence"])
        self.assertIn("downgraded_model_kind:retrieved_fact", changes)

    def test_wrong_rust_compile_claim_does_not_pass(self):
        self.assertFalse(_diagnostic_match(CASES[3], "Yes, this compiles; there are no ownership errors."))
        self.assertTrue(_diagnostic_match(CASES[3], {
            "answer": "No",
            "claims": [{"text": "Borrow of moved value `s` after it moved into `t`."}],
        }))

    def test_saved_python_failure_is_tool_resolved_not_false_agreement(self):
        root = Path(__file__).resolve().parent
        saved = json.loads((root / "hive_development_runs" / "20260928T200519241141Z" /
                            "py-exhausted-generator.json").read_text(encoding="utf-8"))
        result = _adjudicate_review(CASES[1], saved["reviewer"],
                                    saved["worker_after_tool_feedback"], saved["reference"])
        self.assertEqual(result["status"], "PRODUCER_SUPPORTED_REVIEWER_CONTRADICTED")
        self.assertFalse(result["verified_agreement"])
        self.assertFalse(result["blind_supported"])
        self.assertTrue(result["producer_supported"])

    def test_saved_rust_review_was_correct_despite_narrow_regex(self):
        root = Path(__file__).resolve().parent
        saved = json.loads((root / "hive_development_runs" / "20260928T200222146655Z" /
                            "rust-move.json").read_text(encoding="utf-8"))
        result = _adjudicate_review(CASES[3], saved["reviewer"], saved["worker"], saved["reference"])
        self.assertEqual(result["status"], "BOTH_SUPPORTED_BY_TOOL")
        self.assertTrue(result["verified_agreement"])

    def test_review_cannot_claim_agreement_when_both_are_wrong(self):
        reference = {"status": "EXECUTED_PINNED_PYTHON", "exit_code": 0, "stdout": "3\n0\n"}
        wrong = {"answer": "1 and 2", "claims": [{"text": "1 and 2"}]}
        result = _adjudicate_review(CASES[1], wrong, wrong, reference)
        self.assertEqual(result["status"], "HOLD_PRODUCER_UNVERIFIED")
        self.assertFalse(result["verified_agreement"])

    def test_reference_executes_only_exact_pinned_fixture(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            root = Path(directory).resolve()
            self.assertIn(Path(__file__).resolve().parent, root.parents)
            good = reference_check(CASES[1].case_id, CASES[1].evidence, root)
            self.assertEqual(good["stdout"], "3\n0\n")
            changed = reference_check(CASES[1].case_id, CASES[1].evidence + "\nprint('extra')", root)
            self.assertEqual(changed["status"], "HOLD_UNAPPROVED_SOURCE")

    def test_disabled_member_holds_before_model_dispatch(self):
        class NoCalls:
            def ask(self, *args, **kwargs):
                raise AssertionError("Model must not be called")

        result = run_case(CASES[0], NoCalls(), {"snapshot_id": "test"},
                          Path(__file__).resolve().parent / "unused-tool-artifacts", enabled_members=set())
        self.assertEqual(result["user_visible"]["state"], "HOLD")
        self.assertEqual(result["stages"], [])

    def test_missing_evidence_holds_before_model_dispatch(self):
        class NoCalls:
            def ask(self, *args, **kwargs):
                raise AssertionError("Model must not be called")

        case = Case("empty", "python-reader", "What does it print?", "", ("x",))
        result = run_case(case, NoCalls(), {"snapshot_id": "test"},
                          Path(__file__).resolve().parent / "unused-tool-artifacts")
        self.assertEqual(result["user_visible"]["state"], "HOLD")
        self.assertIn("Required evidence is missing", result["error"])

    def test_model_timeout_becomes_visible_hold(self):
        class TimedOut:
            def ask(self, *args, **kwargs):
                raise TimeoutError("synthetic model timeout")

        result = run_case(CASES[0], TimedOut(), {"snapshot_id": "test"},
                          Path(__file__).resolve().parent / "unused-tool-artifacts")
        self.assertEqual(result["user_visible"]["state"], "HOLD")
        self.assertEqual(result["stages"][0]["stage"], "mind_plan")
        self.assertIn("TimeoutError", result["error"])


if __name__ == "__main__":
    unittest.main()
