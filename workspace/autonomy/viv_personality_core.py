"""Compatibility interface for grounded conversational evaluation."""

from __future__ import annotations

from autonomy.viv_conversational_engine import VivConversationalEngine


class VivPersonalityCore:
    """Delegate to persistent memory and semantic topology queries."""

    def __init__(self, memory_store=None):
        self.engine = VivConversationalEngine()

    def evaluate_personality_turn(self, prompt: str, brain=None) -> dict:
        return self.engine.converse(prompt, brain=brain)
