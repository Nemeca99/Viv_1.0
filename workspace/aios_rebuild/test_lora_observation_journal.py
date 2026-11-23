"""The chat journal records evidence but never reports a weight update."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lora_distill_engine import ConversationObservationJournal


class ObservationJournalTests(unittest.TestCase):
    def test_records_observation_without_training_or_manifest_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "observations.jsonl"
            journal = ConversationObservationJournal(path)
            receipt = journal.record_observation("write a function", "def f(): pass")
            self.assertEqual(receipt["status"], "LOGGED_NOT_TRAINED")
            row = json.loads(path.read_text(encoding="utf-8").strip())
            self.assertEqual(row["training_status"], "NOT_TRAINED")
            self.assertFalse(row["admitted_for_training"])
            self.assertEqual(len(row["source_sha256"]), 2)
            self.assertIn("NO_TRAINING", journal.distill_ltm_to_lora_dataset())


if __name__ == "__main__":
    unittest.main(verbosity=2)
