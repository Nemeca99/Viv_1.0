import unittest
import json
import tempfile
from pathlib import Path

from autonomy.socratic_learning_scope import (
    append_architect_review_session,
    append_definition_candidates,
    assess_tutor_response,
    has_explicit_definition_cue,
    include_spelling_feedback,
    record_architect_review_context,
    record_architect_review_definition,
    resolve_definition_candidate,
    run_speech_spelling_practice,
)


class FakeBrain:
    def __init__(self):
        self.calls = []

    def spell(self, word):
        self.calls.append(("spell", word))
        return {"neural_spelled": "c - a - t [c + at]", "attention_state": "PASS"}

    def speak_toddler(self, word):
        self.calls.append(("speak_toddler", word))
        return {"spoken_utterance": "the cat sat.", "gate_state": "PASS_NEURON_GROUNDED"}


class SocraticLearningScopeTests(unittest.TestCase):
    def setUp(self):
        self.known_words = {"the", "cat", "sat", "it", "is", "a", "small", "animal"}
        self.word_parts = {
            "the": "det",
            "cat": "noun",
            "sat": "verb",
            "it": "pronoun",
            "is": "verb",
            "a": "det",
            "small": "adj",
            "animal": "noun",
        }

    def test_language_practice_only_calls_spell_and_speak_for_approved_word(self):
        brain = FakeBrain()
        result = run_speech_spelling_practice(
            brain, "cat", {"concepts": ["cat", "dog"]}
        )
        self.assertEqual(brain.calls, [("spell", "cat"), ("speak_toddler", "cat")])
        self.assertTrue(result["spelling_matches"])

    def test_language_practice_rejects_word_outside_selected_domain(self):
        with self.assertRaisesRegex(PermissionError, "outside_active_curriculum_domain"):
            run_speech_spelling_practice(FakeBrain(), "ocean", {"concepts": ["cat"]})

    def test_unfamiliar_words_are_queued_once_for_definition(self):
        pending = append_definition_candidates([], ["cta", "zorp", "CTA"])
        self.assertEqual(pending, ["cta", "zorp"])

    def test_definition_acceptance_resolves_only_the_current_queue_head(self):
        pending = ["cta", "zorp"]
        self.assertEqual(resolve_definition_candidate(pending, "zorp"), pending)
        self.assertEqual(resolve_definition_candidate(pending, "CTA"), ["zorp"])

    def test_well_formed_sentence_with_known_words_passes(self):
        result = assess_tutor_response("The cat sat.", self.known_words, self.word_parts)
        self.assertTrue(result["passed"])
        self.assertEqual(result["disposition"], "passed")

    def test_reversed_subject_verb_order_fails_format_check(self):
        result = assess_tutor_response("The sat cat.", self.known_words, self.word_parts)
        self.assertFalse(result["well_formed"])
        self.assertEqual(result["disposition"], "incorrect_format")

    def test_unknown_word_keeps_format_pass_but_requests_definition(self):
        result = assess_tutor_response("The cta sat.", self.known_words, self.word_parts)
        self.assertTrue(result["well_formed"])
        self.assertEqual(result["unknown_words"], ["cta"])
        self.assertEqual(result["disposition"], "definition_required")
        self.assertFalse(result["passed"])

    def test_short_answer_requires_definition_and_does_not_pass(self):
        result = assess_tutor_response(
            "It is", self.known_words, self.word_parts, definition_required=True
        )
        self.assertFalse(result["passed"])
        self.assertEqual(result["disposition"], "definition_required")

    def test_novel_word_passes_only_after_tutor_accepts_its_definition(self):
        result = assess_tutor_response(
            "The cta sat.",
            self.known_words,
            self.word_parts,
            definition_text="A cta is a small animal.",
            tutor_accepts_definition=True,
        )
        self.assertTrue(result["passed"])
        self.assertTrue(result["definition_accepted"])

    def test_single_letter_nickname_can_be_defined_and_tutor_accepted(self):
        result = assess_tutor_response(
            "B is my nickname.",
            self.known_words | {"my", "nickname", "for", "me"},
            self.word_parts,
            definition_text="B is a nickname for me.",
            definition_target="b",
            tutor_accepts_definition=True,
        )
        self.assertTrue(result["well_formed"])
        self.assertEqual(result["unknown_words"], ["b"])
        self.assertTrue(result["passed"])

    def test_inline_single_letter_nickname_definition_is_recognized(self):
        response = "B is my nickname."
        self.assertTrue(has_explicit_definition_cue(response, "b"))
        self.assertFalse(has_explicit_definition_cue("The cta sat.", "cta"))
        result = assess_tutor_response(
            response,
            self.known_words | {"my", "nickname"},
            self.word_parts,
            definition_required=True,
            definition_text=response,
            definition_target="b",
            tutor_accepts_definition=True,
        )
        self.assertTrue(result["passed"])
        self.assertTrue(result["definition_accepted"])

    def test_architect_review_persists_definition_without_changing_vocabulary(self):
        queue = {}
        record_architect_review_context(queue, ["B"], "B is my nickname.", 3)
        record_architect_review_definition(queue, "B", "B is my nickname.", True, 3)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.jsonl"
            record = append_architect_review_session(path, "session-1", queue)
            loaded = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(record["status"], "awaiting_architect_review")
        self.assertFalse(record["stable_vocabulary_changed"])
        self.assertEqual(loaded["candidates"][0]["word"], "b")
        self.assertEqual(
            loaded["candidates"][0]["definition_attempts"][0]["definition"],
            "B is my nickname.",
        )
        self.assertTrue(loaded["candidates"][0]["definition_attempts"][0]["tutor_accepted"])

    def test_spelling_mismatch_is_explicit_in_tutor_feedback(self):
        feedback = include_spelling_feedback("Sentence format needs work.", "wave", False)
        self.assertIn("spelling check for 'wave' did not match", feedback)
        self.assertEqual(
            include_spelling_feedback("Good job.", "wave", True),
            "Good job.",
        )

    def test_rejected_definition_does_not_pass_novel_word(self):
        result = assess_tutor_response(
            "The cta sat.",
            self.known_words,
            self.word_parts,
            definition_text="A cta is a small animal.",
            tutor_accepts_definition=False,
        )
        self.assertFalse(result["passed"])
        self.assertEqual(result["disposition"], "definition_not_accepted")

    def test_multiple_unknown_words_are_not_accepted_as_one_definition(self):
        result = assess_tutor_response(
            "The cta zorp sat.",
            self.known_words,
            self.word_parts,
            definition_text="A cta is a small animal.",
            definition_target="cta",
            tutor_accepts_definition=True,
        )
        self.assertFalse(result["passed"])
        self.assertEqual(result["disposition"], "multiple_unknown_words")


if __name__ == "__main__":
    unittest.main()
