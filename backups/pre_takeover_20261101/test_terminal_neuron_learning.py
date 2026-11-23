import json
import sys
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import autonomy.terminal_neuron_learning as terminal_neuron_learning
from autonomy.terminal_neuron_learning import RUNS, follow_up_word, input_words, memory_clone, session_has_more_accepts, snapshot_bytes, starting_input, verify_run
from autonomy.socratic_language_training import digest


class TerminalNeuronLearningTests(unittest.TestCase):
    def test_starting_input_resumes_held_lesson_before_new_input(self):
        held = {"input": "The bird ran.", "next_input_allowed": False}
        with patch.object(terminal_neuron_learning, "verify_run", return_value=held):
            self.assertEqual(starting_input(RUNS / "held", None), "The bird ran.")
            self.assertEqual(starting_input(RUNS / "held", "The cat sat."), "The bird ran.")

    def test_starting_input_accepts_new_input_after_follow_up(self):
        ready = {"input": "The bird ran.", "next_input_allowed": True}
        with patch.object(terminal_neuron_learning, "verify_run", return_value=ready):
            self.assertEqual(starting_input(RUNS / "ready", "The cat sat."), "The cat sat.")
            self.assertEqual(starting_input(RUNS / "ready", None), "The bird ran.")

    def test_session_gate_keeps_failure_history_without_inheriting_tally_debt(self):
        old = {"passes": 10, "fails": 15}
        self.assertTrue(session_has_more_accepts({"passes": 17, "fails": 18}, old))
        self.assertFalse(session_has_more_accepts({"passes": 12, "fails": 19}, old))

    def test_input_words_preserves_order_and_repetition(self):
        self.assertEqual(input_words("The cat saw the cat."), ["the", "cat", "saw", "the", "cat"])
        with self.assertRaises(ValueError):
            input_words(" ")
        with self.assertRaises(ValueError):
            input_words("word " * 9)

    def test_follow_up_flashcard_selects_a_content_word(self):
        self.assertEqual(follow_up_word(["the", "dog", "ran"]), "ran")
        self.assertEqual(follow_up_word(["the", "is"]), "is")

    def test_interactive_body_hold_does_not_reuse_previous_success(self):
        class Held(RuntimeError):
            verdict = {"allowed": False, "reasons": ["wsl_body_request_timed_out"]}

        calls = 0

        def learn_input(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                return {
                    "run": str(RUNS / "test-run"), "input": "The cat sat.",
                    "next_input_allowed": True, "follow_up_allowed": True,
                }
            raise Held()

        with (
            patch.object(terminal_neuron_learning, "learn_input", side_effect=learn_input),
            patch.object(terminal_neuron_learning, "latest_run", return_value=None),
            patch.object(terminal_neuron_learning, "starting_input", side_effect=lambda resume, requested: requested or "The cat sat."),
            patch.object(sys, "argv", ["terminal_neuron_learning", "--interactive"]),
            patch("builtins.input", side_effect=["The sky is blue.", "/quit"]) as read_input,
        ):
            terminal_neuron_learning.main()

        self.assertEqual(calls, 2)
        self.assertIn("Tutor follow-up passed", read_input.call_args_list[0].args[0])
        self.assertIn("Tutor holds 'The sky is blue.'", read_input.call_args_list[1].args[0])

    def test_learning_snapshot_survives_reload_and_does_not_change_parent(self):
        with tempfile.TemporaryDirectory(dir=RUNS) as directory:
            parent = Path(directory) / "parent.sqlite3"
            connection = sqlite3.connect(parent)
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript("CREATE TABLE routes(weight INTEGER); INSERT INTO routes VALUES(10);")
            connection.close()
            before = digest(parent)
            store = memory_clone(SimpleNamespace(connection=sqlite3.connect(f"file:{parent.as_posix()}?mode=ro", uri=True)))
            store.connection.execute("UPDATE routes SET weight=20")
            saved = snapshot_bytes(store)
            store.connection.close()
            restored = sqlite3.connect(":memory:")
            restored.deserialize(saved)
            self.assertEqual(restored.execute("SELECT weight FROM routes").fetchone()[0], 20)
            restored.close()
            self.assertEqual(digest(parent), before)

    def test_resume_rejects_tampered_snapshot(self):
        with tempfile.TemporaryDirectory(prefix="language-routes-", dir=RUNS) as directory:
            run = Path(directory)
            hashes = {}
            for name in ("neuron_graph.sqlite3", "curriculum.sqlite3"):
                connection = sqlite3.connect(run / name)
                connection.execute("CREATE TABLE evidence(value INTEGER)")
                connection.close()
                hashes[name] = digest(run / name)
            (run / "learning.json").write_text(json.dumps({
                "schema": "viv_terminal_neuron_learning_v1", "snapshot_verified": True, "snapshot_hashes": hashes,
            }))
            self.assertTrue(verify_run(run)["snapshot_verified"])
            with (run / "neuron_graph.sqlite3").open("ab") as stream:
                stream.write(b"tampered")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                verify_run(run)


if __name__ == "__main__":
    unittest.main()
