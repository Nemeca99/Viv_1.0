from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from autonomy.agent_index import (append_index_entry, parse_curiosity_summary,
                                  validate_index_proposal)


class AgentIndexTests(unittest.TestCase):
    def setUp(self):
        self.source = {"path": r"L:\Projects\AIOS\README.md", "line": 4,
                       "sha256": "a" * 64, "snippet": "AIOS project readme"}
        self.proposal = {"status": "OBSERVED",
                         "result": "Project path: Projects/AIOS; category: documentation; summary: AIOS project README.",
                         "evidence": [r"L:\Projects\AIOS\README.md:4"], "unknowns": []}

    def test_expert_must_choose_an_existing_ancestor_and_exact_citation(self):
        entry = validate_index_proposal("L", self.source, json.dumps(self.proposal))
        self.assertEqual(entry["project"], "Projects/AIOS")
        self.assertEqual(entry["evidence"], [r"L:\Projects\AIOS\README.md:4"])
        invalid = dict(self.proposal, result="Project path: Projects/Imagined; category: documentation; summary: AIOS README.")
        with self.assertRaisesRegex(ValueError, "ancestor"):
            validate_index_proposal("L", self.source, json.dumps(invalid))
        invalid = dict(self.proposal, evidence=[r"L:\Projects\AIOS\README.md:5"])
        with self.assertRaisesRegex(ValueError, "exact supplied citation"):
            validate_index_proposal("L", self.source, json.dumps(invalid))

    def test_entry_is_append_only_and_deduplicated_by_source_hash(self):
        entry = validate_index_proposal("L", self.source, json.dumps(self.proposal))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, first_id, added = append_index_entry(root, entry)
            _, second_id, duplicate_added = append_index_entry(root, entry)
            self.assertEqual(first_id, second_id)
            self.assertTrue(added)
            self.assertFalse(duplicate_added)
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["schema"], "viv_agent_drive_index_v1")

    def test_unique_full_suffix_is_normalized_but_ambiguous_suffix_is_rejected(self):
        source = {"path": r"L:\root\branch\project\nested\file.py", "line": 9,
                  "sha256": "b" * 64}
        proposal = {"status": "OBSERVED",
                    "result": "Project path: project/nested; category: application; summary: source file.",
                    "evidence": [source["path"] + ":9"], "unknowns": []}
        entry = validate_index_proposal("L", source, json.dumps(proposal))
        self.assertEqual(entry["project"], "root/branch/project/nested")
        self.assertEqual(entry["normalizations"], ["unique_ancestor_suffix"])

        source["path"] = r"L:\root\x\branch\x\file.py"
        proposal["result"] = "Project path: x; category: application; summary: source file."
        proposal["evidence"] = [source["path"] + ":9"]
        with self.assertRaisesRegex(ValueError, "ancestor"):
            validate_index_proposal("L", source, json.dumps(proposal))

    def test_duplicate_json_fields_are_rejected(self):
        duplicate = ('{"status":"OBSERVED","result":"Project path: Projects/AIOS; '
                     'category: documentation; summary: AIOS README.","evidence":[], '
                     '"evidence":[],"unknowns":[]}')
        with self.assertRaisesRegex(ValueError, "repeats field 'evidence'"):
            validate_index_proposal("L", self.source, duplicate)

    def test_unambiguous_status_is_inferred_and_raw_response_is_preserved(self):
        proposal = {key: value for key, value in self.proposal.items() if key != "status"}
        raw = json.dumps(proposal)
        entry = validate_index_proposal("L", self.source, raw)
        self.assertEqual(entry["status"], "OBSERVED")
        self.assertEqual(entry["raw_proposal"], json.loads(raw))
        self.assertIn("inferred_status_from_consistent_fields", entry["normalizations"])

        unknown = {"result": "Project identity is unclear.", "evidence": [],
                   "unknowns": ["Which directory owns this file?"]}
        entry = validate_index_proposal("L", self.source, json.dumps(unknown))
        self.assertEqual(entry["status"], "UNKNOWN")
        self.assertEqual(entry["evidence"], [])

    def test_recursive_curiosity_summary_requires_observation_and_one_question(self):
        root = parse_curiosity_summary(
            "Observation: README describes the API; Follow-up question: Which module implements it?")
        self.assertEqual(root["observation"], "README describes the API")
        self.assertEqual(root["question"], "Which module implements it?")
        child = parse_curiosity_summary(
            "Prior question status: PARTIAL; Observation: one call site is shown; "
            "Follow-up question: Where is the second call site?", parent_question=True)
        self.assertEqual(child["relation"], "PARTIAL")
        with self.assertRaisesRegex(ValueError, "Curiosity summary"):
            parse_curiosity_summary("README describes the API")
        with self.assertRaisesRegex(ValueError, "Curiosity summary"):
            parse_curiosity_summary(
                "Prior question status: MAYBE; Observation: evidence; "
                "Follow-up question: What next?", parent_question=True)

    def test_worker_can_require_curiosity_without_breaking_legacy_schema(self):
        proposal = dict(self.proposal)
        proposal["result"] = (
            "Project path: Projects/AIOS; category: documentation; "
            "summary: Observation: README names the API; Follow-up question: Which module implements it?")
        entry = validate_index_proposal("L", self.source, json.dumps(proposal),
                                        require_curiosity=True)
        self.assertEqual(entry["status"], "OBSERVED")
        proposal["result"] = (
            "Project path: Projects/AIOS; category: documentation; summary: README names the API.")
        with self.assertRaisesRegex(ValueError, "Curiosity summary"):
            validate_index_proposal("L", self.source, json.dumps(proposal),
                                    require_curiosity=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
