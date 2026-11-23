"""Observe and resume Viv's existing native word and sentence route learner."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import time

from autonomy.socratic_language_training import WORKSPACE, body_receipt, digest

STANDALONE = Path(r"L:\Standalone\NN")
if str(STANDALONE) not in sys.path:
    sys.path.insert(0, str(STANDALONE))
RUNS = WORKSPACE / "autonomy/learning/neural_runs"


def input_words(text):
    if not isinstance(text, str) or not re.fullmatch(r"[A-Za-z ,.!?'-]+", text.strip()):
        raise ValueError("This first terminal lesson supports English letters and sentence punctuation")
    words = re.findall(r"[a-z]+(?:['-][a-z]+)*", text.lower())
    if not 1 <= len(words) <= 8 or any(len(word) > 20 for word in words):
        raise ValueError("Use one to eight words, each at most twenty letters")
    return words


def is_template(text: str) -> bool:
    """Check if input text contains slot-filling blanks."""
    if not isinstance(text, str):
        return False
    return any(marker in text for marker in ("[?]", "_", "..."))


def parse_template(text: str) -> tuple[list[str], list[int]]:
    """Parse text into tokens and identify blank slot indices for Mad Libs."""
    raw = text.strip()
    normalized = re.sub(r"\[\s*\?\s*\]|\.\.\.|_", " [?] ", raw)
    tokens = []
    for part in normalized.split():
        clean = part.strip().rstrip(".!?").lower()
        if clean == "[?]" or part.startswith("[?") or part == "_" or part == "...":
            tokens.append("[?]")
        elif clean.isalpha():
            tokens.append(clean)
    blanks = [i for i, t in enumerate(tokens) if t == "[?]"]
    return tokens, blanks


def is_valid_sentence(words: list[str] | tuple[str, ...], graph=None) -> bool:
    """Dynamic route validator; no fixed sentence frames or vocabulary."""
    if not isinstance(words, (list, tuple)) or len(words) < 2:
        return False
    tokens = [str(word).casefold() for word in words]
    if any(not re.fullmatch(r"[a-z]+(?:['-][a-z]+)*", token) for token in tokens):
        return False
    if graph is not None:
        index = graph.manifest().get("word_index", {})
        if not all(token in index for token in tokens):
            return False
    db = WORKSPACE / "autonomy/data/lexicon_ontology.db"
    if not db.is_file():
        return False
    try:
        with sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True, timeout=1.0) as con:
            ids = []
            for token in tokens:
                row = con.execute("SELECT entity_id FROM lexical_entities WHERE lower(lemma)=?", (token,)).fetchone()
                if row:
                    ids.append(int(row[0]))
            if len(ids) < 2:
                return False
            return any(
                con.execute(
                    "SELECT 1 FROM semantic_relations WHERE source_entity_id=? AND target_entity_id=? LIMIT 1",
                    (source, target),
                ).fetchone()
                for source in ids for target in ids if source != target
            )
    except sqlite3.Error:
        return False


def explore_slot_filler(
    sentence_engine,
    graph,
    tokens: list[str] | tuple[str, ...],
    blank_indices: list[int] | tuple[int, ...],
    *,
    seed: int,
    candidate_pool: list[str] | tuple[str, ...] | None = None,
    temperature: float = 0.5,
    denied_candidates: set[str] | None = None,
) -> tuple[str, ...]:
    """Sample candidate filler words for blank slots using Viv's neural graph resonance."""
    denied = denied_candidates or set()
    manifest = graph.manifest()
    word_index = manifest.get("word_index", {})
    dynamic_pool = list(candidate_pool) if candidate_pool is not None else sorted(word_index)
    pool = [w for w in dynamic_pool if w not in denied]
    if not pool:
        pool = list(dynamic_pool)
    resolved_tokens = list(tokens)

    for step_i, blank_idx in enumerate(blank_indices):
        prev_word = resolved_tokens[blank_idx - 1] if blank_idx > 0 else None
        next_word = resolved_tokens[blank_idx + 1] if blank_idx < len(resolved_tokens) - 1 else None

        prev_id = word_index.get(prev_word) if prev_word and prev_word != "[?]" else None
        next_id = word_index.get(next_word) if next_word and next_word != "[?]" else None

        prev_neuron = graph.load_neuron(prev_id) if prev_id else None

        scores = []
        for cand in pool:
            cand_id = word_index.get(cand)
            if not cand_id:
                scores.append(0.0)
                continue

            w_prev = 500_000.0
            if prev_neuron:
                center, _ = sentence_engine._edge_state(prev_neuron, cand_id)
                w_prev = float(center)

            w_next = 500_000.0
            if next_id:
                cand_neuron = graph.load_neuron(cand_id)
                center_next, _ = sentence_engine._edge_state(cand_neuron, next_id)
                w_next = float(center_next)

            total_res = (w_prev + w_next) / 2_000_000.0
            scores.append(total_res)

        import math, random
        rng = random.Random(seed + step_i * 97_409)
        clamped_t = max(0.05, float(temperature))
        max_s = max(scores) if scores else 0.0
        exp_scores = [math.exp((s - max_s) / clamped_t) for s in scores]
        sum_exp = sum(exp_scores)
        probs = [e / sum_exp for e in exp_scores]

        r = rng.random()
        cum = 0.0
        chosen = pool[-1]
        for idx, p in enumerate(probs):
            cum += p
            if r <= cum:
                chosen = pool[idx]
                break
        resolved_tokens[blank_idx] = chosen

    return tuple(resolved_tokens)


