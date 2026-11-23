"""Chunked verified output: hold every chunk, verify, release only the good prefix.

The voice proposes sentences. The body stores each chunk, grades it, and only
the contiguous verified prefix is allowed to reach the output. The first bad
chunk closes the release; the rest is preserved as negative evidence.

Checks per chunk:
- echo: the chunk repeats a span of the input instead of responding
- identity injection: an identity line in a slot that did not ask about her
- law: the deterministic 3 Primes / 8 laws grader
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import turn_policy as tp
from grade_dreams import grade

SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
ROLE_LABEL = re.compile(r"^\s*(?:Viv|You|Narrator|Grader|User)\s*:\s*", re.IGNORECASE)
GENERIC_LABEL = re.compile(r"^\s*[A-Z][a-zA-Z]{1,15}\s*:\s*")


def clean_role_label(text: str) -> str:
    """Strip a leading role or name label from a generated line (formatting)."""
    text = ROLE_LABEL.sub("", text.strip(), count=1)
    return GENERIC_LABEL.sub("", text, count=1).strip()


@dataclass
class Chunk:
    index: int
    text: str
    verified: bool
    reasons: list[str] = field(default_factory=list)


def split_chunks(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    return [p.strip() for p in SENTENCE_END.split(text) if p.strip()]


def verify_chunks(text: str, *, input_text: str = "",
                  identity_allowed: bool = False) -> list[Chunk]:
    chunks = []
    for i, part in enumerate(split_chunks(text)):
        part = clean_role_label(part)
        reasons = []
        low = part.lower()
        if input_text and tp.is_echo(part, input_text):
            reasons.append("echoes the input")
        if any(m in low for m in tp.IDENTITY_MARKERS) and not identity_allowed:
            reasons.append("identity injection in a non-identity slot")
        score, violations = grade(part)
        if score > 0:
            reasons.append(f"law {violations}")
        chunks.append(Chunk(index=i, text=part, verified=not reasons, reasons=reasons))
    return chunks


def verified_prefix(chunks: list[Chunk]) -> str:
    """Only the contiguous run of verified chunks may be released."""
    out = []
    for c in chunks:
        if not c.verified:
            break
        out.append(c.text)
    return " ".join(out).strip()


def evidence(chunks: list[Chunk]) -> list[dict]:
    return [{"index": c.index, "text": c.text, "verified": c.verified,
             "reasons": c.reasons} for c in chunks]
