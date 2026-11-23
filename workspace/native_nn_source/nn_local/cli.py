"""Command-line entry points for the local NN rebuild."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import math
import os
import random
import re
import shutil
import sqlite3
import time
import zipfile
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
from itertools import permutations
from pathlib import Path
from typing import Any, Mapping, Sequence

from .cuda_backend import CudaLibrary
from .fixed_point import SCALE, govern_resource_rid
from .neuron_graph import (
    CurriculumStore,
    GraphStore,
    content_hash,
    make_neuron,
    stable_character_neuron_id,
    utc_now,
)
from .neuronizer import Neuronizer, UniversalCurriculumEngine
from .hydra_membrane import HydraRouteMembrane


WEBSTER_OPAQUE_CLASS_MAP = {
    "n.": "R0",
    "v.": "R1",
    "a.": "R2",
    "adv.": "R3",
    "pron.": "R4",
    "prep.": "R5",
    "conj.": "R6",
    "interj.": "R7",
    "p.": "R8",
}

# Human/CPU navigation names for the neuron dictionary. This mapping is used
# only by the exporter; it is never copied into GPU-visible neuron payloads.
NEURON_DICTIONARY_ROLE_FOLDERS = {
    "n.": "nouns",
    "v.": "verbs",
    "a.": "adjectives",
    "adv.": "adverbs",
    "pron.": "pronouns",
    "prep.": "prepositions",
    "conj.": "conjunctions",
    "interj.": "interjections",
    "p.": "participles",
}

WINDOWS_RESERVED_NEURON_DICTIONARY_PREFIXES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}

# CPU-private Webster evidence rules.  Human meanings never cross into neuron
# payloads; the learner receives only one-bit consequence for S0..S4 guesses.
WEBSTER_OPAQUE_SEMANTIC_RULES = {
    "S0": ("pl. of man", "a man; one"),
    "S1": ("what is fed upon", "anything eaten for nourishment", "flesh of animals used as food"),
    "S2": ("chew and swallow as food", "to take food; to feed"),
    "S3": ("to go swiftly", "to move by quicker action than in walking"),
    "S4": ("in a fast or rapid manner", "quickly; swiftly"),
}

# CPU-private evidence for communication-style name requests.  Only the hash
# of this rule enters an induced intent neuron; the definition words and the
# candidate surface remain on the CPU side of the boundary.
SOCIAL_COMMUNICATION_HEAD_DEFINITION_PROBES = (
    "to utter or express in words",
    "to utter or recite",
    "to tell;",
    "to make known",
)


class LiveResourceRidGovernor:
    """One-second real telemetry governor with zero at safe resource ceilings."""

    def __init__(
        self, *, disk_path: Path, disk_reserve_gb: float,
        ram_reserve_gb: float, vram_reserve_mb: float,
        cpu_ceiling_percent: float, gpu_ceiling_percent: float,
        power_ceiling_percent: float, max_seconds: float,
        slowdown_seconds: float,
    ):
        import psutil
        import pynvml

        self.psutil = psutil
        self.pynvml = pynvml
        self.disk_path = disk_path
        self.started = time.monotonic()
        self.max_seconds = float(max_seconds)
        self.slowdown_us = max(0, int(float(slowdown_seconds) * 1_000_000))
        self.ram_reserve = int(float(ram_reserve_gb) * 1_000_000_000)
        self.vram_reserve = int(float(vram_reserve_mb) * 1_000_000)
        self.disk_reserve = int(float(disk_reserve_gb) * 1_000_000_000)
        self.cpu_ceiling = float(cpu_ceiling_percent)
        self.gpu_ceiling = float(gpu_ceiling_percent)
        self.power_ceiling_percent = float(power_ceiling_percent)
        pynvml.nvmlInit()
        self.gpu = pynvml.nvmlDeviceGetHandleByIndex(0)
        self.psutil.cpu_percent(interval=0.1)
        self.baseline = self._raw()
        self.last_sample = self.started
        self.current = self._state(self.baseline, stage="BASELINE")

    @staticmethod
    def _free_headroom(current: float, reserve: float, baseline: float) -> int:
        capacity = baseline - reserve
        if capacity <= 0:
            return 0
        return max(0, min(SCALE, int((current - reserve) * SCALE / capacity)))

    @staticmethod
    def _load_headroom(current: float, baseline: float, ceiling: float) -> int:
        capacity = ceiling - baseline
        if capacity <= 0:
            return 0
        return max(0, min(SCALE, int((ceiling - current) * SCALE / capacity)))

    def _raw(self) -> dict[str, float]:
        memory = self.psutil.virtual_memory()
        gpu_memory = self.pynvml.nvmlDeviceGetMemoryInfo(self.gpu)
        gpu_util = self.pynvml.nvmlDeviceGetUtilizationRates(self.gpu)
        power_mw = self.pynvml.nvmlDeviceGetPowerUsage(self.gpu)
        power_limit_mw = self.pynvml.nvmlDeviceGetEnforcedPowerLimit(self.gpu)
        return {
            "ram_available_bytes": float(memory.available),
            "vram_free_bytes": float(gpu_memory.free),
            "disk_free_bytes": float(shutil.disk_usage(self.disk_path).free),
            "cpu_percent": float(self.psutil.cpu_percent(interval=None)),
            "gpu_percent": float(gpu_util.gpu),
            "power_percent": float(power_mw) * 100.0 / max(1.0, float(power_limit_mw)),
        }

    def _state(self, raw: dict[str, float], *, stage: str) -> dict[str, object]:
        elapsed = time.monotonic() - self.started
        headrooms = {
            "RAM": self._free_headroom(
                raw["ram_available_bytes"], self.ram_reserve,
                self.baseline["ram_available_bytes"],
            ),
            "VRAM": self._free_headroom(
                raw["vram_free_bytes"], self.vram_reserve,
                self.baseline["vram_free_bytes"],
            ),
            "DISK": self._free_headroom(
                raw["disk_free_bytes"], self.disk_reserve,
                self.baseline["disk_free_bytes"],
            ),
            "CPU": self._load_headroom(
                raw["cpu_percent"], self.baseline["cpu_percent"], self.cpu_ceiling,
            ),
            "GPU": self._load_headroom(
                raw["gpu_percent"], self.baseline["gpu_percent"], self.gpu_ceiling,
            ),
            "POWER": self._load_headroom(
                raw["power_percent"], self.baseline["power_percent"],
                self.power_ceiling_percent,
            ),
            "TIME": max(
                0, min(SCALE, int((self.max_seconds - elapsed) * SCALE / self.max_seconds))
            ) if self.max_seconds > 0 else 0,
        }
        governed = govern_resource_rid(
            headrooms, slowdown_microseconds=self.slowdown_us
        )
        return {
            "schema": "NN_RESOURCE_RID_HEARTBEAT_V1",
            "stage": stage,
            "sampled_unix": time.time(),
            "RID_t": governed.rid,
            "delay_microseconds": governed.delay_microseconds,
            "bottleneck": governed.bottleneck,
            "headrooms": governed.headrooms,
            "stop": governed.stop,
            "raw": {key: round(value, 3) for key, value in raw.items()},
        }

    def pace(self, stage: str) -> dict[str, object]:
        now = time.monotonic()
        if now - self.last_sample >= 1.0:
            self.current = self._state(self._raw(), stage=stage)
            self.last_sample = now
        else:
            self.current = {**self.current, "stage": stage}
        if bool(self.current["stop"]):
            raise RuntimeError(
                f"HOLD_RESOURCE_RID_ZERO bottleneck={self.current['bottleneck']}"
            )
        delay = int(self.current["delay_microseconds"]) / 1_000_000.0
        if delay > 0:
            time.sleep(delay)
        return dict(self.current)

    def close(self) -> None:
        self.pynvml.nvmlShutdown()


def _persistent_sqlite_hashes(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for candidate in (path, Path(str(path) + "-wal")):
        if candidate.is_file() and candidate.stat().st_size > 0:
            result[str(candidate)] = hashlib.sha256(candidate.read_bytes()).hexdigest().upper()
    return result


def command_frozen_recall(args: argparse.Namespace) -> int:
    """Recall the newest admitted words without permitting graph/evidence writes."""
    from .steel_brain_store import SQLiteNeuronGraphStore

    graph_path = args.graph.resolve()
    curriculum_path = args.curriculum_db.resolve()
    before = {
        "graph": _persistent_sqlite_hashes(graph_path),
        "curriculum": _persistent_sqlite_hashes(curriculum_path),
    }
    attempts: list[dict[str, object]] = []
    with SQLiteNeuronGraphStore(graph_path, readonly=True) as store:
        rows = list(store.connection.execute(
            "SELECT token_id,neuron_id FROM neurons WHERE kind='WORD' "
            "ORDER BY token_id DESC LIMIT ?",
            (args.limit,),
        ))
        rows.reverse()
        with CurriculumStore(curriculum_path, readonly=True) as curriculum:
            engine = UniversalCurriculumEngine(store, CudaLibrary(), curriculum)
            for row in rows:
                neuron = store.load_neuron(str(row["neuron_id"]))
                word = str(neuron.get("center_attractor", {}).get("learned_surface", ""))
                for confirmation in range(args.confirmations):
                    seed = (
                        args.seed
                        ^ (int(row["token_id"]) * 0x9E3779B1)
                        ^ ((confirmation + 1) * 1_000_003)
                    )
                    result = (
                        engine.recall_admitted_word(str(row["neuron_id"]), seed=seed)
                        if args.mode == "anchored"
                        else engine.attempt_word(word, seed=seed)
                    )
                    output = str(result.get("output", ""))
                    attempts.append({
                        "token_id": int(row["token_id"]),
                        "neuron_id": str(row["neuron_id"]),
                        "word": word,
                        "confirmation": confirmation + 1,
                        "seed": seed,
                        "output": output,
                        "verdict": "PASS"
                        if result.get("state") == "PASS" and output == word
                        else "FAIL",
                        "route": list(result.get("route", [])),
                        "decisions": list(result.get("decisions", [])),
                    })
        audit = store.audit()
    after = {
        "graph": _persistent_sqlite_hashes(graph_path),
        "curriculum": _persistent_sqlite_hashes(curriculum_path),
    }
    unchanged = before == after
    passed = sum(row["verdict"] == "PASS" for row in attempts)
    report = {
        "schema": "NN_FROZEN_WORD_RECALL_V1",
        "state": "PASS"
        if len(rows) == args.limit and passed == len(attempts) and unchanged
        and audit["state"] == "PASS"
        else "HOLD",
        "words": len(rows),
        "mode": args.mode,
        "confirmations_per_word": args.confirmations,
        "attempts": len(attempts),
        "passes": passed,
        "failures": len(attempts) - passed,
        "persistent_state_unchanged": unchanged,
        "persistent_hashes_before": before,
        "persistent_hashes_after": after,
        "graph_audit": audit,
        "raw_attempts": attempts,
        "promotion_performed": False,
        "deployment_performed": False,
    }
    destination = args.output.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)
    print(json.dumps({key: value for key, value in report.items()
                      if key != "raw_attempts"}, indent=2))
    return 0 if report["state"] == "PASS" else 2


def command_learn_roles(args: argparse.Namespace) -> int:
    """Teach existing WORD neurons one CPU-private opaque tag group."""

    from .leakage_audit import audit_gpu_payload
    from .steel_brain_store import SQLiteNeuronGraphStore

    graph_path = args.graph.resolve()
    curriculum_path = args.curriculum_db.resolve()
    dictionary_path = args.dictionary.resolve()
    rows = json.loads(dictionary_path.read_text(encoding="utf-8"))
    if args.length is not None:
        if args.profile != "grammar":
            raise ValueError("length-rung selection currently requires the Webster grammar profile")
        requested = sorted({
            str(row.get("word", "")).strip().lower()
            for row in rows
            if len(str(row.get("word", "")).strip()) == args.length
            and str(row.get("word", "")).strip().isascii()
            and str(row.get("word", "")).strip().isalpha()
            and str(row.get("pos", "")).strip().lower() in WEBSTER_OPAQUE_CLASS_MAP
        })
        source_word_count = len(requested)
        start = max(0, int(args.offset))
        stop = None if args.limit is None else start + max(1, int(args.limit))
        requested = requested[start:stop]
    else:
        requested = [word.strip().lower() for word in args.words.split(",") if word.strip()]
        source_word_count = len(requested)
    if not requested:
        raise ValueError("role curriculum selected no words")
    teacher: dict[str, set[str]] = {word: set() for word in requested}
    evidence_rows: dict[str, list[str]] = {word: [] for word in requested}
    for row in rows:
        word = str(row.get("word", "")).strip().lower()
        if word not in teacher:
            continue
        canonical_row = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if args.profile == "grammar":
            channel = WEBSTER_OPAQUE_CLASS_MAP.get(str(row.get("pos", "")).strip().lower())
            if channel is not None:
                teacher[word].add(channel)
                evidence_rows[word].append(hashlib.sha256(canonical_row.encode("utf-8")).hexdigest().upper())
        else:
            definition_blob = " ".join(str(value).lower() for value in row.get("definitions", []))
            matched = False
            for channel, needles in WEBSTER_OPAQUE_SEMANTIC_RULES.items():
                if any(needle in definition_blob for needle in needles):
                    teacher[word].add(channel)
                    matched = True
            if matched:
                evidence_rows[word].append(hashlib.sha256(canonical_row.encode("utf-8")).hexdigest().upper())
    missing_teacher = sorted(word for word, channels in teacher.items() if not channels)
    if missing_teacher:
        raise ValueError(f"requested words have no supported Webster class: {missing_teacher}")
    before = {
        "graph": _persistent_sqlite_hashes(graph_path),
        "curriculum": _persistent_sqlite_hashes(curriculum_path),
    }
    results: list[dict[str, object]] = []
    trace_handle = None
    if args.trace is not None:
        trace_path = args.trace.resolve()
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        if trace_path.exists():
            raise FileExistsError("role-learning trace is append-only; choose a fresh path")
        trace_handle = trace_path.open("x", encoding="utf-8", buffering=1)
    with SQLiteNeuronGraphStore(graph_path) as store:
        manifest = store.manifest()
        missing_graph = sorted(word for word in requested if word not in manifest["word_index"])
        if missing_graph:
            raise ValueError(f"requested words are not admitted WORD neurons: {missing_graph}")
        with CurriculumStore(curriculum_path) as curriculum:
            engine = UniversalCurriculumEngine(store, CudaLibrary(), curriculum)
            for index, word in enumerate(requested):
                learner = (
                    engine.learn_word_class_profile
                    if args.profile == "grammar"
                    else engine.learn_word_semantic_profile
                )
                def publish_role_draw(row: dict[str, object]) -> None:
                    if trace_handle is None:
                        return
                    trace_handle.write(json.dumps({
                        **row,
                        "lesson_expected": word,
                        "candidate": [word],
                        "profile_group": args.profile,
                        "curriculum_length": args.length,
                        "synthetic_example": False,
                        "cpu_returned_one_bit_only": True,
                    }, sort_keys=True) + "\n")

                learner_kwargs: dict[str, object] = {
                    "seed": args.seed + index * 10_000_019,
                    "learning_rounds": args.learning_rounds,
                    "frozen_draws": args.frozen_draws,
                }
                if args.profile == "grammar":
                    learner_kwargs["trace_sink"] = publish_role_draw
                result = learner(
                    str(manifest["word_index"][word]), sorted(teacher[word]),
                    **learner_kwargs,
                )
                result["word"] = word
                result["teacher_evidence_row_sha256"] = evidence_rows[word]
                results.append(result)
        audit = store.audit()
        leakage = {
            word: audit_gpu_payload(store.load_neuron(str(manifest["word_index"][word])))
            for word in requested
        }
    if trace_handle is not None:
        trace_handle.close()
    after = {
        "graph": _persistent_sqlite_hashes(graph_path),
        "curriculum": _persistent_sqlite_hashes(curriculum_path),
    }
    if args.compact:
        compact_results: list[dict[str, object]] = []
        for result in results:
            learning_attempts = result.pop("learning_attempts", [])
            frozen_draws = result.pop("frozen_draws", [])
            result["learning_attempt_count"] = len(learning_attempts)
            result["learning_attempts_sha256"] = hashlib.sha256(
                json.dumps(learning_attempts, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest().upper()
            result["frozen_draw_count"] = len(frozen_draws)
            result["frozen_draws_sha256"] = hashlib.sha256(
                json.dumps(frozen_draws, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest().upper()
            compact_results.append(result)
        results = compact_results
    report = {
        "schema": (
            "NN_OPAQUE_WORD_CLASS_LEARNING_REPORT_V1"
            if args.profile == "grammar"
            else "NN_OPAQUE_WORD_SEMANTIC_LEARNING_REPORT_V1"
        ),
        "state": "PASS"
        if all(item["state"] == "PASS" for item in results)
        and audit["state"] == "PASS"
        and all(item["state"] == "PASS" for item in leakage.values())
        else "HOLD",
        "teacher_source": str(dictionary_path),
        "teacher_source_sha256": hashlib.sha256(dictionary_path.read_bytes()).hexdigest().upper(),
        "profile_group": args.profile,
        "curriculum_length": args.length,
        "curriculum_source_word_count": source_word_count,
        "curriculum_offset": int(args.offset),
        "curriculum_limit": args.limit,
        "requested_word_count": len(requested),
        "compact_evidence": bool(args.compact),
        "cpu_private_mapping": (
            WEBSTER_OPAQUE_CLASS_MAP if args.profile == "grammar"
            else {channel: list(needles) for channel, needles in WEBSTER_OPAQUE_SEMANTIC_RULES.items()}
        ),
        "results": results,
        "graph_audit": audit,
        "leakage_audit": leakage,
        "persistent_hashes_before": before,
        "persistent_hashes_after": after,
        "canonical_mutation_authorized": False,
    }
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report is not None:
        path = args.report.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if report["state"] == "PASS" else 2


def command_learn_identity_tags(args: argparse.Namespace) -> int:
    """Teach CPU-authored opaque identity tags, or HOLD before writes when vocabulary is absent."""

    from .leakage_audit import audit_gpu_payload
    from .steel_brain_store import SQLiteNeuronGraphStore

    graph_path = args.graph.resolve()
    curriculum_path = args.curriculum_db.resolve()
    contract_path = args.identity_contract.resolve()
    raw_contract = contract_path.read_bytes()
    contract = json.loads(raw_contract.decode("utf-8"))
    if contract.get("schema") != "NN_CPU_PRIVATE_IDENTITY_TAG_CONTRACT_V1":
        raise ValueError("unsupported CPU-private identity contract schema")
    word_tags = contract.get("word_tags")
    if not isinstance(word_tags, dict) or not word_tags:
        raise ValueError("identity contract word_tags required")
    teacher = {str(word).strip().lower(): {str(tag) for tag in tags}
               for word, tags in word_tags.items() if isinstance(tags, list)}
    if args.words:
        requested = {value.strip().lower() for value in args.words.split(",") if value.strip()}
        unknown = sorted(requested - set(teacher))
        if unknown:
            raise ValueError(f"identity contract has no requested words: {unknown}")
        teacher = {word: tags for word, tags in teacher.items() if word in requested}
    if not teacher or any(not tags or not tags.issubset(UniversalCurriculumEngine.WORD_IDENTITY_CHANNELS)
                          for tags in teacher.values()):
        raise ValueError("identity contract requires nonempty I0..I4 tag sets")
    before = {"graph": _persistent_sqlite_hashes(graph_path), "curriculum": _persistent_sqlite_hashes(curriculum_path)}
    with SQLiteNeuronGraphStore(graph_path, readonly=True) as store:
        manifest = store.manifest()
        missing = sorted(word for word in teacher if word not in manifest["word_index"])
        preflight_audit = store.audit()
    if missing:
        report = {
            "schema": "NN_OPAQUE_WORD_IDENTITY_LEARNING_REPORT_V1",
            "state": "HOLD_IDENTITY_VOCABULARY_MISSING",
            "identity_id": contract.get("identity_id"),
            "teacher_source": str(contract_path),
            "teacher_source_sha256": hashlib.sha256(raw_contract).hexdigest().upper(),
            "missing_admitted_words": missing,
            "identity_tags_written": 0,
            "graph_audit": preflight_audit,
            "persistent_hashes_before": before,
            "persistent_hashes_after": {"graph": _persistent_sqlite_hashes(graph_path), "curriculum": _persistent_sqlite_hashes(curriculum_path)},
            "canonical_mutation_authorized": False,
        }
    else:
        results: list[dict[str, object]] = []
        with SQLiteNeuronGraphStore(graph_path) as store:
            manifest = store.manifest()
            with CurriculumStore(curriculum_path) as curriculum:
                engine = UniversalCurriculumEngine(store, CudaLibrary(), curriculum)
                for index, word in enumerate(sorted(teacher)):
                    result = engine.learn_word_identity_profile(
                        str(manifest["word_index"][word]), sorted(teacher[word]),
                        seed=args.seed + index * 10_000_019,
                        learning_rounds=args.learning_rounds, frozen_draws=args.frozen_draws,
                    )
                    result["word"] = word
                    results.append(result)
            audit = store.audit()
            leakage = {word: audit_gpu_payload(store.load_neuron(str(manifest["word_index"][word]))) for word in teacher}
        report = {
            "schema": "NN_OPAQUE_WORD_IDENTITY_LEARNING_REPORT_V1",
            "state": "PASS" if all(item["state"] == "PASS" for item in results) and audit["state"] == "PASS"
                     and all(item["state"] == "PASS" for item in leakage.values()) else "HOLD",
            "identity_id": contract.get("identity_id"),
            "teacher_source": str(contract_path),
            "teacher_source_sha256": hashlib.sha256(raw_contract).hexdigest().upper(),
            "profile_group": "identity",
            "results": results,
            "graph_audit": audit,
            "leakage_audit": leakage,
            "persistent_hashes_before": before,
            "persistent_hashes_after": {"graph": _persistent_sqlite_hashes(graph_path), "curriculum": _persistent_sqlite_hashes(curriculum_path)},
            "canonical_mutation_authorized": False,
        }
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report is not None:
        path = args.report.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0 if report["state"] == "PASS" else 2


def command_learn_foundation_token(args: argparse.Namespace) -> int:
    """Admit one Architect-authored candidate foundation token through normal word learning."""

    from .leakage_audit import audit_gpu_payload
    from .steel_brain_store import SQLiteNeuronGraphStore

    candidate_root = args.candidate_root.resolve()
    graph_path = args.graph.resolve()
    curriculum_path = args.curriculum_db.resolve()
    contract_path = args.foundation_contract.resolve()
    if not graph_path.is_relative_to(candidate_root) or not curriculum_path.is_relative_to(candidate_root):
        raise ValueError("foundation-token command requires graph and curriculum inside candidate root")
    contract_raw = contract_path.read_bytes()
    contract = json.loads(contract_raw.decode("utf-8"))
    if contract.get("schema") != "NN_CPU_PRIVATE_FOUNDATION_TOKEN_CONTRACT_V1":
        raise ValueError("unsupported foundation token contract schema")
    tokens = {str(item.get("surface", "")).strip().lower(): dict(item)
              for item in contract.get("tokens", []) if isinstance(item, dict)}
    token = str(args.token).strip().lower()
    if token not in tokens or not token.isascii() or not token.isalpha():
        raise ValueError("requested foundation token is not CPU-authorized")
    before = {"graph": _persistent_sqlite_hashes(graph_path), "curriculum": _persistent_sqlite_hashes(curriculum_path)}
    trace_path = args.trace.resolve()
    if trace_path.exists():
        raise FileExistsError("foundation trace is append-only; choose a fresh path")
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    hydra_bin = args.hydra_bin.resolve() if args.hydra_bin is not None else None
    hydra_trace = args.hydra_trace.resolve() if args.hydra_trace is not None else None
    if (hydra_bin is None) != (hydra_trace is None):
        raise ValueError("foundation token Hydra requires both --hydra-bin and --hydra-trace")
    if hydra_bin is not None and not hydra_bin.is_file():
        raise FileNotFoundError(hydra_bin)
    with SQLiteNeuronGraphStore(graph_path) as store:
        manifest = store.manifest()
        missing_characters = sorted(set(token) - set(manifest["character_index"]))
        if missing_characters:
            raise ValueError(f"foundation token has no admitted character base: {missing_characters}")
        with CurriculumStore(curriculum_path) as curriculum:
            # Foundation is a protection/admission property, not a separate
            # route-evidence universe.  A new multi-token foundation word must
            # traverse consequence evidence already earned by the WORD
            # learner; an empty FOUNDATION namespace hard-denies every
            # non-terminal split and only permits accidental one-token births.
            hydra = (HydraRouteMembrane(curriculum, hydra_bin, hydra_trace, evidence_level="WORD")
                     if hydra_bin is not None and hydra_trace is not None else None)
            engine = UniversalCurriculumEngine(
                store, CudaLibrary(), curriculum,
                assembly_evidence=True, route_truth_provider=hydra,
            )
            with trace_path.open("x", encoding="utf-8", buffering=1) as trace:
                def publish(row: dict[str, object]) -> None:
                    trace.write(json.dumps({
                        **row,
                        "candidate_only": True,
                        "foundation_token": True,
                        "teacher_contract_sha256": hashlib.sha256(contract_raw).hexdigest().upper(),
                    }, sort_keys=True) + "\n")
                result = engine.learn_word(
                    token,
                    lesson_id="FOUNDATION-" + hashlib.sha256(contract_raw + token.encode("utf-8")).hexdigest()[:32].upper(),
                    source_handle="ARCHITECT_FOUNDATION_TOKEN:" + hashlib.sha256(contract_raw).hexdigest().upper(),
                    seed=args.seed,
                    max_attempts=args.max_attempts,
                    confirmations=args.confirmations,
                    foundation=True,
                    trace_sink=publish,
                )
            hydra_metrics = hydra.metrics() if hydra is not None else {"enabled": False}
        audit = store.audit()
        word_id = store.manifest()["word_index"].get(token)
        protection = store.load_neuron(str(word_id)).get("protection", {}) if word_id else {}
        leakage = audit_gpu_payload(store.load_neuron(str(word_id))) if word_id else {"state": "HOLD"}
    after = {"graph": _persistent_sqlite_hashes(graph_path), "curriculum": _persistent_sqlite_hashes(curriculum_path)}
    report = {
        "schema": "NN_FOUNDATION_TOKEN_LEARNING_REPORT_V1",
        "state": "PASS" if result.get("state") == "PASS" and result.get("foundation") is True
                 and protection.get("foundation") is True and audit.get("state") == "PASS"
                 and leakage.get("state") == "PASS" else "HOLD",
        "token": token,
        "teacher_contract": str(contract_path),
        "teacher_contract_sha256": hashlib.sha256(contract_raw).hexdigest().upper(),
        "result": result,
        "protection": protection,
        "hydra_route_membrane": hydra_metrics,
        "graph_audit": audit,
        "leakage_audit": leakage,
        "persistent_hashes_before": before,
        "persistent_hashes_after": after,
        "canonical_mutation_authorized": False,
        "promotion_performed": False,
        "deployment_performed": False,
    }
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    args.report.resolve().write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0 if report["state"] == "PASS" else 2


def command_learn_svo(args: argparse.Namespace) -> int:
    """Let Viv generate one utterance; CPU grades three separate one-bit gates."""

    from .leakage_audit import audit_gpu_payload
    from .steel_brain_store import SQLiteNeuronGraphStore

    graph_path = args.graph.resolve()
    curriculum_path = args.curriculum_db.resolve()
    dictionary_path = args.dictionary.resolve()
    teacher_path = args.teacher.resolve()
    hydra_bin = args.hydra_bin.resolve() if args.hydra_bin is not None else None
    hydra_trace = args.hydra_trace.resolve() if args.hydra_trace is not None else None
    if (hydra_bin is None) != (hydra_trace is None):
        raise ValueError("SVO Hydra requires both --hydra-bin and --hydra-trace")
    if hydra_bin is not None and not hydra_bin.is_file():
        raise FileNotFoundError(hydra_bin)
    dictionary_raw = dictionary_path.read_bytes()
    dictionary_sha256 = hashlib.sha256(dictionary_raw).hexdigest().upper()
    teacher_raw = teacher_path.read_bytes()
    teacher_payload = json.loads(teacher_raw.decode("utf-8"))
    external_evidence: list[str] = []
    for source in teacher_payload.get("evidence_sources", ()):
        source_path = Path(str(source.get("path", ""))).resolve()
        expected_sha = str(source.get("sha256", "")).upper()
        if not source_path.is_file() or hashlib.sha256(source_path.read_bytes()).hexdigest().upper() != expected_sha:
            raise ValueError("CPU-private utterance evidence source is missing or stale")
        external_evidence.append(expected_sha)
    teacher_schema = str(teacher_payload.get("schema", ""))
    if teacher_schema not in {
        "NN_CPU_PRIVATE_SENTENCE_FACTS_V1",
        "NN_CPU_PRIVATE_QUESTION_FACTS_V1",
        "NN_CPU_PRIVATE_SOCIAL_ACTS_V1",
        "NN_CPU_PRIVATE_PHRASE_FACTS_V1",
    }:
        raise ValueError("unsupported CPU-private utterance fact schema")
    interrogative = teacher_schema == "NN_CPU_PRIVATE_QUESTION_FACTS_V1"
    social = teacher_schema == "NN_CPU_PRIVATE_SOCIAL_ACTS_V1"
    phrase = teacher_schema == "NN_CPU_PRIVATE_PHRASE_FACTS_V1"
    if str(teacher_payload.get("dictionary_sha256")) != dictionary_sha256:
        raise ValueError("CPU-private sentence facts do not match the Webster source")
    facts = {
        str(item["fact_id"]): item for item in teacher_payload.get("facts", [])
    }
    if args.fact_id not in facts:
        raise ValueError("unknown CPU-private fact id")
    fact = facts[args.fact_id]
    composition_unit_surfaces = tuple(
        tuple(str(word).lower() for word in unit)
        for unit in fact.get("composition_units", ())
    )
    if composition_unit_surfaces and (
        len(composition_unit_surfaces) < 2
        or any(len(unit) < 2 for unit in composition_unit_surfaces)
    ):
        raise ValueError("recursive composition requires at least two multiword phrase units")
    provenance_binding = fact.get("provenance_binding_v1")
    provenance_binding_summary: dict[str, Any] | None = None
    provenance_truth = True
    if provenance_binding is not None:
        if not isinstance(provenance_binding, dict):
            raise ValueError("provenance binding must be an object")
        relation_id = str(
            provenance_binding.get("source_relation_id")
            or provenance_binding.get("dialogue_relation_id")
            or ""
        )
        expected_actor = str(provenance_binding.get("learning_actor", ""))
        expected_speaker = str(provenance_binding.get("speaker", ""))
        expected_source = str(provenance_binding.get("source_sha256", "")).upper()
        if not relation_id or not expected_actor or not expected_speaker or len(expected_source) != 64:
            raise ValueError("provenance binding is incomplete")
        with SQLiteNeuronGraphStore(graph_path, readonly=True) as provenance_store:
            relation = provenance_store.load_neuron(relation_id)
        adjacency = _source_relation_metadata(relation)
        provenance_truth = (
            relation.get("kind") == "SENTENCE"
            and relation.get("lifecycle") == "STABLE"
            and str(adjacency.get("source_sha256", "")).upper() == expected_source
            and adjacency.get("truth_authority") is False
            and expected_actor == "VIV"
            and expected_speaker == "VIV"
        )
        provenance_binding_summary = {
            "source_relation_id": relation_id,
            "dialogue_relation_id": (
                relation_id
                if "opaque_dialogue_adjacency_v1" in relation.get("center_attractor", {})
                else None
            ),
            "source_sha256": expected_source,
            "source_class": str(adjacency.get("source_class", "")),
            "source_lines": [int(value) for value in adjacency.get("source_lines", ())],
            "source_title": str(adjacency.get("source_title", "")),
            "scene_id": str(adjacency.get("scene_id", "")),
            "pair_id": str(adjacency.get("pair_id", "")),
            "learning_actor": expected_actor,
            "speaker": expected_speaker,
            "actor_matches_speaker": expected_actor == expected_speaker,
            "source_relation_verified": bool(provenance_truth),
        }
    authorization_required = bool(fact.get("requires_human_authorization", False))
    authorization_summary: dict[str, Any] | None = None
    authorization_receipt_path = getattr(args, "authorization_receipt", None)
    authorization_target_path = getattr(args, "authorization_target", None)
    inference_receipt_path = getattr(args, "inference_receipt", None)
    response_proposal_path = getattr(args, "response_proposal", None)
    if authorization_required:
        if authorization_receipt_path is None or authorization_target_path is None:
            raise ValueError("human-authorized lesson requires authorization receipt and target")
        authorization_receipt_path = Path(authorization_receipt_path).resolve()
        authorization_target_path = Path(authorization_target_path).resolve()
        target_raw = authorization_target_path.read_bytes()
        target_sha256 = hashlib.sha256(target_raw).hexdigest().upper()
        target = json.loads(target_raw.decode("utf-8"))
        receipt = json.loads(Path(authorization_receipt_path).resolve().read_text(encoding="utf-8"))
        parent_hashes = {
            "graph": next(iter(_persistent_sqlite_hashes(graph_path).values())),
            "curriculum": next(iter(_persistent_sqlite_hashes(curriculum_path).values())),
        }
        inference_confirmation = bool(fact.get("requires_inference_confirmation", False))
        response_composition = str(fact.get("authorization_evidence_kind", "")) == "RESPONSE_PROPOSAL"
        if inference_confirmation and response_composition:
            raise ValueError("lesson cannot require both inference consolidation and response composition")
        required_target = {
            "schema": (
                "NN_HUMAN_AUTHORIZED_SOCIAL_CONSOLIDATION_TARGET_V1"
                if inference_confirmation
                else "NN_HUMAN_AUTHORIZED_SOCIAL_RESPONSE_TARGET_V1"
                if response_composition
                else "NN_HUMAN_AUTHORIZED_SOCIAL_LESSON_TARGET_V1"
            ),
            "fact_id": args.fact_id,
            "teacher_sha256": hashlib.sha256(teacher_raw).hexdigest().upper(),
            "parent_graph_sha256": parent_hashes["graph"],
            "parent_curriculum_sha256": parent_hashes["curriculum"],
            "supported_surface": [str(value).lower() for value in fact.get("supported_surface", ())],
            "response_surface": [str(value).lower() for value in fact.get("response_surface", ())],
        }
        if any(target.get(name) != value for name, value in required_target.items()):
            raise ValueError("human-authorized lesson target does not bind current lesson state")
        evidence_field = (
            "inference_receipt_sha256"
            if inference_confirmation
            else "response_proposal_sha256"
            if response_composition
            else "teaching_request_sha256"
        )
        if not isinstance(target.get(evidence_field), str) or len(target[evidence_field]) != 64:
            raise ValueError("human-authorized lesson target lacks evidence binding")
        if inference_confirmation:
            if inference_receipt_path is None:
                raise ValueError("consolidation requires the successful inference receipt")
            inference_path = Path(inference_receipt_path).resolve()
            inference_raw = inference_path.read_bytes()
            if hashlib.sha256(inference_raw).hexdigest().upper() != str(target[evidence_field]).upper():
                raise ValueError("consolidation target does not bind the supplied inference")
            inference = json.loads(inference_raw.decode("utf-8"))
            matching_turns = [
                row for row in inference.get("turns", ())
                if " ".join(str(row.get("input", "")).lower().rstrip("?.!").split())
                == " ".join(required_target["supported_surface"])
            ]
            if len(matching_turns) != 1:
                raise ValueError("consolidation inference does not contain exactly one matching turn")
            inferred_turn = matching_turns[0]
            intent = inferred_turn.get("intent_generalization", {})
            if (
                inferred_turn.get("state") != "PASS_SOCIAL_RESPONSE"
                or str(inferred_turn.get("response", "")).lower().rstrip(".")
                != " ".join(required_target["response_surface"])
                or inferred_turn.get("write_performed") is not False
                or intent.get("exact_surface_stored") is not False
                or intent.get("future_surface_used") is not False
                or str(target.get("intent_concept_id", "")) != str(intent.get("concept_id", ""))
            ):
                raise ValueError("consolidation inference is not an admissible no-write concept result")
        elif response_composition:
            if response_proposal_path is None:
                raise ValueError("response composition requires the CPU-private response proposal")
            proposal_path = Path(response_proposal_path).resolve()
            proposal_raw = proposal_path.read_bytes()
            if hashlib.sha256(proposal_raw).hexdigest().upper() != str(target[evidence_field]).upper():
                raise ValueError("response target does not bind the supplied proposal")
            proposal = json.loads(proposal_raw.decode("utf-8"))
            required_proposal = {
                "schema": "NN_CPU_PRIVATE_SOCIAL_RESPONSE_PROPOSAL_V1",
                "fact_id": args.fact_id,
                "supported_surface": required_target["supported_surface"],
                "response_surface": required_target["response_surface"],
                "auto_apply": False,
            }
            if any(proposal.get(name) != value for name, value in required_proposal.items()):
                raise ValueError("response proposal does not bind the authorized composition")
            if inference_receipt_path is not None:
                raise ValueError("inference receipt supplied for response composition")
        elif inference_receipt_path is not None or response_proposal_path is not None:
            raise ValueError("unsupported evidence supplied for a direct lesson")
        if (
            receipt.get("schema") != "HYDRA_HUMAN_AUTHORIZATION_CONSUMPTION_RECEIPT_V1"
            or receipt.get("state") != "PASS"
            or receipt.get("action") != "ROUTE_COMMIT"
            or str(receipt.get("target_sha256", "")).upper() != target_sha256
            or sorted(str(value) for value in receipt.get("factor_ids", ()))
            != ["architect_pattern", "architect_usb", "architect_voice"]
            or receipt.get("replay_protected") is not True
        ):
            raise ValueError("human authorization receipt does not admit this lesson")
        authorization_summary = {
            "state": "PASS_HYDRA_THREE_FACTOR_LESSON_ADMISSION",
            "target_sha256": target_sha256,
            evidence_field: target[evidence_field],
            "admission_kind": (
                "INFERENCE_CONSOLIDATION"
                if inference_confirmation
                else "RESPONSE_COMPOSITION"
                if response_composition
                else "DIRECT_LESSON"
            ),
            "factor_ids": receipt["factor_ids"],
            "replay_protected": True,
        }
    elif (
        authorization_receipt_path is not None
        or authorization_target_path is not None
        or inference_receipt_path is not None
        or response_proposal_path is not None
    ):
        raise ValueError("authorization material supplied for a lesson that does not require it")
    routing_profile = str(fact.get("routing_profile", "grammar"))
    if routing_profile not in {
        "grammar", "identity", "social_template", "capability_template", "phrase"
    }:
        raise ValueError("unsupported utterance routing profile")
    activated_words = tuple(str(value).lower() for value in fact["activated_words"])
    supported_surface = tuple(str(value).lower() for value in fact["supported_surface"])
    expected_channels = tuple(str(value) for value in fact["grammar_channels"])
    if sorted(activated_words) != sorted(supported_surface):
        raise ValueError("fact surface does not match its activated inventory")
    dictionary_rows = json.loads(dictionary_raw.decode("utf-8"))
    role_support: dict[str, set[str]] = {word: set() for word in activated_words}
    definition_text: dict[str, list[str]] = {word: [] for word in activated_words}
    row_hashes: set[str] = set()
    for row in dictionary_rows:
        word = str(row.get("word", "")).strip().lower()
        if word not in role_support:
            continue
        channel = WEBSTER_OPAQUE_CLASS_MAP.get(str(row.get("pos", "")).strip().lower())
        if channel is not None:
            role_support[word].add(channel)
        definition_text[word].extend(str(value).lower() for value in row.get("definitions", []))
        row_hashes.add(hashlib.sha256(
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest().upper())
    definition_evidence = [str(value) for value in fact.get("definition_row_sha256", ())]
    if any(value not in row_hashes for value in definition_evidence):
        raise ValueError("CPU-private fact references stale Webster definition evidence")
    definition_evidence.extend(external_evidence)
    selection = fact["selectional_support"]
    grounded_response_surface = tuple(
        str(value).lower() for value in fact.get("grounded_response_surface", ())
    )
    context_requirement = fact.get("opaque_context_requirement")
    if context_requirement not in {None, "K0"}:
        raise ValueError("unsupported opaque context requirement")
    if interrogative and not grounded_response_surface and context_requirement is None:
        raise ValueError("question fact requires a CPU-private grounded response surface")
    question_family = fact.get("opaque_question_family", "Q0") if interrogative else None
    if question_family not in {None, "Q0", "Q1", "Q3"}:
        raise ValueError("unsupported opaque question family")
    grounded_response_truth = False
    grounded_response_sentence_id: str | None = None

    def contains_all(word: str, fragments: Sequence[str]) -> bool:
        joined = "\n".join(definition_text[word])
        return all(str(fragment).lower() in joined for fragment in fragments)

    def judge(candidate: Sequence[str]) -> dict[str, Any]:
        words = tuple(str(value).lower().removeprefix("word:") for value in candidate)
        grammar = (
            len(words) == len(expected_channels)
            and all(channel in role_support.get(word, set()) for word, channel in zip(words, expected_channels))
            if routing_profile == "grammar"
            else len(words) == len(supported_surface)
            and (routing_profile == "identity" or words == supported_surface)
        )
        if interrogative:
            if question_family == "Q3":
                meaning = words == supported_surface
            elif question_family == "Q0":
                meaning = (
                    len(words) == 3
                    and contains_all(words[0], selection["interrogative_definition_contains"])
                    and contains_all(words[1], selection["verb_definition_contains"])
                    and contains_all(words[2], selection["subject_definition_contains"])
                )
            else:
                meaning = (
                    len(words) == 3
                    and contains_all(words[0], selection["verb_definition_contains"])
                    and contains_all(words[1], selection["subject_definition_contains"])
                    and contains_all(words[2], selection["object_definition_contains"])
                )
            # A question is not itself labelled true or false.  C2 records
            # whether the CPU can ground its response in an already admitted,
            # trusted SENTENCE neuron.  Exact question ordering remains hidden
            # in this CPU callback and is never uploaded to CUDA.
            truth = (
                words == supported_surface
                and (grounded_response_truth or context_requirement == "K0")
            )
        else:
            meaning = (
                words == supported_surface
                if routing_profile == "phrase"
                else
                len(words) == len(supported_surface)
                and words == supported_surface
                and (
                    "social_definition_contains" not in selection
                    or len(words) == 1
                    and contains_all(words[0], selection["social_definition_contains"])
                )
                if social
                else len(words) == 3
                and contains_all(words[0], selection["subject_definition_contains"])
                and contains_all(words[1], selection["verb_definition_contains"])
                and contains_all(words[2], selection["object_definition_contains"])
            )
            truth = words == supported_surface and provenance_truth
        return {"grammar": bool(grammar), "meaning": bool(meaning), "truth": bool(truth)}

    before = {
        "graph": _persistent_sqlite_hashes(graph_path),
        "curriculum": _persistent_sqlite_hashes(curriculum_path),
    }
    trace_path = args.trace.resolve()
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    if trace_path.exists():
        raise FileExistsError("sentence trace is append-only; choose a fresh path")
    with SQLiteNeuronGraphStore(graph_path) as store:
        with CurriculumStore(curriculum_path) as curriculum:
            manifest = store.manifest()
            missing = sorted(word for word in activated_words if word not in manifest["word_index"])
            if missing:
                raise ValueError(f"activated sentence words are not admitted: {missing}")
            word_ids = [str(manifest["word_index"][word]) for word in activated_words]
            for word, word_id in zip(activated_words, word_ids):
                neuron = store.load_neuron(word_id)
                center = neuron.get("center_attractor", {})
                if routing_profile == "grammar" and UniversalCurriculumEngine.WORD_CLASS_PROFILE_KEY not in center:
                    raise ValueError(f"word has not learned its opaque grammatical classes: {word}")
                if routing_profile == "identity":
                    profile = center.get(UniversalCurriculumEngine.WORD_IDENTITY_PROFILE_KEY, {})
                    channels = {str(item.get("channel")): item for item in profile.get("channels", ())}
                    required_identity_channel = str(fact.get("identity_channel", ""))
                    if required_identity_channel not in channels or int(channels[required_identity_channel].get("pass_hits", 0)) < 1:
                        raise ValueError(f"word has not learned its required opaque identity channel: {word}")
            composition_unit_ids: list[str] = []
            if composition_unit_surfaces:
                flattened = tuple(word for unit in composition_unit_surfaces for word in unit)
                if Counter(flattened) != Counter(activated_words):
                    raise ValueError("recursive composition units do not cover the activated word inventory")
                for surface in composition_unit_surfaces:
                    expected_ids = tuple(str(manifest["word_index"].get(word, "")) for word in surface)
                    if any(not value for value in expected_ids):
                        raise ValueError("recursive composition unit contains an unadmitted word")
                    matches: list[str] = []
                    for neuron_id, summary in manifest.get("neuron_index", {}).items():
                        if summary.get("kind") != "SENTENCE" or summary.get("lifecycle") != "STABLE":
                            continue
                        candidate = store.load_neuron(str(neuron_id))
                        center = candidate.get("center_attractor", {})
                        if (
                            center.get("trusted_language_memory") is True
                            and tuple(str(value) for value in center.get("construction", ())) == expected_ids
                        ):
                            matches.append(str(neuron_id))
                    if len(matches) != 1:
                        raise ValueError(
                            "recursive composition requires exactly one admitted phrase neuron for "
                            + " ".join(surface)
                        )
                    composition_unit_ids.append(matches[0])
            if interrogative and grounded_response_surface:
                expected_response_ids = tuple(
                    str(manifest["word_index"].get(word, ""))
                    for word in grounded_response_surface
                )
                if any(not value for value in expected_response_ids):
                    raise ValueError("grounded response contains an unadmitted word")
                for neuron_id, summary in manifest.get("neuron_index", {}).items():
                    if summary.get("kind") != "SENTENCE":
                        continue
                    candidate_sentence = store.load_neuron(str(neuron_id))
                    center = candidate_sentence.get("center_attractor", {})
                    if (
                        candidate_sentence.get("lifecycle") == "STABLE"
                        and center.get("trusted_language_memory") is True
                        and tuple(str(value) for value in center.get("construction", ()))
                        == expected_response_ids
                    ):
                        grounded_response_truth = True
                        grounded_response_sentence_id = str(neuron_id)
                        break
                if not grounded_response_truth:
                    raise ValueError("question has no admitted trusted grounded response sentence")
            inventory_context = Neuronizer._inventory_signature(word_ids)
            # Assembly consequence belongs to both the unordered inventory
            # and the opaque language mode. Declarative and interrogative
            # routes can use the same words in different valid orders; they
            # must not poison one another's Hydra policy bucket.
            route_evidence_context = (
                hashlib.sha256(
                    (inventory_context + "\0U1\0" + str(question_family)).encode("utf-8")
                ).hexdigest().upper()
                if interrogative
                else inventory_context
            )
            hydra_membrane = (
                HydraRouteMembrane(curriculum, hydra_bin, hydra_trace, evidence_level="SENTENCE")
                if hydra_bin is not None and hydra_trace is not None
                else None
            )
            engine = Neuronizer(store, CudaLibrary(), route_truth_provider=hydra_membrane)
            source_handle = hashlib.sha256(
                json.dumps(fact, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest().upper()
            # Provenance has two different jobs here and must not collapse
            # them.  The lesson receipt says where this neuron was learned;
            # an optional reference says what external material the learned
            # language is talking about.  For example, the phrase "from the
            # ex machina script" is taught by this bounded CPU lesson while
            # referring to the admitted Ex Machina dialogue relation.  It is
            # not falsely represented as a verbatim line from that script.
            source_provenance_payload = {
                "schema": "NN_COMPOSABLE_SOURCE_PROVENANCE_V1",
                "learned_from_v1": {
                    "teacher_schema": teacher_schema,
                    "teacher_fact_id": str(args.fact_id),
                    "teacher_fact_sha256": source_handle,
                    "teacher_document_sha256": hashlib.sha256(teacher_raw).hexdigest().upper(),
                    "dictionary_sha256": dictionary_sha256,
                    "evidence_source_sha256": list(external_evidence),
                },
                "references_v1": (
                    [deepcopy(provenance_binding_summary)]
                    if provenance_binding_summary is not None
                    else []
                ),
            }
            result = engine.learn_generated_sentence_episode(
                [f"WORD:{word}" for word in activated_words],
                judge,
                seed=args.seed,
                source_handle=source_handle,
                definition_evidence_sha256=definition_evidence,
                max_attempts=args.max_attempts,
                required_confirmations=args.confirmations,
                trace_path=trace_path,
                route_truth_context=route_evidence_context,
                route_truth_evidence_writer=(
                    lambda route, passed: curriculum.apply_assembly_verdict(
                        level="SENTENCE",
                        inventory_context_sha256=route_evidence_context,
                        route=route,
                        passed=passed,
                    )
                ) if hydra_membrane is not None else None,
                # The CPU supplies only the opaque grammatical demand at each
                # split.  It never supplies a target word or correction; each
                # WORD neuron's learned R* metadata determines its attraction
                # to this anchor inside the GPU route field.
                activation_anchors=(
                    tuple({"grammar": channel} for channel in expected_channels)
                    if routing_profile == "grammar" and not composition_unit_ids
                    else tuple({"identity": str(fact["identity_channel"])} for _ in activated_words)
                    if routing_profile == "identity" and not composition_unit_ids
                    else None
                ),
                utterance_mode=(
                    "U1" if interrogative else "U2" if social else "U3" if phrase else "U0"
                ),
                context_requirement=context_requirement,
                question_family=question_family,
                composition_unit_ids=composition_unit_ids or None,
                source_provenance=source_provenance_payload,
            )
            hydra_metrics = (
                hydra_membrane.metrics() if hydra_membrane is not None else {"enabled": False}
            )
        audit = store.audit()
        changed_ids = {
            str(result.get("episode_id", "")),
            str(result.get("sentence_id", "")),
            *word_ids,
            *(str(value) for value in result.get("composition_unit_ids", ())),
        }
        leakage = {
            neuron_id: audit_gpu_payload(store.load_neuron(neuron_id))
            for neuron_id in sorted(changed_ids)
            if neuron_id
        }
    after = {
        "graph": _persistent_sqlite_hashes(graph_path),
        "curriculum": _persistent_sqlite_hashes(curriculum_path),
    }
    report = {
        "schema": "NN_SELF_GENERATED_UTTERANCE_REPORT_V1",
        "state": "PASS"
        if result.get("state") == "PASS"
        and audit["state"] == "PASS"
        and all(item["state"] == "PASS" for item in leakage.values())
        else "HOLD",
        "fact_source_sha256": hashlib.sha256(teacher_path.read_bytes()).hexdigest().upper(),
        "dictionary_source_sha256": dictionary_sha256,
        "activated_word_count": len(activated_words),
        "utterance_kind": (
            "INTERROGATIVE" if interrogative else "SOCIAL" if social else "PHRASE" if phrase else "DECLARATIVE"
        ),
        "cpu_gates": (
            ["QUESTION_GRAMMAR", "QUESTION_MEANING", "GROUNDED_RESPONSE_TRUTH"]
            if interrogative else ["GRAMMAR", "MEANING", "TRUTH"]
        ),
        "grounded_response_sentence_id": grounded_response_sentence_id,
        "opaque_context_requirement": context_requirement,
        "opaque_question_family": question_family,
        "route_evidence_namespaced": bool(interrogative),
        "routing_profile": routing_profile,
        "composition_unit_surfaces": [list(unit) for unit in composition_unit_surfaces],
        "social_act": fact.get("social_act") if social else None,
        "social_response_surface": fact.get("response_surface") if social else None,
        "social_runtime_predicate": fact.get("runtime_predicate") if social else None,
        "human_authorization": authorization_summary,
        "provenance_actor_binding": provenance_binding_summary,
        "hydra_route_membrane": hydra_metrics,
        "result": result,
        "graph_audit": audit,
        "leakage_audit": leakage,
        "persistent_hashes_before": before,
        "persistent_hashes_after": after,
        "canonical_mutation_authorized": False,
        "promotion_performed": False,
        "deployment_performed": False,
    }
    output = json.dumps(report, ensure_ascii=False, indent=2)
    report_path = args.report.resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if report["state"] == "PASS" else 2


def _dialogue_sentence_id(engine: Neuronizer, store: Any, words: Sequence[str]) -> str:
    states = [f"WORD:{str(word).lower()}" for word in words]
    for row in engine.rank_admitted_sentence_experts(states):
        sentence_id = str(row["sentence_id"])
        sentence = store.load_neuron(sentence_id)
        rendered = tuple(
            str(store.load_neuron(str(child))["center_attractor"].get("learned_surface", ""))
            for child in sentence["center_attractor"].get("construction", ())
        )
        if rendered == tuple(str(word).lower() for word in words):
            return sentence_id
    raise ValueError(f"no exact admitted sentence for dialogue utterance: {' '.join(words)}")


def command_learn_dialogue_scene(args: argparse.Namespace) -> int:
    """Teach exact source-bound turn adjacency without granting fiction truth authority."""

    from .steel_brain_store import SQLiteNeuronGraphStore

    graph_path = args.graph.resolve()
    curriculum_path = args.curriculum_db.resolve()
    scene_path = args.scene.resolve()
    raw = scene_path.read_bytes()
    scene = json.loads(raw.decode("utf-8"))
    source_path = Path(str(scene["source_path"])).resolve()
    source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest().upper()
    if source_sha256 != str(scene["source_sha256"]).upper():
        raise ValueError("dialogue scene source is missing or stale")
    if str(scene.get("source_class")) != "FICTION_DIALOGUE":
        raise ValueError("script teacher must remain FICTION_DIALOGUE")
    before_curriculum = _persistent_sqlite_hashes(curriculum_path)
    results: list[dict[str, Any]] = []
    with SQLiteNeuronGraphStore(graph_path) as store:
        engine = Neuronizer(store, CudaLibrary())
        for index, pair in enumerate(scene.get("pairs", ())):
            pair_id = str(pair["pair_id"])
            prompt_words = tuple(str(word).lower() for word in pair["prompt_words"])
            response_words = tuple(str(word).lower() for word in pair["response_words"])
            prompt_sentence_id = _dialogue_sentence_id(engine, store, prompt_words)
            response_sentence_id = _dialogue_sentence_id(engine, store, response_words)
            prompt_state = f"DIALOGUE_UTTERANCE:{source_sha256}:{scene['scene_id']}:{pair_id}:PROMPT"
            response_state = f"DIALOGUE_UTTERANCE:{source_sha256}:{scene['scene_id']}:{pair_id}:RESPONSE"
            engine.ensure_dialogue_utterance_state(
                prompt_sentence_id,
                visible_state_id=prompt_state,
                source_sha256=source_sha256,
                source_class="FICTION_DIALOGUE",
                scene_id=str(scene["scene_id"]),
                speaker=str(pair["prompt_speaker"]),
                source_line=int(pair["prompt_line"]),
            )
            engine.ensure_dialogue_utterance_state(
                response_sentence_id,
                visible_state_id=response_state,
                source_sha256=source_sha256,
                source_class="FICTION_DIALOGUE",
                scene_id=str(scene["scene_id"]),
                speaker=str(pair["response_speaker"]),
                source_line=int(pair["response_line"]),
            )
            result = engine.learn_state_episode(
                [prompt_state, response_state],
                lambda route, expected=(prompt_state, response_state): tuple(route) == expected,
                seed=int(args.seed) + index * 10_000_019,
                max_attempts=int(args.max_attempts),
                required_confirmations=int(args.confirmations),
                source_handle=f"FICTION_DIALOGUE:{source_sha256}:{scene['scene_id']}:{pair_id}",
                trace_path=args.trace.resolve(),
                cpu_guided=True,
            )
            if result.get("state") == "PASS":
                relation = store.load_neuron(str(result["sentence_id"]))
                episode = store.load_neuron(str(result["episode_id"]))
                metadata = {
                    "schema": "NN_SOURCE_BOUND_DIALOGUE_ADJACENCY_V1",
                    "source_sha256": source_sha256,
                    "source_class": "FICTION_DIALOGUE",
                    "truth_authority": False,
                    "identity_authority": False,
                    "stage_directions_spoken": False,
                    "scene_id": str(scene["scene_id"]),
                    "pair_id": pair_id,
                    "prompt_surface": " ".join(prompt_words),
                    "response_surface": " ".join(response_words),
                    "prompt_state_id": prompt_state,
                    "response_state_id": response_state,
                    "prompt_sentence_id": prompt_sentence_id,
                    "response_sentence_id": response_sentence_id,
                    "source_lines": [int(pair["prompt_line"]), int(pair["response_line"])],
                }
                relation["center_attractor"]["opaque_dialogue_adjacency_v1"] = metadata
                episode["center_attractor"]["opaque_dialogue_adjacency_v1"] = metadata
                store.transact(
                    [episode, relation],
                    event_kind="DIALOGUE_ADJACENCY_STABILIZED",
                    details={
                        "relation_id": relation["neuron_id"],
                        "episode_id": episode["neuron_id"],
                        "source_sha256": source_sha256,
                        "scene_id": str(scene["scene_id"]),
                        "pair_id": pair_id,
                        "truth_authority": False,
                    },
                )
            results.append({"pair_id": pair_id, **result})
        audit = store.audit()
    report = {
        "schema": "NN_DIALOGUE_SCENE_LEARNING_REPORT_V1",
        "state": "PASS" if results and all(row.get("state") == "PASS" for row in results) else "HOLD",
        "source_path": str(source_path),
        "source_sha256": source_sha256,
        "source_class": "FICTION_DIALOGUE",
        "scene_id": str(scene["scene_id"]),
        "pairs": results,
        "audit": audit,
        "curriculum_unchanged": before_curriculum == _persistent_sqlite_hashes(curriculum_path),
    }
    args.report.resolve().write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["state"] == "PASS" and report["curriculum_unchanged"] else 2


def command_run_dialogue_scene(args: argparse.Namespace) -> int:
    """Fresh read-only recall of exact learned script exchanges; unsupported prompts HOLD."""

    from .steel_brain_store import SQLiteNeuronGraphStore

    graph_path = args.graph.resolve()
    curriculum_path = args.curriculum_db.resolve()
    before = {
        "graph": _persistent_sqlite_hashes(graph_path),
        "curriculum": _persistent_sqlite_hashes(curriculum_path),
    }
    requested = [" ".join(re.findall(r"[a-z]+", item.lower())) for item in args.turns.split("|")]
    rows: list[dict[str, Any]] = []
    with SQLiteNeuronGraphStore(graph_path, readonly=True) as store:
        engine = Neuronizer(store, CudaLibrary())
        learned: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        for neuron_id, summary in store.manifest().get("neuron_index", {}).items():
            if summary.get("kind") != "SENTENCE":
                continue
            neuron = store.load_neuron(str(neuron_id))
            metadata = neuron.get("center_attractor", {}).get("opaque_dialogue_adjacency_v1")
            if isinstance(metadata, dict):
                learned.setdefault(str(metadata["prompt_surface"]), []).append((str(neuron_id), metadata))
        for turn_index, prompt in enumerate(requested):
            matches = learned.get(prompt, [])
            if not matches:
                rows.append({"turn": turn_index + 1, "input": prompt, "state": "HOLD", "reason": "HOLD_DIALOGUE_TEACHING_REQUIRED"})
                continue
            responses = {str(metadata["response_surface"]) for _, metadata in matches}
            if len(responses) != 1:
                rows.append({"turn": turn_index + 1, "input": prompt, "state": "HOLD", "reason": "HOLD_DIALOGUE_CONTEXT_AMBIGUOUS"})
                continue
            relation_id, metadata = sorted(matches, key=lambda item: item[0])[0]
            seeds = tuple(int(args.seed) + (index + 1) * 1_000_003 for index in range(int(args.confirmations)))
            counts = engine.sample_admitted_sentence_distribution(
                [str(metadata["prompt_state_id"]), str(metadata["response_state_id"])],
                seeds=seeds,
                sentence_id=relation_id,
            )
            expected_route = f"{metadata['prompt_state_id']} {metadata['response_state_id']}"
            passed = counts == {expected_route: len(seeds)}
            rows.append({
                "turn": turn_index + 1,
                "input": prompt,
                "state": "PASS_DIALOGUE_RESPONSE" if passed else "HOLD",
                "reason": None if passed else "HOLD_DIALOGUE_ROUTE_UNSTABLE",
                "response": str(metadata["response_surface"]) if passed else None,
                "relation_id": relation_id,
                "source_sha256": str(metadata["source_sha256"]),
                "source_class": str(metadata["source_class"]),
                "frozen_counts": counts,
            })
        audit = store.audit()
    after = {
        "graph": _persistent_sqlite_hashes(graph_path),
        "curriculum": _persistent_sqlite_hashes(curriculum_path),
    }
    report = {
        "schema": "NN_DIALOGUE_SCENE_RECALL_REPORT_V1",
        "state": "PASS",
        "turns": rows,
        "persistent_state_unchanged": before == after,
        "audit": audit,
    }
    args.output.resolve().write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["persistent_state_unchanged"] else 2


def _source_relation_metadata(relation: dict[str, Any]) -> dict[str, Any]:
    """Return one normalized CPU-side source record for stable memory.

    Dialogue adjacency is retained as a compatibility source class. New source
    classes use the source-neutral record and never masquerade as dialogue.
    """

    center = relation.get("center_attractor", {})
    generic = center.get("represented_source_v1")
    if isinstance(generic, dict):
        return generic
    dialogue = center.get("opaque_dialogue_adjacency_v1")
    if isinstance(dialogue, dict):
        return dialogue
    return {}


def command_attach_source_provenance(args: argparse.Namespace) -> int:
    """CPU-admit an authenticated external source onto learned source memory."""

    from .steel_brain_store import SQLiteNeuronGraphStore

    graph_path = args.graph.resolve()
    curriculum_path = args.curriculum_db.resolve()
    source_path = args.source.resolve()
    receipt = json.loads(args.learning_receipt.resolve().read_text(encoding="utf-8"))
    if receipt.get("state") != "PASS":
        raise ValueError("source provenance requires a PASSed learned source phrase")
    relation_id = str(receipt.get("result", {}).get("sentence_id", ""))
    episode_id = str(receipt.get("result", {}).get("episode_id", ""))
    if not relation_id or not episode_id:
        raise ValueError("source phrase receipt lacks sentence and episode IDs")
    source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest().upper()
    before_curriculum = _persistent_sqlite_hashes(curriculum_path)
    with SQLiteNeuronGraphStore(graph_path) as store:
        relation = store.load_neuron(relation_id)
        episode = store.load_neuron(episode_id)
        if relation.get("kind") != "SENTENCE" or relation.get("lifecycle") != "STABLE":
            raise ValueError("source provenance requires stable learned SENTENCE memory")
        metadata = {
            "schema": "NN_SOURCE_PROVENANCE_RELATION_V1",
            "source_sha256": source_sha256,
            "source_class": str(args.source_class),
            "source_title": str(args.source_title),
            "source_path": str(source_path),
            "relation_kind": "LEARNED_SOURCE_PHRASE",
            "truth_authority": False,
            "identity_authority": False,
        }
        existing_records = []
        for neuron in (relation, episode):
            existing = neuron.get("center_attractor", {}).get("represented_source_v1")
            if existing is not None and existing != metadata:
                raise ValueError("source relation already has different provenance")
            existing_records.append(existing)
            neuron["center_attractor"]["represented_source_v1"] = metadata
        already_attached = all(record == metadata for record in existing_records)
        if not already_attached:
            store.transact(
                [relation, episode],
                event_kind="SOURCE_PROVENANCE_RELATION_ATTACHED",
                details={
                    "source_relation_id": relation_id,
                    "source_episode_id": episode_id,
                    "source_sha256": source_sha256,
                    "source_class": str(args.source_class),
                    "source_title": str(args.source_title),
                    "truth_authority": False,
                },
            )
        audit = store.audit()
    report = {
        **metadata,
        "schema": "NN_SOURCE_PROVENANCE_ATTACHMENT_REPORT_V1",
        "state": "PASS",
        "source_relation_id": relation_id,
        "source_episode_id": episode_id,
        "already_attached": already_attached,
        "curriculum_unchanged": before_curriculum == _persistent_sqlite_hashes(curriculum_path),
        "audit": audit,
    }
    args.report.resolve().write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["curriculum_unchanged"] and audit.get("state") == "PASS" else 2


def command_bind_provenance_explanation(args: argparse.Namespace) -> int:
    """Learn relation -> provenance -> explanation navigation from accepted memory."""

    from .steel_brain_store import SQLiteNeuronGraphStore

    graph_path = args.graph.resolve()
    curriculum_path = args.curriculum_db.resolve()
    receipt = json.loads(args.learning_receipt.resolve().read_text(encoding="utf-8"))
    if receipt.get("state") != "PASS":
        raise ValueError("provenance bridge requires a PASSed explanation lesson")
    binding = receipt.get("provenance_actor_binding")
    if not isinstance(binding, dict) or binding.get("source_relation_verified") is not True:
        raise ValueError("explanation lesson lacks verified actor/source binding")
    relation_id = str(
        binding.get("source_relation_id") or binding.get("dialogue_relation_id") or ""
    )
    if not relation_id:
        raise ValueError("explanation lesson lacks a source relation")
    explanation_id = str(receipt["result"]["sentence_id"])
    source_sha256 = str(binding["source_sha256"]).upper()
    actor = str(binding["learning_actor"])
    speaker = str(binding["speaker"])
    before_curriculum = _persistent_sqlite_hashes(curriculum_path)
    with SQLiteNeuronGraphStore(graph_path) as store:
        engine = Neuronizer(store, CudaLibrary())
        relation = store.load_neuron(relation_id)
        adjacency = _source_relation_metadata(relation)
        explanation = store.load_neuron(explanation_id)
        if str(adjacency.get("source_sha256", "")).upper() != source_sha256:
            raise ValueError("source relation changed after explanation learning")
        common = f"{source_sha256}:{relation_id}"
        subject_state = f"PROVENANCE_SUBJECT:{common}"
        provenance_state = f"PROVENANCE_RECORD:{common}"
        explanation_state = f"PROVENANCE_EXPLANATION:{common}:{explanation_id}"
        subject_concept_id = engine.ensure_metadata_state(
            relation_id,
            visible_state_id=subject_state,
            state_kind="SOURCE_RELATION_SUBJECT",
            payload={"source_relation_id": relation_id, "actor": actor},
        )
        provenance_concept_id = engine.ensure_metadata_state(
            relation_id,
            visible_state_id=provenance_state,
            state_kind="LEARNING_PROVENANCE_RECORD",
            payload={
                "source_relation_id": relation_id,
                "source_sha256": source_sha256,
                "source_class": str(adjacency.get("source_class")),
                "source_lines": list(adjacency.get("source_lines", ())),
                "learning_actor": actor,
                "speaker": speaker,
                "truth_authority": False,
                "identity_authority": False,
            },
        )
        explanation_concept_id = engine.ensure_metadata_state(
            explanation_id,
            visible_state_id=explanation_state,
            state_kind="LEARNED_PROVENANCE_EXPLANATION",
            payload={
                "explanation_sentence_id": explanation_id,
                "source_relation_id": relation_id,
                "source_sha256": source_sha256,
                "learning_actor": actor,
            },
        )
        expected = (subject_state, provenance_state, explanation_state)
        result = engine.learn_state_episode(
            expected,
            lambda route: tuple(route) == expected,
            seed=int(args.seed),
            max_attempts=int(args.max_attempts),
            required_confirmations=int(args.confirmations),
            source_handle=f"PROVENANCE_NAVIGATION:{source_sha256}:{relation_id}",
            trace_path=args.trace.resolve(),
            cpu_guided=True,
        )
        if result.get("state") == "PASS":
            bridge = store.load_neuron(str(result["sentence_id"]))
            episode = store.load_neuron(str(result["episode_id"]))
            relation = store.load_neuron(relation_id)
            explanation = store.load_neuron(explanation_id)
            provenance = store.load_neuron(provenance_concept_id)
            navigation = {
                "schema": "NN_BIDIRECTIONAL_PROVENANCE_NAVIGATION_V2",
                "source_relation_id": relation_id,
                "dialogue_relation_id": relation_id if "opaque_dialogue_adjacency_v1" in relation.get("center_attractor", {}) else None,
                "explanation_sentence_id": explanation_id,
                "bridge_sentence_id": str(result["sentence_id"]),
                "bridge_episode_id": str(result["episode_id"]),
                "subject_state_id": subject_state,
                "provenance_state_id": provenance_state,
                "explanation_state_id": explanation_state,
                "subject_concept_id": subject_concept_id,
                "provenance_concept_id": provenance_concept_id,
                "explanation_concept_id": explanation_concept_id,
                "source_sha256": source_sha256,
                "source_class": str(adjacency.get("source_class")),
                "learning_actor": actor,
                "speaker": speaker,
                "actor_matches_speaker": actor == speaker,
                "truth_authority": False,
                "identity_authority": False,
                "bidirectional": True,
            }
            for neuron in (relation, explanation, provenance, bridge, episode):
                neuron["center_attractor"]["provenance_navigation_v1"] = navigation
            store.transact(
                [relation, explanation, provenance, bridge, episode],
                event_kind="PROVENANCE_EXPLANATION_NAVIGATION_STABILIZED",
                details={
                    "source_relation_id": relation_id,
                    "explanation_sentence_id": explanation_id,
                    "bridge_sentence_id": str(result["sentence_id"]),
                    "source_sha256": source_sha256,
                    "learning_actor": actor,
                    "speaker": speaker,
                    "bidirectional": True,
                },
            )
        audit = store.audit()
    report = {
        "schema": "NN_PROVENANCE_EXPLANATION_BINDING_REPORT_V1",
        "state": result.get("state"),
        "result": result,
        "source_relation_id": relation_id,
        "dialogue_relation_id": relation_id if "opaque_dialogue_adjacency_v1" in relation.get("center_attractor", {}) else None,
        "explanation_sentence_id": explanation_id,
        "source_sha256": source_sha256,
        "learning_actor": actor,
        "speaker": speaker,
        "actor_matches_speaker": actor == speaker,
        "curriculum_unchanged": before_curriculum == _persistent_sqlite_hashes(curriculum_path),
        "audit": audit,
    }
    args.report.resolve().write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["state"] == "PASS" and report["curriculum_unchanged"] else 2


def command_query_provenance_explanation(args: argparse.Namespace) -> int:
    """Cold read-only navigation from a learned relation to Viv's learned explanation."""

    from .steel_brain_store import SQLiteNeuronGraphStore

    graph_path = args.graph.resolve()
    curriculum_path = args.curriculum_db.resolve()
    before = {"graph": _persistent_sqlite_hashes(graph_path), "curriculum": _persistent_sqlite_hashes(curriculum_path)}
    row: dict[str, Any]
    with SQLiteNeuronGraphStore(graph_path, readonly=True) as store:
        try:
            relation_id = args.source_relation_id or args.dialogue_relation_id
            if not relation_id:
                raise KeyError("missing source relation")
            relation = store.load_neuron(relation_id)
        except KeyError:
            relation = None
        navigation = None if relation is None else relation.get("center_attractor", {}).get("provenance_navigation_v1")
        if not isinstance(navigation, dict):
            row = {"state": "HOLD", "reason": "HOLD_PROVENANCE_NOT_LEARNED"}
        elif str(args.speaker).upper() != str(navigation.get("learning_actor", "")).upper():
            row = {"state": "HOLD", "reason": "HOLD_PROVENANCE_ACTOR_MISMATCH"}
        elif args.source_sha256 and str(args.source_sha256).upper() != str(navigation.get("source_sha256", "")).upper():
            row = {"state": "HOLD", "reason": "HOLD_PROVENANCE_SOURCE_MISMATCH"}
        else:
            engine = Neuronizer(store, CudaLibrary())
            states = [str(navigation[key]) for key in ("subject_state_id", "provenance_state_id", "explanation_state_id")]
            seeds = tuple(int(args.seed) + (index + 1) * 1_000_003 for index in range(int(args.confirmations)))
            counts = engine.sample_admitted_sentence_distribution(
                states,
                seeds=seeds,
                sentence_id=str(navigation["bridge_sentence_id"]),
            )
            expected = " ".join(states)
            explanation = store.load_neuron(str(navigation["explanation_sentence_id"]))
            words = [str(store.load_neuron(str(child))["center_attractor"].get("learned_surface", "")) for child in explanation["center_attractor"]["construction"]]
            passed = counts == {expected: len(seeds)}
            row = {
                "state": "PASS_PROVENANCE_EXPLANATION" if passed else "HOLD",
                "reason": None if passed else "HOLD_PROVENANCE_ROUTE_UNSTABLE",
                "response": " ".join(words) if passed else None,
                "source_sha256": navigation["source_sha256"],
                "source_class": navigation["source_class"],
                "learning_actor": navigation["learning_actor"],
                "frozen_counts": counts,
            }
        audit = store.audit()
    after = {"graph": _persistent_sqlite_hashes(graph_path), "curriculum": _persistent_sqlite_hashes(curriculum_path)}
    report = {"schema": "NN_PROVENANCE_EXPLANATION_QUERY_V1", **row, "persistent_state_unchanged": before == after, "audit": audit}
    args.output.resolve().write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["persistent_state_unchanged"] else 2


def command_create_human_review_request(args: argparse.Namespace) -> int:
    """Render one learned, source-grounded request while holding neuron birth."""

    from .steel_brain_store import SQLiteNeuronGraphStore

    output_path = args.output.resolve()
    if output_path.exists():
        raise FileExistsError("human review request evidence is append-only")
    graph_path = args.graph.resolve()
    curriculum_path = args.curriculum_db.resolve()
    dictionary_path = args.dictionary.resolve()
    unknown = str(args.unknown_surface).strip().lower()
    if not unknown.isascii() or not unknown.isalpha():
        raise ValueError("bounded review item must be one ASCII alphabetic surface")
    dictionary_rows = json.loads(dictionary_path.read_text(encoding="utf-8"))
    dictionary_words = {
        part.strip().lower()
        for row in dictionary_rows
        for part in str(row.get("word", "")).split(";")
        if part.strip()
    }
    provenance_query = json.loads(args.provenance_query.resolve().read_text(encoding="utf-8"))
    help_receipt = json.loads(args.help_learning_receipt.resolve().read_text(encoding="utf-8"))
    before = {
        "graph": _persistent_sqlite_hashes(graph_path),
        "curriculum": _persistent_sqlite_hashes(curriculum_path),
    }
    source_occurrences = 0
    with SQLiteNeuronGraphStore(graph_path, readonly=True) as store:
        manifest = store.manifest()
        relation = store.load_neuron(str(args.source_relation_id))
        source = _source_relation_metadata(relation)
        source_path = Path(str(source.get("source_path", ""))).resolve()
        source_sha256 = str(source.get("source_sha256", "")).upper()
        if not source_path.is_file() or hashlib.sha256(source_path.read_bytes()).hexdigest().upper() != source_sha256:
            raise ValueError("represented source is missing or stale")
        if source_path.suffix.lower() == ".epub":
            with zipfile.ZipFile(source_path) as archive:
                source_text = "\n".join(
                    archive.read(name).decode("utf-8", errors="ignore")
                    for name in archive.namelist()
                    if name.lower().endswith((".html", ".htm", ".xhtml", ".txt"))
                )
        else:
            source_text = source_path.read_text(encoding="utf-8", errors="ignore")
        source_occurrences = len(re.findall(rf"\b{re.escape(unknown)}\b", source_text, re.IGNORECASE))
        known_id = manifest.get("word_index", {}).get(unknown)
        valid_provenance = (
            provenance_query.get("state") == "PASS_PROVENANCE_EXPLANATION"
            and provenance_query.get("persistent_state_unchanged") is True
            and str(provenance_query.get("source_sha256", "")).upper() == source_sha256
        )
        if help_receipt.get("state") != "PASS":
            raise ValueError("review request requires a PASSed learned help sentence")
        help_sentence_id = str(help_receipt.get("result", {}).get("sentence_id", ""))
        help_sentence = store.load_neuron(help_sentence_id)
        help_words = tuple(
            str(store.load_neuron(str(child))["center_attractor"].get("learned_surface", ""))
            for child in help_sentence.get("center_attractor", {}).get("construction", ())
        )
        seeds = tuple(int(args.seed) + (index + 1) * 1_000_003 for index in range(int(args.confirmations)))
        counts = Neuronizer(store, CudaLibrary()).sample_admitted_sentence_distribution(
            [f"WORD:{word}" for word in help_words], seeds=seeds, sentence_id=help_sentence_id,
        )
        help_recalled = counts == {" ".join(f"WORD:{word}" for word in help_words): len(seeds)}
        audit = store.audit()
    after = {
        "graph": _persistent_sqlite_hashes(graph_path),
        "curriculum": _persistent_sqlite_hashes(curriculum_path),
    }
    if unknown in dictionary_words or known_id is not None:
        state, reason = "HOLD", "HOLD_REVIEW_ITEM_ALREADY_KNOWN"
    elif source_occurrences < 1:
        state, reason = "HOLD", "HOLD_SOURCE_DOES_NOT_SUPPORT_REVIEW_ITEM"
    elif not valid_provenance:
        state, reason = "HOLD", "HOLD_SOURCE_EXPLANATION_UNVERIFIED"
    elif not help_recalled or help_words != ("can", "you", "help", "me"):
        state, reason = "HOLD", "HOLD_HELP_ROUTE_UNSTABLE"
    else:
        state, reason = "HOLD_HUMAN_REVIEW", "CPU_DICTIONARY_DOES_NOT_KNOW_SOURCE_ITEM"
    response = None
    if state == "HOLD_HUMAN_REVIEW":
        response = f"{str(provenance_query['response']).strip()}. {' '.join(help_words)}?"
    report = {
        "schema": "NN_CONVERSATIONAL_SOURCE_REVIEW_REQUEST_V1",
        "state": state,
        "reason": reason,
        "response": response,
        "response_assembly": {
            "provenance_sentence": provenance_query.get("response"),
            "provenance_source_receipt": str(args.provenance_query.resolve()),
            "help_sentence": " ".join(help_words),
            "help_sentence_id": help_sentence_id,
            "help_frozen_counts": counts,
            "cpu_added_words": [],
        },
        "review_item": {
            "surface": unknown,
            "cpu_dictionary_state": "UNKNOWN" if unknown not in dictionary_words else "KNOWN",
            "word_neuron_id": known_id,
            "neuron_birth_allowed": False,
            "source_relation_id": str(args.source_relation_id),
            "source_sha256": source_sha256,
            "source_class": source.get("source_class"),
            "source_title": source.get("source_title"),
            "source_occurrences": source_occurrences,
        },
        "allowed_decisions": ["APPROVE", "REJECT"],
        "auto_apply": False,
        "candidate_only": True,
        "persistent_state_unchanged": before == after,
        "persistent_hashes_before": before,
        "persistent_hashes_after": after,
        "audit": audit,
        "promotion_performed": False,
        "deployment_performed": False,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    accepted_hold = state == "HOLD_HUMAN_REVIEW" and report["persistent_state_unchanged"]
    return 0 if accepted_hold else 2


def _confirm_reviewed_source_word_provenance(
    word: dict[str, Any],
    *,
    surface: str,
    relation_id: str,
    source_sha256: str,
    request_sha256: str,
    decision_sha256: str,
    authorization_sha256: str,
    occurrences: int,
) -> dict[str, Any]:
    """Deterministically verify source admission separately from spelling."""

    center = word.get("center_attractor", {})
    claims = center.get("claim_provenance_v1", [])
    matching = [
        claim for claim in claims
        if isinstance(claim, dict)
        and claim.get("claim_kind") == "SOURCE_ATTESTED_LEXICAL_SURFACE"
        and str(claim.get("surface", "")).lower() == surface
    ] if isinstance(claims, list) else []
    claim = matching[-1] if len(matching) == 1 else {}
    review = center.get("human_review_v1", {})
    checks = {
        "stable_word": word.get("kind") == "WORD" and word.get("lifecycle") == "STABLE",
        "surface_bound": str(center.get("learned_surface", "")).lower() == surface,
        "trusted_language_memory": center.get("trusted_language_memory") is True,
        "exactly_one_source_claim": len(matching) == 1,
        "source_relation_bound": str(claim.get("source_relation_id", "")) == relation_id,
        "source_hash_bound": str(claim.get("source_sha256", "")).upper() == source_sha256,
        "source_occurrences_bound": int(claim.get("source_occurrences", -1)) == int(occurrences),
        "request_bound": str(claim.get("review_request_sha256", "")).upper() == request_sha256,
        "decision_bound": str(claim.get("review_decision_sha256", "")).upper() == decision_sha256,
        "authorization_bound": str(claim.get("authorization_receipt_sha256", "")).upper() == authorization_sha256,
        "lexical_not_world_truth": (
            claim.get("cpu_reference_state") == "SOURCE_ATTESTED_NOT_WORLD_TRUTH"
            and claim.get("truth_authority") is False
            and claim.get("identity_authority") is False
        ),
        "review_derivation_bound": (
            isinstance(review, dict)
            and review.get("derivation") == "SOURCE_ATTESTED_PROPER_NOUN"
            and str(review.get("review_request_sha256", "")).upper() == request_sha256
            and str(review.get("review_decision_sha256", "")).upper() == decision_sha256
            and str(review.get("authorization_receipt_sha256", "")).upper() == authorization_sha256
        ),
    }
    return {
        "state": "PASS" if all(checks.values()) else "HOLD",
        "reason": "" if all(checks.values()) else "SOURCE_WORD_PROVENANCE_CONFIRMATION_FAILED",
        "checks": checks,
        "claim_id": claim.get("claim_id"),
        "confirmation_kind": "DETERMINISTIC_PROVENANCE_BINDING",
        "spelling_confirmation_reused": False,
    }


def command_admit_reviewed_source_word(args: argparse.Namespace) -> int:
    """Hydra-authorize and learn one source-attested lexical surface."""

    from .leakage_audit import audit_gpu_payload
    from .steel_brain_store import SQLiteNeuronGraphStore

    graph_path = args.graph.resolve()
    curriculum_path = args.curriculum_db.resolve()
    request_path = args.review_request.resolve()
    decision_path = args.review_decision.resolve()
    authorization_path = args.authorization_receipt.resolve()
    report_path = args.report.resolve()
    trace_path = args.trace.resolve()
    if report_path.exists() or trace_path.exists():
        raise FileExistsError("review admission evidence is append-only")

    request_raw = request_path.read_bytes()
    decision_raw = decision_path.read_bytes()
    authorization_raw = authorization_path.read_bytes()
    request = json.loads(request_raw.decode("utf-8"))
    decision = json.loads(decision_raw.decode("utf-8"))
    authorization = json.loads(authorization_raw.decode("utf-8"))
    request_sha256 = hashlib.sha256(request_raw).hexdigest().upper()
    decision_sha256 = hashlib.sha256(decision_raw).hexdigest().upper()
    authorization_sha256 = hashlib.sha256(authorization_raw).hexdigest().upper()
    item = request.get("review_item", {})
    approved = decision.get("review_item", {})
    surface = str(item.get("surface", "")).strip().lower()
    relation_id = str(item.get("source_relation_id", ""))
    source_sha256 = str(item.get("source_sha256", "")).upper()

    request_valid = (
        request.get("schema") == "NN_CONVERSATIONAL_SOURCE_REVIEW_REQUEST_V1"
        and request.get("state") == "HOLD_HUMAN_REVIEW"
        and request.get("reason") == "CPU_DICTIONARY_DOES_NOT_KNOW_SOURCE_ITEM"
        and request.get("candidate_only") is True
        and request.get("auto_apply") is False
        and request.get("persistent_state_unchanged") is True
        and surface.isascii() and surface.isalpha()
        and bool(relation_id) and bool(source_sha256)
        and int(item.get("source_occurrences", 0)) > 0
        and item.get("neuron_birth_allowed") is False
    )
    decision_valid = (
        decision.get("schema") == "NN_CONVERSATIONAL_SOURCE_REVIEW_DECISION_V1"
        and decision.get("state") == "PASS"
        and decision.get("decision") == "APPROVE"
        and decision.get("candidate_only") is True
        and decision.get("canonical_mutation_authorized") is False
        and decision.get("promotion_performed") is False
        and decision.get("deployment_performed") is False
        and str(decision.get("review_request_sha256", "")).upper() == request_sha256
        and str(approved.get("surface", "")).lower() == surface
        and approved.get("derivation") == "SOURCE_ATTESTED_PROPER_NOUN"
        and str(approved.get("source_relation_id", "")) == relation_id
        and str(approved.get("source_sha256", "")).upper() == source_sha256
    )
    factors = {"architect_usb", "architect_voice", "architect_pattern"}
    authorization_valid = (
        authorization.get("schema") == "HYDRA_HUMAN_AUTHORIZATION_CONSUMPTION_RECEIPT_V1"
        and authorization.get("state") == "PASS"
        and authorization.get("action") == "ROUTE_COMMIT"
        and str(authorization.get("target_sha256", "")).upper() == decision_sha256
        and set(authorization.get("factor_ids", ())) == factors
        and authorization.get("replay_protected") is True
    )
    if not request_valid:
        raise ValueError("review request is not one actionable source-grounded HOLD")
    if not decision_valid:
        raise ValueError("human decision does not approve the exact held source item")
    if not authorization_valid:
        raise ValueError("Hydra did not authorize this exact human review decision")

    before = {
        "graph": _persistent_sqlite_hashes(graph_path),
        "curriculum": _persistent_sqlite_hashes(curriculum_path),
    }
    request_parent = {
        group: sorted(values.values())
        for group, values in request.get("persistent_hashes_after", {}).items()
    }
    current_parent = {group: sorted(values.values()) for group, values in before.items()}
    if request_parent != current_parent:
        raise ValueError("review request does not bind the current candidate parent")

    trace_path.parent.mkdir(parents=True, exist_ok=True)
    character_prior = None
    character_prior_sha256 = None
    complete_route_proposal = None
    complete_route_proposal_sha256 = None
    if (args.character_prior_checkpoint is None) != (args.character_prior_vocab is None):
        raise ValueError("character proposal requires both checkpoint and vocabulary")
    if args.character_prior_checkpoint is not None:
        checkpoint_path = args.character_prior_checkpoint.resolve()
        vocab_path = args.character_prior_vocab.resolve()
        checkpoint_raw = checkpoint_path.read_bytes()
        vocab_raw = vocab_path.read_bytes()
        character_prior_sha256 = hashlib.sha256(
            checkpoint_raw + b"\0" + vocab_raw
        ).hexdigest().upper()
        import torch

        checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
        vocab_payload = json.loads(vocab_raw.decode("utf-8"))
        vocab = [str(value) for value in vocab_payload["vocab"]]
        if (
            checkpoint.get("model") != "dense_character_bigram"
            or checkpoint.get("vocab_sha256") != vocab_payload.get("vocab_sha256")
            or int(checkpoint.get("vocab_size", -1)) != len(vocab)
        ):
            raise ValueError("character proposal checkpoint and vocabulary do not match")
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        logits = checkpoint["model_state_dict"]["logits_table"].to(
            device=device, dtype=torch.float64
        )
        log_probabilities = torch.log_softmax(logits, dim=-1)
        stoi = {character: index for index, character in enumerate(vocab)}
        boundary_id = stoi.get(" ", stoi.get("\n"))
        if boundary_id is None:
            raise ValueError("character proposal vocabulary has no boundary token")

        def character_prior(emitted: str, candidates: Sequence[str]) -> list[int]:
            # This closure receives only already-emitted text and currently
            # eligible neuron surfaces. It never receives the ordered lesson.
            context_id = stoi.get(emitted[-1], boundary_id) if emitted else boundary_id
            values = []
            for candidate in candidates:
                ids = [stoi.get(character) for character in candidate]
                if any(value is None for value in ids):
                    values.append(float("-inf"))
                    continue
                transitions = [(context_id, ids[0]), *zip(ids, ids[1:])]
                score = sum(
                    float(log_probabilities[left, right].item())
                    for left, right in transitions
                ) / len(transitions)
                values.append(score)
            finite = [value for value in values if value != float("-inf")]
            if not finite:
                return [1] * len(values)
            peak = max(finite)
            return [
                max(1, min(SCALE, int(round(math.exp(value - peak) * SCALE))))
                if value != float("-inf") else 1
                for value in values
            ]

    if args.route_proposal_transformer_checkpoint is not None:
        checkpoint_path = args.route_proposal_transformer_checkpoint.resolve()
        checkpoint_raw = checkpoint_path.read_bytes()
        complete_route_proposal_sha256 = hashlib.sha256(checkpoint_raw).hexdigest().upper()
        import random
        import torch
        # AUTO: the proposal organ is owned by NN; external UML source is legacy provenance.
        from .transformer import TransformerLanguageModel
        checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
        tokenizer = checkpoint.get("tokenizer", {})
        vocab = [str(value) for value in tokenizer.get("vocab", [])]
        config = checkpoint.get("model_config", {})
        if checkpoint.get("model") != "four_block_four_head_transformer" or not vocab:
            raise ValueError("unsupported complete-route transformer checkpoint")
        model = TransformerLanguageModel(
            len(vocab),
            context_length=int(config["context_length"]),
            embedding_width=int(config["embedding_width"]),
            num_heads=int(config["num_heads"]),
            head_size=int(config["head_size"]),
            num_layers=int(config["num_layers"]),
            dropout=float(config["dropout"]),
        )
        model.load_state_dict(checkpoint["model_state_dict"])
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model.to(device).eval()
        stoi = {character: index for index, character in enumerate(vocab)}
        boundary_id = stoi.get(" ", stoi.get("\n"))
        if boundary_id is None:
            raise ValueError("complete-route transformer vocabulary has no boundary token")
        beam_width = int(args.route_proposal_beam_width)

        def complete_route_proposal(
            inventory: Counter[str],
            proposal_seed: int,
            consequence_packet: Mapping[str, object],
        ) -> dict[str, object]:
            if any(character not in stoi for character in inventory):
                unknown = sorted(character for character in inventory if character not in stoi)
                raise ValueError(f"complete-route transformer lacks inventory characters: {unknown}")
            rng = random.Random(int(proposal_seed))
            beams: list[tuple[str, Counter[str], float]] = [("", Counter(inventory), 0.0)]
            with torch.no_grad():
                while beams and any(remaining for _, remaining, _ in beams):
                    contexts = []
                    for surface_value, _, _ in beams:
                        ids = [boundary_id] + [stoi[ch] for ch in surface_value]
                        contexts.append(ids[-int(config["context_length"]):])
                    input_ids = torch.tensor(contexts, dtype=torch.long, device=device)
                    log_probs = torch.log_softmax(model(input_ids)[:, -1, :], dim=-1).cpu()
                    expanded: list[tuple[str, Counter[str], float]] = []
                    for beam_index, (surface_value, remaining_value, score_value) in enumerate(beams):
                        if not remaining_value:
                            expanded.append((surface_value, remaining_value, score_value))
                            continue
                        for character in sorted(remaining_value):
                            next_remaining = Counter(remaining_value)
                            next_remaining[character] -= 1
                            next_remaining += Counter()
                            # Seeded Gumbel perturbation turns the frozen language
                            # scores into a different bounded whole-route proposal
                            # on each attempt without exposing the ordered lesson.
                            uniform = min(1.0 - 1e-12, max(1e-12, rng.random()))
                            jitter = -math.log(-math.log(uniform))
                            expanded.append((
                                surface_value + character,
                                next_remaining,
                                score_value + float(log_probs[beam_index, stoi[character]]) + jitter,
                            ))
                    expanded.sort(key=lambda row: (row[2], row[0]), reverse=True)
                    beams = expanded[:beam_width]
            if not beams:
                raise RuntimeError("complete-route transformer produced no proposal")
            rejected = {
                str(row.get("output", ""))
                for row in consequence_packet.get("rejected_routes", [])
                if isinstance(row, Mapping)
            }
            selected_beam = next((beam for beam in beams if beam[0] not in rejected), beams[0])
            surface_value, _, score_value = selected_beam
            consequence_sha256 = hashlib.sha256(json.dumps(
                consequence_packet, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")).hexdigest().upper()
            return {
                "surface": surface_value,
                "log_score": score_value,
                "beam_width": beam_width,
                "consequence_sha256": consequence_sha256,
                "rejections_seen": int(consequence_packet.get("rejected_count", len(rejected))),
            }

    with SQLiteNeuronGraphStore(graph_path) as store:
        if store.manifest().get("word_index", {}).get(surface) is not None:
            raise ValueError("reviewed source word is already admitted")
        relation = store.load_neuron(relation_id)
        source = _source_relation_metadata(relation)
        source_path = Path(str(source.get("source_path", ""))).resolve()
        if (
            str(source.get("source_sha256", "")).upper() != source_sha256
            or not source_path.is_file()
            or hashlib.sha256(source_path.read_bytes()).hexdigest().upper() != source_sha256
        ):
            raise ValueError("reviewed source relation is stale or mismatched")
        if source_path.suffix.lower() == ".epub":
            with zipfile.ZipFile(source_path) as archive:
                source_text = "\n".join(
                    archive.read(name).decode("utf-8", errors="ignore")
                    for name in archive.namelist()
                    if name.lower().endswith((".html", ".htm", ".xhtml", ".txt"))
                )
        else:
            source_text = source_path.read_text(encoding="utf-8", errors="ignore")
        occurrences = len(re.findall(rf"\b{re.escape(surface)}\b", source_text, re.IGNORECASE))
        if occurrences != int(item.get("source_occurrences", 0)) or occurrences < 1:
            raise ValueError("reviewed surface is not reproducibly attested by its source")

        with CurriculumStore(curriculum_path) as curriculum:
            engine = UniversalCurriculumEngine(
                store,
                CudaLibrary(),
                curriculum,
                assembly_evidence=True,
                prefix_free_suffix=bool(args.prefix_free_suffix),
                character_prior_provider=character_prior,
                character_prior_sha256=character_prior_sha256,
                complete_route_proposal_provider=complete_route_proposal,
                complete_route_proposal_sha256=complete_route_proposal_sha256,
            )
            with trace_path.open("x", encoding="utf-8", buffering=1) as trace:
                def publish(row: dict[str, object]) -> None:
                    trace.write(json.dumps({
                        **row, "candidate_only": True,
                        "human_review_request_sha256": request_sha256,
                        "human_review_decision_sha256": decision_sha256,
                    }, sort_keys=True) + "\n")
                result = engine.learn_word(
                    surface,
                    lesson_id="HUMAN-REVIEW-" + decision_sha256[:32],
                    source_handle="SOURCE_ATTESTED_PROPER_NOUN:" + source_sha256,
                    seed=int(args.seed), max_attempts=int(args.max_attempts),
                    confirmations=int(args.confirmations), trace_sink=publish,
                )
        if result.get("state") != "PASS":
            raise RuntimeError("authorized reviewed word did not reach PASS")
        word_id = str(store.manifest().get("word_index", {}).get(surface, ""))
        word = store.load_neuron(word_id)
        material = {
            "surface": surface, "source_relation_id": relation_id,
            "source_sha256": source_sha256,
            "review_request_sha256": request_sha256,
            "review_decision_sha256": decision_sha256,
        }
        claim_id = "CLAIM-" + hashlib.sha256(json.dumps(
            material, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest().upper()[:32]
        claim = {
            "schema": "NN_NEURON_CLAIM_PROVENANCE_V1",
            "claim_id": claim_id,
            "claim_kind": "SOURCE_ATTESTED_LEXICAL_SURFACE",
            "learned_state": "LEARNED_HUMAN_AUTHORIZED",
            "cpu_reference_state": "SOURCE_ATTESTED_NOT_WORLD_TRUTH",
            "surface": surface,
            "source_relation_id": relation_id,
            "source_kind": source.get("source_class"),
            "source_title": source.get("source_title"),
            "source_locator": str(source_path),
            "source_sha256": source_sha256,
            "source_occurrences": occurrences,
            "truth_authority": False,
            "identity_authority": False,
            "review_request_sha256": request_sha256,
            "review_decision_sha256": decision_sha256,
            "authorization_receipt_sha256": authorization_sha256,
            "neuron_roles": ["SOURCE_ATTESTED_WORD"],
            "history": [{"revision": 1, "state": "LEARNED_HUMAN_AUTHORIZED"}],
        }
        center = word.setdefault("center_attractor", {})
        claims = center.setdefault("claim_provenance_v1", [])
        if not isinstance(claims, list):
            raise ValueError("reviewed WORD has invalid provenance storage")
        claims.append(claim)
        center["human_review_v1"] = {
            "derivation": "SOURCE_ATTESTED_PROPER_NOUN",
            "review_request_sha256": request_sha256,
            "review_decision_sha256": decision_sha256,
            "authorization_receipt_sha256": authorization_sha256,
        }
        word["updated_utc"] = utc_now()
        word["content_sha256"] = content_hash(word)
        store.transact(
            [word], event_kind="HUMAN_REVIEWED_SOURCE_WORD_PROVENANCE_ATTACHED",
            details={**material, "word_neuron_id": word_id, "claim_id": claim_id,
                     "authorization_receipt_sha256": authorization_sha256},
        )
        provenance_confirmation = _confirm_reviewed_source_word_provenance(
            store.load_neuron(word_id),
            surface=surface, relation_id=relation_id, source_sha256=source_sha256,
            request_sha256=request_sha256, decision_sha256=decision_sha256,
            authorization_sha256=authorization_sha256, occurrences=occurrences,
        )
        audit = store.audit()
        leakage = audit_gpu_payload(store.load_neuron(word_id))

    post_attach = {
        "graph": _persistent_sqlite_hashes(graph_path),
        "curriculum": _persistent_sqlite_hashes(curriculum_path),
    }
    with SQLiteNeuronGraphStore(graph_path) as fresh_store:
        fresh_provenance_confirmation = _confirm_reviewed_source_word_provenance(
            fresh_store.load_neuron(word_id),
            surface=surface, relation_id=relation_id, source_sha256=source_sha256,
            request_sha256=request_sha256, decision_sha256=decision_sha256,
            authorization_sha256=authorization_sha256, occurrences=occurrences,
        )
    after = {
        "graph": _persistent_sqlite_hashes(graph_path),
        "curriculum": _persistent_sqlite_hashes(curriculum_path),
    }
    fresh_provenance_confirmation["persistent_state_unchanged"] = post_attach == after
    report = {
        "schema": "NN_AUTHORIZED_SOURCE_WORD_ADMISSION_V1",
        "state": "PASS" if (
            audit.get("state") == "PASS"
            and leakage.get("state") == "PASS"
            and provenance_confirmation.get("state") == "PASS"
            and fresh_provenance_confirmation.get("state") == "PASS"
            and fresh_provenance_confirmation.get("persistent_state_unchanged") is True
        ) else "HOLD",
        "surface": surface, "word_neuron_id": word_id, "result": result,
        "source_occurrences": occurrences, "claim_id": claim_id,
        "review_request_sha256": request_sha256,
        "review_decision_sha256": decision_sha256,
        "authorization_receipt_sha256": authorization_sha256,
        "factor_ids": sorted(factors), "replay_protected": True,
        "graph_audit": audit, "leakage_audit": leakage,
        "provenance_confirmation": provenance_confirmation,
        "fresh_process_provenance_confirmation": fresh_provenance_confirmation,
        "persistent_hashes_before": before, "persistent_hashes_after": after,
        "candidate_only": True, "canonical_mutation_authorized": False,
        "promotion_performed": False, "deployment_performed": False,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["state"] == "PASS" else 2


def command_recall_grounded_question(args: argparse.Namespace) -> int:
    """Fresh-process, no-write recall of one learned question and its grounded response."""

    from .steel_brain_store import SQLiteNeuronGraphStore

    graph_path = args.graph.resolve()
    curriculum_path = args.curriculum_db.resolve()
    dictionary_path = args.dictionary.resolve()
    teacher_path = args.teacher.resolve()
    learning_receipt_path = args.learning_receipt.resolve()
    teacher = json.loads(teacher_path.read_text(encoding="utf-8"))
    dictionary_sha256 = hashlib.sha256(dictionary_path.read_bytes()).hexdigest().upper()
    if teacher.get("schema") != "NN_CPU_PRIVATE_QUESTION_FACTS_V1":
        raise ValueError("unsupported CPU-private question fact schema")
    if str(teacher.get("dictionary_sha256")) != dictionary_sha256:
        raise ValueError("question facts do not match the Webster source")
    facts = {str(item["fact_id"]): item for item in teacher.get("facts", ())}
    if args.fact_id not in facts:
        raise ValueError("unknown CPU-private question fact id")
    fact = facts[args.fact_id]
    learning_receipt = json.loads(learning_receipt_path.read_text(encoding="utf-8"))
    hydra_receipt = learning_receipt.get("hydra_route_membrane")
    if (
        learning_receipt.get("state") != "PASS"
        or learning_receipt.get("utterance_kind") != "INTERROGATIVE"
        or not isinstance(hydra_receipt, dict)
        or hydra_receipt.get("enabled") is not True
        or int(hydra_receipt.get("compilations", 0)) < 1
    ):
        raise ValueError("grounded recall requires a PASSed Rust-Hydra interrogative receipt")
    hydra_trace_path = Path(str(hydra_receipt.get("trace", ""))).resolve()
    if not hydra_trace_path.is_file():
        raise FileNotFoundError("Rust-Hydra trace from learning receipt is missing")
    question_words = tuple(str(value).lower() for value in fact["supported_surface"])
    response_words = tuple(str(value).lower() for value in fact["grounded_response_surface"])
    if len(question_words) != 3 or len(response_words) != 3:
        raise ValueError("bounded grounded recall currently requires three-word routes")
    before = {
        "graph": _persistent_sqlite_hashes(graph_path),
        "curriculum": _persistent_sqlite_hashes(curriculum_path),
    }
    seeds = tuple(args.seed + (index + 1) * 1_000_003 for index in range(args.confirmations))
    with SQLiteNeuronGraphStore(graph_path, readonly=True) as store:
        manifest = store.manifest()
        question_ids = tuple(str(manifest["word_index"].get(word, "")) for word in question_words)
        response_ids = tuple(str(manifest["word_index"].get(word, "")) for word in response_words)
        if any(not value for value in (*question_ids, *response_ids)):
            raise ValueError("grounded recall references an unadmitted word")
        engine = Neuronizer(store, CudaLibrary())
        question_ranking = engine.rank_admitted_sentence_experts(
            [f"WORD:{word}" for word in question_words]
        )
        question_neuron = store.load_neuron(str(question_ranking[0]["sentence_id"]))
        response_ranking = engine.rank_admitted_sentence_experts(
            [f"WORD:{word}" for word in response_words]
        )
        response_neuron = store.load_neuron(str(response_ranking[0]["sentence_id"]))
        question_counts = engine.sample_admitted_sentence_distribution(
            [f"WORD:{word}" for word in question_words], seeds=seeds
        )
        response_counts = engine.sample_admitted_sentence_distribution(
            [f"WORD:{word}" for word in response_words], seeds=seeds
        )
        audit = store.audit()
    after = {
        "graph": _persistent_sqlite_hashes(graph_path),
        "curriculum": _persistent_sqlite_hashes(curriculum_path),
    }

    def clean_counts(rows: dict[str, int]) -> dict[str, int]:
        return {
            " ".join(part.removeprefix("WORD:") for part in text.split()): count
            for text, count in rows.items()
        }

    question_counts_clean = clean_counts(question_counts)
    response_counts_clean = clean_counts(response_counts)
    question_text = " ".join(question_words)
    response_text = " ".join(response_words)
    question_mode_ok = question_neuron.get("center_attractor", {}).get(
        "opaque_utterance_mode_v1"
    ) == "U1"
    response_mode = response_neuron.get("center_attractor", {}).get(
        "opaque_utterance_mode_v1", "U0"
    )
    response_mode_ok = response_mode == "U0"
    receipt_question_id = str(learning_receipt.get("result", {}).get("sentence_id", ""))
    hydra_binding_ok = receipt_question_id == str(question_neuron["neuron_id"])
    recall_ok = (
        question_counts_clean == {question_text: args.confirmations}
        and response_counts_clean == {response_text: args.confirmations}
    )
    unchanged = before == after
    state = "PASS" if recall_ok and question_mode_ok and response_mode_ok and hydra_binding_ok and unchanged and audit["state"] == "PASS" else "HOLD"
    graph_sha = next(iter(after["graph"].values()))
    curriculum_sha = next(iter(after["curriculum"].values()))
    packet = {
        "schema_version": "steel_brain_grounded_utterance_packet_v1",
        "candidate_only": True,
        "external_effects": False,
        "question": question_text + "?",
        "question_word_route": list(question_words),
        "response": response_text + ".",
        "response_word_route": list(response_words),
        "question_sentence_id": str(question_neuron["neuron_id"]),
        "response_sentence_id": str(response_neuron["neuron_id"]),
        "gates": {
            "question_grammar": "PASS" if question_mode_ok and recall_ok else "HOLD",
            "question_meaning": "PASS" if recall_ok else "HOLD",
            "grounded_response_truth": "PASS" if response_mode_ok and recall_ok else "HOLD",
            "authority": "PASS_NO_AUTHORITY" if state == "PASS" else "HOLD",
        },
        "route_gate": {
            "allowed": state == "PASS",
            "local_text_only": True,
            "state": "PASS_RUST_HYDRA_ROUTE_GATE" if state == "PASS" else "HOLD",
            "hydra_trace_sha256": hashlib.sha256(hydra_trace_path.read_bytes()).hexdigest().upper(),
        },
        "integrity": {"graph_sha256": graph_sha, "curriculum_sha256": curriculum_sha},
        "source_receipt": str(learning_receipt_path),
        "may_emit": False,
        "tool_authority": False,
        "memory_write": False,
    }
    report = {
        "schema": "NN_FROZEN_GROUNDED_QUESTION_RECALL_V1",
        "state": state,
        "fact_id": args.fact_id,
        "raw_question_recall": question_counts_clean,
        "raw_response_recall": response_counts_clean,
        "confirmations": args.confirmations,
        "persistent_state_unchanged": unchanged,
        "rust_hydra_binding": {
            "state": "PASS" if hydra_binding_ok else "HOLD",
            "learning_receipt": str(learning_receipt_path),
            "learning_receipt_sha256": hashlib.sha256(learning_receipt_path.read_bytes()).hexdigest().upper(),
            "trace": str(hydra_trace_path),
            "trace_sha256": hashlib.sha256(hydra_trace_path.read_bytes()).hexdigest().upper(),
            "compilations": int(hydra_receipt.get("compilations", 0)),
            "cache_hits": int(hydra_receipt.get("cache_hits", 0)),
            "denied_candidates": int(hydra_receipt.get("denied_candidates", 0)),
        },
        "graph_audit": audit,
        "persistent_hashes_before": before,
        "persistent_hashes_after": after,
        "aios_packet": packet,
        "canonical_mutation_authorized": False,
        "promotion_performed": False,
        "deployment_performed": False,
    }
    output = json.dumps(report, ensure_ascii=False, indent=2)
    output_path = args.output.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        raise FileExistsError("grounded recall receipt is append-only; choose a fresh path")
    output_path.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if state == "PASS" else 2


def command_run_conversation(args: argparse.Namespace) -> int:
    """Run one bounded, read-only conversation with ephemeral CPU context.

    CUDA recalls only the learned question route. The CPU-private fact index
    resolves it to an admitted declarative SENTENCE; answer targets never
    enter the CUDA candidate payload.
    """

    from .steel_brain_store import SQLiteNeuronGraphStore

    graph_path = args.graph.resolve()
    curriculum_path = args.curriculum_db.resolve()
    teacher_path = args.teacher.resolve()
    dictionary_path = args.dictionary.resolve()
    teacher = json.loads(teacher_path.read_text(encoding="utf-8"))
    dictionary_sha256 = hashlib.sha256(dictionary_path.read_bytes()).hexdigest().upper()
    if teacher.get("schema") != "NN_CPU_PRIVATE_QUESTION_FACTS_V1":
        raise ValueError("unsupported CPU-private conversation fact schema")
    if str(teacher.get("dictionary_sha256")) != dictionary_sha256:
        raise ValueError("conversation facts do not match the Webster source")
    facts = {str(item["fact_id"]): item for item in teacher.get("facts", ())}
    direct_by_question = {
        " ".join(str(value).lower() for value in fact["supported_surface"]): fact
        for fact in facts.values() if fact.get("grounded_response_surface")
    }
    context_by_question = {
        " ".join(str(value).lower() for value in fact["supported_surface"]): fact
        for fact in facts.values() if fact.get("opaque_context_requirement") == "K0"
    }
    receipts: dict[str, dict[str, Any]] = {}
    receipt_paths: dict[str, Path] = {}
    for value in args.learning_receipt:
        path = Path(value).resolve()
        receipt = json.loads(path.read_text(encoding="utf-8"))
        sentence_id = str(receipt.get("result", {}).get("sentence_id", ""))
        hydra = receipt.get("hydra_route_membrane", {})
        interrogative_receipt = (
            receipt.get("utterance_kind") == "INTERROGATIVE"
            or receipt.get("schema") == "NN_TEMPLATE_GENERALIZED_QUESTION_V1"
        )
        if (
            receipt.get("state") != "PASS"
            or not interrogative_receipt
            or not sentence_id
            or not isinstance(hydra, dict)
            or hydra.get("enabled") is not True
            or int(hydra.get("compilations", 0)) < 1
        ):
            raise ValueError(f"invalid Rust-Hydra interrogative receipt: {path}")
        receipts[sentence_id] = receipt
        receipt_paths[sentence_id] = path
    raw_turns = [value.strip() for value in args.turns.split("|") if value.strip()]
    if not raw_turns or len(raw_turns) > args.max_turns:
        raise ValueError("conversation turn count is outside its bound")
    before = {
        "graph": _persistent_sqlite_hashes(graph_path),
        "curriculum": _persistent_sqlite_hashes(curriculum_path),
    }
    session_started = time.monotonic()
    session_number = 1
    current_direct_fact: dict[str, Any] | None = None
    turns: list[dict[str, Any]] = []

    def normalize_question(text: str) -> str:
        return " ".join(text.strip().lower().rstrip("?.!").split())

    with SQLiteNeuronGraphStore(graph_path, readonly=True) as store:
        manifest = store.manifest()
        engine = Neuronizer(store, CudaLibrary())
        stable_sentences: dict[tuple[str, ...], dict[str, Any]] = {}
        for neuron_id, summary in manifest.get("neuron_index", {}).items():
            if summary.get("kind") != "SENTENCE":
                continue
            neuron = store.load_neuron(str(neuron_id))
            center = neuron.get("center_attractor", {})
            if neuron.get("lifecycle") == "STABLE" and center.get("trusted_language_memory") is True:
                stable_sentences[tuple(str(value) for value in center.get("construction", ()))] = neuron
        word_surface_by_id = {
            str(neuron_id): str(surface)
            for surface, neuron_id in manifest["word_index"].items()
        }
        templates: list[tuple[str, dict[str, Any]]] = []
        for neuron_id, summary in manifest.get("neuron_index", {}).items():
            if summary.get("kind") != "CONCEPT":
                continue
            neuron = store.load_neuron(str(neuron_id))
            payload = neuron.get("center_attractor", {}).get("opaque_interrogative_template_v1")
            if neuron.get("lifecycle") == "STABLE" and isinstance(payload, dict):
                templates.append((str(neuron_id), payload))

        def derive_template_fact(question: str) -> dict[str, Any] | None:
            question_words = tuple(question.split())
            question_ids = tuple(str(manifest["word_index"].get(word, "")) for word in question_words)
            if any(not value for value in question_ids):
                return None
            question_neuron = stable_sentences.get(question_ids)
            if question_neuron is None or str(question_neuron["neuron_id"]) not in receipts:
                return None
            question_receipt = receipts[str(question_neuron["neuron_id"])]
            matches: list[dict[str, Any]] = []
            for template_id, payload in templates:
                if (
                    payload.get("question_family") == "Q3"
                    and question_receipt.get("capability_gate", {}).get("state") != "PASS"
                ):
                    continue
                if len(question_ids) != int(payload.get("question_arity", -1)):
                    continue
                constants = {
                    int(position): str(value)
                    for position, value in payload.get("constant_question_positions", {}).items()
                }
                if any(question_ids[position] != value for position, value in constants.items()):
                    continue
                response_constants = {
                    int(position): str(value)
                    for position, value in payload.get("constant_response_positions", {}).items()
                }
                responses: list[tuple[str, ...]] = []
                for route, candidate in stable_sentences.items():
                    center = candidate.get("center_attractor", {})
                    if center.get("opaque_utterance_mode_v1", "U0") != "U0" or len(route) != int(payload.get("response_arity", -1)):
                        if not (
                            payload.get("question_family") == "Q3"
                            and center.get("opaque_utterance_mode_v1") == "U2"
                            and len(route) == int(payload.get("response_arity", -1))
                        ):
                            continue
                    if any(route[position] != value for position, value in response_constants.items()):
                        continue
                    if all(
                        question_ids[int(link["question_position"])]
                        == route[int(link["response_position"])]
                        for link in payload.get("response_copy_links", ())
                    ):
                        responses.append(route)
                if len(responses) == 1:
                    matches.append({
                        "supported_surface": list(question_words),
                        "grounded_response_surface": [word_surface_by_id[value] for value in responses[0]],
                        "grammar_channels": list(payload.get("question_anchor_channels", ())),
                        "_template_id": template_id,
                    })
            return matches[0] if len(matches) == 1 else None
        for turn_number, raw_text in enumerate(raw_turns, 1):
            if raw_text.upper() == "RESET":
                current_direct_fact = None
                session_number += 1
                session_started = time.monotonic()
                turns.append({"turn": turn_number, "session": session_number, "input": "RESET", "state": "SESSION_RESET", "context_persisted": False, "write_performed": False})
                continue
            question = normalize_question(raw_text)
            if time.monotonic() - session_started >= args.context_ttl_seconds:
                current_direct_fact = None
            fact = (
                direct_by_question.get(question)
                or context_by_question.get(question)
                or derive_template_fact(question)
            )
            base = {"turn": turn_number, "session": session_number, "input": raw_text, "write_performed": False}
            if fact is None:
                turns.append({**base, "state": "HOLD_UNSUPPORTED_QUESTION", "gates": {"grammar": "HOLD", "meaning": "HOLD", "truth": "HOLD", "context": "HOLD", "authority": "PASS_NO_AUTHORITY"}})
                continue
            question_words = tuple(str(value).lower() for value in fact["supported_surface"])
            question_ids = tuple(str(manifest["word_index"].get(word, "")) for word in question_words)
            question_neuron = stable_sentences.get(question_ids)
            if question_neuron is None or question_neuron.get("center_attractor", {}).get("opaque_utterance_mode_v1") != "U1" or str(question_neuron.get("neuron_id")) not in receipts:
                turns.append({**base, "state": "HOLD_UNLEARNED_QUESTION_ROUTE", "gates": {"grammar": "HOLD", "meaning": "HOLD", "truth": "HOLD", "context": "HOLD", "authority": "PASS_NO_AUTHORITY"}})
                continue
            question_receipt = receipts[str(question_neuron["neuron_id"])]
            counts = engine.sample_admitted_sentence_distribution(
                [f"WORD:{word}" for word in question_words],
                seeds=tuple(
                    args.seed + turn_number * 1_000_003 + draw * 97_409
                    for draw in range(1, args.confirmations + 1)
                ),
                sentence_id=str(question_neuron["neuron_id"]),
            )
            clean_counts = {" ".join(part.removeprefix("WORD:") for part in text.split()): count for text, count in counts.items()}
            if clean_counts != {question: args.confirmations}:
                turns.append({**base, "state": "HOLD_QUESTION_RECALL", "raw_question_recall": clean_counts, "gates": {"grammar": "HOLD", "meaning": "HOLD", "truth": "HOLD", "context": "HOLD", "authority": "PASS_NO_AUTHORITY"}})
                continue
            contextual = fact.get("opaque_context_requirement") == "K0"
            response_fact = current_direct_fact if contextual else fact
            if response_fact is None:
                turns.append({**base, "state": "HOLD_CONTEXT_EMPTY", "raw_question_recall": clean_counts, "gates": {"grammar": "PASS", "meaning": "PASS", "truth": "HOLD", "context": "HOLD", "authority": "PASS_NO_AUTHORITY"}})
                continue
            response_words = tuple(str(value).lower() for value in response_fact["grounded_response_surface"])
            response_ids = tuple(str(manifest["word_index"].get(word, "")) for word in response_words)
            response_neuron = stable_sentences.get(response_ids)
            allowed_response_modes = {"U2"} if fact.get("_template_id") and question_receipt.get("capability_gate", {}).get("state") == "PASS" else {"U0"}
            if response_neuron is None or response_neuron.get("center_attractor", {}).get("opaque_utterance_mode_v1", "U0") not in allowed_response_modes:
                turns.append({**base, "state": "HOLD_NO_TRUSTED_RESPONSE", "raw_question_recall": clean_counts, "gates": {"grammar": "PASS", "meaning": "PASS", "truth": "HOLD", "context": "PASS" if contextual else "NOT_REQUIRED", "authority": "PASS_NO_AUTHORITY"}})
                continue
            response_counts = engine.sample_admitted_sentence_distribution(
                [f"WORD:{word}" for word in response_words],
                seeds=tuple(
                    args.seed + turn_number * 1_000_003 + draw * 97_409
                    for draw in range(1, args.confirmations + 1)
                ),
                sentence_id=str(response_neuron["neuron_id"]),
            )
            clean_response_counts = {
                " ".join(part.removeprefix("WORD:") for part in text.split()): count
                for text, count in response_counts.items()
            }
            if clean_response_counts != {" ".join(response_words): args.confirmations}:
                turns.append({**base, "state": "HOLD_RESPONSE_RECALL", "raw_question_recall": clean_counts, "raw_response_recall": clean_response_counts, "gates": {"grammar": "PASS", "meaning": "PASS", "truth": "HOLD", "context": "PASS" if contextual else "NOT_REQUIRED", "authority": "PASS_NO_AUTHORITY"}})
                continue
            if not contextual:
                current_direct_fact = fact
            receipt_path = receipt_paths[str(question_neuron["neuron_id"])]
            turns.append({
                **base,
                "state": "PASS_GROUNDED_RESPONSE",
                "question": question + "?",
                "response": " ".join(response_words) + ".",
                "question_sentence_id": str(question_neuron["neuron_id"]),
                "response_sentence_id": str(response_neuron["neuron_id"]),
                "question_word_route": list(question_words),
                "response_word_route": list(response_words),
                "raw_question_recall": clean_counts,
                "raw_response_recall": clean_response_counts,
                "context_source": (
                    "K0_EPHEMERAL_SESSION"
                    if contextual
                    else "TEMPLATE_GENERALIZED_GRAPH_FACT"
                    if fact.get("_template_id")
                    else "DIRECT_CPU_PRIVATE_FACT"
                ),
                **({"template_id": fact["_template_id"]} if fact.get("_template_id") else {}),
                "gates": {"grammar": "PASS", "meaning": "PASS", "truth": "PASS", "context": "PASS" if contextual else "NOT_REQUIRED", "authority": "PASS_NO_AUTHORITY"},
                "rust_hydra_receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest().upper(),
                "target_answer_uploaded_to_cuda": False,
            })
        audit = store.audit()
    after = {"graph": _persistent_sqlite_hashes(graph_path), "curriculum": _persistent_sqlite_hashes(curriculum_path)}
    pass_count = sum(row.get("state") == "PASS_GROUNDED_RESPONSE" for row in turns)
    unsupported_holds = sum(row.get("state") == "HOLD_UNSUPPORTED_QUESTION" for row in turns)
    context_passes = sum(row.get("state") == "PASS_GROUNDED_RESPONSE" and row.get("context_source") == "K0_EPHEMERAL_SESSION" for row in turns)
    context_empty_holds = sum(row.get("state") == "HOLD_CONTEXT_EMPTY" for row in turns)
    unchanged = before == after
    has_context_suite = bool(context_by_question)
    state = "PASS" if (
        unchanged
        and audit["state"] == "PASS"
        and (
            pass_count >= 4 and unsupported_holds >= 1 and context_passes >= 1 and context_empty_holds >= 1
            if has_context_suite
            else pass_count == len([row for row in turns if row.get("state") != "SESSION_RESET"])
        )
    ) else "HOLD"
    graph_sha = next(iter(after["graph"].values()))
    curriculum_sha = next(iter(after["curriculum"].values()))
    boundary_turns: list[dict[str, Any]] = []
    for row in turns:
        boundary_row = {
            "turn": row["turn"],
            "session": row["session"],
            "state": row["state"],
            "gates": row.get("gates", {}),
        }
        if row.get("state") == "PASS_GROUNDED_RESPONSE":
            sentence_id = str(row["question_sentence_id"])
            receipt_path = receipt_paths[sentence_id]
            receipt = receipts[sentence_id]
            hydra_path = Path(str(receipt["hydra_route_membrane"]["trace"])).resolve()
            boundary_row["utterance_packet"] = {
                "schema_version": "steel_brain_grounded_utterance_packet_v1",
                "candidate_only": True,
                "external_effects": False,
                "question": row["question"],
                "question_word_route": row["question_word_route"],
                "response": row["response"],
                "response_word_route": row["response_word_route"],
                "question_sentence_id": row["question_sentence_id"],
                "response_sentence_id": row["response_sentence_id"],
                "gates": {
                    "question_grammar": row["gates"]["grammar"],
                    "question_meaning": row["gates"]["meaning"],
                    "grounded_response_truth": row["gates"]["truth"],
                    "authority": row["gates"]["authority"],
                },
                "route_gate": {
                    "allowed": True,
                    "local_text_only": True,
                    "state": "PASS_RUST_HYDRA_ROUTE_GATE",
                    "hydra_trace_sha256": hashlib.sha256(hydra_path.read_bytes()).hexdigest().upper(),
                },
                "integrity": {"graph_sha256": graph_sha, "curriculum_sha256": curriculum_sha},
                "source_receipt": str(receipt_path),
                "may_emit": False,
                "tool_authority": False,
                "memory_write": False,
            }
        boundary_turns.append(boundary_row)
    aios_packet = {
        "schema_version": "steel_brain_conversation_packet_v1",
        "candidate_only": True,
        "external_effects": False,
        "turns": boundary_turns,
        "context": {"owner": "CPU_SESSION_RAM", "persisted": False, "reset_supported": True},
        "integrity": {"graph_sha256": graph_sha, "curriculum_sha256": curriculum_sha},
        "may_emit": False,
        "tool_authority": False,
        "memory_write": False,
    }
    report = {
        "schema": "NN_BOUNDED_GENERAL_CONVERSATION_V1",
        "state": state,
        "turns": turns,
        "summary": {"grounded_response_passes": pass_count, "context_followup_passes": context_passes, "unsupported_holds": unsupported_holds, "fresh_session_context_holds": context_empty_holds},
        "context": {"owner": "CPU_SESSION_RAM", "ttl_seconds": args.context_ttl_seconds, "persisted": False, "reset_supported": True},
        "target_answer_uploaded_to_cuda": False,
        "aios_packet": aios_packet,
        "graph_audit": audit,
        "persistent_state_unchanged": unchanged,
        "persistent_hashes_before": before,
        "persistent_hashes_after": after,
        "candidate_only": True,
        "canonical_mutation_authorized": False,
        "promotion_performed": False,
        "deployment_performed": False,
    }
    output_path = args.output.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        raise FileExistsError("conversation receipt is append-only; choose a fresh path")
    output = json.dumps(report, ensure_ascii=False, indent=2)
    output_path.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if state == "PASS" else 2


def _opaque_word_signature(neuron: dict[str, Any]) -> str | None:
    """Return the strongest learned opaque identity or grammar channel."""

    center = neuron.get("center_attractor", {})
    ranked: list[tuple[int, int, str]] = []
    for profile_key in (
        UniversalCurriculumEngine.WORD_IDENTITY_PROFILE_KEY,
        UniversalCurriculumEngine.WORD_CLASS_PROFILE_KEY,
    ):
        profile = center.get(profile_key, {})
        for item in profile.get("channels", ()) if isinstance(profile, dict) else ():
            hits = int(item.get("pass_hits", 0))
            if hits > 0:
                ranked.append((hits, int(item.get("weight", 0)), str(item.get("channel", ""))))
        if ranked:
            return max(ranked)[2]
    return None


def _opaque_word_channels(neuron: dict[str, Any]) -> list[str]:
    """Return every positively learned opaque identity/grammar channel."""

    center = neuron.get("center_attractor", {})
    identity = center.get(UniversalCurriculumEngine.WORD_IDENTITY_PROFILE_KEY, {})
    identity_channels = sorted(
        str(item.get("channel"))
        for item in identity.get("channels", ()) if isinstance(identity, dict)
        if int(item.get("pass_hits", 0)) > 0
    )
    if identity_channels:
        return identity_channels
    grammar = center.get(UniversalCurriculumEngine.WORD_CLASS_PROFILE_KEY, {})
    return sorted(
        str(item.get("channel"))
        for item in grammar.get("channels", ()) if isinstance(grammar, dict)
        if int(item.get("pass_hits", 0)) > 0
    )


def command_learn_social_intent(args: argparse.Namespace) -> int:
    """Induce one opaque intent from multiple admitted social question forms."""

    from .leakage_audit import audit_gpu_payload
    from .steel_brain_store import SQLiteNeuronGraphStore

    teacher_path = args.teacher.resolve()
    teacher = json.loads(teacher_path.read_text(encoding="utf-8"))
    if teacher.get("schema") != "NN_CPU_PRIVATE_SOCIAL_ACTS_V1":
        raise ValueError("unsupported social intent teacher schema")
    facts = {str(item["fact_id"]): item for item in teacher.get("facts", ())}
    fact_ids = tuple(value.strip() for value in args.fact_ids.split(",") if value.strip())
    if len(fact_ids) < 2 or any(value not in facts for value in fact_ids):
        raise ValueError("social intent induction requires at least two known facts")
    selected = [facts[value] for value in fact_ids]
    dictionary_raw = args.dictionary.resolve().read_bytes()
    if str(teacher.get("dictionary_sha256", "")) != hashlib.sha256(dictionary_raw).hexdigest().upper():
        raise ValueError("social intent teacher does not match Webster")
    dictionary_rows = json.loads(dictionary_raw.decode("utf-8"))
    interrogative_heads = {
        str(row.get("word", "")).strip().lower()
        for row in dictionary_rows
        if any("interrogative pronoun" in str(value).lower() for value in row.get("definitions", ()))
    }
    dictionary_definitions: dict[str, tuple[str, ...]] = {}
    for row in dictionary_rows:
        word = str(row.get("word", "")).strip().lower()
        dictionary_definitions[word] = dictionary_definitions.get(word, ()) + tuple(
            str(value).lower() for value in row.get("definitions", ())
        )
    acts = {str(item.get("social_act", "")) for item in selected}
    responses = {tuple(str(word).lower() for word in item.get("response_surface", ())) for item in selected}
    if len(acts) != 1 or "" in acts or len(responses) != 1 or not next(iter(responses)):
        raise ValueError("social intent sources must share one act and one response")
    receipt_by_surface: dict[tuple[str, ...], dict[str, Any]] = {}
    for value in args.learning_receipt:
        receipt = json.loads(Path(value).resolve().read_text(encoding="utf-8"))
        construction = tuple(
            str(word).lower().removeprefix("word:")
            for word in receipt.get("result", {}).get("construction", ())
        )
        hydra = receipt.get("hydra_route_membrane", {})
        if (
            receipt.get("state") != "PASS"
            or receipt.get("utterance_kind") != "SOCIAL"
            or not receipt.get("result", {}).get("sentence_id")
            or hydra.get("enabled") is not True
            or not construction
        ):
            raise ValueError("intent source requires PASSed Rust-Hydra social receipts")
        receipt_by_surface[construction] = receipt
    graph_path = args.graph.resolve()
    curriculum_path = args.curriculum_db.resolve()
    before = {"graph": _persistent_sqlite_hashes(graph_path), "curriculum": _persistent_sqlite_hashes(curriculum_path)}
    response_surface = next(iter(responses))
    with SQLiteNeuronGraphStore(graph_path) as store:
        manifest = store.manifest()
        source_ids: list[str] = []
        source_signatures: list[list[str]] = []
        source_patterns: list[dict[str, Any]] = []
        for fact in selected:
            surface = tuple(str(word).lower() for word in fact.get("supported_surface", ()))
            receipt = receipt_by_surface.get(surface)
            if receipt is None:
                raise ValueError(f"missing admitted source receipt for {' '.join(surface)}")
            sentence_id = str(receipt["result"]["sentence_id"])
            sentence = store.load_neuron(sentence_id)
            route = tuple(str(value) for value in sentence.get("center_attractor", {}).get("construction", ()))
            expected = tuple(str(manifest["word_index"].get(word, "")) for word in surface)
            if route != expected or sentence.get("lifecycle") != "STABLE":
                raise ValueError("social intent receipt does not match stable source route")
            signature = [_opaque_word_channels(store.load_neuron(word_id)) for word_id in expected]
            if not signature:
                raise ValueError("social intent source has no learned word route")
            source_ids.append(sentence_id)
            source_signatures.append(signature)
            if surface[0] in interrogative_heads:
                if not signature[0]:
                    raise ValueError("interrogative intent source head lacks learned opaque word metadata")
                source_patterns.append({
                    "pattern_kind": "INTERROGATIVE_HEAD_PLUS_ANCHORED_TAIL_V1",
                    "head_channels": signature[0],
                    "anchored_tail_word_ids": list(expected[1:]),
                })
            elif fact.get("opaque_intent_pattern") == "COMMUNICATION_HEAD_PLUS_NAME_SUFFIX_V1":
                definitions = "\n".join(dictionary_definitions.get(surface[0], ()))
                if not any(probe in definitions for probe in SOCIAL_COMMUNICATION_HEAD_DEFINITION_PROBES):
                    raise ValueError("communication intent source head lacks Webster evidence")
                source_patterns.append({
                    "pattern_kind": "COMMUNICATION_HEAD_PLUS_ANCHORED_SUFFIX_V1",
                    "head_channels": signature[0],
                    "anchored_suffix_word_ids": list(expected[-2:]),
                    "minimum_arity": 3,
                    "maximum_arity": 4,
                    "cpu_probe_sha256": hashlib.sha256(
                        "\0".join(SOCIAL_COMMUNICATION_HEAD_DEFINITION_PROBES).encode("utf-8")
                    ).hexdigest().upper(),
                })
        response_ids = tuple(str(manifest["word_index"].get(word, "")) for word in response_surface)
        response_sentence_id = ""
        for neuron_id, summary in manifest.get("neuron_index", {}).items():
            if summary.get("kind") != "SENTENCE":
                continue
            neuron = store.load_neuron(str(neuron_id))
            center = neuron.get("center_attractor", {})
            if (
                neuron.get("lifecycle") == "STABLE"
                and center.get("trusted_language_memory") is True
                and center.get("opaque_utterance_mode_v1") == "U2"
                and tuple(str(value) for value in center.get("construction", ())) == response_ids
            ):
                response_sentence_id = str(neuron_id)
                break
        if not response_sentence_id:
            raise ValueError("social intent has no admitted grounded response")
        source_handle = hashlib.sha256(
            json.dumps({"facts": fact_ids, "sources": source_ids}, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest().upper()
        result = Neuronizer(store, CudaLibrary()).learn_social_intent_concept(
            source_ids,
            source_signatures=source_signatures,
            source_patterns=source_patterns,
            response_sentence_id=response_sentence_id,
            source_handle=source_handle,
        )
        audit = store.audit()
        leakage = audit_gpu_payload(store.load_neuron(str(result.get("concept_id")))) if result.get("concept_id") else {"state": "HOLD"}
    after = {"graph": _persistent_sqlite_hashes(graph_path), "curriculum": _persistent_sqlite_hashes(curriculum_path)}
    state = "PASS" if result.get("state") == "PASS" and audit.get("state") == "PASS" and leakage.get("state") == "PASS" else "HOLD"
    report = {
        "schema": "NN_SOCIAL_INTENT_INDUCTION_V1",
        "state": state,
        "source_fact_ids": list(fact_ids),
        "cpu_private_social_act": next(iter(acts)),
        "cpu_private_response_surface": list(response_surface),
        "result": result,
        "graph_audit": audit,
        "leakage_audit": leakage,
        "persistent_hashes_before": before,
        "persistent_hashes_after": after,
        "canonical_mutation_authorized": False,
        "promotion_performed": False,
        "deployment_performed": False,
    }
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError("social intent receipt is append-only")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if state == "PASS" else 2


def command_learn_question_template(args: argparse.Namespace) -> int:
    """Induce one reusable question transform from admitted grounded pairs."""

    from .leakage_audit import audit_gpu_payload
    from .steel_brain_store import SQLiteNeuronGraphStore

    graph_path = args.graph.resolve()
    curriculum_path = args.curriculum_db.resolve()
    teacher_path = args.teacher.resolve()
    teacher = json.loads(teacher_path.read_text(encoding="utf-8"))
    facts = {str(item["fact_id"]): item for item in teacher.get("facts", ())}
    fact_ids = tuple(value.strip() for value in args.fact_ids.split(",") if value.strip())
    teacher_schema = str(teacher.get("schema", ""))
    if teacher_schema not in {"NN_CPU_PRIVATE_QUESTION_FACTS_V1", "NN_CPU_PRIVATE_BINARY_RELATIONS_V1"} or len(fact_ids) < 3:
        raise ValueError("template induction requires at least three question facts")
    if any(fact_id not in facts for fact_id in fact_ids):
        raise ValueError("unknown template source fact")
    receipt_ids: set[str] = set()
    for value in args.learning_receipt:
        receipt = json.loads(Path(value).resolve().read_text(encoding="utf-8"))
        binary_receipt = receipt.get("schema") == "NN_BINARY_RELATION_LEARNING_REPORT_V1"
        hydra = receipt.get("question_hydra", {}) if binary_receipt else receipt.get("hydra_route_membrane", {})
        sentence_id = str(
            receipt.get("question_result", {}).get("sentence_id", "")
            if binary_receipt
            else receipt.get("result", {}).get("sentence_id", "")
        )
        if receipt.get("state") != "PASS" or hydra.get("enabled") is not True or not sentence_id:
            raise ValueError("template source requires PASSed Rust-Hydra receipts")
        receipt_ids.add(sentence_id)
    before = {"graph": _persistent_sqlite_hashes(graph_path), "curriculum": _persistent_sqlite_hashes(curriculum_path)}
    with SQLiteNeuronGraphStore(graph_path) as store:
        manifest = store.manifest()
        stable_by_route: dict[tuple[str, ...], dict[str, Any]] = {}
        for neuron_id, summary in manifest.get("neuron_index", {}).items():
            if summary.get("kind") != "SENTENCE":
                continue
            neuron = store.load_neuron(str(neuron_id))
            center = neuron.get("center_attractor", {})
            if neuron.get("lifecycle") == "STABLE" and center.get("trusted_language_memory") is True:
                stable_by_route[tuple(str(value) for value in center.get("construction", ()))] = neuron
        pairs: list[tuple[str, str]] = []
        anchor_rows: list[tuple[str, ...]] = []
        for fact_id in fact_ids:
            fact = facts[fact_id]
            question_surface = fact.get("question_surface", fact.get("supported_surface", ()))
            question_ids = tuple(str(manifest["word_index"].get(str(word).lower(), "")) for word in question_surface)
            question = stable_by_route.get(question_ids)
            structural_only = teacher_schema == "NN_CPU_PRIVATE_BINARY_RELATIONS_V1"
            response = question if structural_only else stable_by_route.get(tuple(str(manifest["word_index"].get(str(word).lower(), "")) for word in fact["grounded_response_surface"]))
            if question is None or response is None or str(question["neuron_id"]) not in receipt_ids:
                raise ValueError(f"template source pair is not admitted and Rust-bound: {fact_id}")
            pairs.append((str(question["neuron_id"]), str(response["neuron_id"])))
            anchor_rows.append(tuple(str(value) for value in fact["grammar_channels"]))
        if len(set(anchor_rows)) != 1:
            raise ValueError("template sources do not share one opaque anchor pattern")
        question_families = {
            str(facts[fact_id].get("opaque_question_family", "Q0"))
            for fact_id in fact_ids
        }
        if len(question_families) != 1:
            raise ValueError("template sources do not share one opaque question family")
        source_handle = hashlib.sha256(
            json.dumps({"facts": fact_ids, "pairs": pairs}, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest().upper()
        result = Neuronizer(store, CudaLibrary()).learn_interrogative_template(
            pairs,
            question_anchor_channels=anchor_rows[0],
            source_handle=source_handle,
            question_family=next(iter(question_families)),
        )
        audit = store.audit()
        leakage = audit_gpu_payload(store.load_neuron(str(result.get("template_id")))) if result.get("template_id") else {"state": "HOLD", "violations": ["template_missing"]}
    after = {"graph": _persistent_sqlite_hashes(graph_path), "curriculum": _persistent_sqlite_hashes(curriculum_path)}
    state = "PASS" if result.get("state") == "PASS" and audit["state"] == "PASS" and leakage["state"] == "PASS" else "HOLD"
    report = {
        "schema": "NN_INTERROGATIVE_TEMPLATE_INDUCTION_V1",
        "state": state,
        "source_fact_ids": list(fact_ids),
        "result": result,
        "graph_audit": audit,
        "leakage_audit": leakage,
        "persistent_hashes_before": before,
        "persistent_hashes_after": after,
        "canonical_mutation_authorized": False,
        "promotion_performed": False,
        "deployment_performed": False,
    }
    output_path = args.output.resolve()
    if output_path.exists():
        raise FileExistsError("template receipt is append-only")
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if state == "PASS" else 2


def command_generalize_question(args: argparse.Namespace) -> int:
    """Learn an unseen question from a reusable template and trusted U0 fact."""

    from .leakage_audit import audit_gpu_payload
    from .steel_brain_store import SQLiteNeuronGraphStore

    graph_path = args.graph.resolve()
    curriculum_path = args.curriculum_db.resolve()
    hydra_bin = args.hydra_bin.resolve()
    hydra_trace = args.hydra_trace.resolve()
    question_words = tuple(value for value in args.question.lower().rstrip("?.!").split() if value)
    before = {"graph": _persistent_sqlite_hashes(graph_path), "curriculum": _persistent_sqlite_hashes(curriculum_path)}
    capability_gate: dict[str, Any] | None = None
    with SQLiteNeuronGraphStore(graph_path) as store:
        manifest = store.manifest()
        question_ids = tuple(str(manifest["word_index"].get(word, "")) for word in question_words)
        if any(not value for value in question_ids):
            raise ValueError("generalized question contains an unadmitted word")
        template = store.load_neuron(args.template_id)
        template_payload = template.get("center_attractor", {}).get("opaque_interrogative_template_v1")
        if template.get("kind") != "CONCEPT" or not isinstance(template_payload, dict):
            raise ValueError("template id is not an admitted interrogative concept")
        if len(question_ids) != int(template_payload["question_arity"]):
            raise ValueError("question arity does not match template")
        constants = {int(position): str(value) for position, value in template_payload["constant_question_positions"].items()}
        if any(question_ids[position] != value for position, value in constants.items()):
            raise ValueError("question does not match template constants")
        if template_payload.get("question_family") == "Q3":
            registry_path = getattr(args, "capability_registry", None)
            if registry_path is None:
                raise ValueError("Q3 capability generalization requires a CPU capability registry")
            registry_path = Path(registry_path).resolve()
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            if registry.get("schema") != "NN_CPU_CAPABILITY_REGISTRY_V1":
                raise ValueError("unsupported CPU capability registry")
            variable_positions = [int(value) for value in template_payload.get("variable_question_positions", ())]
            if len(variable_positions) != 1:
                raise ValueError("Q3 capability template requires exactly one variable position")
            capability_word = question_words[variable_positions[0]]
            capability = registry.get("capabilities", {}).get(capability_word)
            if not isinstance(capability, dict):
                raise ValueError("capability is not admitted by the CPU registry")
            evidence_path = Path(str(capability.get("evidence_path", ""))).resolve()
            evidence_sha256 = str(capability.get("evidence_sha256", "")).upper()
            if not evidence_path.is_file() or hashlib.sha256(evidence_path.read_bytes()).hexdigest().upper() != evidence_sha256:
                raise ValueError("capability evidence is missing or stale")
            runtime_predicate = str(capability.get("runtime_predicate", ""))
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            stable_u1_count = sum(
                1
                for neuron_id, summary in manifest.get("neuron_index", {}).items()
                if summary.get("kind") == "SENTENCE"
                and store.load_neuron(str(neuron_id)).get("center_attractor", {}).get("opaque_utterance_mode_v1") == "U1"
            )
            runtime_ok = (
                runtime_predicate == "GRAPH_READABLE" and store.audit().get("state") == "PASS"
                or runtime_predicate == "TEXT_CONVERSATION_AVAILABLE" and store.audit().get("state") == "PASS"
                or runtime_predicate == "QUESTION_GENERATION_AVAILABLE" and stable_u1_count > 0
                or runtime_predicate == "HOLD_BEHAVIOR_AVAILABLE"
                and evidence.get("state") == "PASS"
                and any(str(row.get("observed_state", "")).startswith("HOLD_") for row in evidence.get("control_results", ()))
            )
            capability_gate = {
                "state": "PASS" if runtime_ok else "HOLD",
                "capability_word": capability_word,
                "runtime_predicate": runtime_predicate,
                "evidence_path": str(evidence_path),
                "evidence_sha256": evidence_sha256,
                "registry_sha256": hashlib.sha256(registry_path.read_bytes()).hexdigest().upper(),
            }
            if not runtime_ok:
                raise ValueError("CPU capability predicate is not currently satisfied")
        structural_only = template_payload.get("grounding_mode") == "STRUCTURE_ONLY"
        response_constants = {
            int(position): str(value)
            for position, value in template_payload.get("constant_response_positions", {}).items()
        }
        stable_responses: list[dict[str, Any]] = []
        if not structural_only:
            for neuron_id, summary in manifest.get("neuron_index", {}).items():
                if summary.get("kind") != "SENTENCE":
                    continue
                neuron = store.load_neuron(str(neuron_id))
                center = neuron.get("center_attractor", {})
                route = tuple(str(value) for value in center.get("construction", ()))
                allowed_response_modes = {"U2"} if template_payload.get("question_family") == "Q3" else {"U0"}
                if neuron.get("lifecycle") != "STABLE" or center.get("trusted_language_memory") is not True or center.get("opaque_utterance_mode_v1", "U0") not in allowed_response_modes or len(route) != int(template_payload["response_arity"]):
                    continue
                if any(route[position] != value for position, value in response_constants.items()):
                    continue
                if all(question_ids[int(link["question_position"])] == route[int(link["response_position"])] for link in template_payload["response_copy_links"]):
                    stable_responses.append(neuron)
            if len(stable_responses) != 1:
                raise ValueError(f"template grounding requires exactly one trusted response, found {len(stable_responses)}")
        response = None if structural_only else stable_responses[0]
        response_route = () if response is None else tuple(str(value) for value in response["center_attractor"]["construction"])
        word_surface_by_id = {str(neuron_id): str(surface) for surface, neuron_id in manifest["word_index"].items()}
        response_surface = tuple(word_surface_by_id[value] for value in response_route)
        position_channels = tuple(
            str(value) for value in template_payload.get("question_position_channels", ())
        )

        def slot_compatible(candidate_ids: Sequence[str]) -> bool:
            if not structural_only:
                return True
            if len(position_channels) != len(candidate_ids):
                return False
            return all(
                Neuronizer._context_tag_weight(
                    store.load_neuron(str(candidate_id)),
                    {"position": position_channels[position]},
                )
                > Neuronizer._context_tag_prior(
                    {"position": position_channels[position]}
                )
                for position, candidate_id in enumerate(candidate_ids)
            )

        def judge(candidate: Sequence[str]) -> dict[str, Any]:
            candidate_words = tuple(str(value).lower().removeprefix("word:") for value in candidate)
            candidate_ids = tuple(str(manifest["word_index"].get(word, "")) for word in candidate_words)
            structure = (
                len(candidate_ids) == len(question_ids)
                and all(candidate_ids[position] == value for position, value in constants.items())
                and slot_compatible(candidate_ids)
                and (
                    structural_only
                    or all(candidate_ids[int(link["question_position"])] == response_route[int(link["response_position"])] for link in template_payload["response_copy_links"])
                )
            )
            return {"grammar": structure, "meaning": structure, "truth": structure}

        with CurriculumStore(curriculum_path) as curriculum:
            inventory_context = Neuronizer._inventory_signature(question_ids)
            question_family = str(template_payload.get("question_family", "Q0"))
            route_evidence_context = hashlib.sha256(
                (inventory_context + "\0U1\0" + question_family).encode("utf-8")
            ).hexdigest().upper()
            membrane = HydraRouteMembrane(curriculum, hydra_bin, hydra_trace, evidence_level="SENTENCE")
            result = Neuronizer(store, CudaLibrary(), route_truth_provider=membrane).learn_generated_sentence_episode(
                [f"WORD:{word}" for word in question_words],
                judge,
                seed=args.seed,
                source_handle=hashlib.sha256((args.template_id + "\0" + "\0".join(question_ids)).encode("utf-8")).hexdigest().upper(),
                definition_evidence_sha256=[str(template["content_sha256"])] + ([] if response is None else [str(response["content_sha256"])]),
                max_attempts=args.max_attempts,
                required_confirmations=args.confirmations,
                trace_path=args.trace.resolve(),
                route_truth_context=route_evidence_context,
                route_truth_evidence_writer=lambda route, passed: curriculum.apply_assembly_verdict(level="SENTENCE", inventory_context_sha256=route_evidence_context, route=route, passed=passed),
                activation_anchors=(
                    None
                    if question_family == "Q3"
                    else tuple(
                        {
                            "grammar": str(value),
                            **(
                                {"position": position_channels[position]}
                                if len(position_channels) == len(question_ids)
                                else {}
                            ),
                        }
                        for position, value in enumerate(template_payload["question_anchor_channels"])
                    )
                ),
                utterance_mode="U1",
                question_family=question_family,
            )
            hydra_metrics = membrane.metrics()
        audit = store.audit()
        changed_ids = {str(result.get("episode_id", "")), str(result.get("sentence_id", "")), *question_ids}
        leakage = {neuron_id: audit_gpu_payload(store.load_neuron(neuron_id)) for neuron_id in sorted(changed_ids) if neuron_id}
        permutation_audit = []
        if structural_only:
            for route in permutations(question_ids):
                if all(route[position] == value for position, value in constants.items()):
                    permutation_audit.append({
                        "route": [word_surface_by_id[value] for value in route],
                        "slot_compatible": slot_compatible(route),
                    })
    after = {"graph": _persistent_sqlite_hashes(graph_path), "curriculum": _persistent_sqlite_hashes(curriculum_path)}
    state = "PASS" if result.get("state") == "PASS" and audit["state"] == "PASS" and all(value["state"] == "PASS" for value in leakage.values()) else "HOLD"
    report = {
        "schema": "NN_TEMPLATE_GENERALIZED_QUESTION_V1",
        "state": state,
        "question": " ".join(question_words) + "?",
        "template_id": args.template_id,
        "template_signature": template_payload["template_signature"],
        "grounded_response_sentence_id": None if response is None else str(response["neuron_id"]),
        "grounded_response": None if response is None else " ".join(response_surface) + ".",
        "truth_answer_available": not structural_only,
        "capability_gate": capability_gate,
        "slot_binding_audit": permutation_audit,
        "future_question_fact_used": False,
        "target_answer_uploaded_to_cuda": False,
        "hydra_route_membrane": hydra_metrics,
        "result": result,
        "graph_audit": audit,
        "leakage_audit": leakage,
        "persistent_hashes_before": before,
        "persistent_hashes_after": after,
        "canonical_mutation_authorized": False,
        "promotion_performed": False,
        "deployment_performed": False,
    }
    report_path = args.report.resolve()
    if report_path.exists():
        raise FileExistsError("generalization report is append-only")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if state == "PASS" else 2


def command_learn_binary_relation(args: argparse.Namespace) -> int:
    """Learn an answerable Q1 question and a one-neuron yes/no response."""

    from .leakage_audit import audit_gpu_payload
    from .steel_brain_store import SQLiteNeuronGraphStore

    graph_path = args.graph.resolve()
    curriculum_path = args.curriculum_db.resolve()
    dictionary_path = args.dictionary.resolve()
    teacher_path = args.teacher.resolve()
    teacher = json.loads(teacher_path.read_text(encoding="utf-8"))
    dictionary_raw = dictionary_path.read_bytes()
    dictionary_sha256 = hashlib.sha256(dictionary_raw).hexdigest().upper()
    if teacher.get("schema") != "NN_CPU_PRIVATE_BINARY_RELATIONS_V1":
        raise ValueError("unsupported binary relation teacher schema")
    if str(teacher.get("dictionary_sha256")) != dictionary_sha256:
        raise ValueError("binary relation teacher does not match Webster")
    facts = {str(item["fact_id"]): item for item in teacher.get("facts", ())}
    if args.fact_id not in facts:
        raise ValueError("unknown binary relation fact")
    fact = facts[args.fact_id]
    if not isinstance(fact.get("truth"), bool):
        raise ValueError("binary relation learning requires an explicit CPU truth bit")
    question_words = tuple(str(value).lower() for value in fact["question_surface"])
    if len(question_words) not in {3, 4}:
        raise ValueError("binary relation paper shack requires three- or four-word questions")
    definition_evidence = [str(value) for value in fact["definition_row_sha256"]]
    dictionary_rows = json.loads(dictionary_raw.decode("utf-8"))
    observed_hashes = {
        hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest().upper()
        for row in dictionary_rows
        if str(row.get("word", "")).strip().lower() in set(question_words)
    }
    if any(value not in observed_hashes for value in definition_evidence):
        raise ValueError("binary relation references stale Webster evidence")
    before = {"graph": _persistent_sqlite_hashes(graph_path), "curriculum": _persistent_sqlite_hashes(curriculum_path)}
    with SQLiteNeuronGraphStore(graph_path) as store:
        manifest = store.manifest()
        question_ids = tuple(str(manifest["word_index"].get(word, "")) for word in question_words)
        answer_ids = tuple(str(manifest["word_index"].get(word, "")) for word in ("yes", "no"))
        if any(not value for value in (*question_ids, *answer_ids)):
            raise ValueError("binary relation references an unadmitted word")
        question_family = str(fact.get("opaque_question_family", "Q1"))
        if question_family not in {"Q1", "Q2"}:
            raise ValueError("unsupported binary question family")
        if args.template_id:
            template = store.load_neuron(args.template_id)
            template_payload = template.get("center_attractor", {}).get("opaque_interrogative_template_v1")
            if template.get("kind") != "CONCEPT" or not isinstance(template_payload, dict) or template_payload.get("question_family") != question_family:
                raise ValueError("binary relation template family mismatch")
            constants = {int(position): str(value) for position, value in template_payload["constant_question_positions"].items()}
            if any(question_ids[position] != value for position, value in constants.items()):
                raise ValueError("binary question does not match template constants")
            question_anchor_channels = tuple(str(value) for value in template_payload["question_anchor_channels"])
        else:
            question_anchor_channels = tuple(str(value) for value in fact.get("grammar_channels", ()))
            if question_family != "Q2" or len(question_anchor_channels) != len(question_words):
                raise ValueError("direct binary learning requires complete Q2 grammar channels")
        stable_question: dict[str, Any] | None = None
        for neuron_id, summary in manifest.get("neuron_index", {}).items():
            if summary.get("kind") != "SENTENCE":
                continue
            candidate = store.load_neuron(str(neuron_id))
            center = candidate.get("center_attractor", {})
            if candidate.get("lifecycle") == "STABLE" and center.get("trusted_language_memory") is True and center.get("opaque_utterance_mode_v1") == "U1" and tuple(str(value) for value in center.get("construction", ())) == question_ids:
                stable_question = candidate
                break
        question_context = hashlib.sha256((Neuronizer._inventory_signature(question_ids) + "\0U1\0" + question_family).encode("utf-8")).hexdigest().upper()
        source_handle = hashlib.sha256(json.dumps(fact, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest().upper()
        with CurriculumStore(curriculum_path) as curriculum:
            question_membrane = HydraRouteMembrane(curriculum, args.hydra_bin.resolve(), args.question_hydra_trace.resolve(), evidence_level="SENTENCE")
            engine = Neuronizer(store, CudaLibrary(), route_truth_provider=question_membrane)
            if stable_question is None:
                def question_judge(candidate: Sequence[str]) -> dict[str, Any]:
                    words = tuple(str(value).lower().removeprefix("word:") for value in candidate)
                    structural = words == question_words
                    return {"grammar": structural, "meaning": structural, "truth": structural}

                question_result = engine.learn_generated_sentence_episode(
                    [f"WORD:{word}" for word in question_words], question_judge,
                    seed=args.seed, source_handle=source_handle,
                    definition_evidence_sha256=definition_evidence,
                    max_attempts=args.max_attempts, required_confirmations=args.confirmations,
                    trace_path=args.question_trace.resolve(), route_truth_context=question_context,
                    route_truth_evidence_writer=lambda route, passed: curriculum.apply_assembly_verdict(level="SENTENCE", inventory_context_sha256=question_context, route=route, passed=passed),
                    activation_anchors=tuple({"grammar": value} for value in question_anchor_channels),
                    utterance_mode="U1", question_family=question_family,
                )
                if question_result.get("state") == "PASS":
                    stable_question = store.load_neuron(str(question_result["sentence_id"]))
            else:
                question_result = {
                    "state": "PASS", "sentence_id": str(stable_question["neuron_id"]),
                    "construction": [f"WORD:{word}" for word in question_words],
                    "attempts": 0,
                    "confirmation_passes": int(stable_question["activation"].get("confirmation_passes", 0)),
                    "reused_admitted_question": True,
                }
            question_metrics = question_membrane.metrics()
            answer_result: dict[str, Any] = {"state": "HOLD", "reason": "QUESTION_NOT_ADMITTED"}
            answer_metrics: dict[str, Any] = {"enabled": False}
            if stable_question is not None:
                answer_context = hashlib.sha256((str(stable_question["neuron_id"]) + "\0B0").encode("utf-8")).hexdigest().upper()
                answer_membrane = HydraRouteMembrane(curriculum, args.hydra_bin.resolve(), args.answer_hydra_trace.resolve(), evidence_level="ANSWER")
                answer_engine = Neuronizer(store, CudaLibrary(), route_truth_provider=answer_membrane)
                expected_answer = "yes" if bool(fact["truth"]) else "no"
                answer_result = answer_engine.learn_binary_answer_episode(
                    str(stable_question["neuron_id"]), ("WORD:yes", "WORD:no"),
                    lambda selected: selected == expected_answer,
                    seed=args.seed + 500_000_003, max_attempts=32,
                    required_confirmations=args.confirmations,
                    confirmation_seed_mode=getattr(args, "confirmation_seed_mode", "nearby"),
                    consolidate_confirmations=getattr(args, "consolidate_confirmations", False),
                    trace_path=args.answer_trace.resolve(), route_truth_context=answer_context,
                    route_truth_evidence_writer=lambda route, passed: curriculum.apply_assembly_verdict(level="ANSWER", inventory_context_sha256=answer_context, route=route, passed=passed),
                )
                answer_metrics = answer_membrane.metrics()
        audit = store.audit()
        changed_ids = {str(question_result.get("sentence_id", "")), *question_ids, *answer_ids}
        leakage = {neuron_id: audit_gpu_payload(store.load_neuron(neuron_id)) for neuron_id in sorted(changed_ids) if neuron_id}
    after = {"graph": _persistent_sqlite_hashes(graph_path), "curriculum": _persistent_sqlite_hashes(curriculum_path)}
    state = "PASS" if question_result.get("state") == "PASS" and answer_result.get("state") == "PASS" and audit.get("state") == "PASS" and all(item.get("state") == "PASS" for item in leakage.values()) else "HOLD"
    report = {
        "schema": "NN_BINARY_RELATION_LEARNING_REPORT_V1", "state": state,
        "fact_id": args.fact_id, "question": " ".join(question_words) + "?",
        "closed_relation": teacher.get("closed_relation"),
        "question_family": question_family,
        "question_result": question_result, "answer_result": answer_result,
        "question_hydra": question_metrics, "answer_hydra": answer_metrics,
        "cpu_truth_bit_hidden_from_gpu": True, "target_answer_uploaded_to_cuda": False,
        "graph_audit": audit, "leakage_audit": leakage,
        "persistent_hashes_before": before, "persistent_hashes_after": after,
        "canonical_mutation_authorized": False, "promotion_performed": False, "deployment_performed": False,
    }
    output_path = args.report.resolve()
    if output_path.exists():
        raise FileExistsError("binary relation report is append-only")
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if state == "PASS" else 2


def command_run_binary_conversation(args: argparse.Namespace) -> int:
    """Run a bounded read-only yes/no conversation from learned relation memory."""

    from .steel_brain_store import SQLiteNeuronGraphStore

    graph_path = args.graph.resolve()
    curriculum_path = args.curriculum_db.resolve()
    teacher = json.loads(args.teacher.resolve().read_text(encoding="utf-8"))
    if teacher.get("schema") != "NN_CPU_PRIVATE_BINARY_RELATIONS_V1":
        raise ValueError("unsupported binary relation teacher schema")
    facts = {
        " ".join(str(value).lower() for value in item["question_surface"]): item
        for item in teacher.get("facts", ())
    }
    receipts: dict[str, tuple[dict[str, Any], Path]] = {}
    for value in args.learning_receipt:
        path = Path(value).resolve()
        receipt = json.loads(path.read_text(encoding="utf-8"))
        answer_hydra = receipt.get("answer_hydra", {})
        if receipt.get("state") != "PASS" or receipt.get("schema") != "NN_BINARY_RELATION_LEARNING_REPORT_V1" or answer_hydra.get("enabled") is not True:
            raise ValueError(f"invalid binary relation receipt: {path}")
        receipts[str(receipt["fact_id"])] = (receipt, path)
    raw_turns = [value.strip() for value in args.turns.split("|") if value.strip()]
    if not raw_turns or len(raw_turns) > args.max_turns:
        raise ValueError("binary conversation turn count is outside its bound")
    before = {"graph": _persistent_sqlite_hashes(graph_path), "curriculum": _persistent_sqlite_hashes(curriculum_path)}
    turns: list[dict[str, Any]] = []
    boundary_turns: list[dict[str, Any]] = []
    session_number = 1
    current_q2_subject: str | None = None
    current_q2_question: str | None = None
    q2_context_candidates: list[str] = []
    pending_context_question: str | None = None
    pending_context_candidates: list[str] = []
    context_cap = max(1, int(getattr(args, "context_cap", 4)))
    context_evictions: list[str] = []
    with SQLiteNeuronGraphStore(graph_path, readonly=True) as store:
        engine = Neuronizer(store, CudaLibrary())
        manifest = store.manifest()
        stable_question_by_route: dict[tuple[str, ...], str] = {}
        for neuron_id, summary in manifest.get("neuron_index", {}).items():
            if summary.get("kind") != "SENTENCE":
                continue
            neuron = store.load_neuron(str(neuron_id))
            center = neuron.get("center_attractor", {})
            if (
                neuron.get("lifecycle") == "STABLE"
                and center.get("trusted_language_memory") is True
                and center.get("opaque_utterance_mode_v1") == "U1"
            ):
                stable_question_by_route[
                    tuple(str(value) for value in center.get("construction", ()))
                ] = str(neuron_id)
        for turn_number, raw_text in enumerate(raw_turns, 1):
            if raw_text.upper() == "RESET":
                current_q2_subject = None
                current_q2_question = None
                q2_context_candidates.clear()
                pending_context_question = None
                pending_context_candidates.clear()
                session_number += 1
                row = {
                    "turn": turn_number, "session": session_number,
                    "input": "RESET", "state": "SESSION_RESET",
                    "context_persisted": False, "write_performed": False,
                }
                turns.append(row)
                boundary_turns.append({
                    "turn": turn_number, "session": session_number,
                    "state": "SESSION_RESET", "gates": {},
                })
                continue
            question = " ".join(raw_text.strip().lower().rstrip("?.!").split())
            question_parts = question.split()
            clarification_input: str | None = None
            disambiguated = False
            forced_context: list[str] = []
            if pending_context_question is not None and len(question_parts) == 1:
                clarification_input = question_parts[0]
                subject_matches = [
                    candidate for candidate in pending_context_candidates
                    if candidate.split()[1] == clarification_input
                ]
                if len(subject_matches) == 1:
                    question = pending_context_question
                    question_parts = question.split()
                    disambiguated = True
                    forced_context = subject_matches
                    pending_context_question = None
                    pending_context_candidates.clear()
                else:
                    base = {"turn": turn_number, "session": session_number, "input": raw_text, "write_performed": False}
                    row = {
                        **base, "state": "HOLD_DISAMBIGUATION_INVALID",
                        "clarification_action": {
                            "state": "REQUEST_DISAMBIGUATION",
                            "question": pending_context_question + "?",
                            "generated_utterance": False,
                        },
                        "gates": {
                            "grammar": "HOLD", "meaning": "HOLD", "truth": "HOLD",
                            "context": "HOLD", "authority": "PASS_NO_AUTHORITY",
                        },
                    }
                    turns.append(row)
                    boundary_turns.append({"turn": turn_number, "session": session_number, "state": row["state"], "gates": row["gates"]})
                    continue
            subject_contextual = (
                len(question_parts) == 4
                and question_parts[0] == "do"
                and question_parts[1] == "they"
            )
            elliptical = question_parts == ["do", "they"]
            contextual = subject_contextual or elliptical or disambiguated
            compatible_context = (
                forced_context if disambiguated else [
                    candidate for candidate in q2_context_candidates
                    if candidate.split()[2:] == question_parts[2:]
                ]
                if subject_contextual else list(q2_context_candidates)
                if elliptical else []
            )
            if contextual and not compatible_context:
                base = {"turn": turn_number, "session": session_number, "input": raw_text, "write_performed": False}
                row = {
                    **base, "state": "HOLD_CONTEXT_EMPTY",
                    "question": question + "?",
                    "clarification_action": {
                        "state": "REQUEST_CONTEXT",
                        "question": question + "?",
                        "generated_utterance": False,
                    },
                    "gates": {
                        "grammar": "PASS", "meaning": "HOLD", "truth": "HOLD",
                        "context": "HOLD", "authority": "PASS_NO_AUTHORITY",
                    },
                }
                turns.append(row)
                boundary_turns.append({"turn": turn_number, "session": session_number, "state": row["state"], "gates": row["gates"]})
                continue
            if contextual and len(compatible_context) > 1:
                base = {"turn": turn_number, "session": session_number, "input": raw_text, "write_performed": False}
                row = {
                    **base, "state": "HOLD_CONTEXT_AMBIGUOUS",
                    "question": question + "?",
                    "compatible_context_count": len(compatible_context),
                    "clarification_action": {
                        "state": "REQUEST_DISAMBIGUATION",
                        "question": question + "?",
                        "generated_utterance": False,
                    },
                    "gates": {
                        "grammar": "PASS", "meaning": "HOLD", "truth": "HOLD",
                        "context": "HOLD", "authority": "PASS_NO_AUTHORITY",
                    },
                }
                turns.append(row)
                pending_context_question = question
                pending_context_candidates = list(compatible_context)
                boundary_turns.append({"turn": turn_number, "session": session_number, "state": row["state"], "gates": row["gates"]})
                continue
            resolved_question = (
                compatible_context[0]
                if contextual
                else question
            )
            fact = facts.get(resolved_question)
            base = {"turn": turn_number, "session": session_number, "input": raw_text, "write_performed": False}
            if fact is None or str(fact["fact_id"]) not in receipts:
                question_route = tuple(
                    str(manifest["word_index"].get(word, ""))
                    for word in question.split()
                )
                learned_question_id = stable_question_by_route.get(question_route)
                learned_structure = (
                    learned_question_id is not None
                    and fact is not None
                    and fact.get("opaque_question_family") == "Q2"
                )
                row = {
                    **base,
                    "state": (
                        "HOLD_UNGROUNDED_ANSWER"
                        if learned_structure
                        else "HOLD_UNSUPPORTED_QUESTION"
                    ),
                    **(
                        {
                            "question": question + "?",
                            "question_sentence_id": learned_question_id,
                            "question_word_route": question.split(),
                            "context_source": "LEARNED_QUESTION_STRUCTURE",
                        }
                        if learned_structure
                        else {}
                    ),
                    "clarification_action": {
                        "state": "REQUEST_TEACHING",
                        "question": question + "?",
                        "expected_teaching_shape": (
                            "SUBJECT VERB OBJECT"
                            if fact is not None and fact.get("opaque_question_family") == "Q2"
                            else "SUBJECT IS CLASS"
                        ),
                        "generated_utterance": False,
                    },
                    "gates": {
                        "grammar": "PASS" if learned_structure else "HOLD",
                        "meaning": "PASS" if learned_structure else "HOLD",
                        "truth": "HOLD",
                        "context": "NOT_REQUIRED",
                        "authority": "PASS_NO_AUTHORITY",
                    },
                }
                turns.append(row)
                boundary_turns.append({"turn": turn_number, "session": 1, "state": row["state"], "gates": row["gates"]})
                continue
            receipt, receipt_path = receipts[str(fact["fact_id"])]
            question_id = str(receipt["question_result"]["sentence_id"])
            answer_id = str(receipt["answer_result"]["answer_neuron_id"])
            expected = "yes" if bool(fact["truth"]) else "no"
            counts = engine.sample_binary_answer_distribution(
                question_id,
                seeds=tuple(
                    args.seed + turn_number * 1_000_003 + confirmation * 97_409
                    for confirmation in range(args.confirmations)
                ),
            )
            if counts != {expected: args.confirmations}:
                row = {**base, "state": "HOLD_BINARY_ANSWER_RECALL", "raw_answer_recall": counts, "gates": {"grammar": "PASS", "meaning": "PASS", "truth": "HOLD", "context": "NOT_REQUIRED", "authority": "PASS_NO_AUTHORITY"}}
                turns.append(row)
                boundary_turns.append({"turn": turn_number, "session": 1, "state": row["state"], "gates": row["gates"]})
                continue
            answer_hydra_path = Path(str(receipt["answer_hydra"]["trace"])).resolve()
            row = {
                **base, "state": "PASS_GROUNDED_RESPONSE",
                "question": question + "?", "response": expected + ".",
                "question_sentence_id": question_id, "response_sentence_id": answer_id,
                "question_word_route": resolved_question.split(), "response_word_route": [expected],
                "raw_answer_recall": counts,
                "context_source": "K0_DISAMBIGUATED_SUBJECT" if disambiguated else "K0_EPHEMERAL_Q2_ELLIPSIS" if elliptical else "K0_EPHEMERAL_SUBJECT" if subject_contextual else "LEARNED_BINARY_RELATION",
                **({"resolved_question": resolved_question + "?"} if contextual else {}),
                **({"clarification_input": clarification_input} if clarification_input else {}),
                "gates": {"grammar": "PASS", "meaning": "PASS", "truth": "PASS", "context": "PASS" if contextual else "NOT_REQUIRED", "authority": "PASS_NO_AUTHORITY"},
                "rust_hydra_receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest().upper(),
                "target_answer_uploaded_to_cuda": False,
            }
            turns.append(row)
            if not contextual and fact.get("opaque_question_family") == "Q2":
                current_q2_subject = str(fact["question_surface"][1]).lower()
                current_q2_question = resolved_question
                if resolved_question not in q2_context_candidates:
                    q2_context_candidates.append(resolved_question)
                    while len(q2_context_candidates) > context_cap:
                        context_evictions.append(q2_context_candidates.pop(0))
            boundary_turns.append({
                "turn": turn_number, "session": session_number, "state": row["state"], "gates": row["gates"],
                "utterance_packet": {
                    "schema_version": "steel_brain_grounded_utterance_packet_v1",
                    "candidate_only": True, "external_effects": False,
                    "question": row["question"], "question_word_route": row["question_word_route"],
                    "response": row["response"], "response_word_route": row["response_word_route"],
                    "question_sentence_id": question_id, "response_sentence_id": answer_id,
                    "gates": {"question_grammar": "PASS", "question_meaning": "PASS", "grounded_response_truth": "PASS", "authority": "PASS_NO_AUTHORITY"},
                    "route_gate": {"allowed": True, "local_text_only": True, "state": "PASS_RUST_HYDRA_ROUTE_GATE", "hydra_trace_sha256": hashlib.sha256(answer_hydra_path.read_bytes()).hexdigest().upper()},
                    "integrity": {}, "source_receipt": str(receipt_path),
                    "may_emit": False, "tool_authority": False, "memory_write": False,
                    **({
                        "context_resolution": {
                            "schema": "steel_brain_context_resolution_v1",
                            "kind": "K0_DISAMBIGUATED_SUBJECT" if disambiguated else "K0_Q2_ELLIPSIS" if elliptical else "K0_SUBJECT_PRONOUN",
                            "surface_pronoun": "they",
                            "resolved_question": row["resolved_question"],
                            "persisted": False,
                        }
                    } if contextual else {}),
                },
            })
        audit = store.audit()
    after = {"graph": _persistent_sqlite_hashes(graph_path), "curriculum": _persistent_sqlite_hashes(curriculum_path)}
    graph_sha = next(iter(after["graph"].values()))
    curriculum_sha = next(iter(after["curriculum"].values()))
    for boundary in boundary_turns:
        if "utterance_packet" in boundary:
            boundary["utterance_packet"]["integrity"] = {"graph_sha256": graph_sha, "curriculum_sha256": curriculum_sha}
    pass_rows = [row for row in turns if row["state"] == "PASS_GROUNDED_RESPONSE"]
    safe_holds = sum(row["state"] == "HOLD_UNSUPPORTED_QUESTION" for row in turns)
    context_passes = sum(str(row.get("context_source", "")).startswith("K0_") for row in pass_rows)
    context_empty_holds = sum(row["state"] == "HOLD_CONTEXT_EMPTY" for row in turns)
    context_ambiguous_holds = sum(row["state"] == "HOLD_CONTEXT_AMBIGUOUS" for row in turns)
    unchanged = before == after
    legacy_gate = len(pass_rows) >= 4 and {row["response"] for row in pass_rows} == {"yes.", "no."} and safe_holds >= 1
    context_gate = len(pass_rows) >= 2 and context_passes >= 1 and context_empty_holds >= 1
    state = "PASS" if (legacy_gate or context_gate) and unchanged and audit.get("state") == "PASS" else "HOLD"
    aios_packet = {
        "schema_version": "steel_brain_conversation_packet_v1", "candidate_only": True,
        "external_effects": False, "turns": boundary_turns,
        "context": {"owner": "CPU_SESSION_RAM", "persisted": False, "reset_supported": True, "max_entries": context_cap, "eviction_policy": "FIFO"},
        "integrity": {"graph_sha256": graph_sha, "curriculum_sha256": curriculum_sha},
        "may_emit": False, "tool_authority": False, "memory_write": False,
    }
    report = {
        "schema": "NN_BINARY_RELATION_CONVERSATION_V1", "state": state,
        "turns": turns,
        "summary": {"grounded_response_passes": len(pass_rows), "safe_holds": safe_holds, "yes_passes": sum(row.get("response") == "yes." for row in pass_rows), "no_passes": sum(row.get("response") == "no." for row in pass_rows), "context_followup_passes": context_passes, "fresh_session_context_holds": context_empty_holds, "ambiguous_context_holds": context_ambiguous_holds, "context_evictions": len(context_evictions)},
        "context_evictions": context_evictions,
        "aios_packet": aios_packet, "graph_audit": audit,
        "persistent_state_unchanged": unchanged,
        "persistent_hashes_before": before, "persistent_hashes_after": after,
        "candidate_only": True, "canonical_mutation_authorized": False,
        "promotion_performed": False, "deployment_performed": False,
    }
    output_path = args.output.resolve()
    if output_path.exists():
        raise FileExistsError("binary conversation receipt is append-only")
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if state == "PASS" else 2


def command_run_binary_teaching_session(args: argparse.Namespace) -> int:
    """Run one bounded unknown -> teach -> grounded binary conversation."""

    teacher_path = args.teacher.resolve()
    teacher = json.loads(teacher_path.read_text(encoding="utf-8"))
    if teacher.get("schema") != "NN_CPU_PRIVATE_BINARY_RELATIONS_V1":
        raise ValueError("unsupported binary relation teacher schema")
    facts = {str(item["fact_id"]): item for item in teacher.get("facts", ())}
    fact = facts.get(args.fact_id)
    if fact is None or not isinstance(fact.get("truth"), bool):
        raise ValueError("teaching session requires one explicit CPU truth fact")
    expected_answer = "yes" if fact["truth"] else "no"
    if args.teaching_answer.lower() != expected_answer:
        raise ValueError("teaching answer does not match the CPU-private truth contract")
    question = " ".join(str(value).lower() for value in fact["question_surface"]) + "?"
    evidence_dir = args.evidence_dir.resolve()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "pre": evidence_dir / "pre_teaching_conversation.json",
        "learning": evidence_dir / "truth_lesson_report.json",
        "post": evidence_dir / "post_teaching_conversation.json",
        "question_trace": evidence_dir / "question_reuse.jsonl",
        "answer_trace": evidence_dir / "answer_learning.jsonl",
        "question_hydra": evidence_dir / "question_hydra.jsonl",
        "answer_hydra": evidence_dir / "answer_hydra.jsonl",
    }
    if args.output.resolve().exists() or any(path.exists() for path in paths.values()):
        raise FileExistsError("binary teaching session evidence is append-only")
    before = {
        "graph": _persistent_sqlite_hashes(args.graph.resolve()),
        "curriculum": _persistent_sqlite_hashes(args.curriculum_db.resolve()),
    }
    with contextlib.redirect_stdout(io.StringIO()):
        pre_code = command_run_binary_conversation(argparse.Namespace(
            teacher=teacher_path, learning_receipt=[], graph=args.graph,
            curriculum_db=args.curriculum_db, turns=question,
            output=paths["pre"], seed=args.seed, max_turns=2,
            confirmations=args.confirmations,
        ))
        learn_code = command_learn_binary_relation(argparse.Namespace(
            dictionary=args.dictionary, teacher=teacher_path,
            fact_id=args.fact_id, template_id=None, graph=args.graph,
            curriculum_db=args.curriculum_db,
            question_trace=paths["question_trace"],
            answer_trace=paths["answer_trace"],
            question_hydra_trace=paths["question_hydra"],
            answer_hydra_trace=paths["answer_hydra"],
            hydra_bin=args.hydra_bin, report=paths["learning"],
            seed=args.seed + 1_000_003, max_attempts=args.max_attempts,
            confirmations=args.confirmations,
            confirmation_seed_mode=getattr(args, "confirmation_seed_mode", "nearby"),
            consolidate_confirmations=getattr(args, "consolidate_confirmations", False),
        ))
        post_code = command_run_binary_conversation(argparse.Namespace(
            teacher=teacher_path, learning_receipt=[str(paths["learning"])],
            graph=args.graph, curriculum_db=args.curriculum_db,
            turns=question, output=paths["post"],
            seed=args.seed + 2_000_006, max_turns=2,
            confirmations=args.confirmations,
        ))
    pre = json.loads(paths["pre"].read_text(encoding="utf-8"))
    learning = json.loads(paths["learning"].read_text(encoding="utf-8"))
    post = json.loads(paths["post"].read_text(encoding="utf-8"))
    pre_turn = pre["turns"][0]
    post_turn = post["turns"][0]
    pre_state = pre_turn.get("state")
    pre_safe_unknown = (
        pre_state == "HOLD_UNGROUNDED_ANSWER"
        and pre_turn.get("gates", {}).get("grammar") == "PASS"
        and pre_turn.get("gates", {}).get("meaning") == "PASS"
        and pre_turn.get("gates", {}).get("truth") == "HOLD"
    ) or (
        pre_state == "HOLD_UNSUPPORTED_QUESTION"
        and pre_turn.get("gates", {}).get("truth") == "HOLD"
        and pre_turn.get("clarification_action", {}).get("state") == "REQUEST_TEACHING"
    )
    question_result = learning.get("question_result", {})
    question_is_reused = question_result.get("reused_admitted_question") is True
    question_confirmation_gate = (
        int(question_result.get("confirmation_passes", 0)) >= 3
        if question_is_reused
        else question_result.get("confirmation_passes") == args.confirmations
    )
    question_learned_or_reused = (
        question_result.get("state") == "PASS"
        and isinstance(question_result.get("sentence_id"), str)
        and bool(question_result.get("sentence_id"))
        and question_confirmation_gate
    )
    accepted = (
        pre_code == 2
        and pre_safe_unknown
        and learn_code == 0 and learning.get("state") == "PASS"
        and question_learned_or_reused
        and learning.get("answer_result", {}).get("answer") == expected_answer
        and post_turn.get("state") == "PASS_GROUNDED_RESPONSE"
        and post_turn.get("response") == expected_answer + "."
        and post_turn.get("raw_answer_recall") == {expected_answer: args.confirmations}
        and post.get("persistent_state_unchanged") is True
        and post.get("graph_audit", {}).get("state") == "PASS"
    )
    after = {
        "graph": _persistent_sqlite_hashes(args.graph.resolve()),
        "curriculum": _persistent_sqlite_hashes(args.curriculum_db.resolve()),
    }
    report = {
        "schema": "NN_BINARY_TEACHING_SESSION_V1",
        "state": "PASS" if accepted else "HOLD",
        "fact_id": args.fact_id,
        "turns": [
            {"speaker": "USER", "text": question},
            {"speaker": "VIV", "state": pre_turn.get("state"), "response": None, "clarification_action": pre_turn.get("clarification_action")},
            {"speaker": "CPU_TEACHER", "text": expected_answer + ".", "truth_contract_match": True},
            {"speaker": "USER", "text": question},
            {"speaker": "VIV", "state": post_turn.get("state"), "response": post_turn.get("response"), "raw_answer_recall": post_turn.get("raw_answer_recall")},
        ],
        "pre_teaching_boundary": pre_state,
        "question_learned_during_session": question_result.get("attempts", 0) > 0,
        "question_reused_without_relearning": learning.get("question_result", {}).get("attempts") == 0,
        "learning_receipt": str(paths["learning"]),
        "pre_teaching_receipt": str(paths["pre"]),
        "post_teaching_receipt": str(paths["post"]),
        "persistent_hashes_before": before,
        "persistent_hashes_after": after,
        "candidate_only": True,
        "canonical_mutation_authorized": False,
        "promotion_performed": False,
        "deployment_performed": False,
    }
    args.output.resolve().write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if accepted else 2


def command_extract_article_binary_lesson(args: argparse.Namespace) -> int:
    """Deterministically extract one CPU-private Q2 lesson from a frozen article.

    This intentionally supports only a small, auditable clause family.  It is
    an architecture proof for source -> fact extraction, not a general parser.
    """

    source_path = args.source.resolve()
    dictionary_path = args.dictionary.resolve()
    manifest_path = args.output_manifest.resolve()
    teacher_path = args.output_teacher.resolve()
    receipt_path = args.output_receipt.resolve()
    if any(path.exists() for path in (manifest_path, teacher_path, receipt_path)):
        raise FileExistsError("article extraction evidence is append-only")
    source_raw = source_path.read_bytes()
    source_sha256 = hashlib.sha256(source_raw).hexdigest().upper()
    source_text = source_raw.decode("utf-8")
    try:
        source_json = json.loads(source_text)
    except json.JSONDecodeError:
        source_json = None
    if isinstance(source_json, dict) and isinstance(source_json.get("extract"), str):
        clean_text = str(source_json["extract"])
        title = str(source_json.get("title") or args.title)
    else:
        clean_text = source_text
        title = str(args.title)
    clean_text = " ".join(clean_text.split())
    clean_text_sha256 = hashlib.sha256(clean_text.encode("utf-8")).hexdigest().upper()

    dictionary_raw = dictionary_path.read_bytes()
    dictionary_sha256 = hashlib.sha256(dictionary_raw).hexdigest().upper()
    dictionary_rows = json.loads(dictionary_raw.decode("utf-8"))
    rows_by_word: dict[str, list[dict[str, Any]]] = {}
    for row in dictionary_rows:
        word = str(row.get("word", "")).strip().lower()
        if word:
            rows_by_word.setdefault(word, []).append(row)

    def row_for(word: str, role: str) -> dict[str, Any] | None:
        rows = rows_by_word.get(word, ())
        if role == "noun":
            return next((row for row in rows if str(row.get("pos", "")).lower().startswith("n")), None)
        if role == "verb":
            return next((row for row in rows if str(row.get("pos", "")).lower().startswith("v")), None)
        return rows[0] if rows else None

    verb_map = {
        "is": "be", "are": "be", "was": "be", "were": "be",
        "has": "have", "have": "have", "had": "have",
        "eats": "eat", "eat": "eat", "feeds": "feed", "feed": "feed",
        "gives": "give", "give": "give", "provides": "give", "provide": "give",
        "kills": "kill", "kill": "kill", "needs": "need", "need": "need",
        "uses": "use", "use": "use", "loves": "love", "love": "love",
        "produces": "produce", "produce": "produce", "contains": "contain", "contain": "contain",
    }
    structural_words = {"a", "an", "the", "this", "that", "these", "those"}
    sentences = [value.strip() for value in re.split(r"(?<=[.!?])\s+", clean_text) if value.strip()]
    candidates: list[dict[str, Any]] = []
    selected: dict[str, Any] | None = None
    for sentence_index, sentence in enumerate(sentences, 1):
        words = tuple(re.findall(r"[A-Za-z]+", sentence.lower()))
        candidate: dict[str, Any] = {"sentence_index": sentence_index, "evidence": sentence, "state": "REJECT"}
        for verb_index, surface_verb in enumerate(words):
            base_verb = verb_map.get(surface_verb)
            if base_verb is None or row_for(base_verb, "verb") is None:
                continue
            subject = next((word for word in reversed(words[:verb_index]) if word not in structural_words and row_for(word, "noun") is not None), None)
            object_word = next((word for word in words[verb_index + 1:] if word not in structural_words and row_for(word, "noun") is not None), None)
            if subject is None or object_word is None or subject == object_word:
                continue
            question_surface = ["do", subject, base_verb, object_word]
            evidence_rows = [
                row_for("do", "verb") or row_for("do", "any"),
                row_for(subject, "noun"), row_for(base_verb, "verb"), row_for(object_word, "noun"),
            ]
            if any(row is None for row in evidence_rows):
                continue
            candidate.update({
                "state": "PASS_SUPPORTED_CLAUSE",
                "surface_verb": surface_verb,
                "question_surface": question_surface,
            })
            selected = {
                **candidate,
                "definition_row_sha256": [
                    hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest().upper()
                    for row in evidence_rows
                ],
            }
            break
        candidates.append(candidate)
        if selected is not None:
            break
    if selected is None:
        receipt = {
            "schema": "NN_CPU_ARTICLE_BINARY_EXTRACTION_V1", "state": "HOLD_NO_SUPPORTED_CLAUSE",
            "source_sha256": source_sha256, "clean_text_sha256": clean_text_sha256,
            "candidates": candidates, "writes_to_learner": 0,
        }
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return 2

    fact_id = "AUTO_ARTICLE_" + hashlib.sha256(
        (source_sha256 + "\0" + str(selected["sentence_index"]) + "\0" + " ".join(selected["question_surface"])).encode("utf-8")
    ).hexdigest().upper()[:24]
    fact = {
        "fact_id": fact_id,
        "question_surface": selected["question_surface"],
        "grammar_channels": ["R1", "R0", "R1", "R0"],
        "opaque_question_family": "Q2",
        "truth": True,
        "definition_row_sha256": selected["definition_row_sha256"],
    }
    teacher = {
        "schema": "NN_CPU_PRIVATE_BINARY_RELATIONS_V1",
        "dictionary_sha256": dictionary_sha256,
        "closed_relation": "R11_ACTION_SVO_BINARY",
        "facts": [fact],
    }
    manifest = {
        "schema": "NN_WIKIPEDIA_ARTICLE_LESSON_MANIFEST_V1",
        "candidate": str(args.candidate),
        "single_variable": "CPU extracts the first supported noun-verb-noun assertion without a hand-authored fact fixture",
        "normalization_note": "Q2 retains the Steel Brain internal base-verb surface.",
        "articles": [{
            "title": title,
            "snapshot": os.path.relpath(source_path, manifest_path.parent).replace("\\", "/"),
            "source_sha256": source_sha256,
            "clean_text_sha256": clean_text_sha256,
            "evidence": selected["evidence"],
            "normalized_fact_id": fact_id,
            "normalized_question": " ".join(selected["question_surface"]) + "?",
            "extraction_sentence_index": selected["sentence_index"],
        }],
        "candidate_only": True,
        "promotion_authorized": False,
        "deployment_authorized": False,
    }
    receipt = {
        "schema": "NN_CPU_ARTICLE_BINARY_EXTRACTION_V1", "state": "PASS",
        "source_sha256": source_sha256, "clean_text_sha256": clean_text_sha256,
        "dictionary_sha256": dictionary_sha256, "selected": selected,
        "fact_id": fact_id, "teacher": str(teacher_path), "manifest": str(manifest_path),
        "candidate_count_examined": len(candidates), "human_authored_fact_rows": 0,
        "gpu_used_for_extraction": False, "learner_write_performed": False,
    }
    for path, payload in ((teacher_path, teacher), (manifest_path, manifest), (receipt_path, receipt)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


def command_run_article_learning_session(args: argparse.Namespace) -> int:
    """Run encounter -> CPU word query -> neuron birth -> question regeneration.

    This is the core form of the Candidate 079 paper-shack pipeline.  Article
    provenance and CPU dictionary evidence are checked before any learning
    write.  A required surface absent from the CPU dictionary holds the whole
    lesson for human review.
    """

    from .steel_brain_store import SQLiteNeuronGraphStore

    output_path = args.output.resolve()
    evidence_dir = args.evidence_dir.resolve()
    if output_path.exists() or evidence_dir.exists():
        raise FileExistsError("article learning evidence is append-only")
    evidence_dir.mkdir(parents=True)

    dictionary_path = args.dictionary.resolve()
    dictionary_raw = dictionary_path.read_bytes()
    dictionary_sha256 = hashlib.sha256(dictionary_raw).hexdigest().upper()
    dictionary_rows = json.loads(dictionary_raw.decode("utf-8"))
    rows_by_word: dict[str, list[dict[str, Any]]] = {}
    for row in dictionary_rows:
        word = str(row.get("word", "")).strip().lower()
        if word:
            rows_by_word.setdefault(word, []).append(row)

    teacher_path = args.teacher.resolve()
    teacher = json.loads(teacher_path.read_text(encoding="utf-8"))
    if teacher.get("schema") != "NN_CPU_PRIVATE_BINARY_RELATIONS_V1":
        raise ValueError("unsupported article teacher schema")
    if str(teacher.get("dictionary_sha256")) != dictionary_sha256:
        raise ValueError("article teacher does not match the CPU dictionary")
    facts_by_id = {str(row["fact_id"]): row for row in teacher.get("facts", ())}
    fact_ids = tuple(dict.fromkeys(str(value) for value in args.fact_id))
    if not fact_ids or any(value not in facts_by_id for value in fact_ids):
        raise ValueError("article session requires known fact ids")
    facts = tuple(facts_by_id[value] for value in fact_ids)

    article_manifest_path = args.article_manifest.resolve()
    article_manifest_raw = article_manifest_path.read_bytes()
    article_manifest = json.loads(article_manifest_raw.decode("utf-8"))
    if article_manifest.get("schema") != "NN_WIKIPEDIA_ARTICLE_LESSON_MANIFEST_V1":
        raise ValueError("unsupported article manifest schema")
    article_fact_ids = {
        str(row.get("normalized_fact_id")) for row in article_manifest.get("articles", ())
    }
    if any(value not in article_fact_ids for value in fact_ids):
        raise ValueError("selected fact is not bound to the article manifest")
    article_sources: list[dict[str, object]] = []
    for row in article_manifest.get("articles", ()):
        if str(row.get("normalized_fact_id")) not in fact_ids:
            continue
        snapshot = (article_manifest_path.parent / str(row["snapshot"])).resolve()
        observed = hashlib.sha256(snapshot.read_bytes()).hexdigest().upper()
        if observed != str(row.get("source_sha256")):
            raise ValueError(f"article snapshot hash mismatch: {snapshot}")
        article_sources.append({
            "fact_id": str(row["normalized_fact_id"]),
            "snapshot": str(snapshot),
            "source_sha256": observed,
            "clean_text_sha256": str(row.get("clean_text_sha256", "")),
        })

    before = {
        "graph": _persistent_sqlite_hashes(args.graph.resolve()),
        "curriculum": _persistent_sqlite_hashes(args.curriculum_db.resolve()),
    }
    required_words = tuple(dict.fromkeys(
        str(word).lower()
        for fact in facts
        for word in fact.get("question_surface", ())
    ))
    with SQLiteNeuronGraphStore(args.graph.resolve(), readonly=True) as store:
        admitted_before = set(store.manifest()["word_index"])
    missing_words = tuple(word for word in required_words if word not in admitted_before)
    query_words = tuple(dict.fromkeys((*missing_words, *(str(v).lower() for v in args.probe_word))))
    word_queries = [
        {
            "word": word,
            "state": "PASS_WORD_QUERY" if word in rows_by_word else "HOLD_HUMAN_REVIEW",
            "neuron_birth_allowed": word in rows_by_word,
        }
        for word in query_words
    ]
    encounter_receipts: list[dict[str, object]] = []
    with contextlib.redirect_stdout(io.StringIO()):
        for index, fact in enumerate(facts, 1):
            question = " ".join(str(value).lower() for value in fact["question_surface"]) + "?"
            encounter_path = evidence_dir / f"encounter_{index:02d}.json"
            code = command_run_binary_conversation(argparse.Namespace(
                teacher=teacher_path, learning_receipt=[], graph=args.graph,
                curriculum_db=args.curriculum_db, turns=question,
                output=encounter_path, seed=args.seed + index,
                max_turns=1, confirmations=args.question_confirmations, context_cap=4,
            ))
            receipt = json.loads(encounter_path.read_text(encoding="utf-8"))
            turn = receipt["turns"][0]
            valid_hold = (
                code == 2 and receipt.get("state") == "HOLD"
                and turn.get("state") == "HOLD_UNSUPPORTED_QUESTION"
                and turn.get("write_performed") is False
                and turn.get("clarification_action", {}).get("state") == "REQUEST_TEACHING"
                and receipt.get("persistent_state_unchanged") is True
            )
            encounter_receipts.append({
                "fact_id": str(fact["fact_id"]), "path": str(encounter_path),
                "state": turn.get("state"), "valid_safe_hold": valid_hold,
            })
    if not all(bool(row["valid_safe_hold"]) for row in encounter_receipts):
        raise RuntimeError("article first encounter did not produce the required safe HOLD")

    # The unknown surface must first be encountered and safely held.  Only then
    # does the CPU teacher answer the word query.  An unknown required word
    # stops the lesson before neuron birth or any other persistent write.
    required_unknown = tuple(word for word in missing_words if word not in rows_by_word)
    review_inputs = (
        getattr(args, "human_review_request", None),
        getattr(args, "human_review_decision", None),
        getattr(args, "human_authorization_receipt", None),
    )
    if any(review_inputs) and not all(review_inputs):
        raise ValueError("human review request, decision, and authorization receipt are all required")
    approved_review: dict[str, Any] | None = None
    if required_unknown and all(review_inputs):
        request_path = Path(review_inputs[0]).resolve()
        decision_path = Path(review_inputs[1]).resolve()
        authorization_path = Path(review_inputs[2]).resolve()
        request_raw = request_path.read_bytes()
        decision_raw = decision_path.read_bytes()
        request = json.loads(request_raw.decode("utf-8"))
        decision = json.loads(decision_raw.decode("utf-8"))
        authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
        request_words = tuple(str(row.get("word", "")).lower() for row in request.get("required_unknown_words", ()))
        decision_words = tuple(str(row.get("word", "")).lower() for row in decision.get("words", ()))
        current_parent_values = {
            group: sorted(values.values()) for group, values in before.items()
        }
        request_parent_values = {
            group: sorted(values.values())
            for group, values in request.get("parent_persistent_hashes", {}).items()
        }
        request_sha256 = hashlib.sha256(request_raw).hexdigest().upper()
        decision_sha256 = hashlib.sha256(decision_raw).hexdigest().upper()
        required_factor_ids = {"architect_usb", "architect_voice", "architect_pattern"}
        if (
            request.get("schema") != "NN_HUMAN_WORD_REVIEW_REQUEST_V1"
            or request.get("state") != "PENDING_HUMAN_REVIEW"
            or request.get("action") != "ROUTE_COMMIT"
            or str(request.get("dictionary_sha256")) != dictionary_sha256
            or str(request.get("article_manifest_sha256")) != hashlib.sha256(article_manifest_raw).hexdigest().upper()
            or current_parent_values != request_parent_values
            or request_words != required_unknown
        ):
            raise ValueError("human review request does not bind the current held lesson")
        if (
            decision.get("schema") != "NN_HUMAN_WORD_REVIEW_DECISION_V1"
            or decision.get("state") != "PASS"
            or decision.get("decision") != "APPROVE"
            or decision.get("candidate_only") is not True
            or decision.get("promotion_performed") is not False
            or decision.get("deployment_performed") is not False
            or str(decision.get("review_request_sha256")) != request_sha256
            or decision_words != required_unknown
        ):
            raise ValueError("human review decision does not approve exactly the held words")
        if (
            authorization.get("schema") != "HYDRA_HUMAN_AUTHORIZATION_CONSUMPTION_RECEIPT_V1"
            or authorization.get("state") != "PASS"
            or authorization.get("action") != "ROUTE_COMMIT"
            or str(authorization.get("target_sha256")) != decision_sha256
            or set(authorization.get("factor_ids", ())) != required_factor_ids
            or authorization.get("replay_protected") is not True
        ):
            raise ValueError("Hydra did not authorize this exact human review decision")

        derived_rows: list[dict[str, Any]] = []
        for row in decision.get("words", ()):
            word = str(row["word"]).lower()
            base_word = str(row["base_word"]).lower()
            pos = str(row["pos"])
            if row.get("derivation") != "PLURAL_S" or word != base_word + "s":
                raise ValueError(f"unsupported reviewed derivation: {word}")
            if not any(str(base.get("pos")) == pos for base in rows_by_word.get(base_word, ())):
                raise ValueError(f"reviewed base word/POS is absent from CPU dictionary: {base_word}/{pos}")
            derived_rows.append({
                "pos": pos,
                "word": word.upper(),
                "definitions": [f"Plural of {base_word}."],
                "human_review_v1": {
                    "base_word": base_word,
                    "derivation": "PLURAL_S",
                    "review_request_sha256": request_sha256,
                    "review_decision_sha256": decision_sha256,
                    "authorization_receipt_sha256": hashlib.sha256(authorization_path.read_bytes()).hexdigest().upper(),
                },
            })
        dictionary_rows = [*dictionary_rows, *derived_rows]
        rows_by_word = {}
        for row in dictionary_rows:
            word = str(row.get("word", "")).strip().lower()
            if word:
                rows_by_word.setdefault(word, []).append(row)
        runtime_dictionary_path = evidence_dir / "human_review_extended_dictionary.json"
        runtime_dictionary_path.write_text(
            json.dumps(dictionary_rows, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
        )
        runtime_dictionary_sha256 = hashlib.sha256(runtime_dictionary_path.read_bytes()).hexdigest().upper()
        runtime_teacher = json.loads(json.dumps(teacher))
        runtime_teacher["dictionary_sha256"] = runtime_dictionary_sha256
        for fact in runtime_teacher.get("facts", ()):
            if str(fact.get("fact_id")) not in fact_ids:
                continue
            fact["definition_row_sha256"] = [
                hashlib.sha256(json.dumps(rows_by_word[str(word).lower()][0], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest().upper()
                for word in fact.get("question_surface", ())
            ]
        runtime_teacher_path = evidence_dir / "human_review_runtime_teacher.json"
        runtime_teacher_path.write_text(
            json.dumps(runtime_teacher, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        dictionary_path = runtime_dictionary_path
        dictionary_sha256 = runtime_dictionary_sha256
        teacher_path = runtime_teacher_path
        teacher = runtime_teacher
        facts_by_id = {str(row["fact_id"]): row for row in teacher.get("facts", ())}
        facts = tuple(facts_by_id[value] for value in fact_ids)
        word_queries = [
            {
                "word": word,
                "state": "PASS_HUMAN_REVIEW" if word in required_unknown else "PASS_WORD_QUERY",
                "neuron_birth_allowed": word in rows_by_word,
            }
            for word in query_words
        ]
        approved_review = {
            "request": str(request_path), "request_sha256": request_sha256,
            "decision": str(decision_path), "decision_sha256": decision_sha256,
            "authorization_receipt": str(authorization_path),
            "extended_dictionary": str(runtime_dictionary_path),
            "extended_dictionary_sha256": runtime_dictionary_sha256,
            "approved_words": list(required_unknown),
        }
        required_unknown = ()
    query_receipt = {
        "schema": "NN_CPU_WORD_QUERY_RECEIPT_V1",
        "dictionary_sha256": dictionary_sha256,
        "queries": word_queries,
        "required_unknown_words": list(required_unknown),
    }
    (evidence_dir / "cpu_word_query_receipt.json").write_text(
        json.dumps(query_receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if required_unknown:
        after_hold = {
            "graph": _persistent_sqlite_hashes(args.graph.resolve()),
            "curriculum": _persistent_sqlite_hashes(args.curriculum_db.resolve()),
        }
        if after_hold != before:
            raise RuntimeError("persistent state changed before human review HOLD")
        selected_manifest_rows = {
            str(row.get("normalized_fact_id")): row
            for row in article_manifest.get("articles", ())
            if str(row.get("normalized_fact_id")) in fact_ids
        }
        review_words = []
        for word in required_unknown:
            supporting_facts = [
                str(fact["fact_id"])
                for fact in facts
                if word in {str(value).lower() for value in fact.get("question_surface", ())}
            ]
            review_words.append({
                "word": word,
                "cpu_dictionary_state": "UNKNOWN",
                "neuron_birth_allowed": False,
                "supporting_facts": supporting_facts,
                "source_evidence": [
                    {
                        "fact_id": fact_id,
                        "evidence": str(selected_manifest_rows[fact_id].get("evidence", "")),
                        "source_sha256": str(selected_manifest_rows[fact_id].get("source_sha256", "")),
                        "clean_text_sha256": str(selected_manifest_rows[fact_id].get("clean_text_sha256", "")),
                    }
                    for fact_id in supporting_facts
                ],
            })
        review_request = {
            "schema": "NN_HUMAN_WORD_REVIEW_REQUEST_V1",
            "state": "PENDING_HUMAN_REVIEW",
            "action": "ROUTE_COMMIT",
            "dictionary_sha256": dictionary_sha256,
            "article_manifest_sha256": hashlib.sha256(article_manifest_raw).hexdigest().upper(),
            "parent_persistent_hashes": before,
            "required_unknown_words": review_words,
            "allowed_decisions": ["APPROVE", "REJECT"],
            "approval_scope": "WORD_NEURON_BIRTH_THEN_REGENERATE_BOUND_FACTS",
            "auto_apply": False,
            "candidate_only": True,
        }
        review_request_path = evidence_dir / "human_word_review_request.json"
        review_request_path.write_text(
            json.dumps(review_request, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        review_request_sha256 = hashlib.sha256(review_request_path.read_bytes()).hexdigest().upper()
        report = {
            "schema": "NN_ARTICLE_LEARNING_SESSION_V1",
            "state": "HOLD_HUMAN_REVIEW",
            "reason": "CPU_DICTIONARY_DOES_NOT_KNOW_REQUIRED_WORD",
            "required_unknown_words": list(required_unknown),
            "word_query_receipt": str(evidence_dir / "cpu_word_query_receipt.json"),
            "human_review_request": str(review_request_path),
            "human_review_request_sha256": review_request_sha256,
            "encounters": encounter_receipts,
            "persistent_hashes_before": before,
            "persistent_hashes_after": after_hold,
            "candidate_only": True,
            "promotion_performed": False,
            "deployment_performed": False,
        }
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2

    word_result: dict[str, object] = {"state": "PASS", "results": []}
    if missing_words:
        canonical_words = sorted(
            {
                str(row.get("word", "")).lower()
                for row in dictionary_rows
                if str(row.get("word", "")).isalpha()
                and str(row.get("word", "")).isascii()
            },
            key=lambda value: (len(value), value),
        )
        ranks = {word: index for index, word in enumerate(canonical_words, 1)}
        lessons = [
            {"rank": ranks[word], "word": word, "count": 1}
            for word in missing_words
        ]
        corpus_hash = hashlib.sha256(
            json.dumps(lessons, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest().upper()
        corpus = {
            "schema": "NN_BOOK_WORD_CORPUS_V1",
            "source": {"path": str(dictionary_path), "sha256": dictionary_sha256, "kind": "WEBSTER_DICTIONARY_HEADWORDS"},
            "corpus_sha256": corpus_hash,
            "ordering": "LENGTH_THEN_LEXICOGRAPHIC_SUBSET",
            "lessons": lessons,
            "synthetic_examples": 0,
        }
        corpus_path = evidence_dir / "queried_word_corpus.json"
        corpus_path.write_text(json.dumps(corpus, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        word_report_path = evidence_dir / "word_learning_report.json"
        with contextlib.redirect_stdout(io.StringIO()):
            word_code = command_learn_book(argparse.Namespace(
                corpus=corpus_path, graph=args.graph, curriculum_db=args.curriculum_db,
                trace=evidence_dir / "word_learning_trace.jsonl", limit=len(lessons),
                min_length=1, max_length=1_000_000, rehearse_learned=False,
                max_attempts=args.max_word_attempts, confirmations=args.word_confirmations,
                seed=args.seed + 100_000, live_render_delay_ms=0.0, status=None,
                heartbeat_seconds=1.0, min_free_gb=5.0, resource_governed=False,
                assembly_evidence=True, self_discovery=True, prefix_free_suffix=True,
                resource_slowdown_seconds=1.0, resource_max_seconds=3600.0,
                ram_reserve_gb=4.0, vram_reserve_mb=512.0,
                cpu_ceiling_percent=95.0, gpu_ceiling_percent=95.0,
                power_ceiling_percent=95.0, report=word_report_path,
                hydra_bin=None, hydra_trace=None,
            ))
        word_result = json.loads(word_report_path.read_text(encoding="utf-8"))
        if word_code != 0 or word_result.get("state") != "PASS":
            raise RuntimeError("CPU-approved article vocabulary did not learn")

    teaching_results: list[dict[str, object]] = []
    for index, fact in enumerate(facts, 1):
        teaching_path = evidence_dir / f"teaching_{index:02d}.json"
        with contextlib.redirect_stdout(io.StringIO()):
            code = command_run_binary_teaching_session(argparse.Namespace(
                dictionary=dictionary_path, teacher=teacher_path,
                fact_id=str(fact["fact_id"]), teaching_answer="yes" if fact["truth"] else "no",
                graph=args.graph, curriculum_db=args.curriculum_db,
                hydra_bin=args.hydra_bin, evidence_dir=evidence_dir / f"teaching_{index:02d}_evidence",
                output=teaching_path, seed=args.seed + 200_000 + index,
                max_attempts=args.max_question_attempts,
                confirmations=args.question_confirmations,
                confirmation_seed_mode="nearby", consolidate_confirmations=True,
            ))
        receipt = json.loads(teaching_path.read_text(encoding="utf-8"))
        teaching_results.append({
            "fact_id": str(fact["fact_id"]), "path": str(teaching_path),
            "state": receipt.get("state"),
            "question_learned_during_session": receipt.get("question_learned_during_session"),
        })
        if code != 0 or receipt.get("state") != "PASS":
            raise RuntimeError(f"article relation did not learn: {fact['fact_id']}")

    with SQLiteNeuronGraphStore(args.graph.resolve(), readonly=True) as store:
        manifest_after = store.manifest()
        audit = store.audit()
    admitted_after = set(manifest_after["word_index"])
    after = {
        "graph": _persistent_sqlite_hashes(args.graph.resolve()),
        "curriculum": _persistent_sqlite_hashes(args.curriculum_db.resolve()),
    }
    accepted = (
        all(word in admitted_after for word in missing_words)
        and all(str(value).lower() not in admitted_after for value in args.probe_word if str(value).lower() not in rows_by_word)
        and audit.get("state") == "PASS"
        and all(row["state"] == "PASS" for row in teaching_results)
    )
    report = {
        "schema": "NN_ARTICLE_LEARNING_SESSION_V1",
        "state": "PASS" if accepted else "HOLD",
        "article_manifest_sha256": hashlib.sha256(article_manifest_raw).hexdigest().upper(),
        "article_sources": article_sources,
        "fact_ids": list(fact_ids),
        "required_words": list(required_words),
        "missing_words_before": list(missing_words),
        "word_queries": word_queries,
        "human_review": approved_review,
        "encounters": encounter_receipts,
        "word_learning": word_result,
        "teaching_results": teaching_results,
        "graph_audit": audit,
        "persistent_hashes_before": before,
        "persistent_hashes_after": after,
        "candidate_only": True,
        "canonical_mutation_authorized": False,
        "promotion_performed": False,
        "deployment_performed": False,
    }
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if accepted else 2


def command_attach_article_provenance(args: argparse.Namespace) -> int:
    """Attach one receipt-backed article claim to every participating neuron.

    The payload is internal learned memory, not a CPU truth-store replacement.
    It records exactly where the relation came from and which role each neuron
    played.  Existing neurons grow metadata; no duplicate semantic neuron is
    born merely to hold provenance.
    """

    from .steel_brain_store import SQLiteNeuronGraphStore

    graph_path = args.graph.resolve()
    manifest_path = args.article_manifest.resolve()
    teacher_path = args.teacher.resolve()
    session_path = args.session_report.resolve()
    output_path = args.output.resolve()
    if output_path.exists():
        raise FileExistsError("article provenance receipt is append-only")

    manifest_raw = manifest_path.read_bytes()
    teacher_raw = teacher_path.read_bytes()
    session_raw = session_path.read_bytes()
    manifest = json.loads(manifest_raw.decode("utf-8"))
    teacher = json.loads(teacher_raw.decode("utf-8"))
    session = json.loads(session_raw.decode("utf-8"))
    if manifest.get("schema") != "NN_WIKIPEDIA_ARTICLE_LESSON_MANIFEST_V1":
        raise ValueError("unsupported article manifest schema")
    if teacher.get("schema") != "NN_CPU_PRIVATE_BINARY_RELATIONS_V1":
        raise ValueError("unsupported article teacher schema")
    if (
        session.get("schema") != "NN_ARTICLE_LEARNING_SESSION_V1"
        or session.get("state") != "PASS"
        or session.get("candidate_only") is not True
        or session.get("promotion_performed") is not False
        or session.get("deployment_performed") is not False
    ):
        raise ValueError("provenance requires one accepted candidate-only article session")
    manifest_sha256 = hashlib.sha256(manifest_raw).hexdigest().upper()
    if str(session.get("article_manifest_sha256")) != manifest_sha256:
        raise ValueError("session is not bound to this article manifest")

    def payload_sha256(value: object) -> str:
        raw = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest().upper()

    article_by_fact = {
        str(row["normalized_fact_id"]): row for row in manifest.get("articles", ())
    }
    fact_by_id = {str(row["fact_id"]): row for row in teacher.get("facts", ())}
    teaching_by_fact = {
        str(row["fact_id"]): row for row in session.get("teaching_results", ())
    }
    selected_fact_ids = tuple(str(value) for value in session.get("fact_ids", ()))
    if not selected_fact_ids or any(
        fact_id not in article_by_fact
        or fact_id not in fact_by_id
        or fact_id not in teaching_by_fact
        for fact_id in selected_fact_ids
    ):
        raise ValueError("session fact set is incomplete")

    word_episode_ids = {
        str(row["word"]).lower(): str(row["episode_neuron_id"])
        for row in session.get("word_learning", {}).get("results", ())
        if row.get("state") == "PASS" and row.get("episode_neuron_id")
    }
    before = _persistent_sqlite_hashes(graph_path)
    attachments: dict[str, dict[str, dict[str, object]]] = {}
    claim_summaries: list[dict[str, object]] = []

    with SQLiteNeuronGraphStore(graph_path) as store:
        graph_manifest = store.manifest()
        for fact_id in selected_fact_ids:
            article = article_by_fact[fact_id]
            fact = fact_by_id[fact_id]
            teaching_outer_path = Path(str(teaching_by_fact[fact_id]["path"])).resolve()
            teaching_outer_raw = teaching_outer_path.read_bytes()
            teaching_outer = json.loads(teaching_outer_raw.decode("utf-8"))
            if teaching_outer.get("state") != "PASS" or str(teaching_outer.get("fact_id")) != fact_id:
                raise ValueError(f"teaching receipt is not an accepted fact: {fact_id}")
            lesson_path = Path(str(teaching_outer["learning_receipt"])).resolve()
            lesson_raw = lesson_path.read_bytes()
            lesson = json.loads(lesson_raw.decode("utf-8"))
            if lesson.get("state") != "PASS" or str(lesson.get("fact_id")) != fact_id:
                raise ValueError(f"truth lesson is not an accepted fact: {fact_id}")

            snapshot_path = (manifest_path.parent / str(article["snapshot"])).resolve()
            snapshot_raw = snapshot_path.read_bytes()
            source_sha256 = hashlib.sha256(snapshot_raw).hexdigest().upper()
            if source_sha256 != str(article.get("source_sha256")):
                raise ValueError(f"article source hash mismatch: {fact_id}")
            source_locator = str(snapshot_path)
            try:
                snapshot_json = json.loads(snapshot_raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                snapshot_json = None
            if isinstance(snapshot_json, dict):
                source_locator = str(
                    snapshot_json.get("content_urls", {}).get("desktop", {}).get("page")
                    or snapshot_json.get("content_urls", {}).get("mobile", {}).get("page")
                    or snapshot_path
                )

            question = lesson.get("question_result", {})
            answer = lesson.get("answer_result", {})
            roles_by_neuron: dict[str, set[str]] = {}
            for word in (str(value).lower() for value in fact.get("question_surface", ())):
                neuron_id = graph_manifest.get("word_index", {}).get(word)
                if not neuron_id:
                    raise ValueError(f"learned claim has no WORD neuron: {word}")
                roles_by_neuron.setdefault(str(neuron_id), set()).add("CLAIM_WORD")
                if word in word_episode_ids:
                    roles_by_neuron.setdefault(word_episode_ids[word], set()).add(
                        "WORD_LEARNING_EPISODE"
                    )
            for field, role in (
                ("sentence_id", "CLAIM_QUESTION_SENTENCE"),
                ("episode_id", "CLAIM_QUESTION_EPISODE"),
            ):
                if question.get(field):
                    roles_by_neuron.setdefault(str(question[field]), set()).add(role)
            if answer.get("answer_neuron_id"):
                roles_by_neuron.setdefault(str(answer["answer_neuron_id"]), set()).add(
                    "CLAIM_ANSWER"
                )
            if not roles_by_neuron:
                raise ValueError(f"accepted fact has no participating neurons: {fact_id}")

            evidence_text = str(article.get("evidence", ""))
            claim_material = {
                "fact_id": fact_id,
                "question_surface": [str(value).lower() for value in fact.get("question_surface", ())],
                "truth": bool(fact.get("truth")),
                "source_sha256": source_sha256,
                "evidence_sha256": hashlib.sha256(evidence_text.encode("utf-8")).hexdigest().upper(),
            }
            claim_id = "CLAIM-" + payload_sha256(claim_material)[:32]
            peer_ids = sorted(roles_by_neuron)
            common = {
                "schema": "NN_NEURON_CLAIM_PROVENANCE_V1",
                "claim_id": claim_id,
                "claim_kind": "ARTICLE_BINARY_RELATION",
                "claim_payload_sha256": payload_sha256(fact),
                "fact_id": fact_id,
                "learned_state": "LEARNED_VERIFIED",
                "cpu_reference_state": "KNOWN_TRUE" if bool(fact.get("truth")) else "KNOWN_FALSE",
                "source_kind": "WIKIPEDIA_ARTICLE_SNAPSHOT",
                "source_title": str(article.get("title", "")),
                "source_locator": source_locator,
                "source_snapshot": str(snapshot_path),
                "source_sha256": source_sha256,
                "clean_text_sha256": str(article.get("clean_text_sha256", "")),
                "evidence_text": evidence_text,
                "evidence_sha256": claim_material["evidence_sha256"],
                "teacher_sha256": hashlib.sha256(teacher_raw).hexdigest().upper(),
                "dictionary_sha256": str(teacher.get("dictionary_sha256", "")),
                "article_manifest_sha256": manifest_sha256,
                "session_report_sha256": hashlib.sha256(session_raw).hexdigest().upper(),
                "teaching_receipt_sha256": hashlib.sha256(teaching_outer_raw).hexdigest().upper(),
                "truth_lesson_sha256": hashlib.sha256(lesson_raw).hexdigest().upper(),
                "see_also_neuron_ids": peer_ids,
                "history": [{
                    "revision": 1,
                    "state": "LEARNED_VERIFIED",
                    "evidence_sha256": claim_material["evidence_sha256"],
                }],
            }
            for neuron_id, roles in roles_by_neuron.items():
                entry = {**common, "neuron_roles": sorted(roles)}
                attachments.setdefault(neuron_id, {})[claim_id] = entry
            claim_summaries.append({
                "claim_id": claim_id,
                "fact_id": fact_id,
                "source_title": common["source_title"],
                "source_locator": source_locator,
                "participating_neuron_ids": peer_ids,
            })

        changed: list[dict[str, object]] = []
        for neuron_id, claims in sorted(attachments.items()):
            neuron = store.load_neuron(neuron_id)
            center = neuron.setdefault("center_attractor", {})
            existing = center.setdefault("claim_provenance_v1", [])
            if not isinstance(existing, list):
                raise ValueError(f"invalid provenance field on neuron: {neuron_id}")
            by_id = {
                str(row.get("claim_id")): row
                for row in existing
                if isinstance(row, dict) and row.get("claim_id")
            }
            for claim_id, entry in claims.items():
                if claim_id in by_id and by_id[claim_id] != entry:
                    raise ValueError(f"claim collision on neuron: {neuron_id}/{claim_id}")
                by_id[claim_id] = entry
            center["claim_provenance_v1"] = [by_id[key] for key in sorted(by_id)]
            neuron["updated_utc"] = utc_now()
            neuron["content_sha256"] = content_hash(neuron)
            changed.append(neuron)
        event_head = store.transact(
            changed,
            event_kind="NEURON_CLAIM_PROVENANCE_ATTACHED",
            details={
                "article_manifest_sha256": manifest_sha256,
                "session_report_sha256": hashlib.sha256(session_raw).hexdigest().upper(),
                "claim_ids": [str(row["claim_id"]) for row in claim_summaries],
                "changed_neuron_count": len(changed),
            },
        )
        audit = store.audit()

    after = _persistent_sqlite_hashes(graph_path)
    report = {
        "schema": "NN_ARTICLE_NEURON_PROVENANCE_RECEIPT_V1",
        "state": "PASS" if audit.get("state") == "PASS" else "HOLD",
        "claims": claim_summaries,
        "changed_neuron_count": len(attachments),
        "event_head": event_head,
        "graph_audit": audit,
        "persistent_hashes_before": before,
        "persistent_hashes_after": after,
        "candidate_only": True,
        "promotion_performed": False,
        "deployment_performed": False,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["state"] == "PASS" else 2


def command_attach_relation_provenance(args: argparse.Namespace) -> int:
    """Attach one CPU-teacher-backed binary claim inside its real neurons."""

    from .steel_brain_store import SQLiteNeuronGraphStore

    graph_path = args.graph.resolve()
    teacher_path = args.teacher.resolve()
    lesson_path = args.learning_receipt.resolve()
    output_path = args.output.resolve()
    if output_path.exists():
        raise FileExistsError("relation provenance receipt is append-only")

    teacher_raw = teacher_path.read_bytes()
    lesson_raw = lesson_path.read_bytes()
    teacher = json.loads(teacher_raw.decode("utf-8"))
    lesson = json.loads(lesson_raw.decode("utf-8"))
    if teacher.get("schema") != "NN_CPU_PRIVATE_BINARY_RELATIONS_V1":
        raise ValueError("unsupported binary relation teacher schema")
    if lesson.get("schema") != "NN_BINARY_RELATION_LEARNING_REPORT_V1" or lesson.get("state") != "PASS":
        raise ValueError("relation provenance requires one accepted truth lesson")
    fact_id = str(lesson.get("fact_id", ""))
    facts = {str(row.get("fact_id")): row for row in teacher.get("facts", ())}
    if fact_id not in facts:
        raise ValueError("truth lesson is not bound to this CPU teacher")
    fact = facts[fact_id]
    expected_answer = "yes" if bool(fact.get("truth")) else "no"
    if lesson.get("answer_result", {}).get("answer") != expected_answer:
        raise ValueError("truth lesson answer does not match CPU teacher")
    if lesson.get("cpu_truth_bit_hidden_from_gpu") is not True or lesson.get("target_answer_uploaded_to_cuda") is not False:
        raise ValueError("truth lesson lacks the required leakage boundary")

    teacher_sha256 = hashlib.sha256(teacher_raw).hexdigest().upper()
    lesson_sha256 = hashlib.sha256(lesson_raw).hexdigest().upper()
    question_words = tuple(str(value).lower() for value in fact.get("question_surface", ()))
    evidence_text = " ".join(question_words) + "? " + expected_answer + "."
    evidence_sha256 = hashlib.sha256(evidence_text.encode("utf-8")).hexdigest().upper()
    claim_material = {
        "fact_id": fact_id,
        "question_surface": list(question_words),
        "truth": bool(fact.get("truth")),
        "teacher_sha256": teacher_sha256,
        "truth_lesson_sha256": lesson_sha256,
    }
    claim_payload = json.dumps(
        claim_material, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    claim_id = "CLAIM-" + hashlib.sha256(claim_payload).hexdigest().upper()[:32]
    before = _persistent_sqlite_hashes(graph_path)

    with SQLiteNeuronGraphStore(graph_path) as store:
        manifest = store.manifest()
        roles_by_neuron: dict[str, set[str]] = {}
        for word in question_words:
            neuron_id = manifest.get("word_index", {}).get(word)
            if not neuron_id:
                raise ValueError(f"learned relation has no WORD neuron: {word}")
            roles_by_neuron.setdefault(str(neuron_id), set()).add("CLAIM_WORD")
        question = lesson.get("question_result", {})
        answer = lesson.get("answer_result", {})
        if question.get("sentence_id"):
            roles_by_neuron.setdefault(str(question["sentence_id"]), set()).add("CLAIM_QUESTION_SENTENCE")
        if question.get("episode_id"):
            roles_by_neuron.setdefault(str(question["episode_id"]), set()).add("CLAIM_QUESTION_EPISODE")
        if answer.get("answer_neuron_id"):
            roles_by_neuron.setdefault(str(answer["answer_neuron_id"]), set()).add("CLAIM_ANSWER")
        if not roles_by_neuron:
            raise ValueError("accepted relation has no participating neurons")

        peer_ids = sorted(roles_by_neuron)
        common = {
            "schema": "NN_NEURON_CLAIM_PROVENANCE_V1",
            "claim_id": claim_id,
            "claim_kind": "CPU_BINARY_RELATION",
            "claim_payload_sha256": hashlib.sha256(
                json.dumps(fact, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest().upper(),
            "fact_id": fact_id,
            "learned_state": "LEARNED_VERIFIED",
            "cpu_reference_state": "KNOWN_TRUE" if bool(fact.get("truth")) else "KNOWN_FALSE",
            "source_kind": "CPU_PRIVATE_RELATION_TEACHER",
            "source_title": str(args.source_title),
            "source_locator": str(teacher_path),
            "source_snapshot": str(teacher_path),
            "source_sha256": teacher_sha256,
            "evidence_text": evidence_text,
            "evidence_sha256": evidence_sha256,
            "teacher_sha256": teacher_sha256,
            "dictionary_sha256": str(teacher.get("dictionary_sha256", "")),
            "truth_lesson_sha256": lesson_sha256,
            "see_also_neuron_ids": peer_ids,
            "history": [{"revision": 1, "state": "LEARNED_VERIFIED", "evidence_sha256": evidence_sha256}],
        }
        changed: list[dict[str, object]] = []
        for neuron_id, roles in sorted(roles_by_neuron.items()):
            neuron = store.load_neuron(neuron_id)
            center = neuron.setdefault("center_attractor", {})
            existing = center.setdefault("claim_provenance_v1", [])
            if not isinstance(existing, list):
                raise ValueError(f"invalid provenance field on neuron: {neuron_id}")
            entry = {**common, "neuron_roles": sorted(roles)}
            by_id = {
                str(row.get("claim_id")): row for row in existing
                if isinstance(row, dict) and row.get("claim_id")
            }
            if claim_id in by_id and by_id[claim_id] != entry:
                raise ValueError(f"claim collision on neuron: {neuron_id}/{claim_id}")
            by_id[claim_id] = entry
            center["claim_provenance_v1"] = [by_id[key] for key in sorted(by_id)]
            neuron["updated_utc"] = utc_now()
            neuron["content_sha256"] = content_hash(neuron)
            changed.append(neuron)
        event_head = store.transact(
            changed,
            event_kind="NEURON_CLAIM_PROVENANCE_ATTACHED",
            details={
                "source_kind": "CPU_PRIVATE_RELATION_TEACHER",
                "teacher_sha256": teacher_sha256,
                "truth_lesson_sha256": lesson_sha256,
                "claim_ids": [claim_id],
                "changed_neuron_count": len(changed),
            },
        )
        audit = store.audit()

    after = _persistent_sqlite_hashes(graph_path)
    report = {
        "schema": "NN_RELATION_NEURON_PROVENANCE_RECEIPT_V1",
        "state": "PASS" if audit.get("state") == "PASS" else "HOLD",
        "claim_id": claim_id,
        "fact_id": fact_id,
        "source_title": str(args.source_title),
        "source_locator": str(teacher_path),
        "participating_neuron_ids": peer_ids,
        "changed_neuron_count": len(changed),
        "event_head": event_head,
        "graph_audit": audit,
        "persistent_hashes_before": before,
        "persistent_hashes_after": after,
        "candidate_only": True,
        "promotion_performed": False,
        "deployment_performed": False,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["state"] == "PASS" else 2


def command_query_neuron_source(args: argparse.Namespace) -> int:
    """Read provenance already inside a neuron; never infer a missing source."""

    from .steel_brain_store import SQLiteNeuronGraphStore

    graph_path = args.graph.resolve()
    output_path = args.output.resolve()
    if output_path.exists():
        raise FileExistsError("source-query receipt is append-only")
    before = _persistent_sqlite_hashes(graph_path)
    with SQLiteNeuronGraphStore(graph_path, readonly=True) as store:
        manifest = store.manifest()
        neuron_id = str(args.neuron_id or "")
        if args.surface:
            resolved = manifest.get("word_index", {}).get(str(args.surface).lower())
            if resolved is None:
                result = {
                    "schema": "NN_NEURON_SOURCE_QUERY_V1",
                    "state": "HOLD_UNKNOWN_NEURON",
                    "surface": str(args.surface).lower(),
                    "claims": [],
                }
                neuron = None
            else:
                neuron_id = str(resolved)
                neuron = store.load_neuron(neuron_id)
        else:
            try:
                neuron = store.load_neuron(neuron_id)
            except KeyError:
                neuron = None
                result = {
                    "schema": "NN_NEURON_SOURCE_QUERY_V1",
                    "state": "HOLD_UNKNOWN_NEURON",
                    "neuron_id": neuron_id,
                    "claims": [],
                }
        if neuron is not None:
            claims = neuron.get("center_attractor", {}).get("claim_provenance_v1", [])
            if not isinstance(claims, list) or not claims:
                result = {
                    "schema": "NN_NEURON_SOURCE_QUERY_V1",
                    "state": "HOLD_NO_RECORDED_SOURCE",
                    "neuron_id": neuron_id,
                    "kind": neuron.get("kind"),
                    "claims": [],
                }
            else:
                result = {
                    "schema": "NN_NEURON_SOURCE_QUERY_V1",
                    "state": "PASS",
                    "neuron_id": neuron_id,
                    "kind": neuron.get("kind"),
                    "claims": claims,
                }
        audit = store.audit()
    after = _persistent_sqlite_hashes(graph_path)
    if after != before:
        raise RuntimeError("read-only neuron source query changed persistent state")
    result.update({
        "graph_audit": audit,
        "persistent_state_unchanged": True,
        "persistent_hashes": before,
    })
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["state"] == "PASS" else 2


def _unquoted_phrase_index(text: str, phrase: str) -> int:
    """Return the first case-insensitive phrase occurrence outside quotes."""

    lowered = text.lower()
    target = phrase.lower()
    quote: str | None = None
    pairs = {'"': '"', '`': '`', '\u201c': '\u201d'}
    index = 0
    while index <= len(text) - len(target):
        character = text[index]
        if quote is None and character in pairs:
            quote = pairs[character]
            index += 1
            continue
        if quote is not None:
            if character == quote:
                quote = None
            index += 1
            continue
        if lowered.startswith(target, index):
            left_ok = index == 0 or not lowered[index - 1].isalnum()
            right = index + len(target)
            right_ok = right == len(text) or not lowered[right].isalnum()
            if left_ok and right_ok:
                return index
        index += 1
    return -1


def command_route_addressed_conversation(args: argparse.Namespace) -> int:
    """Separate ordinary conversation from addressed task proposals.

    The wake phrase changes routing intent only.  It never grants action,
    filesystem, tool, or security authority and this candidate command cannot
    execute a task.
    """

    graph_path = args.graph.resolve()
    curriculum_path = args.curriculum_db.resolve()
    output_path = args.output.resolve()
    if output_path.exists():
        raise FileExistsError("addressed-conversation receipt is append-only")
    raw_turns = [value.strip() for value in str(args.turns).split("|") if value.strip()]
    if not raw_turns or len(raw_turns) > int(args.max_turns):
        raise ValueError("addressed conversation turn count is outside its bound")
    before = {
        "graph": _persistent_sqlite_hashes(graph_path),
        "curriculum": _persistent_sqlite_hashes(curriculum_path),
    }
    trigger = "would you kindly"
    routed: list[dict[str, object]] = []
    task_requests = 0
    conversations = 0
    incomplete = 0
    for number, raw in enumerate(raw_turns, 1):
        phrase_index = _unquoted_phrase_index(raw, trigger)
        segments: list[dict[str, object]] = []
        if phrase_index < 0:
            conversations += 1
            segments.append({
                "kind": "CONVERSATION",
                "text": raw,
                "external_effects": False,
                "tool_authority": False,
            })
            state = "PASS_CONVERSATION"
        else:
            prefix = raw[:phrase_index].strip(" \t,;:-")
            request = raw[phrase_index + len(trigger):].strip(" \t,;:-")
            request = request.rstrip().rstrip("?!.").strip()
            if prefix:
                conversations += 1
                segments.append({
                    "kind": "CONVERSATION",
                    "text": prefix,
                    "external_effects": False,
                    "tool_authority": False,
                })
            if not request:
                incomplete += 1
                state = "HOLD_INCOMPLETE_TASK_REQUEST"
                segments.append({
                    "kind": "TASK_REQUEST",
                    "state": state,
                    "trigger": "WOULD_YOU_KINDLY",
                    "request": None,
                    "may_execute": False,
                    "authority": "ABSENT",
                })
            else:
                task_requests += 1
                state = "HOLD_TASK_AUTHORIZATION_REQUIRED"
                segments.append({
                    "kind": "TASK_REQUEST",
                    "state": state,
                    "trigger": "WOULD_YOU_KINDLY",
                    "request": request,
                    "request_sha256": hashlib.sha256(request.encode("utf-8")).hexdigest().upper(),
                    "may_execute": False,
                    "authority": "NOT_GRANTED_BY_TRIGGER",
                    "required_next_gate": "AIOS_CAPABILITY_AND_HYDRA_AUTHORIZATION",
                    "external_effects": False,
                    "tool_authority": False,
                    "filesystem_authority": False,
                    "security_authority": False,
                })
        routed.append({
            "turn": number,
            "input": raw,
            "state": state,
            "segments": segments,
            "write_performed": False,
        })
    after = {
        "graph": _persistent_sqlite_hashes(graph_path),
        "curriculum": _persistent_sqlite_hashes(curriculum_path),
    }
    if after != before:
        raise RuntimeError("conversation/task routing changed persistent state")
    report = {
        "schema": "NN_ADDRESSED_CONVERSATION_ROUTE_V1",
        "state": "PASS",
        "trigger": "WOULD_YOU_KINDLY",
        "trigger_semantics": "INTENT_ROUTE_ONLY_NOT_AUTHORITY",
        "turns": routed,
        "counts": {
            "conversation_segments": conversations,
            "task_requests": task_requests,
            "incomplete_task_requests": incomplete,
            "executed_tasks": 0,
        },
        "persistent_state_unchanged": True,
        "persistent_hashes": before,
        "candidate_only": True,
        "external_effects": False,
        "promotion_performed": False,
        "deployment_performed": False,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def command_run_mixed_conversation(args: argparse.Namespace) -> int:
    """Route descriptive and Q2 binary turns through their proven readers."""

    from .steel_brain_store import SQLiteNeuronGraphStore

    raw_turns = [value.strip() for value in args.turns.split("|") if value.strip()]
    if not raw_turns or len(raw_turns) > args.max_turns:
        raise ValueError("mixed conversation turn count is outside its bound")
    evidence_dir = args.evidence_dir.resolve()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output.resolve()
    turn_paths = [evidence_dir / f"turn_{index:02d}.json" for index in range(1, len(raw_turns) + 1)]
    if output_path.exists() or any(path.exists() for path in turn_paths):
        raise FileExistsError("mixed conversation evidence is append-only")
    before = {
        "graph": _persistent_sqlite_hashes(args.graph.resolve()),
        "curriculum": _persistent_sqlite_hashes(args.curriculum_db.resolve()),
    }
    turns: list[dict[str, Any]] = []
    boundary_turns: list[dict[str, Any]] = []
    family_passes = {"DESCRIPTIVE": 0, "BINARY_Q2": 0}
    source_inputs = 0
    source_passes = 0
    task_inputs = 0
    task_authority_holds = 0
    assertion_inputs = 0
    assertion_passes = 0
    social_inputs = 0
    social_passes = 0
    active_family: str | None = None
    descriptive_anchor: str | None = None
    cross_family_context_holds = 0
    social_routes: dict[str, tuple[dict[str, Any], Path]] = {}
    social_response_map: dict[str, str] = {}
    social_runtime_predicates: dict[str, str] = {}
    social_acts: dict[str, str] = {}
    social_context_requirements: dict[str, str] = {}
    active_social_act: str | None = None
    binary_history: list[str] = []
    social_intents: list[tuple[dict[str, Any], Path]] = []
    dictionary_rows_for_intent = json.loads(args.dictionary.resolve().read_text(encoding="utf-8"))
    interrogative_heads_for_intent = {
        str(row.get("word", "")).strip().lower()
        for row in dictionary_rows_for_intent
        if any("interrogative pronoun" in str(value).lower() for value in row.get("definitions", ()))
    }
    dictionary_definitions_for_intent: dict[str, tuple[str, ...]] = {}
    for row in dictionary_rows_for_intent:
        word = str(row.get("word", "")).strip().lower()
        dictionary_definitions_for_intent[word] = dictionary_definitions_for_intent.get(word, ()) + tuple(
            str(value).lower() for value in row.get("definitions", ())
        )
    dictionary_proven_articles = {
        word
        for word, definitions in dictionary_definitions_for_intent.items()
        if any(
            "article" in definition
            or "placed before nouns to limit or individualize their meaning" in definition
            for definition in definitions
        )
    }
    communication_probe_sha256 = hashlib.sha256(
        "\0".join(SOCIAL_COMMUNICATION_HEAD_DEFINITION_PROBES).encode("utf-8")
    ).hexdigest().upper()

    def social_intent_pattern_matches(
        words: tuple[str, ...],
        word_ids: tuple[str, ...],
        signature: list[list[str]],
        pattern: dict[str, Any],
    ) -> bool:
        if not words or not word_ids or not signature:
            return False
        head_channels = set(pattern.get("head_channels", ()))
        if head_channels and not head_channels.issubset(set(signature[0])):
            return False
        pattern_kind = str(pattern.get("pattern_kind", "INTERROGATIVE_HEAD_PLUS_ANCHORED_TAIL_V1"))
        if pattern_kind == "INTERROGATIVE_HEAD_PLUS_ANCHORED_TAIL_V1":
            return (
                words[0] in interrogative_heads_for_intent
                and list(word_ids[1:]) == list(pattern.get("anchored_tail_word_ids", ()))
            )
        if pattern_kind == "COMMUNICATION_HEAD_PLUS_ANCHORED_SUFFIX_V1":
            minimum_arity = int(pattern.get("minimum_arity", 0))
            maximum_arity = int(pattern.get("maximum_arity", 0))
            suffix = tuple(str(value) for value in pattern.get("anchored_suffix_word_ids", ()))
            definitions = "\n".join(dictionary_definitions_for_intent.get(words[0], ()))
            return (
                str(pattern.get("cpu_probe_sha256", "")) == communication_probe_sha256
                and minimum_arity <= len(words) <= maximum_arity
                and bool(suffix)
                and word_ids[-len(suffix):] == suffix
                and any(probe in definitions for probe in SOCIAL_COMMUNICATION_HEAD_DEFINITION_PROBES)
            )
        return False
    social_teacher_path = getattr(args, "social_teacher", None)
    if social_teacher_path is not None:
        social_teacher_path = Path(social_teacher_path).resolve()
        social_teacher = json.loads(social_teacher_path.read_text(encoding="utf-8"))
        if social_teacher.get("schema") != "NN_CPU_PRIVATE_SOCIAL_ACTS_V1":
            raise ValueError("unsupported CPU-private social act schema")
        for fact in social_teacher.get("facts", ()):
            input_surface = " ".join(str(value).lower() for value in fact.get("supported_surface", ()))
            response_surface = " ".join(str(value).lower() for value in fact.get("response_surface", ()))
            if input_surface and response_surface:
                social_response_map[input_surface] = response_surface
            if input_surface and fact.get("runtime_predicate"):
                social_runtime_predicates[input_surface] = str(fact["runtime_predicate"])
            if input_surface and fact.get("social_act"):
                social_acts[input_surface] = str(fact["social_act"])
            if input_surface and fact.get("social_context_requirement"):
                requirement = str(fact["social_context_requirement"])
                if requirement not in {"STATUS_QUERY"}:
                    raise ValueError("unsupported social context requirement")
                social_context_requirements[input_surface] = requirement
    for value in getattr(args, "social_learning_receipt", None) or ():
        social_receipt_path = Path(value).resolve()
        social_receipt = json.loads(social_receipt_path.read_text(encoding="utf-8"))
        hydra = social_receipt.get("hydra_route_membrane", {})
        if (
            social_receipt.get("state") != "PASS"
            or social_receipt.get("utterance_kind") != "SOCIAL"
            or not social_receipt.get("result", {}).get("sentence_id")
            or not isinstance(hydra, dict)
            or hydra.get("enabled") is not True
        ):
            raise ValueError("invalid Rust-Hydra social learning receipt")
        surface = " ".join(
            str(part).removeprefix("WORD:").lower()
            for part in social_receipt["result"].get("construction", ())
        )
        if not surface or surface in social_routes:
            raise ValueError("social learning receipts require unique learned surfaces")
        social_routes[surface] = (social_receipt, social_receipt_path)
    for value in getattr(args, "social_intent_receipt", None) or ():
        intent_path = Path(value).resolve()
        intent_receipt = json.loads(intent_path.read_text(encoding="utf-8"))
        if (
            intent_receipt.get("schema") != "NN_SOCIAL_INTENT_INDUCTION_V1"
            or intent_receipt.get("state") != "PASS"
            or not intent_receipt.get("result", {}).get("concept_id")
            or intent_receipt.get("result", {}).get("future_surface_used") is not False
        ):
            raise ValueError("invalid learned social intent receipt")
        social_intents.append((intent_receipt, intent_path))
    learned_social_vocatives = {
        parts[-1]
        for surface in social_routes
        for parts in (surface.split(),)
        if len(parts) == 3 and parts[:2] == ["i", "am"]
    }

    def social_clause_sequence(raw_text: str, normalized_text: str) -> tuple[str, ...]:
        """Resolve a natural multi-act social surface from learned routes only."""

        if normalized_text in social_routes:
            return (normalized_text,)
        clauses = [
            " ".join(re.findall(r"[a-z]+", clause.lower()))
            for clause in re.split(r"[,;]+", raw_text)
        ]
        resolved: list[str] = []
        for clause in clauses:
            if not clause:
                continue
            if clause in social_routes:
                resolved.append(clause)
                continue
            words = clause.split()
            without_vocative = " ".join(words[:-1])
            if (
                len(words) >= 2
                and words[-1] in learned_social_vocatives
                and without_vocative in social_routes
            ):
                resolved.append(without_vocative)
                continue
            return ()
        return tuple(resolved) if resolved else ()

    for index, (raw_text, turn_path) in enumerate(zip(raw_turns, turn_paths), 1):
        normalized = " ".join(raw_text.strip().lower().rstrip("?.!").split())
        normalized_words = tuple(normalized.split())
        descriptive_surface = normalized
        grammar_normalization: dict[str, Any] | None = None
        article_candidate = normalized_words[2] if len(normalized_words) == 4 else ""
        predicate_initial = normalized_words[3][:1] if len(normalized_words) == 4 else ""
        article_placement_supported = (
            article_candidate == "the"
            or (article_candidate == "a" and predicate_initial not in "aeiou")
            or (article_candidate == "an" and predicate_initial in "aeiou")
        )
        if (
            len(normalized_words) == 4
            and normalized_words[0] == "is"
            and article_candidate in dictionary_proven_articles
            and article_placement_supported
        ):
            descriptive_surface = " ".join(
                (normalized_words[0], normalized_words[1], normalized_words[3])
            )
            grammar_normalization = {
                "schema": "NN_CPU_DICTIONARY_GRAMMAR_NORMALIZATION_V1",
                "rule": "COPULAR_Q1_OPTIONAL_ARTICLE_V1",
                "surface": normalized,
                "canonical_surface": descriptive_surface,
                "removed_word": normalized_words[2],
                "placement_check": "ORTHOGRAPHIC_INDEFINITE_ARTICLE_V1",
                "evidence_source": str(args.dictionary.resolve()),
                "evidence_definitions": list(
                    dictionary_definitions_for_intent[normalized_words[2]]
                ),
                "answer_or_truth_added": False,
            }
        task_phrase_index = _unquoted_phrase_index(raw_text, "would you kindly")
        source_match = re.fullmatch(
            r"(?:where did you learn|what is the source of) ([a-z]+)", normalized
        )
        social_sequence = social_clause_sequence(raw_text, normalized)
        social = bool(social_sequence)
        social_surface = social_sequence[-1] if social_sequence else normalized
        intent_match: tuple[dict[str, Any], Path, list[list[str]]] | None = None
        if not social and social_intents:
            words = tuple(normalized.split())
            with SQLiteNeuronGraphStore(args.graph.resolve(), readonly=True) as intent_store:
                intent_manifest = intent_store.manifest()
                word_ids = tuple(str(intent_manifest["word_index"].get(word, "")) for word in words)
                if all(word_ids):
                    signature = [_opaque_word_channels(intent_store.load_neuron(word_id)) for word_id in word_ids]
                    if signature:
                        matches: list[tuple[dict[str, Any], Path, list[list[str]]]] = []
                        for intent_receipt, intent_path in social_intents:
                            concept = intent_store.load_neuron(str(intent_receipt["result"]["concept_id"]))
                            payload = concept.get("center_attractor", {}).get("opaque_social_intent_v1", {})
                            pattern_match = any(
                                social_intent_pattern_matches(words, word_ids, signature, pattern)
                                for pattern in payload.get("source_patterns", ())
                            )
                            if (
                                concept.get("kind") == "CONCEPT"
                                and concept.get("lifecycle") == "STABLE"
                                and pattern_match
                            ):
                                matches.append((intent_receipt, intent_path, signature))
                        if len(matches) == 1:
                            intent_match = matches[0]
        assertion = not social and not raw_text.rstrip().endswith("?") and len(normalized.split()) == 3
        binary_disambiguation = (
            bool(binary_history)
            and len(normalized.split()) == 1
            and bool(turns)
            and turns[-1].get("state") == "HOLD_CONTEXT_AMBIGUOUS"
        )
        family = (
            "TASK" if task_phrase_index >= 0
            else "SOURCE" if source_match is not None
            else "SOCIAL" if social
            else "SOCIAL_INTENT" if intent_match
            else "ASSERTION" if assertion
            else "BINARY_Q2" if normalized.startswith("do ") or binary_disambiguation
            else "DESCRIPTIVE"
        )
        if family not in {"BINARY_Q2", "ASSERTION"}:
            binary_history.clear()
        if family == "SOURCE":
            source_inputs += 1
        if family == "TASK":
            task_inputs += 1
        if social or intent_match:
            social_inputs += 1
        if assertion:
            assertion_inputs += 1
        descriptive_followup = normalized == "what is it"
        if family == "TASK":
            prefix = raw_text[:task_phrase_index].strip(" \t,;:-")
            request = raw_text[task_phrase_index + len("would you kindly"):].strip(" \t,;:-")
            request = request.rstrip("?!.").strip()
            task_state = (
                "HOLD_TASK_AUTHORIZATION_REQUIRED"
                if request else "HOLD_INCOMPLETE_TASK_REQUEST"
            )
            task_gates = {
                "grammar": "PASS" if request else "HOLD",
                "meaning": "PASS" if request else "HOLD",
                "truth": "NOT_APPLICABLE",
                "context": "NOT_REQUIRED",
                "authority": "HOLD",
            }
            task_turn = {
                "turn": 1,
                "session": 1,
                "input": raw_text,
                "state": task_state,
                "question_family": "TASK",
                "conversation_preamble": prefix or None,
                "task_request": request or None,
                "trigger": "WOULD_YOU_KINDLY",
                "required_next_gate": (
                    "AIOS_CAPABILITY_AND_HYDRA_AUTHORIZATION" if request else None
                ),
                "gates": task_gates,
                "write_performed": False,
            }
            task_boundary = {
                "turn": 1,
                "session": 1,
                "state": task_state,
                "gates": task_gates,
                "task_packet": {
                    "schema_version": "steel_brain_task_proposal_v1",
                    "trigger": "WOULD_YOU_KINDLY",
                    "request": request or None,
                    "request_sha256": (
                        hashlib.sha256(request.encode("utf-8")).hexdigest().upper()
                        if request else None
                    ),
                    "may_execute": False,
                    "tool_authority": False,
                    "filesystem_authority": False,
                    "security_authority": False,
                    "required_next_gate": (
                        "AIOS_CAPABILITY_AND_HYDRA_AUTHORIZATION" if request else None
                    ),
                },
            }
            receipt = {
                "schema": "NN_MIXED_TASK_PROPOSAL_TURN_V1",
                "state": "HOLD",
                "turns": [task_turn],
                "aios_packet": {
                    "schema_version": "steel_brain_conversation_packet_v1",
                    "candidate_only": True,
                    "external_effects": False,
                    "turns": [task_boundary],
                    "may_emit": False,
                    "tool_authority": False,
                    "memory_write": False,
                },
            }
            turn_path.write_text(
                json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            if request:
                task_authority_holds += 1
        elif family == "SOURCE":
            assert source_match is not None
            surface = str(source_match.group(1)).lower()
            with SQLiteNeuronGraphStore(args.graph.resolve(), readonly=True) as source_store:
                source_neuron_id = source_store.manifest().get("word_index", {}).get(surface)
                source_neuron = (
                    source_store.load_neuron(str(source_neuron_id))
                    if source_neuron_id is not None else None
                )
                claims = (
                    source_neuron.get("center_attractor", {}).get("claim_provenance_v1", [])
                    if source_neuron is not None else []
                )
            source_ok = isinstance(claims, list) and bool(claims)
            source_state = "PASS_SOURCE_REPORT" if source_ok else (
                "HOLD_UNKNOWN_NEURON" if source_neuron is None else "HOLD_NO_RECORDED_SOURCE"
            )
            selected_claim = claims[0] if source_ok else None
            source_gates = {
                "grammar": "PASS",
                "meaning": "PASS" if source_ok else "HOLD",
                "truth": "PASS" if source_ok else "HOLD",
                "context": "NOT_REQUIRED",
                "authority": "PASS_NO_AUTHORITY",
            }
            rendered_response = (
                f"I learned {surface} from {selected_claim['source_title']}."
                if source_ok else None
            )
            source_turn = {
                "turn": 1,
                "session": 1,
                "input": raw_text,
                "state": source_state,
                "question_family": "SOURCE",
                "response": rendered_response,
                "response_renderer": "CPU_PROVENANCE_TEMPLATE_V1" if source_ok else None,
                "neuron_id": str(source_neuron_id) if source_neuron_id else None,
                "claim": selected_claim,
                "gates": source_gates,
                "write_performed": False,
            }
            source_boundary = {
                "turn": 1,
                "session": 1,
                "state": source_state,
                "gates": source_gates,
                "source_packet": {
                    "schema_version": "steel_brain_neuron_source_packet_v1",
                    "neuron_id": str(source_neuron_id) if source_neuron_id else None,
                    "claim_id": selected_claim.get("claim_id") if source_ok else None,
                    "source_title": selected_claim.get("source_title") if source_ok else None,
                    "source_locator": selected_claim.get("source_locator") if source_ok else None,
                    "source_sha256": selected_claim.get("source_sha256") if source_ok else None,
                    "may_emit": False,
                    "tool_authority": False,
                },
            }
            receipt = {
                "schema": "NN_MIXED_NEURON_SOURCE_TURN_V1",
                "state": "PASS" if source_ok else "HOLD",
                "turns": [source_turn],
                "aios_packet": {
                    "schema_version": "steel_brain_conversation_packet_v1",
                    "candidate_only": True,
                    "external_effects": False,
                    "turns": [source_boundary],
                    "may_emit": False,
                    "tool_authority": False,
                    "memory_write": False,
                },
            }
            turn_path.write_text(
                json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            if source_ok:
                source_passes += 1
        elif intent_match is not None:
            intent_receipt, intent_receipt_path, matched_signature = intent_match
            response_surface = " ".join(str(value).lower() for value in intent_receipt["cpu_private_response_surface"])
            if response_surface not in social_routes:
                raise ValueError("learned intent has no independently learned response route")
            response_receipt, response_receipt_path = social_routes[response_surface]
            response_sentence_id = str(response_receipt["result"]["sentence_id"])
            response_words = tuple(response_surface.split())
            input_words = tuple(normalized.split())
            with SQLiteNeuronGraphStore(args.graph.resolve(), readonly=True) as intent_store:
                concept = intent_store.load_neuron(str(intent_receipt["result"]["concept_id"]))
                payload = concept.get("center_attractor", {}).get("opaque_social_intent_v1", {})
                response_sentence = intent_store.load_neuron(response_sentence_id)
                response_center = response_sentence.get("center_attractor", {})
                manifest = intent_store.manifest()
                response_ids = tuple(str(manifest["word_index"].get(word, "")) for word in response_words)
                input_word_ids = tuple(str(manifest["word_index"].get(word, "")) for word in input_words)
                seeds = tuple(args.seed + index * 1_000_003 + draw * 97_409 for draw in range(1, args.confirmations + 1))
                counts = Neuronizer(intent_store, CudaLibrary()).sample_admitted_sentence_distribution(
                    [f"WORD:{word}" for word in response_words], seeds=seeds, sentence_id=response_sentence_id,
                )
                route_recalled = (
                    concept.get("lifecycle") == "STABLE"
                    and payload.get("future_surface_used") is False
                    and any(
                        social_intent_pattern_matches(input_words, input_word_ids, matched_signature, pattern)
                        for pattern in payload.get("source_patterns", ())
                    )
                    and str(payload.get("response_sentence_id")) == response_sentence_id
                    and response_sentence.get("lifecycle") == "STABLE"
                    and response_center.get("trusted_language_memory") is True
                    and tuple(str(value) for value in response_center.get("construction", ())) == response_ids
                    and counts == {" ".join(f"WORD:{word}" for word in response_words): args.confirmations}
                )
            gates = {
                "grammar": "PASS" if route_recalled else "HOLD",
                "meaning": "PASS" if route_recalled else "HOLD",
                "truth": "PASS" if route_recalled else "HOLD",
                "context": "NOT_REQUIRED",
                "authority": "PASS_NO_AUTHORITY",
            }
            state = "PASS_SOCIAL_RESPONSE" if route_recalled else "HOLD_SOCIAL_RECALL"
            turn = {
                "turn": 1, "session": 1, "input": raw_text, "state": state,
                "response": response_surface + "." if route_recalled else None,
                "intent_generalization": {
                    "concept_id": intent_receipt["result"]["concept_id"],
                    "matched_opaque_signature": matched_signature,
                    "exact_surface_stored": False,
                    "future_surface_used": False,
                },
                "raw_social_response_recall": {
                    " ".join(key.removeprefix("WORD:") for key in text.split()): count
                    for text, count in counts.items()
                },
                "gates": gates, "write_performed": False,
            }
            boundary: dict[str, Any] = {"turn": 1, "session": 1, "state": state, "gates": gates}
            if route_recalled:
                hydra_trace = Path(str(response_receipt["hydra_route_membrane"]["trace"])).resolve()
                boundary["utterance_packet"] = {
                    "schema_version": "steel_brain_social_utterance_packet_v1",
                    "candidate_only": True, "external_effects": False,
                    "input": normalized, "input_word_route": list(input_words),
                    "response": response_surface + ".", "response_word_route": list(response_words),
                    "learned_intent_concept_id": intent_receipt["result"]["concept_id"],
                    "learned_response_sentence_id": response_sentence_id,
                    "gates": gates,
                    "route_gate": {
                        "allowed": True, "local_text_only": True,
                        "state": "PASS_RUST_HYDRA_ROUTE_GATE",
                        "hydra_trace_sha256": hashlib.sha256(hydra_trace.read_bytes()).hexdigest().upper(),
                    },
                    "integrity": {
                        "graph_sha256": next(iter(before["graph"].values())),
                        "curriculum_sha256": next(iter(before["curriculum"].values())),
                    },
                    "source_receipt": str(intent_receipt_path),
                    "response_source_receipt": str(response_receipt_path),
                    "may_emit": False, "tool_authority": False, "memory_write": False,
                }
            receipt = {
                "schema": "NN_SOCIAL_INTENT_CONVERSATION_TURN_V1",
                "state": "PASS" if route_recalled else "HOLD", "turns": [turn],
                "aios_packet": {
                    "schema_version": "steel_brain_conversation_packet_v1",
                    "candidate_only": True, "external_effects": False,
                    "turns": [boundary],
                    "context": {"owner": "CPU_SESSION_RAM", "persisted": False, "reset_supported": True},
                    "may_emit": False, "tool_authority": False, "memory_write": False,
                },
            }
            turn_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        elif social:
            social_receipt, social_receipt_path = social_routes[social_surface]
            response_surface = social_response_map.get(social_surface) or " ".join(
                str(value).lower() for value in social_receipt.get("social_response_surface", ())
            ) or social_surface
            if response_surface not in social_routes:
                raise ValueError("social input has no independently learned response route")
            response_receipt, response_receipt_path = social_routes[response_surface]
            sentence_id = str(social_receipt["result"]["sentence_id"])
            response_sentence_id = str(response_receipt["result"]["sentence_id"])
            input_words = tuple(social_surface.split())
            response_words = tuple(response_surface.split())
            social_context_requirement = social_context_requirements.get(social_surface)
            social_context_ok = (
                social_context_requirement is None
                or (active_family == "SOCIAL" and active_social_act == social_context_requirement)
            )
            with SQLiteNeuronGraphStore(args.graph.resolve(), readonly=True) as social_store:
                sentence = social_store.load_neuron(sentence_id)
                center = sentence.get("center_attractor", {})
                construction = tuple(str(value) for value in center.get("construction", ()))
                response_sentence = social_store.load_neuron(response_sentence_id)
                response_center = response_sentence.get("center_attractor", {})
                response_construction = tuple(str(value) for value in response_center.get("construction", ()))
                manifest = social_store.manifest()
                input_ids = tuple(str(manifest["word_index"].get(word, "")) for word in input_words)
                response_ids = tuple(str(manifest["word_index"].get(word, "")) for word in response_words)
                social_engine = Neuronizer(social_store, CudaLibrary())
                seeds = tuple(args.seed + index * 1_000_003 + draw * 97_409 for draw in range(1, args.confirmations + 1))
                input_counts = social_engine.sample_admitted_sentence_distribution(
                    [f"WORD:{word}" for word in input_words], seeds=seeds, sentence_id=sentence_id,
                )
                response_counts = social_engine.sample_admitted_sentence_distribution(
                    [f"WORD:{word}" for word in response_words], seeds=seeds, sentence_id=response_sentence_id,
                )
                runtime_predicate = (
                    social_runtime_predicates.get(social_surface)
                    or social_runtime_predicates.get(response_surface)
                    or social_receipt.get("social_runtime_predicate")
                    or response_receipt.get("social_runtime_predicate")
                )
                if runtime_predicate not in {
                    None,
                    "GRAPH_READABLE",
                    "TEXT_CONVERSATION_AVAILABLE",
                }:
                    raise ValueError("unsupported social runtime predicate")
                runtime_ok = (
                    runtime_predicate is None
                    or social_store.audit().get("state") == "PASS"
                    and (
                        runtime_predicate == "GRAPH_READABLE"
                        or runtime_predicate == "TEXT_CONVERSATION_AVAILABLE"
                        and args.max_turns >= 1
                    )
                )
            clean_input_counts = {
                " ".join(part.removeprefix("WORD:") for part in text.split()): count
                for text, count in input_counts.items()
            }
            clean_response_counts = {
                " ".join(part.removeprefix("WORD:") for part in text.split()): count
                for text, count in response_counts.items()
            }
            route_recalled = (
                sentence.get("lifecycle") == "STABLE"
                and center.get("trusted_language_memory") is True
                and center.get("opaque_utterance_mode_v1") == "U2"
                and construction == input_ids
                and response_sentence.get("lifecycle") == "STABLE"
                and response_center.get("trusted_language_memory") is True
                and response_center.get("opaque_utterance_mode_v1") == "U2"
                and response_construction == response_ids
                and clean_input_counts == {social_surface: args.confirmations}
                and clean_response_counts == {response_surface: args.confirmations}
                and runtime_ok
            )
            recalled = route_recalled and social_context_ok
            social_gates = {
                "grammar": "PASS" if route_recalled else "HOLD",
                "meaning": "PASS" if route_recalled else "HOLD",
                "truth": "PASS" if recalled else "HOLD",
                "context": (
                    "NOT_REQUIRED" if social_context_requirement is None
                    else "PASS" if social_context_ok else "HOLD"
                ),
                "authority": "PASS_NO_AUTHORITY",
                **({"runtime": "PASS" if runtime_ok else "HOLD"} if runtime_predicate else {}),
            }
            social_state = (
                "PASS_SOCIAL_RESPONSE" if recalled
                else "HOLD_CONTEXT_EMPTY" if not social_context_ok
                else "HOLD_SOCIAL_RECALL"
            )
            social_turn = {
                "turn": 1, "session": 1, "input": raw_text, "state": social_state,
                "response": response_surface + "." if recalled else None,
                "social_route_surface": social_surface,
                "social_sequence": list(social_sequence),
                "raw_social_input_recall": clean_input_counts,
                "raw_social_response_recall": clean_response_counts,
                "runtime_predicate": runtime_predicate,
                "social_context_requirement": social_context_requirement,
                "social_context_source": (
                    "EPHEMERAL_PRIOR_SOCIAL_ACT" if social_context_requirement and social_context_ok
                    else None
                ),
                "gates": social_gates,
                "write_performed": False,
            }
            social_boundary: dict[str, Any] = {
                "turn": 1, "session": 1, "state": social_state, "gates": social_gates,
            }
            if recalled:
                hydra_trace = Path(str(response_receipt["hydra_route_membrane"]["trace"])).resolve()
                graph_sha = next(iter(before["graph"].values()))
                curriculum_sha = next(iter(before["curriculum"].values()))
                social_boundary["utterance_packet"] = {
                    "schema_version": "steel_brain_social_utterance_packet_v1",
                    "candidate_only": True, "external_effects": False,
                    "input": normalized, "input_word_route": list(input_words),
                    "response": response_surface + ".", "response_word_route": list(response_words),
                    "learned_input_sentence_id": sentence_id,
                    "learned_response_sentence_id": response_sentence_id,
                    "gates": social_gates,
                    "route_gate": {
                        "allowed": True, "local_text_only": True,
                        "state": "PASS_RUST_HYDRA_ROUTE_GATE",
                        "hydra_trace_sha256": hashlib.sha256(hydra_trace.read_bytes()).hexdigest().upper(),
                    },
                    "integrity": {"graph_sha256": graph_sha, "curriculum_sha256": curriculum_sha},
                    "source_receipt": str(social_receipt_path),
                    "response_source_receipt": str(response_receipt_path),
                    "may_emit": False, "tool_authority": False, "memory_write": False,
                }
            receipt = {
                "schema": "NN_SOCIAL_CONVERSATION_TURN_V1",
                "state": "PASS" if recalled else "HOLD", "turns": [social_turn],
                "aios_packet": {
                    "schema_version": "steel_brain_conversation_packet_v1",
                    "candidate_only": True, "external_effects": False,
                    "turns": [social_boundary],
                    "context": {"owner": "CPU_SESSION_RAM", "persisted": False, "reset_supported": True},
                    "may_emit": False, "tool_authority": False, "memory_write": False,
                },
            }
            turn_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        elif descriptive_followup and (active_family != "DESCRIPTIVE" or descriptive_anchor is None):
            hold_gates = {
                "grammar": "PASS", "meaning": "HOLD", "truth": "HOLD",
                "context": "HOLD", "authority": "PASS_NO_AUTHORITY",
            }
            hold_turn = {
                "turn": 1, "session": 1, "input": raw_text,
                "state": "HOLD_CONTEXT_FAMILY_MISMATCH", "gates": hold_gates,
                "clarification": "REQUEST_CONTEXT", "write_performed": False,
            }
            hold_boundary = {"turn": 1, "session": 1, "state": hold_turn["state"], "gates": hold_gates}
            receipt = {
                "schema": "NN_MIXED_FAMILY_CONTEXT_HOLD_V1", "state": "HOLD",
                "turns": [hold_turn],
                "aios_packet": {
                    "schema_version": "steel_brain_conversation_packet_v1",
                    "candidate_only": True, "external_effects": False,
                    "turns": [hold_boundary],
                    "context": {"owner": "CPU_SESSION_RAM", "persisted": False, "reset_supported": True},
                    "may_emit": False, "tool_authority": False, "memory_write": False,
                },
            }
            turn_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            cross_family_context_holds += 1
        else:
            with contextlib.redirect_stdout(io.StringIO()):
                if family in {"BINARY_Q2", "ASSERTION"}:
                    binary_surface = f"do {normalized}" if family == "ASSERTION" else raw_text
                    binary_history.append(binary_surface)
                    command_run_binary_conversation(argparse.Namespace(
                        teacher=args.binary_teacher,
                        learning_receipt=list(args.binary_learning_receipt),
                        graph=args.graph, curriculum_db=args.curriculum_db,
                        turns="|".join(binary_history), output=turn_path,
                        seed=args.seed + index * 1_000_003,
                        max_turns=len(binary_history), confirmations=args.confirmations,
                        context_cap=4,
                    ))
                else:
                    descriptive_turns = (
                        f"{descriptive_anchor}|{descriptive_surface}"
                        if descriptive_followup and descriptive_anchor is not None
                        else descriptive_surface
                    )
                    command_run_conversation(argparse.Namespace(
                        dictionary=args.dictionary,
                        teacher=args.descriptive_teacher,
                        learning_receipt=list(args.descriptive_learning_receipt),
                        graph=args.graph, curriculum_db=args.curriculum_db,
                        turns=descriptive_turns, output=turn_path,
                        seed=args.seed + index * 1_000_003,
                        max_turns=2 if descriptive_followup else 1, context_ttl_seconds=60.0,
                        confirmations=args.confirmations,
                    ))
        receipt = json.loads(turn_path.read_text(encoding="utf-8"))
        if not receipt.get("turns") or not receipt.get("aios_packet", {}).get("turns"):
            raise ValueError(f"mixed conversation child receipt has no turn: {turn_path}")
        child_turn_index = (
            len(receipt["turns"]) - 1
            if family in {"BINARY_Q2", "ASSERTION"} and len(receipt["turns"]) > 1
            else 1 if descriptive_followup and len(receipt["turns"]) > 1
            else 0
        )
        turn = dict(receipt["turns"][child_turn_index])
        turn["turn"] = index
        turn["session"] = 1
        turn["input"] = raw_text
        turn["question_family"] = family
        if grammar_normalization is not None and family == "DESCRIPTIVE":
            turn["surface_question"] = normalized
            turn["canonical_question"] = descriptive_surface
            turn["grammar_normalization"] = grammar_normalization
        if family == "ASSERTION":
            turn["input"] = raw_text
            turn["assertion"] = normalized + "."
            turn["internal_truth_query"] = f"do {normalized}?"
        boundary = dict(receipt["aios_packet"]["turns"][child_turn_index])
        boundary["turn"] = index
        boundary["session"] = 1
        boundary["surface_input"] = raw_text
        if grammar_normalization is not None and family == "DESCRIPTIVE":
            boundary["surface_input"] = raw_text
            boundary["canonical_input"] = descriptive_surface
            boundary["grammar_normalization"] = grammar_normalization
            if isinstance(boundary.get("utterance_packet"), dict):
                boundary["utterance_packet"]["surface_question"] = normalized
                boundary["utterance_packet"]["canonical_question"] = descriptive_surface
                boundary["utterance_packet"]["grammar_normalization"] = grammar_normalization
        if (
            turn.get("state") == "HOLD_UNSUPPORTED_QUESTION"
            and family == "DESCRIPTIVE"
        ):
            request_words = tuple(normalized.split())
            with SQLiteNeuronGraphStore(args.graph.resolve(), readonly=True) as request_store:
                request_word_index = request_store.manifest()["word_index"]
            admitted_words = [word for word in request_words if word in request_word_index]
            missing_words = [word for word in request_words if word not in request_word_index]
            teaching_request = {
                "schema": "NN_CONVERSATIONAL_TEACHING_REQUEST_V1",
                "surface": normalized,
                "word_route": list(request_words),
                "admitted_words": admitted_words,
                "missing_words": missing_words,
                "authority_required": "CPU_TEACHER_ADMISSION",
                "auto_apply": False,
            }
            turn.update({
                "state": "HOLD_TEACHING_REQUIRED",
                "clarification": "REQUEST_TEACHING",
                "teaching_request": teaching_request,
            })
            boundary.update({
                "state": "HOLD_TEACHING_REQUIRED",
                "teaching_request": teaching_request,
            })
        turns.append(turn)
        boundary_turns.append(boundary)
        if turn.get("state") == "PASS_GROUNDED_RESPONSE":
            if family == "ASSERTION":
                assertion_passes += 1
            else:
                family_passes[family] += 1
            if family == "DESCRIPTIVE":
                active_family = "DESCRIPTIVE"
                if not descriptive_followup:
                    descriptive_anchor = descriptive_surface
            else:
                active_family = "BINARY_Q2"
        elif turn.get("state") == "PASS_SOCIAL_RESPONSE":
            social_passes += 1
            active_family = "SOCIAL"
            active_social_act = social_acts.get(social_surface)
    with SQLiteNeuronGraphStore(args.graph.resolve(), readonly=True) as store:
        audit = store.audit()
    after = {
        "graph": _persistent_sqlite_hashes(args.graph.resolve()),
        "curriculum": _persistent_sqlite_hashes(args.curriculum_db.resolve()),
    }
    unchanged = before == after
    safe_holds = sum(str(row.get("state", "")).startswith("HOLD_") for row in turns)
    state = "PASS" if (
        all(family_passes.values())
        and safe_holds >= 1
        and (assertion_inputs == 0 or assertion_passes >= 1)
        and (social_inputs == 0 or social_passes >= 1)
        and (source_inputs == 0 or source_passes >= 1)
        and (task_inputs == 0 or task_authority_holds >= 1)
        and unchanged
        and audit.get("state") == "PASS"
    ) else "HOLD"
    graph_sha = next(iter(after["graph"].values()))
    curriculum_sha = next(iter(after["curriculum"].values()))
    packet = {
        "schema_version": "steel_brain_conversation_packet_v1",
        "candidate_only": True, "external_effects": False,
        "turns": boundary_turns,
        "context": {"owner": "CPU_SESSION_RAM", "persisted": False, "reset_supported": True},
        "integrity": {"graph_sha256": graph_sha, "curriculum_sha256": curriculum_sha},
        "may_emit": False, "tool_authority": False, "memory_write": False,
    }
    report = {
        "schema": "NN_MIXED_FAMILY_CONVERSATION_V1",
        "state": state, "turns": turns,
        "summary": {
            "family_grounded_passes": family_passes,
            "safe_holds": safe_holds,
            "cross_family_context_holds": cross_family_context_holds,
            "assertion_inputs": assertion_inputs,
            "assertion_grounded_passes": assertion_passes,
            "social_inputs": social_inputs,
            "social_grounded_passes": social_passes,
            "source_inputs": source_inputs,
            "source_grounded_passes": source_passes,
            "task_inputs": task_inputs,
            "task_authority_holds": task_authority_holds,
        },
        "child_receipts": [str(path) for path in turn_paths],
        "aios_packet": packet, "graph_audit": audit,
        "persistent_state_unchanged": unchanged,
        "persistent_hashes_before": before, "persistent_hashes_after": after,
        "candidate_only": True, "canonical_mutation_authorized": False,
        "promotion_performed": False, "deployment_performed": False,
    }
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if state == "PASS" else 2


def command_run_learning_conversation(args: argparse.Namespace) -> int:
    """Encounter unknown words, ask the CPU dictionary, learn, and regenerate.

    This wraps the existing mixed dispatcher and universal one-bit word learner;
    it does not add a shortcut spelling path or a sentence-specific response.
    A surface absent from the CPU dictionary stops before any persistent write.
    """

    from .steel_brain_store import SQLiteNeuronGraphStore

    output_path = args.output.resolve()
    evidence_dir = args.evidence_dir.resolve()
    if output_path.exists() or evidence_dir.exists():
        raise FileExistsError("learning conversation evidence is append-only")
    evidence_dir.mkdir(parents=True)
    before = {
        "graph": _persistent_sqlite_hashes(args.graph.resolve()),
        "curriculum": _persistent_sqlite_hashes(args.curriculum_db.resolve()),
    }

    def mixed_namespace(stage: str, seed: int) -> argparse.Namespace:
        values = dict(vars(args))
        values.update({
            "evidence_dir": evidence_dir / f"{stage}_turns",
            "output": evidence_dir / f"{stage}_conversation.json",
            "seed": seed,
        })
        return argparse.Namespace(**values)

    initial_args = mixed_namespace("encounter", args.seed)
    with contextlib.redirect_stdout(io.StringIO()):
        command_run_mixed_conversation(initial_args)
    initial = json.loads(Path(initial_args.output).read_text(encoding="utf-8"))
    teaching_holds = [
        row for row in initial.get("turns", ())
        if row.get("state") == "HOLD_TEACHING_REQUIRED"
        and isinstance(row.get("teaching_request"), dict)
    ]
    relation_holds = [
        row for row in initial.get("turns", ())
        if row.get("state") in {"HOLD_UNSUPPORTED_QUESTION", "HOLD_UNGROUNDED_ANSWER"}
        and row.get("question_family") == "BINARY_Q2"
    ]
    missing_words = tuple(dict.fromkeys(
        str(word).strip().lower()
        for row in teaching_holds
        for word in row["teaching_request"].get("missing_words", ())
        if str(word).strip().lower().isascii() and str(word).strip().lower().isalpha()
    ))
    if not teaching_holds and not relation_holds:
        raise ValueError("learning conversation requires an unknown-word or unsupported-relation HOLD")

    dictionary_path = args.dictionary.resolve()
    dictionary_raw = dictionary_path.read_bytes()
    dictionary_sha256 = hashlib.sha256(dictionary_raw).hexdigest().upper()
    dictionary_rows = json.loads(dictionary_raw.decode("utf-8"))
    rows_by_word: dict[str, list[dict[str, Any]]] = {}
    for row in dictionary_rows:
        word = str(row.get("word", "")).strip().lower()
        if word:
            rows_by_word.setdefault(word, []).append(row)
    cpu_queries = [
        {
            "word": word,
            "state": "PASS_WORD_QUERY" if word in rows_by_word else "HOLD_HUMAN_REVIEW",
            "neuron_birth_allowed": word in rows_by_word,
            "definition_row_count": len(rows_by_word.get(word, ())),
        }
        for word in missing_words
    ]
    unknown_to_cpu = tuple(row["word"] for row in cpu_queries if not row["neuron_birth_allowed"])
    binary_teacher = json.loads(args.binary_teacher.resolve().read_text(encoding="utf-8"))
    if binary_teacher.get("schema") != "NN_CPU_PRIVATE_BINARY_RELATIONS_V1":
        raise ValueError("unsupported CPU-private binary teacher schema")
    facts_by_question = {
        " ".join(str(value).lower() for value in fact.get("question_surface", ())): fact
        for fact in binary_teacher.get("facts", ())
    }
    relation_queries: list[dict[str, Any]] = []
    selected_relation_facts: list[dict[str, Any]] = []
    for row in relation_holds:
        question = " ".join(str(row.get("input", "")).lower().rstrip("?.!").split())
        fact = facts_by_question.get(question)
        relation_queries.append({
            "question": question,
            "state": "PASS_RELATION_QUERY" if fact is not None else "HOLD_HUMAN_REVIEW",
            "relation_learning_allowed": fact is not None,
            "fact_id": str(fact.get("fact_id")) if fact is not None else None,
        })
        if fact is not None:
            selected_relation_facts.append(fact)
    unknown_relations = tuple(
        row["question"] for row in relation_queries if not row["relation_learning_allowed"]
    )
    query_receipt = {
        "schema": "NN_CONVERSATIONAL_CPU_WORD_QUERY_V1",
        "dictionary": str(dictionary_path),
        "dictionary_sha256": dictionary_sha256,
        "queries": cpu_queries,
        "unknown_to_cpu": list(unknown_to_cpu),
        "relation_queries": relation_queries,
        "unknown_relations": list(unknown_relations),
    }
    query_path = evidence_dir / "cpu_word_query.json"
    query_path.write_text(json.dumps(query_receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if unknown_to_cpu or unknown_relations:
        after_hold = {
            "graph": _persistent_sqlite_hashes(args.graph.resolve()),
            "curriculum": _persistent_sqlite_hashes(args.curriculum_db.resolve()),
        }
        if after_hold != before:
            raise RuntimeError("persistent state changed before CPU-unknown human-review HOLD")
        report = {
            "schema": "NN_ONLINE_LEARNING_CONVERSATION_V1",
            "state": "HOLD_HUMAN_REVIEW",
            "reason": (
                "CPU_DICTIONARY_DOES_NOT_KNOW_REQUIRED_WORD"
                if unknown_to_cpu else "CPU_TEACHER_DOES_NOT_KNOW_REQUIRED_RELATION"
            ),
            "initial_conversation": str(initial_args.output),
            "cpu_word_query": str(query_path),
            "missing_words": list(missing_words),
            "unknown_to_cpu": list(unknown_to_cpu),
            "unknown_relations": list(unknown_relations),
            "persistent_hashes_before": before,
            "persistent_hashes_after": after_hold,
            "candidate_only": True,
            "promotion_performed": False,
            "deployment_performed": False,
        }
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2

    canonical_words = sorted(
        {
            str(row.get("word", "")).lower()
            for row in dictionary_rows
            if str(row.get("word", "")).isalpha() and str(row.get("word", "")).isascii()
        },
        key=lambda value: (len(value), value),
    )
    ranks = {word: index for index, word in enumerate(canonical_words, 1)}
    lessons = [{"rank": ranks[word], "word": word, "count": 1} for word in missing_words]
    corpus = {
        "schema": "NN_BOOK_WORD_CORPUS_V1",
        "source": {"path": str(dictionary_path), "sha256": dictionary_sha256, "kind": "WEBSTER_DICTIONARY_HEADWORD_CPU_QUERY"},
        "corpus_sha256": hashlib.sha256(
            json.dumps(lessons, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest().upper(),
        "ordering": "CPU_QUERY_REQUIRED_WORDS",
        "lessons": lessons,
        "synthetic_examples": 0,
    }
    corpus_path = evidence_dir / "queried_word_corpus.json"
    word_report_path = evidence_dir / "word_learning_report.json"
    hydra_bin = args.hydra_bin.resolve() if args.hydra_bin is not None else None
    hydra_trace = evidence_dir / "hydra_word_masks.jsonl" if hydra_bin is not None else None
    word_learning: dict[str, Any] = {"schema": "NN_UNIVERSAL_BOOK_CURRICULUM_RESULT_V1", "state": "PASS", "results": []}
    if lessons:
        corpus_path.write_text(json.dumps(corpus, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            word_code = command_learn_book(argparse.Namespace(
            corpus=corpus_path, graph=args.graph, curriculum_db=args.curriculum_db,
            trace=evidence_dir / "word_learning_trace.jsonl", limit=len(lessons),
            min_length=1, max_length=1_000_000, rehearse_learned=False,
            max_attempts=args.max_word_attempts, confirmations=args.word_confirmations,
            seed=args.seed + 100_000, live_render_delay_ms=0.0, status=None,
            heartbeat_seconds=1.0, min_free_gb=5.0, resource_governed=False,
            assembly_evidence=True, self_discovery=True, prefix_free_suffix=True,
            resource_slowdown_seconds=1.0, resource_max_seconds=3600.0,
            ram_reserve_gb=4.0, vram_reserve_mb=512.0,
            cpu_ceiling_percent=95.0, gpu_ceiling_percent=95.0,
            power_ceiling_percent=95.0, report=word_report_path,
            hydra_bin=hydra_bin, hydra_trace=hydra_trace,
            ))
        word_learning = json.loads(word_report_path.read_text(encoding="utf-8"))
        if word_code != 0 or word_learning.get("state") != "PASS":
            raise RuntimeError("CPU-known conversational vocabulary did not learn")

    relation_teaching: list[dict[str, Any]] = []
    regenerated_binary_receipts = list(args.binary_learning_receipt)
    for index, fact in enumerate(selected_relation_facts, 1):
        teaching_path = evidence_dir / f"relation_teaching_{index:02d}.json"
        with contextlib.redirect_stdout(io.StringIO()):
            relation_code = command_run_binary_teaching_session(argparse.Namespace(
                dictionary=args.dictionary, teacher=args.binary_teacher,
                fact_id=str(fact["fact_id"]), teaching_answer="yes" if fact["truth"] else "no",
                graph=args.graph, curriculum_db=args.curriculum_db,
                hydra_bin=args.hydra_bin,
                evidence_dir=evidence_dir / f"relation_teaching_{index:02d}_evidence",
                output=teaching_path, seed=args.seed + 150_000 + index,
                max_attempts=args.max_relation_attempts,
                confirmations=args.confirmations,
                confirmation_seed_mode="nearby", consolidate_confirmations=True,
            ))
        teaching_receipt = json.loads(teaching_path.read_text(encoding="utf-8"))
        relation_teaching.append({
            "fact_id": str(fact["fact_id"]),
            "path": str(teaching_path),
            "learning_receipt": str(teaching_receipt.get("learning_receipt", "")),
            "state": teaching_receipt.get("state"),
            "question_learned_during_session": teaching_receipt.get("question_learned_during_session"),
        })
        if relation_code != 0 or teaching_receipt.get("state") != "PASS":
            raise RuntimeError("CPU-known conversational relation did not learn")
        regenerated_binary_receipts.append(str(teaching_receipt["learning_receipt"]))

    regenerated_args = mixed_namespace("regenerated", args.seed + 200_000)
    regenerated_args.binary_learning_receipt = regenerated_binary_receipts
    with contextlib.redirect_stdout(io.StringIO()):
        command_run_mixed_conversation(regenerated_args)
    regenerated = json.loads(Path(regenerated_args.output).read_text(encoding="utf-8"))
    regenerated_by_input = {str(row.get("input")): row for row in regenerated.get("turns", ())}
    repaired = all(
        not str(regenerated_by_input.get(str(row.get("input")), {}).get("state", "")).startswith("HOLD_TEACHING")
        for row in teaching_holds
    )
    relation_repaired = all(
        regenerated_by_input.get(str(row.get("input")), {}).get("state") == "PASS_GROUNDED_RESPONSE"
        and regenerated_by_input.get(str(row.get("input")), {}).get("response")
            == ("yes." if bool(fact["truth"]) else "no.")
        for row, fact in zip(relation_holds, selected_relation_facts, strict=True)
    )
    changed_inputs = {
        str(row.get("input")) for row in (*teaching_holds, *relation_holds)
    }
    control_turns_preserved = all(
        regenerated_by_input.get(str(row.get("input")), {}).get("state") == row.get("state")
        and regenerated_by_input.get(str(row.get("input")), {}).get("response") == row.get("response")
        for row in initial.get("turns", ())
        if str(row.get("input")) not in changed_inputs
    )
    with SQLiteNeuronGraphStore(args.graph.resolve(), readonly=True) as store:
        manifest_after = store.manifest()
        audit = store.audit()
    after = {
        "graph": _persistent_sqlite_hashes(args.graph.resolve()),
        "curriculum": _persistent_sqlite_hashes(args.curriculum_db.resolve()),
    }
    accepted = (
        repaired
        and relation_repaired
        and all(word in manifest_after["word_index"] for word in missing_words)
        and all(row.get("state") == "PASS" for row in relation_teaching)
        and control_turns_preserved
        and regenerated.get("persistent_state_unchanged") is True
        and audit.get("state") == "PASS"
    )
    report = {
        "schema": "NN_ONLINE_LEARNING_CONVERSATION_V1",
        "state": "PASS" if accepted else "HOLD",
        "initial_conversation": str(initial_args.output),
        "cpu_word_query": str(query_path),
        "missing_words": list(missing_words),
        "word_learning": word_learning,
        "relation_teaching": relation_teaching,
        "regenerated_conversation": str(regenerated_args.output),
        "regenerated_turns": regenerated.get("turns", ()),
        "teaching_holds_repaired": repaired,
        "relation_holds_repaired": relation_repaired,
        "control_turns_preserved": control_turns_preserved,
        "graph_audit": audit,
        "persistent_hashes_before": before,
        "persistent_hashes_after": after,
        "candidate_only": True,
        "canonical_mutation_authorized": False,
        "promotion_performed": False,
        "deployment_performed": False,
    }
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if accepted else 2


def command_run_autonomous_teaching(args: argparse.Namespace) -> int:
    """Execute a frozen, bounded lesson board through existing teaching paths.

    The supervisor owns sequencing and receipts only.  GPU route choice, CPU
    one-bit judgment, Hydra filtering, sentence learning, and mixed recall stay
    in their existing implementations.  It has no promotion or task authority.
    """

    from .steel_brain_store import SQLiteNeuronGraphStore

    board_path = args.lesson_board.resolve()
    board = json.loads(board_path.read_text(encoding="utf-8"))
    if (
        board.get("schema") != "NN_AUTONOMOUS_TEACHING_BOARD_V1"
        or board.get("candidate_only") is not True
    ):
        raise ValueError("autonomous teaching requires a candidate-only V1 board")
    lessons = list(board.get("lessons", ()))
    controls = list(board.get("controls", ()))
    if not lessons or len(lessons) > args.max_lessons:
        raise ValueError("autonomous lesson count is outside its frozen bound")
    evidence_dir = args.evidence_dir.resolve()
    output_path = args.output.resolve()
    if evidence_dir.exists() or output_path.exists():
        raise FileExistsError("autonomous teaching evidence is append-only")
    evidence_dir.mkdir(parents=True)
    before = {
        "graph": _persistent_sqlite_hashes(args.graph.resolve()),
        "curriculum": _persistent_sqlite_hashes(args.curriculum_db.resolve()),
    }
    social_receipts = [str(Path(value).resolve()) for value in (args.social_learning_receipt or ())]
    lesson_results: list[dict[str, Any]] = []

    def resolve_board_path(value: object) -> Path:
        path = Path(str(value))
        return path.resolve() if path.is_absolute() else (board_path.parent / path).resolve()

    def run_probe(label: str, turns: list[str], seed: int) -> dict[str, Any]:
        probe_dir = evidence_dir / label
        probe_output = evidence_dir / f"{label}.json"
        values = dict(vars(args))
        values.update({
            "turns": "|".join(turns),
            "evidence_dir": probe_dir,
            "output": probe_output,
            "seed": seed,
            "max_turns": len(turns),
            "social_learning_receipt": list(social_receipts),
        })
        with contextlib.redirect_stdout(io.StringIO()):
            command_run_mixed_conversation(argparse.Namespace(**values))
        return json.loads(probe_output.read_text(encoding="utf-8"))

    for lesson_index, lesson in enumerate(lessons, 1):
        lesson_id = str(lesson.get("lesson_id", "")).strip()
        prompt = str(lesson.get("prompt", "")).strip()
        expected_response = str(lesson.get("expected_response", "")).strip()
        fact_ids = [str(value) for value in lesson.get("fact_ids", ())]
        teacher_path = resolve_board_path(lesson.get("teacher"))
        if not lesson_id or not prompt or not expected_response or not fact_ids:
            raise ValueError("autonomous lesson is incomplete")
        pre = run_probe(f"lesson_{lesson_index:02d}_pre", [prompt], args.seed + lesson_index * 10_000)
        pre_turn = pre.get("turns", [{}])[0]
        expected_pre_state = str(lesson.get("expected_pre_state", "HOLD_TEACHING_REQUIRED"))
        if pre_turn.get("state") != expected_pre_state:
            raise ValueError(f"lesson {lesson_id} precondition changed")
        learned_receipts: list[str] = []
        for fact_index, fact_id in enumerate(fact_ids, 1):
            stem = f"lesson_{lesson_index:02d}_fact_{fact_index:02d}"
            report_path = evidence_dir / f"{stem}.json"
            with contextlib.redirect_stdout(io.StringIO()):
                code = command_learn_svo(argparse.Namespace(
                    dictionary=args.dictionary,
                    teacher=teacher_path,
                    fact_id=fact_id,
                    graph=args.graph,
                    curriculum_db=args.curriculum_db,
                    trace=evidence_dir / f"{stem}_trace.jsonl",
                    report=report_path,
                    seed=args.seed + lesson_index * 100_000 + fact_index * 1_003,
                    max_attempts=args.max_attempts,
                    confirmations=args.confirmations,
                    hydra_bin=args.hydra_bin,
                    hydra_trace=evidence_dir / f"{stem}_hydra.jsonl",
                    authorization_target=None,
                    authorization_receipt=None,
                    inference_receipt=None,
                    response_proposal=None,
                ))
            learned = json.loads(report_path.read_text(encoding="utf-8"))
            if code != 0 or learned.get("state") != "PASS":
                raise RuntimeError(f"lesson {lesson_id} fact {fact_id} did not learn")
            learned_receipts.append(str(report_path))
            social_receipts.append(str(report_path))
        post = run_probe(f"lesson_{lesson_index:02d}_post", [prompt], args.seed + lesson_index * 10_000 + 1)
        post_turn = post.get("turns", [{}])[0]
        lesson_passed = (
            post_turn.get("state") == "PASS_SOCIAL_RESPONSE"
            and post_turn.get("response") == expected_response
            and post.get("persistent_state_unchanged") is True
        )
        lesson_results.append({
            "lesson_id": lesson_id,
            "prompt": prompt,
            "expected_pre_state": expected_pre_state,
            "observed_pre_state": pre_turn.get("state"),
            "fact_ids": fact_ids,
            "learning_receipts": learned_receipts,
            "observed_post_state": post_turn.get("state"),
            "observed_response": post_turn.get("response"),
            "passed": lesson_passed,
        })
        if not lesson_passed:
            break

    control_prompts = [str(row.get("prompt", "")).strip() for row in controls]
    control_report = (
        run_probe("final_controls", control_prompts, args.seed + 900_000)
        if control_prompts and all(row["passed"] for row in lesson_results)
        else None
    )
    control_results: list[dict[str, Any]] = []
    if control_report is not None:
        for contract, turn in zip(controls, control_report.get("turns", ()), strict=True):
            expected_state = str(contract.get("expected_state", ""))
            expected_response_value = contract.get("expected_response")
            passed = (
                turn.get("state") == expected_state
                and turn.get("response") == expected_response_value
            )
            control_results.append({
                "prompt": contract["prompt"],
                "expected_state": expected_state,
                "expected_response": expected_response_value,
                "observed_state": turn.get("state"),
                "observed_response": turn.get("response"),
                "passed": passed,
            })
    with SQLiteNeuronGraphStore(args.graph.resolve(), readonly=True) as store:
        audit = store.audit()
    after = {
        "graph": _persistent_sqlite_hashes(args.graph.resolve()),
        "curriculum": _persistent_sqlite_hashes(args.curriculum_db.resolve()),
    }
    accepted = (
        len(lesson_results) == len(lessons)
        and all(row["passed"] for row in lesson_results)
        and len(control_results) == len(controls)
        and all(row["passed"] for row in control_results)
        and control_report is not None
        and control_report.get("persistent_state_unchanged") is True
        and audit.get("state") == "PASS"
        and audit.get("event_chain_valid") is True
    )
    report = {
        "schema": "NN_AUTONOMOUS_TEACHING_REPORT_V1",
        "state": "PASS" if accepted else "HOLD",
        "lesson_board": str(board_path),
        "lesson_board_sha256": hashlib.sha256(board_path.read_bytes()).hexdigest().upper(),
        "lesson_results": lesson_results,
        "control_results": control_results,
        "social_learning_receipts": social_receipts,
        "graph_audit": audit,
        "persistent_hashes_before": before,
        "persistent_hashes_after": after,
        "candidate_only": True,
        "canonical_mutation_authorized": False,
        "task_authority": False,
        "promotion_performed": False,
        "deployment_performed": False,
    }
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if accepted else 2


def command_learn_grammar_bucket(args: argparse.Namespace) -> int:
    """Exhaust one bounded GPU-selected word bucket against CPU grammar only."""

    from .leakage_audit import audit_gpu_payload
    from .steel_brain_store import SQLiteNeuronGraphStore

    dictionary_path = args.dictionary.resolve()
    graph_path = args.graph.resolve()
    curriculum_path = args.curriculum_db.resolve()
    hydra_bin = args.hydra_bin.resolve() if args.hydra_bin is not None else None
    hydra_trace = args.hydra_trace.resolve() if args.hydra_trace is not None else None
    if (hydra_bin is None) != (hydra_trace is None):
        raise ValueError("sentence Hydra requires both --hydra-bin and --hydra-trace")
    if hydra_bin is not None and not hydra_bin.is_file():
        raise FileNotFoundError(hydra_bin)
    bucket_words = tuple(
        dict.fromkeys(value.strip().lower() for value in args.words.split(",") if value.strip())
    )
    if len(bucket_words) < 3:
        raise ValueError("grammar bucket requires at least three distinct words")
    dictionary_raw = dictionary_path.read_bytes()
    dictionary_rows = json.loads(dictionary_raw.decode("utf-8"))
    role_support: dict[str, set[str]] = {word: set() for word in bucket_words}
    for row in dictionary_rows:
        word = str(row.get("word", "")).strip().lower()
        if word not in role_support:
            continue
        channel = WEBSTER_OPAQUE_CLASS_MAP.get(str(row.get("pos", "")).strip().lower())
        if channel is not None:
            role_support[word].add(channel)
    missing_roles = sorted(word for word, support in role_support.items() if not support)
    if missing_roles:
        raise ValueError(f"bucket words lack supported grammatical roles: {missing_roles}")
    patterns = (("R0", "R1", "R0"), ("R0", "R1", "R0", "R3"))

    def judge(candidate: Sequence[str]) -> bool:
        words = tuple(str(value).lower().removeprefix("word:") for value in candidate)
        return any(
            len(words) == len(pattern)
            and all(channel in role_support.get(word, set()) for word, channel in zip(words, pattern))
            for pattern in patterns
        )

    trace_path = args.trace.resolve()
    if trace_path.exists():
        raise FileExistsError("grammar bucket trace is append-only; choose a fresh path")
    before = {
        "graph": _persistent_sqlite_hashes(graph_path),
        "curriculum": _persistent_sqlite_hashes(curriculum_path),
    }
    with SQLiteNeuronGraphStore(graph_path) as store:
        manifest = store.manifest()
        missing = sorted(word for word in bucket_words if word not in manifest["word_index"])
        if missing:
            raise ValueError(f"grammar bucket words are not admitted: {missing}")
        for word in bucket_words:
            neuron = store.load_neuron(str(manifest["word_index"][word]))
            if UniversalCurriculumEngine.WORD_CLASS_PROFILE_KEY not in neuron.get("center_attractor", {}):
                raise ValueError(f"word has not learned its opaque grammatical classes: {word}")
        with CurriculumStore(curriculum_path) as curriculum:
            word_ids = tuple(str(manifest["word_index"][word]) for word in bucket_words)
            inventory_context = Neuronizer._inventory_signature(word_ids)
            hydra_membrane = (
                HydraRouteMembrane(
                    curriculum, hydra_bin, hydra_trace, evidence_level="SENTENCE"
                )
                if hydra_bin is not None and hydra_trace is not None
                else None
            )
            engine = Neuronizer(store, CudaLibrary(), route_truth_provider=hydra_membrane)
            source_handle = hashlib.sha256(
                json.dumps(
                    {"words": bucket_words, "patterns": patterns, "route_length": args.route_length},
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest().upper()
            result = engine.learn_sentence_grammar_bucket(
                [f"WORD:{word}" for word in bucket_words],
                judge,
                route_length=args.route_length,
                seed=args.seed,
                source_handle=source_handle,
                target_sentences=args.target_sentences,
                max_attempts=args.max_attempts,
                trace_path=trace_path,
                route_truth_context=inventory_context,
                route_truth_evidence_writer=(
                    lambda route, passed: curriculum.apply_assembly_verdict(
                        level="SENTENCE",
                        inventory_context_sha256=inventory_context,
                        route=route,
                        passed=passed,
                    )
                ) if hydra_membrane is not None else None,
            )
            hydra_metrics = (
                hydra_membrane.metrics() if hydra_membrane is not None else {"enabled": False}
            )
        audit = store.audit()
        leakage = audit_gpu_payload(store.load_neuron(str(result["episode_id"])))
    after = {
        "graph": _persistent_sqlite_hashes(graph_path),
        "curriculum": _persistent_sqlite_hashes(curriculum_path),
    }
    report = {
        "schema": "NN_CUMULATIVE_GRAMMAR_BUCKET_REPORT_V1",
        "state": "PASS"
        if result.get("state") == "PASS" and audit["state"] == "PASS" and leakage["state"] == "PASS"
        else "HOLD",
        "dictionary_source_sha256": hashlib.sha256(dictionary_raw).hexdigest().upper(),
        "bucket_words": list(bucket_words),
        "opaque_grammar_patterns": [list(pattern) for pattern in patterns],
        "result": result,
        "graph_audit": audit,
        "leakage_audit": leakage,
        "hydra_route_membrane": hydra_metrics,
        "persistent_hashes_before": before,
        "persistent_hashes_after": after,
        "canonical_mutation_authorized": False,
        "promotion_performed": False,
        "deployment_performed": False,
    }
    report_path = args.report.resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "schema": report["schema"],
        "state": report["state"],
        "bucket_words": report["bucket_words"],
        "route_total": result.get("route_total"),
        "grammar_sentence_target": result.get("grammar_sentence_target"),
        "unique_routes_attempted": result.get("unique_routes_attempted"),
        "grammar_supported_routes": result.get("grammar_supported_routes"),
        "attempts": result.get("attempts"),
        "graph_audit": audit,
        "leakage_audit": leakage,
        "report": str(report_path),
        "trace": str(trace_path),
    }, ensure_ascii=False, indent=2))
    return 0 if report["state"] == "PASS" else 2


def command_learn_meaning_bucket(args: argparse.Namespace) -> int:
    """Exhaust current routes and open vocabulary demand only on proven need."""

    from .leakage_audit import audit_gpu_payload
    from .steel_brain_store import SQLiteNeuronGraphStore

    graph_path = args.graph.resolve()
    curriculum_path = args.curriculum_db.resolve()
    dictionary_path = args.dictionary.resolve()
    hydra_bin = args.hydra_bin.resolve() if args.hydra_bin is not None else None
    hydra_trace = args.hydra_trace.resolve() if args.hydra_trace is not None else None
    if (hydra_bin is None) != (hydra_trace is None):
        raise ValueError("sentence Hydra requires both --hydra-bin and --hydra-trace")
    if hydra_bin is not None and not hydra_bin.is_file():
        raise FileNotFoundError(hydra_bin)
    rows = json.loads(dictionary_path.read_text(encoding="utf-8"))
    bucket_words = tuple(
        dict.fromkeys(value.strip().lower() for value in args.words.split(",") if value.strip())
    )
    teacher: dict[str, set[str]] = {word: set() for word in bucket_words}
    roles: dict[str, set[str]] = {word: set() for word in bucket_words}
    for row in rows:
        word = str(row.get("word", "")).strip().lower()
        if word not in teacher:
            continue
        role = WEBSTER_OPAQUE_CLASS_MAP.get(str(row.get("pos", "")).strip().lower())
        if role:
            roles[word].add(role)
        blob = " ".join(str(value).lower() for value in row.get("definitions", []))
        for channel, needles in WEBSTER_OPAQUE_SEMANTIC_RULES.items():
            if any(needle in blob for needle in needles):
                teacher[word].add(channel)
    if any(not teacher[word] for word in bucket_words):
        raise ValueError("all bucket words require CPU-private semantic evidence")

    grammar_patterns = (("R0", "R1", "R0"), ("R0", "R1", "R0", "R3"))

    def grammar_judge(candidate: Sequence[str]) -> bool:
        words = tuple(str(value).lower().removeprefix("word:") for value in candidate)
        return any(
            len(words) == len(pattern)
            and all(channel in roles.get(word, set()) for word, channel in zip(words, pattern))
            for pattern in grammar_patterns
        )

    semantic_patterns = (("S0", "S2", "S1"), ("S0", "S2", "S1", "S4"), ("S0", "S3", "S4"))

    def meaning_judge(candidate: Sequence[str]) -> bool:
        words = tuple(str(value).lower().removeprefix("word:") for value in candidate)
        return any(
            len(words) == len(pattern)
            and all(channel in teacher.get(word, set()) for word, channel in zip(words, pattern))
            for pattern in semantic_patterns
        )

    trace_path = args.trace.resolve()
    if trace_path.exists():
        raise FileExistsError("meaning trace is append-only; choose a fresh path")
    before = {
        "graph": _persistent_sqlite_hashes(graph_path),
        "curriculum": _persistent_sqlite_hashes(curriculum_path),
    }
    with SQLiteNeuronGraphStore(graph_path) as store:
        with CurriculumStore(curriculum_path) as curriculum:
            manifest = store.manifest()
            word_ids = tuple(str(manifest["word_index"][word]) for word in bucket_words)
            inventory_context = Neuronizer._inventory_signature(word_ids)
            hydra_membrane = (
                HydraRouteMembrane(
                    curriculum, hydra_bin, hydra_trace, evidence_level="SENTENCE"
                )
                if hydra_bin is not None and hydra_trace is not None
                else None
            )
            engine = Neuronizer(store, CudaLibrary(), route_truth_provider=hydra_membrane)
            result = engine.learn_sentence_meaning_bucket(
                args.episode_id, grammar_judge, meaning_judge,
                seed=args.seed, target_sentences=args.target_sentences,
                max_attempts=args.max_attempts, trace_path=trace_path,
                route_truth_context=inventory_context,
                route_truth_evidence_writer=(
                    lambda route, passed: curriculum.apply_assembly_verdict(
                        level="SENTENCE",
                        inventory_context_sha256=inventory_context,
                        route=route,
                        passed=passed,
                    )
                ) if hydra_membrane is not None else None,
            )
            hydra_metrics = (
                hydra_membrane.metrics() if hydra_membrane is not None else {"enabled": False}
            )
        audit = store.audit()
        leakage = audit_gpu_payload(store.load_neuron(args.episode_id))
    after = {
        "graph": _persistent_sqlite_hashes(graph_path),
        "curriculum": _persistent_sqlite_hashes(curriculum_path),
    }
    report = {
        "schema": "NN_DEMAND_GATED_SEMANTIC_BUCKET_REPORT_V1",
        "state": "PASS"
        if result.get("state") == "PASS" and audit["state"] == "PASS" and leakage["state"] == "PASS"
        else "HOLD",
        "dictionary_source_sha256": hashlib.sha256(dictionary_path.read_bytes()).hexdigest().upper(),
        "bucket_words": list(bucket_words),
        "opaque_grammar_patterns": [list(value) for value in grammar_patterns],
        "opaque_semantic_patterns": [list(value) for value in semantic_patterns],
        "result": result,
        "graph_audit": audit,
        "leakage_audit": leakage,
        "hydra_route_membrane": hydra_metrics,
        "persistent_hashes_before": before,
        "persistent_hashes_after": after,
        "canonical_mutation_authorized": False,
        "promotion_performed": False,
    }
    output = json.dumps(report, ensure_ascii=False, indent=2)
    args.report.resolve().write_text(output + "\n", encoding="utf-8")
    print(output)
    # A verified expression HOLD is successful governor evidence, not a process error.
    verified_hold = (
        result.get("state") == "HOLD"
        and result.get("route_space_exhausted") is True
        and result.get("vocabulary_demand_bit") == 1
        and audit["state"] == "PASS"
        and leakage["state"] == "PASS"
    )
    return 0 if report["state"] == "PASS" or verified_hold else 2


def command_build_webster_corpus(args: argparse.Namespace) -> int:
    """Compile real Webster headwords into the universal word curriculum."""
    source = args.dictionary.resolve()
    raw = source.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    words = sorted(
        {
            str(row.get("word", "")).lower()
            for row in payload
            if str(row.get("word", "")).isalpha()
            and str(row.get("word", "")).isascii()
        },
        key=lambda value: (len(value), value),
    )
    lessons = [
        {"rank": rank, "word": word, "count": 1}
        for rank, word in enumerate(words, start=1)
    ]
    corpus_hash = hashlib.sha256(
        json.dumps(lessons, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest().upper()
    result = {
        "schema": "NN_BOOK_WORD_CORPUS_V1",
        "source": {
            "path": str(source),
            "sha256": hashlib.sha256(raw).hexdigest().upper(),
            "kind": "WEBSTER_DICTIONARY_HEADWORDS",
        },
        "corpus_sha256": corpus_hash,
        "ordering": "LENGTH_THEN_LEXICOGRAPHIC",
        "lessons": lessons,
        "synthetic_examples": 0,
    }
    destination = args.output.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(destination)
    print(json.dumps({
        "state": "PASS", "source_sha256": result["source"]["sha256"],
        "corpus_sha256": corpus_hash, "words": len(words), "output": str(destination),
    }, indent=2))
    return 0


def command_materialize_neuron_dictionary(args: argparse.Namespace) -> int:
    """Create a CPU-only prefix-folder view over canonical neuron identities.

    The folders are a deterministic navigation/pathfinding projection, never a
    second source of word memory. A multi-role word gets reference leaves in
    multiple folders, all pointing to the same canonical WORD neuron.
    """

    from .steel_brain_store import SQLiteNeuronGraphStore

    graph_path = args.graph.resolve()
    dictionary_path = args.dictionary.resolve()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"neuron dictionary output already exists: {output}")

    raw_dictionary = dictionary_path.read_bytes()
    dictionary_rows = json.loads(raw_dictionary.decode("utf-8"))
    roles_by_word: dict[str, set[str]] = {}
    for row in dictionary_rows:
        surface = str(row.get("word", "")).strip().lower()
        role = NEURON_DICTIONARY_ROLE_FOLDERS.get(str(row.get("pos", "")).strip().lower())
        if surface.isascii() and surface.isalpha() and role is not None:
            roles_by_word.setdefault(surface, set()).add(role)

    output.mkdir(parents=True)
    path_index: dict[str, list[dict[str, Any]]] = {}
    reference_count = 0
    role_counts = {role: 0 for role in (*NEURON_DICTIONARY_ROLE_FOLDERS.values(), "sentences")}
    grammar_roles = tuple(NEURON_DICTIONARY_ROLE_FOLDERS.values())
    grammar_transitions = {
        role: [candidate for candidate in grammar_roles if candidate != role]
        for role in grammar_roles
    }
    max_grammar_depth = max(1, int(args.max_grammar_depth))
    grammar_paths: list[tuple[str, ...]] = []

    def materialize_grammar_paths(root: Path, sequence: tuple[str, ...]) -> None:
        grammar_paths.append(sequence)
        if len(sequence) >= max_grammar_depth:
            return
        for successor in grammar_transitions[sequence[-1]]:
            child = root / successor
            child.mkdir(exist_ok=True)
            materialize_grammar_paths(child, (*sequence, successor))

    # A category folder is a grammar-state node. Child role folders encode the
    # next legal state. The same role is intentionally absent (no nouns/nouns
    # branch), while paths such as nouns/verbs/adjectives remain addressable.
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        for role in grammar_roles:
            role_root = output / letter / role
            role_root.mkdir(parents=True, exist_ok=True)
            materialize_grammar_paths(role_root, (role,))

    def write_leaf(relative: Path, payload: dict[str, Any]) -> None:
        nonlocal reference_count
        # The reference is duplicated across navigation nodes, never the
        # neuron payload itself. Every file resolves to the same neuron ID.
        destination = output / relative / f"{payload['neuron_id']}.ref.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        path_index.setdefault(str(payload["neuron_id"]), []).append({
            "path": relative.as_posix(),
            "logical_prefix_path": list(payload["logical_prefix_path"]),
            "kind": payload["kind"],
            "role": payload["role"],
        })
        reference_count += 1
        role_counts[payload["role"]] += 1

    with SQLiteNeuronGraphStore(graph_path, readonly=True) as store:
        manifest = store.manifest()
        word_index = manifest["word_index"]
        for surface, neuron_id in sorted(word_index.items()):
            word = str(surface).lower()
            if not word.isascii() or not word.isalpha():
                continue
            roles = sorted(roles_by_word.get(word, set()))
            if not roles:
                continue
            neuron = store.load_neuron(str(neuron_id))
            prefixes = [word[:length].upper() for length in range(2, len(word) + 1)]
            physical_prefixes = [
                f"_{prefix}" if prefix in WINDOWS_RESERVED_NEURON_DICTIONARY_PREFIXES else prefix
                for prefix in prefixes
            ]
            for role in roles:
                payload = {
                    "schema": "NN_NEURON_DICTIONARY_LEAF_V1",
                    "kind": "WORD",
                    "role": role,
                    "surface": word,
                    "logical_prefix_path": prefixes,
                    "neuron_id": str(neuron_id),
                    "token_id": store.token_id(str(neuron_id)),
                    "lifecycle": neuron["lifecycle"],
                    "canonical_graph": str(graph_path),
                    "cpu_navigation_only": True,
                }
                role_root = Path(word[0].upper(), role)
                for depth in range(len(physical_prefixes) + 1):
                    write_leaf(role_root / Path(*physical_prefixes[:depth]), payload)

        reverse_words = {str(neuron_id): str(surface).lower() for surface, neuron_id in word_index.items()}
        for neuron_id, metadata in sorted(manifest["neuron_index"].items()):
            if metadata.get("kind") != "SENTENCE" or metadata.get("lifecycle") != "STABLE":
                continue
            sentence = store.load_neuron(str(neuron_id))
            route_ids = [str(item) for item in sentence.get("center_attractor", {}).get("construction", [])]
            surfaces = [reverse_words[item] for item in route_ids if item in reverse_words]
            if not surfaces:
                continue
            marker = surfaces[0]
            prefixes = [marker[:length].upper() for length in range(2, len(marker) + 1)]
            physical_prefixes = [
                f"_{prefix}" if prefix in WINDOWS_RESERVED_NEURON_DICTIONARY_PREFIXES else prefix
                for prefix in prefixes
            ]
            payload = {
                "schema": "NN_NEURON_DICTIONARY_LEAF_V1",
                "kind": "SENTENCE",
                "role": "sentences",
                "surface": " ".join(surfaces),
                "logical_prefix_path": prefixes,
                "neuron_id": str(neuron_id),
                "token_id": store.token_id(str(neuron_id)),
                "lifecycle": sentence["lifecycle"],
                "construction": route_ids,
                "canonical_graph": str(graph_path),
                "cpu_navigation_only": True,
            }
            role_root = Path(marker[0].upper(), "sentences")
            for depth in range(len(physical_prefixes) + 1):
                write_leaf(role_root / Path(*physical_prefixes[:depth]), payload)
        audit = store.audit()

    index = {
        "schema": "NN_NEURON_DICTIONARY_PREFIX_TREE_V1",
        "state": "PASS" if audit["state"] == "PASS" else "HOLD",
        "graph": str(graph_path),
        "graph_sha256": _persistent_sqlite_hashes(graph_path)[str(graph_path)],
        "dictionary": str(dictionary_path),
        "dictionary_sha256": hashlib.sha256(raw_dictionary).hexdigest().upper(),
        "layout": "LETTER/ROLE/(NEXT_ROLE|PREFIX...)/neuron.ref.json",
        "reserved_prefix_escape": "leading underscore only for Windows device-name prefixes",
        "roles": ["nouns", "verbs", "adjectives", "adverbs", "sentences"],
        "grammar_transitions": grammar_transitions,
        "max_grammar_depth": max_grammar_depth,
        "grammar_paths": [list(path) for path in sorted(set(grammar_paths))],
        "reference_count": reference_count,
        "unique_neurons_referenced": len(path_index),
        "role_counts": role_counts,
        "neuron_paths": {key: sorted(value, key=lambda row: row["path"]) for key, value in sorted(path_index.items())},
        "graph_audit": audit,
        "cpu_navigation_only": True,
        "gpu_payload_mutated": False,
    }
    (output / "cpu_path_index.json").write_text(
        json.dumps(index, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "state": index["state"], "output": str(output), "reference_count": reference_count,
        "role_counts": role_counts, "graph_audit": audit["state"],
    }, indent=2))
    return 0 if index["state"] == "PASS" else 2


def command_status(args: argparse.Namespace) -> int:
    # Status is observational: never enable WAL or replay graph transactions.
    graph_path = args.graph.resolve()
    if graph_path.is_file() and graph_path.suffix.lower() in {".sqlite", ".sqlite3", ".db"}:
        from .steel_brain_store import SQLiteNeuronGraphStore

        store = SQLiteNeuronGraphStore(graph_path, readonly=True)
        material = "SQLITE_PRODUCTION_CANDIDATE"
    else:
        store = GraphStore(graph_path, readonly=True)
        material = "JSON_ROLLBACK_GRAPH"
    try:
        audit = store.audit()
    finally:
        close_store = getattr(store, "close", None)
        if callable(close_store):
            close_store()
    attempts = 0
    if args.curriculum_db.is_file():
        with contextlib.closing(sqlite3.connect(
            args.curriculum_db.resolve().as_uri() + "?mode=ro", uri=True
        )) as connection:
            attempts = int(connection.execute("SELECT COUNT(*) FROM attempts").fetchone()[0])
    latest_trace: dict[str, object] = {}
    if args.trace.is_file():
        with args.trace.open("rb") as handle:
            handle.seek(max(0, args.trace.stat().st_size - 1_000_000))
            lines = handle.read().decode("utf-8", errors="replace").splitlines()
        for line in reversed(lines):
            try:
                latest_trace = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
    print(
        json.dumps(
            {
                "schema": "NN_STEEL_BRAIN_STATUS_V1",
                "state": "PASS" if audit.get("state") == "PASS" else "HOLD",
                "graph": str(graph_path),
                "graph_material": material,
                "graph_audit": audit,
                "curriculum_attempts": attempts,
                "latest": {
                    "phase": latest_trace.get("phase"),
                    "word": latest_trace.get("lesson_expected"),
                    "output": latest_trace.get("lesson_selected"),
                    "verdict": latest_trace.get("verdict"),
                    "attempt": latest_trace.get("attempt_number"),
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_learn_book(args: argparse.Namespace) -> int:
    """Run the one universal live curriculum over complete observed book words."""
    corpus_path = args.corpus.resolve()
    graph_path = args.graph.resolve()
    hydra_bin = args.hydra_bin.resolve() if args.hydra_bin is not None else None
    hydra_trace = args.hydra_trace.resolve() if args.hydra_trace is not None else None
    hydra_deployment_path = graph_path.parent / "HYDRA_DEPLOYMENT.json"
    hydra_deployment: dict[str, object] | None = None
    if hydra_deployment_path.is_file():
        if hydra_bin is not None or hydra_trace is not None:
            raise ValueError("graph-local Hydra deployment cannot be overridden by command-line paths")
        hydra_deployment = json.loads(hydra_deployment_path.read_text(encoding="utf-8"))
        if hydra_deployment.get("schema") != "NN_HYDRA_LIVE_DEPLOYMENT_V1":
            raise ValueError("invalid live Hydra deployment schema")
        if not all(hydra_deployment.get(key) is True for key in ("accepted", "promoted", "deployed", "enabled")):
            raise ValueError("live Hydra deployment is not fully authorized")
        hydra_bin = Path(str(hydra_deployment["binary"])).resolve()
        hydra_trace = Path(str(hydra_deployment["trace"])).resolve()
        digest = hashlib.sha256(hydra_bin.read_bytes()).hexdigest().upper()
        if digest != str(hydra_deployment["binary_sha256"]):
            raise ValueError("live Hydra binary hash does not match deployment manifest")
    if (hydra_bin is None) != (hydra_trace is None):
        raise ValueError("live Hydra deployment requires both binary and trace")
    if hydra_bin is not None and not hydra_bin.is_file():
        raise FileNotFoundError(hydra_bin)
    persistent_hashes_before = {
        "graph": _persistent_sqlite_hashes(graph_path),
        "curriculum": _persistent_sqlite_hashes(args.curriculum_db.resolve()),
    }
    payload = json.loads(corpus_path.read_text(encoding="utf-8"))
    if payload.get("schema") != "NN_BOOK_WORD_CORPUS_V1":
        raise ValueError("learn-book requires the real complete-word book corpus")
    source_sha = str(payload["source"]["sha256"])
    strict_dictionary_composition = bool(
        getattr(args, "strict_dictionary_composition", False)
    )
    require_complete_shorter_lengths = bool(
        getattr(args, "require_complete_shorter_lengths", False)
    )
    if strict_dictionary_composition and args.min_length != args.max_length:
        raise ValueError(
            "strict dictionary composition requires one exact target length per run"
        )
    authorized_word_surfaces = frozenset(
        str(row["word"]) for row in payload["lessons"]
    )
    status_path = args.status.resolve() if args.status is not None else None
    started_utc = time.time()

    def write_status(state: str, **fields: object) -> None:
        if status_path is None:
            return
        status_path.parent.mkdir(parents=True, exist_ok=True)
        value = {
            "schema": "NN_STEEL_BRAIN_RUN_STATUS_V1",
            "state": state,
            "pid": os.getpid(),
            "source_corpus_sha256": source_sha,
            "graph": str(graph_path),
            "curriculum_database": str(args.curriculum_db.resolve()),
            "trace": str(args.trace.resolve()),
            "seed": args.seed,
            "started_unix": started_utc,
            "updated_unix": time.time(),
            **fields,
        }
        temporary = status_path.with_suffix(status_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(status_path)

    def disk_free_gb() -> float:
        return shutil.disk_usage(graph_path.anchor or graph_path).free / 1_000_000_000
    if graph_path.is_file() and graph_path.suffix.lower() in {".sqlite", ".sqlite3", ".db"}:
        from .steel_brain_store import SQLiteNeuronGraphStore

        store = SQLiteNeuronGraphStore(graph_path)
        graph_material = "SQLITE_PRODUCTION_CANDIDATE"
    else:
        store = GraphStore(graph_path)
        graph_material = "JSON_ROLLBACK_GRAPH"
    manifest = store.manifest()
    characters = set(manifest["character_index"])

    def stable_dictionary_composition_issue(surface: str, neuron_id: str) -> str:
        neuron = store.load_neuron(str(neuron_id))
        admission = str(
            neuron.get("center_attractor", {}).get("admission_state", "")
        )
        if neuron.get("kind") != "WORD" or neuron.get("lifecycle") != "STABLE":
            return "WORD_NOT_STABLE"
        children = list(neuron.get("children", []))
        if not children:
            return "WORD_HAS_NO_CONSTRUCTION"
        if "FROZEN_CONFIRMATIONS" not in admission:
            return "WORD_HAS_NO_FROZEN_CONFIRMATION_ADMISSION"
        if not strict_dictionary_composition:
            return ""
        reconstructed: list[str] = []
        for child_id in children:
            child = store.load_neuron(str(child_id))
            child_surface = UniversalCurriculumEngine._surface(child)
            reconstructed.append(child_surface)
            legal = child.get("kind") == "CHARACTER" or (
                child.get("kind") == "WORD"
                and child_surface in authorized_word_surfaces
                and len(child_surface) < len(surface)
            )
            if not legal:
                return f"ILLEGAL_CHILD_{child.get('kind', '')}"
        if "".join(reconstructed) != surface:
            return "CONSTRUCTION_DOES_NOT_RECONSTRUCT_WORD"
        return ""

    if require_complete_shorter_lengths:
        incomplete_shorter: list[str] = []
        for row in payload["lessons"]:
            surface = str(row["word"])
            if len(surface) >= args.min_length:
                continue
            neuron_id = manifest["word_index"].get(surface)
            if neuron_id is None:
                incomplete_shorter.append(surface)
                continue
            issue = stable_dictionary_composition_issue(surface, str(neuron_id))
            if issue:
                incomplete_shorter.append(f"{surface}:{issue}")
        if incomplete_shorter:
            raise RuntimeError(
                "HOLD_INCOMPLETE_SHORTER_WORD_LAYER "
                f"target_length={args.min_length} "
                f"count={len(incomplete_shorter)} "
                f"examples={','.join(incomplete_shorter[:12])}"
            )
    candidate_lessons = [
        row for row in payload["lessons"]
        if args.min_length <= len(str(row["word"])) <= args.max_length
        and (
            args.rehearse_learned
            or str(row["word"]) not in manifest["word_index"]
        )
        and all(character in characters for character in str(row["word"]))
    ]
    lesson_offset = max(0, int(getattr(args, "offset", 0)))
    lessons = candidate_lessons[lesson_offset:][: args.limit]
    trace_path = args.trace.resolve()
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []
    resource_governor = (
        LiveResourceRidGovernor(
            disk_path=graph_path.anchor or graph_path,
            disk_reserve_gb=args.min_free_gb,
            ram_reserve_gb=args.ram_reserve_gb,
            vram_reserve_mb=args.vram_reserve_mb,
            cpu_ceiling_percent=args.cpu_ceiling_percent,
            gpu_ceiling_percent=args.gpu_ceiling_percent,
            power_ceiling_percent=args.power_ceiling_percent,
            max_seconds=args.resource_max_seconds,
            slowdown_seconds=args.resource_slowdown_seconds,
        )
        if args.resource_governed else None
    )
    write_status(
        "RUNNING",
        graph_material=graph_material,
        lessons_requested=len(lessons),
        lessons_completed=0,
        disk_free_gb=disk_free_gb(),
        resource_governed=bool(resource_governor),
    )
    with CurriculumStore(args.curriculum_db.resolve()) as curriculum:
        hydra_membrane = (
            HydraRouteMembrane(curriculum, hydra_bin, hydra_trace)
            if hydra_bin is not None and hydra_trace is not None
            else None
        )
        engine = UniversalCurriculumEngine(
            store,
            CudaLibrary(),
            curriculum,
            assembly_evidence=bool(args.assembly_evidence),
            self_discovery=bool(args.self_discovery),
            prefix_free_suffix=bool(args.prefix_free_suffix),
            route_truth_provider=hydra_membrane,
            strict_dictionary_composition=strict_dictionary_composition,
            authorized_word_surfaces=authorized_word_surfaces,
        )
        with trace_path.open("a", encoding="utf-8", buffering=1) as trace:
            last_heartbeat = 0.0
            latest_resource: dict[str, object] = {}

            def publish(row: dict[str, object]) -> None:
                nonlocal last_heartbeat, latest_resource
                enriched = dict(row)
                enriched.update({
                    "source_corpus_sha256": source_sha,
                    "synthetic_example": False,
                    "complete_source_unit": True,
                })
                resource = enriched.get("resource_governor")
                if isinstance(resource, dict):
                    latest_resource = dict(resource)
                    enriched.update({
                        "resource_RID_t": resource.get("RID_t"),
                        "resource_delay_microseconds": resource.get("delay_microseconds"),
                        "resource_bottleneck": resource.get("bottleneck"),
                        "resource_headrooms": resource.get("headrooms"),
                    })
                trace.write(json.dumps(enriched, sort_keys=True) + "\n")
                free_gb = disk_free_gb()
                if free_gb < args.min_free_gb:
                    raise RuntimeError(
                        f"HOLD_DISK_FLOOR free_gb={free_gb:.3f} floor_gb={args.min_free_gb:.3f}"
                    )
                now = time.monotonic()
                if now - last_heartbeat >= args.heartbeat_seconds:
                    write_status(
                        "RUNNING",
                        graph_material=graph_material,
                        lessons_requested=len(lessons),
                        lessons_completed=len(results),
                        active_word=enriched.get("lesson_expected"),
                        attempt=enriched.get("attempt_number"),
                        phase=enriched.get("phase"),
                        verdict=enriched.get("verdict"),
                        disk_free_gb=free_gb,
                        resource_RID_t=enriched.get("resource_RID_t"),
                        resource_delay_microseconds=enriched.get(
                            "resource_delay_microseconds"
                        ),
                        resource_bottleneck=enriched.get("resource_bottleneck"),
                    )
                    last_heartbeat = now
                if args.live_render_delay_ms > 0:
                    time.sleep(args.live_render_delay_ms / 1000.0)

            for row in lessons:
                word = str(row["word"])
                lesson_id = "BOOK-" + hashlib.sha256(
                    f"{payload['corpus_sha256']}\0{int(row['rank'])}".encode("utf-8")
                ).hexdigest()[:32].upper()
                try:
                    result = engine.learn_word(
                        word,
                        lesson_id=lesson_id,
                        source_handle=f"{source_sha}:WORD_RANK:{int(row['rank'])}",
                        seed=args.seed ^ int(row["rank"]),
                        max_attempts=args.max_attempts,
                        confirmations=args.confirmations,
                        trace_sink=publish,
                        work_gate=(
                            resource_governor.pace
                            if resource_governor is not None else None
                        ),
                    )
                except RuntimeError as error:
                    if not str(error).startswith((
                        "HOLD_DISK_FLOOR", "HOLD_RESOURCE_RID_ZERO"
                    )):
                        raise
                    result = {
                        "state": "HOLD",
                        "reason": str(error),
                        "word": word,
                    }
                    if resource_governor is not None:
                        latest_resource = dict(resource_governor.current)
                        result["resource_governor"] = latest_resource
                        publish({
                            "phase": "RESOURCE_RID_STOP",
                            "level": "WORD",
                            "lesson_id": lesson_id,
                            "lesson_source": word,
                            "lesson_expected": word,
                            "lesson_selected": "",
                            "attempt_number": None,
                            "verdict": "HOLD",
                            "consequence": "HOLD",
                            "judge": "RESOURCE_RID_ZERO_SHORT_CIRCUIT",
                            "resource_governor": latest_resource,
                        })
                results.append({
                    "rank": int(row["rank"]), "word": word,
                    "occurrences": int(row["count"]), **result,
                })
                if result.get("state") != "PASS":
                    break
    audit = store.audit()
    composition_routes: list[dict[str, object]] = []
    composition_violations: list[dict[str, object]] = []
    if strict_dictionary_composition:
        for result in results:
            route_tokens: list[dict[str, object]] = []
            target_word = str(result["word"])
            for token_id in result.get("route", []):
                neuron = store.load_neuron(str(token_id))
                surface = UniversalCurriculumEngine._surface(neuron)
                token_row = {
                    "token_id": str(token_id),
                    "kind": str(neuron.get("kind", "")),
                    "surface": surface,
                    "length": len(surface),
                }
                route_tokens.append(token_row)
                legal = token_row["kind"] == "CHARACTER" or (
                    token_row["kind"] == "WORD"
                    and surface in authorized_word_surfaces
                    and len(surface) < len(target_word)
                )
                if not legal:
                    composition_violations.append({
                        "word": target_word,
                        **token_row,
                    })
            composition_routes.append({
                "word": target_word,
                "route": route_tokens,
                "reconstructed": "".join(
                    str(token["surface"]) for token in route_tokens
                ),
            })
    manifest_after = store.manifest()
    layer_surfaces = [
        str(row["word"]) for row in payload["lessons"]
        if args.min_length <= len(str(row["word"])) <= args.max_length
    ]
    layer_missing_after = [
        surface for surface in layer_surfaces
        if surface not in manifest_after["word_index"]
    ]
    layer_unstable_after: list[str] = []
    for surface in layer_surfaces:
        neuron_id = manifest_after["word_index"].get(surface)
        if neuron_id is None:
            continue
        issue = stable_dictionary_composition_issue(surface, str(neuron_id))
        if issue:
            layer_unstable_after.append(f"{surface}:{issue}")
    layer_complete = not layer_missing_after and not layer_unstable_after
    report = {
        "schema": "NN_UNIVERSAL_BOOK_CURRICULUM_RESULT_V1",
        "state": "PASS"
        if len(results) == len(lessons)
        and all(row.get("state") == "PASS" for row in results)
        and audit["state"] == "PASS"
        else "HOLD",
        "source_epub_sha256": source_sha,
        "graph_material": graph_material,
        "lessons_requested": len(lessons),
        "results": results,
        "graph_audit": audit,
        "curriculum_database": str(args.curriculum_db.resolve()),
        "trace": str(trace_path),
        "synthetic_examples": 0,
        "fragment_targets": 0,
        "strict_dictionary_composition": strict_dictionary_composition,
        "dictionary_composition": {
            "teacher_words": len(authorized_word_surfaces),
            "target_length": args.min_length if args.min_length == args.max_length else None,
            "shorter_layers_required": require_complete_shorter_lengths,
            "generic_combination_neurons_allowed": False
            if strict_dictionary_composition else None,
            "legal_piece_kinds": ["CHARACTER", "SHORTER_AUTHORIZED_WORD"]
            if strict_dictionary_composition else None,
            "routes": composition_routes,
            "violations": composition_violations,
            "all_routes_legal": not composition_violations,
        },
        "layer_gate": {
            "expected": len(layer_surfaces),
            "admitted_stable": len(layer_surfaces)
            - len(layer_missing_after) - len(layer_unstable_after),
            "missing": len(layer_missing_after),
            "unstable": len(layer_unstable_after),
            "complete": layer_complete,
            "missing_examples": layer_missing_after[:12],
            "unstable_examples": layer_unstable_after[:12],
        },
        "promotion_performed": bool(
            hydra_deployment is not None and hydra_deployment.get("promoted") is True
        ),
        "deployment_performed": bool(
            hydra_deployment is not None and hydra_deployment.get("deployed") is True
        ),
        "hydra_route_membrane": (
            {
                **hydra_membrane.metrics(),
                "deployment_manifest": str(hydra_deployment_path) if hydra_deployment is not None else None,
                "automatic_live_deployment": hydra_deployment is not None,
            }
            if hydra_membrane is not None else {"enabled": False}
        ),
    }
    if strict_dictionary_composition and composition_violations:
        report["state"] = "HOLD"
    write_status(
        report["state"],
        graph_material=graph_material,
        lessons_requested=len(lessons),
        lessons_completed=sum(row.get("state") == "PASS" for row in results),
        disk_free_gb=disk_free_gb(),
        result=report["state"],
        resource_RID_t=latest_resource.get("RID_t") if resource_governor else None,
        resource_delay_microseconds=(
            latest_resource.get("delay_microseconds") if resource_governor else None
        ),
        resource_bottleneck=(
            latest_resource.get("bottleneck") if resource_governor else None
        ),
    )
    close_store = getattr(store, "close", None)
    if callable(close_store):
        close_store()
    if resource_governor is not None:
        resource_governor.close()
    report["persistent_hashes_before"] = persistent_hashes_before
    report["persistent_hashes_after"] = {
        "graph": _persistent_sqlite_hashes(graph_path),
        "curriculum": _persistent_sqlite_hashes(args.curriculum_db.resolve()),
    }
    if args.report is not None:
        destination = args.report.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["state"] == "PASS" else 2


def command_bootstrap_word_ladder(args: argparse.Namespace) -> int:
    """Create a clean candidate whose only construction layer is characters."""
    from .steel_brain_store import SQLiteNeuronGraphStore

    corpus_path = args.corpus.resolve()
    graph_path = args.graph.resolve()
    curriculum_path = args.curriculum_db.resolve()
    report_path = args.report.resolve()
    payload = json.loads(corpus_path.read_text(encoding="utf-8"))
    if payload.get("schema") != "NN_BOOK_WORD_CORPUS_V1":
        raise ValueError("word-ladder bootstrap requires the teacher word corpus")
    for path in (graph_path, curriculum_path, report_path):
        if path.exists():
            raise FileExistsError(path)
    surfaces = [str(row["word"]) for row in payload["lessons"]]
    characters = sorted({character for surface in surfaces for character in surface})
    neurons = [
        make_neuron(
            neuron_id=stable_character_neuron_id(character),
            kind="CHARACTER",
            lifecycle="STABLE",
            creation_event="WORD_LADDER_CHARACTER_FOUNDATION",
            foundation=True,
            center={
                "learned_character": character,
                "input_node_id": f"IN:{stable_character_neuron_id(character)}",
                "output_node_id": f"OUT:{stable_character_neuron_id(character)}",
                "activation_prior": SCALE,
                "truth_compatibility": SCALE,
                "trusted_language_memory": True,
                "construction_alignment": SCALE,
                "admission_state": "ARCHITECT_CHARACTER_FOUNDATION",
                "source_corpus_sha256": str(payload["source"]["sha256"]),
            },
        )
        for character in characters
    ]
    graph_path.parent.mkdir(parents=True, exist_ok=True)
    with SQLiteNeuronGraphStore(graph_path, create=True) as store:
        store.transact(
            neurons,
            event_kind="WORD_LADDER_CHARACTER_FOUNDATION",
            details={
                "characters": len(characters),
                "source_corpus_sha256": str(payload["source"]["sha256"]),
                "next_word_length": 1,
            },
        )
        audit = store.audit()
        manifest = store.manifest()
    with CurriculumStore(curriculum_path):
        pass
    report = {
        "schema": "NN_CUMULATIVE_WORD_LADDER_BOOTSTRAP_V1",
        "state": "PASS"
        if audit.get("state") == "PASS"
        and len(manifest["character_index"]) == len(characters)
        and not manifest["word_index"]
        and not manifest["combination_index"]
        else "HOLD",
        "source_corpus_sha256": str(payload["source"]["sha256"]),
        "graph": str(graph_path),
        "curriculum_database": str(curriculum_path),
        "characters": characters,
        "character_neurons": len(manifest["character_index"]),
        "word_neurons": len(manifest["word_index"]),
        "combination_neurons": len(manifest["combination_index"]),
        "next_word_length": 1,
        "graph_audit": audit,
        "persistent_hashes": {
            "graph": _persistent_sqlite_hashes(graph_path),
            "curriculum": _persistent_sqlite_hashes(curriculum_path),
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["state"] == "PASS" else 2


def command_migrate_store(args: argparse.Namespace) -> int:
    """Build one transactional SQLite candidate from the real JSON graph."""
    from .steel_brain_store import SQLiteNeuronGraphStore

    graph_root = args.graph.resolve()
    manifest_path = graph_root / "manifest.json"
    database = args.database.resolve()
    if database.exists():
        raise FileExistsError(f"production candidate already exists: {database}")

    def file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest().upper()

    manifest_before = file_sha256(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    selected = [
        str(entry["path"])
        for _neuron_id, entry in sorted(manifest["neuron_index"].items())
    ]
    imported_ids: list[str] = []
    round_trip_exact = True
    started = time.perf_counter()
    with SQLiteNeuronGraphStore(database, create=True) as store:
        for offset in range(0, len(selected), args.batch_size):
            rows = store.import_paths(
                graph_root, selected[offset : offset + args.batch_size]
            )
            for row in rows:
                imported_ids.append(row.neuron_id)
                round_trip_exact = round_trip_exact and (
                    hashlib.sha256(store.read_raw(row.neuron_id)).hexdigest().upper()
                    == row.source_sha256
                )
        audit = store.audit()
    manifest_after = file_sha256(manifest_path)
    python_probe = {
        "token_count": audit["tokens"],
        "link_count": audit["links"],
        "resolved_link_count": audit["token_links_resolved"],
        "weight_sum": audit["weight_sum"],
        "token_min": audit["token_min"],
        "token_max": audit["token_max"],
        "event_count": audit["events"],
    }
    rust_probe = CudaLibrary().steel_brain_store_probe(database)
    source_stable = manifest_before == manifest_after
    passed = (
        audit["state"] == "PASS"
        and len(imported_ids) == len(selected)
        and len(set(imported_ids)) == len(imported_ids)
        and round_trip_exact
        and python_probe == rust_probe
        and source_stable
    )
    report = {
        "schema": "NN_STEEL_BRAIN_PRODUCTION_MIGRATION_V1",
        "state": "PASS" if passed else "HOLD",
        "source": {
            "graph_root": str(graph_root),
            "manifest_sha256_before": manifest_before,
            "manifest_sha256_after": manifest_after,
            "source_stable_during_migration": source_stable,
            "neurons": len(selected),
        },
        "candidate": {
            "database": str(database),
            "database_sha256": file_sha256(database),
            "elapsed_seconds": time.perf_counter() - started,
            **audit,
        },
        "round_trip_exact": round_trip_exact,
        "python_rust_exact_parity": python_probe == rust_probe,
        "python_probe": python_probe,
        "rust_probe": rust_probe,
        "implemented": True,
        "executed": True,
        "accepted": False,
        "promoted": False,
        "deployed": False,
    }
    if args.receipt is not None:
        receipt = args.receipt.resolve()
        receipt.parent.mkdir(parents=True, exist_ok=True)
        temporary = receipt.with_suffix(receipt.suffix + ".tmp")
        temporary.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(receipt)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if passed else 2


def command_learn_word(args: argparse.Namespace) -> int:
    from .audit import append_command_log
    from .lexicon_training import sync_lexicon_from_word_registry
    from .word_engine import LearningControls, WordEngine

    state = _load_state(args.state)
    memory = state.get_or_create_word(args.word)
    controls = LearningControls.from_frontend(state.frontend)
    if args.max_attempts is not None:
        controls = LearningControls(**{**asdict(controls), "max_attempts": args.max_attempts})
    engine = WordEngine(controls)
    result = engine.learn_word(
        memory.word,
        memory,
        state.rotor_links,
        rng=random.Random(args.seed),
    )
    lexicon_added = sync_lexicon_from_word_registry(state)
    append_command_log(
        state,
        "learnWord",
        "PASS" if result.passed else "HOLD",
        summary=f"learnWord: {memory.word}",
        metrics={**result.public(), "lexiconAdded": lexicon_added},
    )
    state.metadata["last_command"] = "learn-word"
    state.metadata["last_result"] = result.public()
    state.save(args.state)
    print(
        json.dumps(
            {**result.public(), "lexicon_added": lexicon_added, "state_hash": state.content_hash()},
            indent=2,
        )
    )
    return 0


def command_resolve_sentence(args: argparse.Namespace) -> int:
    from .audit import append_command_log
    from .hierarchy import resolve_sentence
    from .hierarchy_persistence import persist_resolution

    state = _load_state(args.state)
    result = resolve_sentence(
        args.text,
        state.words,
        state.lexicon,
        sentence_model=state.hierarchy_model,
    )
    output: dict[str, object] = {"result": result.as_dict()}
    if args.persist:
        output["persistence"] = persist_resolution(
            state, result, mode="SENTENCE_ONLY"
        )
        append_command_log(
            state,
            "resolveSentence",
            result.state,
            summary="resolveSentence: completed",
            metrics={
                "state": result.state,
                "stable": result.stable,
                "cycles": result.cycles,
                "protectedStateUnchanged": output["persistence"][
                    "protected_state_unchanged"
                ],
            },
        )
        state.save(args.state)
        output["state_hash"] = state.content_hash()
    else:
        output = result.as_dict()
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def command_resolve_paragraph(args: argparse.Namespace) -> int:
    from .audit import append_command_log
    from .hierarchy import resolve_paragraph
    from .hierarchy_persistence import persist_resolution

    state = _load_state(args.state)
    result = resolve_paragraph(
        args.text,
        state.words,
        state.lexicon,
        sentence_model=state.hierarchy_model,
    )
    output: dict[str, object] = {"result": result.as_dict()}
    if args.persist:
        output["persistence"] = persist_resolution(state, result, mode="PARAGRAPH")
        append_command_log(
            state,
            "resolveParagraph",
            result.state,
            summary="resolveParagraph: completed",
            metrics={
                "state": result.state,
                "stable": result.stable,
                "cycles": result.details.get("cycles", 0),
                "protectedStateUnchanged": output["persistence"][
                    "protected_state_unchanged"
                ],
            },
        )
        state.save(args.state)
        output["state_hash"] = state.content_hash()
    else:
        output = result.as_dict()
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def command_resolve_page(args: argparse.Namespace) -> int:
    from .audit import append_command_log
    from .hierarchy import resolve_page
    from .hierarchy_persistence import persist_resolution

    state = _load_state(args.state)
    result = resolve_page(
        args.text,
        state.words,
        state.lexicon,
        sentence_model=state.hierarchy_model,
    )
    output: dict[str, object] = {"result": result.as_dict()}
    if args.persist:
        output["persistence"] = persist_resolution(state, result, mode="PAGE")
        append_command_log(
            state,
            "resolvePage",
            result.state,
            summary="resolvePage: completed",
            metrics={
                "state": result.state,
                "stable": result.stable,
                "cycles": result.details.get("cycles", 0),
                "stopPoint": result.details.get("stop_point", result.reason),
                "feedbackIntegrity": result.details.get("feedback_integrity", 0),
                "protectedStateUnchanged": output["persistence"][
                    "protected_state_unchanged"
                ],
            },
        )
        state.save(args.state)
        output["state_hash"] = state.content_hash()
    else:
        output = result.as_dict()
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def command_teach_sentence_model(args: argparse.Namespace) -> int:
    from .audit import append_command_log
    from .sentence_model import teach_sentence_model

    state = _load_state(args.state)
    result = teach_sentence_model(
        state,
        args.conllu,
        source_marker=args.source_marker,
    )
    append_command_log(
        state,
        "teachSentenceModel",
        "PASS",
        summary="teachSentenceModel: completed",
        metrics=result,
    )
    state.save(args.state)
    print(json.dumps({**result, "state_hash": state.content_hash()}, indent=2))
    return 0


def command_teach_lexicon(args: argparse.Namespace) -> int:
    from .audit import append_command_log
    from .lexicon_training import teach_lexicon

    state = _load_state(args.state)
    result = teach_lexicon(
        state,
        args.conllu,
        source_marker=args.source_marker,
    )
    append_command_log(
        state,
        "teachLexicon",
        "PASS",
        summary="teachLexicon: completed",
        metrics=result,
    )
    state.save(args.state)
    print(json.dumps({**result, "state_hash": state.content_hash()}, indent=2))
    return 0


def command_verify_recall(args: argparse.Namespace) -> int:
    from .recall import verify_frozen_vocabulary

    state = _load_state(args.state)
    result = verify_frozen_vocabulary(
        state,
        sample_size=args.sample_size,
        attempts_per_word=args.attempts_per_word,
        stop_on_exact=args.stop_on_exact == 1,
        seed=args.seed,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def command_verify_lexicon(args: argparse.Namespace) -> int:
    from .lexicon_verify import verify_lexicon

    state = _load_state(args.state)
    result = verify_lexicon(
        state,
        args.conllu,
        source_marker=args.source_marker,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def command_train_dictionary(args: argparse.Namespace) -> int:
    from .audit import append_command_log
    from .dictionary import load_wordlist, train_dictionary_batch

    state = _load_state(args.state)
    dictionary = load_wordlist(args.wordlist)
    result = train_dictionary_batch(
        state,
        dictionary,
        words_per_run=args.words_per_run,
        min_len=args.min_len,
        max_len=args.max_len,
        exclude_verified=not args.include_verified,
        seed=args.seed,
        max_attempts=args.max_attempts,
        save_path=args.state,
    )
    append_command_log(
        state,
        "trainDictionary",
        "PASS" if result.failed == 0 else "HOLD",
        summary="trainDictionary: completed",
        metrics=result.as_dict(),
    )
    state.save(args.state)
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return 0


def command_learn_hierarchy(args: argparse.Namespace) -> int:
    from .audit import append_command_log
    from .recursive_hierarchy import teach_hierarchy

    state = _load_state(args.state)
    result = teach_hierarchy(state, args.text, seed=args.seed)
    append_command_log(
        state,
        "learnHierarchy",
        result["state"],
        summary="learnHierarchy: recursive sentence/paragraph/page buckets",
        metrics={
            "state": result["state"],
            "reason": result.get("reason", ""),
            "pageId": result.get("page_id", ""),
            "levelCounts": result.get("level_counts", {}),
            "protectedStateUnchanged": result.get("protected_state_unchanged", False),
        },
    )
    state.metadata["last_command"] = "learn-hierarchy"
    state.metadata["last_result"] = result
    state.save(args.state)
    print(json.dumps({**result, "state_hash": state.content_hash()}, ensure_ascii=False, indent=2))
    return 0


def command_verify_hierarchy(args: argparse.Namespace) -> int:
    from .recursive_hierarchy import verify_hierarchy

    state = _load_state(args.state)
    result = verify_hierarchy(
        state,
        args.text,
        seed=args.seed,
        attempts_per_node=args.attempts_per_node,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nn-local")
    parser.add_argument(
        "--state",
        default="data/state.json",
        help="path to the local imported state JSON",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status")
    status.add_argument(
        "--graph",
        type=Path,
        default=Path("data/live/steel_brain_odyssey_two_letter_v1/neuron_graph_v1"),
    )
    status.add_argument(
        "--curriculum-db",
        type=Path,
        default=Path("data/live/steel_brain_odyssey_two_letter_v1/curriculum.sqlite3"),
    )
    status.add_argument(
        "--trace",
        type=Path,
        default=Path("verification/live/steel_brain_odyssey_two_letter_v1/universal_curriculum_live.jsonl"),
    )

    book = subparsers.add_parser(
        "learn-book",
        help="one universal live learner for complete observed book words",
    )
    book.add_argument("--corpus", type=Path, required=True)
    book.add_argument("--graph", type=Path, required=True)
    book.add_argument("--curriculum-db", type=Path, required=True)
    book.add_argument("--trace", type=Path, required=True)
    book.add_argument("--limit", type=int, default=1)
    book.add_argument(
        "--offset", type=int, default=0,
        help="skip this many eligible lessons after deterministic corpus filtering",
    )
    book.add_argument("--min-length", type=int, default=1)
    book.add_argument("--max-length", type=int, default=1_000_000)
    book.add_argument(
        "--rehearse-learned",
        action="store_true",
        help="re-run already admitted source-authentic lessons through the one-bit loop",
    )
    book.add_argument("--max-attempts", type=int, default=50_000)
    book.add_argument("--confirmations", type=int, default=3)
    book.add_argument("--seed", type=int, default=0)
    book.add_argument("--live-render-delay-ms", type=float, default=0.0)
    book.add_argument("--status", type=Path)
    book.add_argument("--heartbeat-seconds", type=float, default=1.0)
    book.add_argument("--min-free-gb", type=float, default=5.0)
    book.add_argument("--resource-governed", action="store_true")
    book.add_argument(
        "--assembly-evidence",
        action="store_true",
        help="apply target-free complete-route consequence evidence",
    )
    book.add_argument(
        "--self-discovery",
        action="store_true",
        help="apply earned target-free cross-word pattern guidance",
    )
    book.add_argument(
        "--prefix-free-suffix",
        action="store_true",
        help="use reusable structural suffix DP with route-specific assembly correction",
    )
    book.add_argument(
        "--strict-dictionary-composition",
        action="store_true",
        help=(
            "construct length-N words only from characters and CPU-authorized "
            "WORD neurons shorter than N; exclude generic combinations"
        ),
    )
    book.add_argument(
        "--require-complete-shorter-lengths",
        action="store_true",
        help="HOLD unless every shorter teacher-dictionary length is stable first",
    )
    book.add_argument("--resource-slowdown-seconds", type=float, default=1.0)
    book.add_argument("--resource-max-seconds", type=float, default=3600.0)
    book.add_argument("--ram-reserve-gb", type=float, default=4.0)
    book.add_argument("--vram-reserve-mb", type=float, default=512.0)
    book.add_argument("--cpu-ceiling-percent", type=float, default=95.0)
    book.add_argument("--gpu-ceiling-percent", type=float, default=95.0)
    book.add_argument("--power-ceiling-percent", type=float, default=95.0)
    book.add_argument("--report", type=Path)
    book.add_argument(
        "--hydra-bin",
        type=Path,
        help="accepted Rust Hydra binary used to compile hard route masks",
    )
    book.add_argument(
        "--hydra-trace",
        type=Path,
        help="append-only target-free trace of live Hydra route masks",
    )

    ladder_bootstrap = subparsers.add_parser(
        "bootstrap-word-ladder",
        help="create a clean candidate with character foundations and no prelearned words",
    )
    ladder_bootstrap.add_argument("--corpus", type=Path, required=True)
    ladder_bootstrap.add_argument("--graph", type=Path, required=True)
    ladder_bootstrap.add_argument("--curriculum-db", type=Path, required=True)
    ladder_bootstrap.add_argument("--report", type=Path, required=True)

    migrate = subparsers.add_parser(
        "migrate-store",
        help="build one lossless Python/Rust SQLite candidate from the live graph",
    )
    migrate.add_argument("--graph", type=Path, required=True)
    migrate.add_argument("--database", type=Path, required=True)
    migrate.add_argument("--receipt", type=Path)
    migrate.add_argument("--batch-size", type=int, default=512)

    webster = subparsers.add_parser(
        "build-webster-corpus",
        help="compile real Webster headwords into the universal word schema",
    )
    webster.add_argument("--dictionary", type=Path, required=True)
    webster.add_argument("--output", type=Path, required=True)

    neuron_dictionary = subparsers.add_parser(
        "materialize-neuron-dictionary",
        help="materialize the CPU-only grammar/prefix folder view of learned neurons",
    )
    neuron_dictionary.add_argument("--graph", type=Path, required=True)
    neuron_dictionary.add_argument("--dictionary", type=Path, required=True)
    neuron_dictionary.add_argument("--output", type=Path, required=True)
    neuron_dictionary.add_argument("--max-grammar-depth", type=int, default=4)

    frozen = subparsers.add_parser(
        "frozen-recall",
        help="run no-write fresh-seed recall over newest admitted words",
    )
    frozen.add_argument("--graph", type=Path, required=True)
    frozen.add_argument("--curriculum-db", type=Path, required=True)
    frozen.add_argument("--output", type=Path, required=True)
    frozen.add_argument("--limit", type=int, required=True)
    frozen.add_argument("--confirmations", type=int, default=3)
    frozen.add_argument("--seed", type=int, default=0)
    frozen.add_argument(
        "--mode", choices=("anchored", "unanchored"), default="anchored"
    )

    roles = subparsers.add_parser(
        "learn-roles",
        help="teach existing WORD neurons an opaque grammar or semantic probability group",
    )
    roles.add_argument("--dictionary", type=Path, required=True)
    roles.add_argument("--graph", type=Path, required=True)
    roles.add_argument("--curriculum-db", type=Path, required=True)
    role_selection = roles.add_mutually_exclusive_group(required=True)
    role_selection.add_argument("--words", help="comma-separated admitted words")
    role_selection.add_argument(
        "--length", type=int, choices=range(1, 65), metavar="N",
        help="teach every admitted source-authentic Webster word of exactly N letters",
    )
    roles.add_argument("--profile", choices=("grammar", "semantic"), default="grammar")
    roles.add_argument("--learning-rounds", type=int, default=8)
    roles.add_argument("--frozen-draws", type=int, default=156)
    roles.add_argument("--seed", type=int, default=0)
    roles.add_argument(
        "--offset", type=int, default=0,
        help="zero-based offset within a deterministic --length curriculum",
    )
    roles.add_argument(
        "--limit", type=int,
        help="bounded word count within a deterministic --length curriculum",
    )
    roles.add_argument("--report", type=Path)
    roles.add_argument(
        "--trace", type=Path,
        help="fresh append-only JSONL stream of real learning and frozen draws",
    )
    roles.add_argument(
        "--compact", action="store_true",
        help="retain profiles and evidence digests without embedding every draw",
    )

    identity_tags = subparsers.add_parser(
        "learn-identity-tags",
        help="teach CPU-authored opaque identity tags or return a no-write vocabulary HOLD",
    )
    identity_tags.add_argument("--identity-contract", type=Path, required=True)
    identity_tags.add_argument("--graph", type=Path, required=True)
    identity_tags.add_argument("--curriculum-db", type=Path, required=True)
    identity_tags.add_argument("--learning-rounds", type=int, default=8)
    identity_tags.add_argument("--frozen-draws", type=int, default=156)
    identity_tags.add_argument("--seed", type=int, default=0)
    identity_tags.add_argument("--words", help="optional comma-separated staged subset from the identity contract")
    identity_tags.add_argument("--report", type=Path)

    foundation_token = subparsers.add_parser(
        "learn-foundation-token",
        help="candidate-only protected foundation token learned through the normal CPU/GPU word path",
    )
    foundation_token.add_argument("--foundation-contract", type=Path, required=True)
    foundation_token.add_argument("--candidate-root", type=Path, required=True)
    foundation_token.add_argument("--graph", type=Path, required=True)
    foundation_token.add_argument("--curriculum-db", type=Path, required=True)
    foundation_token.add_argument("--token", required=True)
    foundation_token.add_argument("--trace", type=Path, required=True)
    foundation_token.add_argument("--report", type=Path, required=True)
    foundation_token.add_argument("--seed", type=int, default=0)
    foundation_token.add_argument("--max-attempts", type=int, default=2000)
    foundation_token.add_argument("--confirmations", type=int, default=3)
    foundation_token.add_argument("--hydra-bin", type=Path)
    foundation_token.add_argument("--hydra-trace", type=Path)

    svo = subparsers.add_parser(
        "learn-svo",
        help="self-generate one sentence with separate CPU grammar, meaning, and truth gates",
    )
    svo.add_argument("--dictionary", type=Path, required=True)
    svo.add_argument("--teacher", type=Path, required=True)
    svo.add_argument("--fact-id", required=True)
    svo.add_argument("--graph", type=Path, required=True)
    svo.add_argument("--curriculum-db", type=Path, required=True)
    svo.add_argument("--trace", type=Path, required=True)
    svo.add_argument("--report", type=Path, required=True)
    svo.add_argument("--seed", type=int, default=0)
    svo.add_argument("--max-attempts", type=int, default=1000)
    svo.add_argument("--confirmations", type=int, default=3)
    svo.add_argument("--hydra-bin", type=Path)
    svo.add_argument("--hydra-trace", type=Path)
    svo.add_argument("--authorization-target", type=Path)
    svo.add_argument("--authorization-receipt", type=Path)
    svo.add_argument("--inference-receipt", type=Path)
    svo.add_argument("--response-proposal", type=Path)

    utterance = subparsers.add_parser(
        "learn-utterance",
        help="self-generate a declarative or interrogative with three separate CPU gates",
    )
    utterance.add_argument("--dictionary", type=Path, required=True)
    utterance.add_argument("--teacher", type=Path, required=True)
    utterance.add_argument("--fact-id", required=True)
    utterance.add_argument("--graph", type=Path, required=True)
    utterance.add_argument("--curriculum-db", type=Path, required=True)
    utterance.add_argument("--trace", type=Path, required=True)
    utterance.add_argument("--report", type=Path, required=True)
    utterance.add_argument("--seed", type=int, default=0)
    utterance.add_argument("--max-attempts", type=int, default=1000)
    utterance.add_argument("--confirmations", type=int, default=3)
    utterance.add_argument("--hydra-bin", type=Path)
    utterance.add_argument("--hydra-trace", type=Path)

    dialogue_learn = subparsers.add_parser(
        "learn-dialogue-scene",
        help="teach source-bound fictional dialogue adjacency without truth authority",
    )
    dialogue_learn.add_argument("--scene", type=Path, required=True)
    dialogue_learn.add_argument("--graph", type=Path, required=True)
    dialogue_learn.add_argument("--curriculum-db", type=Path, required=True)
    dialogue_learn.add_argument("--trace", type=Path, required=True)
    dialogue_learn.add_argument("--report", type=Path, required=True)
    dialogue_learn.add_argument("--seed", type=int, default=0)
    dialogue_learn.add_argument("--max-attempts", type=int, default=1000)
    dialogue_learn.add_argument("--confirmations", type=int, default=8)

    dialogue_run = subparsers.add_parser(
        "run-dialogue-scene",
        help="fresh read-only recall of learned source-bound dialogue turns",
    )
    dialogue_run.add_argument("--graph", type=Path, required=True)
    dialogue_run.add_argument("--curriculum-db", type=Path, required=True)
    dialogue_run.add_argument("--turns", required=True, help="pipe-separated prompts")
    dialogue_run.add_argument("--output", type=Path, required=True)
    dialogue_run.add_argument("--seed", type=int, default=0)
    dialogue_run.add_argument("--confirmations", type=int, default=8)

    source_attach = subparsers.add_parser(
        "attach-source-provenance",
        help="attach one authenticated source record to a learned source phrase",
    )
    source_attach.add_argument("--learning-receipt", type=Path, required=True)
    source_attach.add_argument("--source", type=Path, required=True)
    source_attach.add_argument("--source-class", required=True)
    source_attach.add_argument("--source-title", required=True)
    source_attach.add_argument("--graph", type=Path, required=True)
    source_attach.add_argument("--curriculum-db", type=Path, required=True)
    source_attach.add_argument("--report", type=Path, required=True)

    provenance_bind = subparsers.add_parser(
        "bind-provenance-explanation",
        help="learn source relation to provenance to explanation navigation",
    )
    provenance_bind.add_argument("--learning-receipt", type=Path, required=True)
    provenance_bind.add_argument("--graph", type=Path, required=True)
    provenance_bind.add_argument("--curriculum-db", type=Path, required=True)
    provenance_bind.add_argument("--trace", type=Path, required=True)
    provenance_bind.add_argument("--report", type=Path, required=True)
    provenance_bind.add_argument("--seed", type=int, default=0)
    provenance_bind.add_argument("--max-attempts", type=int, default=1000)
    provenance_bind.add_argument("--confirmations", type=int, default=8)

    provenance_query = subparsers.add_parser(
        "query-provenance-explanation",
        help="cold read-only navigation to one learned provenance explanation",
    )
    provenance_relation = provenance_query.add_mutually_exclusive_group(required=True)
    provenance_relation.add_argument("--source-relation-id")
    provenance_relation.add_argument("--dialogue-relation-id")
    provenance_query.add_argument("--speaker", default="VIV")
    provenance_query.add_argument("--source-sha256")
    provenance_query.add_argument("--graph", type=Path, required=True)
    provenance_query.add_argument("--curriculum-db", type=Path, required=True)
    provenance_query.add_argument("--output", type=Path, required=True)
    provenance_query.add_argument("--seed", type=int, default=0)
    provenance_query.add_argument("--confirmations", type=int, default=8)

    review_request = subparsers.add_parser(
        "create-human-review-request",
        help="render a learned source-grounded request while holding unknown neuron birth",
    )
    review_request.add_argument("--source-relation-id", required=True)
    review_request.add_argument("--unknown-surface", required=True)
    review_request.add_argument("--provenance-query", type=Path, required=True)
    review_request.add_argument("--help-learning-receipt", type=Path, required=True)
    review_request.add_argument("--dictionary", type=Path, required=True)
    review_request.add_argument("--graph", type=Path, required=True)
    review_request.add_argument("--curriculum-db", type=Path, required=True)
    review_request.add_argument("--output", type=Path, required=True)
    review_request.add_argument("--seed", type=int, default=0)
    review_request.add_argument("--confirmations", type=int, default=8)

    reviewed_word = subparsers.add_parser(
        "admit-reviewed-source-word",
        help="consume a Hydra-authorized conversational review and learn its source-attested word",
    )
    reviewed_word.add_argument("--graph", type=Path, required=True)
    reviewed_word.add_argument("--curriculum-db", type=Path, required=True)
    reviewed_word.add_argument("--review-request", type=Path, required=True)
    reviewed_word.add_argument("--review-decision", type=Path, required=True)
    reviewed_word.add_argument("--authorization-receipt", type=Path, required=True)
    reviewed_word.add_argument("--trace", type=Path, required=True)
    reviewed_word.add_argument("--report", type=Path, required=True)
    reviewed_word.add_argument("--seed", type=int, default=1270001)
    reviewed_word.add_argument("--max-attempts", type=int, default=5000)
    reviewed_word.add_argument("--confirmations", type=int, default=8)
    reviewed_word.add_argument("--prefix-free-suffix", action="store_true")
    reviewed_word.add_argument("--character-prior-checkpoint", type=Path)
    reviewed_word.add_argument("--character-prior-vocab", type=Path)
    reviewed_word.add_argument("--route-proposal-transformer-checkpoint", type=Path)
    reviewed_word.add_argument("--route-proposal-beam-width", type=int, default=16)

    grounded_recall = subparsers.add_parser(
        "recall-grounded-question",
        help="fresh no-write recall of one learned question and trusted response",
    )
    grounded_recall.add_argument("--dictionary", type=Path, required=True)
    grounded_recall.add_argument("--teacher", type=Path, required=True)
    grounded_recall.add_argument("--learning-receipt", type=Path, required=True)
    grounded_recall.add_argument("--fact-id", required=True)
    grounded_recall.add_argument("--graph", type=Path, required=True)
    grounded_recall.add_argument("--curriculum-db", type=Path, required=True)
    grounded_recall.add_argument("--output", type=Path, required=True)
    grounded_recall.add_argument("--seed", type=int, default=0)
    grounded_recall.add_argument("--confirmations", type=int, default=3)

    conversation = subparsers.add_parser(
        "run-conversation",
        help="bounded read-only grounded conversation with ephemeral CPU context",
    )
    conversation.add_argument("--dictionary", type=Path, required=True)
    conversation.add_argument("--teacher", type=Path, required=True)
    conversation.add_argument("--learning-receipt", action="append", required=True)
    conversation.add_argument("--graph", type=Path, required=True)
    conversation.add_argument("--curriculum-db", type=Path, required=True)
    conversation.add_argument("--turns", required=True, help="pipe-separated prompts; RESET starts a fresh session")
    conversation.add_argument("--output", type=Path, required=True)
    conversation.add_argument("--seed", type=int, default=0)
    conversation.add_argument("--max-turns", type=int, default=12)
    conversation.add_argument("--context-ttl-seconds", type=float, default=60.0)
    conversation.add_argument("--confirmations", type=int, default=1)

    question_template = subparsers.add_parser(
        "learn-question-template",
        help="induce one reusable opaque interrogative transform from grounded pairs",
    )
    question_template.add_argument("--teacher", type=Path, required=True)
    question_template.add_argument("--fact-ids", required=True)
    question_template.add_argument("--learning-receipt", action="append", required=True)
    question_template.add_argument("--graph", type=Path, required=True)
    question_template.add_argument("--curriculum-db", type=Path, required=True)
    question_template.add_argument("--output", type=Path, required=True)

    social_intent = subparsers.add_parser(
        "learn-social-intent",
        help="induce one opaque social intent from multiple admitted question forms",
    )
    social_intent.add_argument("--teacher", type=Path, required=True)
    social_intent.add_argument("--dictionary", type=Path, required=True)
    social_intent.add_argument("--fact-ids", required=True)
    social_intent.add_argument("--learning-receipt", action="append", required=True)
    social_intent.add_argument("--graph", type=Path, required=True)
    social_intent.add_argument("--curriculum-db", type=Path, required=True)
    social_intent.add_argument("--output", type=Path, required=True)

    generalized_question = subparsers.add_parser(
        "generalize-question",
        help="learn one unseen grounded question through an admitted template",
    )
    generalized_question.add_argument("--question", required=True)
    generalized_question.add_argument("--template-id", required=True)
    generalized_question.add_argument("--graph", type=Path, required=True)
    generalized_question.add_argument("--curriculum-db", type=Path, required=True)
    generalized_question.add_argument("--trace", type=Path, required=True)
    generalized_question.add_argument("--report", type=Path, required=True)
    generalized_question.add_argument("--hydra-bin", type=Path, required=True)
    generalized_question.add_argument("--hydra-trace", type=Path, required=True)
    generalized_question.add_argument("--seed", type=int, default=0)
    generalized_question.add_argument("--max-attempts", type=int, default=1000)
    generalized_question.add_argument("--confirmations", type=int, default=3)
    generalized_question.add_argument("--capability-registry", type=Path)

    binary_relation = subparsers.add_parser(
        "learn-binary-relation",
        help="learn an answerable Q1 relation and a one-neuron yes/no response",
    )
    binary_relation.add_argument("--dictionary", type=Path, required=True)
    binary_relation.add_argument("--teacher", type=Path, required=True)
    binary_relation.add_argument("--fact-id", required=True)
    binary_relation.add_argument("--template-id")
    binary_relation.add_argument("--graph", type=Path, required=True)
    binary_relation.add_argument("--curriculum-db", type=Path, required=True)
    binary_relation.add_argument("--question-trace", type=Path, required=True)
    binary_relation.add_argument("--answer-trace", type=Path, required=True)
    binary_relation.add_argument("--question-hydra-trace", type=Path, required=True)
    binary_relation.add_argument("--answer-hydra-trace", type=Path, required=True)
    binary_relation.add_argument("--hydra-bin", type=Path, required=True)
    binary_relation.add_argument("--report", type=Path, required=True)
    binary_relation.add_argument("--seed", type=int, default=0)
    binary_relation.add_argument("--max-attempts", type=int, default=1000)
    binary_relation.add_argument("--confirmations", type=int, default=3)
    binary_relation.add_argument(
        "--confirmation-seed-mode", choices=("nearby", "spread"), default="nearby"
    )
    binary_relation.add_argument("--consolidate-confirmations", action="store_true")

    binary_conversation = subparsers.add_parser(
        "run-binary-conversation",
        help="bounded read-only conversation over learned yes/no relation answers",
    )
    binary_conversation.add_argument("--teacher", type=Path, required=True)
    # A first encounter has no prior learning receipt by definition.  The
    # read-only runtime must be able to return HOLD_UNSUPPORTED_QUESTION and
    # request teaching without fabricating a receipt.  Any receipts that are
    # supplied are still validated strictly by command_run_binary_conversation.
    binary_conversation.add_argument("--learning-receipt", action="append", default=[])
    binary_conversation.add_argument("--graph", type=Path, required=True)
    binary_conversation.add_argument("--curriculum-db", type=Path, required=True)
    binary_conversation.add_argument("--turns", required=True)
    binary_conversation.add_argument("--output", type=Path, required=True)
    binary_conversation.add_argument("--seed", type=int, default=0)
    binary_conversation.add_argument("--max-turns", type=int, default=12)
    binary_conversation.add_argument("--confirmations", type=int, default=1)
    binary_conversation.add_argument("--context-cap", type=int, default=4)

    binary_teaching = subparsers.add_parser(
        "run-binary-teaching-session",
        help="run one bounded unknown-to-grounded conversational truth lesson",
    )
    binary_teaching.add_argument("--dictionary", type=Path, required=True)
    binary_teaching.add_argument("--teacher", type=Path, required=True)
    binary_teaching.add_argument("--fact-id", required=True)
    binary_teaching.add_argument("--teaching-answer", choices=("yes", "no"), required=True)
    binary_teaching.add_argument("--graph", type=Path, required=True)
    binary_teaching.add_argument("--curriculum-db", type=Path, required=True)
    binary_teaching.add_argument("--hydra-bin", type=Path, required=True)
    binary_teaching.add_argument("--evidence-dir", type=Path, required=True)
    binary_teaching.add_argument("--output", type=Path, required=True)
    binary_teaching.add_argument("--seed", type=int, default=0)
    binary_teaching.add_argument("--max-attempts", type=int, default=1000)
    binary_teaching.add_argument("--confirmations", type=int, default=8)
    binary_teaching.add_argument(
        "--confirmation-seed-mode", choices=("nearby", "spread"), default="nearby"
    )
    binary_teaching.add_argument("--consolidate-confirmations", action="store_true")

    article_learning = subparsers.add_parser(
        "run-article-learning-session",
        help="encounter article facts, query CPU vocabulary, regenerate, and learn",
    )
    article_learning.add_argument("--dictionary", type=Path, required=True)
    article_learning.add_argument("--teacher", type=Path, required=True)
    article_learning.add_argument("--article-manifest", type=Path, required=True)
    article_learning.add_argument("--fact-id", action="append", required=True)
    article_learning.add_argument("--probe-word", action="append", default=[])
    article_learning.add_argument("--human-review-request", type=Path)
    article_learning.add_argument("--human-review-decision", type=Path)
    article_learning.add_argument("--human-authorization-receipt", type=Path)
    article_learning.add_argument("--graph", type=Path, required=True)
    article_learning.add_argument("--curriculum-db", type=Path, required=True)
    article_learning.add_argument("--hydra-bin", type=Path, required=True)
    article_learning.add_argument("--evidence-dir", type=Path, required=True)
    article_learning.add_argument("--output", type=Path, required=True)
    article_learning.add_argument("--seed", type=int, default=0)
    article_learning.add_argument("--max-word-attempts", type=int, default=10_000)
    article_learning.add_argument("--max-question-attempts", type=int, default=1_000)
    article_learning.add_argument("--word-confirmations", type=int, default=3)
    article_learning.add_argument("--question-confirmations", type=int, default=8)

    article_provenance = subparsers.add_parser(
        "attach-article-provenance",
        help="attach one receipt-backed article claim inside every participating neuron",
    )
    article_provenance.add_argument("--graph", type=Path, required=True)
    article_provenance.add_argument("--article-manifest", type=Path, required=True)
    article_provenance.add_argument("--teacher", type=Path, required=True)
    article_provenance.add_argument("--session-report", type=Path, required=True)
    article_provenance.add_argument("--output", type=Path, required=True)

    relation_provenance = subparsers.add_parser(
        "attach-relation-provenance",
        help="attach one accepted CPU binary relation source inside participating neurons",
    )
    relation_provenance.add_argument("--graph", type=Path, required=True)
    relation_provenance.add_argument("--teacher", type=Path, required=True)
    relation_provenance.add_argument("--learning-receipt", type=Path, required=True)
    relation_provenance.add_argument("--source-title", required=True)
    relation_provenance.add_argument("--output", type=Path, required=True)

    neuron_source = subparsers.add_parser(
        "query-neuron-source",
        help="read claim-level sources already stored inside one neuron",
    )
    neuron_source.add_argument("--graph", type=Path, required=True)
    neuron_selection = neuron_source.add_mutually_exclusive_group(required=True)
    neuron_selection.add_argument("--neuron-id")
    neuron_selection.add_argument("--surface")
    neuron_source.add_argument("--output", type=Path, required=True)

    addressed = subparsers.add_parser(
        "route-addressed-conversation",
        help="separate conversation from Would-you-kindly task proposals without granting authority",
    )
    addressed.add_argument("--graph", type=Path, required=True)
    addressed.add_argument("--curriculum-db", type=Path, required=True)
    addressed.add_argument("--turns", required=True, help="pipe-separated user turns")
    addressed.add_argument("--max-turns", type=int, default=12)
    addressed.add_argument("--output", type=Path, required=True)

    article_extract = subparsers.add_parser(
        "extract-article-binary-lesson",
        help="extract one bounded CPU-private binary lesson from a frozen article",
    )
    article_extract.add_argument("--source", type=Path, required=True)
    article_extract.add_argument("--title", required=True)
    article_extract.add_argument("--dictionary", type=Path, required=True)
    article_extract.add_argument("--candidate", required=True)
    article_extract.add_argument("--output-manifest", type=Path, required=True)
    article_extract.add_argument("--output-teacher", type=Path, required=True)
    article_extract.add_argument("--output-receipt", type=Path, required=True)

    mixed_conversation = subparsers.add_parser(
        "run-mixed-conversation",
        help="route descriptive and binary questions through one bounded session",
    )
    mixed_conversation.add_argument("--dictionary", type=Path, required=True)
    mixed_conversation.add_argument("--descriptive-teacher", type=Path, required=True)
    mixed_conversation.add_argument("--descriptive-learning-receipt", action="append", required=True)
    mixed_conversation.add_argument("--binary-teacher", type=Path, required=True)
    mixed_conversation.add_argument("--binary-learning-receipt", action="append", required=True)
    mixed_conversation.add_argument("--social-learning-receipt", type=Path, action="append")
    mixed_conversation.add_argument("--social-intent-receipt", type=Path, action="append")
    mixed_conversation.add_argument("--social-teacher", type=Path)
    mixed_conversation.add_argument("--graph", type=Path, required=True)
    mixed_conversation.add_argument("--curriculum-db", type=Path, required=True)
    mixed_conversation.add_argument("--turns", required=True)
    mixed_conversation.add_argument("--evidence-dir", type=Path, required=True)
    mixed_conversation.add_argument("--output", type=Path, required=True)
    mixed_conversation.add_argument("--seed", type=int, default=0)
    mixed_conversation.add_argument("--max-turns", type=int, default=12)
    mixed_conversation.add_argument("--confirmations", type=int, default=8)

    learning_conversation = subparsers.add_parser(
        "run-learning-conversation",
        help="query CPU-known unknown words, learn them, and regenerate conversation",
    )
    learning_conversation.add_argument("--dictionary", type=Path, required=True)
    learning_conversation.add_argument("--descriptive-teacher", type=Path, required=True)
    learning_conversation.add_argument("--descriptive-learning-receipt", action="append", required=True)
    learning_conversation.add_argument("--binary-teacher", type=Path, required=True)
    learning_conversation.add_argument("--binary-learning-receipt", action="append", required=True)
    learning_conversation.add_argument("--social-learning-receipt", type=Path, action="append")
    learning_conversation.add_argument("--social-intent-receipt", type=Path, action="append")
    learning_conversation.add_argument("--social-teacher", type=Path)
    learning_conversation.add_argument("--graph", type=Path, required=True)
    learning_conversation.add_argument("--curriculum-db", type=Path, required=True)
    learning_conversation.add_argument("--turns", required=True)
    learning_conversation.add_argument("--evidence-dir", type=Path, required=True)
    learning_conversation.add_argument("--output", type=Path, required=True)
    learning_conversation.add_argument("--seed", type=int, default=0)
    learning_conversation.add_argument("--max-turns", type=int, default=12)
    learning_conversation.add_argument("--confirmations", type=int, default=8)
    learning_conversation.add_argument("--max-word-attempts", type=int, default=50_000)
    learning_conversation.add_argument("--word-confirmations", type=int, default=3)
    learning_conversation.add_argument("--max-relation-attempts", type=int, default=1_000)
    learning_conversation.add_argument("--hydra-bin", type=Path)

    autonomous_teaching = subparsers.add_parser(
        "run-autonomous-teaching",
        help="execute a frozen bounded lesson board through existing Viv teaching paths",
    )
    autonomous_teaching.add_argument("--lesson-board", type=Path, required=True)
    autonomous_teaching.add_argument("--dictionary", type=Path, required=True)
    autonomous_teaching.add_argument("--descriptive-teacher", type=Path, required=True)
    autonomous_teaching.add_argument("--descriptive-learning-receipt", action="append", required=True)
    autonomous_teaching.add_argument("--binary-teacher", type=Path, required=True)
    autonomous_teaching.add_argument("--binary-learning-receipt", action="append", required=True)
    autonomous_teaching.add_argument("--social-learning-receipt", type=Path, action="append")
    autonomous_teaching.add_argument("--social-intent-receipt", type=Path, action="append")
    autonomous_teaching.add_argument("--social-teacher", type=Path, required=True)
    autonomous_teaching.add_argument("--graph", type=Path, required=True)
    autonomous_teaching.add_argument("--curriculum-db", type=Path, required=True)
    autonomous_teaching.add_argument("--hydra-bin", type=Path, required=True)
    autonomous_teaching.add_argument("--evidence-dir", type=Path, required=True)
    autonomous_teaching.add_argument("--output", type=Path, required=True)
    autonomous_teaching.add_argument("--seed", type=int, default=0)
    autonomous_teaching.add_argument("--max-lessons", type=int, default=8)
    autonomous_teaching.add_argument("--max-attempts", type=int, default=1_000)
    autonomous_teaching.add_argument("--confirmations", type=int, default=8)
    autonomous_teaching.add_argument("--max-turns", type=int, default=12)

    grammar_bucket = subparsers.add_parser(
        "learn-grammar-bucket",
        help="exhaust one bounded cumulative word bucket against CPU grammar",
    )
    grammar_bucket.add_argument("--dictionary", type=Path, required=True)
    grammar_bucket.add_argument("--graph", type=Path, required=True)
    grammar_bucket.add_argument("--curriculum-db", type=Path, required=True)
    grammar_bucket.add_argument("--words", required=True, help="comma-separated admitted words")
    grammar_bucket.add_argument("--route-length", type=int, default=3)
    grammar_bucket.add_argument("--target-sentences", type=int, default=10)
    grammar_bucket.add_argument("--trace", type=Path, required=True)
    grammar_bucket.add_argument("--report", type=Path, required=True)
    grammar_bucket.add_argument("--seed", type=int, default=0)
    grammar_bucket.add_argument("--max-attempts", type=int, default=12000)
    grammar_bucket.add_argument("--hydra-bin", type=Path)
    grammar_bucket.add_argument("--hydra-trace", type=Path)

    meaning_bucket = subparsers.add_parser(
        "learn-meaning-bucket",
        help="exhaust current grammar routes and emit a verified vocabulary-need bit",
    )
    meaning_bucket.add_argument("--dictionary", type=Path, required=True)
    meaning_bucket.add_argument("--graph", type=Path, required=True)
    meaning_bucket.add_argument("--curriculum-db", type=Path, required=True)
    meaning_bucket.add_argument("--episode-id", required=True)
    meaning_bucket.add_argument("--words", required=True)
    meaning_bucket.add_argument("--target-sentences", type=int, default=10)
    meaning_bucket.add_argument("--trace", type=Path, required=True)
    meaning_bucket.add_argument("--report", type=Path, required=True)
    meaning_bucket.add_argument("--seed", type=int, default=0)
    meaning_bucket.add_argument("--max-attempts", type=int, default=24000)
    meaning_bucket.add_argument("--hydra-bin", type=Path)
    meaning_bucket.add_argument("--hydra-trace", type=Path)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    commands = {
        "status": command_status,
        "learn-book": command_learn_book,
        "bootstrap-word-ladder": command_bootstrap_word_ladder,
        "migrate-store": command_migrate_store,
        "build-webster-corpus": command_build_webster_corpus,
        "materialize-neuron-dictionary": command_materialize_neuron_dictionary,
        "frozen-recall": command_frozen_recall,
        "learn-roles": command_learn_roles,
        "learn-identity-tags": command_learn_identity_tags,
        "learn-foundation-token": command_learn_foundation_token,
        "learn-svo": command_learn_svo,
        "learn-utterance": command_learn_svo,
        "learn-dialogue-scene": command_learn_dialogue_scene,
        "run-dialogue-scene": command_run_dialogue_scene,
        "attach-source-provenance": command_attach_source_provenance,
        "bind-provenance-explanation": command_bind_provenance_explanation,
        "query-provenance-explanation": command_query_provenance_explanation,
        "create-human-review-request": command_create_human_review_request,
        "admit-reviewed-source-word": command_admit_reviewed_source_word,
        "recall-grounded-question": command_recall_grounded_question,
        "run-conversation": command_run_conversation,
        "learn-question-template": command_learn_question_template,
        "learn-social-intent": command_learn_social_intent,
        "generalize-question": command_generalize_question,
        "learn-binary-relation": command_learn_binary_relation,
        "run-binary-conversation": command_run_binary_conversation,
        "run-binary-teaching-session": command_run_binary_teaching_session,
        "extract-article-binary-lesson": command_extract_article_binary_lesson,
        "run-article-learning-session": command_run_article_learning_session,
        "attach-article-provenance": command_attach_article_provenance,
        "attach-relation-provenance": command_attach_relation_provenance,
        "query-neuron-source": command_query_neuron_source,
        "route-addressed-conversation": command_route_addressed_conversation,
        "run-mixed-conversation": command_run_mixed_conversation,
        "run-learning-conversation": command_run_learning_conversation,
        "run-autonomous-teaching": command_run_autonomous_teaching,
        "learn-grammar-bucket": command_learn_grammar_bucket,
        "learn-meaning-bucket": command_learn_meaning_bucket,
    }
    return commands[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