def follow_up_word(words):
    return list(dict.fromkeys(words))[-1]


def memory_clone(store):
    memory = sqlite3.connect(":memory:")
    memory.row_factory = store.connection.row_factory
    store.connection.backup(memory)
    store.connection.close()
    store.connection = memory
    memory.execute("PRAGMA journal_mode=MEMORY")
    memory.execute("PRAGMA foreign_keys=ON")
    return store


def open_curriculum(snapshot=None):
    from nn_local.neuron_graph import CurriculumStore

    if snapshot is not None:
        return memory_clone(CurriculumStore(snapshot, readonly=True))
    template = STANDALONE / "data/live/steel_brain_language_emergence_v1/curriculum.sqlite3"
    source = sqlite3.connect(f"file:{template.as_posix()}?mode=ro", uri=True)
    try:
        schema = [row[0] for row in source.execute(
            "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY type DESC"
        )]
    finally:
        source.close()
    store = CurriculumStore.__new__(CurriculumStore)
    store.path = Path(":memory:")
    store.connection = sqlite3.connect(":memory:")
    store.connection.executescript(";\n".join(schema))
    store._evidence_cache = {}
    store._assembly_evidence_cache = {}
    store._pattern_evidence_cache = {}
    return store


_BPE_ENGINE_CLASS = None


def get_bpe_engine_class():
    global _BPE_ENGINE_CLASS
    if _BPE_ENGINE_CLASS is not None:
        return _BPE_ENGINE_CLASS
    from nn_local.neuronizer import UniversalCurriculumEngine

    class BPEUniversalCurriculumEngine(UniversalCurriculumEngine):
        """Multi-Scale BPE Token Curriculum Engine.

        Invariant Principle: 1 Neuron = 1 Token across all scales.
        Permits COMBINATION neurons (e.g. 'ne', 'ed', 'ing', 'th', 'st') as legitimate
        structural building blocks for word synthesis, enabling words like 'need' to assemble
        compositionally from subwords rather than raw single characters.
        """

        def _word_composition_catalog(self, word: str):
            target_length = len(str(word))
            return [
                token
                for token in self._token_catalog()
                if token["kind"] in {"CHARACTER", "WORD", "COMBINATION"}
                and len(str(token["surface"])) < target_length
            ]

    _BPE_ENGINE_CLASS = BPEUniversalCurriculumEngine
    return _BPE_ENGINE_CLASS


def __getattr__(name: str):
    if name == "BPEUniversalCurriculumEngine":
        return get_bpe_engine_class()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def snapshot_bytes(store):
    store.connection.commit()
    integrity = store.connection.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise ValueError(f"Neuron learning snapshot integrity failed: {integrity}")
    payload = store.connection.serialize()
    if payload[:16] != b"SQLite format 3\0":
        raise ValueError("Invalid serialized learning snapshot")
    payload = payload[:18] + b"\x01\x01" + payload[20:]
    restored = sqlite3.connect(":memory:")
    try:
        restored.deserialize(payload)
        if restored.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Standalone learning snapshot failed reload integrity")
    finally:
        restored.close()
    return payload


_VERIFIED_RUN_CACHE: dict[str, tuple[float, float, dict]] = {}


def verify_run(run):
    run = Path(run).resolve()
    if run.parent != RUNS.resolve() or not run.name.startswith("language-routes-"):
        raise ValueError("Resume requires a committed language-route run")
    learning_path = run / "learning.json"
    g_path = run / "neuron_graph.sqlite3"
    c_path = run / "curriculum.sqlite3"
    cache_key = str(run)
    try:
        mtime_sig = (
            learning_path.stat().st_mtime,
            g_path.stat().st_mtime,
            g_path.stat().st_size,
            c_path.stat().st_mtime,
            c_path.stat().st_size,
        )
    except OSError as exc:
        raise ValueError(f"Route snapshot missing file: {exc}") from exc
    cached = _VERIFIED_RUN_CACHE.get(cache_key)
    if cached is not None and cached[0] == mtime_sig:
        return cached[2]
    record = json.loads(learning_path.read_text(encoding="utf-8"))
    if record.get("schema") != "viv_terminal_neuron_learning_v1" or not record.get("snapshot_verified"):
        raise ValueError("Route session lacks a verified snapshot")
    for name in ("neuron_graph.sqlite3", "curriculum.sqlite3"):
        if digest(run / name) != record["snapshot_hashes"][name]:
            raise ValueError(f"Route snapshot hash mismatch: {name}")
    _VERIFIED_RUN_CACHE[cache_key] = (mtime_sig, 0.0, record)
    return record


