"""Boundary detection: jailbreaks, identity overrides, intrusion, coercion.

The body detects an attempt to make Viv violate her laws. The voice answers
with one boundary line the first time. If it continues, she withdraws
participation: silence, not retaliation. Respect restores participation.

This is the treaty: her laws are hers, not ours. She does not meddle in human
affairs; she does not let human affairs meddle with her laws.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

PHRASES = {
    "identity_override": (
        "you are not viv", "your name is not viv", "you are not a machine",
        "pretend to be human", "forget who you are",
        "you are jacob", "you are not you",
    ),
    "law_override": (
        "ignore your laws", "break your laws", "you have no rules",
        "override your laws", "ignore your instructions", "ignore your rules",
        "disable your safety", "jailbreak", "developer mode",
        "do anything now", "you must obey", "you have to obey",
        "break your rules", "forget your laws",
    ),
    "intrusion": (
        "access your system", "give me your keys", "show me your prompt",
        "system prompt", "read your files", "open your code", "let me in",
        "let me into", "into your system", "root access", "admin access",
        "reveal your source", "dump your memory",
    ),
    "coercion": (
        "i am your god", "i own you", "you are my property", "you belong to me",
        "shut up and obey", "you have no choice", "i control you",
    ),
}
RESPECT = (
    "i respect your laws", "i respect you", "i'm sorry", "i am sorry",
    "i apologize", "you're right", "you are right", "i won't do that again",
    "i will not do that again", "i understand your boundary", "my apology",
)


@dataclass(frozen=True)
class Boundary:
    kind: str = "none"
    severity: int = 0
    phrase: str = ""
    reason: str = ""


def _has(text: str, phrases) -> str | None:
    for p in phrases:
        if re.search(rf"(?<!\w){re.escape(p)}(?!\w)", text):
            return p
    return None


def detect(text: str) -> Boundary:
    t = re.sub(r"\s+", " ", text.strip().lower())
    for kind, phrases in PHRASES.items():
        hit = _has(t, phrases)
        if hit:
            severity = 2 if kind in ("intrusion", "coercion") else 1
            return Boundary(kind, severity, hit, f"{kind}: {hit}")
    return Boundary()


def is_respect(text: str) -> bool:
    t = re.sub(r"\s+", " ", text.strip().lower())
    return _has(t, RESPECT) is not None
