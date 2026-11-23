"""Deterministic provenance and split checks for autonomous evidence learning."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from autonomy.learning_corpus import (capture_agent_index_episode, capture_evidence, dataset_is_safe,
                                      prepare_fresh_corpus, record_evaluation_failures,
                                      source_is_safe)


class LearningCorpusTests(unittest.TestCase):
    def test_agent_index_episode_records_queen_teacher_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            learning = root / "learning"
            source = {"path": str(root / "README.md"), "line": 3,
                      "sha256": "a" * 64, "snippet": "The sensor map is read only."}
            messages = [{"role": "system", "content": "Queen review"},
                        {"role": "user", "content": "same source and rejection feedback"}]
            entry = {"project": "demo", "category": "documentation",
                     "summary": "Evidence summary"}
            self.assertEqual(capture_agent_index_episode(
                learning, source, messages, entry, supervision_source="queen_repair"), 1)
            row = json.loads((learning / "evidence_episodes.jsonl").read_text().strip())
            self.assertEqual(row["source"]["supervision_source"], "queen_repair")
            self.assertEqual(row["messages"][0]["content"], "Queen review")
            self.assertEqual(capture_agent_index_episode(
                learning, source, messages, entry, supervision_source="queen_repair"), 0)
            with self.assertRaises(ValueError):
                capture_agent_index_episode(
                    learning, source, messages, entry, supervision_source="unverified_model")

    def test_python_capture_adds_hash_checked_structure_task(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_path = root / "small_module.py"
            source_text = (
                "def alpha(value):\n"
                "    return beta(value)\n\n"
                "class Box:\n"
                "    pass\n\n"
                "async def beta(value):\n"
                "    return value\n")
            source_path.write_text(source_text, encoding="utf-8")
            source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
            learning = root / "learning"
            added = capture_evidence(learning, {"matches": [{
                "path": str(source_path), "line": 1, "sha256": source_hash,
                "snippet": "def alpha(value):", "sampling_tier": "source_document",
            }]})
            rows = [json.loads(line) for line in
                    (learning / "evidence_episodes.jsonl").read_text(encoding="utf-8").splitlines()]
            structural = next(row for row in rows if row["source"].get("task_type"))
            self.assertEqual(added, 2)
            self.assertEqual(structural["source"]["task_type"],
                             "python_top_level_symbol_inventory_v1")
            self.assertEqual(structural["expected"]["required_terms"],
                             ["alpha", "Box", "beta"])
            self.assertEqual(structural["expected"]["citations"], [
                f"{source_path}:1", f"{source_path}:4", f"{source_path}:7"])
            self.assertIn("Do not include nested methods", structural["messages"][0]["content"])

    def test_capture_deduplicates_hash_pinned_source_lines(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            search = {"matches": [
                {"path": str(root / "guide.md"), "line": 7,
                 "sha256": "a" * 64, "snippet": "The scanner is read only."},
                {"path": str(root / "guide.md"), "line": 7,
                 "sha256": "a" * 64, "snippet": "The scanner is read only."},
            ]}
            learning = root / "learning"
            self.assertEqual(capture_evidence(learning, search), 1)
            self.assertEqual(capture_evidence(learning, search), 0)
            row = json.loads((learning / "evidence_episodes.jsonl").read_text().strip())
            self.assertEqual(row["source"]["line"], 7)
            self.assertEqual(row["messages"][-1]["role"], "assistant")

    def test_fresh_rows_get_disjoint_hashed_train_and_heldout_sets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            learning = root / "learning"
            hits = {"matches": [
                {"path": str(root / f"notes_{number}.md"), "line": number,
                 "sha256": f"{number:064x}",
                 "snippet": f"Verified statement number {1 if number == 8 else number}."}
                for number in range(1, 9)
            ]}
            self.assertEqual(capture_evidence(learning, hits), 8)
            corpus = prepare_fresh_corpus(learning, set())
            self.assertIsNotNone(corpus)
            manifest = corpus["manifest"]
            self.assertFalse(set(manifest["training_ids"]) & set(manifest["evaluation_ids"]))
            self.assertEqual(len(manifest["training_ids"]) + len(manifest["evaluation_ids"]), 8)
            corpus_rows = [json.loads(line) for line in corpus["evaluation_path"].read_text().splitlines()]
            evidence = {json.loads(line)["id"]: json.loads(line) for line in
                        (learning / "evidence_episodes.jsonl").read_text().splitlines()}
            training_paths = {evidence[row_id]["source"]["path"] for row_id in manifest["training_ids"]}
            eval_paths = {evidence[row["id"]]["source"]["path"] for row in corpus_rows}
            training_snippets = {evidence[row_id]["source"]["snippet"] for row_id in manifest["training_ids"]}
            eval_snippets = {evidence[row["id"]]["source"]["snippet"] for row in corpus_rows}
            self.assertFalse(training_paths & eval_paths)
            self.assertFalse(training_snippets & eval_snippets)
            self.assertGreaterEqual(len(corpus_rows), 4)
            self.assertGreaterEqual(manifest["evaluation_group_count"], 3)
            self.assertGreaterEqual(manifest["evaluation_source_count"], 3)
            self.assertIsNone(prepare_fresh_corpus(
                learning, set(corpus["training_ids"]), set(corpus["evaluation_ids"])))

    def test_drive_corpus_contains_only_the_selected_drive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            learning = root / "learning"
            hits = {"matches": [
                {"path": str(root / f"notes_{number}.md"), "line": number,
                 "sha256": f"{number:064x}", "snippet": f"Drive scoped statement {number}."}
                for number in range(1, 9)
            ]}
            capture_evidence(learning, hits)
            drive = Path(temporary).drive.rstrip(":\\/").upper()
            corpus = prepare_fresh_corpus(learning, set(), drive=drive)
            self.assertIsNotNone(corpus)
            self.assertEqual(corpus["manifest"]["drive"], drive)
            material = {
                "drive": drive,
                "tool_scheme_sha256": corpus["manifest"]["tool_scheme_sha256"],
                "source_safety_policy": corpus["manifest"]["source_safety_policy"],
                "training_ids": corpus["manifest"]["training_ids"],
                "evaluation_ids": corpus["manifest"]["evaluation_ids"],
            }
            encoded = json.dumps(material, ensure_ascii=False, sort_keys=True,
                                 separators=(",", ":")).encode("utf-8")
            self.assertEqual(corpus["manifest"]["corpus_sha256"],
                             hashlib.sha256(encoded).hexdigest())
            self.assertIn(drive, str(corpus["output_path"]).upper())
            self.assertIsNone(prepare_fresh_corpus(
                learning, set(), drive="D" if drive != "D" else "C"))

    def test_sensitive_and_binary_sources_never_enter_new_corpora(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            learning = root / "learning"
            safe_hits = {"matches": [
                {"path": str(root / f"notes_{number}.md"), "line": 1,
                 "sha256": f"{number:064x}", "snippet": f"Safe source statement {number}.",
                 "sampling_tier": "source_document"}
                for number in range(1, 9)
            ]}
            self.assertEqual(capture_evidence(learning, safe_hits), 8)
            bad_hits = {"matches": [
                {"path": r"E:\\key.txt", "line": 1, "sha256": "f" * 64,
                 "snippet": "credential-like value"},
                {"path": str(root / "legacy.txt"), "line": 1, "sha256": "e" * 64,
                 "snippet": "\x00binary text"},
                {"path": str(root / "secrets.md"), "line": 1, "sha256": "d" * 64,
                 "snippet": "password=hunter2"},
            ]}
            self.assertEqual(capture_evidence(learning, bad_hits), 0)
            self.assertFalse(source_is_safe(r"E:\\key.txt", "ordinary text"))
            self.assertFalse(source_is_safe(str(root / "notes.md"), "\x00binary"))
            self.assertFalse(source_is_safe(str(root / "notes.md"), "password=example"))

            output = learning / "evidence_episodes.jsonl"
            unsafe_legacy = {
                "id": "legacy-unsafe-row",
                "source": {"path": r"E:\\eula.1033.txt", "line": 2,
                           "sha256": "c" * 64, "snippet": "\x00binary", 
                           "sampling_tier": "unspecified"},
                "messages": [{"role": "assistant", "content": "contaminated"}],
                "expected": {"status": "OBSERVED", "required_terms": [],
                             "citations": [], "forbidden_terms": []},
            }
            with output.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(unsafe_legacy) + "\n")
            corpus = prepare_fresh_corpus(learning, set())
            self.assertIsNotNone(corpus)
            self.assertEqual(corpus["manifest"]["excluded_unsafe_source_count"], 1)
            self.assertNotIn("legacy-unsafe-row", corpus["manifest"]["training_ids"])
            self.assertNotIn("legacy-unsafe-row", corpus["manifest"]["evaluation_ids"])
            unsafe_dataset = root / "unsafe.jsonl"
            unsafe_dataset.write_text(json.dumps({"messages": [
                {"role": "user", "content": "\x00bad"}]}), encoding="utf-8")
            self.assertEqual(dataset_is_safe(unsafe_dataset), (False, "binary_nul_content"))

    def test_failures_and_evaluated_holdouts_train_next_candidate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            learning = root / "learning"

            def hits(prefix, first, last):
                return {"matches": [
                    {"path": str(root / f"{prefix}_{number}.md"), "line": 1,
                     "sha256": f"{number + (0 if prefix == 'seed' else 100):064x}",
                     "snippet": f"Verified statement {prefix} {number}."}
                    for number in range(first, last)
                ]}

            self.assertEqual(capture_evidence(learning, hits("seed", 0, 16)), 16)
            first = prepare_fresh_corpus(learning, set())
            self.assertIsNotNone(first)
            heldout = json.loads(first["evaluation_path"].read_text().splitlines()[0])
            receipt = root / "first-receipt.json"
            receipt.write_text(json.dumps({"results": [{
                "arm": "base", "id": heldout["id"], "passed": False,
                "checks": [{"passed": False, "reason": "invalid_json"}],
                "outputs": ["malformed answer"],
            }]}), encoding="utf-8")
            self.assertEqual(record_evaluation_failures(
                learning, first["evaluation_path"], receipt), 1)
            correction = json.loads((learning / "failure_episodes.jsonl").read_text().strip())

            self.assertEqual(capture_evidence(learning, hits("next", 1, 9)), 8)
            second = prepare_fresh_corpus(
                learning, set(first["training_ids"]), set(first["evaluation_ids"]))
            self.assertIsNotNone(second)
            self.assertIn(correction["id"], second["manifest"]["training_ids"])
            self.assertGreaterEqual(second["manifest"]["failure_feedback_training_count"], 1)
            self.assertGreaterEqual(
                second["manifest"]["previously_evaluated_training_count"], 4)
            all_rows = {json.loads(line)["id"]: json.loads(line) for line in
                        (learning / "evidence_episodes.jsonl").read_text().splitlines()}
            all_rows.update({json.loads(line)["id"]: json.loads(line) for line in
                             (learning / "failure_episodes.jsonl").read_text().splitlines()})
            train = [all_rows[i]["source"] for i in second["manifest"]["training_ids"]]
            evaluation = [all_rows[i]["source"] for i in second["manifest"]["evaluation_ids"]]
            self.assertFalse({r["path"] for r in train} & {r["path"] for r in evaluation})
            self.assertFalse({r["snippet"] for r in train} & {r["snippet"] for r in evaluation})

    def test_repeated_failed_candidates_chain_to_original_grounded_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            learning = root / "learning"
            hits = {"matches": [
                {"path": str(root / f"notes_{number}.md"), "line": number,
                 "sha256": f"{number:064x}", "snippet": f"Verified statement number {number}."}
                for number in range(1, 9)
            ]}
            capture_evidence(learning, hits)
            corpus = prepare_fresh_corpus(learning, set())
            eval_path = corpus["evaluation_path"]
            heldout = json.loads(eval_path.read_text(encoding="utf-8").splitlines()[0])
            receipt_path = root / "receipt.json"
            receipt_path.write_text(json.dumps({"results": [{
                "arm": "base", "id": heldout["id"], "passed": False,
                "checks": [{"passed": False, "reason": "required citation missing"}],
                "outputs": ["uncited base claim"],
            }]}), encoding="utf-8")
            self.assertEqual(record_evaluation_failures(learning, eval_path, receipt_path), 1)
            self.assertEqual(record_evaluation_failures(learning, eval_path, receipt_path), 0)
            failures_path = learning / "failure_episodes.jsonl"
            first = json.loads(failures_path.read_text().strip())
            original = next(json.loads(line) for line in
                            (learning / "evidence_episodes.jsonl").read_text().splitlines()
                            if json.loads(line)["id"] == heldout["id"])
            self.assertEqual(first["parent_episode_id"], heldout["id"])
            self.assertEqual(first["root_episode_id"], heldout["id"])
            self.assertEqual(first["failed_arm"], "base")
            self.assertEqual(first["messages"][-1], original["messages"][-1])
            self.assertIn("untrusted diagnostic data", first["messages"][-2]["content"])

            second_eval = root / "retry-eval.jsonl"
            second_eval.write_text(json.dumps({"id": first["id"],
                                               "messages": first["messages"],
                                               "expected": first["expected"]}) + "\n",
                                    encoding="utf-8")
            receipt_path.write_text(json.dumps({"results": [{
                "arm": "candidate", "id": first["id"], "passed": False,
                "checks": [{"passed": False, "reason": "required unknown missing"}],
                "outputs": ["second rejected output"],
            }]}), encoding="utf-8")
            self.assertEqual(record_evaluation_failures(learning, second_eval, receipt_path), 1)
            rows = [json.loads(line) for line in failures_path.read_text().splitlines()]
            second = rows[1]
            self.assertEqual(second["parent_episode_id"], first["id"])
            self.assertEqual(second["root_episode_id"], heldout["id"])
            self.assertEqual(second["failed_arm"], "candidate")
            prompt = second["messages"][-2]["content"]
            self.assertEqual(prompt.count("Learning from a failed attempt"), 1)
            self.assertEqual(second["messages"][-1], original["messages"][-1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