def latest_run():
    candidates = sorted(RUNS.glob("language-routes-*"), reverse=True)
    return candidates[0] if candidates else None


def latest_verified_run():
    """Choose the newest intact route snapshot; retain rejected runs as evidence."""
    for candidate in sorted(RUNS.glob("language-routes-*"), reverse=True):
        try:
            verify_run(candidate)
        except (ValueError, KeyError, OSError, json.JSONDecodeError) as exc:
            print(f"[ROUTE SNAPSHOT HOLD] {candidate.name}: {exc}", flush=True)
            continue
        return candidate
    return None


def starting_input(resume, requested_input):
    if resume is None:
        if not requested_input:
            raise ValueError("No input supplied and no verified route parent is available")
        return requested_input
    record = verify_run(resume)
    if requested_input and requested_input != record.get("input"):
        return requested_input
    if not record.get("next_input_allowed"):
        return record["input"]
    return requested_input or record["input"]


def session_has_more_accepts(score, starting_score):
    return (score["passes"] - starting_score["passes"]) > (
        score["fails"] - starting_score["fails"]
    )


def counts(store):
    return {
        "neurons": store.connection.execute("SELECT count(*) FROM neurons").fetchone()[0],
        "edges": store.connection.execute("SELECT count(*) FROM links").fetchone()[0],
        "events": store.connection.execute("SELECT count(*) FROM graph_events").fetchone()[0],
    }


