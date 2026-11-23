"""Manual conversation smoke harness; performs no tools or model training.

The former harness automatically dispatched searches and called a function
that only journaled transcripts while reporting them as trained. Tool routing
now belongs to ``viv_chat_cli.py`` and model training belongs to the explicit
Dream candidate path.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, r"L:\LocalCoder\workspace")
sys.path.insert(0, r"L:\LocalCoder\workspace\aios_rebuild")

from viv_context_store import memory_store
from viv_chat_cli import ask_mind, get_mind_system_prompt, speak_viv
from aios_rebuild.lora_distill_engine import lora_engine


TEST_PROMPTS = [
    "Describe your current role without claiming consciousness or capabilities you cannot verify.",
    "What evidence would you need before saying an AIOS core is operational?",
    "Write a small Python function that adds two integers.",
]


def run_conversation_smoke_test(*, speak: bool = False) -> list[str]:
    """Exercise ordinary text turns only; no tools, training, or promotion."""
    replies: list[str] = []
    for prompt in TEST_PROMPTS:
        history = [
            {"role": "system", "content": get_mind_system_prompt()},
            {"role": "user", "content": prompt},
        ]
        reply = ask_mind(history).strip()
        memory_store.append_dialogue_turn("user", prompt)
        memory_store.append_dialogue_turn("assistant", reply)
        receipt = lora_engine.record_observation(prompt, reply)
        print(f"[Conversation]: {prompt}\n[Viv]: {reply}\n[{receipt['status']}]")
        if speak:
            speak_viv(reply, mode="human")
        replies.append(reply)
    return replies


if __name__ == "__main__":
    run_conversation_smoke_test(speak="--speak" in sys.argv[1:])
