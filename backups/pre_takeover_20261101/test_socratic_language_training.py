import unittest

from autonomy.socratic_language_training import body_receipt, learning_passed, sentence_curriculum


class SocraticLanguageTrainingTests(unittest.TestCase):
    def test_body_receipt_binds_run_without_exposing_permit(self):
        result = body_receipt({"allowed": True, "body_runtime_permit": "secret"}, "language-test")
        self.assertEqual(result, {"allowed": True, "candidate_run_id": "language-test"})

    def test_fresh_sentences_are_not_teaching_targets(self):
        lessons, combinations, heldout = sentence_curriculum()
        self.assertEqual(len(heldout), 4)
        self.assertFalse({row["target"] for row in heldout} &
                         {row["target"] for row in lessons + combinations})
        self.assertIn("The wave is big.", {row["target"] for row in lessons})

    def scores(self, fresh):
        return {
            "spelling": {"exact": 5, "total": 5},
            "sentences": {"exact": 5, "total": 5},
            "fresh_combinations": {"exact": fresh, "total": 4},
            "retention": {"examples": [{"prompt": "Spell: cat\n", "exact": True}]},
        }

    def test_memorized_lessons_without_transfer_do_not_pass(self):
        self.assertFalse(learning_passed(self.scores(0), self.scores(0), True))

    def test_improvement_requires_retention_and_parent_integrity(self):
        before, after = self.scores(0), self.scores(3)
        self.assertTrue(learning_passed(before, after, True))
        self.assertFalse(learning_passed(before, after, False))
        after["retention"]["examples"][0]["exact"] = False
        self.assertFalse(learning_passed(before, after, True))


if __name__ == "__main__":
    unittest.main()
