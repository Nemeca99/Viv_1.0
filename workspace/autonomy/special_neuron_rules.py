"""Deterministic transition rules for Viv's 26 character neurons plus SHIFT."""
from __future__ import annotations

import string

SPECIAL_NEURONS = tuple(string.ascii_lowercase) + ("SHIFT",)


def step_character_layer(active: set[str], token: str, *, shift: bool = False) -> set[str]:
    """Advance the control layer for one token without mutating word neurons.

    A character neuron is active when its character occurs in the token. SHIFT
    is a one-step mode marker for capitalization; it is never treated as a
    normal word-neuron birth or death.
    """
    token_letters = {char.lower() for char in token if char.lower() in string.ascii_lowercase}
    next_active = {char for char in active if char in token_letters}
    next_active.update(token_letters)
    if shift:
        next_active.add("SHIFT")
    else:
        next_active.discard("SHIFT")
    return next_active


def validate_special_layer(active: set[str]) -> bool:
    return active <= set(SPECIAL_NEURONS)
