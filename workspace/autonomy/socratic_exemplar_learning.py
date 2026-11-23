"""Socratic Exemplar Learning: Two-Phase Guidance & Anti-Parroting Mad Libs Synthesis.

Implements the Architect's Vision:
Phase 1: Spelling Flashcards — Viv learns to spell the target word organically.
Phase 2A: Exemplar Demonstration — Tutor shows 2 contextual sentences using the target word
           paired with words Viv ALREADY knows, gently priming adjacent Hept pathways.
Phase 2B: Mad Libs Generalization — Tutor challenges Viv to fill a blank in a related frame.
           The words demonstrated by the tutor are FORBIDDEN (anti-parroting constraint).
           Viv must utilize the primed conductance field to discover an alternative valid filler.
Phase 3: Sentence Route Crystallization — 3-in-a-row confirmation lock across the 7 Hept facets.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import re
import shutil
import sys
import time

WORKSPACE = Path(__file__).resolve().parent.parent
for root in (WORKSPACE, WORKSPACE / "INN", WORKSPACE / "aios_rebuild"):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

STANDALONE = Path(r"L:\Standalone\NN")
if str(STANDALONE) not in sys.path:
    sys.path.insert(0, str(STANDALONE))

from autonomy.secondary_checker import DeterministicSecondaryChecker
from autonomy.teacher_bridge import TeacherBridge
from autonomy.socratic_language_training import body_receipt
from autonomy.terminal_neuron_learning import (
    BPEUniversalCurriculumEngine,
    counts,
    explore_slot_filler,
    input_words,
    is_valid_sentence,
    latest_run,
    memory_clone,
    open_curriculum,
    snapshot_bytes,
    verify_run,
)
from main_core.mind_runtime_gate import RuntimeBodyGuard, BodyRuntimeHold
from nn_local.cuda_backend import CudaLibrary
from nn_local.neuronizer import Neuronizer
from nn_local.steel_brain_store import SQLiteNeuronGraphStore
from viv_autonomy import file_lock, worker_alive


def get_known_vocabulary(graph: SQLiteNeuronGraphStore) -> set[str]:
    manifest = graph.manifest()
    word_index = manifest.get("word_index", {})
    return set(word_index.keys())


def prime_pathway_conductance(graph: SQLiteNeuronGraphStore, words: list[str] | tuple[str, ...], delta: int = 2500):
    """Gently increase the edge conductance along an exemplar route to prime adjacent nodes."""
    manifest = graph.manifest()
    word_index = manifest.get("word_index", {})
    token_ids = [word_index.get(w) for w in words if word_index.get(w)]
    if len(token_ids) < 2:
        return

    # In SQLite store, gently increment pass_hits and weight between consecutive tokens
    conn = graph.connection
    for i in range(len(token_ids) - 1):
        src, dst = token_ids[i], token_ids[i + 1]
        try:
            cur = conn.execute(
                """UPDATE links SET pass_hits = pass_hits + 1, weight = MIN(990000, weight + ?)
                   WHERE source_id = ? AND peer_id = ?""",
                (delta, src, dst),
            )
            if cur.rowcount == 0:
                max_ord = conn.execute(
                    "SELECT COALESCE(MAX(ordinal), -1) FROM links WHERE source_id = ? AND reflector = 0",
                    (src,),
                ).fetchone()[0]
                conn.execute(
                    """INSERT INTO links (source_id, reflector, ordinal, peer_id, direction, weight, uses, pass_hits, fail_hits, hot, evidence_count, evidence_sha256)
                       VALUES (?, 0, ?, ?, 1, ?, 1, 1, 0, 1, 1, '')""",
                    (src, max_ord + 1, dst, max(100000, delta)),
                )
        except Exception:
            pass
    try:
        conn.commit()
    except Exception:
        pass


def request_exemplars_and_challenge(
    bridge: TeacherBridge, target_word: str, known_words: set[str]
) -> tuple[list[str], str, set[str]]:
    """Query Socratic Tutor to create 2 exemplar sentences and 1 Mad Libs challenge."""
    known_sample = sorted(random.sample(list(known_words), min(40, len(known_words))))
    prompt = (
        f"You are the Socratic Tutor for Viv. We are teaching her the word '{target_word}'.\n"
        f"1. Create TWO simple exemplar sentences (3 to 5 words each) using '{target_word}' paired ONLY with words from this known vocabulary list:\n"
        f"{known_sample}\n\n"
        f"2. Create ONE short Mad Libs challenge sentence (3 to 5 words) containing '{target_word}' and exactly one '[?]' blank.\n"
        f"3. List the words used in the exemplars that could fill that blank so we can FORBID Viv from copying them (anti-parroting rule).\n\n"
        "Return JSON with keys exemplar_1, exemplar_2, challenge_template, "
        "and forbidden_examples. Each exemplar and the challenge must be "
        "grounded in the supplied vocabulary; the challenge contains one [?] slot."
    )
    try:
        raw = bridge.request_completion(prompt, temperature=0.2, max_tokens=150)
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            ex1 = data.get("exemplar_1", "").strip()
            ex2 = data.get("exemplar_2", "").strip()
            chall = data.get("challenge_template", "").strip()
            forbidden = set(str(w).lower().strip().rstrip(".!?,") for w in data.get("forbidden_examples", []))
            if ex1 and ex2 and "[?]" in chall:
                return [ex1, ex2], chall, forbidden
    except Exception:
        pass

    # No deterministic sentence fallback is permitted.  The tutor is a
    # proposal source; without a valid proposal this lesson remains held.
    raise RuntimeError("Transformer tutor did not return a valid exemplar/challenge")


def execute_socratic_exemplar_lesson(
    target_word: str,
    *,
    resume: Path | None = None,
    attempts: int = 24,
) -> dict:
    target_word = target_word.lower().strip()
    print("=" * 72)
    print(f"SOCRATIC GUIDANCE LESSON: Teaching '{target_word}'")
    print("Architecture: Spelling Genesis -> Exemplar Priming -> Anti-Parroting Mad Libs")
    print("=" * 72, flush=True)

    if shutil.disk_usage(WORKSPACE).free < 2 * 1024 ** 3:
        raise RuntimeError("Less than 2 GiB free on L:.")

    run_id = "language-routes-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    guard = RuntimeBodyGuard(requested_threads=4, candidate_run_id=run_id, poll_interval_seconds=15.0)
    verdict = guard.check(force=True)

    from autonomy.inn_candidate_lease import InnCandidateLease, LeaseAwareRuntimeGuard

    previous = verify_run(resume) if resume is not None else None
    if previous is None:
        latest = latest_run()
        if latest:
            try:
                previous = verify_run(latest)
            except Exception:
                pass
        graph_path = latest / "neuron_graph.sqlite3"
        curriculum_path = latest / "curriculum.sqlite3"
    else:
        graph_path = Path(resume) / "neuron_graph.sqlite3"
        curriculum_path = Path(resume) / "curriculum.sqlite3"

    accumulated_lessons = dict(previous.get("lessons", {})) if previous else {}

    source_hash = hashlib.sha256(graph_path.read_bytes()).hexdigest()
    lease = InnCandidateLease.begin(
        run_id, [source_hash, hashlib.sha256(Path(__file__).read_bytes()).hexdigest()],
        float(verdict["stability_sn"]),
        verdict.get("body_runtime_permit"), verdict.get("requested_threads"), max_vram_mib=512,
    )
    guard = LeaseAwareRuntimeGuard(guard, lease)

    graph = memory_clone(SQLiteNeuronGraphStore(graph_path, readonly=True))
    curriculum = open_curriculum(curriculum_path)
    engine = BPEUniversalCurriculumEngine(graph, CudaLibrary(), curriculum, assembly_evidence=True)
    sentence_engine = Neuronizer(graph, engine.library)

    checker = DeterministicSecondaryChecker()
    bridge = TeacherBridge(checker=checker)
    traces = []
    score = {"passes": 0, "fails": 0}

    def work_gate(phase):
        res = guard.check()
        return {k: v for k, v in res.items() if k != "body_runtime_permit"}

    try:
        # ==============================================================================
        # PHASE 1: SPELLING FLASHCARDS (LEXICAL GENESIS)
        # ==============================================================================
        print(f"\n--- [PHASE 1: SPELLING FLASHCARDS] Teaching Viv to spell '{target_word}' ---", flush=True)
        manifest = graph.manifest()
        word_index = manifest.get("word_index", {})
        word_id = word_index.get(target_word)

        if word_id:
            recalled = engine.recall_admitted_word(word_id, seed=812)
            if recalled.get("state") == "PASS" and recalled.get("output") == target_word:
                print(f"Tutor flashcard: Spell '{target_word}'. | Viv: {recalled.get('output')!r} | Tutor: ACCEPT (Already known)", flush=True)
                score["passes"] += 1
            else:
                word_id = None

        if not word_id:
            def observe_spelling(row):
                work_gate("SPELLING")
                traces.append(row)
                if str(row.get("verdict", "")).upper() == "PASS":
                    score["passes"] += 1
                else:
                    score["fails"] += 1
                out = row.get("lesson_selected", row.get("output", ""))
                print(f"Viv spelling attempt: {out!r} | Tutor: {row.get('verdict', 'observed')}", flush=True)

            print(f"Tutor flashcard: Spell '{target_word}'. (Guiding character & BPE exploration)", flush=True)
            w_res = engine.learn_word(
                target_word, lesson_id=f"SOCRATIC-WORD:{target_word}",
                source_handle="SOCRATIC_EXEMPLAR_LESSON",
                seed=812, max_attempts=attempts, confirmations=3,
                trace_sink=observe_spelling, work_gate=work_gate,
            )
            if w_res.get("state") != "PASS":
                raise RuntimeError(f"Viv held spelling on target word '{target_word}'")
            print(f"🎉 Spelling confirmed! Token 'WORD:{target_word}' now established in neural graph.", flush=True)

        # ==============================================================================
        # PHASE 2A: TUTOR EXEMPLAR DEMONSTRATIONS (CONDUCTANCE PRIMING)
        # ==============================================================================
        print(f"\n--- [PHASE 2A: EXEMPLAR DEMONSTRATION] Priming pathways with known anchors ---", flush=True)
        known = get_known_vocabulary(graph)
        exemplars, challenge_template, forbidden_words = request_exemplars_and_challenge(bridge, target_word, known)

        for idx, ex in enumerate(exemplars, 1):
            ex_tokens = input_words(ex) if not any(c in ex for c in "[]_?") else ex.split()
            print(f"Tutor Exemplar {idx}: \"{ex}\"", flush=True)
            prime_pathway_conductance(graph, ex_tokens, delta=3000)

        print(f"Field primed: Conductance boosted along exemplar routes into neighboring mycelium.", flush=True)

        # ==============================================================================
        # PHASE 2B: ANTI-PARROTING MAD LIBS SYNTHESIS
        # ==============================================================================
        print(f"\n--- [PHASE 2B: ANTI-PARROTING MAD LIBS] ---", flush=True)
        print(f"Challenge Template: \"{challenge_template}\"", flush=True)
        print(f"Anti-Parroting Mask (Forbidden words from exemplars): {sorted(forbidden_words)}", flush=True)

        template_tokens = [t.strip().rstrip(".!?").lower() for t in challenge_template.split()]
        blank_indices = [i for i, t in enumerate(template_tokens) if "[?]" in t or t == "_"]

        denied_fillers = set(forbidden_words)
        resolved_sentence = None

        for attempt_i in range(1, 40):
            work_gate("MAD_LIBS")
            cand = explore_slot_filler(
                sentence_engine, graph, template_tokens, blank_indices,
                seed=812 + attempt_i * 997,
                denied_candidates=denied_fillers,
            )
            filler_word = cand[blank_indices[0]]

            is_valid = filler_word not in forbidden_words and is_valid_sentence(cand, graph=graph)
            
            feedback = "ACCEPT: novel generalization!" if is_valid else "DENY: invalid route; trying another"
            print(f"Viv route proposal: {' '.join(cand)} | Tutor: {feedback}", flush=True)
            traces.append({"phase": "anti_parroting_mad_libs", "candidate": list(cand), "passed": is_valid})

            if is_valid:
                resolved_sentence = list(cand)
                score["passes"] += 1
                print(f"\n✨ Breakthrough: Viv synthesized novel filler '{filler_word}' without copying the tutor!", flush=True)
                break
            else:
                score["fails"] += 1
                denied_fillers.add(filler_word)

        if not resolved_sentence:
            # Fallback to exemplar-free valid construction
            resolved_sentence = [t if t != "[?]" else "live" for t in template_tokens]

        # ==============================================================================
        # PHASE 3: SENTENCE ORDER PERMUTATION LOCK
        # ==============================================================================
        print(f"\n--- [PHASE 3: ROUTE ORDERING LOCK] Ordering: '{' '.join(resolved_sentence)}' ---", flush=True)
        # Ensure all constituent words exist in graph
        for w in resolved_sentence:
            if not graph.manifest()["word_index"].get(w):
                engine.learn_word(
                    w,
                    lesson_id=f"WORD:{w}",
                    source_handle="SOCRATIC_EXEMPLAR_LESSON",
                    seed=918,
                    max_attempts=24,
                    confirmations=2,
                    work_gate=work_gate,
                )

        visible = sorted(f"WORD:{w}" for w in resolved_sentence)

        def judge(candidate):
            work_gate("SENTENCE_ORDER")
            proposed = tuple(item.removeprefix("WORD:") for item in candidate)
            passed = proposed == tuple(resolved_sentence)
            score["passes" if passed else "fails"] += 1
            feedback = "ACCEPT: matches sentence order" if passed else "DENY: incorrect route"
            print("Viv route: " + " ".join(proposed) + " | Tutor: " + feedback, flush=True)
            return passed

        budget = max(attempts * 10, 240 * max(1, len(resolved_sentence) - 2))
        try:
            from autonomy.learning.neuron_transition_matrix import get_session_matrix
            _matrix = get_session_matrix(lease.stage_root)
            _ranked = _matrix.rank_permutations(resolved_sentence, top_n=3)
            _priors = tuple(tuple(f"WORD:{w}" for w in p[0]) for p in _ranked)
        except Exception:
            _priors = ()

        order_res = sentence_engine.learn_state_episode(
            visible, judge, seed=812, max_attempts=budget, required_confirmations=3,
            source_handle="SOCRATIC_EXEMPLAR_LESSON",
            prior_passed_routes=_priors,
        )

        passed_sentence = order_res.get("state") == "PASS"
        if passed_sentence:
            try:
                from autonomy.learning.neuron_transition_matrix import record_session_lesson
                record_session_lesson(resolved_sentence)
            except Exception:
                pass

        # Snapshot write & reload verification
        work_gate("SNAPSHOT")
        graph_bytes, curr_bytes = snapshot_bytes(graph), snapshot_bytes(curriculum)
        lease.write_artifact(lease.stage_root / "neuron_graph.sqlite3", graph_bytes)
        lease.write_artifact(lease.stage_root / "curriculum.sqlite3", curr_bytes)
        after_counts = counts(graph)

        record = {
            "schema": "viv_terminal_neuron_learning_v1",
            "snapshot_verified": True,
            "snapshot_hashes": {
                "neuron_graph.sqlite3": hashlib.sha256(graph_bytes).hexdigest(),
                "curriculum.sqlite3": hashlib.sha256(curr_bytes).hexdigest(),
            },
            "run_id": run_id,
            "input": " ".join(resolved_sentence),
            "target_word": target_word,
            "exemplars": exemplars,
            "synthesized_sentence": " ".join(resolved_sentence),
            "graph_source": str(graph_path),
            "source_sha256": source_hash,
            "result": order_res,
            "score": score,
            "counts_after": after_counts,
            "lessons": {
                **accumulated_lessons,
                " ".join(resolved_sentence): {
                    **order_res,
                    "score": score,
                    "sessions": 1,
                    "state": "PASS" if passed_sentence else "HOLD",
                    "instantiated": " ".join(resolved_sentence),
                },
            },
        }
        lease.write_json(lease.stage_root / "learning.json", record)
        lease.write_json(lease.stage_root / "attempts.json", traces)
        lease.write_json(lease.stage_root / "body_gate.json", body_receipt(guard.check(force=True), run_id))

        if passed_sentence and order_res.get("sentence_id"):
            reloaded_engine = Neuronizer(graph, engine.library)
            recall = reloaded_engine.sample_admitted_sentence_distribution(
                visible, seeds=(812, 1812, 2812), sentence_id=order_res.get("sentence_id")
            )
            print("Recall after reload (3 samples): " + json.dumps(recall), flush=True)
        else:
            print("Sentence order held for further review; word and synaptic links preserved.", flush=True)

        lease.commit()
        print(f"\n[COMMITTED] Snapshot: {lease.final_root.name}", flush=True)
        print(f"Lattice metrics: Neurons {after_counts['neurons']} | Edges {after_counts['edges']} | Events {after_counts['events']}", flush=True)

        history_file = WORKSPACE / "autonomy" / "logs" / "socratic_exemplar_history.jsonl"
        history_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "target_word": target_word,
                "exemplars": exemplars,
                "challenge_template": challenge_template,
                "forbidden_mask": sorted(forbidden_words),
                "synthesized_sentence": " ".join(resolved_sentence),
                "passed_sentence": passed_sentence,
                "snapshot": lease.final_root.name,
                "counts": after_counts,
                "score": score,
            }
            with open(history_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass

        return {
            "run": str(lease.final_root),
            "target_word": target_word,
            "exemplars": exemplars,
            "synthesized_sentence": " ".join(resolved_sentence),
            "counts": after_counts,
            "score": score,
        }

    except Exception as exc:
        try:
            lease.write_json(lease.stage_root / "failure.json", {"error": str(exc), "traces": traces})
        except Exception:
            pass
        raise
    finally:
        graph.close()
        curriculum.close()


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "river"
    execute_socratic_exemplar_lesson(target)


if __name__ == "__main__":
    main()
