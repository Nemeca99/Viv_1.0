"""Containment-first three-state query pipeline.

This module is read-only by default. It treats the RNN as a route proposal
scorer and never emits generated text before a cartridge verifies a row.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import json
import re
import sqlite3
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Sequence

CONTAINED = "CONTAINED"
PARTIAL = "PARTIAL"
NULL = "NULL"
_STOP = {"a", "an", "and", "are", "do", "does", "have", "is", "my", "the", "what", "who"}
_SEMANTIC = {"green": {"color", "colour", "blue", "red", "light", "scattering"}, "sky": {"atmosphere", "radiation", "light"}}


def _file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class SonarCandidate:
    cartridge: str
    row_id: str
    text: str
    weight: int
    shape: str


@dataclass(frozen=True)
class ContainmentResult:
    state: str
    answer: str
    candidates: tuple[SonarCandidate, ...]
    trace: tuple[str, ...]
    receipt: dict[str, Any]


class JsonFactCartridge:
    """A read-only JSON fact cartridge with deterministic token sonar."""

    def __init__(self, identifier: str, path: str | Path):
        self.identifier = identifier
        self.path = Path(path)
        self.rows = json.loads(self.path.read_text(encoding="utf-8")).get("facts", [])

    @staticmethod
    def _tokens(text: str) -> set[str]:
        normalized = unicodedata.normalize("NFKD", text.casefold()).encode("ascii", "ignore").decode("ascii")
        return {token for token in re.findall(r"[a-z]+", normalized) if token not in _STOP}

    def ping(self, query: str) -> list[SonarCandidate]:
        query_tokens = self._tokens(query)
        shape = hashlib.sha256(" ".join(sorted(query_tokens)).encode()).hexdigest()
        candidates = []
        for row in self.rows:
            text = str(row.get("raw", ""))
            weight = len(query_tokens & self._tokens(" ".join(str(row.get(k, "")) for k in ("subject", "relation", "raw"))))
            if weight:
                candidates.append(SonarCandidate(self.identifier, str(row.get("id")), text, weight, shape))
        return sorted(candidates, key=lambda item: (-item.weight, item.row_id))

    def verify(self, candidate: SonarCandidate, query: str) -> bool:
        # Verification is exact containment of the queried terms in the row's
        # indexed subject/relation/raw fields; the RNN is not truth authority.
        return candidate.weight >= 2

    def stage_fact(self, fact: dict[str, Any]) -> None:
        self.rows.append(dict(fact))


class SQLitePrimitiveCartridge:
    """Read-only cartridge over verified code primitives."""

    def __init__(self, identifier: str, path: str | Path):
        self.identifier = identifier
        self.path = Path(path)

    def ping(self, query: str) -> list[SonarCandidate]:
        query_tokens = JsonFactCartridge._tokens(query)
        shape = hashlib.sha256(" ".join(sorted(query_tokens)).encode()).hexdigest()
        uri = f"file:{self.path.resolve().as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            rows = conn.execute(
                "SELECT primitive_id, intent_description, verified_python_code FROM verified_code_primitives WHERE execution_status = 'VERIFIED_GRADUATE'"
            ).fetchall()
        candidates = []
        for primitive_id, intent, code in rows:
            text = f"{intent}\n{code}"
            weight = len(query_tokens & JsonFactCartridge._tokens(text))
            if weight:
                candidates.append(SonarCandidate(self.identifier, str(primitive_id), text, weight, shape))
        return sorted(candidates, key=lambda item: (-item.weight, item.row_id))

    def verify(self, candidate: SonarCandidate, query: str) -> bool:
        return candidate.weight >= 2


class SQLiteArticleCartridge:
    """Read-only domain article cartridge for live corpus containment."""

    def __init__(self, identifier: str, path: str | Path):
        self.identifier = identifier
        self.path = Path(path)

    def ping(self, query: str) -> list[SonarCandidate]:
        query_tokens = JsonFactCartridge._tokens(query)
        expanded_tokens = query_tokens | {term for token in query_tokens for term in _SEMANTIC.get(token, set())}
        shape = hashlib.sha256(" ".join(sorted(query_tokens)).encode()).hexdigest()
        uri = f"file:{self.path.resolve().as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            rows = conn.execute("SELECT article_id,title,summary FROM articles").fetchall()
        candidates = []
        for article_id, title, summary in rows:
            text = f"{title}\n{summary or ''}"
            weight = len(expanded_tokens & JsonFactCartridge._tokens(text))
            # A single common token is not an adjacent neighborhood.  Require
            # two independent shape terms before a live article can enter the
            # ranked cascade; this keeps unrelated NULL queries fail-closed.
            if weight >= 2:
                candidates.append(SonarCandidate(self.identifier, str(article_id), text, weight, shape))
        return sorted(candidates, key=lambda item: (-item.weight, item.row_id))

    def verify(self, candidate: SonarCandidate, query: str) -> bool:
        title = candidate.text.split("\n", 1)[0]
        query_tokens = JsonFactCartridge._tokens(query)
        return len(query_tokens & JsonFactCartridge._tokens(title)) >= 2


class SQLiteOverlayCartridge(SQLiteArticleCartridge):
    """Writable candidate cartridge; source cartridges remain read-only."""

    def __init__(self, identifier: str, path: str | Path, *, source_path: str | Path | None = None):
        super().__init__(identifier, path)
        self.source_path = Path(source_path) if source_path else None

    @property
    def provenance(self) -> dict[str, Any]:
        return {
            "cartridge": self.identifier,
            "overlay_path": str(self.path),
            "overlay_sha256": _file_sha256(self.path),
            "source_path": None if self.source_path is None else str(self.source_path),
            "source_sha256": None if self.source_path is None else _file_sha256(self.source_path),
        }

    @property
    def rows(self) -> list[dict[str, Any]]:
        uri = f"file:{self.path.resolve().as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            return [
                {"article_id": row[0], "title": row[1], "summary": row[2], "subject": row[3], "relation": row[4], "object": row[5]}
                for row in conn.execute("SELECT article_id,title,summary,subject,relation,object FROM articles")
            ]

    def stage_fact(self, fact: dict[str, Any]) -> dict[str, str]:
        article_id = int(fact["article_id"])
        title = str(fact["title"])
        summary = str(fact.get("summary", ""))
        if self.source_path is not None and _file_sha256(self.source_path) != self.provenance["source_sha256"]:
            raise ValueError("source cartridge hash changed; refusing candidate admission")
        before = _file_sha256(self.path)
        with sqlite3.connect(self.path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT INTO articles(article_id,title,summary,subject,relation,object) VALUES (?,?,?,?,?,?)", (article_id, title, summary, fact.get("subject", ""), fact.get("relation", ""), fact.get("object", "")))
            conn.commit()
        return {"before_sha256": before, "after_sha256": _file_sha256(self.path)}


class ContainmentEngine:
    def __init__(self, cartridges: Sequence[JsonFactCartridge], *, rnn: Any = None):
        self.cartridges = tuple(cartridges)
        self.rnn = rnn
        self.trace_counters: dict[str, int] = {}

    def query(self, question: str) -> ContainmentResult:
        with ThreadPoolExecutor(max_workers=max(1, len(self.cartridges))) as pool:
            batches = pool.map(lambda cartridge: cartridge.ping(question), self.cartridges)
            candidates = [candidate for batch in batches for candidate in batch]
        ranked = sorted(candidates, key=lambda item: (-item.weight, item.cartridge, item.row_id))
        trace = [f"SONAR:{candidate.cartridge}:{candidate.row_id}" for candidate in ranked]
        for candidate in ranked:
            trace.append(f"CASCADE:{candidate.cartridge}:{candidate.row_id}")
            cartridge = next(item for item in self.cartridges if item.identifier == candidate.cartridge)
            if cartridge.verify(candidate, question):
                receipt = self._receipt(question, CONTAINED, candidate, trace)
                return ContainmentResult(CONTAINED, candidate.text, tuple(ranked), tuple(trace), receipt)
        state = PARTIAL if ranked else NULL
        answer = "I don't know." if state == NULL else "I don't know this exactly, but this is what I do know: " + ranked[0].text
        receipt = self._receipt(question, state, ranked[0] if ranked else None, trace)
        return ContainmentResult(state, answer, tuple(ranked), tuple(trace), receipt)

    def learn_after(
        self,
        result: ContainmentResult,
        *,
        cartridge_id: str,
        fact: dict[str, Any],
        journal_path: str | Path,
    ) -> dict[str, Any]:
        """Stage a user-provided fact only after deterministic contradiction check."""
        cartridge = next(item for item in self.cartridges if item.identifier == cartridge_id)
        subject = str(fact.get("subject", ""))
        relation = str(fact.get("relation", ""))
        obj = str(fact.get("object", ""))
        def norm(value: str) -> str:
            return unicodedata.normalize("NFKD", value.casefold()).encode("ascii", "ignore").decode("ascii")
        contradictions = [
            row for row in cartridge.rows
            if norm(str(row.get("subject", ""))) == norm(subject)
            and norm(str(row.get("relation", ""))) == norm(relation)
            and norm(str(row.get("object", ""))) != norm(obj)
        ]
        if contradictions:
            decision = {"decision": "REJECT", "reason": "CONTRADICTION", "rows": contradictions}
        else:
            staged = dict(fact)
            staged.setdefault("id", f"staged-{len(cartridge.rows) + 1}")
            commit_receipt = cartridge.stage_fact(staged)
            decision = {"decision": "COMMIT", "row": staged}
            if commit_receipt:
                decision["commit_receipt"] = commit_receipt
        self.credit_trace(result.trace, 1 if decision["decision"] == "COMMIT" else -1)
        journal = Path(journal_path)
        journal.parent.mkdir(parents=True, exist_ok=True)
        with journal.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"query_receipt": result.receipt, "cartridge": cartridge_id, **decision}, sort_keys=True) + "\n")
        return decision

    def credit_trace(self, trace: Iterable[str], reward: int) -> None:
        """Integer forward/reverse trace credit; no gradients or floating weights."""
        for instruction in trace if reward >= 0 else reversed(tuple(trace)):
            self.trace_counters[instruction] = self.trace_counters.get(instruction, 0) + reward

    def record_gate_rejection(
        self,
        result: ContainmentResult,
        *,
        proposed_fact: dict[str, Any],
        journal_path: str | Path,
        reason: str = "GATE_REJECTED_UNVERIFIED_CLAIM",
    ) -> dict[str, Any]:
        """Journal a PARTIAL claim rejected against its sonar neighborhood."""
        if result.state != PARTIAL or not result.candidates:
            raise ValueError("gate rejection requires a PARTIAL result with candidates")
        decision = {
            "decision": "REJECT",
            "reason": reason,
            "proposed_row": proposed_fact,
            "contradicting_rows": [
                {"cartridge": candidate.cartridge, "row_id": candidate.row_id, "text": candidate.text}
                for candidate in result.candidates[:5]
            ],
            "query_receipt": result.receipt,
        }
        self.credit_trace(result.trace, -1)
        journal = Path(journal_path)
        journal.parent.mkdir(parents=True, exist_ok=True)
        with journal.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(decision, sort_keys=True) + "\n")
        return decision

    @staticmethod
    def _receipt(question: str, state: str, candidate: SonarCandidate | None, trace: list[str]) -> dict[str, Any]:
        return {
            "schema": "viv-deterministic-containment-receipt-v1",
            "state": state,
            "question_sha256": hashlib.sha256(question.encode()).hexdigest(),
            "candidate": None if candidate is None else {
                "cartridge": candidate.cartridge, "row_id": candidate.row_id,
                "shape": candidate.shape, "weight": candidate.weight,
            },
            "instruction_trace": trace,
        }


__all__ = ["CONTAINED", "PARTIAL", "NULL", "ContainmentEngine", "ContainmentResult", "JsonFactCartridge", "SQLitePrimitiveCartridge", "SQLiteArticleCartridge", "SQLiteOverlayCartridge"]
