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

    def test_is_template_and_parse_template(self):
        from autonomy.terminal_neuron_learning import is_template, parse_template

        self.assertTrue(is_template("The cat [?]."))
        self.assertTrue(is_template("The [?] sat."))
        self.assertTrue(is_template("The sky is _."))
        self.assertTrue(is_template("The [?] is [?]."))
        self.assertFalse(is_template("The cat sat."))

        tokens, blanks = parse_template("The cat [?].")
        self.assertEqual(tokens, ["the", "cat", "[?]"])
        self.assertEqual(blanks, [2])

        tokens, blanks = parse_template("The [?] is tall.")
        self.assertEqual(tokens, ["the", "[?]", "is", "tall"])
        self.assertEqual(blanks, [1])

        tokens, blanks = parse_template("The cat sat.")
        self.assertEqual(tokens, ["the", "cat", "sat"])
        self.assertEqual(blanks, [])

    def test_is_valid_sentence_oracle(self):
        from autonomy.terminal_neuron_learning import is_valid_sentence

        self.assertTrue(is_valid_sentence(["the", "cat", "sat"]))
        self.assertTrue(is_valid_sentence(["the", "cat", "slept"]))
        self.assertTrue(is_valid_sentence(["the", "dog", "is", "tall"]))
        self.assertTrue(is_valid_sentence(["the", "cat", "is", "big"]))
        self.assertTrue(is_valid_sentence(["the", "sun", "is", "dark"]))
        self.assertTrue(is_valid_sentence(["the", "bird", "can", "learn"]))
        self.assertTrue(is_valid_sentence(["the", "tree", "is", "blue"]))
        self.assertTrue(is_valid_sentence(["the", "fish", "is", "hot"]))
        self.assertTrue(is_valid_sentence(["the", "star", "is", "big"]))
        self.assertTrue(is_valid_sentence(["the", "moon", "is", "bright"]))

        self.assertFalse(is_valid_sentence(["the", "cat", "blue"]))
        self.assertFalse(is_valid_sentence(["the", "fish", "sat"]))
        self.assertFalse(is_valid_sentence(["the", "cat", "tall"]))
        self.assertFalse(is_valid_sentence(["the", "tall", "is", "dog"]))
        self.assertFalse(is_valid_sentence(["cat", "sat", "the"]))
        self.assertFalse(is_valid_sentence(["the"]))

    def test_next_autonomous_lesson_mad_libs_progression(self):
        from autonomy.terminal_neuron_learning import (
            MAD_LIBS_CURRICULUM, next_autonomous_lesson,
        )

        record = {"lessons": {}}
        self.assertEqual(next_autonomous_lesson(record, mad_libs=True), MAD_LIBS_CURRICULUM[0])

        first_key = MAD_LIBS_CURRICULUM[0].strip().rstrip(".!?").lower()
        record["lessons"][first_key] = {"state": "PASS"}
        self.assertEqual(next_autonomous_lesson(record, mad_libs=True), MAD_LIBS_CURRICULUM[1])

        completed = {c.strip().rstrip(".!?").lower(): {"state": "PASS"} for c in MAD_LIBS_CURRICULUM}
        # After completing Grade 2 Mad Libs, mad_libs auto-graduates to Grade 3 Homophones
        first_h = terminal_neuron_learning.GRADE_3_HOMOPHONE_CURRICULUM[0]
        self.assertEqual(next_autonomous_lesson({"lessons": completed}, mad_libs=True), first_h)

    def test_grade3_homophone_oracle_duels(self):
        from autonomy.terminal_neuron_learning import is_valid_sentence

        # Matrix 1: sea vs see
        self.assertTrue(is_valid_sentence(["fish", "swim", "in", "sea"]))
        self.assertTrue(is_valid_sentence(["water", "is", "in", "sea"]))
        self.assertTrue(is_valid_sentence(["the", "bird", "can", "see"]))
        self.assertTrue(is_valid_sentence(["the", "cat", "can", "see"]))
        self.assertFalse(is_valid_sentence(["fish", "swim", "in", "see"]))
        self.assertFalse(is_valid_sentence(["water", "is", "in", "see"]))
        self.assertFalse(is_valid_sentence(["the", "bird", "can", "sea"]))
        self.assertFalse(is_valid_sentence(["the", "cat", "can", "sea"]))

        # Matrix 2: there vs their
        self.assertTrue(is_valid_sentence(["the", "cat", "sat", "there"]))
        self.assertTrue(is_valid_sentence(["the", "bird", "sat", "there"]))
        self.assertTrue(is_valid_sentence(["they", "ate", "their", "fish"]))
        self.assertTrue(is_valid_sentence(["they", "saw", "their", "dog"]))
        self.assertFalse(is_valid_sentence(["the", "cat", "sat", "their"]))
        self.assertFalse(is_valid_sentence(["the", "bird", "sat", "their"]))
        self.assertFalse(is_valid_sentence(["they", "ate", "there", "fish"]))
        self.assertFalse(is_valid_sentence(["they", "saw", "there", "dog"]))

        # Matrix 3: to vs too vs two
        self.assertTrue(is_valid_sentence(["they", "ran", "to", "sea"]))
        self.assertTrue(is_valid_sentence(["they", "ran", "to", "tree"]))
        self.assertTrue(is_valid_sentence(["the", "dog", "is", "too", "big"]))
        self.assertTrue(is_valid_sentence(["the", "wave", "is", "too", "big"]))
        self.assertTrue(is_valid_sentence(["one", "and", "one", "is", "two"]))
        self.assertFalse(is_valid_sentence(["they", "ran", "too", "sea"]))
        self.assertFalse(is_valid_sentence(["they", "ran", "two", "sea"]))
        self.assertFalse(is_valid_sentence(["the", "dog", "is", "to", "big"]))
        self.assertFalse(is_valid_sentence(["the", "wave", "is", "to", "big"]))
        self.assertFalse(is_valid_sentence(["one", "and", "one", "is", "to"]))
        self.assertFalse(is_valid_sentence(["one", "and", "one", "is", "too"]))

        # Matrix 4: hear vs here
        self.assertTrue(is_valid_sentence(["they", "can", "hear", "the", "bird"]))
        self.assertTrue(is_valid_sentence(["they", "can", "hear", "the", "wave"]))
        self.assertTrue(is_valid_sentence(["they", "sat", "here"]))
        self.assertTrue(is_valid_sentence(["water", "is", "here"]))
        self.assertFalse(is_valid_sentence(["they", "can", "here", "the", "bird"]))
        self.assertFalse(is_valid_sentence(["they", "can", "here", "the", "wave"]))
        self.assertFalse(is_valid_sentence(["they", "sat", "hear"]))
        self.assertFalse(is_valid_sentence(["water", "is", "hear"]))

        # Matrix 5: new vs knew
        self.assertTrue(is_valid_sentence(["they", "knew", "the", "path"]))
        self.assertTrue(is_valid_sentence(["the", "path", "is", "new"]))
        self.assertTrue(is_valid_sentence(["they", "knew", "the", "word"]))
        self.assertTrue(is_valid_sentence(["the", "sound", "is", "new"]))
        self.assertFalse(is_valid_sentence(["they", "new", "the", "path"]))
        self.assertFalse(is_valid_sentence(["the", "path", "is", "knew"]))
        self.assertFalse(is_valid_sentence(["they", "new", "the", "word"]))
        self.assertFalse(is_valid_sentence(["the", "sound", "is", "knew"]))

        # Matrix 6: right vs write
        self.assertTrue(is_valid_sentence(["they", "can", "write", "the", "word"]))
        self.assertTrue(is_valid_sentence(["the", "route", "is", "right"]))
        self.assertTrue(is_valid_sentence(["the", "mind", "can", "write", "the", "word"]))
        self.assertTrue(is_valid_sentence(["the", "turn", "is", "right"]))
        self.assertFalse(is_valid_sentence(["they", "can", "right", "the", "word"]))
        self.assertFalse(is_valid_sentence(["the", "route", "is", "write"]))
        self.assertFalse(is_valid_sentence(["the", "mind", "can", "right", "the", "word"]))
        self.assertFalse(is_valid_sentence(["the", "turn", "is", "write"]))

    def test_next_autonomous_lesson_homophone_progression(self):
        from autonomy.terminal_neuron_learning import (
            GRADE_3_HOMOPHONE_CURRICULUM, MAD_LIBS_CURRICULUM, next_autonomous_lesson,
        )

        record = {"lessons": {}}
        self.assertEqual(next_autonomous_lesson(record, homophones=True), GRADE_3_HOMOPHONE_CURRICULUM[0])

        all_passed = {c.strip().rstrip(".!?").lower(): {"state": "PASS"} for c in MAD_LIBS_CURRICULUM}
        for h in GRADE_3_HOMOPHONE_CURRICULUM:
            all_passed[h.strip().rstrip(".!?").lower()] = {"state": "PASS"}
        self.assertIsNone(next_autonomous_lesson({"lessons": all_passed}, mad_libs=True))
        self.assertIsNone(next_autonomous_lesson({"lessons": all_passed}, homophones=True))

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

    def test_next_autonomous_lesson_finds_first_unlearned_lesson(self):
        from autonomy.terminal_neuron_learning import next_autonomous_lesson

        record = {
            "lessons": {
                "the cat sat": {"state": "PASS"},
                "the cat ran": {"state": "PASS"},
            }
        }
        self.assertEqual(next_autonomous_lesson(record), "The cat ate.")

    def test_autonomous_mode_stops_at_max_lessons(self):
        calls = 0

        def learn_input(text, *args, **kwargs):
            nonlocal calls
            calls += 1
            return {
                "run": str(RUNS / "test-run"),
                "input": text,
                "next_input_allowed": True,
                "follow_up_allowed": True,
                "lessons": {text.strip().rstrip(".!?").lower(): {"state": "PASS"}},
            }

        with (
            patch.object(terminal_neuron_learning, "learn_input", side_effect=learn_input),
            patch.object(terminal_neuron_learning, "latest_run", return_value=None),
            patch.object(terminal_neuron_learning, "starting_input", side_effect=lambda resume, requested: requested or "The cat sat."),
            patch.object(sys, "argv", ["terminal_neuron_learning", "--autonomous", "--max-lessons", "2"]),
        ):
            terminal_neuron_learning.main()

        self.assertEqual(calls, 2)

    def _run_autonomous(self, learn_input, extra_args=()):
        with (
            patch.object(terminal_neuron_learning, "learn_input", side_effect=learn_input),
            patch.object(terminal_neuron_learning, "latest_run", return_value=None),
            patch.object(terminal_neuron_learning, "starting_input", side_effect=lambda resume, requested: requested or "The cat sat."),
            patch.object(terminal_neuron_learning.time, "sleep", return_value=None),
            patch.object(sys, "argv", ["terminal_neuron_learning", "--autonomous", *extra_args]),
        ):
            terminal_neuron_learning.main()

    def test_curriculum_exhaustion_returns_none_instead_of_repeating_a_lesson(self):
        from autonomy.terminal_neuron_learning import (
            AUTONOMOUS_CURRICULUM, next_autonomous_lesson,
        )

        lessons = {
            sentence.strip().rstrip(".!?").lower(): {"state": "PASS"}
            for sentence in AUTONOMOUS_CURRICULUM
        }
        for subject in ("the cat", "the dog", "the bird", "the fish"):
            for action in ("sat", "ran", "ate", "slept", "swam"):
                lessons[f"{subject} {action}"] = {"state": "PASS"}
        self.assertIsNone(next_autonomous_lesson({"lessons": lessons}))

    def test_autonomous_mode_stops_when_curriculum_is_exhausted(self):
        calls = []

        def learn_input(text, *args, **kwargs):
            calls.append(text)
            return {"run": str(RUNS / "t"), "input": text, "next_input_allowed": True, "lessons": {}}

        with patch.object(terminal_neuron_learning, "next_autonomous_lesson", return_value=None):
            self._run_autonomous(learn_input)
        self.assertEqual(len(calls), 1)

    def test_autonomous_mode_stops_for_review_when_a_lesson_never_clears(self):
        from autonomy.terminal_neuron_learning import MAX_CONSECUTIVE_RUNS_PER_LESSON

        calls = []

        def learn_input(text, *args, **kwargs):
            calls.append(text)
            return {"run": str(RUNS / "t"), "input": text, "next_input_allowed": False, "lessons": {}}

        self._run_autonomous(learn_input)
        self.assertEqual(len(calls), MAX_CONSECUTIVE_RUNS_PER_LESSON)

    def test_autonomous_mode_stops_instead_of_retrying_when_disk_guard_trips(self):
        calls = []

        def learn_input(text, *args, **kwargs):
            calls.append(text)
            raise RuntimeError("Less than 2 GiB is free for durable learning snapshots")

        self._run_autonomous(learn_input)
        self.assertEqual(len(calls), 1)

    def test_bpe_subword_composition_catalog_includes_combination_neurons(self):
        """Verify 1 Neuron = 1 Token: Subword COMBINATION neurons are included in the composition catalog."""
        from autonomy.terminal_neuron_learning import latest_run, open_curriculum
        from nn_local.steel_brain_store import SQLiteNeuronGraphStore
        from nn_local.neuronizer import UniversalCurriculumEngine
        from nn_local.cuda_backend import CudaLibrary

        latest = latest_run()
        store = SQLiteNeuronGraphStore(latest / "neuron_graph.sqlite3", readonly=True)
        curriculum = open_curriculum(latest / "curriculum.sqlite3")

        # Standard UniversalCurriculumEngine filters out COMBINATION
        std_engine = UniversalCurriculumEngine(store, CudaLibrary(), curriculum, assembly_evidence=True)
        std_catalog = std_engine._word_composition_catalog("need")
        std_kinds = {t["kind"] for t in std_catalog}
        self.assertNotIn("COMBINATION", std_kinds)

        # BPE Engine includes COMBINATION tokens shorter than word
        from autonomy.terminal_neuron_learning import BPEUniversalCurriculumEngine
        bpe_engine = BPEUniversalCurriculumEngine(store, CudaLibrary(), curriculum, assembly_evidence=True)
        bpe_catalog = bpe_engine._word_composition_catalog("need")
        bpe_kinds = {t["kind"] for t in bpe_catalog}
        self.assertIn("COMBINATION", bpe_kinds)

        bpe_surfaces = {t["surface"] for t in bpe_catalog if t["kind"] == "COMBINATION"}
        # Both 'ne' and 'ed' exist in the graph and are shorter than 'need'
        self.assertTrue("ne" in bpe_surfaces or "ed" in bpe_surfaces or "ee" in bpe_surfaces)


if __name__ == "__main__":
    unittest.main()
