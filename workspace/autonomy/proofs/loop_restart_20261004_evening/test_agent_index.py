from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from autonomy.agent_index import append_index_entry, validate_index_proposal


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
