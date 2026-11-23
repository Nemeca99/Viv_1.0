"""Durable, target-free memory graph for the Neuronizer candidate.

The language bucket proves a construction.  A neuron makes that learned state
addressable and lets later experience form plastic, reciprocal associations.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import time
import uuid
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Sequence

from .fixed_point import SCALE, toward_one, toward_zero

if TYPE_CHECKING:
    from .language_state import LearnedBucket


GRAPH_SCHEMA = "NN_NEURON_GRAPH_V1"
NEURON_SCHEMA = "NN_EXPERT_NEURON_V1"
MANIFEST_SCHEMA = "NN_NEURON_GRAPH_MANIFEST_V1"
LEDGER_SCHEMA = "NN_NEURON_GRAPH_EVENT_V1"
NEURON_KINDS = {
    "CHARACTER",
    "COMBINATION",
    "WORD",
    "EPISODE",
    "SENTENCE",
    "PARAGRAPH",
    "PAGE",
    "CONCEPT",
    "COMPRESSION",
}
LIFECYCLES = {"NEWBORN", "PLASTIC", "STABLE", "DORMANT", "ARCHIVED"}
REFLECTORS = ("LEFT", "RIGHT", "UP", "DOWN", "FRONT", "BACK")


class CurriculumStore:
    """Single-file learned route evidence for every recursive curriculum rung."""

    def __init__(self, path: str | Path, *, readonly: bool = False):
        self.path = Path(path).resolve()
        if readonly:
            if not self.path.is_file():
                raise FileNotFoundError(self.path)
            self.connection = sqlite3.connect(
                f"file:{self.path.as_posix()}?mode=ro", uri=True
            )
            self.connection.execute("PRAGMA query_only=ON")
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(self.path)
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("PRAGMA synchronous=FULL")
            self.connection.executescript(
                """
            CREATE TABLE IF NOT EXISTS route_evidence (
                level TEXT NOT NULL,
                context_sha256 TEXT NOT NULL,
                token_id TEXT NOT NULL,
                pass_hits INTEGER NOT NULL DEFAULT 0,
                fail_hits INTEGER NOT NULL DEFAULT 0,
                uses INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (level, context_sha256, token_id)
            );
            CREATE TABLE IF NOT EXISTS assembly_evidence (
                level TEXT NOT NULL,
                inventory_context_sha256 TEXT NOT NULL,
                route_sha256 TEXT NOT NULL,
                pass_hits INTEGER NOT NULL DEFAULT 0,
                fail_hits INTEGER NOT NULL DEFAULT 0,
                uses INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (level, inventory_context_sha256, route_sha256)
            );
            CREATE TABLE IF NOT EXISTS pattern_evidence (
                level TEXT NOT NULL,
                feature_sha256 TEXT NOT NULL,
                pass_hits INTEGER NOT NULL DEFAULT 0,
                fail_hits INTEGER NOT NULL DEFAULT 0,
                uses INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (level, feature_sha256)
            );
            CREATE TABLE IF NOT EXISTS attempts (
                attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_utc TEXT NOT NULL,
                level TEXT NOT NULL,
                lesson_id TEXT NOT NULL,
                source_handle TEXT NOT NULL,
                output_text TEXT NOT NULL,
                verdict TEXT NOT NULL CHECK (verdict IN ('PASS','FAIL','HOLD')),
                route_json TEXT NOT NULL,
                decision_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS attempts_lesson ON attempts(level, lesson_id, attempt_id);
                """
            )
            self.connection.commit()
        self._evidence_cache = {
            (str(level), str(context), str(token)): (int(passes), int(failures))
            for level, context, token, passes, failures in self.connection.execute(
                "SELECT level,context_sha256,token_id,pass_hits,fail_hits FROM route_evidence"
            )
        }
        self._assembly_evidence_cache = {
            (str(level), str(context), str(route)): (int(passes), int(failures))
            for level, context, route, passes, failures in self.connection.execute(
                "SELECT level,inventory_context_sha256,route_sha256,pass_hits,fail_hits "
                "FROM assembly_evidence"
            )
        }
        has_pattern_table = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='pattern_evidence'"
        ).fetchone()
        self._pattern_evidence_cache = (
            {
                (str(level), str(feature)): (int(passes), int(failures))
                for level, feature, passes, failures in self.connection.execute(
                    "SELECT level,feature_sha256,pass_hits,fail_hits FROM pattern_evidence"
                )
            }
            if has_pattern_table
            else {}
        )

    def evidence(self, level: str, context_sha256: str, token_ids: Sequence[str]) -> list[tuple[int, int]]:
        prefix = (str(level), str(context_sha256))
        return [
            self._evidence_cache.get((*prefix, str(token_id)), (0, 0))
            for token_id in token_ids
        ]

    def apply_route_verdict(
        self,
        *,
        level: str,
        steps: Sequence[tuple[str, str]],
        passed: bool,
    ) -> None:
        field = "pass_hits" if passed else "fail_hits"
        keys = [
            (str(level), str(context_sha256), str(token_id))
            for context_sha256, token_id in steps
        ]
        with self.connection:
            for _level, context_sha256, token_id in keys:
                self.connection.execute(
                    "INSERT INTO route_evidence(level,context_sha256,token_id,pass_hits,fail_hits,uses) "
                    "VALUES(?,?,?,?,?,1) ON CONFLICT(level,context_sha256,token_id) DO UPDATE SET "
                    f"{field}={field}+1, uses=uses+1",
                    (
                        str(level), str(context_sha256), str(token_id),
                        1 if passed else 0, 0 if passed else 1,
                    ),
                )
        for key in keys:
            pass_hits, fail_hits = self._evidence_cache.get(key, (0, 0))
            self._evidence_cache[key] = (
                pass_hits + int(passed),
                fail_hits + int(not passed),
            )

    @staticmethod
    def _route_sha256(route: Sequence[str]) -> str:
        return hashlib.sha256("\0".join(str(value) for value in route).encode("utf-8")).hexdigest().upper()

    def assembly_evidence(
        self,
        level: str,
        inventory_context_sha256: str,
        route: Sequence[str],
    ) -> tuple[int, int]:
        key = (
            str(level),
            str(inventory_context_sha256),
            self._route_sha256(route),
        )
        return self._assembly_evidence_cache.get(key, (0, 0))

    def apply_assembly_verdict(
        self,
        *,
        level: str,
        inventory_context_sha256: str,
        route: Sequence[str],
        passed: bool,
    ) -> None:
        route_sha256 = self._route_sha256(route)
        key = (str(level), str(inventory_context_sha256), route_sha256)
        field = "pass_hits" if passed else "fail_hits"
        with self.connection:
            self.connection.execute(
                "INSERT INTO assembly_evidence("
                "level,inventory_context_sha256,route_sha256,pass_hits,fail_hits,uses"
                ") VALUES(?,?,?,?,?,1) ON CONFLICT("
                "level,inventory_context_sha256,route_sha256"
                ") DO UPDATE SET "
                f"{field}={field}+1, uses=uses+1",
                (
                    str(level),
                    str(inventory_context_sha256),
                    route_sha256,
                    1 if passed else 0,
                    0 if passed else 1,
                ),
            )
        pass_hits, fail_hits = self._assembly_evidence_cache.get(key, (0, 0))
        self._assembly_evidence_cache[key] = (
            pass_hits + int(passed),
            fail_hits + int(not passed),
        )

    def pattern_evidence(
        self, level: str, feature_sha256s: Sequence[str]
    ) -> list[tuple[int, int]]:
        return [
            self._pattern_evidence_cache.get(
                (str(level), str(feature_sha256)), (0, 0)
            )
            for feature_sha256 in feature_sha256s
        ]

    def apply_pattern_verdict(
        self,
        *,
        level: str,
        feature_sha256s: Sequence[str],
        passed: bool,
    ) -> None:
        # Store only opaque features of the attempted path. The teacher's
        # target, correction positions, and unattempted alternatives never enter.
        keys = list(dict.fromkeys(
            (str(level), str(feature_sha256))
            for feature_sha256 in feature_sha256s
        ))
        field = "pass_hits" if passed else "fail_hits"
        with self.connection:
            for _level, feature_sha256 in keys:
                self.connection.execute(
                    "INSERT INTO pattern_evidence("
                    "level,feature_sha256,pass_hits,fail_hits,uses"
                    ") VALUES(?,?,?,?,1) ON CONFLICT(level,feature_sha256) "
                    "DO UPDATE SET "
                    f"{field}={field}+1, uses=uses+1",
                    (_level, feature_sha256, int(passed), int(not passed)),
                )
        for key in keys:
            pass_hits, fail_hits = self._pattern_evidence_cache.get(key, (0, 0))
            self._pattern_evidence_cache[key] = (
                pass_hits + int(passed), fail_hits + int(not passed)
            )

    def record_attempt(
        self,
        *,
        level: str,
        lesson_id: str,
        source_handle: str,
        output_text: str,
        verdict: str,
        route: Sequence[str],
        decisions: Sequence[dict[str, Any]],
    ) -> int:
        if verdict not in {"PASS", "FAIL", "HOLD"}:
            raise ValueError("invalid curriculum verdict")
        with self.connection:
            cursor = self.connection.execute(
                "INSERT INTO attempts(created_utc,level,lesson_id,source_handle,output_text,verdict,route_json,decision_json) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    utc_now(), str(level), str(lesson_id), str(source_handle),
                    str(output_text), verdict,
                    json.dumps(list(route), separators=(",", ":")),
                    json.dumps(list(decisions), separators=(",", ":")),
                ),
            )
        return int(cursor.lastrowid)

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "CurriculumStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def content_hash(value: dict[str, Any]) -> str:
    clean = deepcopy(value)
    clean.pop("content_sha256", None)
    return hashlib.sha256(canonical_json(clean)).hexdigest().upper()


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def stable_word_neuron_id(bucket_id: str) -> str:
    digest = hashlib.sha256(f"WORD\0{bucket_id}".encode("utf-8")).hexdigest().upper()
    return f"N-{digest[:32]}"


def stable_character_neuron_id(character: str) -> str:
    value = str(character)
    if len(value) != 1 or value.isspace():
        raise ValueError("character neuron identity must be one non-whitespace code point")
    digest = hashlib.sha256(f"CHARACTER\0{value}".encode("utf-8")).hexdigest().upper()
    return f"N-{digest[:32]}"


def stable_combination_neuron_id(surface: str) -> str:
    value = str(surface)
    if len(value) < 2 or any(character.isspace() for character in value):
        raise ValueError("combination neuron identity requires at least two non-whitespace code points")
    digest = hashlib.sha256(f"COMBINATION\0{value}".encode("utf-8")).hexdigest().upper()
    return f"N-{digest[:32]}"


def new_neuron_id() -> str:
    return f"N-{uuid.uuid4().hex.upper()}"


def new_physical_neuron_id() -> str:
    """Return a permanent entropy-born address for one neuron instance."""

    return f"P-{secrets.token_hex(32).upper()}"


def semantic_neuron_key(kind: str, center: dict[str, Any]) -> str:
    """Group equivalent learned content without collapsing physical instances."""

    if kind == "CHARACTER":
        material: Any = center.get("learned_character", "")
    elif kind == "COMBINATION":
        material = center.get("learned_combination", "")
    elif kind == "WORD":
        material = center.get("learned_surface", "")
    elif kind == "EPISODE":
        material = {
            "admitted_endpoint": center.get("admitted_endpoint", ""),
            "selected_token_path": list(center.get("selected_token_path", ())),
        }
    else:
        material = center
    payload = canonical_json({"kind": str(kind), "material": material})
    return f"S-{hashlib.sha256(payload).hexdigest().upper()}"


def learned_word(bucket: LearnedBucket) -> str:
    """Recover a word solely from the model's frozen admitted path."""

    if bucket.state != "PASS" or bucket.visible.level != "WORD":
        raise ValueError("word neuron requires an admitted WORD bucket")
    candidates = len(bucket.visible.candidate_ids)
    symbols: list[str] = []
    for position in range(bucket.visible.position_count):
        row = bucket.heads[position * candidates : (position + 1) * candidates]
        supported = [index for index, value in enumerate(row) if value > 0]
        if len(supported) != 1:
            raise ValueError(f"word bucket is not operationally closed: {bucket.visible.bucket_id}")
        symbol = bucket.visible.candidate_ids[supported[0]]
        if not symbol.startswith("CHAR:"):
            raise ValueError("word bucket contains unsupported non-character child")
        symbols.append(symbol.removeprefix("CHAR:"))
    return "".join(symbols)


def blank_reflectors() -> dict[str, list[dict[str, Any]]]:
    return {name: [] for name in REFLECTORS}


def make_neuron(
    *,
    neuron_id: str,
    kind: str,
    center: dict[str, Any],
    creation_event: str,
    children: Iterable[str] = (),
    lifecycle: str = "NEWBORN",
    foundation: bool = False,
    neuron_lock: bool = False,
    physical_identity: bool = False,
) -> dict[str, Any]:
    if kind not in NEURON_KINDS or lifecycle not in LIFECYCLES:
        raise ValueError("invalid neuron kind or lifecycle")
    now = utc_now()
    neuron = {
        "schema": NEURON_SCHEMA,
        "neuron_id": neuron_id,
        "kind": kind,
        "lifecycle": lifecycle,
        "created_utc": now,
        "updated_utc": now,
        "creation_event": creation_event,
        "center_attractor": center,
        "reflectors": blank_reflectors(),
        "children": list(children),
        "parents": [],
        "protection": {
            "foundation": bool(foundation),
            "foundation_authority": "ARCHITECTURE" if foundation else "",
            "neuron_lock": bool(neuron_lock),
            "lock_authority": "ARCHITECT" if neuron_lock else "",
        },
        "activation": {
            "uses": 0,
            "pass_hits": 0,
            "fail_hits": 0,
            "confirmation_passes": 0,
            "hold_hits": 0,
        },
    }
    if physical_identity:
        neuron["physical_id"] = new_physical_neuron_id()
        neuron["semantic_key"] = semantic_neuron_key(kind, center)
    neuron["content_sha256"] = content_hash(neuron)
    validate_neuron(neuron)
    return neuron


def validate_neuron(neuron: dict[str, Any]) -> None:
    from .leakage_audit import audit_gpu_payload

    if neuron.get("schema") != NEURON_SCHEMA:
        raise ValueError("unsupported neuron schema")
    if neuron.get("kind") not in NEURON_KINDS or neuron.get("lifecycle") not in LIFECYCLES:
        raise ValueError("invalid neuron state")
    if tuple(neuron.get("reflectors", {}).keys()) != REFLECTORS:
        raise ValueError("neuron must contain exactly six ordered reflectors")
    physical_id = neuron.get("physical_id")
    semantic_key = neuron.get("semantic_key")
    if (physical_id is None) != (semantic_key is None):
        raise ValueError("physical identity and semantic key must be present together")
    if physical_id is not None:
        if not isinstance(physical_id, str) or len(physical_id) != 66 or not physical_id.startswith("P-"):
            raise ValueError("physical neuron identity must be one 256-bit address")
        if not isinstance(semantic_key, str) or len(semantic_key) != 66 or not semantic_key.startswith("S-"):
            raise ValueError("semantic neuron key must be one SHA-256 identity")
        try:
            int(physical_id[2:], 16)
            int(semantic_key[2:], 16)
        except ValueError as exc:
            raise ValueError("neuron identity contains non-hexadecimal material") from exc
    protection = neuron.get("protection")
    if protection is not None:
        if bool(protection.get("foundation")) != (
            protection.get("foundation_authority") == "ARCHITECTURE"
        ):
            raise ValueError("foundation protection requires architecture authority")
        if bool(protection.get("neuron_lock")) != (
            protection.get("lock_authority") == "ARCHITECT"
        ):
            raise ValueError("neuron lock requires Architect authority")
    for edges in neuron["reflectors"].values():
        for edge in edges:
            if edge.get("direction") not in {"IN", "OUT"}:
                raise ValueError("connection direction must be learned IN or OUT")
            if not 0 <= int(edge.get("weight", -1)) <= SCALE:
                raise ValueError("connection weight outside fixed-point bounds")
    if audit_gpu_payload(neuron)["state"] != "PASS":
        raise ValueError("neuron payload crossed the target-hidden boundary")
    if neuron.get("content_sha256") != content_hash(neuron):
        raise ValueError("neuron content hash mismatch")


class GraphStore:
    """Hash-sharded neuron files with recoverable reciprocal transactions."""

    def __init__(self, root: str | Path, *, readonly: bool = False):
        self.root = Path(root).resolve()
        self.readonly = readonly
        self.manifest_path = self.root / "manifest.json"
        self.ledger_path = self.root / "ledger" / "activation_links.jsonl"
        archive_root = os.environ.get("NN_TRANSACTION_ARCHIVE_ROOT", "").strip()
        self.transaction_root = (
            Path(archive_root).resolve()
            if archive_root
            else self.root / "transactions"
        )
        if not self.manifest_path.is_file():
            raise FileNotFoundError(self.manifest_path)
        self._known_ledger_event_ids: set[str] = set()
        # Inspection must not replay interrupted writes or create directories.
        if not self.readonly:
            self.transaction_root.mkdir(parents=True, exist_ok=True)
            self.recover()

    def _require_writable(self) -> None:
        if self.readonly:
            raise PermissionError("readonly neuron graph cannot be mutated")

    @classmethod
    def initialize(
        cls,
        root: str | Path,
        *,
        language_state_path: str | Path,
        protected_paths: Iterable[str | Path],
    ) -> "GraphStore":
        graph_root = Path(root).resolve()
        if graph_root.exists() and any(graph_root.iterdir()):
            raise FileExistsError(f"Neuronizer candidate root is not empty: {graph_root}")
        for name in ("neurons", "ledger", "transactions", "archive", "source"):
            (graph_root / name).mkdir(parents=True, exist_ok=True)
        language_source = Path(language_state_path).resolve()
        language_copy = graph_root / "source" / "language_gpu_state.json"
        shutil.copy2(language_source, language_copy)
        protected = {str(Path(path).resolve()): file_sha256(path) for path in protected_paths}
        manifest = {
            "schema": MANIFEST_SCHEMA,
            "graph_schema": GRAPH_SCHEMA,
            "created_utc": utc_now(),
            "updated_utc": utc_now(),
            "candidate_only": True,
            "promotion_authorized": False,
            "promotion_performed": False,
            "source_language_state": {
                "path": str(language_source),
                "file_sha256": file_sha256(language_source),
                "copy": str(language_copy),
                "copy_sha256": file_sha256(language_copy),
            },
            "protected_hashes": protected,
            "neuron_index": {},
            "character_index": {},
            "combination_index": {},
            "word_index": {},
            "state_index": {},
            "kind_counts": {kind: 0 for kind in sorted(NEURON_KINDS)},
            "lifecycle_counts": {state: 0 for state in sorted(LIFECYCLES)},
            "assembly_multiplicity": {},
            "assembly_members": {},
            "compression_index": {},
            "route_multiplicity": {},
            "hold_regions": {},
            "ledger_head": "0" * 64,
            "events": 0,
        }
        cls._write_json_atomic(graph_root / "manifest.json", manifest)
        return cls(graph_root)

    @classmethod
    def initialize_from_corpus(
        cls,
        root: str | Path,
        *,
        corpus_path: str | Path,
        protected_paths: Iterable[str | Path],
        copy_source: bool = False,
    ) -> "GraphStore":
        """Initialize a candidate graph whose external source is a CPU corpus.

        The corpus is CPU-private by default.  ``copy_source`` exists for
        diagnostics that explicitly need a local evidence copy; the graph
        learner does not copy teacher material into its model root.
        """

        graph_root = Path(root).resolve()
        if graph_root.exists() and any(graph_root.iterdir()):
            raise FileExistsError(f"Neuronizer candidate root is not empty: {graph_root}")
        for name in ("neurons", "ledger", "transactions", "archive", "source"):
            (graph_root / name).mkdir(parents=True, exist_ok=True)
        source = Path(corpus_path).resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        corpus_copy = graph_root / "source" / source.name
        if copy_source:
            shutil.copy2(source, corpus_copy)
        protected = {str(Path(path).resolve()): file_sha256(path) for path in protected_paths}
        manifest = {
            "schema": MANIFEST_SCHEMA,
            "graph_schema": GRAPH_SCHEMA,
            "created_utc": utc_now(),
            "updated_utc": utc_now(),
            "candidate_only": True,
            "promotion_authorized": False,
            "promotion_performed": False,
            "source_language_state": None,
            "source_corpus": {
                "path": str(source),
                "file_sha256": file_sha256(source),
                "copy": str(corpus_copy) if copy_source else None,
                "copy_sha256": file_sha256(corpus_copy) if copy_source else None,
            },
            "protected_hashes": protected,
            "neuron_index": {},
            "character_index": {},
            "combination_index": {},
            "word_index": {},
            "state_index": {},
            "kind_counts": {kind: 0 for kind in sorted(NEURON_KINDS)},
            "lifecycle_counts": {state: 0 for state in sorted(LIFECYCLES)},
            "assembly_multiplicity": {},
            "assembly_members": {},
            "compression_index": {},
            "route_multiplicity": {},
            "hold_regions": {},
            "ledger_head": "0" * 64,
            "events": 0,
        }
        cls._write_json_atomic(graph_root / "manifest.json", manifest)
        return cls(graph_root)

    @staticmethod
    def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        # Windows can briefly deny an otherwise atomic replacement while a
        # read-only monitor or Defender has the destination open.  Keep the
        # same fully-written temporary file and retry only the publication
        # operation; never rewrite or partially modify the live manifest.
        for attempt in range(100):
            try:
                os.replace(temporary, path)
                return
            except PermissionError:
                if attempt == 99:
                    raise
                time.sleep(0.05)

    def manifest(self) -> dict[str, Any]:
        with self.manifest_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if payload.get("schema") != MANIFEST_SCHEMA:
            raise ValueError("unsupported Neuronizer manifest")
        return payload

    def neuron_path(self, neuron_id: str) -> Path:
        # A neuron identity is a filename component, never a path or NTFS stream.
        if (not isinstance(neuron_id, str) or not neuron_id
                or neuron_id in {".", ".."}
                or any(character in neuron_id for character in '<>:"/\\|?*\0')
                or any(ord(character) < 32 for character in neuron_id)):
            raise ValueError("invalid neuron identity filename")
        digest = hashlib.sha256(neuron_id.encode("utf-8")).hexdigest().upper()
        return self.root / "neurons" / digest[:2] / digest[2:4] / f"{neuron_id}.json"

    def load_neuron(self, neuron_id: str) -> dict[str, Any]:
        with self.neuron_path(neuron_id).open("r", encoding="utf-8") as handle:
            neuron = json.load(handle)
        validate_neuron(neuron)
        if neuron["neuron_id"] != neuron_id:
            raise ValueError("neuron filename and identity disagree")
        return neuron

    @staticmethod
    def is_protected_neuron(neuron: dict[str, Any]) -> bool:
        protection = neuron.get("protection", {})
        # CHARACTER is the compatibility rule for graphs created before the
        # explicit protection field existed.  New character neurons are also
        # stamped FOUNDATION at birth.
        return bool(
            neuron.get("kind") == "CHARACTER"
            or protection.get("foundation")
            or protection.get("neuron_lock")
        )

    @staticmethod
    def connection_count(neuron: dict[str, Any]) -> int:
        return (
            sum(len(edges) for edges in neuron.get("reflectors", {}).values())
            + len(neuron.get("children", ()))
            + len(neuron.get("parents", ()))
        )

    def _ledger_event_ids(self) -> set[str]:
        if not self.ledger_path.is_file():
            return set()
        ids: set[str] = set()
        with self.ledger_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    ids.add(str(json.loads(line)["event_id"]))
        return ids

    def _append_event(self, event: dict[str, Any]) -> None:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._known_ledger_event_ids.add(str(event["event_id"]))

    def transact(
        self,
        neurons: Iterable[dict[str, Any]],
        *,
        event_kind: str,
        details: dict[str, Any],
        manifest_mutator: Any | None = None,
        interrupt_after_writes: int | None = None,
    ) -> str:
        self._require_writable()
        changed = [deepcopy(neuron) for neuron in neurons]
        if not changed:
            raise ValueError("transaction requires at least one neuron")
        # Writer and replay must agree on one final payload per neuron identity.
        if len({neuron["neuron_id"] for neuron in changed}) != len(changed):
            raise ValueError("transaction requires unique neuron identities")
        event_id = f"E-{uuid.uuid4().hex.upper()}"
        transaction = self.transaction_root / event_id
        staged = transaction / "staged"
        staged.mkdir(parents=True, exist_ok=False)
        manifest = self.manifest()
        prior_head = str(manifest["ledger_head"])
        for neuron in changed:
            neuron["updated_utc"] = utc_now()
            neuron["content_sha256"] = content_hash(neuron)
            validate_neuron(neuron)
            relative = self.neuron_path(neuron["neuron_id"]).relative_to(self.root)
            self._write_json_atomic(staged / relative, neuron)
            old = manifest["neuron_index"].get(neuron["neuron_id"])
            if old is None:
                manifest["kind_counts"].setdefault(neuron["kind"], 0)
                manifest["kind_counts"][neuron["kind"]] += 1
                manifest["lifecycle_counts"][neuron["lifecycle"]] += 1
            elif old["lifecycle"] != neuron["lifecycle"]:
                manifest["lifecycle_counts"][old["lifecycle"]] -= 1
                manifest["lifecycle_counts"][neuron["lifecycle"]] += 1
            manifest["neuron_index"][neuron["neuron_id"]] = {
                "path": str(relative).replace("\\", "/"),
                "kind": neuron["kind"],
                "lifecycle": neuron["lifecycle"],
                "content_sha256": neuron["content_sha256"],
            }
            surface = neuron["center_attractor"].get("learned_surface")
            if neuron["kind"] == "WORD" and surface:
                manifest["word_index"][surface] = neuron["neuron_id"]
                manifest.setdefault("state_index", {})[f"WORD:{surface}"] = neuron["neuron_id"]
            character = neuron["center_attractor"].get("learned_character")
            if neuron["kind"] == "CHARACTER" and character:
                manifest.setdefault("character_index", {})[character] = neuron["neuron_id"]
            combination = neuron["center_attractor"].get("learned_combination")
            if neuron["kind"] == "COMBINATION" and combination:
                manifest.setdefault("combination_index", {})[combination] = neuron["neuron_id"]
                manifest.setdefault("state_index", {})[f"COMBINATION:{combination}"] = neuron["neuron_id"]
            visible_state = neuron["center_attractor"].get("visible_state_id")
            if visible_state:
                manifest.setdefault("state_index", {})[str(visible_state)] = neuron["neuron_id"]
        if manifest_mutator is not None:
            manifest_mutator(manifest)
        event = {
            "schema": LEDGER_SCHEMA,
            "event_id": event_id,
            "created_utc": utc_now(),
            "kind": event_kind,
            "neuron_ids": [neuron["neuron_id"] for neuron in changed],
            "details": details,
            "prior_event_sha256": prior_head,
        }
        event["event_sha256"] = hashlib.sha256(canonical_json(event)).hexdigest().upper()
        manifest["ledger_head"] = event["event_sha256"]
        manifest["events"] += 1
        manifest["updated_utc"] = utc_now()
        self._write_json_atomic(transaction / "event.json", event)
        self._write_json_atomic(transaction / "manifest.json", manifest)
        self._write_json_atomic(transaction / "COMMIT.json", {"event_id": event_id, "state": "COMMIT"})
        writes = 0
        for neuron in changed:
            relative = self.neuron_path(neuron["neuron_id"]).relative_to(self.root)
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(staged / relative, destination)
            writes += 1
            if interrupt_after_writes is not None and writes >= interrupt_after_writes:
                raise RuntimeError("INJECTED_TRANSACTION_INTERRUPTION")
        committed_manifest = json.loads(
            (transaction / "manifest.json").read_text(encoding="utf-8")
        )
        self._write_json_atomic(self.manifest_path, committed_manifest)
        if event_id not in self._known_ledger_event_ids:
            self._append_event(event)
        self._write_json_atomic(transaction / "COMPLETE.json", {"event_id": event_id, "state": "COMPLETE"})
        return event_id

    def remove_zero_connection_neurons(
        self, neuron_ids: Iterable[str] | None = None
    ) -> dict[str, Any]:
        """Remove unconnected residue from the active graph, preserving tombstones.

        FOUNDATION and Architect NEURON_LOCK are absolute exceptions.  Removal
        means absent from the active manifest and routing tree; the immutable
        prior neuron JSON remains under archive/removals for audit and recovery.
        """
        self._require_writable()
        manifest = self.manifest()
        requested = (
            sorted(set(str(item) for item in neuron_ids))
            if neuron_ids is not None
            else sorted(manifest["neuron_index"])
        )
        removable: list[dict[str, Any]] = []
        protected: list[str] = []
        connected: list[str] = []
        missing: list[str] = []
        for neuron_id in requested:
            if neuron_id not in manifest["neuron_index"]:
                missing.append(neuron_id)
                continue
            neuron = self.load_neuron(neuron_id)
            if self.is_protected_neuron(neuron):
                protected.append(neuron_id)
            elif self.connection_count(neuron) != 0:
                connected.append(neuron_id)
            else:
                removable.append(neuron)
        if not removable:
            return {
                "state": "PASS",
                "removed": 0,
                "protected": protected,
                "connected": connected,
                "missing": missing,
                "event_id": None,
            }

        event_id = f"E-{uuid.uuid4().hex.upper()}"
        transaction = self.transaction_root / event_id
        staged = transaction / "removed"
        staged.mkdir(parents=True, exist_ok=False)
        removed_ids = [str(neuron["neuron_id"]) for neuron in removable]
        for neuron in removable:
            self._write_json_atomic(staged / f"{neuron['neuron_id']}.json", neuron)

        for neuron in removable:
            neuron_id = str(neuron["neuron_id"])
            index = manifest["neuron_index"].pop(neuron_id)
            manifest["kind_counts"][str(index["kind"])] -= 1
            manifest["lifecycle_counts"][str(index["lifecycle"])] -= 1
            for name in (
                "character_index", "combination_index", "word_index",
                "state_index", "compression_index",
            ):
                values = manifest.get(name, {})
                for key in [key for key, value in values.items() if value == neuron_id]:
                    del values[key]

        event = {
            "schema": LEDGER_SCHEMA,
            "event_id": event_id,
            "created_utc": utc_now(),
            "kind": "REMOVE_ZERO_CONNECTION_NEURONS",
            "neuron_ids": removed_ids,
            "details": {
                "reason": "ZERO_CONNECTION_RESIDUE",
                "foundation_exempt": protected,
                "neuron_lock_exempt": [
                    neuron_id for neuron_id in protected
                    if self.load_neuron(neuron_id).get("protection", {}).get("neuron_lock")
                ],
                "tombstones_retained": True,
            },
            "prior_event_sha256": str(manifest["ledger_head"]),
        }
        event["event_sha256"] = hashlib.sha256(canonical_json(event)).hexdigest().upper()
        manifest["ledger_head"] = event["event_sha256"]
        manifest["events"] += 1
        manifest["updated_utc"] = utc_now()
        self._write_json_atomic(transaction / "event.json", event)
        self._write_json_atomic(transaction / "manifest.json", manifest)
        self._write_json_atomic(transaction / "removals.json", {"neuron_ids": removed_ids})
        self._write_json_atomic(transaction / "COMMIT.json", {"event_id": event_id, "state": "COMMIT"})
        archive = self.root / "archive" / "removals" / event_id
        archive.mkdir(parents=True, exist_ok=True)
        for neuron_id in removed_ids:
            shutil.copy2(staged / f"{neuron_id}.json", archive / f"{neuron_id}.json")
            self.neuron_path(neuron_id).unlink(missing_ok=True)
        self._write_json_atomic(self.manifest_path, manifest)
        if event_id not in self._known_ledger_event_ids:
            self._append_event(event)
        self._write_json_atomic(transaction / "COMPLETE.json", {"event_id": event_id, "state": "COMPLETE"})
        return {
            "state": "PASS",
            "removed": len(removed_ids),
            "removed_ids": removed_ids,
            "protected": protected,
            "connected": connected,
            "missing": missing,
            "event_id": event_id,
            "archive": str(archive),
        }

    def _validate_recovery(self, transaction: Path) -> tuple[dict[str, Any], dict[str, Any]]:
        """Reject damaged replay evidence before copying or deleting graph files."""
        try:
            commit = json.loads((transaction / "COMMIT.json").read_text(encoding="utf-8"))
            event = json.loads((transaction / "event.json").read_text(encoding="utf-8"))
            manifest = json.loads((transaction / "manifest.json").read_text(encoding="utf-8"))
            material = dict(event)
            claimed = material.pop("event_sha256")
            if (
                commit != {"event_id": transaction.name, "state": "COMMIT"}
                or event["event_id"] != transaction.name
                or event["schema"] != LEDGER_SCHEMA
                or claimed != hashlib.sha256(canonical_json(material)).hexdigest().upper()
                or manifest["schema"] != MANIFEST_SCHEMA
                or manifest["ledger_head"] != claimed
            ):
                raise ValueError("recovery commit/event/manifest mismatch")
            current = self.manifest()
            if current["ledger_head"] == event["prior_event_sha256"]:
                if manifest["events"] != current["events"] + 1:
                    raise ValueError("recovery event count mismatch")
            elif current["ledger_head"] != claimed or current["events"] != manifest["events"]:
                raise ValueError("recovery does not extend the current graph head")
            ids = event["neuron_ids"]
            if not ids or len(ids) != len(set(ids)):
                raise ValueError("recovery requires unique neuron identities")
            removals_path = transaction / "removals.json"
            removing = removals_path.is_file()
            if removing and json.loads(removals_path.read_text(encoding="utf-8"))["neuron_ids"] != ids:
                raise ValueError("recovery removal identities mismatch")
            expected_paths = set()
            for neuron_id in ids:
                relative = self.neuron_path(neuron_id).relative_to(self.root)
                source = (transaction / "removed" / f"{neuron_id}.json" if removing
                          else transaction / "staged" / relative)
                if not source.resolve().is_relative_to(transaction.resolve()):
                    raise ValueError("recovery source escapes transaction")
                neuron = json.loads(source.read_text(encoding="utf-8"))
                validate_neuron(neuron)
                if neuron["neuron_id"] != neuron_id:
                    raise ValueError("recovery neuron identity mismatch")
                if removing:
                    if neuron_id in manifest["neuron_index"] or self.is_protected_neuron(neuron) or self.connection_count(neuron):
                        raise ValueError("recovery removal violates neuron protection")
                else:
                    index = manifest["neuron_index"][neuron_id]
                    if index != {"path": relative.as_posix(), "kind": neuron["kind"],
                                 "lifecycle": neuron["lifecycle"], "content_sha256": neuron["content_sha256"]}:
                        raise ValueError("recovery neuron index mismatch")
                    expected_paths.add(source.resolve())
            if not removing and expected_paths != {p.resolve() for p in (transaction / "staged").rglob("*.json")}:
                raise ValueError("recovery staged file set mismatch")
            # Manifest counters must describe the indexed neurons being installed.
            kinds = Counter(row["kind"] for row in manifest["neuron_index"].values())
            lifecycles = Counter(row["lifecycle"] for row in manifest["neuron_index"].values())
            if (set(kinds) - NEURON_KINDS or set(lifecycles) - LIFECYCLES
                    or any(manifest["kind_counts"].get(kind, 0) != kinds[kind] for kind in NEURON_KINDS)
                    or any(manifest["lifecycle_counts"].get(state, 0) != lifecycles[state] for state in LIFECYCLES)):
                raise ValueError("recovery manifest counts mismatch")
            # Semantic lookup tables are routing inputs, not cosmetic metadata.
            # Verify their targets against payloads, including unchanged neurons.
            cached = {}
            for name, kind, field in (
                ("word_index", "WORD", "learned_surface"),
                ("character_index", "CHARACTER", "learned_character"),
                ("combination_index", "COMBINATION", "learned_combination"),
                ("state_index", None, None),
            ):
                for label, neuron_id in manifest.get(name, {}).items():
                    index = manifest["neuron_index"][neuron_id]
                    if neuron_id not in cached:
                        relative = self.neuron_path(neuron_id).relative_to(self.root)
                        source = transaction / "staged" / relative if not removing and neuron_id in ids else self.root / relative
                        cached[neuron_id] = json.loads(source.read_text(encoding="utf-8"))
                        validate_neuron(cached[neuron_id])
                    neuron = cached[neuron_id]
                    if neuron["neuron_id"] != neuron_id or neuron["content_sha256"] != index["content_sha256"]:
                        raise ValueError("recovery lookup payload mismatch")
                    center = neuron["center_attractor"]
                    if kind is not None:
                        valid = neuron["kind"] == kind and center.get(field) == label
                    else:
                        valid = str(center.get("visible_state_id", "")) == label
                        valid |= neuron["kind"] == "WORD" and label == f"WORD:{center.get('learned_surface')}"
                        valid |= neuron["kind"] == "COMBINATION" and label == f"COMBINATION:{center.get('learned_combination')}"
                    if not valid:
                        raise ValueError("recovery semantic lookup mismatch")
            return event, manifest
        except (OSError, KeyError, TypeError) as error:
            raise ValueError(f"invalid recovery evidence: {transaction.name}") from error

    def recover(self) -> dict[str, int]:
        self._require_writable()
        # Refresh once per recovery pass.  Normal transactions generate a new
        # UUID and use the in-process set above, avoiding an O(events) ledger
        # scan on every attempt while retaining crash-replay deduplication.
        self._known_ledger_event_ids = self._ledger_event_ids()
        replayed = 0
        transaction_roots = [self.root / "transactions"]
        if self.transaction_root != transaction_roots[0]:
            transaction_roots.append(self.transaction_root)
        transactions = sorted(
            transaction
            for transaction_root in transaction_roots
            for transaction in transaction_root.glob("E-*")
        )
        for transaction in transactions:
            if not (transaction / "COMMIT.json").is_file() or (transaction / "COMPLETE.json").is_file():
                continue
            # Validate the complete transaction before the first publication;
            # a later audit cannot undo overwritten or removed neuron evidence.
            event, recovered_manifest = self._validate_recovery(transaction)
            staged = transaction / "staged"
            removals_path = transaction / "removals.json"
            if removals_path.is_file():
                removed_ids = json.loads(removals_path.read_text(encoding="utf-8"))["neuron_ids"]
                archive = self.root / "archive" / "removals" / str(event["event_id"])
                archive.mkdir(parents=True, exist_ok=True)
                for neuron_id in removed_ids:
                    source = transaction / "removed" / f"{neuron_id}.json"
                    shutil.copy2(source, archive / source.name)
                    self.neuron_path(str(neuron_id)).unlink(missing_ok=True)
            else:
                for source in staged.rglob("*.json"):
                    relative = source.relative_to(staged)
                    destination = self.root / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
            self._write_json_atomic(self.manifest_path, recovered_manifest)
            if event["event_id"] not in self._known_ledger_event_ids:
                self._append_event(event)
            self._write_json_atomic(
                transaction / "COMPLETE.json", {"event_id": event["event_id"], "state": "RECOVERED"}
            )
            replayed += 1
        return {"transactions_replayed": replayed}

    def audit(self) -> dict[str, Any]:
        manifest = self.manifest()
        violations: list[str] = []
        # A readonly view can observe a committed but unfinished transaction.
        # Surface that condition instead of declaring the old manifest healthy.
        for root in {self.root / "transactions", self.transaction_root}:
            for transaction in root.glob("E-*"):
                if (transaction / "COMMIT.json").is_file() and not (transaction / "COMPLETE.json").is_file():
                    violations.append(f"pending recovery: {transaction.name}")
        counts = {kind: 0 for kind in sorted(NEURON_KINDS)}
        lifecycles = {state: 0 for state in sorted(LIFECYCLES)}
        for neuron_id, index in manifest["neuron_index"].items():
            try:
                neuron = self.load_neuron(neuron_id)
            except Exception as error:  # audit must report all damaged records
                violations.append(f"{neuron_id}:{error}")
                continue
            counts[neuron["kind"]] += 1
            lifecycles[neuron["lifecycle"]] += 1
            if neuron["content_sha256"] != index["content_sha256"]:
                violations.append(f"{neuron_id}:manifest hash mismatch")
        manifest_kind_counts = {
            kind: int(manifest.get("kind_counts", {}).get(kind, 0))
            for kind in NEURON_KINDS
        }
        if counts != manifest_kind_counts:
            violations.append("kind counts mismatch")
        if lifecycles != manifest["lifecycle_counts"]:
            violations.append("lifecycle counts mismatch")
        ledger_events = 0
        ledger_head = "0" * 64
        if self.ledger_path.is_file():
            with self.ledger_path.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if not line.strip():
                        continue
                    event = json.loads(line)
                    claimed = str(event.pop("event_sha256", ""))
                    observed = hashlib.sha256(canonical_json(event)).hexdigest().upper()
                    if event.get("schema") != LEDGER_SCHEMA:
                        violations.append(f"ledger line {line_number}: schema mismatch")
                    if event.get("prior_event_sha256") != ledger_head:
                        violations.append(f"ledger line {line_number}: chain mismatch")
                    if claimed != observed:
                        violations.append(f"ledger line {line_number}: event hash mismatch")
                    ledger_head = claimed
                    ledger_events += 1
        if ledger_events != int(manifest["events"]):
            violations.append("ledger event count mismatch")
        if ledger_head != manifest["ledger_head"]:
            violations.append("ledger head mismatch")
        protected = {
            path: file_sha256(path) if Path(path).is_file() else "MISSING"
            for path in manifest["protected_hashes"]
        }
        protected_unchanged = protected == manifest["protected_hashes"]
        if not protected_unchanged:
            violations.append("protected hash changed")
        return {
            "state": "PASS" if not violations else "FAIL",
            "neurons": len(manifest["neuron_index"]),
            "kind_counts": counts,
            "lifecycle_counts": lifecycles,
            "ledger_events": ledger_events,
            "ledger_chain_valid": not any("ledger" in item for item in violations),
            "protected_unchanged": protected_unchanged,
            "violations": violations,
        }

    def decay_plastic_links(
        self,
        neuron_ids: Iterable[str],
        *,
        decay_rate: int = 50_000,
        hot_floor: int = 10_000,
    ) -> dict[str, Any]:
        if not 0 < decay_rate <= SCALE or not 0 <= hot_floor <= SCALE:
            raise ValueError("invalid decay controls")
        changed: list[dict[str, Any]] = []
        links_weakened = 0
        dormant = 0
        for neuron_id in neuron_ids:
            neuron = self.load_neuron(neuron_id)
            for edges in neuron["reflectors"].values():
                for edge in edges:
                    if edge["fail_hits"] <= edge["pass_hits"] or not edge.get("hot", True):
                        continue
                    edge["weight"] = toward_zero(int(edge["weight"]), decay_rate)
                    links_weakened += 1
                    if edge["weight"] < hot_floor:
                        edge["hot"] = False
            hot_links = sum(
                bool(edge.get("hot", True))
                for edges in neuron["reflectors"].values()
                for edge in edges
            )
            if neuron["kind"] != "WORD" and neuron["lifecycle"] == "PLASTIC" and hot_links == 0:
                neuron["lifecycle"] = "DORMANT"
                dormant += 1
            changed.append(neuron)
        if changed:
            self.transact(
                changed,
                event_kind="BIOLOGICAL_DECAY",
                details={"links_weakened": links_weakened, "neurons_dormant": dormant},
            )
        return {"state": "PASS", "links_weakened": links_weakened, "neurons_dormant": dormant}

    def archive_dormant(self, neuron_id: str, *, reason: str) -> dict[str, Any]:
        neuron = self.load_neuron(neuron_id)
        if neuron["lifecycle"] != "DORMANT":
            return {"state": "HOLD", "reason": "NEURON_NOT_DORMANT", "neuron_id": neuron_id}
        neuron["lifecycle"] = "ARCHIVED"
        for edges in neuron["reflectors"].values():
            for edge in edges:
                edge["hot"] = False
        event_id = self.transact(
            [neuron],
            event_kind="REVERSIBLE_ARCHIVE",
            details={"neuron_id": neuron_id, "reason": reason},
        )
        archived = self.load_neuron(neuron_id)
        archive_path = self.root / "archive" / neuron_id / f"{archived['content_sha256']}.json"
        self._write_json_atomic(archive_path, archived)
        return {
            "state": "PASS",
            "neuron_id": neuron_id,
            "event_id": event_id,
            "archive_path": str(archive_path),
            "original_retained": self.neuron_path(neuron_id).is_file(),
        }


def project_admitted_words(store: GraphStore, language_state_path: str | Path) -> dict[str, Any]:
    from .language_state import GpuLanguageState

    state = GpuLanguageState.load(language_state_path)
    expected_words = {
        learned_word(bucket)
        for bucket in state.buckets.values()
        if bucket.visible.level == "WORD" and bucket.state == "PASS"
    }
    created: list[dict[str, Any]] = []
    existing = store.manifest()["word_index"]
    for bucket_id, bucket in sorted(state.buckets.items()):
        if bucket.visible.level != "WORD" or bucket.state != "PASS":
            continue
        surface = learned_word(bucket)
        if surface in existing:
            continue
        bucket_payload = bucket.public()
        bucket_sha = hashlib.sha256(canonical_json(bucket_payload)).hexdigest().upper()
        word_key = f"WORD:{surface}"
        center = {
            "learned_surface": surface,
            "language_bucket_id": bucket_id,
            "language_bucket_sha256": bucket_sha,
            "behavioral_profile_ref": word_key if word_key in state.behavioral_profiles else "",
            "latent_category_refs": sorted(
                category_id
                for category_id, category in state.latent_categories.items()
                if word_key in category.get("members", [])
            ),
            "self_dictionary_ref": word_key if word_key in state.learned_dictionary else "",
            "self_thesaurus_ref": word_key if word_key in state.learned_thesaurus else "",
            "truth_compatibility": SCALE,
        }
        created.append(
            make_neuron(
                neuron_id=stable_word_neuron_id(bucket_id),
                kind="WORD",
                lifecycle="STABLE",
                center=center,
                creation_event="PROJECT_ADMITTED_WORD",
            )
        )
    if created:
        store.transact(
            created,
            event_kind="PROJECT_ADMITTED_WORDS",
            details={"created": len(created), "source_state_sha256": file_sha256(language_state_path)},
        )
    return {
        "state": (
            "PASS"
            if set(store.manifest()["word_index"]) == expected_words
            else "HOLD"
        ),
        "created": len(created),
        "word_neurons": len(store.manifest()["word_index"]),
        "expected_admitted_words": len(expected_words),
    }


def create_character_neurons(
    store: GraphStore, corpus_path: str | Path
) -> dict[str, Any]:
    """Birth one untrusted CHARACTER neuron for every corpus character."""

    artifact = json.loads(Path(corpus_path).read_text(encoding="utf-8"))
    if artifact.get("schema") != "NN_BOOK_CHARACTER_CORPUS_V1":
        raise ValueError("unsupported character corpus")
    lessons = list(artifact.get("lessons", []))
    existing = store.manifest().get("character_index", {})
    created: list[dict[str, Any]] = []
    for row in lessons:
        character = str(row["key"])
        if character in existing:
            continue
        neuron_id = stable_character_neuron_id(character)
        created.append(
            make_neuron(
                neuron_id=neuron_id,
                kind="CHARACTER",
                lifecycle="NEWBORN",
                creation_event="CHARACTER_EXPERIENCE_BIRTH",
                foundation=True,
                center={
                    "learned_character": character,
                    "input_node_id": f"IN:{neuron_id}",
                    "output_node_id": f"OUT:{neuron_id}",
                    "activation_prior": SCALE // 2,
                    "truth_compatibility": SCALE // 2,
                    "trusted_language_memory": False,
                },
            )
        )
    if created:
        store.transact(
            created,
            event_kind="CHARACTER_EXPERIENCE_BIRTH",
            details={
                "created": len(created),
                "corpus_sha256": file_sha256(corpus_path),
                "trusted_language_memory": False,
            },
        )
    manifest = store.manifest()
    return {
        "state": "PASS" if len(manifest.get("character_index", {})) == len(lessons) else "HOLD",
        "created": len(created),
        "character_neurons": len(manifest.get("character_index", {})),
        "expected_characters": len(lessons),
    }


def project_recursive_word_memory(
    store: GraphStore,
    memory_artifact_path: str | Path,
    *,
    language_state_path: str | Path | None = None,
) -> dict[str, Any]:
    """Materialize one stable target-free recursive word as a WORD expert."""

    artifact_path = Path(memory_artifact_path).resolve()
    with artifact_path.open("r", encoding="utf-8") as handle:
        artifact = json.load(handle)
    if artifact.get("schema") != "NN_RECURSIVE_WORD_MEMORY_ARTIFACT_V1":
        raise ValueError("unsupported recursive word memory artifact")

    # Import locally so the base graph schema remains usable without loading
    # the native word router.  The artifact itself is still fully validated.
    from .recursive_word import RecursiveWordMemory

    memory_payload = dict(artifact["memory"])
    memory = RecursiveWordMemory.from_public(memory_payload)
    if memory.state != "STABLE":
        return {"state": "HOLD", "reason": "WORD_MEMORY_NOT_STABLE"}
    if memory.content_hash() != str(artifact.get("memory_sha256", "")):
        raise ValueError("recursive word memory artifact hash mismatch")

    visible_bucket_id = str(artifact.get("visible_bucket_id", ""))
    rendering = tuple(str(item) for item in artifact.get("stable_rendering", []))
    expected = Counter(
        symbol
        for symbol, count in zip(memory.candidate_ids, memory.inventory, strict=True)
        for _ in range(count)
    )
    if (
        not visible_bucket_id
        or not rendering
        or len(rendering) != sum(memory.inventory)
        or Counter(rendering) != expected
        or any(not item.startswith("CHAR:") for item in rendering)
    ):
        raise ValueError("stable recursive word rendering does not match its inventory")
    surface = "".join(item.removeprefix("CHAR:") for item in rendering)
    neuron_id = stable_word_neuron_id(visible_bucket_id)
    manifest = store.manifest()
    existing_id = manifest.get("word_index", {}).get(surface)
    if existing_id is not None:
        existing = store.load_neuron(str(existing_id))
        if (
            existing["neuron_id"] == neuron_id
            and existing["center_attractor"].get("recursive_word_memory_sha256")
            == str(artifact["memory_sha256"])
        ):
            return {
                "state": "PASS",
                "created": 0,
                "word_neuron_id": neuron_id,
                "surface": surface,
                "reason": "ALREADY_PROJECTED",
            }
        return {
            "state": "HOLD",
            "reason": "WORD_SURFACE_IDENTITY_CONFLICT",
            "surface": surface,
            "existing_neuron_id": str(existing_id),
        }
    if neuron_id in manifest.get("neuron_index", {}):
        raise ValueError("recursive word neuron ID exists with another surface")

    center: dict[str, Any] = {
        "learned_surface": surface,
        "visible_bucket_id": visible_bucket_id,
        "recursive_word_memory_ref": str(artifact_path),
        "recursive_word_memory_sha256": file_sha256(artifact_path),
        "recursive_word_memory_content_sha256": str(artifact["memory_sha256"]),
        "learned_character_construction": list(rendering),
        "behavioral_profile_ref": "",
        "latent_category_refs": [],
        "self_dictionary_ref": "",
        "self_thesaurus_ref": "",
        "truth_compatibility": SCALE,
        "trusted_language_memory": True,
        "admission_state": "ADMITTED_AFTER_WORD_CONFIRMATIONS",
    }
    if language_state_path is not None:
        from .language_state import GpuLanguageState

        state = GpuLanguageState.load(language_state_path)
        bucket = state.buckets.get(visible_bucket_id)
        if bucket is not None and bucket.state == "PASS":
            center["language_bucket_id"] = visible_bucket_id
            center["language_bucket_sha256"] = hashlib.sha256(
                canonical_json(bucket.public())
            ).hexdigest().upper()
    neuron = make_neuron(
        neuron_id=neuron_id,
        kind="WORD",
        lifecycle="STABLE",
        creation_event="PROJECT_STABLE_RECURSIVE_WORD",
        center=center,
    )
    store.transact(
        [neuron],
        event_kind="PROJECT_STABLE_RECURSIVE_WORD",
        details={
            "word_neuron_id": neuron_id,
            "memory_artifact_sha256": file_sha256(artifact_path),
            "source_bucket_id": visible_bucket_id,
        },
    )
    return {
        "state": "PASS",
        "created": 1,
        "word_neuron_id": neuron_id,
        "surface": surface,
        "memory_artifact_sha256": file_sha256(artifact_path),
    }


def project_visible_states(store: GraphStore, state_ids: Iterable[str]) -> dict[str, Any]:
    """Make externally visible construction symbols addressable without encoding order.

    Word states resolve to the already admitted word neurons.  Orthography states
    are neutral sentence-level symbols, analogous to the already available
    character inventory; their use and routing are learned only from verdicts.
    """

    manifest = store.manifest()
    state_index = dict(manifest.get("state_index", {}))
    for surface, neuron_id in manifest["word_index"].items():
        state_index.setdefault(f"WORD:{surface}", neuron_id)
    created: list[dict[str, Any]] = []
    for state_id in sorted(set(str(item) for item in state_ids)):
        if state_id in state_index:
            continue
        if state_id.startswith("WORD:"):
            surface = state_id.removeprefix("WORD:")
            if surface not in manifest["word_index"]:
                raise ValueError(f"unsupported word state: {state_id}")
            state_index[state_id] = manifest["word_index"][surface]
            continue
        if not state_id.startswith("ORTHO:"):
            raise ValueError(f"unsupported visible construction state: {state_id}")
        digest = hashlib.sha256(f"VISIBLE_STATE\0{state_id}".encode("utf-8")).hexdigest().upper()
        neuron = make_neuron(
            neuron_id=f"N-{digest[:32]}",
            kind="CONCEPT",
            lifecycle="PLASTIC",
            creation_event="PROJECT_VISIBLE_CONSTRUCTION_STATE",
            center={
                "visible_state_id": state_id,
                "truth_compatibility": SCALE,
                "trusted_language_memory": False,
            },
        )
        created.append(neuron)
        state_index[state_id] = neuron["neuron_id"]

    def update_index(current: dict[str, Any]) -> None:
        current.setdefault("state_index", {}).update(state_index)

    if created:
        store.transact(
            created,
            event_kind="PROJECT_VISIBLE_CONSTRUCTION_STATES",
            details={"created": len(created), "visible_states": len(state_index)},
            manifest_mutator=update_index,
        )
    elif manifest.get("state_index") != state_index:
        # A transaction is required so the derived index remains atomic and
        # ledger-backed. Rewriting one existing neuron leaves its content intact.
        anchor_id = next(iter(manifest["neuron_index"]))
        store.transact(
            [store.load_neuron(anchor_id)],
            event_kind="REBUILD_VISIBLE_STATE_INDEX",
            details={"visible_states": len(state_index)},
            manifest_mutator=update_index,
        )
    return {
        "state": "PASS",
        "created": len(created),
        "visible_states": len(store.manifest().get("state_index", {})),
    }


def find_edge(neuron: dict[str, Any], peer_id: str, direction: str) -> tuple[str, dict[str, Any]] | None:
    for reflector, edges in neuron["reflectors"].items():
        for edge in edges:
            if edge["peer_id"] == peer_id and edge["direction"] == direction:
                return reflector, edge
    return None


def reflector_for(source_id: str, peer_id: str) -> str:
    digest = hashlib.sha256(f"{source_id}\0{peer_id}".encode("utf-8")).digest()
    return REFLECTORS[digest[0] % len(REFLECTORS)]


def reinforce_connection(
    source: dict[str, Any],
    peer_id: str,
    *,
    direction: str,
    passed: bool,
    event_id: str,
    initial_weight: int = SCALE // 2,
) -> None:
    found = find_edge(source, peer_id, direction)
    if found is None:
        reflector = reflector_for(source["neuron_id"], peer_id)
        edge = {
            "peer_id": peer_id,
            "direction": direction,
            "weight": initial_weight,
            "uses": 0,
            "pass_hits": 0,
            "fail_hits": 0,
            "evidence_events": [],
            "hot": True,
        }
        source["reflectors"][reflector].append(edge)
    else:
        _, edge = found
    edge["uses"] += 1
    edge["evidence_events"].append(event_id)
    if passed:
        edge["pass_hits"] += 1
        edge["weight"] = toward_one(edge["weight"], 900_000)
        edge["hot"] = True
    else:
        edge["fail_hits"] += 1
        edge["weight"] = toward_zero(edge["weight"], 150_000)
        if edge["weight"] < 10_000:
            edge["hot"] = False


__all__ = [
    "GRAPH_SCHEMA",
    "GraphStore",
    "LIFECYCLES",
    "NEURON_KINDS",
    "REFLECTORS",
    "content_hash",
    "file_sha256",
    "learned_word",
    "make_neuron",
    "new_neuron_id",
    "stable_character_neuron_id",
    "stable_combination_neuron_id",
    "project_admitted_words",
    "create_character_neurons",
    "project_recursive_word_memory",
    "project_visible_states",
    "reinforce_connection",
    "validate_neuron",
]
