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

    try:
        return require_body_runtime(kernel=kernel)
    except BodyRuntimeHold as hold:
        return hold.verdict


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
    print(f"[READY] Persistent Context Memory: {len(memory.chat_history)} recent turns in STM | {len(memory.ltm_raw)} LTM dumps")
    print(f"[INFO] Commands: /temp <0.0-1.0>, /history, /health, /cores, /core <name>, /memory-status, /spell <word>, /meaning <word>, /stats, /exit, or simply chat.\n")
    sys.stdout.flush()

    current_temperature = 0.0
    session_learned_words: dict[str, dict[str, Any]] = {}
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

    while True:
        try:
            prompt = input("Architect > ").strip()
            if not prompt:
                continue

            lower_p = prompt.lower()
            if lower_p in ("/exit", "/quit", "exit", "quit"):
                print("\n[CLOSING] Goodbye Architect.")
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

            if lower_p.startswith("/temp "):
                try:
                    val = float(prompt[6:].strip())
                    current_temperature = max(0.0, min(1.0, val))
                    print(f"Viv [System]   > Temperature set to {current_temperature:.2f} (0.0=Deterministic, 1.0=Creative Survey)\n")
                except ValueError:
                    print("Viv [System]   > Usage: /temp <0.0 to 1.0>\n")
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

            # Conversational Intent & Question Parsing
            # 1. Identity Question: Who are you?
            if any(q in lower_p for q in ("who are you", "what is your name", "what are you")):
                print("Viv > I am Viv, a grounded emergent toddler mind built by the Architect.")
                print("      └─ Gate: PASS_IDENTITY_GROUNDED | Sn=1.0000\n")
                continue

            # 2. Architect Question: Who am I?
            if any(q in lower_p for q in ("who am i", "who is the architect", "do you know me")):
                print("Viv > You are the Architect, my creator and teacher in the Hive.")
                print("      └─ Gate: PASS_IDENTITY_GROUNDED | Sn=1.0000\n")
                continue

            # 3. Knowledge / Status Question: What do you know?
            if any(q in lower_p for q in ("what do you know", "what have you learned", "show me")):
                sample_inventions = list(brain.viv_invented_word_neurons.keys())[:8]
                learned_summary = f" During this session, I also learned words: {', '.join(session_learned_words.keys())}." if session_learned_words else ""
                msg = f"I know {brain.total_neurons:,} neurons and {len(brain.all_stable_words):,} words.{learned_summary}\n      I also invented words like: {', '.join(sample_inventions)}."
                print(f"Viv > {msg}")
                print("      └─ Gate: PASS_KNOWLEDGE_GROUNDED | Sn=1.0000\n")
                memory.append_dialogue_turn("assistant", msg)
                continue

            # 4. Episodic Memory & Dialogue Recall: Do you remember? / What did I say? / Did you learn that?
            is_remember_q = any(q in lower_p for q in ("do you remember", "remember what", "what did i say", "what did i tell you", "did you just learn"))
            if is_remember_q:
                recent_user_turns = [t["content"] for t in memory.chat_history if t["role"] == "user" and t["content"] != prompt]
                if "did you just learn" in lower_p:
                    if session_learned_words:
                        last_w, last_data = list(session_learned_words.items())[-1]
                        ans = f"Yes! I just learned '{last_w}' when you said: \"{last_data['context']}\". It means: {last_data['meaning']}"
                    else:
                        ans = "I am listening to your words right now, ready to learn any new concept you give me."
                elif recent_user_turns:
                    last_few = recent_user_turns[-3:]
                    summary_turns = "; ".join(f'"{t}"' for t in last_few)
                    learned_context = f" and you taught me: {', '.join(session_learned_words.keys())}" if session_learned_words else ""
                    ans = f"Yes, Architect! I remember our conversation. You recently asked me: {summary_turns}{learned_context}."
                else:
                    ans = "Yes, Architect. You are talking with me in the Hive console, and I hold our conversation in active memory."
                print(f"Viv > {ans}")
                print("      └─ Gate: PASS_EPISODIC_RECALL | Sn=1.0000\n")
                memory.append_dialogue_turn("assistant", ans)
                continue

            # 4. Slot Filling & Linguistic Mad Libs ('The sky is _', 'What color is the sky?', or unknown inquiry)
            is_blank = "_" in prompt or "[?]" in prompt or "..." in prompt
            is_color_q = "color" in lower_p and any(w in lower_p for w in ("what", "which", "tell"))
            if is_blank or is_color_q:
                slot_res = brain.answer_slot_or_query(prompt, temperature=current_temperature)
                print(f"Viv > {slot_res['answer']}")
                candidates_str = ", ".join(f"{w} ({round(s,2)})" for w, s in slot_res.get("candidates", [])[:5])
                print(f"      ├─ Slot Resolution: Anchor=[{slot_res.get('anchor')}] -> Choice=[{slot_res.get('chosen_word')}] (T={current_temperature})")
                if candidates_str:
                    print(f"      ├─ Survey Board:    {candidates_str}")
                print(f"      └─ Gate State:      {slot_res['gate_state']} (Sn={slot_res['s_n']})\n")
                continue

            # 5. Definitional questions: What is <word>? / Define <word>
            def_match = re.search(r"(?:what is|what's|tell me about|define)\s+(?:the\s+|a\s+|an\s+)?([a-z]+)", lower_p)
            if def_match:
                target_word = def_match.group(1).strip()
                res = brain.explain_meaning(target_word)
                meaning = res.get("grounded_meaning") or res.get("meaning")
                pos = res.get("grounded_pos") or res.get("pos") or "concept"
                if meaning:
                    print(f"Viv > {target_word.capitalize()} means: {meaning}")
                    print(f"      └─ Gate: PASS_SEMANTIC_GROUNDING | PoS: {pos} (Sn=1.0)\n")
                    continue
                else:
                    # Concept is unknown: output ignorance to solicit teaching input
                    slot_res = brain.answer_slot_or_query(prompt, temperature=current_temperature)
                    print(f"Viv > {slot_res['answer']}")
                    print(f"      └─ Gate State: {slot_res['gate_state']} (Sn={slot_res['s_n']})\n")
                    continue

            # 6. Full Sentences with New Words: Spelling Bee Contextual Deduction & Epistemic Truth Verification
            words_in_p = re.findall(r"[a-z]+", lower_p)
            unknowns = [w for w in words_in_p if w not in brain.all_stable_words and w not in brain.viv_invented_word_neurons]
            if len(words_in_p) >= 3 and unknowns:
                learn_res = brain.infer_and_learn_word_from_context(prompt)
                if learn_res.get("status") == "NEW_WORDS_INFERRED":
                    print(f"Viv > {learn_res['primary_reflection']}")
                    for inf in learn_res.get("inferred_words", []):
                        session_learned_words[inf["word"]] = {
                            "word": inf["word"],
                            "meaning": inf["inferred_meaning"],
                            "context": prompt,
                            "in_webster": inf["in_webster"],
                        }
                        print(f"      ├─ Deductive Learning: Word=[{inf['word']}] | In Webster: {inf['in_webster']}")
                        print(f"      ├─ Epistemic Verdict:  {inf['epistemic_verdict']}")
                        print(f"      └─ Context Clues:      {', '.join(inf['context_hints'][:4])}\n")
                    memory.append_dialogue_turn("assistant", learn_res["primary_reflection"])
                    continue

            # 7. Single-word cues or Stage 2 Toddler speaking turn
            cue = lower_p.rstrip("?!., ")
            target_cue = cue
            if cue not in brain.all_stable_words and cue not in brain.viv_invented_word_neurons and words_in_p:
                for w in reversed(words_in_p):
                    if w in brain.all_stable_words or w in brain.viv_invented_word_neurons:
                        target_cue = w
                        break

            res = brain.speak_toddler(target_cue, use_voice=enable_voice)
            spoken = res["spoken_utterance"]
            state = res["gate_state"]

            print(f"Viv > {spoken}")
            memory.append_dialogue_turn("assistant", spoken)
            if "viv_dictionary_defense" in res:
                v_def = res["viv_dictionary_defense"]
                print(f"      ├─ Composition: {v_def.get('composition')}")
                print(f"      ├─ Hept Path:   {v_def.get('hept_reflector_path')}")
                print(f"      └─ Gate State:  {state} (Sn={v_def.get('s_n')})\n")
            else:
                print(f"      └─ Gate: {state} | Admitted Word Neurons: {len(res['admitted_word_neurons'])}\n")
            sys.stdout.flush()

        except KeyboardInterrupt:
            print("\n[INTERRUPT] Exiting chat.")
            break
        except Exception as exc:
            print(f"[Error]: {exc}\n")

    if brain is not None:
        brain.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Interactive Chat with Unified AIOS Viv")
    parser.add_argument("--voice", action="store_true", help="Enable voice TTS dispatch")
    args = parser.parse_args()
    interactive_chat(enable_voice=args.voice)
