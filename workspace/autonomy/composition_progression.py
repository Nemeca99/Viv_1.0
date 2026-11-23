"""Evidence-only sentence and paragraph composition over Viv's learned routes.

This module never invents a sentence and never writes ontology edges.  It only
groups sentence records that already carry a verified relation path.  Paragraph
membership is therefore a derived observation, not a semantic fact.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Iterable, Mapping, Sequence


_WORD_RE = re.compile(r"[a-z][a-z'-]*", re.IGNORECASE)


@dataclass(frozen=True)
class SentenceEvidence:
    sentence: str
    sentence_hash: str
    sentence_type: str
    target: str | None
    relation_nodes: tuple[str, ...]
    provenance: tuple[Mapping[str, Any], ...]
    valid: bool
    novelty: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "sentence": self.sentence,
            "sentence_hash": self.sentence_hash,
            "sentence_type": self.sentence_type,
            "target": self.target,
            "relation_nodes": list(self.relation_nodes),
            "provenance": [dict(item) for item in self.provenance],
            "valid": self.valid,
            "novelty": self.novelty,
        }


def _hash_sentence(sentence: str) -> str:
    normalized = " ".join(sentence.casefold().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _relation_nodes(path: Sequence[Mapping[str, Any]] | None) -> tuple[str, ...]:
    nodes: list[str] = []
    for hop in path or ():
        for key in ("source", "target", "from", "to", "subject", "object"):
            value = hop.get(key)
            if value is not None:
                value = str(value).casefold().strip()
                if value and value not in nodes:
                    nodes.append(value)
    return tuple(nodes)


def validate_sentence_record(
    record: Mapping[str, Any],
    learned_words: Iterable[str],
    historical_hashes: set[str] | None = None,
    known_neurons: Iterable[str] = (),
) -> SentenceEvidence:
    """Validate an existing route record without using a static vocabulary.

    A sentence is admissible for composition only when its tokens are in the
    learned set and its record contains a non-empty provenance path.  This is
    deliberately stricter than grammatical plausibility: grammar alone cannot
    establish a grounded relationship.
    """
    sentence = str(record.get("sentence", "")).strip()
    tokens = {token.casefold() for token in _WORD_RE.findall(sentence)}
    learned = {
        str(word).casefold().strip()
        for word in (*learned_words, *known_neurons)
        if str(word).strip()
    }
    path = record.get("relation_path")
    provenance = tuple(path) if isinstance(path, (list, tuple)) else tuple()
    valid = bool(sentence and tokens and tokens.issubset(learned) and provenance)
    sentence_hash = _hash_sentence(sentence) if sentence else ""
    historical = historical_hashes or set()
    return SentenceEvidence(
        sentence=sentence,
        sentence_hash=sentence_hash,
        sentence_type=str(record.get("type", "UNKNOWN")),
        target=str(record.get("target") or record.get("word") or "") or None,
        relation_nodes=_relation_nodes(provenance),
        provenance=provenance,
        valid=valid,
        novelty=sentence_hash not in historical if sentence_hash else False,
    )


def compose_paragraphs(
    records: Sequence[Mapping[str, Any]],
    learned_words: Iterable[str],
    *,
    historical_hashes: set[str] | None = None,
    known_neurons: Iterable[str] = (),
    min_sentences: int = 2,
    max_sentences: int = 5,
) -> dict[str, Any]:
    """Build evidence-only paragraphs from relation-linked valid sentences.

    Sentences are never rewritten.  Two sentences are linked when their
    recorded provenance paths share a graph node.  The output is a report for
    tutor/evaluation use, not a write-back candidate.
    """
    evidence = [
        validate_sentence_record(item, learned_words, historical_hashes, known_neurons)
        for item in records
    ]
    valid = [item for item in evidence if item.valid]
    adjacency: dict[int, set[int]] = defaultdict(set)
    for left in range(len(valid)):
        for right in range(left + 1, len(valid)):
            if set(valid[left].relation_nodes) & set(valid[right].relation_nodes):
                adjacency[left].add(right)
                adjacency[right].add(left)

    visited: set[int] = set()
    paragraphs: list[dict[str, Any]] = []
    for start in range(len(valid)):
        if start in visited:
            continue
        component: list[int] = []
        stack = [start]
        while stack and len(component) < max_sentences:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            component.append(current)
            stack.extend(sorted(adjacency.get(current, ()), reverse=True))
        if len(component) < min_sentences:
            continue
        selected = [valid[index] for index in component]
        paragraphs.append({
            "paragraph_id": hashlib.sha256(
                json.dumps([item.sentence_hash for item in selected], separators=(",", ":")).encode()
            ).hexdigest(),
            "sentence_hashes": [item.sentence_hash for item in selected],
            "sentences": [item.sentence for item in selected],
            "shared_relation_nodes": sorted(set.intersection(*(set(item.relation_nodes) for item in selected))),
            "status": "DERIVED_PARAGRAPH",
            "ontology_writeback": False,
        })

    return {
        "valid_sentence_count": len(valid),
        "invalid_sentence_count": len(evidence) - len(valid),
        "novel_valid_sentence_count": sum(item.novelty for item in valid),
        "paragraph_count": len(paragraphs),
        "sentences": [item.to_dict() for item in evidence],
        "paragraphs": paragraphs,
    }

