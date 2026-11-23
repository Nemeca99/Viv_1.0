import unittest

from autonomy.socratic_correction import attempt_one_correction


class FakeBrain:
    def __init__(self):
        self.calls = []

    def answer_slot_or_query(self, prompt, *, temperature):
        self.calls.append((prompt, temperature))
        return {"answer": "Soil is in the ground.", "gate_state": "RESPONSE", "s_n": 0.8}


class FailingBrain:
    def answer_slot_or_query(self, prompt, *, temperature):
        raise RuntimeError("candidate correction failed")


class SocraticCorrectionTests(unittest.TestCase):
    def test_one_correction_uses_failure_and_feedback_as_context(self):
        brain = FakeBrain()
        result = attempt_one_correction(
            brain,
            "Where do you find soil?",
            "s.",
            "Speak in a complete thought.",
            0.2,
        )

        self.assertEqual(len(brain.calls), 1)
        self.assertIn("Where do you find soil?", brain.calls[0][0])
        self.assertIn("s.", brain.calls[0][0])
        self.assertIn("complete thought", brain.calls[0][0])
        self.assertEqual(brain.calls[0][1], 0.2)
        self.assertEqual(result["answer"], "Soil is in the ground.")
        self.assertEqual(result["s_n"], 0.8)

    def test_failed_correction_returns_a_structured_failure(self):
        result = attempt_one_correction(
            FailingBrain(), "Where do you find soil?", "s.", "Try a sentence.", 0.2
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_type"], "RuntimeError")
        self.assertIn("candidate correction failed", result["error"])


if __name__ == "__main__":
    unittest.main()
