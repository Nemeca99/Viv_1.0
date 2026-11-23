import tempfile
import json
from pathlib import Path
import unittest

from autonomy.learning.neuron_transition_matrix import NeuronTransitionMatrix
from autonomy.terminal_neuron_learning import latest_run


class NeuronTransitionMatrixTests(unittest.TestCase):
    def setUp(self):
        self.matrix = NeuronTransitionMatrix()
        # Seed with synthetic lesson sentences
        self.matrix.feed_sentence(["the", "cat", "ran", "to", "the", "tree"])
        self.matrix.feed_sentence(["the", "dog", "can", "see", "the", "cat"])
        self.matrix.feed_sentence(["they", "can", "see", "the", "fish"])
        self.matrix.feed_sentence(["the", "sun", "is", "too", "hot"])

    def test_vocab_and_sentence_count(self):
        self.assertEqual(self.matrix.total_sentences, 4)
        self.assertIn("cat", self.matrix.vocab)
        self.assertIn("sun", self.matrix.vocab)
        self.assertEqual(self.matrix.start_counts["the"], 3)
        self.assertEqual(self.matrix.start_counts["they"], 1)

    def test_predict_next_token(self):
        # After 'the cat ran', next token should be 'to'
        preds = self.matrix.predict_next(["the", "cat", "ran"])
        self.assertTrue(len(preds) > 0)
        self.assertEqual(preds[0][0], "to")
        self.assertAlmostEqual(preds[0][1], 1.0)

        # After 'they can', next token should be 'see'
        preds_see = self.matrix.predict_next(["they", "can"])
        self.assertEqual(preds_see[0][0], "see")

    def test_rank_permutations_prefers_valid_sentence(self):
        # Shuffled bag: ['see', 'fish', 'the', 'they', 'can']
        bag = ["see", "fish", "the", "they", "can"]
        ranked = self.matrix.rank_permutations(bag, top_n=5)
        top_route = ranked[0][0]
        self.assertEqual(top_route, ("they", "can", "see", "the", "fish"))

    def test_generate_continuation(self):
        gen = self.matrix.generate("the cat ran", max_tokens=6)
        self.assertEqual(gen, "the cat ran to the tree")

    def test_serialization_roundtrip(self):
        state = self.matrix.to_dict()
        restored = NeuronTransitionMatrix.from_dict(state)
        self.assertEqual(restored.total_sentences, self.matrix.total_sentences)
        self.assertEqual(restored.vocab, self.matrix.vocab)
        self.assertEqual(restored.start_counts, self.matrix.start_counts)
        self.assertEqual(restored.predict_next(["the", "cat", "ran"]), self.matrix.predict_next(["the", "cat", "ran"]))

    def test_load_from_live_snapshot(self):
        latest = latest_run()
        if latest and (latest / "learning.json").exists():
            live_matrix = NeuronTransitionMatrix.from_snapshot(latest)
            self.assertGreaterEqual(live_matrix.total_sentences, 50)
            self.assertIn("the", live_matrix.vocab)
            # Verify live ranking of 'they can see the fish'
            ranked = live_matrix.rank_permutations(["see", "fish", "the", "they", "can"], top_n=1)
            self.assertEqual(ranked[0][0], ("they", "can", "see", "the", "fish"))

    def test_incremental_session_matrix_updates(self):
        from autonomy.learning.neuron_transition_matrix import (
            get_session_matrix, record_session_lesson, reset_session_matrix
        )
        reset_session_matrix()
        session = get_session_matrix()
        self.assertEqual(session.total_sentences, 0)
        
        # Ingest lesson 1 in-memory
        record_session_lesson(["the", "cat", "saw", "the", "dog"])
        self.assertEqual(session.total_sentences, 1)
        self.assertIn("saw", session.vocab)
        
        # Check transition immediately available in-memory without disk read
        preds = session.predict_next(["the", "cat"])
        self.assertEqual(preds[0][0], "saw")
        
        # Ingest lesson 2 in-memory
        record_session_lesson(["the", "dog", "ate", "fish"])
        self.assertEqual(session.total_sentences, 2)
        preds2 = session.predict_next(["the", "dog"])
        self.assertEqual(preds2[0][0], "ate")


if __name__ == "__main__":
    unittest.main()