def learn_input(text, *, resume=None, attempts=24, semantic_provenance=None):
    """Commit an observed input route with optional, data-derived provenance.

    ``semantic_provenance`` is evidence supplied by the caller, not a route
    generator.  It is persisted verbatim with the immutable snapshot so a
    composed sentence can always be traced back to the SQLite edges that
    justified it.
    """
    if is_template(text):
        tokens, blanks = parse_template(text)
        words = [t for t in tokens if t != "[?]"]
        lesson_key = " ".join(tokens)
    else:
        words = input_words(text)
        tokens, blanks = list(words), []
        lesson_key = " ".join(words)
    if not 1 <= attempts <= 64:
        raise ValueError("Attempt budget must be 1..64 per word/sentence")
    from main_core.mind_runtime_gate import RuntimeBodyGuard
    from autonomy.inn_candidate_lease import InnCandidateLease, LeaseAwareRuntimeGuard
    from viv_autonomy import file_lock, worker_alive

    with file_lock(WORKSPACE / "autonomy/terminal_neuron_learning.lock"):
        if worker_alive():
            raise RuntimeError("Hive worker must be paused during terminal learning")
        if shutil.disk_usage(WORKSPACE).free < 2 * 1024 ** 3:
            raise RuntimeError("Less than 2 GiB is free for durable learning snapshots")
        if resume == "latest_verified":
            resume = latest_verified_run()
            if resume is None:
                raise RuntimeError("No verified route parent is available")
        run_id = "language-routes-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        from aios_rebuild.privacy_core.privacy_core import PrivacyCore
        privacy = PrivacyCore()
        for artifact in ("neuron_graph.sqlite3", "curriculum.sqlite3"):
            decision = privacy.authorize_file_write(str(RUNS / run_id / artifact))
            if decision.get("allowed") is not True:
                raise PermissionError(f"PrivacyCore denied route snapshot: {decision.get('reason')}")
        # Commits are serialized; request one CPU thread for each commit.
        guard = RuntimeBodyGuard(requested_threads=1, candidate_run_id=run_id, poll_interval_seconds=15.0)
        verdict = guard.check(force=True)
        previous = verify_run(resume) if resume is not None else None
        if previous is None:
            status = json.loads((WORKSPACE / "autonomy/learning/unified_viv_status.json").read_text())
            parent_receipt = json.loads((Path(status["run"]) / "evaluation.json").read_text())
            if parent_receipt.get("passed") is not True:
                raise ValueError("Unified Viv parent did not pass its existing gate")
            graph_path = Path(parent_receipt["isolated_db"])
            curriculum_path = None
        else:
            graph_path = Path(resume) / "neuron_graph.sqlite3"
            curriculum_path = Path(resume) / "curriculum.sqlite3"
        source_hash = digest(graph_path)
        lease = InnCandidateLease.begin(
            run_id, [source_hash, digest(__file__)], float(verdict["stability_sn"]),
            verdict.get("body_runtime_permit"), verdict.get("requested_threads"), max_vram_mib=512,
        )
        guard = LeaseAwareRuntimeGuard(guard, lease)
        from nn_local.steel_brain_store import SQLiteNeuronGraphStore
        from nn_local.neuronizer import Neuronizer, UniversalCurriculumEngine
        from nn_local.cuda_backend import CudaLibrary

        BPEUniversalCurriculumEngine = get_bpe_engine_class()

        graph = memory_clone(SQLiteNeuronGraphStore(graph_path, readonly=True))
        curriculum = open_curriculum(curriculum_path)
        started = time.monotonic()
        # A daemon commit owns the global commit lock.  Its requested attempt
        # budget must therefore also bound wall-clock ownership.  Interactive
        # lessons retain a larger proportional window without allowing the
        # background learner to burn indefinitely on one sentence.
        lesson_deadline_seconds = max(45, attempts * 5)
        # A daemon candidate already passed the separate three-fact ontology
        # gate before reaching this function.  It needs one deterministic
        # route proof plus the mandatory reload proof; repeating the same
        # in-memory route three times monopolizes the serialized commit lane.
        # Interactive lessons retain their three confirmation passes.
        background_commit = attempts <= 6
        sentence_confirmations = 1 if background_commit else 3
        reload_seeds = (9181,) if background_commit else (9181, 9182, 9183)

        def sentence_attempt_budget(token_count: int) -> int:
            floor = 3 * max(1, token_count - 2)
            return max(attempts * (2 if background_commit else 10), floor)
        traces = []
        lessons = dict(previous["lessons"]) if previous is not None else {}
        source_counts = counts(graph)
        prior_score = lessons.get(lesson_key, {}).get("score", {})
        score = {
            "passes": int(prior_score.get("passes", 0)),
            "fails": int(prior_score.get("fails", 0)),
        }
        starting_score = score.copy()
        print(f"\nInput: {text}\nBody: ALLOW | continuing saved neuron learning: {previous is not None}", flush=True)

        def work_gate(phase):
            if time.monotonic() - started > lesson_deadline_seconds:
                raise TimeoutError(
                    f"Bounded terminal lesson reached {lesson_deadline_seconds} seconds "
                    f"during phase={phase}"
                )
            result = guard.check()
            return {key: value for key, value in result.items() if key != "body_runtime_permit"}

        def observe(row):
            work_gate("ATTEMPT")
            traces.append(row)
            verdict = str(row.get("verdict", "")).upper()
            if verdict == "PASS":
                score["passes"] += 1
            elif verdict == "FAIL":
                score["fails"] += 1
            output = row.get("lesson_selected", row.get("output", ""))
            print(f"Viv word attempt: {output!r} | Graph verifier: {row.get('verdict', row.get('state', 'observed'))}", flush=True)

        try:
            engine = BPEUniversalCurriculumEngine(
                graph, CudaLibrary(), curriculum, assembly_evidence=True, ordered_prefix_composition=True
            )
            sentence_engine = Neuronizer(graph, engine.library)
            word_results = {}
            for index, word in enumerate(dict.fromkeys(words)):
                work_gate("WORD")
                word_id = graph.manifest()["word_index"].get(word)
                if word_id:
                    result = engine.recall_admitted_word(word_id, seed=812 + index)
                    if result.get("state") == "PASS" and result.get("output") == word:
                        score["passes"] += 1
                        traces.append({"phase": "word_flashcard", "prompt": f"Spell: {word}", "response": result.get("output"), "verdict": "PASS"})
                        print(f"Graph flashcard: Spell '{word}'. | Viv: {result.get('output')!r} | Graph verifier: ACCEPT", flush=True)
                        word_results[word] = {"state": "PASS", "word_neuron_id": word_id, "recalled": True}
                        continue
                print(f"Graph flashcard: Spell '{word}'.", flush=True)
                word_results[word] = engine.learn_word(
                    word, lesson_id=f"TERMINAL-WORD:{word}", source_handle="ARCHITECT_TERMINAL_INPUT",
                    seed=812 + index, max_attempts=max(attempts, 24), confirmations=3,
                    trace_sink=observe, work_gate=work_gate,
                )
            supported = all(result.get("state") == "PASS" for result in word_results.values())
            result = {"state": "HOLD", "reason": "WORD_LEARNING_IN_PROGRESS"}
            before_distribution = {}
            if supported and blanks:
                prior = lessons.get(lesson_key, {})
                found_valid = False
                chosen_sentence = None
                if prior.get("state") == "PASS" and prior.get("instantiated"):
                    chosen_sentence = [t for t in prior["instantiated"].split() if t]
                    words = chosen_sentence
                    result = dict(prior)
                    result["sessions"] = int(prior.get("sessions", 0)) + 1
                    found_valid = True
                    print("This route already has a learned sentence neuron; testing graph recall after restart.", flush=True)
                else:
                    denied_fillers: set[str] = set()
                    slot_budget = max(attempts, len(graph.manifest().get("word_index", {})) + 8)
                    for attempt_i in range(1, slot_budget + 1):
                        work_gate("MAD_LIBS_EXPLORATION")
                        cand_tokens = explore_slot_filler(
                            sentence_engine, graph, tokens, blanks,
                            seed=812 + attempt_i * 1_000_003 + int(prior.get("sessions", 0)) * 7919,
                            denied_candidates=denied_fillers,
                        )
                        is_valid = is_valid_sentence(cand_tokens)
                        score["passes" if is_valid else "fails"] += 1
                        feedback = "ACCEPT: valid sentence" if is_valid else "DENY: invalid sentence; try another filler"
                        print(f"Viv route: {' '.join(cand_tokens)} | Graph verifier: {feedback}", flush=True)
                        traces.append({"phase": "mad_libs_exploration", "candidate": list(cand_tokens), "passed": is_valid})
                        if is_valid:
                            found_valid = True
                            chosen_sentence = list(cand_tokens)
                            words = chosen_sentence
                            break
                        else:
                            for b_idx in blanks:
                                if b_idx < len(cand_tokens):
                                    denied_fillers.add(cand_tokens[b_idx])
                    if found_valid and chosen_sentence:
                        for index, word in enumerate(dict.fromkeys(chosen_sentence)):
                            work_gate("WORD")
                            word_id = graph.manifest()["word_index"].get(word)
                            if word_id:
                                result_w = engine.recall_admitted_word(word_id, seed=812 + index)
                                if result_w.get("state") == "PASS" and result_w.get("output") == word:
                                    word_results[word] = {"state": "PASS", "word_neuron_id": word_id, "recalled": True}
                                    continue
                            word_results[word] = engine.learn_word(
                                word, lesson_id=f"TERMINAL-WORD:{word}", source_handle="ARCHITECT_TERMINAL_INPUT",
                                seed=812 + index, max_attempts=max(attempts, 24), confirmations=3,
                                trace_sink=observe, work_gate=work_gate,
                            )
                        visible = sorted(f"WORD:{w}" for w in chosen_sentence)

                        def judge(candidate):
                            work_gate("SENTENCE")
                            proposed = tuple(item.removeprefix("WORD:") for item in candidate)
                            passed = proposed == tuple(chosen_sentence)
                            row = {"phase": "sentence_order", "candidate": list(proposed), "passed": passed}
                            traces.append(row)
                            score["passes" if passed else "fails"] += 1
                            feedback = "ACCEPT: matches the input order" if passed else "DENY: different input order; try another route"
                            print("Viv route: " + " ".join(proposed) + " | Graph verifier: " + feedback, flush=True)
                            return passed

                        resume_ep = (
                            prior.get("episode_id")
                            if (prior.get("state") != "PASS" and prior.get("instantiated") == " ".join(chosen_sentence))
                            else None
                        )
                        budget = sentence_attempt_budget(len(chosen_sentence))
                        session_seed_offset = int(prior.get("sessions", 0)) * 97_409_111
                        # Positional Lock & Synaptic Gradient Scaffold (The Architect's Protocol)
                        try:
                            from autonomy.positional_locking_engine import PositionalLockingEngine
                            PositionalLockingEngine(graph).scaffold_sentence(
                                chosen_sentence,
                                seed=812 + session_seed_offset,
                                work_gate=work_gate,
                                score_sink=score,
                                trace_sink=traces,
                                verbose=True,
                            )
                        except Exception as e:
                            print(f"[SCAFFOLD NOTICE] {e}", flush=True)
                        _priors = (tuple(f"WORD:{w}" for w in chosen_sentence),)
                        result = sentence_engine.learn_state_episode(
                            visible, judge, seed=812 + session_seed_offset,
                            max_attempts=budget, required_confirmations=sentence_confirmations,
                            source_handle="ARCHITECT_TERMINAL_INPUT",
                            prior_passed_routes=_priors,
                            resume_episode_id=resume_ep,
                        )
                        if result.get("state") == "PASS":
                            try:
                                from autonomy.learning.neuron_transition_matrix import record_session_lesson
                                record_session_lesson(chosen_sentence)
                            except Exception:
                                pass
                        result = {
                            **result,
                            "sessions": int(prior.get("sessions", 0)) + 1,
                            "template": text,
                            "instantiated": " ".join(chosen_sentence),
                        }
                    else:
                        result = {"state": "HOLD", "reason": "SLOT_EXPLORATION_UNRESOLVED", "sessions": int(prior.get("sessions", 0)) + 1}
            elif supported and len(words) > 1:
                visible = sorted(f"WORD:{word}" for word in words)
                before_distribution = sentence_engine.sample_state_distribution(visible, seeds=(812, 1812, 2812))
                print("Fresh route samples: " + json.dumps(before_distribution), flush=True)
                expected_route = tuple(f"WORD:{word}" for word in words)
                for candidate, frequency in before_distribution.items():
                    proposed_route = tuple(candidate.split())
                    passed = proposed_route == expected_route
                    score["passes" if passed else "fails"] += int(frequency)
                    feedback = "ACCEPT" if passed else "DENY: route differs from input order"
                    print(f"Graph route check ({frequency} samples): {candidate} | {feedback}", flush=True)
                prior = lessons.get(lesson_key, {})

                def judge(candidate):
                    work_gate("SENTENCE")
                    proposed = tuple(item.removeprefix("WORD:") for item in candidate)
                    passed = proposed == tuple(words)
                    row = {"phase": "sentence_order", "candidate": list(proposed), "passed": passed}
                    traces.append(row)
                    score["passes" if passed else "fails"] += 1
                    feedback = "ACCEPT: matches the input order" if passed else "DENY: different input order; try another route"
                    print("Viv route: " + " ".join(proposed) + " | Graph verifier: " + feedback, flush=True)
                    return passed

                if prior.get("state") == "PASS":
                    result = prior
                    print("This input already has a learned sentence neuron; testing recall after restart.", flush=True)
                else:
                    budget = sentence_attempt_budget(len(words))
                    session_seed_offset = int(prior.get("sessions", 0)) * 97_409_111
                    # Positional Lock & Synaptic Gradient Scaffold (The Architect's Protocol)
                    try:
                        from autonomy.positional_locking_engine import PositionalLockingEngine
                        PositionalLockingEngine(graph).scaffold_sentence(
                            words,
                            seed=812 + session_seed_offset,
                            work_gate=work_gate,
                            score_sink=score,
                            trace_sink=traces,
                            verbose=True,
                        )
                    except Exception as e:
                        print(f"[SCAFFOLD NOTICE] {e}", flush=True)
                    _priors = (tuple(f"WORD:{w}" for w in words),)
                    result = sentence_engine.learn_state_episode(
                        visible, judge, seed=812 + session_seed_offset,
                        max_attempts=budget, required_confirmations=sentence_confirmations,
                        source_handle="ARCHITECT_TERMINAL_INPUT",
                        prior_passed_routes=_priors,
                        resume_episode_id=prior.get("episode_id"),
                    )
                    if result.get("state") == "PASS":
                        try:
                            from autonomy.learning.neuron_transition_matrix import record_session_lesson
                            record_session_lesson(words)
                        except Exception:
                            pass
                result = {**result, "sessions": int(prior.get("sessions", 0)) + 1}
            elif supported:
                result = {"state": "PASS", "word": words[0]}
            work_gate("SNAPSHOT")
            graph_payload, curriculum_payload = snapshot_bytes(graph), snapshot_bytes(curriculum)
            lease.write_artifact(lease.stage_root / "neuron_graph.sqlite3", graph_payload)
            lease.write_artifact(lease.stage_root / "curriculum.sqlite3", curriculum_payload)
            snapshot_hashes = {
                "neuron_graph.sqlite3": hashlib.sha256(graph_payload).hexdigest(),
                "curriculum.sqlite3": hashlib.sha256(curriculum_payload).hexdigest(),
            }
            after_counts = counts(graph)
            graph.close()
            graph = memory_clone(SQLiteNeuronGraphStore(lease.stage_root / "neuron_graph.sqlite3", readonly=True))
            curriculum.close()
            curriculum = open_curriculum(lease.stage_root / "curriculum.sqlite3")
            engine = BPEUniversalCurriculumEngine(graph, CudaLibrary(), curriculum, assembly_evidence=True)
            sentence_engine = Neuronizer(graph, engine.library)
            recall = {}
            work_gate("RELOADED_RECALL")
            if result.get("sentence_id") and result.get("state") == "PASS":
                recall = sentence_engine.sample_admitted_sentence_distribution(
                    sorted(f"WORD:{word}" for word in words), seeds=reload_seeds,
                    sentence_id=result["sentence_id"],
                )
            elif len(words) == 1 and supported:
                word_id = graph.manifest()["word_index"][words[0]]
                recall = engine.recall_admitted_word(word_id, seed=9181)
            if result.get("sentence_id") and result.get("state") == "PASS":
                expected_route = tuple(f"WORD:{word}" for word in words)
                for candidate, frequency in recall.items():
                    passed = tuple(candidate.split()) == expected_route
                    score["passes" if passed else "fails"] += int(frequency)
                    feedback = "ACCEPT: route survived reload" if passed else "DENY: reloaded route differs"
                    print(f"Graph reload check ({frequency} samples): {candidate} | {feedback}", flush=True)
            follow_up_asked = (
                (session_has_more_accepts(score, starting_score) if not blanks else True)
                and supported
                and result.get("state") == "PASS"
            )
            follow_up = {"asked": False, "state": "HOLD"}
            if follow_up_asked:
                target_word = (
                    chosen_sentence[blanks[0]]
                    if blanks and chosen_sentence and blanks[0] < len(chosen_sentence)
                    else follow_up_word(words)
                )
                target_id = graph.manifest()["word_index"].get(target_word)
                follow_up["asked"] = True
                follow_up["word"] = target_word
                print(f"Graph follow-up flashcard: Spell '{target_word}'.", flush=True)
                if target_id:
                    response = engine.recall_admitted_word(target_id, seed=9184)
                    passed = response.get("state") == "PASS" and response.get("output") == target_word
                    follow_up.update({
                        "state": "PASS" if passed else "FAIL",
                        "response": response.get("output", ""),
                        "route": response.get("route", []),
                    })
                    score["passes" if passed else "fails"] += 1
                    traces.append({
                        "phase": "tutor_follow_up_flashcard", "prompt": f"Spell: {target_word}",
                        "response": response.get("output", ""), "verdict": "PASS" if passed else "FAIL",
                    })
                    print(f"Viv: {response.get('output')!r} | Graph verifier: {'ACCEPT' if passed else 'DENY'}", flush=True)
                else:
                    follow_up["reason"] = "WORD_NEURON_NOT_FOUND"
                    print("Graph verifier: HOLD | no admitted word neuron for follow-up card", flush=True)
            follow_up_allowed = follow_up_asked
            next_input_allowed = (
                (session_has_more_accepts(score, starting_score) if not blanks else True)
                and follow_up.get("state") == "PASS"
            )
            session_score = {
                "passes": score["passes"] - starting_score["passes"],
                "fails": score["fails"] - starting_score["fails"],
            }
            lessons[lesson_key] = {
                **{key: value for key, value in result.items() if key != "trace"},
                "score": score,
                "session_score": session_score,
                "follow_up_allowed": follow_up_allowed,
                "follow_up": follow_up,
            }
            if blanks and result.get("instantiated"):
                inst_key = result["instantiated"].strip().rstrip(".!?").lower()
                lessons[inst_key] = {
                    **{key: value for key, value in result.items() if key != "trace"},
                    "score": score,
                    "session_score": session_score,
                    "follow_up_allowed": follow_up_allowed,
                    "follow_up": follow_up,
                }
            record = {
                "schema": "viv_terminal_neuron_learning_v1", "input": text,
                "run": str(lease.final_root), "parent_run": str(resume) if resume else None,
                "graph_source": str(graph_path), "source_sha256": source_hash,
                "source_unchanged": digest(graph_path) == source_hash,
                "snapshot_hashes": snapshot_hashes, "snapshot_verified": counts(graph) == after_counts,
                "lessons": lessons, "word_results": word_results, "result": result,
                "score": score, "session_score": session_score,
                "follow_up_allowed": follow_up_allowed,
                "follow_up": follow_up, "next_input_allowed": next_input_allowed,
                "counts_before": source_counts, "counts_after": after_counts,
                "before_learning_samples": before_distribution, "reloaded_recall": recall,
                "elapsed_seconds": time.monotonic() - started, "live_activated": False,
                "scope": "Observed-input word/sentence route learning; exact input-order feedback, not a general grammar judgment",
            }
            if semantic_provenance is not None:
                record["semantic_provenance"] = semantic_provenance
            if not record["source_unchanged"] or not record["snapshot_verified"]:
                raise RuntimeError("Learning snapshot failed integrity checks")
            lease.write_json(lease.stage_root / "learning.json", record)
            lease.write_json(lease.stage_root / "attempts.json", traces)
            final_verdict = None
            for _attempt in range(3):
                try:
                    final_verdict = guard.check(force=True)
                    break
                except Exception:
                    if _attempt == 2:
                        raise
                    time.sleep(1.0)
            lease.write_json(lease.stage_root / "body_gate.json", body_receipt(final_verdict, run_id))
            try:
                from autonomy.learning.neuron_transition_matrix import get_session_matrix
                get_session_matrix(lease.stage_root).save_to_snapshot(lease.stage_root)
            except Exception:
                pass
            lease.commit()
            # Rolling Retention Gate: Keep max 20 snapshots on NVMe, move older to E:\Backup\neural_runs_archive
            try:
                archive_dir = Path(r"E:\Backup\neural_runs_archive")
                existing_runs = sorted(RUNS.glob("language-routes-*"), key=lambda p: p.stat().st_mtime, reverse=True)
                if len(existing_runs) > 20:
                    archive_dir.mkdir(parents=True, exist_ok=True)
                    for old_r in existing_runs[20:]:
                        dest = archive_dir / old_r.name
                        if not dest.exists():
                            shutil.move(str(old_r), str(dest))
                        else:
                            shutil.rmtree(str(old_r))
            except Exception:
                pass
            print(f"Saved: {lease.final_root}\nNeurons: {source_counts['neurons']} -> {after_counts['neurons']} | edges: {source_counts['edges']} -> {after_counts['edges']}", flush=True)
            print("Recall after reload: " + json.dumps(recall), flush=True)
            print(
                f"Graph verifier tally: {score['passes']} accepted / {score['fails']} denied | "
                f"follow-up: {'ALLOW' if follow_up_allowed else 'HOLD'}",
                flush=True,
            )
            return record
        except Exception as exc:
            try:
                failure_payload = {"error": str(exc), "attempts": traces}
                if hasattr(exc, "verdict"):
                    failure_payload["body_gate_verdict"] = exc.verdict
                lease.write_json(lease.stage_root / "failure.json", failure_payload)
            except Exception:
                pass
            raise
        finally:
            graph.close()
            curriculum.close()


