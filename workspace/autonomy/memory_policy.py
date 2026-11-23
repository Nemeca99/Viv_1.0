"""Attention and memory policy: listen for the name, keep only what was for her.

Rules from the Architect:
- She listens for "Viv", "hey", "hey you", and direct address. Without one of
  those she does not respond unless she reasons the input is for her.
- Every input is observed into a RAM buffer first.
- Only input that was for her may go to the HD (persistent store).
- Unaddressed input is dumped, not remembered.
- She does not remember until an intent needs the memory.

Nothing here writes without an authorization callable. No authorizer means no
write: assume no before saying yes.
"""
from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass, field

from grade_dreams import grade

WAKE_MARKERS = ("viv", "hey you")
WAKE_STARTS = ("hey", "hi", "hello")
INTENT_MARKERS = (
    "remember", "recall", "last time", "earlier", "before", "you said",
    "we talked", "do you know", "my name", "what did i", "remind me",
    "we discussed", "previously",
)
STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "then", "that", "this", "these",
    "those", "is", "are", "was", "were", "be", "been", "am", "do", "does", "did",
    "i", "you", "we", "he", "she", "it", "they", "me", "my", "your", "our",
    "to", "of", "in", "on", "for", "with", "at", "by", "from", "as", "what",
    "who", "how", "why", "when", "where", "can", "could", "would", "should",
}


def is_wake(text: str) -> bool:
    """The name, 'hey you', or a greeting that opens an address."""
    t = text.strip().lower()
    return ("viv" in t or "hey you" in t
            or any(t.startswith(w) for w in WAKE_STARTS))


def intent_needs_memory(text: str) -> bool:
    """Retrieval is intent-driven, not continuous."""
    t = text.strip().lower()
    return any(m in t for m in INTENT_MARKERS)


def _terms(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z']+", text.lower()) if w not in STOPWORDS}


@dataclass
class InputRecord:
    text: str
    at: float
    addressed: bool
    act: str
    shape: str
    persisted: bool = False


class InputBuffer:
    """RAM only. Every input is observed; only addressed input may persist."""

    def __init__(self, capacity: int = 64):
        self.capacity = capacity
        self.records: deque[InputRecord] = deque(maxlen=capacity)

    def observe(self, text: str, decision) -> InputRecord:
        rec = InputRecord(text=text, at=time.time(), addressed=decision.addressed,
                          act=decision.act, shape=decision.shape)
        self.records.append(rec)
        return rec

    def for_persistence(self) -> list[InputRecord]:
        return [r for r in self.records if r.addressed and not r.persisted]

    def dump_unaddressed(self) -> int:
        """Drop ambient input from RAM. Returns how many were dumped."""
        before = len(self.records)
        self.records = deque((r for r in self.records if r.addressed),
                             maxlen=self.capacity)
        return before - len(self.records)


class MemoryStore:
    """Persistent store. Writes require an explicit authorizer (fail closed).

    The authorizer is the existing PrivacyCore gate in the live path; tests
    inject a lambda. No authorizer means every persist is refused.
    """

    def __init__(self, authorize=None):
        self.authorize = authorize
        self.records: list[dict] = []
        self.refused = 0
        self.dropped = 0

    def persist(self, rec: InputRecord) -> tuple[bool, str]:
        if not rec.addressed:
            self.dropped += 1
            return False, "not addressed to Viv"
        if self.authorize is None:
            self.refused += 1
            return False, "no authorizer; assume no"
        if not self.authorize():
            self.refused += 1
            return False, "authorizer refused"
        self.records.append({"text": rec.text, "at": rec.at, "act": rec.act})
        rec.persisted = True
        return True, "persisted"

    def retrieve(self, query: str, limit: int = 5) -> list[dict]:
        """Only when an intent needs memory; otherwise return nothing."""
        if not intent_needs_memory(query):
            return []
        terms = _terms(query)
        if not terms:
            return []
        scored = []
        for r in self.records:
            score = len(terms & _terms(r["text"]))
            if score:
                scored.append((score, r))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [r for _s, r in scored[:limit]]


@dataclass
class Observation:
    text: str
    at: float
    addressed: bool
    reasonable: bool
    verified: bool
    reason: str = ""


class KnowledgeGate:
    """Observe -> reason -> verify -> persist only if reasonable.

    Even an indirect observation may be learned, but only after verification:
    "does this make sense?" If it is not verified, it stays in RAM and is never
    written to the HD. No verifier or no authorizer means no write.
    """

    def __init__(self, verifier=None, authorizer=None):
        self.verifier = verifier
        self.authorizer = authorizer
        self.persisted: list[dict] = []
        self.dropped = 0
        self.refused = 0

    def assess(self, text: str, addressed: bool = False) -> Observation:
        score, violations = grade(text)
        reasonable = bool(text.strip()) and score == 0
        if self.verifier is None:
            verified, why = False, "no verifier; assume no"
        else:
            verified, why = self.verifier(text)
        reason = f"law violation: {violations}" if score else why
        return Observation(text, time.time(), addressed, reasonable, verified, reason)

    def persist(self, obs: Observation) -> tuple[bool, str]:
        if not obs.reasonable:
            self.dropped += 1
            return False, obs.reason or "not reasonable"
        if not obs.verified:
            self.dropped += 1
            return False, obs.reason or "unverified; keep in RAM"
        if self.authorizer is None:
            self.refused += 1
            return False, "no authorizer; assume no"
        if not self.authorizer():
            self.refused += 1
            return False, "authorizer refused"
        self.persisted.append({"text": obs.text, "at": obs.at,
                               "addressed": obs.addressed})
        return True, "persisted"
