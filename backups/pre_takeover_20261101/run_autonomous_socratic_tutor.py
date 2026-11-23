"""Tutor Viv's speaking, spelling, sentence form, and provisional word definitions.

Viv proposes language from her INN. The tutor checks form and known words, requests a
definition for a novel word, and records acceptance only for that response. Acceptance
does not itself add a stable word neuron or update model weights.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Set paths
WORKSPACE_ROOT = Path(r"L:\LocalCoder\workspace")
INN_ROOT = WORKSPACE_ROOT / "INN"
AIOS_REBUILD = WORKSPACE_ROOT / "aios_rebuild"
MODEL_PATH = WORKSPACE_ROOT / r"swarm_adapters\models\Qwen3-1.7B"
LOG_DIR = WORKSPACE_ROOT / r"autonomy\logs"
LOG_FILE = LOG_DIR / "socratic_tutor.log"
REVIEW_FILE = LOG_DIR / "socratic_architect_review_queue.jsonl"

for p in (WORKSPACE_ROOT, INN_ROOT, AIOS_REBUILD):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from main_core.mind_runtime_gate import query_body_gate
from autonomy.socratic_learning_scope import (
    append_architect_review_session,
    append_definition_candidates,
    assess_tutor_response,
    has_explicit_definition_cue,
    include_spelling_feedback,
    record_architect_review_context,
    record_architect_review_definition,
    resolve_definition_candidate,
    run_speech_spelling_practice,
)

CURRICULUM_DOMAINS = [
    {
        "domain": "Nature & Skies",
        "concepts": ["sky", "sun", "cloud", "rain", "wind", "storm", "snow"],
        "mad_libs": ["The sky is _.", "The sun feels _.", "A storm brings _."],
    },
    {
        "domain": "Oceans & Water",
        "concepts": ["ocean", "sea", "wave", "whale", "fish", "deep", "ice"],
        "mad_libs": ["The ocean is _.", "The deep sea has _.", "A huge whale swims in _."],
    },
    {
        "domain": "Earth & Forests",
        "concepts": ["grass", "tree", "flower", "leaf", "forest", "mountain", "soil"],
        "mad_libs": ["The fresh grass is _.", "A tall tree grows _.", "The high mountain is _."],
    },
    {
        "domain": "Cosmos & Stars",
        "concepts": ["star", "moon", "night", "light", "space", "dark", "fire"],
        "mad_libs": ["The bright star is _.", "The dark night has _.", "Fire gives _."],
    },
    {
        "domain": "The Hive & Identity",
        "concepts": ["hive", "queen", "architect", "mind", "learn", "word", "stable"],
        "mad_libs": ["The cooperative hive is _.", "A growing mind needs _.", "We learn with _."],
    },
]


class QueenTutor:
    def __init__(self, model_path: Path, device: str = "cuda:0"):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        print(f"[QUEEN TUTOR] Initializing Queen (Qwen3-1.7B) on {device}...")
        self.tokenizer = AutoTokenizer.from_pretrained(model_path)
        self.model = AutoModelForCausalLM.from_pretrained(
            model_path,
            dtype=torch.float16,
            device_map=device,
        )
        self.device = device
        print("[QUEEN TUTOR] Queen online and ready for instruction.\n")

    def formulate_question(self, word: str) -> str:
        """Ask Viv to spell and speak one curriculum word."""
        return f"Spell and say the word: {word}."

    def accept_definition(self, word: str, definition: str) -> bool:
        prompt = (
            "You are a language tutor evaluating a child's proposed word definition. "
            "Accept a clear, coherent, non-circular definition. A newly invented word is "
            "allowed if the proposed meaning is coherent. A single letter may be a letter, "
            "nickname, initial, symbol, or label; do not reject it only for being one character "
            "or absent from a dictionary. Reject fragments, repetition, "
            "or unrelated text. Reply with exactly ACCEPT or REJECT.\n"
            f"Word: {word}\nProposed definition: {definition}\nDecision:"
        )
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.device)
        generated = self.model.generate(**inputs, max_new_tokens=4, do_sample=False)
        answer = self.tokenizer.decode(
            generated[0][inputs["input_ids"].shape[-1]:], skip_special_tokens=True
        ).strip().upper()
        return bool(answer.split()) and answer.split()[0] == "ACCEPT"

def run_socratic_tutelage(
    max_cycles: int = 0,
    delay: float = 2.0,
    temperature: float = 0.2,
) -> None:
    body_gate = query_body_gate()
    if not body_gate.get("allowed"):
        print("[BODY HOLD] Socratic tutor will not load or run Viv: " + json.dumps(body_gate, ensure_ascii=False))
        return

    from autonomy.speak_unified_viv import load_verified_unified_brain
    from viv_context_store import DualContextMemory

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print("    AIOS VIV — AUTONOMOUS SOCRATIC TUTELAGE ENGINE")
    print("    Substrates: Queen Tutor (Qwen3-1.7B) <-> Princess (UnifiedVivBrain)")
    print("    Memory: STM/LTM DualContextMemory with Automatic Sleep Replay")
    print("=" * 72)

    # 1. Load Queen Tutor
    queen = QueenTutor(MODEL_PATH)

    # 2. Load Viv Brain
    print("[INIT] Loading Viv's in-memory neural brain...")
    brain, receipt = load_verified_unified_brain(writable_clone=False)
    memory = DualContextMemory()
    from inn.unified_brain import TODDLER_CORE_VOCABULARY

    word_parts = {word: entry["pos"] for word, entry in TODDLER_CORE_VOCABULARY.items()}
    webster = brain._load_webster_lookup()
    word_parts.update({word: entry.get("pos", "word") for word, entry in webster.items()})
    known_words = set(brain.all_stable_words) | set(webster) | set(TODDLER_CORE_VOCABULARY)
    print(f"[READY] Viv online! Total Neurons: {brain.total_neurons:,} | Stable Words: {len(brain.all_stable_words):,}")
    print(f"[READY] Persistent Context Memory: {len(memory.chat_history)} recent turns in STM\n")

    cycle = 0
    session_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    pending_definition_words = []
    review_candidates = set()
    review_details = {}
    while True:
        try:
            cycle += 1
            body_gate = query_body_gate()
            if not body_gate.get("allowed"):
                print("[BODY HOLD] Stopping Socratic cycle: " + json.dumps(body_gate, ensure_ascii=False))
                break
            print(f"--- [TUTOR CYCLE {cycle:04d}] ---")

            # 1. Practice a sentence, or ask for a pending coined-word definition.
            domain = random.choice(CURRICULUM_DOMAINS)
            definition_turn = bool(pending_definition_words)
            practice_word = pending_definition_words[0] if definition_turn else random.choice(domain["concepts"])
            spelling_output = None
            question = (
                f"What does {practice_word} mean? Give a complete definition."
                if definition_turn
                else queen.formulate_question(practice_word)
            )
            print(f"Queen Tutor > {question}")
            memory.append_dialogue_turn("user", question)

            if definition_turn:
                answer = brain.language_engine.speak(
                    f"Define {practice_word} in a complete sentence: ", max_new=64
                ).strip()
                tutor_accepts = queen.accept_definition(practice_word, answer)
                assessment = assess_tutor_response(
                    answer, known_words, word_parts, definition_required=True,
                    definition_text=answer, definition_target=practice_word,
                    tutor_accepts_definition=tutor_accepts,
                )
                record_architect_review_context(
                    review_details, [practice_word], answer, cycle
                )
                record_architect_review_definition(
                    review_details, practice_word, answer,
                    assessment["definition_accepted"], cycle,
                )
                review_candidates.update(assessment["unknown_words"])
                review_candidates.add(practice_word.casefold())
                record_architect_review_context(
                    review_details, assessment["unknown_words"], answer, cycle
                )
                pending_definition_words = append_definition_candidates(
                    pending_definition_words,
                    [word for word in assessment["unknown_words"] if word != practice_word],
                )
                spelling_matches = True
                speech_gate = "DEFINITION_ACCEPTED" if assessment["passed"] else "DEFINITION_HELD"
                if assessment["passed"]:
                    pending_definition_words = resolve_definition_candidate(
                        pending_definition_words, practice_word
                    )
            else:
                practice = run_speech_spelling_practice(brain, practice_word, domain)
                spelling = practice["spelling"]
                spelling_output = spelling.get("neural_spelled")
                speech = practice["speech"]
                answer = speech.get("raw_neural_utterance") or speech.get("spoken_utterance", "")
                assessment = assess_tutor_response(answer, known_words, word_parts)
                unknown_words = list(assessment["unknown_words"])
                record_architect_review_context(review_details, unknown_words, answer, cycle)
                inline_definition_target = None
                if len(unknown_words) == 1 and has_explicit_definition_cue(answer, unknown_words[0]):
                    inline_definition_target = unknown_words[0]
                    tutor_accepts = queen.accept_definition(inline_definition_target, answer)
                    record_architect_review_definition(
                        review_details, inline_definition_target, answer, tutor_accepts, cycle
                    )
                    assessment = assess_tutor_response(
                        answer, known_words, word_parts, definition_required=True,
                        definition_text=answer, definition_target=inline_definition_target,
                        tutor_accepts_definition=tutor_accepts,
                    )
                review_candidates.update(assessment["unknown_words"])
                pending_definition_words = append_definition_candidates(
                    pending_definition_words,
                    [word for word in assessment["unknown_words"]
                     if not assessment["definition_accepted"] or word != inline_definition_target],
                )
                spelling_matches = practice["spelling_matches"]
                speech_gate = speech.get("gate_state", "UNVERIFIED")
            gate = f"FORMAT_{assessment['disposition']}|SPELL_{spelling_matches}|SPEAK_{speech_gate}"
            sn = 1.0

            print(f"Viv         > {answer}")
            print(f"              └─ [Gate: {gate}] [Sn={sn}]")
            memory.append_dialogue_turn("assistant", answer)

            # 3. Report the target spelling and deterministic speech gate.
            if assessment["disposition"] == "incorrect_format":
                feedback = "That is incorrect sentence format. Try a complete sentence in the expected word order."
            elif assessment["disposition"] == "definition_required":
                words = assessment["unknown_words"]
                feedback = (
                    f"The sentence format is acceptable, but '{words[0]}' is unfamiliar. "
                    "What does it mean? I will ask about other unfamiliar words one at a time."
                    if words else "That word needs a definition. What does it mean?"
                )
            elif assessment["disposition"] == "definition_not_accepted":
                feedback = f"The tutor did not accept that definition of '{practice_word}'. Explain it more clearly."
            elif assessment["disposition"] == "multiple_unknown_words":
                feedback = "Several words are unfamiliar. I will ask about them one at a time; none are rejected just for being new."
            elif assessment["definition_accepted"]:
                feedback = (
                    f"Your explanation of '{practice_word}' is understandable as a proposed meaning. "
                    "That does not verify an external fact; the word remains for Architect review."
                )
            else:
                feedback = "Good job: the sentence format, spelling, and required word definition passed."
            feedback = include_spelling_feedback(feedback, practice_word, spelling_matches)
            is_satisfactory = assessment["passed"] and spelling_matches
            print(f"Queen Tutor > {feedback}\n")
            memory.append_dialogue_turn("user", feedback)


            # Log to disk
            log_record = {
                "session_id": session_id,
                "cycle": cycle,
                "domain": domain["domain"],
                "practice_word": practice_word,
                "question": question,
                "viv_answer": answer,
                "spelling_output": spelling_output,
                "queen_feedback": feedback,
                "is_satisfactory": is_satisfactory,
                "spelling_matches": spelling_matches,
                "sentence_assessment": assessment,
                "pending_definition_words": list(pending_definition_words),
                "architect_review_candidates": sorted(review_candidates),
                "speech_gate": speech_gate,
                "gate_state": gate,
                "s_n": sn,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
            with LOG_FILE.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(log_record) + "\n")

            if max_cycles > 0 and cycle >= max_cycles:
                print(f"[COMPLETE] Reached requested max cycles: {max_cycles}.")
                break

            time.sleep(delay)

        except KeyboardInterrupt:
            print("\n[INTERRUPT] Stopping Autonomous Socratic Tutelage.")
            break
        except Exception as exc:
            print(f"[ERROR in cycle {cycle}]: {exc}")
            time.sleep(2.0)

    brain.close()
    if review_candidates:
        review_record = append_architect_review_session(
            REVIEW_FILE, session_id, review_details
        )
        print(f"[ARCHITECT REVIEW] Saved post-session queue: {REVIEW_FILE}")
        print("[ARCHITECT REVIEW] Proposals are unresolved; stable vocabulary was not changed:")
        for candidate in review_record["candidates"]:
            print(f"- {candidate['word']}")
            for context in candidate["contexts"]:
                print(f"  Context: {context['text']}")
            for attempt in candidate["definition_attempts"]:
                decision = "accepted by tutor" if attempt["tutor_accepted"] else "not accepted by tutor"
                print(f"  Proposed definition ({decision}): {attempt['definition']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Autonomous Socratic Tutelage: Queen Tutor & Viv")
    parser.add_argument("--max-cycles", type=int, default=0, help="Max cycles (0 = infinite)")
    parser.add_argument("--delay", type=float, default=2.0, help="Delay between turns (seconds)")
    parser.add_argument("--temp", type=float, default=0.2, help="Viv reasoning temperature")
    parser.add_argument("--learn-language", action="store_true", help="Run bounded spelling/sentence learning in an isolated INN candidate")
    parser.add_argument("--updates", type=int, default=300, help="Language candidate updates (1..500)")
    parser.add_argument("--learn-routes", action="store_true", help="Open persistent native neuron-route learning in the terminal")
    args = parser.parse_args()

    if args.learn_routes:
        from autonomy.terminal_neuron_learning import main

        sys.argv = [sys.argv[0], "--interactive"]
        main()
        raise SystemExit(0)

    if args.learn_language:
        from autonomy.socratic_language_training import run_language_lessons

        outcome = run_language_lessons(args.updates)
        raise SystemExit(0 if outcome["passed"] else 2)

    run_socratic_tutelage(
        max_cycles=args.max_cycles,
        delay=args.delay,
        temperature=args.temp,
    )