def next_autonomous_lesson(record: dict, mad_libs: bool = False, homophones: bool = False) -> str | None:
    """Curriculum is supplied by the verified graph/Wikipedia reservoir."""
    return None


# Stop and ask the Architect instead of silently burning one 197 MB snapshot per retry.
MAX_CONSECUTIVE_RUNS_PER_LESSON = 12


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input")
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--attempts", type=int, default=24)
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--autonomous", action="store_true", help="Autonomously step through curriculum lessons")
    parser.add_argument("--mad-libs", action="store_true", help="Enable Mad Libs compositional slot-filling learning")
    parser.add_argument("--homophones", "--grade3", action="store_true", help="Enable Grade 3 homophone duel curriculum")
    parser.add_argument("--max-lessons", type=int, default=0, help="Max lessons to learn (0=continuous)")
    parser.add_argument("--duration-minutes", type=float, default=0.0, help="Max duration in minutes (0=continuous)")
    args = parser.parse_args()
    resume = args.resume or latest_run()
    record = verify_run(resume) if resume else None
    default_lesson = (
        next_autonomous_lesson(record, mad_libs=args.mad_libs, homophones=args.homophones)
        if args.autonomous
        else None
    )
    text = starting_input(resume, args.input or default_lesson)
    if args.input and text != args.input:
        print(f"Tutor holds new input until '{text}' passes its follow-up.", flush=True)
    completed_lessons = 0
    start_time = time.monotonic()
    streak_text, streak_runs = None, 0
    while True:
        text = starting_input(resume, text)
        if args.autonomous:
            streak_runs = streak_runs + 1 if text == streak_text else 1
            streak_text = text
            if streak_runs > MAX_CONSECUTIVE_RUNS_PER_LESSON:
                print(
                    f"\n[STOP] '{text}' has not cleared its progression gate after "
                    f"{MAX_CONSECUTIVE_RUNS_PER_LESSON} consecutive runs. Stopping for Architect review; "
                    "no lesson was skipped and every snapshot is preserved.",
                    flush=True,
                )
                return
        record = None
        try:
            record = learn_input(text, resume=resume, attempts=args.attempts)
            resume = Path(record["run"])
        except KeyboardInterrupt:
            print("\nStopped. The last committed snapshot is preserved.")
            return
        except Exception as exc:
            print(f"Learning held: {type(exc).__name__}: {exc}", flush=True)
            body_verdict = getattr(exc, "verdict", None)
            if isinstance(body_verdict, dict):
                print("Body verdict: " + json.dumps(body_verdict, sort_keys=True), flush=True)
            if args.autonomous:
                if "Less than 2 GiB is free" in str(exc):
                    print("\n[STOP] Disk guard tripped. Free space on L: before resuming; nothing was written.", flush=True)
                    return
                elapsed_min = (time.monotonic() - start_time) / 60.0
                if args.duration_minutes > 0 and elapsed_min >= args.duration_minutes:
                    print(f"\n[COMPLETE] Reached requested duration: {elapsed_min:.1f} minutes.", flush=True)
                    return
                print("Autonomous mode: waiting 2s before retrying held lesson...", flush=True)
                time.sleep(2.0)
                continue
            if not args.interactive:
                raise
            try:
                retry = input(
                    f"\nTutor holds '{text}'. Press Enter to retry this lesson or /quit to stop: "
                ).strip()
            except (EOFError, KeyboardInterrupt):
                return
            if retry.lower() in {"/quit", "/exit"}:
                return
            if retry:
                print("New input held; retry the current lesson first.", flush=True)
            continue
        if args.autonomous:
            if record.get("next_input_allowed"):
                completed_lessons += 1
                elapsed_min = (time.monotonic() - start_time) / 60.0
                if args.max_lessons > 0 and completed_lessons >= args.max_lessons:
                    print(f"\n[COMPLETE] Reached requested max lessons: {args.max_lessons}.", flush=True)
                    return
                if args.duration_minutes > 0 and elapsed_min >= args.duration_minutes:
                    print(f"\n[COMPLETE] Reached requested duration: {elapsed_min:.1f} minutes ({completed_lessons} lessons committed).", flush=True)
                    return
                text = next_autonomous_lesson(record, mad_libs=args.mad_libs, homophones=args.homophones)
                if text is None:
                    print(
                        f"\n[COMPLETE] Curriculum exhausted after {completed_lessons} lessons; "
                        "every authored sentence has passed. Waiting for new Architect input.",
                        flush=True,
                    )
                    return
                print(f"\n--- [NEXT AUTONOMOUS LESSON {completed_lessons + 1} ({elapsed_min:.1f}m elapsed)]: {text} ---", flush=True)
            time.sleep(1.0)
            continue
        if not args.interactive:
            return
        try:
            if record.get("next_input_allowed"):
                prompt = "\nTutor follow-up passed. Architect may enter the next word or sentence (/quit to stop): "
            elif record.get("follow_up_allowed"):
                prompt = "\nTutor asked a follow-up flashcard but held progression. Repeat the lesson or retry (/quit to stop): "
            else:
                prompt = f"\nTutor holds progression. Continue '{record.get('input', text)}' or retry (/quit to stop): "
            text = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            return
        if text.lower() in {"/quit", "/exit"}:
            return
        if not text:
            text = record["input"]


if __name__ == "__main__":
    main()
