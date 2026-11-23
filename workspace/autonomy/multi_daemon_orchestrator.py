"""Multi-Daemon Concept-Partitioned Cognitive Orchestrator for Viv (AIOS V2).

Executes parallel learning daemons where each daemon is assigned an isolated
semantic concept domain. Employs a synchronized lease coordinator to eliminate
SQLite lock contention during physical neural lattice commits.
Runs continuously overnight with atomic snapshot commits and live telemetry.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import hashlib
import os
from pathlib import Path
import random
import re
import signal
import sqlite3
import sys
import tempfile
import threading
import time
from typing import Any

for _extra_path in (r"L:\LocalCoder\workspace", r"L:\Standalone\NN"):
    if os.path.isdir(_extra_path) and _extra_path not in sys.path:
        sys.path.insert(0, _extra_path)

GRADUATION_RECEIPT_PATH = Path(r"L:\LocalCoder\workspace\autonomy\learning\daemon_graduation_receipts.jsonl")
_graduation_receipt_lock = threading.Lock()


def append_graduation_receipt(receipt: dict[str, Any], privacy_core) -> dict[str, Any]:
    """Append a self-contained, hash-chained graduation event after commit verification."""
    with _graduation_receipt_lock:
        decision = privacy_core.authorize_file_write(str(GRADUATION_RECEIPT_PATH))
        if decision.get("allowed") is not True:
            raise PermissionError(decision.get("reason", "graduation_receipt_write_denied"))
        previous = "GENESIS"
        if GRADUATION_RECEIPT_PATH.exists():
            for line in GRADUATION_RECEIPT_PATH.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                item = json.loads(line)
                if item.get("prev_hash") != previous:
                    raise RuntimeError("Graduation receipt chain corruption detected")
                body = {k: v for k, v in item.items() if k != "receipt_hash"}
                expected = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                if item.get("receipt_hash") != expected:
                    raise RuntimeError("Graduation receipt checksum mismatch")
                previous = expected
        body = {**receipt, "prev_hash": previous}
        body["receipt_hash"] = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        GRADUATION_RECEIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with GRADUATION_RECEIPT_PATH.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(body, sort_keys=True) + "\n")
        return body

from autonomy.fractal_cognitive_engine import (
    FractalCognitiveEngine,
    latest_run,
    load_graduated_words,
    ontology_composed_facts,
    ontology_definition_facts,
    ontology_pos_grounded_facts,
)
def _lazy_learn_input(text, **kwargs):
    """Load the snapshot writer only at the physical commit boundary."""
    from autonomy.terminal_neuron_learning import learn_input
    return learn_input(text, **kwargs)
from autonomy.learning_paths import latest_verified_run
from autonomy.checkpoint_backup import CheckpointBackup
from autonomy.graph_attention import GraphAttentionScorer
from autonomy.graph_recurrent_attention import TopologyRecurrentAttention
from autonomy.composition_progression import compose_paragraphs
from nn_local.steel_brain_store import SQLiteNeuronGraphStore


# ---------------------------------------------------------------------------
# 4 Canonical Concept Domains with Deep Lexical Seeds
# ---------------------------------------------------------------------------

def _load_orthogonal_domain_seeds() -> dict[str, list[str]]:
    """Load orthogonal domain queues from persisted dynamic_categories.json without hardcoded lists."""
    category_path = Path(r"L:\LocalCoder\workspace\autonomy\learning\dynamic_categories.json")
    mapping = {
        "sensory_thermal": "sensory_adjectives",
        "kinematic_motion": "motion_verbs",
        "botanical_living": "botanical",
        "structural_material": "objects",
    }
    allocated: set[str] = set()
    result: dict[str, list[str]] = {k: [] for k in mapping}
    if category_path.is_file():
        try:
            raw = json.loads(category_path.read_text(encoding="utf-8"))
            for domain_key, cat_key in mapping.items():
                words = raw.get(cat_key, [])
                orthogonal: list[str] = []
                for w in words:
                    w_clean = str(w).strip().lower()
                    if w_clean and w_clean not in allocated:
                        allocated.add(w_clean)
                        orthogonal.append(w_clean)
                        if len(orthogonal) >= 64:
                            break
                result[domain_key] = orthogonal
        except Exception:
            pass
    return result


_ORTHOGONAL_SEEDS = _load_orthogonal_domain_seeds()

CONCEPT_DOMAINS: dict[str, dict[str, Any]] = {
    "sensory_thermal": {
        "name": "Sensory & Thermal Dynamics",
        "description": "Scalar thermal states, radiation, temperature gradients, and sensory perception.",
        "words": _ORTHOGONAL_SEEDS["sensory_thermal"],
    },
    "kinematic_motion": {
        "name": "Kinematic & Locomotion Dynamics",
        "description": "Physical spatial vectors, momentum, rotational and translative motion.",
        "words": _ORTHOGONAL_SEEDS["kinematic_motion"],
    },
    "botanical_living": {
        "name": "Botanical & Living Structures",
        "description": "Vegetative structures, organic growth, botanical entities, and plant taxonomy.",
        "words": _ORTHOGONAL_SEEDS["botanical_living"],
    },
    "structural_material": {
        "name": "Structural & Material Entities",
        "description": "Physical objects, tools, architectural components, and raw materials.",
        "words": _ORTHOGONAL_SEEDS["structural_material"],
    },
}


def commit_sentence_with_retry(sentence: str, *, semantic_provenance=None,
                               commit_fn=None, sleep_fn=None, jitter_fn=None,
                               max_attempts: int = 3) -> tuple[dict, list[dict]]:
    """Replay a pending sentence from the newest verified parent on each attempt."""
    if not 1 <= max_attempts <= 3:
        raise ValueError("Commit attempt budget must be 1..3")
    commit_fn = commit_fn or _lazy_learn_input
    sleep_fn = sleep_fn or time.sleep
    jitter_fn = jitter_fn or random.uniform
    retries: list[dict] = []
    for attempt in range(1, max_attempts + 1):
        try:
            commit_kwargs = {"resume": "latest_verified", "attempts": 6}
            if semantic_provenance is not None:
                commit_kwargs["semantic_provenance"] = semantic_provenance
            receipt = commit_fn(sentence, **commit_kwargs)
            return receipt, retries
        except Exception as exc:
            reason = str(exc)
            retryable = (
                (isinstance(exc, RuntimeError) and "Lock busy:" in reason)
                or (isinstance(exc, ValueError) and "Route snapshot hash mismatch:" in reason)
                or (isinstance(exc, sqlite3.OperationalError) and "locked" in reason.lower())
            )
            if not retryable:
                raise
            event = {"attempt": attempt, "error": type(exc).__name__, "reason": reason}
            retries.append(event)
            print(f"[COMMIT RETRY] {event}", flush=True)
            if attempt == max_attempts:
                raise RuntimeError(f"Commit retry budget exhausted after {attempt} attempts: {reason}") from exc
            sleep_fn(min(2.0, 0.2 * (2 ** (attempt - 1))) + jitter_fn(0.0, 0.1))
    raise AssertionError("unreachable commit retry state")


def _transient_body_hold(verdict: dict | None) -> bool:
    """Return true for telemetry/resource holds that may clear without intervention."""
    if not isinstance(verdict, dict):
        return False
    reasons = [str(reason).lower() for reason in verdict.get("reasons", [])]
    transient_markers = (
        "gpu_memory_at_or_above_limit_or_unavailable",
        "body_thermal_telemetry_missing_or_stale",
        "wsl_body_request_timed_out",
        "body_gate_unavailable",
    )
    return bool(reasons) and all(any(marker in reason for marker in transient_markers) for reason in reasons)


@dataclass
class DaemonTelemetry:
    daemon_id: str
    domain_key: str
    domain_name: str
    words_attempted: int = 0
    words_graduated: int = 0
    words_derived: int = 0
    sentences_synthesized: int = 0
    rectified_scalar_count: int = 0
    open_circuit_count: int = 0
    cycle_latencies: list[float] = field(default_factory=list)
    word_receipts: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    learning_test_count: int = 0
    last_learning_test: dict[str, Any] | None = None
    last_cycle_started_at: str | None = None
    last_cycle_completed_at: str | None = None
    valid_sentences: int = 0
    invalid_sentences: int = 0
    paragraphs_built: int = 0


class MultiDaemonOrchestrator:
    """Coordinates parallel concept-partitioned learning daemons with safe serialized lattice commits."""

    def __init__(
        self,
        domains: dict[str, dict[str, Any]] | None = None,
        status_file: Path | None = None,
        status_privacy_core=None,
    ):
        self.domains = domains or CONCEPT_DOMAINS
        self.commit_lock = threading.Lock()
        self.pool_lock = threading.Lock()
        self.status_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.status_file = status_file or Path(r"L:\LocalCoder\workspace\autonomy\learning\multi_daemon_status.json")
        if status_privacy_core is None:
            from aios_rebuild.privacy_core.privacy_core import PrivacyCore
            status_privacy_core = PrivacyCore()
        self.status_privacy_core = status_privacy_core
        self.status_file.parent.mkdir(parents=True, exist_ok=True)

        # Shared vocabulary coordinate state
        self.in_flight_words: set[str] = set()
        self.graduated_words: set[str] = set()
        self.quarantined_words: set[str] = set()
        self.graduated_since_test = 0
        self.retry_words: dict[str, list[str]] = {key: [] for key in self.domains}
        self._wiki_candidates: list[str] | None = None
        self._wiki_sources: dict[str, dict[str, str]] = {}
        self._ontology_support_cache: dict[tuple[str, str], bool] = {}
        self._attention_scorer: GraphAttentionScorer | None = None
        self._recurrent_attention: TopologyRecurrentAttention | None = None
        self._attention_scores: dict[str, float] = {}
        self.enforce_grounded_frontier = True
        self.learning_test_receipts: list[dict[str, Any]] = []
        # Git-like lineage for checkpoint heads; initialized lazily after the
        # first successful physical commit so startup remains read-only.
        self.checkpoint_backup: CheckpointBackup | None = None
        self.consolidation_lock = threading.Lock()
        self.consolidation_counter = 0
        self.consolidation_batches = 0
        self.consolidation_routes_replayed = 0
        self.consolidation_routes_failed = 0
        self.last_consolidation_monotonic = time.monotonic()
        # Sentence evidence is retained only as a bounded observation window.
        # Paragraph composition never writes these records into the ontology.
        self.composition_lock = threading.Lock()
        self.composition_records: list[dict[str, Any]] = []
        self.last_composition_report: dict[str, Any] = {
            "valid_sentence_count": 0,
            "invalid_sentence_count": 0,
            "novel_valid_sentence_count": 0,
            "paragraph_count": 0,
            "paragraphs": [],
        }

        # Populate genuinely graduated words from historical fractal mastery
        try:
            self.graduated_words = load_graduated_words()
            print(f"[ORCHESTRATOR] Initialized with {len(self.graduated_words)} retained mastery words (legacy mastery plus semantic graduations).")
        except Exception as e:
            print(f"[ORCHESTRATOR WARNING] Could not load graduated words: {e}")
            self.graduated_words = set()

        # Read-only attention cache over the latest verified graph.  It ranks
        # existing grounded candidates; it never authorizes or writes edges.
        try:
            attention_run = Path(latest_run())
            attention_graph = attention_run / "neuron_graph.sqlite3"
            if attention_graph.is_file():
                self._attention_scorer = GraphAttentionScorer(attention_graph, top_k=8)
                self._recurrent_attention = TopologyRecurrentAttention(self._attention_scorer)
                print(f"[ATTENTION] Loaded verified graph scorer from {attention_graph.name}", flush=True)
        except Exception as attention_error:
            print(f"[ATTENTION HOLD] scorer unavailable: {attention_error}", flush=True)

        # Concept queues per domain
        self.domain_queues: dict[str, list[str]] = {}
        for k, v in self.domains.items():
            if self.domains is CONCEPT_DOMAINS:
                unlearned = [w for w in v["words"] if w.lower() not in self.graduated_words]
            else:
                unlearned = list(v["words"])
            self.domain_queues[k] = list(unlearned)

        self.telemetry: dict[str, DaemonTelemetry] = {}
        for key, val in self.domains.items():
            self.telemetry[key] = DaemonTelemetry(
                daemon_id=f"daemon_{key}",
                domain_key=key,
                domain_name=val["name"],
            )

    def _load_consolidation_routes(self, limit: int = 4) -> list[dict[str, Any]]:
        """Return recent receipt-backed sentences eligible for replay.

        Replay is restricted to sentences already recorded with a committed
        snapshot. Tutor proposals and uncommitted candidates never enter this
        reservoir.
        """
        receipt_path = GRADUATION_RECEIPT_PATH
        if not receipt_path.is_file():
            return []
        routes: list[dict[str, Any]] = []
        seen: set[str] = set()
        previous = "GENESIS"
        records: list[dict[str, Any]] = []
        for raw in receipt_path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            item = json.loads(raw)
            if item.get("prev_hash") != previous:
                raise RuntimeError("Consolidation receipt chain corruption detected")
            body = {k: v for k, v in item.items() if k != "receipt_hash"}
            expected = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            if item.get("receipt_hash") != expected:
                raise RuntimeError("Consolidation receipt checksum mismatch")
            previous = expected
            records.append(item)
        for item in reversed(records):
            if len(routes) >= limit:
                break
            if (
                item.get("sentence_type") != "COMPOSED_FACT"
                or not item.get("provenance")
                or not item.get("snapshot_id")
                or not item.get("verification", {}).get("reloaded_recall")
            ):
                continue
            text = str(item.get("sentence", "")).strip()
            key = text.casefold()
            if not text or key in seen:
                continue
            seen.add(key)
            routes.append({
                "word": str(item.get("word", "")).strip().lower(),
                "sentence": text,
                "source_snapshot": str(item.get("snapshot_id")),
                "provenance": item.get("provenance"),
            })
        return routes

    def run_consolidation_batch(self, limit: int = 4) -> dict[str, Any]:
        """Replay existing verified routes through the normal commit gate."""
        routes = self._load_consolidation_routes(limit=limit)
        result = {"routes_selected": len(routes), "routes_replayed": 0, "routes_failed": 0}
        if not routes:
            return result
        with self.consolidation_lock:
            with self.commit_lock:
                for route in routes:
                    try:
                        commit_sentence_with_retry(route["sentence"])
                        result["routes_replayed"] += 1
                    except Exception as exc:
                        result["routes_failed"] += 1
                        print(f"[CONSOLIDATION HOLD] {route['sentence']!r}: {exc}", flush=True)
            self.consolidation_batches += 1
            self.consolidation_routes_replayed += result["routes_replayed"]
            self.consolidation_routes_failed += result["routes_failed"]
            print(f"[CONSOLIDATION] selected={result['routes_selected']} replayed={result['routes_replayed']} failed={result['routes_failed']}", flush=True)
        return result

    def _maybe_consolidate(self) -> None:
        with self.pool_lock:
            self.consolidation_counter += 1
            due = self.consolidation_counter % 25 == 0
        if due:
            self.run_consolidation_batch(limit=4)

    def claim_next_word(
        self,
        domain_key: str,
        engine: FractalCognitiveEngine,
        *,
        grounded_only: bool = True,
    ) -> str | None:
        """Atomically claim the next candidate word for a domain with 1-hop fallback."""
        def attention_score(candidate: str) -> float:
            if self._attention_scorer is None:
                return 0.0
            key = candidate.casefold()
            if key not in self._attention_scores:
                try:
                    ranked = self._attention_scorer.rank(candidate)
                    self._attention_scores[key] = max((item.attention for item in ranked), default=0.0)
                except Exception:
                    self._attention_scores[key] = 0.0
            graph_score = self._attention_scores[key]
            recurrent_score = (
                self._recurrent_attention.score([*self._recurrent_attention.context, candidate])
                if self._recurrent_attention is not None else 0.0
            )
            return 0.5 * graph_score + 0.5 * recurrent_score

        with self.pool_lock:
            retries = self.retry_words.setdefault(domain_key, [])
            while retries:
                cand = retries.pop(0)
                if cand not in self.graduated_words and cand not in self.in_flight_words:
                    self.in_flight_words.add(cand)
                    return cand
            # 1. First try unlearned words from static domain queue
            queue = self.domain_queues.get(domain_key, [])
            deferred: list[str] = []
            eligible_queue: list[str] = []
            while queue:
                cand = queue.pop(0).lower().strip()
                if (self.domains is not CONCEPT_DOMAINS or cand not in self.graduated_words) and cand not in self.in_flight_words and cand not in self.quarantined_words:
                    if grounded_only and self.domains is CONCEPT_DOMAINS and not self._has_ontology_support(cand, domain_key):
                        deferred.append(cand)
                        continue
                    eligible_queue.append(cand)
            if eligible_queue:
                cand = max(enumerate(eligible_queue), key=lambda pair: (attention_score(pair[1]), -pair[0]))[1]
                self.in_flight_words.add(cand)
                queue.extend(eligible_queue[1:] if eligible_queue and eligible_queue[0] == cand else eligible_queue)
                if cand in queue:
                    queue.remove(cand)
                return cand
            queue.extend(deferred)

            # 2. Dynamic 1-Hop Frontier expansion: harvest frontier words from the engine
            try:
                candidates = engine.harvest_1hop_frontier_candidates()
                eligible_frontier: list[tuple[str, str]] = []
                for cand_word, anchor in candidates:
                    cand = str(cand_word).lower().strip()
                    if cand in self.graduated_words or cand in self.in_flight_words or cand in self.quarantined_words:
                        continue
                    if grounded_only and not self._has_ontology_support(cand, domain_key):
                        continue
                    eligible_frontier.append((cand, anchor))
                    if len(eligible_frontier) >= 24:
                        break
                eligible_frontier.sort(key=lambda item: attention_score(item[0]), reverse=True)
                if eligible_frontier:
                    cand = eligible_frontier[0][0]
                    self.in_flight_words.add(cand)
                    return cand
            except Exception as e:
                print(f"[ORCHESTRATOR WARNING] Frontier harvesting failed: {e}", flush=True)

            # 3. Dynamic ontology fallback.  This is read-only and keeps the
            # daemon from spinning when the neuron frontier is exhausted.
            ontology_path = Path(__file__).resolve().parent / "data" / "lexicon_ontology.db"
            wiki_db = Path(__file__).resolve().parent / "data" / "wikipedia_emergent_shapes.db"
            try:
                if wiki_db.is_file():
                    raise LookupError("verified Wikipedia curriculum takes precedence over raw ontology fallback")
                with sqlite3.connect(f"file:{ontology_path.resolve()}?mode=ro", uri=True, timeout=1.0) as con:
                    rows = con.execute(
                        "SELECT lemma FROM lexical_entities WHERE lower(domain)=lower(?) ORDER BY entity_id LIMIT 256",
                        (domain_key,),
                    ).fetchall()
                for (candidate,) in rows:
                    cand = str(candidate).lower().strip()
                    if cand not in self.graduated_words and cand not in self.in_flight_words and cand not in self.quarantined_words:
                        self.in_flight_words.add(cand)
                        return cand
            except Exception as e:
                if not isinstance(e, LookupError):
                    print(f"[ORCHESTRATOR WARNING] Ontology fallback failed: {e}", flush=True)

            # 4. Wikipedia title curriculum.  This is a read-only vocabulary
            # source; use only the existing dual-parser VERIFIED shape index.
            if self._wiki_candidates is None:
                wiki_db = Path(__file__).resolve().parent / "data" / "wikipedia_emergent_shapes.db"
                candidates: list[str] = []
                try:
                    with sqlite3.connect(f"file:{wiki_db.resolve()}?mode=ro", uri=True, timeout=1.0) as con:
                        rows = con.execute(
                            "SELECT lower(entity), source_title, provenance_file FROM emergent_shapes WHERE status='VERIFIED' ORDER BY id"
                        ).fetchall()
                    for entity, title, source_file in rows:
                        if entity:
                            key = str(entity).strip()
                            candidates.append(key)
                            self._wiki_sources.setdefault(key, {"title": str(title or key), "source_file": str(source_file or "")})
                except Exception as exc:
                    print(f"[ORCHESTRATOR WARNING] Verified Wikipedia index unavailable: {exc}", flush=True)
                self._wiki_candidates = list(dict.fromkeys(candidates))
                print(f"[ORCHESTRATOR] Verified Wikipedia curriculum indexed: {len(self._wiki_candidates)} entities", flush=True)
            # Draw a small local neighborhood rather than ingesting the whole
            # verified reservoir.  Proximity is deterministic and derived from
            # the vocabulary already graduated by Viv.
            graduated = tuple(self.graduated_words)
            def proximity(word: str) -> tuple[int, int, str]:
                best = 0
                for known in graduated:
                    prefix = 0
                    for left, right in zip(word, known):
                        if left != right:
                            break
                        prefix += 1
                    suffix = 0
                    for left, right in zip(word[::-1], known[::-1]):
                        if left != right:
                            break
                        suffix += 1
                    best = max(best, prefix + suffix)
                return (-best, abs(len(word) - 5), word)
            # The verified index is the curriculum reservoir.  Do not cap this
            # to an arbitrary prefix: failed candidates are quarantined for the
            # current pass, and a prefix cap can falsely exhaust the learner
            # while thousands of verified titles remain available.
            candidates = sorted(self._wiki_candidates, key=proximity)
            for cand in candidates:
                if grounded_only and not self._has_ontology_support(cand, domain_key):
                    continue
                if cand not in self.graduated_words and cand not in self.in_flight_words and cand not in self.quarantined_words:
                    self.in_flight_words.add(cand)
                    source = self._wiki_sources.get(cand)
                    if source:
                        print(f"[WIKIPEDIA BOOK SELECTED] '{source['title']}' -> lesson entity '{cand}'", flush=True)
                    return cand

            # A failed pass must not permanently starve the daemon.  Preserve
            # the quarantine receipts for inspection, then open a new
            # curriculum pass once every non-graduated verified entity has been
            # attempted.  Graduated entities remain excluded.
            recycled = {
                cand for cand in self.quarantined_words
                if cand in self._wiki_candidates and cand not in self.graduated_words
            }
            if recycled:
                self.quarantined_words.difference_update(recycled)
                print(
                    f"[WIKIPEDIA CURRICULUM RECYCLE] reopened {len(recycled)} "
                    "verified entities for another learning pass",
                    flush=True,
                )
                for cand in candidates:
                    if grounded_only and not self._has_ontology_support(cand, domain_key):
                        continue
                    if cand not in self.graduated_words and cand not in self.in_flight_words:
                        self.in_flight_words.add(cand)
                        source = self._wiki_sources.get(cand)
                        if source:
                            print(f"[WIKIPEDIA BOOK SELECTED] '{source['title']}' -> lesson entity '{cand}'", flush=True)
                        return cand

            return None

    def _has_ontology_support(self, word: str, domain_key: str) -> bool:
        """Accept a curriculum word only when the ontology can ground it."""
        key = (word.casefold(), domain_key)
        cached = self._ontology_support_cache.get(key)
        if cached is not None:
            return cached
        try:
            direct = ontology_definition_facts(word, domain_key)
            typed = ontology_pos_grounded_facts(word, domain_key)
            composed = ontology_composed_facts(word, direct or typed)
            # A composed route is only meaningful when it starts from at least
            # one grounded SQL fact. Empty-anchor paths must never enter tutor.
            supported = bool(direct or typed) and bool(composed)
        except Exception:
            supported = False
        self._ontology_support_cache[key] = supported
        return supported

    def release_word(self, word: str, graduated: bool = False, quarantine: bool = False) -> None:
        """Release word from in-flight tracking."""
        with self.pool_lock:
            self.in_flight_words.discard(word)
            if self._recurrent_attention is not None:
                self._recurrent_attention.observe(word)
            if graduated:
                self.graduated_words.add(word)
            if quarantine:
                self.quarantined_words.add(word)

    def _run_learning_test_cycle(self) -> None:
        """Evaluate retained learned routes after each ten new graduations."""
        try:
            from autonomy.standard_learning_eval import evaluate
            receipt = evaluate()
            receipt["trigger"] = "TEN_NEW_GRADUATIONS"
            receipt["new_graduations"] = 10
            self.learning_test_receipts.append(receipt)
            if len(self.learning_test_receipts) > 10:
                self.learning_test_receipts.pop(0)
            for telemetry in self.telemetry.values():
                telemetry.learning_test_count += 1
                telemetry.last_learning_test = receipt
            print(
                "[LEARNING TEST] "
                f"held_out={receipt.get('fully_grounded_count')}/"
                f"{receipt.get('held_out_count')} "
                f"learned={receipt.get('learned_questions_grounded')}/"
                f"{receipt.get('learned_question_count')} "
                f"unknown_utility={receipt.get('unknown_probe', {}).get('utility')}",
                flush=True,
            )
        except Exception as exc:
            receipt = {
                "status": "HOLD",
                "reason": type(exc).__name__,
                "detail": str(exc),
                "trigger": "TEN_NEW_GRADUATIONS",
            }
            self.learning_test_receipts.append(receipt)
            for telemetry in self.telemetry.values():
                telemetry.learning_test_count += 1
                telemetry.last_learning_test = receipt
            print(f"[LEARNING TEST HOLD] {receipt}", flush=True)

    def _worker_daemon(
        self,
        domain_key: str,
        domain_meta: dict[str, Any],
        max_cycles: int = 0,
        pause_seconds: float = 1.0,
        enable_physical_commits: bool = True,
    ) -> DaemonTelemetry:
        """Isolated daemon worker executing fractal learning cycles on its assigned concept domain."""
        daemon_id = f"daemon_{domain_key}"
        t_record = self.telemetry[domain_key]
        print(f"\n[{daemon_id.upper()}] Initialized domain: '{domain_meta['name']}'")

        engine = FractalCognitiveEngine()
        cycles_done = 0

        while not self.stop_event.is_set():
            if max_cycles > 0 and cycles_done >= max_cycles:
                print(f"[{daemon_id.upper()}] Reached cycle budget ({max_cycles}). Worker terminating.")
                break

            target_word = self.claim_next_word(
                domain_key, engine, grounded_only=enable_physical_commits
            )
            if not target_word:
                if enable_physical_commits and time.monotonic() - self.last_consolidation_monotonic >= 30.0:
                    self.last_consolidation_monotonic = time.monotonic()
                    self.run_consolidation_batch(limit=4)
                print(f"[{daemon_id.upper()}] No candidate word available in frontier; waiting 5s...", flush=True)
                time.sleep(5.0)
                continue

            print(f"[{daemon_id.upper()}] Claimed target word: '{target_word}' (Cycle {cycles_done + 1})", flush=True)

            cycles_done += 1
            t_record.words_attempted += 1
            start_word = time.monotonic()
            t_record.last_cycle_started_at = datetime.now(timezone.utc).isoformat()
            self._save_heartbeat()
            if enable_physical_commits:
                self._maybe_consolidate()

            try:
                # 1. Execute Fractal Mastery Cycle across Micro-circuit, Game 1, Game 2, Game 3
                rec = engine.execute_fractal_mastery_cycle(
                    # Every continuous lesson now requires the local transformer
                    # tutor for contextual instruction.  TeacherBridge fails
                    # closed when LM Studio has no loaded model; there is no
                    # deterministic dialogue fallback here.
                    target_word, domain_hint=domain_key, use_teacher_context=enable_physical_commits
                )
                elapsed = time.monotonic() - start_word
                t_record.cycle_latencies.append(elapsed)

                novel_sentences = rec.get("novel_sentences", [])
                synthesis_count = rec.get("composed_fact_count", 0)
                t_record.sentences_synthesized += synthesis_count

                # Composition phase: evaluate existing route records and build
                # only relation-linked paragraph observations.  No tutor text
                # is accepted as evidence and no inferred edge is written back.
                sentence_records = rec.get("sentence_details", [])
                with self.composition_lock:
                    for item in sentence_records:
                        if isinstance(item, dict):
                            self.composition_records.append(dict(item))
                    self.composition_records = self.composition_records[-200:]
                    composition_report = compose_paragraphs(
                        self.composition_records,
                        self.graduated_words | {target_word},
                        known_neurons=(
                            self._attention_scorer.known_surfaces
                            if self._attention_scorer is not None else ()
                        ),
                    )
                    self.last_composition_report = composition_report
                t_record.valid_sentences += composition_report["valid_sentence_count"]
                t_record.invalid_sentences += composition_report["invalid_sentence_count"]
                t_record.paragraphs_built += composition_report["paragraph_count"]

                # Polarity & Cognitive Rectifier stats
                rectifier_info = rec.get("polarity_result", {}).get("rectifier", {})
                if rectifier_info.get("status") == "RECTIFIED_DC_CONDUCTION":
                    t_record.rectified_scalar_count += 1
                else:
                    t_record.open_circuit_count += 1

                # 2. Synchronized Atomic Lattice Commit
                commit_receipt = None
                committed_ok = False
                graduated_ok = False
                run_learning_test = False
                held_by_body = False
                body_hold_verdict = None
                commit_retries: list[dict] = []
                body_hold_retries: list[dict] = []
                if enable_physical_commits and rec.get("tri_sentence_mastery") and novel_sentences:
                    composed_to_commit = [
                        s for s in rec["sentence_details"]
                        if s.get("type") == "COMPOSED_FACT" and s["novel_to_history"]
                    ]
                    # tri_sentence_mastery is intentionally impossible without
                    # a composed fact.  Keep an explicit fail-closed guard so a
                    # future scorer cannot silently commit a raw definition.
                    if not composed_to_commit:
                        raise RuntimeError("Tri-sentence mastery lacks a composed semantic route")
                    selected_composition = composed_to_commit[0]
                    best_sentence = selected_composition["sentence"]

                    with self.commit_lock:
                        if self.stop_event.is_set():
                            self.release_word(target_word, graduated=False, quarantine=False)
                            break
                        print(f"[{daemon_id.upper()}] Acquired atomic commit lock for '{target_word}'. Inscribing: \"{best_sentence}\"", flush=True)
                        try:
                            last_body_hold = None
                            # A Body health hold is distinct from a SQLite replay.
                            # Do not wait indefinitely while owning commit_lock: that
                            # would starve the other partitions and hide the pending
                            # word instead of returning it to the explicit retry queue.
                            for body_attempt in range(1, 4):
                                try:
                                    commit_receipt, commit_retries = commit_sentence_with_retry(
                                        best_sentence,
                                        semantic_provenance=selected_composition.get("relation_path"),
                                    )
                                    break
                                except Exception as retry_error:
                                    retry_verdict = getattr(retry_error, "verdict", None)
                                    if not _transient_body_hold(retry_verdict):
                                        raise
                                    last_body_hold = retry_error
                                    body_hold_retries.append(retry_verdict)
                                    if body_attempt == 3:
                                        raise retry_error
                                    print(f"[{daemon_id.upper()}] BODY HOLD: retrying pending sentence for "
                                          f"'{target_word}' after 15s (attempt {body_attempt}/3): "
                                          f"{json.dumps(retry_verdict, sort_keys=True)}", flush=True)
                                    if self.stop_event.wait(15.0):
                                        raise last_body_hold
                            commit_retries = body_hold_retries + commit_retries
                            counts_after = commit_receipt.get("counts_after", {})
                            print(f"[{daemon_id.upper()}] COMMIT SUCCESS -> Snapshot: {os.path.basename(str(commit_receipt.get('run')))} | Neurons: {counts_after.get('neurons')} | Edges: {counts_after.get('edges')}", flush=True)
                            try:
                                active_run = Path(str(commit_receipt.get("run"))).resolve()
                                runs = sorted(
                                    (active_run.parent).glob("language-routes-*"),
                                    key=lambda p: p.stat().st_mtime,
                                    reverse=True,
                                )
                                parent_run = next((p for p in runs if p != active_run), None)
                                if self.checkpoint_backup is None:
                                    self.checkpoint_backup = CheckpointBackup(active_run.parent.parent)
                                backup_commit = self.checkpoint_backup.record_head(active_run, parent_run)
                                commit_receipt["backup_core_commit"] = backup_commit
                                print(f"[{daemon_id.upper()}] BACKUP CORE HEAD -> {backup_commit[:12]}", flush=True)
                            except Exception as backup_error:
                                detail = f"checkpoint_backup_error: {type(backup_error).__name__}: {backup_error}"
                                print(f"[{daemon_id.upper()}] {detail}", flush=True)
                                t_record.errors.append(detail)
                            semantic_clear = bool(
                                selected_composition.get("surprise_evaluation", {}).get(
                                    "eligible_for_writeback", False
                                )
                            )
                            graduation_tier = "SEMANTIC_GRADUATION" if semantic_clear else "DERIVED_SENTENCE"
                            graduation_receipt = append_graduation_receipt({
                                "event": graduation_tier,
                                "tier": graduation_tier,
                                "word": target_word,
                                "snapshot_id": os.path.basename(str(commit_receipt.get("run"))),
                                "snapshot_hash": commit_receipt.get("snapshot_hash"),
                                "sentence": best_sentence,
                                "sentence_type": selected_composition.get("type"),
                                "provenance": selected_composition.get("relation_path"),
                                "verification": {
                                    "counts_after": commit_receipt.get("counts_after"),
                                    "reloaded_recall": commit_receipt.get("reloaded_recall"),
                                },
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            }, self.status_privacy_core)
                            commit_receipt["graduation_receipt_hash"] = graduation_receipt["receipt_hash"]
                            committed_ok = True
                            t_record.words_derived += 1
                            graduated_ok = semantic_clear
                            if semantic_clear:
                                t_record.words_graduated += 1
                                self.graduated_since_test += 1
                                if self.graduated_since_test >= 10:
                                    self.graduated_since_test -= 10
                                    run_learning_test = True
                        except Exception as e:
                            body_hold_verdict = getattr(e, "verdict", None)
                            held_by_body = isinstance(body_hold_verdict, dict)
                            detail = json.dumps(body_hold_verdict, sort_keys=True) if held_by_body else str(e)
                            print(f"[{daemon_id.upper()}] Commit error for '{target_word}': {detail}", flush=True)
                            t_record.errors.append(f"commit_error({target_word}): {detail}")
                            # Persist health-hold attempts in the receipt/status even
                            # when no commit succeeds.  A zero retry count must not
                            # conceal the bounded retries that just occurred.
                            commit_retries = body_hold_retries
                            if held_by_body:
                                if _transient_body_hold(body_hold_verdict):
                                    with self.pool_lock:
                                        self.retry_words.setdefault(domain_key, []).append(target_word)
                                    print(
                                        f"[{daemon_id.upper()}] BODY HOLD is transient; queued '{target_word}' "
                                        "for explicit retry after a health window.", flush=True)
                                    time.sleep(2.0)
                                else:
                                    self.stop_event.set()

                self.release_word(target_word, graduated=graduated_ok,
                                  quarantine=not committed_ok and not held_by_body)
                t_record.last_cycle_completed_at = datetime.now(timezone.utc).isoformat()
                if run_learning_test and not self.stop_event.is_set():
                    self._run_learning_test_cycle()

                # Keep rolling receipt history
                receipt = {
                    "word": target_word,
                    "teacher_model_id": rec.get("teacher_model_id"),
                    "domain": domain_key,
                    "elapsed_sec": round(elapsed, 3),
                    "tri_mastery": rec.get("tri_sentence_mastery", False),
                    "failure_stage": rec.get("failure_stage"),
                    "failure_reason": rec.get("failure_reason"),
                    "synthesis_count": synthesis_count,
                    "grounded_fact_count": rec.get("grounded_fact_count", 0),
                    "composed_relation_paths": [
                        s.get("relation_path") for s in rec.get("sentence_details", [])
                        if s.get("type") == "COMPOSED_FACT" and s.get("relation_path")
                    ],
                    "composition_surprise_evaluations": [
                        s.get("surprise_evaluation") for s in rec.get("sentence_details", [])
                        if s.get("type") == "COMPOSED_FACT" and s.get("surprise_evaluation")
                    ],
                    "sentences": novel_sentences,
                    "utility_advertisements": rec.get("utility_advertisements", []),
                    "selected_utility": rec.get("selected_utility", 0.0),
                    "rectifier_status": rectifier_info.get("status", "OPEN_CIRCUIT"),
                    "v_out_rectified": rectifier_info.get("v_out_rectified", 0.0),
                    "commit_snapshot": os.path.basename(str(commit_receipt.get("run"))) if commit_receipt else None,
                    "commit_retries": commit_retries,
                    "body_hold_verdict": body_hold_verdict,
                    "composition": {
                        "valid_sentence_count": composition_report["valid_sentence_count"],
                        "invalid_sentence_count": composition_report["invalid_sentence_count"],
                        "novel_valid_sentence_count": composition_report["novel_valid_sentence_count"],
                        "paragraph_count": composition_report["paragraph_count"],
                        "paragraphs": composition_report["paragraphs"],
                    },
                }
                t_record.word_receipts.append(receipt)
                if len(t_record.word_receipts) > 100:
                    t_record.word_receipts.pop(0)

                # Periodic heartbeat write
                self._save_heartbeat()

                time.sleep(pause_seconds)

            except Exception as e:
                print(f"[{daemon_id.upper()}] Error processing '{target_word}': {e}", flush=True)
                t_record.errors.append(f"cycle_error({target_word}): {e}")
                self.release_word(target_word, graduated=False, quarantine=True)
                time.sleep(2.0)

        print(f"[{daemon_id.upper()}] Worker loop finished. Graduated: {t_record.words_graduated}/{t_record.words_attempted}")
        return t_record

    def _save_heartbeat(self) -> None:
        """Write live telemetry summary to JSON file."""
        try:
            decision = self.status_privacy_core.authorize_file_write(str(self.status_file))
            if decision.get("allowed") is not True:
                raise PermissionError(decision.get("reason", "status_write_denied"))
            total_attempted = sum(t.words_attempted for t in self.telemetry.values())
            total_graduated = sum(t.words_graduated for t in self.telemetry.values())
            total_derived = sum(t.words_derived for t in self.telemetry.values())
            total_sentences = sum(t.sentences_synthesized for t in self.telemetry.values())
            total_valid_sentences = sum(t.valid_sentences for t in self.telemetry.values())
            total_invalid_sentences = sum(t.invalid_sentences for t in self.telemetry.values())
            total_paragraphs = sum(t.paragraphs_built for t in self.telemetry.values())
            total_scalar = sum(t.rectified_scalar_count for t in self.telemetry.values())
            total_open = sum(t.open_circuit_count for t in self.telemetry.values())

            status = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "running": not self.stop_event.is_set(),
                "active_partitions": len(self.domains),
                "total_attempted": total_attempted,
                "total_graduated": total_graduated,
                "total_derived": total_derived,
                "total_sentences_synthesized": total_sentences,
                "composition_valid_sentences": total_valid_sentences,
                "composition_invalid_sentences": total_invalid_sentences,
                "composition_paragraphs_built": total_paragraphs,
                "latest_composition": {
                    "valid_sentence_count": self.last_composition_report.get("valid_sentence_count", 0),
                    "invalid_sentence_count": self.last_composition_report.get("invalid_sentence_count", 0),
                    "novel_valid_sentence_count": self.last_composition_report.get("novel_valid_sentence_count", 0),
                    "paragraph_count": self.last_composition_report.get("paragraph_count", 0),
                    "paragraphs": self.last_composition_report.get("paragraphs", [])[-2:],
                },
                "consolidation_batches": self.consolidation_batches,
                "consolidation_attempt_counter": self.consolidation_counter,
                "consolidation_routes_replayed": self.consolidation_routes_replayed,
                "consolidation_routes_failed": self.consolidation_routes_failed,
                "attention_enabled": self._attention_scorer is not None,
                "attention_cached_candidates": len(self._attention_scores),
                "recurrent_attention_enabled": self._recurrent_attention is not None,
                "recurrent_context_depth": len(self._recurrent_attention.context) if self._recurrent_attention else 0,
                "rectifier_scalar_dc_count": total_scalar,
                "rectifier_open_circuit_count": total_open,
                "latest_snapshot": os.path.basename(str(latest_verified_run())),
                "latest_candidate": os.path.basename(str(latest_run())),
                "per_daemon": {
                    k: {
                        "domain_name": t.domain_name,
                        "words_attempted": t.words_attempted,
                        "words_graduated": t.words_graduated,
                        "words_derived": t.words_derived,
                        "sentences_synthesized": t.sentences_synthesized,
                        "valid_sentences": t.valid_sentences,
                        "invalid_sentences": t.invalid_sentences,
                        "paragraphs_built": t.paragraphs_built,
                        "recent_word": t.word_receipts[-1]["word"] if t.word_receipts else None,
                        "error_count": len(t.errors),
                        "recent_errors": t.errors[-3:],
                        "commit_retry_count": sum(len(r.get("commit_retries", [])) for r in t.word_receipts),
                        "learning_test_count": t.learning_test_count,
                        "last_learning_test": t.last_learning_test,
                        "last_cycle_started_at": t.last_cycle_started_at,
                        "last_cycle_completed_at": t.last_cycle_completed_at,
                    }
                    for k, t in self.telemetry.items()
                },
            }
            with self.status_lock:
                temporary = None
                try:
                    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".tmp",
                                                     prefix=self.status_file.stem + ".",
                                                     dir=self.status_file.parent, delete=False) as stream:
                        temporary = Path(stream.name)
                        json.dump(status, stream, indent=2)
                        stream.flush()
                        os.fsync(stream.fileno())
                    replace_error = None
                    for attempt in range(1, 4):
                        try:
                            os.replace(temporary, self.status_file)
                            replace_error = None
                            break
                        except PermissionError as exc:
                            replace_error = exc
                            if attempt < 3:
                                time.sleep(0.25)
                    if replace_error is not None:
                        raise replace_error
                finally:
                    if temporary is not None and temporary.exists():
                        temporary.unlink()
        except Exception as exc:
            print(f"[ORCHESTRATOR HEARTBEAT HOLD] {type(exc).__name__}: {exc}", flush=True)

    def run_continuous(
        self,
        max_cycles_per_daemon: int = 0,
        pause_seconds: float = 1.0,
        enable_commits: bool = True,
    ) -> None:
        """Run parallel execution continuously across all concept domains."""
        self.enforce_grounded_frontier = bool(enable_commits)
        print("=" * 80)
        print("AIOS V2 -- PARALLEL MULTI-DAEMON CONTINUOUS COGNITIVE LEARNER")
        print(f"Active Partitions: {len(self.domains)}")
        for k, v in self.domains.items():
            print(f"  * [{k}] {v['name']} ({len(v['words'])} seed words)")
        print(f"Physical Database Commits: {enable_commits}")
        print(f"Max Cycles per Daemon: {max_cycles_per_daemon if max_cycles_per_daemon > 0 else 'UNLIMITED (Overnight)'}")
        print("=" * 80, flush=True)

        def _handle_exit(sig, frame):
            print("\n[ORCHESTRATOR] Shutdown signal received. Setting stop event...")
            self.stop_event.set()

        signal.signal(signal.SIGINT, _handle_exit)
        signal.signal(signal.SIGTERM, _handle_exit)

        with ThreadPoolExecutor(max_workers=len(self.domains), thread_name_prefix="Daemon") as executor:
            futures = {
                executor.submit(
                    self._worker_daemon,
                    domain_key=key,
                    domain_meta=val,
                    max_cycles=max_cycles_per_daemon,
                    pause_seconds=pause_seconds,
                    enable_physical_commits=enable_commits,
                ): key
                for key, val in self.domains.items()
            }

            for future in as_completed(futures):
                domain_key = futures[future]
                try:
                    future.result()
                except Exception as exc:
                    print(f"[ORCHESTRATOR ERROR] Daemon '{domain_key}' error: {exc}", flush=True)

        print("\n[ORCHESTRATOR] All daemon workers have cleanly shut down.")
        self.stop_event.set()
        self._save_heartbeat()

    def run_parallel_test(
        self,
        words_per_domain: int = 1,
        enable_commits: bool = False,
    ) -> dict[str, Any]:
        """Execute bounded parallel test across domains and return structured telemetry."""
        self.run_continuous(
            max_cycles_per_daemon=words_per_domain,
            pause_seconds=0.1,
            enable_commits=enable_commits,
        )
        total_attempted = sum(t.words_attempted for t in self.telemetry.values())
        total_graduated = sum(t.words_graduated for t in self.telemetry.values())
        total_sentences = sum(t.sentences_synthesized for t in self.telemetry.values())
        return {
            "total_attempted": total_attempted,
            "total_graduated": total_graduated,
            "total_sentences_synthesized": total_sentences,
            "per_daemon_telemetry": {
                k: {
                    "words_attempted": t.words_attempted,
                    "words_graduated": t.words_graduated,
                    "sentences_synthesized": t.sentences_synthesized,
                    "errors": t.errors,
                    "receipts": t.word_receipts,
                }
                for k, t in self.telemetry.items()
            },
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-Daemon Concept-Partitioned Cognitive Orchestrator")
    parser.add_argument("--max-cycles", type=int, default=0, help="Max words per daemon (0 = infinite overnight)")
    parser.add_argument("--pause", type=float, default=1.0, help="Pause seconds between cycles per daemon")
    parser.add_argument("--no-commit", action="store_true", help="Dry run without physical disk commits")
    args = parser.parse_args()

    orchestrator = MultiDaemonOrchestrator()
    orchestrator.run_continuous(
        max_cycles_per_daemon=args.max_cycles,
        pause_seconds=args.pause,
        enable_commits=not args.no_commit,
    )


if __name__ == "__main__":
    main()
