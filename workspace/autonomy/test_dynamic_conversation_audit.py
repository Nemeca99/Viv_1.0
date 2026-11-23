"""Behavioral probes for the episodic and semantic conversation boundary."""

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from autonomy.viv_conversational_engine import (
    NULL, PERSISTENT_MEMORY_PATH, VivConversationalEngine,
)


class DenyingPrivacy:
    def authorize_file_write(self, path):
        return {"allowed": False, "reason": "audit_denial"}

    def write_text(self, *args, **kwargs):
        raise AssertionError("write attempted after denial")


class DynamicConversationAudit(unittest.TestCase):
    def test_fail_closed_and_dynamic_learning(self):
        with tempfile.TemporaryDirectory(dir=PERSISTENT_MEMORY_PATH.parent) as directory:
            memory = Path(directory) / "persistent_memory.json"
            memory.write_text('{"facts": []}', encoding="utf-8")
            engine = VivConversationalEngine(run_dir=Path(directory), memory_path=memory,
                                            ontology_path=Path(directory) / "missing.db")
            unknown = engine.converse("Who is Sarah?")
            self.assertEqual(unknown["response"], NULL)
            self.assertEqual(unknown["type"], NULL)
            learned = engine.converse("My dog is named Buster.")
            self.assertTrue(learned["data"]["authorization"]["allowed"])
            self.assertTrue(learned["data"]["write_receipt"]["allowed"])
            stored = json.loads(memory.read_text(encoding="utf-8"))
            self.assertEqual(stored["facts"][-1]["object"], "Buster")
            recalled = VivConversationalEngine(run_dir=Path(directory), memory_path=memory).converse("Who is Buster?")
            self.assertEqual(recalled["type"], "DYNAMIC_MEMORY_RECALL")
            self.assertEqual(recalled["data"], stored["facts"][-1])
            print("A:", unknown)
            print("B write:", learned["data"]["authorization"], learned["data"]["write_receipt"])
            print("B recall:", recalled)

    def test_denial_leaves_memory_unchanged(self):
        with tempfile.TemporaryDirectory(dir=PERSISTENT_MEMORY_PATH.parent) as directory:
            memory = Path(directory) / "persistent_memory.json"
            memory.write_text('{"facts": []}', encoding="utf-8")
            engine = VivConversationalEngine(run_dir=Path(directory), memory_path=memory,
                                            privacy=DenyingPrivacy())
            with self.assertRaises(PermissionError):
                engine.converse("My dog is named Buster.")
            self.assertEqual(json.loads(memory.read_text(encoding="utf-8")), {"facts": []})

    def test_semantics_require_database_edges(self):
        with tempfile.TemporaryDirectory(dir=PERSISTENT_MEMORY_PATH.parent) as directory:
            root = Path(directory)
            db = root / "lexicon_ontology.db"
            connection = sqlite3.connect(db)
            try:
                connection.executescript("CREATE TABLE lexical_entities (entity_id INTEGER PRIMARY KEY, lemma TEXT); "
                                         "CREATE TABLE semantic_relations (source_entity_id INTEGER, target_entity_id INTEGER, relation_type TEXT, confidence REAL); "
                                         "INSERT INTO lexical_entities VALUES (1, 'wheel'), (2, 'axle'); "
                                         "INSERT INTO semantic_relations VALUES (1, 2, 'connects', 1.0);")
            finally:
                connection.close()
            engine = VivConversationalEngine(run_dir=root, memory_path=root / "missing.json", ontology_path=db)
            self.assertEqual(engine.converse("What is wheel?")["data"]["relations"], [["axle", "connects", 1.0]])
            self.assertEqual(engine.converse("What is shadow?")["response"], NULL)


if __name__ == "__main__":
    unittest.main()
