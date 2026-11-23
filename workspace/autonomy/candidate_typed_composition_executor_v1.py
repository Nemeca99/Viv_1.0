"""Execute a candidate Python circuit from persisted, typed relay evidence.

The executor reads only ALLOW candidate versions and the append-only typed
relay graph. It validates version receipts, contract identity, relay digests,
source call sites, and types before composing exact function definitions. Each
dependency subtree and the requested entry function must pass the existing
deterministic Python gate. No active pointer, learned memory, live topology,
model weights, or candidate graph rows are changed.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import uuid

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
ROOT = WORKSPACE.parent
sys.path[:0] = [str(WORKSPACE), str(HERE)]

import candidate_typed_function_relays_v1 as relay_builder
import candidate_verified_function_store as store
import viv_code_learning_loop as gates
from aios_rebuild.privacy_core.privacy_core import PrivacyCore

DB_PATH = store.DB_PATH
CURRICULUM_PATH = HERE / "python_edge_curriculum_test_10017.py"
RECEIPT_ROOT = HERE / "learning" / "neural_runs" / "composition_receipts"
GOAL_ID = "01a1d847-3b27-7533-bbc2-c718ace48ae7"
TABLE = "typed_function_relays_v1"
MAX_DEPTH = 16
MAX_NODES = 32


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def canonical_hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return sha256_bytes(encoded)


def body_preflight() -> dict:
    command = [str(Path(sys.executable)), "-m",
               "aios_rebuild.main_core.mind_runtime_gate",
               "--goal-id", GOAL_ID]
    result = subprocess.run(command, cwd=WORKSPACE, capture_output=True,
                            text=True, encoding="utf-8", timeout=45)
    if result.returncode != 0:
        raise RuntimeError("RUST_BODY_PREFLIGHT_FAILED:" + result.stderr[-1200:])
    try:
        body = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError("RUST_BODY_PREFLIGHT_INVALID_JSON") from exc
    if (body.get("allowed") is not True
            or body.get("authority") != "deterministic_aios_body_rust"
            or body.get("disposition") != "ALLOW_MIND_RUNTIME"):
        raise PermissionError("RUST_BODY_PREFLIGHT_DENIED:" + json.dumps(body))
    return body


def load_curriculum() -> dict[str, dict]:
    spec = importlib.util.spec_from_file_location(
        "candidate_composition_executor_curriculum", CURRICULUM_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("CURRICULUM_IMPORT_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows = module.CURRICULUM + module.EDGE_TRANSFER_CURRICULUM
    result: dict[str, dict] = {}
    for row in rows:
        task_id = str(row.get("id", ""))
        if not task_id or task_id in result:
            raise ValueError("CURRICULUM_TASK_ID_MISSING_OR_DUPLICATE")
        result[task_id] = row
    return result


def open_readonly() -> sqlite3.Connection:
    if not DB_PATH.is_file():
        raise FileNotFoundError(DB_PATH)
    connection = sqlite3.connect(
        f"file:{DB_PATH.as_posix()}?mode=ro", uri=True, timeout=15)
    connection.row_factory = sqlite3.Row
    return connection


def load_version(db: sqlite3.Connection, version_id: int) -> dict:
    row = db.execute("""
        SELECT f.function_key,f.language,f.domain,f.function_name,f.signature,
               f.specification,f.contract_sha256,
               v.version_id,v.parent_version_id,v.task_id,v.source_kind,
               v.source_sha256,v.code,v.code_sha256,v.tests_sha256,
               v.gate_name,v.gate_status,v.gate_output,v.gate_receipt_sha256,
               v.admitted_utc
        FROM function_versions v
        JOIN functions f USING(function_key)
        WHERE v.version_id=?
    """, (version_id,)).fetchone()
    if row is None:
        raise ValueError(f"FUNCTION_VERSION_NOT_FOUND:{version_id}")
    version = dict(row)
    name = version["function_name"]
    if version["language"] != "python" or version["gate_status"] != "ALLOW":
        raise ValueError(f"FUNCTION_VERSION_NOT_ADMITTED_PYTHON:{version_id}")
    if sha256_text(version["code"]) != version["code_sha256"]:
        raise ValueError(f"FUNCTION_CODE_HASH_MISMATCH:{version_id}")
    if sha256_text(version["specification"]) != version["contract_sha256"]:
        raise ValueError(f"FUNCTION_SPEC_HASH_MISMATCH:{version_id}")
    expected_key, expected_name, expected_signature = store._function_identity(
        version["language"], version["domain"], version["specification"])
    if (expected_key != version["function_key"]
            or expected_name != name
            or expected_signature != version["signature"]):
        raise ValueError(f"FUNCTION_CONTRACT_IDENTITY_MISMATCH:{version_id}")
    gate_evidence = {
        "task_id": version["task_id"], "language": version["language"],
        "function_key": version["function_key"],
        "code_sha256": version["code_sha256"],
        "tests_sha256": version["tests_sha256"],
        "gate": version["gate_name"], "status": version["gate_status"],
        "output": version["gate_output"],
        "created_utc": version["admitted_utc"],
    }
    if canonical_hash(gate_evidence) != version["gate_receipt_sha256"]:
        raise ValueError(f"FUNCTION_GATE_RECEIPT_MISMATCH:{version_id}")
    version["function_code"], version["function_ast"] = relay_builder.extract_function(
        version["code"], name)
    return version


def validate_edge(db: sqlite3.Connection, raw: sqlite3.Row,
                  versions: dict[int, dict]) -> dict:
    stored = json.loads(raw["evidence_json"])
    callsite = json.loads(raw["callsite_json"])
    if not isinstance(stored, dict) or not isinstance(callsite, dict):
        raise ValueError("RELAY_EVIDENCE_NOT_OBJECT")
    if stored.get("schema") != "viv_typed_function_relay_v1":
        raise ValueError("RELAY_SCHEMA_UNSUPPORTED")
    if stored.get("receipt_sha256") != raw["receipt_sha256"]:
        raise ValueError("RELAY_RECEIPT_COLUMN_MISMATCH")
    receipt_payload = dict(stored)
    claimed_receipt = receipt_payload.pop("receipt_sha256")
    if canonical_hash(receipt_payload) != claimed_receipt:
        raise ValueError("RELAY_RECEIPT_HASH_MISMATCH")
    key_payload = dict(receipt_payload)
    claimed_key = key_payload.pop("relay_key", None)
    if claimed_key != raw["relay_key"] or canonical_hash(key_payload) != claimed_key:
        raise ValueError("RELAY_KEY_HASH_MISMATCH")
    provider_id = int(raw["provider_version_id"])
    consumer_id = int(raw["consumer_version_id"])
    provider = versions.setdefault(provider_id, load_version(db, provider_id))
    consumer = versions.setdefault(consumer_id, load_version(db, consumer_id))
    columns = {
        "provider_version_id": provider_id,
        "consumer_version_id": consumer_id,
        "provider_function_name": provider["function_name"],
        "consumer_function_name": consumer["function_name"],
        "direction": "PROVIDER_RETURN_TO_CALLER_TYPED_USE",
        "provider_output_type": raw["provider_output_type"],
        "consumer_input_type": raw["consumer_input_type"],
    }
    for key, value in columns.items():
        if stored.get(key) != value:
            raise ValueError(f"RELAY_COLUMN_EVIDENCE_MISMATCH:{key}")
    if callsite != stored.get("callsite"):
        raise ValueError("RELAY_CALLSITE_COLUMN_MISMATCH")
    if raw["provider_output_type"] != raw["consumer_input_type"]:
        raise ValueError("RELAY_TYPE_EDGE_MISMATCH")
    regenerated = relay_builder.typed_calls(
        provider, consumer, provider["function_code"], consumer["function_code"],
        provider["function_ast"], consumer["function_ast"])
    exact = [item for item in regenerated if item["relay_key"] == raw["relay_key"]]
    if len(exact) != 1 or canonical_hash(exact[0]) != canonical_hash(stored):
        raise ValueError("RELAY_SOURCE_OR_TYPE_EVIDENCE_MISMATCH")
    return {"row": dict(raw), "evidence": stored,
            "provider": provider, "consumer": consumer}


def edges_for_consumer(db: sqlite3.Connection, version_id: int,
                       versions: dict[int, dict]) -> list[dict]:
    rows = db.execute(f"""
        SELECT relay_key,provider_version_id,consumer_version_id,
               provider_function_name,consumer_function_name,direction,
               provider_output_type,consumer_input_type,callsite_json,
               evidence_json,receipt_sha256,created_utc
        FROM {TABLE}
        WHERE consumer_version_id=?
        ORDER BY provider_function_name,callsite_json,relay_key
    """, (version_id,)).fetchall()
    validated = [validate_edge(db, row, versions) for row in rows]
    providers_by_name: dict[str, int] = {}
    for edge in validated:
        name = edge["provider"]["function_name"]
        provider_id = edge["provider"]["version_id"]
        previous = providers_by_name.setdefault(name, provider_id)
        if previous != provider_id:
            raise ValueError(f"AMBIGUOUS_PROVIDER_VERSION:{name}")
    call_names = {
        node.func.id for node in ast.walk(versions[version_id]["function_ast"])
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    candidate_names = {row[0] for row in db.execute("""
        SELECT DISTINCT f.function_name
        FROM function_versions v JOIN functions f USING(function_key)
        WHERE f.language='python' AND v.gate_status='ALLOW'
    """)}
    represented = set(providers_by_name)
    unlinked_candidates = sorted((call_names & candidate_names) - represented)
    if unlinked_candidates:
        raise ValueError("MISSING_TYPED_RELAY:" + ",".join(unlinked_candidates))
    if represented - call_names:
        raise ValueError("RELAY_PROVIDER_NOT_CALLED:" + ",".join(sorted(represented - call_names)))
    return validated


def curriculum_for_version(version: dict, curriculum: dict[str, dict],
                           root_task: dict | None) -> dict:
    task = root_task if root_task is not None else curriculum.get(version["task_id"])
    if task is None:
        raise ValueError(f"CURRICULUM_TEST_SOURCE_UNAVAILABLE:{version['task_id']}")
    if task["spec"] != version["specification"]:
        raise ValueError(f"CURRICULUM_SPEC_MISMATCH:{version['version_id']}")
    if sha256_text(task["tests"]) != version["tests_sha256"]:
        raise ValueError(f"CURRICULUM_TEST_HASH_MISMATCH:{version['version_id']}")
    return task


def execute(entry_task_id: str, persist_receipt: bool = False) -> dict:
    body = body_preflight()
    curriculum = load_curriculum()
    root_task = curriculum.get(entry_task_id)
    if root_task is None:
        raise ValueError(f"ENTRY_TASK_NOT_FOUND:{entry_task_id}")
    db_hash_before = sha256_bytes(DB_PATH.read_bytes())
    versions: dict[int, dict] = {}
    circuit_cache: dict[int, dict] = {}
    visiting: set[int] = set()
    edges_by_consumer: dict[int, list[dict]] = {}

    with open_readonly() as db:
        quick = db.execute("PRAGMA quick_check").fetchone()[0]
        if quick != "ok":
            raise RuntimeError("CANDIDATE_STORE_QUICK_CHECK_FAILED")
        target = db.execute("""
            SELECT v.version_id
            FROM function_versions v JOIN functions f USING(function_key)
            WHERE f.language='python' AND f.function_name=?
              AND f.specification=? AND v.tests_sha256=?
              AND v.gate_status='ALLOW'
            ORDER BY v.version_id DESC
        """, (root_task["spec"].split("(", 1)[0].removeprefix("def "),
              root_task["spec"], sha256_text(root_task["tests"]))).fetchall()
        if len(target) != 1:
            raise ValueError(f"ENTRY_VERSION_NOT_UNIQUE:{entry_task_id}:{len(target)}")
        root_id = int(target[0][0])
        root_version = load_version(db, root_id)
        if root_version["specification"] != root_task["spec"]:
            raise ValueError("ENTRY_SPEC_MISMATCH")
        if root_version["tests_sha256"] != sha256_text(root_task["tests"]):
            raise ValueError("ENTRY_TEST_HASH_MISMATCH")

        def build(version_id: int, depth: int = 0,
                  is_root: bool = False) -> dict:
            if depth > MAX_DEPTH:
                raise ValueError("CIRCUIT_DEPTH_EXCEEDED")
            if version_id in circuit_cache:
                return circuit_cache[version_id]
            if version_id in visiting:
                raise ValueError("CIRCUIT_CYCLE_DETECTED")
            if len(versions) > MAX_NODES:
                raise ValueError("CIRCUIT_NODE_LIMIT_EXCEEDED")
            visiting.add(version_id)
            version = versions.setdefault(version_id, load_version(db, version_id))
            if is_root:
                task = curriculum_for_version(version, curriculum, root_task)
            else:
                task = curriculum_for_version(version, curriculum, None)
            edges = edges_by_consumer.setdefault(
                version_id, edges_for_consumer(db, version_id, versions))
            order: list[int] = []
            for provider_id in sorted({edge["provider"]["version_id"] for edge in edges}):
                child = build(provider_id, depth + 1, False)
                for item in child["order"]:
                    if item not in order:
                        order.append(item)
            if version_id not in order:
                order.append(version_id)
            names: dict[str, int] = {}
            parts = []
            for item in order:
                selected = versions[item]
                name = selected["function_name"]
                previous = names.setdefault(name, item)
                if previous != item:
                    raise ValueError(f"CIRCUIT_FUNCTION_NAME_COLLISION:{name}")
                parts.append(selected["function_code"].rstrip())
            composed = "\n\n".join(parts) + "\n"
            passed, output = gates.gate_python(composed, task["tests"])
            if not passed:
                raise RuntimeError(
                    f"CIRCUIT_GATE_DENIED:{version_id}:" + output[:2400])
            node = {"version_id": version_id, "task_id": version["task_id"],
                    "function_name": version["function_name"],
                    "code_sha256": version["code_sha256"],
                    "tests_sha256": version["tests_sha256"],
                    "relay_count": len(edges), "order": order,
                    "composed_code": composed,
                    "gate": {"status": "ALLOW", "output": output[-1000:]}}
            circuit_cache[version_id] = node
            visiting.remove(version_id)
            return node

        root = build(root_id, is_root=True)
        all_edges = [edge["evidence"] for consumer_id in root["order"]
                     for edge in edges_by_consumer.get(consumer_id, [])]
        db_hash_after_read = sha256_bytes(DB_PATH.read_bytes())
        if db_hash_after_read != db_hash_before:
            raise RuntimeError("CANDIDATE_STORE_CHANGED_DURING_READ")

    receipt = {
        "schema": "viv_typed_composition_execution_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "entry_task_id": entry_task_id,
        "entry_version_id": root_id,
        "entry_function": root["function_name"],
        "execution_order": root["order"],
        "node_count": len(root["order"]),
        "relay_count": len(all_edges),
        "typed_relays": all_edges,
        "node_gates": [
            {key: value for key, value in circuit_cache[item].items()
             if key in {"version_id", "task_id", "function_name", "code_sha256",
                        "tests_sha256", "relay_count", "gate"}}
            for item in root["order"]
        ],
        "candidate_store_sha256": db_hash_before,
        "candidate_store_quick_check": "ok",
        "candidate_store_read_only": True,
        "body_preflight": {
            "authority": body.get("authority"),
            "disposition": body.get("disposition"),
            "body_image": body.get("body_image"),
        },
        "live_viv_modified": False,
        "promoted": False,
        "model_weights_changed": False,
    }
    target_path = None
    if persist_receipt:
        body_preflight()
        decision = PrivacyCore().authorize_file_write(str(RECEIPT_ROOT))
        if decision.get("allowed") is not True:
            raise PermissionError("PRIVACYCORE_DENIED_RECEIPT_DIRECTORY:" + json.dumps(decision))
        RECEIPT_ROOT.mkdir(parents=True, exist_ok=True)
        target_path = RECEIPT_ROOT / (
            f"typed_composition_execution_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_"
            f"{uuid.uuid4().hex[:8]}.json")
        decision = PrivacyCore().authorize_file_write(str(target_path))
        if decision.get("allowed") is not True:
            raise PermissionError("PRIVACYCORE_DENIED_RECEIPT:" + json.dumps(decision))
        receipt["receipt_path"] = str(target_path)
    receipt["receipt_sha256"] = canonical_hash(receipt)
    if target_path is not None:
        encoded = json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
        with target_path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(encoded)
        receipt["receipt_file_sha256"] = sha256_bytes(target_path.read_bytes())
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--entry-task", default="py24_gregorian_leap_rule")
    parser.add_argument("--persist-receipt", action="store_true")
    args = parser.parse_args()
    if not args.self_check:
        parser.error("--self-check is required")
    result = execute(args.entry_task, args.persist_receipt)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
