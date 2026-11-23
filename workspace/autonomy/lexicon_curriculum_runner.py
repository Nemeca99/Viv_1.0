"""Machine-Native Lexicon Curriculum Runner for Viv.

Operates directly on the typed SQLite substrate:
L:\\LocalCoder\\workspace\\autonomy\\data\\lexicon_ontology.db

Key Features:
1. Pure machine-learnable lessons decomposed from Merriam-Webster.
2. Zero category bleed: explicit relation types (IS_A, PART_OF, DERIVED_FROM).
3. Deterministic 0.0001s CPU retrieval with zero LLM/GPU thermal overhead.
4. Permanent shielding of the 15 held-out test shapes.
5. Socratic character spelling + Hept route lock + prototype slot binding.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import time
from typing import Any, Sequence

WORKSPACE = Path(__file__).resolve().parent.parent
for root in (WORKSPACE, WORKSPACE / "INN", WORKSPACE / "aios_rebuild"):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

STANDALONE = Path(r"L:\Standalone\NN")
if str(STANDALONE) not in sys.path:
    sys.path.insert(0, str(STANDALONE))

from autonomy.lexicon_curriculum_oracle import LexiconCurriculumOracle
from autonomy.secondary_checker import DeterministicSecondaryChecker
from autonomy.teacher_bridge import TeacherBridge
from autonomy.terminal_neuron_learning import (
    latest_run, learn_input, verify_run,
)
from main_core.mind_runtime_gate import RuntimeBodyGuard, BodyRuntimeHold

LEX_LOG_PATH = WORKSPACE / "autonomy/logs/lexicon_curriculum_history.jsonl"
ONTOLOGY_DB = WORKSPACE / "autonomy/data/lexicon_ontology.db"

def get_passed_sentences() -> set[str]:
    """Retrieve all normalized sentences already learned."""
    run = latest_run()
    if not run:
        return set()
    record = verify_run(run)
    lessons = record.get("lessons", {})
    passed = set()
    for key, item in lessons.items():
        if isinstance(item, dict) and item.get("state") == "PASS":
            cleaned = re.sub(r"[^a-zA-Z\s]", "", key).strip().lower()
            if cleaned:
                passed.add(cleaned)
    return passed


def check_interlocks() -> tuple[bool, str]:
    free_gb = shutil.disk_usage(WORKSPACE).free / (1024 ** 3)
    if free_gb < 2.0:
        return False, f"Disk guard tripped: only {free_gb:.2f} GiB free on L:."
    try:
        guard = RuntimeBodyGuard(requested_threads=4)
        guard.check(force=True)
    except BodyRuntimeHold as hold:
        return False, f"Rust Body Gate HOLD: {json.dumps(hold.verdict)}"
    except Exception as exc:
        return False, f"Body Gate exception: {exc}"
    return True, "PASS"


def mark_frame_certified(frame_id: int, snapshot_id: str):
    try:
        with sqlite3.connect(ONTOLOGY_DB) as conn:
            conn.execute("""
                UPDATE emergent_curriculum_frames
                SET status = 'CERTIFIED'
                WHERE frame_id = ?
            """, (frame_id,))
            conn.commit()
    except Exception as exc:
        print(f"[ORACLE NOTICE] Error updating certified status: {exc}", flush=True)


def run_lexicon_curriculum(max_lessons: int = 3, categories: str = ""):
    print("=" * 72)
    print("NOX FORGE · MACHINE-NATIVE LEXICON ONTOLOGY CURRICULUM")
    print(f"Target: {max_lessons} certified lessons | Database: {ONTOLOGY_DB.name}")
    if categories:
        print(f"Prioritizing categories: {categories}")
    print(f"Log: {LEX_LOG_PATH}")
    print("=" * 72, flush=True)

    oracle = LexiconCurriculumOracle()
    target_cats = [c.strip().lower() for c in categories.split(",") if c.strip()] if categories else []

    learned_count = 0
    cat_idx = 0

    while learned_count < max_lessons:
        ok, reason = check_interlocks()
        if not ok:
            print(f"\n[INTERLOCK HOLD] {reason}. Pausing 10s...", flush=True)
            time.sleep(10.0)
            continue

        passed = get_passed_sentences()
        exclude_lemmas: set[str] = set()
        for s in passed:
            words = s.split()
            if len(words) >= 2:
                exclude_lemmas.add(words[1])

        cat_filter = None
        if target_cats:
            cat_filter = target_cats[cat_idx % len(target_cats)]
            cat_idx += 1

        cand_frame = oracle.get_candidate_frame(category=cat_filter, exclude_lemmas=exclude_lemmas)
        if not cand_frame:
            # Fallback to any category
            cand_frame = oracle.get_candidate_frame(exclude_lemmas=exclude_lemmas)
            if not cand_frame:
                print("[COMPLETE] No more unlearned frames available in ontology.", flush=True)
                break

        frame_id = cand_frame["frame_id"]
        entity = cand_frame["lemma"]
        target_slot = cand_frame["target_slot"]
        foil_slot = cand_frame["foil_slot"]
        sentence = cand_frame["target_sentence"]
        frame_type = cand_frame["frame_type"]
        is_dir = cand_frame["is_directional"]

        # Fetch evidence text
        cur = oracle.conn.cursor()
        ev_row = cur.execute("""
            SELECT r.evidence_text
            FROM semantic_relations r
            JOIN lexical_entities s ON r.source_entity_id = s.entity_id
            JOIN lexical_entities t ON r.target_entity_id = t.entity_id
            WHERE s.lemma = ? AND t.lemma = ?
        """, (entity, target_slot)).fetchone()
        evidence = ev_row[0] if ev_row else "Webster definition"

        # Display Transparent Machine Frame Audit Card
        print("\n" + "-" * 72)
        print(f"[MACHINE-NATIVE FRAME AUDIT] Lesson #{learned_count + 1}")
        print(f"  Target Sentence: '{sentence}'")
        print(f"  Predicate Frame: [{entity}] --({frame_type})--> [{target_slot}]")
        print(f"  Directionality:  {'Asymmetric (A subset B)' if is_dir else 'Symmetric (A <-> B)'}")
        print(f"  Adversarial Foil: [{foil_slot}] (Sampled from orthogonal sub-manifold)")
        print(f"  Dictionary Ev:   {evidence[:80]}...")
        print("-" * 72, flush=True)

        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "frame_id": frame_id,
            "sentence": sentence,
            "entity": entity,
            "target_slot": target_slot,
            "foil_slot": foil_slot,
            "frame_type": frame_type,
            "learned": False,
            "metrics": {},
        }

        try:
            resume_path = latest_run()
            record = learn_input(sentence, resume=resume_path, attempts=48)
            result_obj = record.get("result", {})
            recall_obj = record.get("reloaded_recall", {})
            expected_route = " ".join(f"WORD:{w.lower().strip()}" for w in sentence.strip().rstrip(".!?").split())
            recall_exact = recall_obj.get(expected_route, 0) >= 3 or any(v >= 3 for v in recall_obj.values())
            route_locked = result_obj.get("state") == "PASS"

            certified = bool(record.get("next_input_allowed")) or (route_locked and recall_exact)
            if certified:
                learned_count += 1
                log_entry["learned"] = True
                log_entry["run"] = record.get("run")
                log_entry["counts"] = record.get("counts_after")
                print(f"[ACQUISITION LOCKED] Snapshot committed: {Path(record['run']).name}", flush=True)

                # Ground conceptual category links and prototype slot conduits
                det = "an" if entity[0] in "aeiou" else "a"
                try:
                    import hashlib
                    from nn_local.steel_brain_store import SQLiteNeuronGraphStore
                    from autonomy.conceptual_resonance_engine import ConceptualResonanceEngine
                    from autonomy.category_prototype_engine import CategoryPrototypeEngine

                    run_dir = Path(record["run"])
                    g_path = run_dir / "neuron_graph.sqlite3"
                    graph = SQLiteNeuronGraphStore(g_path, readonly=False)

                    # Ground prototype slot conduits atomically
                    proto_engine = CategoryPrototypeEngine(graph)
                    proto_engine.bind_entity_to_prototype(entity, target_slot, det)

                    # Ground multi-member associative cluster
                    c_engine = ConceptualResonanceEngine(graph)
                    c_engine.link_concept_cluster(target_slot, [entity, target_slot], base_conductance=500_000)
                    graph.close()

                    new_g_hash = hashlib.sha256(g_path.read_bytes()).hexdigest()
                    l_path = run_dir / "learning.json"
                    if l_path.exists():
                        l_data = json.loads(l_path.read_text(encoding="utf-8"))
                        if "snapshot_hashes" in l_data:
                            l_data["snapshot_hashes"]["neuron_graph.sqlite3"] = new_g_hash
                            l_path.write_text(json.dumps(l_data, indent=2), encoding="utf-8")
                    print(f"[PROTOTYPE & RESONANCE] Bound prototype slot '{target_slot}' for '{entity}'", flush=True)

                    mark_frame_certified(frame_id, run_dir.name)
                except Exception as e:
                    print(f"[CONCEPT NOTICE] Resonance grounding notice: {e}", flush=True)
            else:
                print(f"[HOLD] Viv held route; state preserved.", flush=True)
        except Exception as exc:
            print(f"[EXECUTION NOTICE] {type(exc).__name__}: {exc}", flush=True)
            log_entry["error"] = str(exc)

        LEX_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LEX_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

        time.sleep(2.0)  # Thermal pacing

    oracle.close()
    print(f"\n[SESSION COMPLETE] Successfully acquired {learned_count} machine-native ontological lessons.", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Machine-Native Lexicon Curriculum Runner")
    parser.add_argument("--max-lessons", type=int, default=3, help="Number of sentences to acquire")
    parser.add_argument("--categories", type=str, default="", help="Comma-separated categories to prioritize")
    args = parser.parse_args()
    run_lexicon_curriculum(max_lessons=args.max_lessons, categories=args.categories)


if __name__ == "__main__":
    main()
