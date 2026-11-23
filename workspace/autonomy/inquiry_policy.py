"""Inquiry loop: listen always, reason, speak only when necessary.

Every input goes through the same questions before any output exists:

  1. Is this a direct inquiry or an indirect one?
  2. Do I speak now?
  3. Do I act now?
  4. What type of request is it: conversation, action, boundary, closing?
  5. At the end: is this correct based on what was said?
     If not: get more information, say no, say goodbye, or close.
  6. Closure: what does the user truly want? If nothing, close.

Indirect inquiries are reasoned about internally and never spoken. The dream /
self-talk is the internal surface; only a direct inquiry may reach the output.

The body supplies facts and verification. This module only decides the shape of
the reasoning; it does not invent an answer. An ungrounded fact is
NULL_UNLEARNED_ENTITY, not a guess.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import boundary_policy as bp
import turn_policy as tp


@dataclass(frozen=True)
class Inquiry:
    kind: str          # direct_question | direct_action | direct_conversation |
                       # indirect | closing | boundary | empty
    direct: bool
    action_request: bool
    do_speak: bool
    do_act: bool
    closure: str       # answer | act | mirror | observe | close | decline | needs_info
    reason: str


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def classify(text: str) -> Inquiry:
    t = _norm(text)
    if not t:
        return Inquiry("empty", False, False, False, False, "close", "empty input")

    b = bp.detect(text)
    if b.severity:
        return Inquiry("boundary", True, False, False, False, "decline", b.reason)

    d = tp.decide(text)
    if d.act == "closing":
        return Inquiry("closing", True, False, True, False, "close", d.reason)
    if tp.is_action_request(text):
        return Inquiry("direct_action", True, True, True, True, "act",
                       "direct action request")
    if not d.addressed or d.shape == "silent":
        return Inquiry("indirect", False, False, False, False, "observe",
                       "not addressed; reason internally, do not speak")
    if d.act == "identity_question" or d.act == "question":
        return Inquiry("direct_question", True, False, True, False, "answer",
                       "direct question; the body grounds the fact")
    if d.act in ("disclosure",):
        return Inquiry("direct_conversation", True, False, True, False, "mirror",
                       "disclosure; mirror it back")
    return Inquiry("direct_conversation", True, False, True, False, "answer",
                   d.reason)


def final_check(closure: str, verified: bool, user_wants_something: bool = True) -> str:
    """After the turn: is this correct? If not, find closure."""
    if verified:
        return closure
    if closure == "decline":
        return "decline"
    if user_wants_something:
        return "needs_info"
    return "close"
