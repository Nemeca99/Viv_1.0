"""Candidate-only, append-only registry for deterministically gated functions.

The registry is deliberately separate from viv_code_topology.sqlite3. Every
write is authorized by PrivacyCore, and an implementation must pass the
existing Python/Rust body gate before its source or gate receipt is admitted.
Frozen held-out task IDs are never admissible.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
sys.path.insert(0, str(WORKSPACE))
sys.path.insert(0, str(HERE))

from aios_rebuild.privacy_core.privacy_core import PrivacyCore
import viv_code_learning_loop as gates

DB_PATH = HERE / "learning" / "neural_runs" / "candidate_verified_functions.sqlite3"
SUITE_PATH = HERE / "learning" / "deepseek_candidate_runs" / "frozen_code_eval_v2_1.json"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _task_ids() -> set[str]:
    envelope = json.loads(SUITE_PATH.read_text(encoding="utf-8"))
    expected = envelope.pop("suite_sha256", None)
    if expected != canonical_hash(envelope):
        raise ValueError("FROZEN_SUITE_HASH_MISMATCH")
    return {str(row["id"]) for row in envelope.get("held_out", [])}


def _function_identity(lang: str, domain: str, spec: str) -> tuple[str, str, str]:
    if lang == "python":
        match = re.search(r"\bdef\s+([A-Za-z_]\w*)\s*\((.*?)\)\s*(?:->\s*[^:]+)?\s*:", spec, re.S)
    elif lang == "rust":
        match = re.search(r"\bpub\s+fn\s+([A-Za-z_]\w*)\s*\((.*?)\)\s*(?:->\s*[^:]+)?\s*(?::|\{)", spec, re.S)
    else:
        raise ValueError("LANGUAGE_UNSUPPORTED")
    if not match:
        raise ValueError("FUNCTION_SIGNATURE_NOT_FOUND")
    name = match.group(1)
    signature = re.sub(r"\s+", " ", match.group(0)).strip()
    identity = canonical_hash({"lang": lang, "domain": domain.casefold().strip(),
                               "name": name, "signature": signature,
                               "contract": spec.strip()})
    return identity, name, signature


def _connection() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH, timeout=15)


def initialize() -> None:
    """Create the candidate registry after PrivacyCore authorizes its path."""
    privacy = PrivacyCore()
    decision = privacy.authorize_file_write(str(DB_PATH))
    if decision.get("allowed") is not True:
        raise PermissionError(f"PrivacyCore denied candidate DB: {decision}")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connection() as db:
        db.executescript("""
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS functions (
                function_key TEXT PRIMARY KEY,
                language TEXT NOT NULL,
                domain TEXT NOT NULL,
                function_name TEXT NOT NULL,
                signature TEXT NOT NULL,
                specification TEXT NOT NULL,
                contract_sha256 TEXT NOT NULL,
                created_utc TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS function_versions (
                version_id INTEGER PRIMARY KEY AUTOINCREMENT,
                function_key TEXT NOT NULL REFERENCES functions(function_key),
                parent_version_id INTEGER REFERENCES function_versions(version_id),
                task_id TEXT NOT NULL,
                source_kind TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                code TEXT NOT NULL,
                code_sha256 TEXT NOT NULL,
                tests_sha256 TEXT NOT NULL,
                gate_name TEXT NOT NULL,
                gate_status TEXT NOT NULL CHECK(gate_status='ALLOW'),
                gate_output TEXT NOT NULL,
                gate_receipt_sha256 TEXT NOT NULL,
                admitted_utc TEXT NOT NULL,
                UNIQUE(function_key, code_sha256, tests_sha256)
            );
            CREATE TABLE IF NOT EXISTS active_versions (
                function_key TEXT PRIMARY KEY REFERENCES functions(function_key),
                version_id INTEGER NOT NULL REFERENCES function_versions(version_id),
                selection_reason TEXT NOT NULL,
                selected_utc TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_function_versions_key
                ON function_versions(function_key, version_id);
            CREATE TABLE IF NOT EXISTS admission_journal (
                journal_id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                function_key TEXT NOT NULL,
                code_sha256 TEXT NOT NULL,
                decision TEXT NOT NULL,
                reason TEXT NOT NULL,
                receipt_sha256 TEXT NOT NULL,
                created_utc TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS proposal_attempts (
                attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                function_key TEXT NOT NULL,
                language TEXT NOT NULL,
                source_kind TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                code TEXT NOT NULL,
                code_sha256 TEXT NOT NULL,
                tests_sha256 TEXT NOT NULL,
                gate_status TEXT NOT NULL CHECK(gate_status IN ('ALLOW','DENY')),
                gate_output TEXT NOT NULL,
                gate_receipt_sha256 TEXT NOT NULL,
                created_utc TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS integer_networks (
                network_key TEXT PRIMARY KEY,
                network_name TEXT NOT NULL,
                contract_json TEXT NOT NULL,
                created_utc TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS integer_network_versions (
                version_id INTEGER PRIMARY KEY AUTOINCREMENT,
                network_key TEXT NOT NULL REFERENCES integer_networks(network_key),
                parent_version_id INTEGER REFERENCES integer_network_versions(version_id),
                task_id TEXT NOT NULL,
                mode_indices_json TEXT NOT NULL,
                mode_indices_sha256 TEXT NOT NULL,
                source_path TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                tests_sha256 TEXT NOT NULL,
                gate_name TEXT NOT NULL,
                gate_status TEXT NOT NULL CHECK(gate_status='ALLOW'),
                gate_output TEXT NOT NULL,
                gate_receipt_sha256 TEXT NOT NULL,
                admitted_utc TEXT NOT NULL,
                UNIQUE(network_key,mode_indices_sha256,tests_sha256)
            );
            CREATE TABLE IF NOT EXISTS active_integer_network_versions (
                network_key TEXT PRIMARY KEY REFERENCES integer_networks(network_key),
                version_id INTEGER NOT NULL REFERENCES integer_network_versions(version_id),
                selection_reason TEXT NOT NULL,
                selected_utc TEXT NOT NULL
            );
        """)


def admit_candidate(*, task_id: str, lang: str, domain: str, spec: str,
                    code: str, tests: str, source_kind: str,
                    source_sha256: str, parent_version_id: int | None = None,
                    expected_gate: str = "existing_body_gate") -> dict[str, Any]:
    """Gate then append a candidate version; first admitted version becomes active.

    Later versions are retained but do not silently replace the active version.
    Selection is a separate operation requiring a passing explicit comparison.
    """
    if task_id in _task_ids():
        raise ValueError("HELD_OUT_TASK_ADMISSION_DENIED")
    if not all(isinstance(value, str) and value.strip() for value in
               (task_id, lang, domain, spec, code, tests, source_kind, source_sha256)):
        raise ValueError("ADMISSION_FIELDS_REQUIRED")
    key, name, signature = _function_identity(lang, domain, spec)
    gate = gates.gate_python if lang == "python" else gates.gate_rust
    passed, output = gate(code, tests)
    now = datetime.now(timezone.utc).isoformat()
    code_hash, tests_hash = sha256_text(code), sha256_text(tests)
    gate_receipt = {"task_id": task_id, "language": lang, "function_key": key,
                    "code_sha256": code_hash, "tests_sha256": tests_hash,
                    "gate": expected_gate, "status": "ALLOW" if passed else "DENY",
                    "output": output[:4000], "created_utc": now}
    gate_receipt_hash = canonical_hash(gate_receipt)
    privacy = PrivacyCore()
    decision = privacy.authorize_file_write(str(DB_PATH))
    if decision.get("allowed") is not True:
        raise PermissionError(f"PrivacyCore denied candidate DB: {decision}")
    initialize()
    with _connection() as db:
        db.execute("INSERT INTO proposal_attempts(task_id,function_key,language,source_kind,source_sha256,code,code_sha256,tests_sha256,gate_status,gate_output,gate_receipt_sha256,created_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   (task_id, key, lang, source_kind, source_sha256, code, code_hash,
                    sha256_text(tests), gate_receipt["status"], output[:4000],
                    gate_receipt_hash, now))
        if not passed:
            db.execute("INSERT INTO admission_journal(task_id,function_key,code_sha256,decision,reason,receipt_sha256,created_utc) VALUES(?,?,?,?,?,?,?)",
                       (task_id, key, code_hash, "DENY", output[:4000], gate_receipt_hash, now))
            return {**gate_receipt, "gate_receipt_sha256": gate_receipt_hash,
                    "decision": "DENY", "version_id": None}
        db.execute("INSERT OR IGNORE INTO functions(function_key,language,domain,function_name,signature, specification,contract_sha256,created_utc) VALUES(?,?,?,?,?,?,?,?)",
                   (key, lang, domain, name, signature, spec, sha256_text(spec), now))
        try:
            cur = db.execute("INSERT INTO function_versions(function_key,parent_version_id,task_id,source_kind,source_sha256,code,code_sha256,tests_sha256,gate_name,gate_status,gate_output,gate_receipt_sha256,admitted_utc) VALUES(?,?,?,?,?,?,?,?,?,'ALLOW',?,?,?)",
                             (key, parent_version_id, task_id, source_kind, source_sha256,
                              code, code_hash, tests_hash, expected_gate, output[:4000],
                              gate_receipt_hash, now))
            version_id = cur.lastrowid
        except sqlite3.IntegrityError:
            row = db.execute("SELECT version_id FROM function_versions WHERE function_key=? AND code_sha256=? AND tests_sha256=?",
                             (key, code_hash, tests_hash)).fetchone()
            if row is None:
                raise
            version_id = row[0]
        db.execute("INSERT INTO admission_journal(task_id,function_key,code_sha256,decision,reason,receipt_sha256,created_utc) VALUES(?,?,?,?,?,?,?)",
                   (task_id, key, code_hash, "ALLOW", "deterministic body gate passed", gate_receipt_hash, now))
        db.execute("INSERT OR IGNORE INTO active_versions(function_key,version_id,selection_reason,selected_utc) VALUES(?,?,?,?)",
                   (key, version_id, "first gate-accepted version", now))
    return {**gate_receipt, "gate_receipt_sha256": gate_receipt_hash,
            "decision": "ALLOW", "version_id": version_id}


def proposal_history(task_id: str) -> list[dict[str, Any]]:
    """Return preserved accepted and rejected proposals for one task."""
    if not DB_PATH.is_file():
        return []
    with _connection() as db:
        rows = db.execute("""
            SELECT attempt_id,function_key,language,source_kind,source_sha256,
                   code,code_sha256,tests_sha256,gate_status,gate_output,
                   gate_receipt_sha256,created_utc
            FROM proposal_attempts WHERE task_id=? ORDER BY attempt_id
        """, (task_id,)).fetchall()
    fields = ("attempt_id", "function_key", "language", "source_kind",
              "source_sha256", "code", "code_sha256", "tests_sha256",
              "gate_status", "gate_output", "gate_receipt_sha256", "created_utc")
    return [dict(zip(fields, row)) for row in rows]


def admit_integer_network(*, task_id: str, network_name: str,
                          contract: dict[str, Any], mode_indices: tuple[int, ...],
                          code: str, tests: str, source_path: str,
                          source_sha256: str, parent_version_id: int | None = None,
                          gate_name: str = "python_docker_body_gate") -> dict[str, Any]:
    """Gate and append fixed-integer network state to the candidate DB."""
    if task_id in _task_ids():
        raise ValueError("HELD_OUT_TASK_ADMISSION_DENIED")
    if (len(mode_indices) != 3 or any(type(value) is not int or not 0 <= value < 6
                                     for value in mode_indices)):
        raise ValueError("INTEGER_NETWORK_MODE_INDICES_INVALID")
    if not all(isinstance(value, str) and value.strip() for value in
               (task_id, network_name, code, tests, source_path, source_sha256)):
        raise ValueError("INTEGER_NETWORK_ADMISSION_FIELDS_REQUIRED")
    contract_json = json.dumps(contract, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"))
    network_key = canonical_hash({"network_name": network_name,
                                  "contract": json.loads(contract_json)})
    modes_json = json.dumps(list(mode_indices), separators=(",", ":"))
    modes_hash = hashlib.sha256(modes_json.encode("utf-8")).hexdigest()
    code_hash, tests_hash = sha256_text(code), sha256_text(tests)
    passed, output = gates.gate_python(code, tests)
    now = datetime.now(timezone.utc).isoformat()
    gate_receipt = {"task_id": task_id, "network_key": network_key,
                    "mode_indices": json.loads(modes_json), "mode_indices_sha256": modes_hash,
                    "code_sha256": code_hash, "tests_sha256": tests_hash,
                    "gate_name": gate_name, "status": "ALLOW" if passed else "DENY",
                    "output": output[:4000], "created_utc": now}
    receipt_hash = canonical_hash(gate_receipt)
    privacy = PrivacyCore()
    decision = privacy.authorize_file_write(str(DB_PATH))
    if decision.get("allowed") is not True:
        raise PermissionError(f"PrivacyCore denied candidate DB: {decision}")
    initialize()
    if not passed:
        return {**gate_receipt, "gate_receipt_sha256": receipt_hash,
                "decision": "DENY", "version_id": None}
    with _connection() as db:
        db.execute("INSERT OR IGNORE INTO integer_networks(network_key,network_name,contract_json,created_utc) VALUES(?,?,?,?)",
                   (network_key, network_name, contract_json, now))
        try:
            cur = db.execute("""
                INSERT INTO integer_network_versions(
                    network_key,parent_version_id,task_id,mode_indices_json,
                    mode_indices_sha256,source_path,source_sha256,tests_sha256,
                    gate_name,gate_status,gate_output,gate_receipt_sha256,admitted_utc
                ) VALUES(?,?,?,?,?,?,?,?,?,'ALLOW',?,?,?)
            """, (network_key, parent_version_id, task_id, modes_json, modes_hash,
                  source_path, source_sha256, tests_hash, gate_name, output[:4000],
                  receipt_hash, now))
            version_id = cur.lastrowid
        except sqlite3.IntegrityError:
            found = db.execute("""
                SELECT version_id FROM integer_network_versions
                WHERE network_key=? AND mode_indices_sha256=? AND tests_sha256=?
            """, (network_key, modes_hash, tests_hash)).fetchone()
            if found is None:
                raise
            version_id = found[0]
        db.execute("""
            INSERT OR IGNORE INTO active_integer_network_versions(
                network_key,version_id,selection_reason,selected_utc
            ) VALUES(?,?,?,?)
        """, (network_key, version_id, "first truth-table-gated candidate state", now))
    return {**gate_receipt, "gate_receipt_sha256": receipt_hash,
            "decision": "ALLOW", "version_id": version_id}


def get_active_integer_network(network_name: str,
                               contract: dict[str, Any]) -> dict[str, Any] | None:
    """Return the candidate-only immutable integer state for an exact contract."""
    if not DB_PATH.is_file():
        return None
    key = canonical_hash({"network_name": network_name, "contract": contract})
    with _connection() as db:
        row = db.execute("""
            SELECT n.network_key,n.network_name,v.version_id,v.task_id,
                   v.mode_indices_json,v.mode_indices_sha256,v.source_path,
                   v.source_sha256,v.tests_sha256,v.gate_receipt_sha256,
                   v.gate_status
            FROM active_integer_network_versions a
            JOIN integer_networks n USING(network_key)
            JOIN integer_network_versions v ON v.version_id=a.version_id
            WHERE n.network_key=?
        """, (key,)).fetchone()
    if row is None:
        return None
    fields = ("network_key", "network_name", "version_id", "task_id",
              "mode_indices_json", "mode_indices_sha256", "source_path",
              "source_sha256", "tests_sha256", "gate_receipt_sha256", "gate_status")
    result = dict(zip(fields, row))
    result["mode_indices"] = json.loads(result.pop("mode_indices_json"))
    return result


def get_active(*, lang: str, domain: str, spec: str) -> dict[str, Any] | None:
    """Retrieve the deterministic active implementation for an exact contract."""
    key, _, _ = _function_identity(lang, domain, spec)
    if not DB_PATH.is_file():
        return None
    with _connection() as db:
        row = db.execute("""
            SELECT f.function_key, f.language, f.domain, f.function_name,
                   v.version_id, v.task_id, v.code, v.code_sha256,
                   v.tests_sha256, v.gate_receipt_sha256
            FROM active_versions a
            JOIN functions f USING(function_key)
            JOIN function_versions v ON v.version_id=a.version_id
            WHERE a.function_key=? AND v.gate_status='ALLOW'
        """, (key,)).fetchone()
    if row is None:
        return None
    return dict(zip(("function_key", "language", "domain", "function_name",
                     "version_id", "task_id", "code", "code_sha256",
                     "tests_sha256", "gate_receipt_sha256"), row))


def versions(*, lang: str, domain: str, spec: str) -> list[dict[str, Any]]:
    """List immutable versions newest-first for A/B comparison and repair history."""
    key, _, _ = _function_identity(lang, domain, spec)
    if not DB_PATH.is_file():
        return []
    with _connection() as db:
        rows = db.execute("""
            SELECT version_id,parent_version_id,task_id,source_kind,source_sha256,
                   code,code_sha256,tests_sha256,gate_name,gate_status,
                   gate_output,gate_receipt_sha256,admitted_utc
            FROM function_versions WHERE function_key=? ORDER BY version_id DESC
        """, (key,)).fetchall()
    fields = ("version_id", "parent_version_id", "task_id", "source_kind",
              "source_sha256", "code", "code_sha256", "tests_sha256", "gate_name",
              "gate_status", "gate_output", "gate_receipt_sha256", "admitted_utc")
    return [dict(zip(fields, row)) for row in rows]
