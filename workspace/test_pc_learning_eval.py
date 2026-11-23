"""Independent rubric checks for the isolated PC-learning adapter."""
import unittest
import json

from swarm_adapters.evaluate_pc_learning import check, score_gate


class PCReaderEvaluationTests(unittest.TestCase):
    def test_equal_performance_is_behavior_pass_but_not_learning_gain(self):
        gate = score_gate(base_passed=11, candidate_passed=11, cases=11)
        self.assertTrue(gate["candidate_behavior_pass"])
        self.assertFalse(gate["candidate_improved"])
        self.assertFalse(gate["candidate_pass"])

    def test_candidate_must_pass_behavior_and_improve_to_activate(self):
        gate = score_gate(base_passed=6, candidate_passed=9, cases=10)
        self.assertTrue(gate["candidate_behavior_pass"])
        self.assertTrue(gate["candidate_improved"])
        self.assertTrue(gate["candidate_pass"])

    def test_correct_source_bound_answer_passes(self):
        expected = {"status": "PASS", "required_terms": ["3/3", "not promotion"],
                    "citations": ["report.md:42"], "forbidden_terms": ["live"]}
        answer = ('{"status":"PASS","result":"The report says 3/3; not promotion.",'
                  '"evidence":["report.md:42"],"unknowns":[]}')
        self.assertTrue(check(answer, expected)["passed"])

    def test_wrong_claim_or_missing_citation_fails(self):
        expected = {"status": "PASS", "required_terms": ["3/3"],
                    "citations": ["report.md:42"], "forbidden_terms": ["live"]}
        answer = ('{"status":"PASS","result":"The report says 3/3 and live.",'
                  '"evidence":[],"unknowns":[]}')
        result = check(answer, expected)
        self.assertFalse(result["passed"])
        self.assertFalse(result["checks"]["citations"])
        self.assertFalse(result["checks"]["forbidden_terms"])

    def test_unanswerable_question_requires_unknown(self):
        expected = {"status": "UNKNOWN", "required_terms": ["measurement"],
                    "citations": [], "forbidden_terms": ["8.56"]}
        answer = ('{"status":"UNKNOWN","result":"No live measurement is supplied.",'
                  '"evidence":[],"unknowns":["missing measurement"]}')
        self.assertTrue(check(answer, expected)["passed"])

    def test_accepts_fenced_json_and_structured_exact_citations(self):
        expected = {"status": "PASS", "required_any_terms": [["never executed", "not executed"]],
                    "citations": ["proof.rs:5"], "forbidden_terms": []}
        output = ('```json\n{"status":"PASS","result":"It was never executed.",'
                  '"evidence":[{"path":"proof.rs","line":5}],"unknowns":[]}\n```')
        self.assertTrue(check(output, expected)["passed"])

    def test_unknown_must_name_the_missing_measurement(self):
        expected = {"status": "UNKNOWN", "required_any_terms": [["cannot be determined"]],
                    "required_unknown_terms": ["free ram"], "citations": [], "forbidden_terms": []}
        answer = {"status": "UNKNOWN", "result": "Free RAM cannot be determined from this text.",
                  "evidence": [], "unknowns": ["current free RAM measurement"]}
        self.assertTrue(check(json.dumps(answer), expected)["passed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
