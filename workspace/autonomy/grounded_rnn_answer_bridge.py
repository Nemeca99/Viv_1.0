"""Read-only grounded answer bridge for the admitted topology RNN candidate."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from autonomy.topology_integer_rnn import TopologyIntegerRNN

NULL_UNLEARNED_ENTITY = "NULL_UNLEARNED_ENTITY"
_STOP = {"a", "an", "and", "are", "is", "my", "the", "what", "who", "does", "do", "have"}


class GroundedRNNAnswerBridge:
    """Compose a candidate only from a fact retrieved from persistent memory."""

    def __init__(self, memory_path: str | Path, candidate_path: str | Path, *, topology_sha256: str):
        self.memory_path = Path(memory_path)
        self.candidate = TopologyIntegerRNN.load_candidate(candidate_path, expected_topology_sha256=topology_sha256)
        self.facts = json.loads(self.memory_path.read_text(encoding="utf-8")).get("facts", [])

    @staticmethod
    def _tokens(text: str) -> set[str]:
        normalized = unicodedata.normalize("NFKD", text.casefold()).encode("ascii", "ignore").decode("ascii")
        return {token for token in re.findall(r"[a-z]+", normalized) if token not in _STOP}

    @staticmethod
    def _anchor(token: str) -> tuple[int, int, int, int]:
        digest = hashlib.sha256(token.encode()).digest()
        return (int.from_bytes(digest[:2], "big") % 97, 1, 1, 1)

    def answer(self, question: str) -> dict[str, Any]:
        query_tokens = self._tokens(question)
        ranked = []
        for fact in self.facts:
            raw = str(fact.get("raw", ""))
            subject = str(fact.get("subject", ""))
            relation = str(fact.get("relation", ""))
            if "name" in query_tokens and "named" not in relation and "is_named" not in relation:
                continue
            searchable = " ".join((subject, relation, raw))
            overlap = query_tokens & self._tokens(searchable)
            structural_hits = query_tokens & self._tokens(subject + " " + relation)
            match_score = len(overlap) + len(structural_hits)
            if overlap:
                route = [self._anchor(token) for token in sorted(overlap)]
                route_score = self.candidate.route_score(route) if len(route) > 1 else 0
                ranked.append((match_score, route_score, fact, sorted(overlap)))
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        if not ranked or ranked[0][0] < 2:
            answer = NULL_UNLEARNED_ENTITY
            return {
                "answer": answer,
                "status": "HOLD",
                "evidence": [],
                "route_score": 0,
                "evidence_receipt": self._receipt(question, answer, [], 0),
            }
        _, route_score, fact, overlap = ranked[0]
        evidence = f"{self.memory_path}#facts[{fact.get('id')}]"
        answer = str(fact["raw"])
        return {
            "answer": answer,
            "status": "GROUNDED",
            "evidence": [evidence],
            "matched_tokens": overlap,
            "route_score": route_score,
            "evidence_receipt": self._receipt(question, answer, [evidence], route_score),
        }

    def _receipt(self, question: str, answer: str, evidence: list[str], route_score: int) -> dict[str, Any]:
        memory_hash = hashlib.sha256(self.memory_path.read_bytes()).hexdigest()
        return {
            "schema": "viv-grounded-rnn-answer-receipt-v1",
            "question_sha256": hashlib.sha256(question.encode()).hexdigest(),
            "answer_sha256": hashlib.sha256(answer.encode()).hexdigest(),
            "memory_sha256": memory_hash,
            "evidence": evidence,
            "route_score": route_score,
        }


__all__ = ["GroundedRNNAnswerBridge", "NULL_UNLEARNED_ENTITY"]
