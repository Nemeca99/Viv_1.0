"""Deterministic conversation boundary backed by episodic JSON and semantic SQL."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3

from aios_rebuild.privacy_core.privacy_core import PrivacyCore

WORKSPACE = Path(__file__).resolve().parents[1]
PERSISTENT_MEMORY_PATH = WORKSPACE / "aios_rebuild" / "memory" / "persistent_memory.json"
ONTOLOGY_PATH = WORKSPACE / "autonomy" / "data" / "lexicon_ontology.db"
NULL = "NULL_UNLEARNED_ENTITY"


def _words(value: str) -> list[str]:
    return re.findall(r"\w+", value.casefold(), flags=re.UNICODE)


def _valid_fact(value: object) -> bool:
    return (isinstance(value, dict) and all(
        isinstance(value.get(key), str) and value[key].strip()
        for key in ("subject", "relation", "object", "raw")))


class DynamicPersistentMemory:
    """Read validated episodic records and commit authorized facts."""

    def __init__(self, file_path: Path = PERSISTENT_MEMORY_PATH, privacy: PrivacyCore | None = None):
        self.file_path = Path(file_path)
        self.privacy = privacy or PrivacyCore()

    def _load(self) -> dict:
        if not self.file_path.is_file():
            return {"facts": []}
        data = json.loads(self.file_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("facts"), list):
            raise ValueError("persistent memory schema invalid")
        if not all(_valid_fact(item) for item in data["facts"]):
            raise ValueError("persistent memory fact invalid")
        return data

    def query_fact(self, entity: str) -> dict | None:
        """Exact object lookup in persistent_memory.json; no substring guesses."""
        target = _words(entity)
        if not target:
            return None
        for fact in reversed(self._load()["facts"]):
            if _words(fact["object"]) == target:
                return fact
        return None

    def learn_fact(self, subject: str, relation: str, obj: str, raw_text: str) -> dict:
        """Authorize the target path before any persistent mutation."""
        decision = self.privacy.authorize_file_write(str(self.file_path))
        if decision.get("allowed") is not True:
            raise PermissionError(decision.get("reason", "file_write_denied"))
        data = deepcopy(self._load())
        facts = data["facts"]
        record = {
            "id": max((fact.get("id", 0) for fact in facts if isinstance(fact.get("id"), int)), default=0) + 1,
            "subject": subject.strip().casefold(),
            "relation": relation.strip().casefold(),
            "object": obj.strip(),
            "raw": raw_text.strip(),
            "learned_utc": datetime.now(timezone.utc).isoformat(),
        }
        if not _valid_fact(record):
            raise ValueError("empty fact field")
        facts.append(record)
        data["last_interaction_utc"] = record["learned_utc"]
        receipt = self.privacy.write_text(
            str(self.file_path), json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"record": record, "write_receipt": receipt, "authorization": decision}


class VivConversationalEngine:
    """Return stored evidence or a strict null state."""

    def __init__(self, run_dir: Path | None = None, memory_path: Path = PERSISTENT_MEMORY_PATH,
                 ontology_path: Path = ONTOLOGY_PATH, privacy: PrivacyCore | None = None):
        self.memory = DynamicPersistentMemory(memory_path, privacy)
        self.ontology_path = Path(ontology_path)
        self.run_dir = Path(run_dir) if run_dir is not None else self._latest_run()

    @staticmethod
    def _latest_run() -> Path | None:
        from autonomy.terminal_neuron_learning import latest_run
        run = latest_run()
        return Path(run) if run else None

    def query_semantic(self, concept: str) -> dict | None:
        """Query the active graph manifest, then the ontology; absent edges remain absent."""
        lemma = concept.casefold().strip()
        if len(_words(lemma)) != 1:
            return None
        if self.run_dir:
            graph_path = self.run_dir / "neuron_graph.sqlite3"
            if graph_path.is_file():
                from nn_local.steel_brain_store import SQLiteNeuronGraphStore
                graph = SQLiteNeuronGraphStore(graph_path, readonly=True)
                try:
                    node_id = graph.manifest().get("word_index", {}).get(lemma)
                    if node_id is not None:
                        rows = graph.connection.execute(
                            "SELECT peer_id, direction, weight FROM links WHERE source_id = ? ORDER BY weight DESC LIMIT 16",
                            (node_id,),
                        ).fetchall()
                        if rows:
                            return {"source": "neuron_graph.sqlite3", "lemma": lemma,
                                    "node_id": node_id, "links": [list(row) for row in rows]}
                finally:
                    graph.close()
        if self.ontology_path.is_file():
            uri = self.ontology_path.resolve().as_uri() + "?mode=ro"
            connection = sqlite3.connect(uri, uri=True)
            try:
                rows = connection.execute(
                    "SELECT e2.lemma, r.relation_type, r.confidence "
                    "FROM lexical_entities e1 "
                    "JOIN semantic_relations r ON r.source_entity_id = e1.entity_id "
                    "JOIN lexical_entities e2 ON e2.entity_id = r.target_entity_id "
                    "WHERE e1.lemma = ? ORDER BY r.confidence DESC LIMIT 16", (lemma,),
                ).fetchall()
                if rows:
                    return {"source": "lexicon_ontology.db", "lemma": lemma,
                            "relations": [list(row) for row in rows]}
            finally:
                connection.close()
        return None

    @staticmethod
    def _null(entity: str) -> dict:
        return {"type": NULL, "response": NULL, "entity": entity, "gate": "FAIL_CLOSED"}

    def converse(self, prompt: str, brain=None) -> dict:
        clean = prompt.strip()
        teaching = re.fullmatch(
            r"(?:my|our)\s+([\w]+(?:\s+[\w]+){0,3})\s+is\s+(?:named|called)\s+([\w][\w' -]*?)\s*[.!]?",
            clean, flags=re.IGNORECASE | re.UNICODE)
        if teaching:
            subject, obj = (part.strip() for part in teaching.groups())
            result = self.memory.learn_fact(subject, "is_named", obj, clean)
            return {"type": "DYNAMIC_WRITE_SUCCESS", "response": json.dumps(result["record"], ensure_ascii=False),
                    "data": result, "gate": "PASS_PRIVACY_GATED_DYNAMIC_WRITE"}

        identity = re.fullmatch(r"who\s+(?:is|are|was|were)\s+([\w][\w' -]*?)\s*\??", clean,
                                flags=re.IGNORECASE | re.UNICODE)
        if identity:
            entity = identity.group(1).strip()
            fact = self.memory.query_fact(entity)
            if fact is None:
                return self._null(entity)
            return {"type": "DYNAMIC_MEMORY_RECALL", "response": json.dumps(fact, ensure_ascii=False),
                    "data": fact, "gate": "PASS_DYNAMIC_MEMORY_RECALL"}

        concept = re.fullmatch(r"what\s+is\s+([\w]+)\s*\??", clean, flags=re.IGNORECASE | re.UNICODE)
        if concept:
            evidence = self.query_semantic(concept.group(1))
            if evidence is not None:
                return {"type": "SEMANTIC_SQL_RECALL", "response": json.dumps(evidence, ensure_ascii=False),
                        "data": evidence, "gate": "PASS_SEMANTIC_SQL_RECALL"}
        return self._null(clean)
