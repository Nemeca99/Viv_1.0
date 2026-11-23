"""Interactive Chat Terminal for Unified AIOS Viv (Grounded Emergent Cognitive Mind).

Architecture:
- AIOS deterministic body health authorizes or holds the probabilistic Viv neural mind.
- Connects the live Unified Viv Brain to AIOS body health and memory queries.
- Queries Viv using her grounded multi-stage engine:
  * Spelling & Deconstruction (Stage 1)
  * Toddler Speaking & Conversational Defense (Stage 2)
  * Grounded Meaning & Urban Dictionary Lookup (Stage 3)
  * Real-time Neologism Explanation & Hept Path Inspection
- Zero external LLM dependency: conversational responses use Viv's neural network; body facts come from deterministic AIOS services.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

# Paths
WORKSPACE_ROOT = Path(r"L:\LocalCoder\workspace")
INN_ROOT = WORKSPACE_ROOT / "INN"
STANDALONE_NN = Path(r"L:\Standalone\NN")
sys.path.insert(0, str(WORKSPACE_ROOT))
sys.path.insert(0, str(INN_ROOT))
sys.path.insert(0, str(STANDALONE_NN))

from viv_context_store import DualContextMemory


def _body_runtime_verdict(kernel=None) -> dict:
    from aios_rebuild.main_core.mind_runtime_gate import BodyRuntimeHold, require_body_runtime

    for attempt in range(3):
        try:
            return require_body_runtime(kernel=kernel)
        except BodyRuntimeHold as hold:
            reasons = hold.verdict.get("reasons", [])
            if attempt < 2 and any("timed_out" in str(r) for r in reasons):
                time.sleep(1.0)
                continue
            return hold.verdict
        except Exception as exc:
            if attempt < 2:
                time.sleep(1.0)
                continue
            return {"allowed": False, "disposition": "HOLD_MIND_RUNTIME", "reasons": [str(exc)]}


def _load_brain_after_body_authorization(run_dir: Path | None):
    import torch

    torch.set_num_threads(2)
    from autonomy.speak_unified_viv import load_verified_unified_brain

    return load_verified_unified_brain(run_dir=run_dir, writable_clone=False)


def interactive_chat(run_dir: Path | None = None, enable_voice: bool = False) -> None:
    print("=" * 72)
    print("    AIOS VIV — INTERACTIVE GROUNDED NEURAL CHAT CONSOLE")
    print("    Substrate: Direct In-Memory Unified Brain (No External Cloud/LLM)")
    print("=" * 72)
    print("[INIT] Checking deterministic AIOS body authority before loading Viv's neural mind...")
    sys.stdout.flush()

    memory = DualContextMemory()
    aios_kernel = None
    brain = None
    try:
        from main_core.main_core import kernel as aios_kernel
        mind_gate = _body_runtime_verdict(aios_kernel)
    except Exception as exc:
        mind_gate = {
            "allowed": False,
            "disposition": "HOLD_MIND_RUNTIME",
            "authority": "deterministic_aios_body",
            "reasons": [f"body_health_unavailable:{exc}"],
        }
    print("[BODY GATE] " + json.dumps(mind_gate, ensure_ascii=False))
    if mind_gate.get("allowed") is True:
        try:
            print("[INIT] Body is ready; loading Viv's verified neural mind...")
            brain, receipt = _load_brain_after_body_authorization(run_dir)
        except Exception as exc:
            mind_gate = {
                **mind_gate,
                "allowed": False,
                "disposition": "HOLD_MIND_RUNTIME",
                "reasons": [f"neural_mind_load_failed:{exc}"],
            }
            print("[MIND HOLD] " + json.dumps(mind_gate, ensure_ascii=False))
    else:
        print("[MIND HOLD] AIOS body health did not authorize neural runtime.")
    if brain is not None:
        print(f"[READY] Viv mind online! Total Neurons: {brain.total_neurons:,} | Stable Words: {len(brain.all_stable_words):,}")
        print(f"[READY] Viv-Invented Neologisms in Graph: {len(brain.viv_invented_word_neurons)}")
    else:
        print("[READY] Body diagnostics remain available; neural mind is held.")

    phys_adapter = None
    try:
        from autonomy.physical_dialogue_adapter import PhysicalDialogueAdapter
        phys_adapter = PhysicalDialogueAdapter(run_dir=run_dir)
        print(f"[READY] Physical & Causal Reasoning Lattice online! (Mechanics, Thermodynamics, Hydraulics, Electrodynamics)")
    except Exception as exc:
        print(f"[PHYSICAL LATTICE NOTICE] Adapter unavailable: {exc}")

    math_gateway = None
    try:
        from autonomy.arithmetic_gateway import ArithmeticGateway
        math_gateway = ArithmeticGateway(run_dir=run_dir)
        math_gateway.ground_elementary_arithmetic_tables()
        print(f"[READY] Elementary Arithmetic & Sensory Transduction Gateway online! (0..10 Word Problems)")
    except Exception as exc:
        print(f"[ARITHMETIC NOTICE] Gateway unavailable: {exc}")

    conv_engine = None
    try:
        from autonomy.viv_conversational_engine import VivConversationalEngine
        conv_engine = VivConversationalEngine(run_dir=run_dir)
        print(f"[READY] Conversational Companion & Persistent Memory Engine online! (General Dialogue & Real-time Learning)")
    except Exception as exc:
        print(f"[CONVERSATION NOTICE] Engine unavailable: {exc}")

    print(f"[READY] Persistent Context Memory: {len(memory.chat_history)} recent turns in STM | {len(memory.ltm_raw)} LTM dumps")
    print("[INFO] Commands: /history, /health, /cores, /core <name>, /memory-status, /spell <word>, /meaning <word>, /stats, /exit.\n")
    sys.stdout.flush()

    def query_aios_health() -> dict[str, Any]:
        nonlocal aios_kernel
        if aios_kernel is None:
            from main_core.main_core import kernel as aios_kernel
        health = aios_kernel.get_system_health()
        health["mind_gate"] = _body_runtime_verdict(aios_kernel)
        return health

    def query_mind_gate() -> dict[str, Any]:
        nonlocal aios_kernel
        if aios_kernel is None:
            from main_core.main_core import kernel as aios_kernel
        return _body_runtime_verdict(aios_kernel)

    def record_body_reply(label: str, response: str) -> None:
        print(f"{label} > {response}\n")
        memory.append_dialogue_turn("assistant", f"[AIOS body query: {label}] {response}")

    def grounded_turn(prompt: str) -> dict:
        if conv_engine is None:
            return {"type": "NULL_UNLEARNED_ENTITY", "response": "NULL_UNLEARNED_ENTITY", "gate": "FAIL_CLOSED"}
        try:
            return conv_engine.converse(prompt, brain=brain)
        except Exception:
            return {"type": "NULL_UNLEARNED_ENTITY", "response": "NULL_UNLEARNED_ENTITY", "gate": "FAIL_CLOSED"}

    while True:
        try:
            prompt = input("Architect > ").strip()
            if not prompt:
                continue

            lower_p = prompt.lower()
            if lower_p in ("/exit", "/quit", "exit", "quit"):
                print("\n[CLOSING]")
                break

            # Append incoming user prompt to persistent short-term dialogue memory
            memory.append_dialogue_turn("user", prompt)

            aios_health_question = (
                any(subject in lower_p for subject in ("aios", "system", "core", "kernel", "body"))
                and any(term in lower_p for term in ("health", "status", "state", "core", "kernel", "doing", "working", "okay"))
            )
            if lower_p in ("/health", "/cores") or lower_p.startswith("/core ") or aios_health_question:
                try:
                    health = query_aios_health()
                    cores = health.get("cores", {})
                    if lower_p == "/cores":
                        response = "\n".join(
                            [f"{health.get('active_cores_count', len(cores))} AIOS cores bound."]
                            + [f"{name}: {json.dumps(status, ensure_ascii=False)}" for name, status in cores.items()]
                        )
                        record_body_reply("Viv [AIOS Cores]", response)
                    elif lower_p.startswith("/core "):
                        core_name = prompt.split(maxsplit=1)[1].strip()
                        status = cores.get(core_name)
                        response = (
                            f"{core_name}: {json.dumps(status, ensure_ascii=False, indent=2)}"
                            if status is not None
                            else f"Unknown core: {core_name}. Use /cores to list bound cores."
                        )
                        record_body_reply("Viv [AIOS Core]", response)
                    else:
                        response = json.dumps(health, ensure_ascii=False, indent=2)
                        record_body_reply("Viv [AIOS Health]", response)
                except Exception as exc:
                    record_body_reply("Viv [AIOS Health]", f"Unable to read AIOS health: {exc}")
                continue

            aios_memory_question = (
                any(subject in lower_p for subject in ("aios", "system", "body"))
                and "memory" in lower_p
            )
            if lower_p == "/memory-status" or aios_memory_question:
                dream_state = WORKSPACE_ROOT / "aios_rebuild" / "dream_core" / "state"
                latest_receipt = None
                receipt_path = dream_state / "consolidations.jsonl"
                if receipt_path.is_file():
                    try:
                        with receipt_path.open("r", encoding="utf-8") as stream:
                            for line in stream:
                                if line.strip():
                                    latest_receipt = json.loads(line)
                    except (OSError, json.JSONDecodeError) as exc:
                        latest_receipt = {"read_error": str(exc)}
                summary = {
                    "recent_chat_turns": len(memory.chat_history),
                    "long_term_dumps": len(memory.ltm_raw),
                    "compacted_memory_fields": sorted(memory.stm.keys()) if isinstance(memory.stm, dict) else [],
                    "dream_latest_receipt": {
                        key: latest_receipt.get(key)
                        for key in ("created_at", "status", "records_processed", "cluster_count", "candidate_count", "receipt_sha256")
                    } if isinstance(latest_receipt, dict) else None,
                }
                record_body_reply("Viv [AIOS Memory Status]", json.dumps(summary, ensure_ascii=False, indent=2))
                continue

            if lower_p == "/history":
                recent = memory.get_recent_chat_history(6)
                print(f"Viv [Memory]   > Recent Dialogue History ({len(recent)} turns):")
                for r in recent:
                    print(f"                 [{r['role'].capitalize()}]: {r['content']}")
                print()
                continue

            try:
                mind_gate = query_mind_gate()
            except Exception as exc:
                mind_gate = {
                    "allowed": False,
                    "disposition": "HOLD_MIND_RUNTIME",
                    "authority": "deterministic_aios_body",
                    "reasons": [f"body_health_unavailable:{exc}"],
                }
            if not mind_gate.get("allowed"):
                record_body_reply("Viv [Mind HOLD]", json.dumps(mind_gate, ensure_ascii=False))
                continue
            if brain is None:
                try:
                    brain, receipt = _load_brain_after_body_authorization(run_dir)
                    print(f"[MIND READY] Viv neural graph loaded after body authorization; neurons={brain.total_neurons:,}.")
                except Exception as exc:
                    record_body_reply("Viv [Mind HOLD]", f"AIOS body allowed runtime, but the neural mind failed to load: {exc}")
                    continue

            if lower_p.startswith("/spell "):
                word = prompt[7:].strip()
                res = brain.spell(word)
                print(f"Viv [Spelling] > {res.get('neuron_formula') or res.get('neural_spelled')}")
                print(f"                 Neuron: {res.get('admitted_neuron')} | Attn: {res.get('attention_state')}\n")
                continue

            if lower_p.startswith("/meaning "):
                word = prompt[9:].strip()
                res = brain.explain_meaning(word)
                print(f"Viv [Meaning]  > {res.get('meaning')}")
                print(f"                 Source: {res.get('source')} | PoS: {res.get('pos')}\n")
                continue

            if lower_p == "/stats":
                print(f"Viv [Stats]    > Total Neurons: {brain.total_neurons:,}")
                print(f"                 Invented Words: {list(brain.viv_invented_word_neurons.keys())[:15]}")
                print(f"                 Active Graph Path: {brain.source_graph_path}\n")
                continue

            protected_turn = (
                re.fullmatch(r"who\s+(?:is|are|was|were)\s+.+", prompt, re.IGNORECASE)
                or re.fullmatch(r"(?:my|our)\s+.+\s+is\s+(?:named|called)\s+.+", prompt, re.IGNORECASE)
                or re.fullmatch(r"what\s+is\s+\w+\s*\??", prompt, re.IGNORECASE)
            )
            if protected_turn:
                result = grounded_turn(prompt)
                print(f"Viv > {result['response']}")
                memory.append_dialogue_turn("assistant", result["response"])
                continue

            # -1. Math & Arithmetic Transduction Gate Check
            if math_gateway and math_gateway.is_math_query(prompt):
                math_res = math_gateway.process_math_turn(prompt, brain=brain)
                if math_res:
                    print(f"Viv > {math_res['formatted_output']}")
                    print(f"      |-- Transduced: '{math_res['word_transduction']}' | Calculator Oracle: {math_res['calculator_oracle']}")
                    print(f"      |-- Equation Shape: {math_res['viv_thought']} | Gate: {math_res['verdict']}\n")
                    memory.append_dialogue_turn("assistant", math_res["formatted_output"])
                    continue

            # 0. Physical & Causal Multi-System Reasoning Check
            if phys_adapter:
                phys_res = phys_adapter.reason_physical_query(prompt)
                if phys_res:
                    phys_reply = phys_adapter.format_physical_response(phys_res)
                    print(f"Viv > {phys_reply}\n")
                    memory.append_dialogue_turn("assistant", phys_reply)
                    continue

            conv_res = grounded_turn(prompt)
            print(f"Viv > {conv_res['response']}")
            print(f"      |-- Type: {conv_res['type']} | Gate: {conv_res['gate']}\n")
            memory.append_dialogue_turn("assistant", conv_res["response"])
            continue

        except KeyboardInterrupt:
            print("\n[INTERRUPT] Exiting chat.")
            break
        except Exception as exc:
            print(f"[Error]: {exc}\n")

    if brain is not None:
        brain.close()
    if phys_adapter is not None:
        phys_adapter.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Interactive Chat with Unified AIOS Viv")
    parser.add_argument("--voice", action="store_true", help="Enable voice TTS dispatch")
    args = parser.parse_args()
    interactive_chat(enable_voice=args.voice)
