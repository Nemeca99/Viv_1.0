"""Tests for local observer scope, redaction, and read-only behavior."""
from __future__ import annotations

from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

import workspace_observer as observer
from autonomy.pc_source_index import advance_index, indexed_paths, random_indexed_paths


class WorkspaceObserverTests(unittest.TestCase):
    def test_inventory_uses_bounded_orientation_walk_instead_of_loading_full_index(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "viv" / "sample"
            project.mkdir(parents=True)
            readme = project / "README.md"
            manifest = project / "pyproject.toml"
            readme.write_text("A bounded read-only source inventory.", encoding="utf-8")
            manifest.write_text("[project]\nname='sample'\n", encoding="utf-8")
            indexed_roots = [{"root": str(root), "eligible_files": 2,
                              "directories_indexed": 2, "directory_errors": 0,
                              "complete": False}]
            index_stats = {"roots": indexed_roots, "eligible_files_indexed": 2,
                           "index_complete": False, "index_traversal_finished": False}
            walk_stats = {"directories": 4, "files": 7, "truncated": True,
                          "elapsed_seconds": 0.2}
            with (patch.object(observer, "mounted_drive_roots", return_value=(root,)),
                  patch.object(observer, "advance_index", return_value=index_stats),
                  patch.object(observer, "_walk", return_value=([readme, manifest], walk_stats)),
                  patch.object(observer, "indexed_paths",
                               side_effect=AssertionError("must not materialize the full index"),
                               create=True)):
                result = observer.inventory_pc_sources()
            self.assertTrue(result["inventory"]["orientation_scan"]["truncated"])
            self.assertTrue(any(group["path"] == str(project)
                                for group in result["projects"]))
            self.assertTrue(any(doc["path"] == str(readme)
                                for doc in result["orientation_documents"]))

    def test_macro_sampler_tiers_source_docs_ahead_of_archive_noise(self):
        self.assertEqual(observer.sample_tier(Path(r"F:\projects\viv\runtime.py")),
                         "source_document")
        self.assertEqual(observer.sample_tier(Path(r"D:\notes\training.jsonl")),
                         "structured_text")
        self.assertEqual(observer.sample_tier(Path(
            r"F:\archive_dev_core\datasets\batch_12_scan.log")), "archive_or_log")
        self.assertEqual(sum(observer.SAMPLE_TIER_WEIGHTS.values()), 1.0)

    def setUp(self):
        observer._walk_cached.cache_clear()

    def tearDown(self):
        observer._walk_cached.cache_clear()

    def test_content_search_returns_hash_pinned_redacted_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "src").mkdir()
            (root / "src" / "guide.md").write_text(
                "Viv uses local learning.\napi_key=SECRET-VALUE\n", encoding="utf-8")
            with patch.object(observer, "SCAN_ROOTS", (root,)):
                result = observer.search_pc_content("local learning secret")
            self.assertEqual(result["mode"], "read_only")
            self.assertTrue(any(hit["path"].endswith("guide.md") for hit in result["matches"]))
            self.assertTrue(all("SECRET-VALUE" not in hit["snippet"] for hit in result["matches"]))
            self.assertRegex(result["matches"][0]["sha256"], r"^[0-9a-f]{64}$")

    def test_search_prunes_sensitive_directories(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "src").mkdir()
            (root / ".ssh").mkdir()
            (root / ".hive_proof_env" / "Lib" / "site-packages").mkdir(parents=True)
            (root / "src" / "safe.md").write_text("autonomy evidence", encoding="utf-8")
            (root / ".ssh" / "private.md").write_text("autonomy evidence", encoding="utf-8")
            (root / ".hive_proof_env" / "Lib" / "site-packages" / "third_party.md").write_text(
                "autonomy evidence", encoding="utf-8")
            with patch.object(observer, "SCAN_ROOTS", (root,)):
                result = observer.search_pc_content("autonomy evidence")
            self.assertTrue(any(hit["path"].endswith("safe.md") for hit in result["matches"]))
            self.assertFalse(any(".ssh" in hit["path"] for hit in result["matches"]))
            self.assertFalse(any(".hive_proof_env" in hit["path"]
                                 for hit in result["matches"]))

    def test_invalid_or_unbounded_queries_are_rejected(self):
        for query in ("", " ", "x" * 401):
            with self.subTest(query_length=len(query)), self.assertRaises(ValueError):
                observer.search_pc_content(query)

    def test_search_ranks_concise_learning_lines_before_minified_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "a.json").write_text(
                '{"viv":"' + " autonomous learning training evaluation" * 30 + '"}',
                encoding="utf-8")
            (root / "b.md").write_text(
                "Viv autonomous learning needs source citations.\n", encoding="utf-8")
            with patch.object(observer, "SCAN_ROOTS", (root,)):
                result = observer.search_pc_content("Viv autonomous learning training evaluation")
            self.assertTrue(result["matches"])
            self.assertEqual(Path(result["matches"][0]["path"]).suffix, ".md")
            self.assertLessEqual(len(result["matches"][0]["snippet"]),
                                 observer.LEARNING_SNIPPET_CHARS)

    def test_autonomous_search_prefers_unseen_hash_pinned_lines(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "a.md"
            second = root / "b.md"
            first.write_text("Viv evidence training candidate\n", encoding="utf-8")
            second.write_text("Viv evidence training candidate\n", encoding="utf-8")
            with patch.object(observer, "SCAN_ROOTS", (root,)):
                initial = observer.search_pc_content("Viv evidence training candidate")
                self.assertGreaterEqual(len(initial["matches"]), 2)
                first_hit = initial["matches"][0]
                exclude = {(str(Path(first_hit["path"]).resolve()).casefold(),
                            first_hit["line"], first_hit["sha256"])}
                refreshed = observer.search_pc_content(
                    "Viv evidence training candidate", exclude=exclude)
            self.assertNotEqual(refreshed["matches"][0]["path"], first_hit["path"])
            self.assertNotIn("_previously_seen", refreshed["matches"][0])

    def test_recursive_search_can_exclude_every_previously_seen_hit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "a.md"
            second = root / "b.md"
            first.write_text("module answers the recursive question\n", encoding="utf-8")
            second.write_text("module answers the recursive question\n", encoding="utf-8")
            with patch.object(observer, "SCAN_ROOTS", (root,)):
                initial = observer.search_pc_content("recursive question module")
                exclude = {(str(Path(hit["path"]).resolve()).casefold(),
                            hit["line"], hit["sha256"]) for hit in initial["matches"]}
                recursive = observer.search_pc_content(
                    "recursive question module", exclude=exclude, exclude_seen_only=True)
            self.assertEqual(recursive["matches"], [])
            self.assertEqual(recursive["bytes_read"], len(first.read_bytes()) + len(second.read_bytes()))

    def test_macro_sampler_is_repeatable_hash_pinned_and_respects_seen_lines(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index in range(12):
                (root / f"{index:02}.md").write_text(
                    f"Document {index} has readable learning evidence.\napi_key=SECRET{index}\n",
                    encoding="utf-8")
            index_db = root / "index.sqlite3"
            with patch.object(observer, "SCAN_ROOTS", (root,)):
                with patch.object(observer, "PC_INDEX_DB", index_db):
                    first = observer.sample_pc_content(count=6, seed=42, roots=(root,))
                    repeat = observer.sample_pc_content(count=6, seed=42, roots=(root,))
                self.assertEqual(first["matches"], repeat["matches"])
                self.assertEqual(first["mode"], "read_only_macro_random_sample")
                self.assertEqual(len(first["matches"]), 6)
                self.assertLessEqual(first["candidate_path_pool_size"], 256)
                self.assertEqual(len({hit["path"] for hit in first["matches"]}), 6)
                self.assertTrue(all(len(hit["snippet"]) <= 240 for hit in first["matches"]))
                self.assertTrue(all(len(hit["sha256"]) == 64 for hit in first["matches"]))
                self.assertTrue(all("SECRET" not in hit["snippet"] for hit in first["matches"]))
                exclude = {(str(Path(hit["path"]).resolve()).casefold(),
                            hit["line"], hit["sha256"]) for hit in first["matches"]}
                with patch.object(observer, "PC_INDEX_DB", index_db):
                    second = observer.sample_pc_content(count=6, seed=42, exclude=exclude,
                                                        roots=(root,))
                self.assertFalse(any((str(Path(hit["path"]).resolve()).casefold(),
                                      hit["line"], hit["sha256"]) in exclude
                                     for hit in second["matches"]))

    def test_macro_sampler_skips_syntax_only_lines_before_accepting_a_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "notes.md").write_text(
                "try:\n@property\nCPU package temperature is 48 C.\n", encoding="utf-8")
            index_db = root / "index.sqlite3"
            with patch.object(observer, "SCAN_ROOTS", (root,)), \
                 patch.object(observer, "PC_INDEX_DB", index_db):
                result = observer.sample_pc_content(count=1, seed=3, roots=(root,))
            self.assertEqual(len(result["matches"]), 1)
            self.assertEqual(result["matches"][0]["line"], 3)
            self.assertGreaterEqual(result["skipped_low_information_lines"], 1)

    def test_content_search_omits_syntax_only_matches(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "notes.md").write_text(
                "try:\nThe try marker begins a guarded block here.\n", encoding="utf-8")
            with patch.object(observer, "SCAN_ROOTS", (root,)):
                result = observer.search_pc_content("try marker")
            self.assertEqual([hit["line"] for hit in result["matches"]], [2])

    def test_macro_sampler_skips_credential_files_binary_text_and_secret_lines(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "safe.md").write_text(
                "Ordinary project documentation.\napi_key=never-train-this\n",
                encoding="utf-8")
            (root / "key.txt").write_text("credential-like value", encoding="utf-8")
            (root / "eula.txt").write_bytes("Windows license".encode("utf-16"))
            index_db = root / "index.sqlite3"
            with patch.object(observer, "SCAN_ROOTS", (root,)), \
                 patch.object(observer, "PC_INDEX_DB", index_db):
                result = observer.sample_pc_content(count=2, seed=11, roots=(root,))
            self.assertEqual(len(result["matches"]), 1)
            self.assertTrue(result["matches"][0]["path"].endswith("safe.md"))
            self.assertNotIn("never-train-this", result["matches"][0]["snippet"])
            self.assertGreaterEqual(result["skipped_binary_files"], 1)
            self.assertTrue(observer._sensitive_source_path(root / "key.txt"))

    def test_persistent_index_advances_each_root_and_records_completion(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            roots = (base / "drive_c", base / "drive_f")
            for drive in roots:
                (drive / "project").mkdir(parents=True)
                (drive / "project" / "readme.md").write_text("source data", encoding="utf-8")
                (drive / ".ssh").mkdir()
                (drive / ".ssh" / "private.md").write_text("excluded", encoding="utf-8")
            database = base / "pc_index.sqlite3"
            result = advance_index(database, roots, max_dirs=1, max_seconds=2)
            self.assertEqual(result["directories_scanned_this_slice"], 1)
            while not result["index_traversal_finished"]:
                result = advance_index(database, roots, max_dirs=1, max_seconds=2)
            self.assertTrue(result["index_complete"])
            self.assertEqual(len(result["roots"]), 2)
            self.assertTrue(all(root["complete"] for root in result["roots"]))
            self.assertTrue(all(root["eligible_files"] == 1 for root in result["roots"]))
            paths = {str(path) for path in indexed_paths(database)}
            self.assertEqual(len(paths), 2)
            self.assertFalse(any(".ssh" in path for path in paths))

    def test_random_indexed_paths_is_bounded_repeatable_and_drive_scoped(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "drive_l"
            project = root / "project"
            project.mkdir(parents=True)
            for index in range(100):
                (project / f"source_{index:03}.md").write_text(
                    f"source line {index}", encoding="utf-8")
            database = base / "pc_index.sqlite3"
            advance_index(database, (root,), max_dirs=10, max_seconds=2)
            first = random_indexed_paths(database, 24, random.Random(17))
            repeat = random_indexed_paths(database, 24, random.Random(17))
            scoped = random_indexed_paths(
                database, 24, random.Random(17), root=str(root.resolve()))
            self.assertEqual(first, repeat)
            self.assertEqual(len(first), 24)
            self.assertEqual(len({str(path) for path in first}), 24)
            self.assertTrue(all(path.is_relative_to(root) for path in scoped))


if __name__ == "__main__":
    unittest.main(verbosity=2)
