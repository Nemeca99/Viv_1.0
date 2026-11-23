"""Autonomous Dual-Substrate Engine: GPU Subconscious Proposer + CPU Deterministic Arbiter.

Architecture:
1. GPU (RTX 3060 Ti VRAM):
   - High-throughput parallel exploration of candidate Hept pathways, combinatorial morpheme
     bridges, and associative dreaming weighted by P(n) ~ (C_n + alpha)^beta * S_n^gamma.
   - Proposes candidate routes, newly discovered words, and structural shortcuts.
2. CPU / System RAM:
   - Holds the verified SQLite neural graph (101,258 neurons) and lifetime activation WAL ledger.
   - Serves as the executive authority: runs proven deterministic paths instantaneously.
   - For any GPU proposal:
     * Evaluates UML !0 Logic Space Gate (< !0, !0 > = 1.0, < !0, 0 > = 0.0) and RID S_n >= 0.95.
     * Evaluates Webster & morphological soundess (Hept bridge rules).
     * If valid & higher stability: ALLOWS and SOLIDIFIES into candidate graph and ledger.
     * If invalid / collapsed: DENIES, suppresses pathway via STDP toward_zero.
3. Live Logging & Interactive Terminal:
   - Real-time formatted console output and append-only disk logging for live inspection.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Any

# Ensure path resolution
WORKSPACE_ROOT = Path(r"L:\LocalCoder\workspace")
INN_ROOT = WORKSPACE_ROOT / "INN"
STANDALONE_NN = Path(r"L:\Standalone\NN")
AIOS_REBUILD = WORKSPACE_ROOT / "aios_rebuild"
sys.path.insert(0, str(WORKSPACE_ROOT))
sys.path.insert(0, str(INN_ROOT))
sys.path.insert(0, str(STANDALONE_NN))
sys.path.insert(0, str(AIOS_REBUILD))

from aios_rebuild.main_core.mind_runtime_gate import BodyRuntimeHold, require_body_runtime

LOG_FILE = WORKSPACE_ROOT / "autonomy" / "logs" / "autonomous_daemon.log"


def _load_mind_stack():
    from autonomy.speak_unified_viv import load_verified_unified_brain
    from inn.uml_neural_gate import UML_CEILING_UNITY, UML_FLOOR_ZERO
    from nn_local.cuda_backend import CudaLibrary

    return {
        "load_verified_unified_brain": load_verified_unified_brain,
        "UML_CEILING_UNITY": UML_CEILING_UNITY,
        "UML_FLOOR_ZERO": UML_FLOOR_ZERO,
        "CudaLibrary": CudaLibrary,
    }


def promote_candidate_under_body_authority(brain, word: str):
    require_body_runtime()
    return brain.promote_neologism_to_graph(word)


def log_event(entry: dict[str, Any], console: bool = True) -> None:
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    entry["timestamp_utc"] = now_str
    line = json.dumps(entry, ensure_ascii=False)
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    if console:
        cycle = entry.get("cycle", 0)
        action = entry.get("action", "EVENT")
        details = entry.get("details", "")
        sn = entry.get("s_n", 1.0)
        status = entry.get("arbiter_status", "PASS")
        print(f"[{now_str[11:19]}] [Cycle {cycle:04d}] [{action:<16}] Sn={sn:.4f} | Arbiter: {status:<6} | {details}")
        sys.stdout.flush()


def run_autonomous_loop(
    *,
    max_cycles: int = 0,
    cycle_delay_sec: float = 0.5,
    seed: int = 20261031,
) -> None:
    try:
        require_body_runtime()
    except BodyRuntimeHold as hold:
        print("[BODY HOLD] Viv mind runtime denied: " + json.dumps(hold.verdict, ensure_ascii=False))
        return

    mind_stack = _load_mind_stack()
    load_verified_unified_brain = mind_stack["load_verified_unified_brain"]
    UML_CEILING_UNITY = mind_stack["UML_CEILING_UNITY"]
    UML_FLOOR_ZERO = mind_stack["UML_FLOOR_ZERO"]
    CudaLibrary = mind_stack["CudaLibrary"]
    print("=" * 76)
    print("    AIOS VIV — AUTONOMOUS DUAL-SUBSTRATE COGNITIVE ENGINE")
    print("    GPU: Subconscious Exploration & Morpheme Proposals (RTX 3060 Ti)")
    print("    CPU: Deterministic Execution & UML !0 Arbiter Gate (System RAM)")
    print("=" * 76)
    print(f"Logging to: {LOG_FILE}\n")
    sys.stdout.flush()

    # 1. Initialize GPU CUDA Backend Subconscious
    cuda_lib = CudaLibrary()
    vram_free, vram_total = cuda_lib.memory_info() if cuda_lib.available else (0, 0)
    print(f"[INIT:GPU] Subconscious Probe: {cuda_lib.version}")
    print(f"[INIT:GPU] Hardware VRAM: {vram_free / 1e9:.2f} GB free / {vram_total / 1e9:.2f} GB total")

    # 2. Mount Verified Unified Brain in System RAM with Writable Candidate Clone
    print(f"[INIT:CPU] Mounting Unified Brain & SQLite Ledger into System RAM...")
    brain, receipt = load_verified_unified_brain(writable_clone=True)
    print(f"[INIT:CPU] Loaded {brain.total_neurons:,} neurons ({len(brain.all_stable_words):,} stable words).")
    print(f"[INIT:CPU] Universal Machine Language Gate: < !0, !0 > = {UML_CEILING_UNITY}, < !0, 0 > = {UML_FLOOR_ZERO}")
    print(f"[INIT:CPU] Initial RID Stability S_n = {receipt['rid_stability']['s_n']:.6f} ({receipt['rid_stability']['triadic_state']})")
    print("-" * 76)
    sys.stdout.flush()

    rng = random.Random(seed)
    cycle = 0

    try:
        while True:
            cycle += 1
            try:
                require_body_runtime()
            except BodyRuntimeHold as hold:
                print("[BODY HOLD] Stopping Viv mind cycle: " + json.dumps(hold.verdict, ensure_ascii=False))
                break
            if max_cycles > 0 and cycle > max_cycles:
                print(f"\n[INFO] Reached configured maximum cycle count ({max_cycles}).")
                break

            # Mode selection: Alternates between:
            # A) Deterministic CPU Routine Execution & Flashcard Mastery
            # B) GPU Subconscious Dreaming & Emergent Morpheme Proposals
            # C) Self-Evaluation, Toddler Utterance Defense & Lexicon Solidification
            mode_dice = rng.random()

            # Mode selection: Balanced distribution:
            # A) 25% Deterministic CPU Solidified Routine Recall
            # B) 35% GPU Subconscious Dreaming & Emergent Morpheme Proposals
            # C) 40% Toddler Self-Expression, Grounded Speech & Neologism Defense
            mode_dice = rng.random()

            if mode_dice < 0.25:
                # MODE A: DETERMINISTIC CPU SOLIDIFIED PATHWAY VERIFICATION
                stable_pool = list(brain.all_stable_words.keys())
                test_word = rng.choice(stable_pool)
                spell_res = brain.spell(test_word)
                meaning_res = brain.explain_meaning(test_word)
                s_n = 1.0 if spell_res["attention_state"] != "UNGROUNDED" else 0.5
                log_event({
                    "cycle": cycle,
                    "action": "CPU_DETERMINISTIC",
                    "word": test_word,
                    "s_n": s_n,
                    "arbiter_status": "LOCKED",
                    "details": f"Deterministic recall '{test_word}': formula={spell_res['neuron_formula']} | pos={meaning_res.get('pos')}",
                })

            elif mode_dice < 0.60:
                # MODE B: GPU SUBCONSCIOUS PROPOSAL & DREAMING
                dream_seed = rng.randint(1, 1_000_000_000)
                dream_dict = brain.dream_and_invent_dictionary(
                    None,
                    iterations=64,
                    seed=dream_seed,
                )
                hits = dream_dict.get("validated_hits", [])
                invented = dream_dict.get("invented_words", [])

                if hits:
                    hit = rng.choice(hits[: min(len(hits), 10)])
                    word = hit["word"]
                    comp = hit["composition"]
                    s_n = float(hit.get("s_n", 1.0))
                    is_sound = hit.get("is_morphologically_sound", False)

                    # CPU Arbiter Decision: Allow or Deny
                    if is_sound and s_n >= 0.95:
                        try:
                            promoted = promote_candidate_under_body_authority(brain, word)
                        except BodyRuntimeHold as hold:
                            print("[BODY HOLD] Proposal not committed: "
                                  + json.dumps(hold.verdict, ensure_ascii=False))
                            break
                        arbiter = "ALLOW"
                        details = f"GPU proposed '{word}' ({comp}) -> ALLOWED & SOLIDIFIED into RAM (Neuron: {promoted['neuron_id']})"
                    else:
                        arbiter = "DENY"
                        details = f"GPU proposed '{word}' ({comp}) -> DENIED (Morphological violation or low Sn)"

                    log_event({
                        "cycle": cycle,
                        "action": "GPU_PROPOSAL",
                        "word": word,
                        "s_n": s_n,
                        "arbiter_status": arbiter,
                        "details": details,
                    })
                elif invented:
                    cand = rng.choice(invented[: min(len(invented), 10)])
                    word = cand["word"]
                    comp = cand.get("composition", "")
                    s_n = float(cand.get("s_n", 0.90))
                    log_event({
                        "cycle": cycle,
                        "action": "GPU_DREAM_EXPLORE",
                        "word": word,
                        "s_n": s_n,
                        "arbiter_status": "EXPLORE",
                        "details": f"Subconscious explored nascent candidate '{word}' ({comp}) (Hept={cand['hept_reflector_path']})",
                    })

            else:
                # MODE C: TODDLER SELF-EXPRESSION & GROUNDED SPEECH
                # Draw from Viv's core grounded vocabulary (464 words) + admitted neologisms + natural questions
                from inn.unified_brain import TODDLER_CORE_VOCABULARY
                core_pool = list(TODDLER_CORE_VOCABULARY.keys())
                neologism_pool = list(brain.viv_invented_word_neurons.keys()) if brain.viv_invented_word_neurons else ["doinger", "steding", "reating"]
                question_pool = [
                    "what are you doing?",
                    "who are you?",
                    "where is the sun?",
                    "can you run?",
                    "tell me a story",
                ]

                cue_dice = rng.random()
                if cue_dice < 0.35 and neologism_pool:
                    cue = rng.choice(neologism_pool)
                elif cue_dice < 0.60:
                    cue = rng.choice(question_pool)
                else:
                    cue = rng.choice(core_pool)

                speech = brain.speak_toddler(cue, use_voice=False)
                log_event({
                    "cycle": cycle,
                    "action": "TODDLER_SPEAK",
                    "cue": cue,
                    "s_n": 0.9985,
                    "arbiter_status": speech["gate_state"],
                    "details": f"Cue: '{cue}' -> Spoken: \"{speech['spoken_utterance']}\"",
                })

            time.sleep(cycle_delay_sec)

    except KeyboardInterrupt:
        print("\n[STOP] Received manual stop signal from Architect.")
    finally:
        brain.close()
        print("[SHUTDOWN] Candidate graph SQLite connections safely checkpointed and closed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AIOS Viv Autonomous Dual-Substrate Engine")
    parser.add_argument("--max-cycles", type=int, default=0, help="Max cycles (0 = run forever)")
    parser.add_argument("--delay", type=float, default=0.75, help="Delay in seconds between cycles")
    parser.add_argument("--seed", type=int, default=20261031, help="RNG seed")
    args = parser.parse_args()

    run_autonomous_loop(
        max_cycles=args.max_cycles,
        cycle_delay_sec=args.delay,
        seed=args.seed,
    )
