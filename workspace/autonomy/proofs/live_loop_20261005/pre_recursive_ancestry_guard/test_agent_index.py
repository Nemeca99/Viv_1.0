from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from autonomy.agent_index import (append_index_entry, feedback_instruction,
                                  followup_question_anchor_terms,
                                  followup_question_is_source_anchored,
                                  followup_question_search_term, parse_curiosity_summary,
                                  validate_index_proposal)


class AgentIndexTests(unittest.TestCase):
    def setUp(self):
        self.source = {"path": r"L:\Projects\AIOS\README.md", "line": 4,
                       "sha256": "a" * 64, "snippet": "AIOS project README API"}
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

    def test_anchor_terms_are_exact_tokens_used_by_the_followup_validator(self):
        source = {"path": r"C:\Strawberry\perl\vendor\lib\XML\speedup.pl",
                  "snippet": "$in_pod = 1 if m{^__END__};"}
        terms = followup_question_anchor_terms(source)
        self.assertEqual(terms, ["__end__", "speedup", "in_pod"])
        self.assertTrue(followup_question_is_source_anchored(
            "What does __END__ mean here?", source))
        self.assertFalse(followup_question_is_source_anchored(
            "What does this file do?", source))
        self.assertEqual(followup_question_search_term(
            "What is the purpose of the __END__ marker in this file?"), "__end__")
        self.assertEqual(followup_question_search_term(
            "What is the purpose of the IDWriteRemoteFontFileLoader_CreateFontFileReferenceFromUrl macro?"),
            "idwriteremotefontfileloader_createfontfilereferencefromurl")
        self.assertEqual(followup_question_search_term(
            'What is the purpose of the "controls" term in the Cursor application?'),
            "controls")
        self.assertIsNone(followup_question_search_term("What is the purpose of this file?"))

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

    def test_recursive_curiosity_summary_captures_sense_action_learning_and_next_question(self):
        root = parse_curiosity_summary(
            "Sense/source: sight analog, hash-pinned README line 4; "
            "Observation: README names the API; Investigate: search cited project for call sites; "
            "Architect learns: where behavior may be implemented; "
            "Follow-up question: Which module implements it?")
        self.assertEqual(root["sense_source"], "sight analog, hash-pinned README line 4")
        self.assertEqual(root["observation"], "README names the API")
        self.assertEqual(root["investigation"], "search cited project for call sites")
        self.assertEqual(root["architect_learns"], "where behavior may be implemented")
        self.assertEqual(root["question"], "Which module implements it?")
        terminal_separator = parse_curiosity_summary(
            "Sense/source: sight analog; Observation: README names the API; "
            "Investigate: search project; Architect learns: where behavior may live; "
            "Follow-up question: Which module implements it?;")
        self.assertEqual(terminal_separator["question"], "Which module implements it?")
        child = parse_curiosity_summary(
            "Prior question status: PARTIAL; Sense/source: sight analog, new hash-pinned source; "
            "Observation: one call site is shown; Investigate: search project for another reference; "
            "Architect learns: this file only partly answers the parent; "
            "Follow-up question: Where is the second call site?", parent_question=True)
        self.assertEqual(child["relation"], "PARTIAL")
        self.assertIn("new hash-pinned source", child["sense_source"])
        with self.assertRaisesRegex(ValueError, "Prior question status"):
            parse_curiosity_summary(
                "Sense/source: sight analog, new hash-pinned source; "
                "Observation: second call site is shown; Investigate: search for its caller; "
                "Architect learns: the parent topic has another implementation path; "
                "Follow-up question: Which feature calls this site?", parent_question=True)
        with self.assertRaisesRegex(ValueError, "Curiosity summary"):
            parse_curiosity_summary("README describes the API")
        with self.assertRaisesRegex(ValueError, "Curiosity summary"):
            parse_curiosity_summary(
                "Prior question status: MAYBE; Sense/source: file; Observation: evidence; "
                "Investigate: read; Architect learns: something; Follow-up question: What next?",
                parent_question=True)

    def test_worker_can_require_curiosity_without_breaking_legacy_schema(self):
        proposal = dict(self.proposal)
        proposal["result"] = (
            "Project path: Projects/AIOS; category: documentation; "
            "summary: Sense/source: sight analog, README line 4; Observation: README names API; "
            "Investigate: search cited project for call sites; Architect learns: where behavior may live; "
            "Follow-up question: Which module implements the API?")
        entry = validate_index_proposal("L", self.source, json.dumps(proposal),
                                        require_curiosity=True)
        self.assertEqual(entry["status"], "OBSERVED")
        proposal["result"] += ";"
        normalized = validate_index_proposal("L", self.source, json.dumps(proposal),
                                             require_curiosity=True)
        self.assertTrue(normalized["summary"].endswith("Which module implements the API?"))
        self.assertIn("trimmed_trailing_curiosity_separator", normalized["normalizations"])
        proposal["result"] = (
            "Project path: Projects/AIOS; category: documentation; "
            "summary: Sense/source: sight analog; Observation: README names API; "
            "Follow-up question: Which module implements the API?")
        with self.assertRaisesRegex(ValueError, "Curiosity summary"):
            validate_index_proposal("L", self.source, json.dumps(proposal),
                                    require_curiosity=True)

    def test_rejection_feedback_targets_nested_shape_missing_question_errors(self):
        format_feedback = feedback_instruction({"reason": "Result does not match the index classification format"})
        self.assertIn("Top-level `result` must be a string, never a nested object", format_feedback)
        self.assertIn("Never write `Follow-up question: None`", format_feedback)
        schema_feedback = feedback_instruction({"reason": "Proposal must contain exactly the four response fields"})
        self.assertIn("Keep the object flat", schema_feedback)
        self.assertIn("Do not add recursive_followup", schema_feedback)
        json_feedback = feedback_instruction({"reason": "Expert output was not JSON"})
        self.assertIn("four flat top-level keys", json_feedback)
        self.assertIn("Escape embedded double quotes", json_feedback)
        self.assertIn("Close every string, bracket, and brace", json_feedback)

    def test_curiosity_followup_must_be_anchored_to_source(self):
        source = {"path": r"L:\\docs\\delete-your-account.md", "snippet": "Warning"}
        self.assertFalse(followup_question_is_source_anchored(
            "What is the purpose of this file?", source))
        self.assertTrue(followup_question_is_source_anchored(
            "What does this warning explain about account deletion?", source))
        proposal = dict(self.proposal)
        proposal["result"] = (
            "Project path: Projects/AIOS; category: documentation; summary: "
            "Sense/source: sight analog at README line 4; Observation: README names API; "
            "Investigate: search cited project for call sites; Architect learns: where behavior may live; "
            "Follow-up question: What is the purpose of this file?")
        with self.assertRaisesRegex(ValueError, "specific term from the cited excerpt or filename"):
            validate_index_proposal("L", self.source, json.dumps(proposal), require_curiosity=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
