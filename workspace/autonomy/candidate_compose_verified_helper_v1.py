"""Ask the isolated coding candidate to reuse a gate-admitted helper.

The candidate proposes the caller. This module retrieves both real candidate
versions, verifies their existing tests, compiles the proposal with its helper,
and records a directed helper-output-to-caller relay only after ALLOW.
"""
from __future__ import annotations

from datetime import datetime, timezone
import ast
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import uuid

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
sys.path[:0] = [str(WORKSPACE), str(HERE)]

import candidate_verified_function_store as store
import candidate_coding_runtime_v1 as runtime
from aios_rebuild.privacy_core.privacy_core import PrivacyCore

CURRICULUM_PATH = HERE / "python_edge_curriculum_test_10017.py"
SUITE_PATH = store.SUITE_PATH
LIVE = runtime.LIVE
CANDIDATE = Path(os.environ.get(
    "VIV_CODE_CANDIDATE",
    r"F:\LocalCoder_Archive\Viv_model_candidates\epoch_10027"))
DOMAIN = "python.core"
HELPER_ID = "py24_divisible_zero_safe"
CALLER_ID = "py24_gregorian_leap_rule"
HELPER_SPEC = (
    "def divisible_or_false(value: int, divisor: int) -> bool: "
    "return whether value is divisible by divisor; a zero divisor returns false")
CALLER_SPEC = (
    "def gregorian_leap(year: int) -> bool: apply the Gregorian rule that "
    "years divisible by four are leap years except centuries not divisible "
    "by four hundred")
RECEIPTS = HERE / "learning" / "neural_runs" / "composition_receipts"
MAX_TOKENS = 384


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def write_authorized_new(path: Path, value: dict) -> str:
    decision = PrivacyCore().authorize_file_write(str(path))
    if decision.get("allowed") is not True:
        raise PermissionError(f"PrivacyCore denied receipt path: {decision}")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(encoded)
    return sha256_bytes(path.read_bytes())


def curriculum_task(task_id: str) -> dict:
    # Importing this data-only module executes no training or mutation path.
    import importlib.util
    spec = importlib.util.spec_from_file_location("candidate_edge_curriculum", CURRICULUM_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("CURRICULUM_IMPORT_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows = module.CURRICULUM + module.EDGE_TRANSFER_CURRICULUM
    matches = [row for row in rows if row["id"] == task_id]
    if len(matches) != 1:
        raise ValueError(f"CURRICULUM_TASK_NOT_UNIQUE:{task_id}")
    return matches[0]


def active_for(spec: str) -> dict:
    row = store.get_active(lang="python", domain=DOMAIN, spec=spec)
    if row is None:
        raise RuntimeError("VERIFIED_FUNCTION_MISSING:" + spec)
    return row


def function_call_sites(code: str, caller_name: str,
                        dependency_name: str) -> list[dict]:
    tree = ast.parse(code)
    fn = next((node for node in tree.body
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
               and node.name == caller_name), None)
    if fn is None:
        return []
    sites = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == dependency_name:
            sites.append({
                "dependency_name": dependency_name,
                "line": node.lineno,
                "arguments": [ast.unparse(arg) for arg in node.args],
                "keywords": {kw.arg: ast.unparse(kw.value) for kw in node.keywords},
            })
    return sorted(sites, key=lambda row: (row["line"], row["arguments"]))


def record_relay(*, provider: dict, consumer: dict, site: dict,
                 proposal_sha256: str, tests_sha256: str) -> tuple[int, str]:
    decision = PrivacyCore().authorize_file_write(str(store.DB_PATH))
    if decision.get("allowed") is not True:
        raise PermissionError(f"PrivacyCore denied candidate relay write: {decision}")
    with store._connection() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS function_relays (
                relay_id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider_version_id INTEGER NOT NULL REFERENCES function_versions(version_id),
                consumer_version_id INTEGER NOT NULL REFERENCES function_versions(version_id),
                provider_function_key TEXT NOT NULL REFERENCES functions(function_key),
                consumer_function_key TEXT NOT NULL REFERENCES functions(function_key),
                direction TEXT NOT NULL CHECK(direction='PROVIDER_OUTPUT_TO_CONSUMER_INPUT'),
                provider_output_pin TEXT NOT NULL,
                consumer_input_pin TEXT NOT NULL,
                callsite_json TEXT NOT NULL,
                callsite_sha256 TEXT NOT NULL,
                proposal_sha256 TEXT NOT NULL,
                tests_sha256 TEXT NOT NULL,
                receipt_sha256 TEXT NOT NULL,
                created_utc TEXT NOT NULL,
                UNIQUE(provider_version_id,consumer_version_id,callsite_sha256)
            )
        """)
        now = datetime.now(timezone.utc).isoformat()
        callsite_json = json.dumps(site, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":"))
        callsite_hash = sha256_bytes(callsite_json.encode("utf-8"))
        # Reserve the append-only row first; then bind the final receipt to its ID.
        db.execute("""
            INSERT OR IGNORE INTO function_relays(
                provider_version_id,consumer_version_id,provider_function_key,
                consumer_function_key,direction,provider_output_pin,
                consumer_input_pin,callsite_json,callsite_sha256,proposal_sha256,
                tests_sha256,receipt_sha256,created_utc
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (provider["version_id"], consumer["version_id"],
              provider["function_key"], consumer["function_key"],
              "PROVIDER_OUTPUT_TO_CONSUMER_INPUT", "return:bool",
              "call-result:bool", callsite_json, callsite_hash,
              proposal_sha256, tests_sha256, "PENDING", now))
        row = db.execute("""
            SELECT relay_id,receipt_sha256,created_utc FROM function_relays
            WHERE provider_version_id=? AND consumer_version_id=?
              AND callsite_sha256=?
        """, (provider["version_id"], consumer["version_id"],
              callsite_hash)).fetchone()
        if row is None:
            raise RuntimeError("RELAY_ROW_NOT_FOUND_AFTER_INSERT")
        relay_id = int(row[0])
        evidence = {
            "schema": "viv_candidate_function_relay_v1",
            "relay_id": relay_id,
            "provider_version_id": provider["version_id"],
            "consumer_version_id": consumer["version_id"],
            "provider_function_key": provider["function_key"],
            "consumer_function_key": consumer["function_key"],
            "direction": "PROVIDER_OUTPUT_TO_CONSUMER_INPUT",
            "provider_output_pin": "return:bool",
            "consumer_input_pin": "call-result:bool",
            "callsite": site,
            "callsite_sha256": callsite_hash,
            "proposal_sha256": proposal_sha256,
            "tests_sha256": tests_sha256,
            "created_utc": row[2],
        }
        receipt_hash = canonical_hash(evidence)
        if row[1] == "PENDING":
            db.execute("UPDATE function_relays SET receipt_sha256=? WHERE relay_id=?",
                       (receipt_hash, relay_id))
        elif row[1] != receipt_hash:
            raise RuntimeError("RELAY_RECEIPT_HASH_CONFLICT")
    return relay_id, receipt_hash


def main() -> int:
    helper_task = curriculum_task(HELPER_ID)
    caller_task = curriculum_task(CALLER_ID)
    helper = active_for(helper_task["spec"])
    caller = active_for(caller_task["spec"])
    for label, row, task in (("helper", helper, helper_task),
                             ("caller", caller, caller_task)):
        if hashlib.sha256(task["tests"].encode("utf-8")).hexdigest() \
                != row["tests_sha256"]:
            raise RuntimeError(f"CURRICULUM_TEST_HASH_MISMATCH:{label}")
        passed, error = runtime.gates.gate_python(row["code"], task["tests"])
        if not passed:
            raise RuntimeError(f"ADMITTED_BASELINE_FAILED:{label}:{error}")

    suite = json.loads(SUITE_PATH.read_text(encoding="utf-8"))
    expected_suite_hash = suite.pop("suite_sha256", None)
    if expected_suite_hash != store.canonical_hash(suite):
        raise RuntimeError("FROZEN_SUITE_HASH_MISMATCH")
    heldout_names = set()
    for task in suite.get("held_out", []):
        found = runtime.re.search(r"\b(?:pub\s+fn|def)\s+([A-Za-z_]\w*)\s*\(",
                                  task.get("spec", ""))
        if found:
            heldout_names.add((task.get("lang"), found.group(1)))
    if ("python", "gregorian_leap") in heldout_names \
            or caller_task["id"] in store._task_ids():
        raise RuntimeError("COMPOSITION_TASK_INTERSECTS_FROZEN_HELDOUT")

    helper_name = "divisible_or_false"
    prompt = (
        "SYSTEM: Implement the requested Python function. You may use the supplied "
        "verified helper as-is; do not copy or redefine it. Return only one fenced "
        "Python function, with no tests or explanation.\n\n"
        "Verified helper source (already admitted and tested):\n"
        f"{helper['code']}\n\n"
        f"USER: Implement: {caller_task['spec']}\n\nASSISTANT:")

    before = runtime.evaluator.request("/v1/status")
    if before.get("status") != "ACTIVE" or before.get("active_adapter") != LIVE.name:
        raise RuntimeError("UNEXPECTED_LIVE_ADAPTER:" + json.dumps(before))
    if not (CANDIDATE / "adapter_model.safetensors").is_file():
        raise FileNotFoundError(CANDIDATE / "adapter_model.safetensors")
    candidate_hash = runtime.sha256(CANDIDATE / "adapter_model.safetensors")
    attempt = {"state": "PROPOSED", "candidate": str(CANDIDATE),
               "candidate_sha256": candidate_hash, "parent_function_version": caller["version_id"],
               "provider_function_version": helper["version_id"],
               "prompt_sha256": sha256_bytes(prompt.encode("utf-8"))}
    restore = None
    try:
        runtime.evaluator.activate(CANDIDATE)
        raw = runtime.request_completion(prompt, temperature=0.0)
        code = runtime.evaluator.extract_requested_function(
            raw, "python", caller_task["spec"])
        if not code:
            raise RuntimeError("MODEL_DID_NOT_RETURN_REQUESTED_FUNCTION")
        sites = function_call_sites(code, "gregorian_leap", helper_name)
        if not sites:
            raise RuntimeError("CANDIDATE_DID_NOT_ROUTE_THROUGH_VERIFIED_HELPER")

        composed_code = helper["code"].rstrip() + "\n\n" + code.rstrip() + "\n"
        passed, error = runtime.gates.gate_python(composed_code, caller_task["tests"])
        attempt.update({"raw_output": raw, "proposal": code,
                        "proposal_sha256": sha256_bytes(code.encode("utf-8")),
                        "call_sites": sites, "composed_gate": "ALLOW" if passed else "DENY",
                        "composed_gate_output": error})
        if not passed:
            attempt["state"] = "DENIED"
        else:
            tests_hash = sha256_bytes(caller_task["tests"].encode("utf-8"))
            admitted = store.admit_candidate(
                task_id="offsplit_composed_gregorian_leap_v1",
                lang="python", domain=DOMAIN, spec=caller_task["spec"],
                code=composed_code, tests=caller_task["tests"],
                source_kind=f"model_composition_candidate_{CANDIDATE.name}",
                source_sha256=candidate_hash,
                parent_version_id=caller["version_id"],
            )
            if admitted["decision"] != "ALLOW":
                attempt.update({"state": "DENIED", "admission": admitted})
            else:
                consumer = {"version_id": admitted["version_id"],
                            "function_key": admitted["function_key"]}
                relays = [record_relay(
                    provider=helper, consumer=consumer, site=site,
                    proposal_sha256=attempt["proposal_sha256"], tests_sha256=tests_hash)
                    for site in sites]
                attempt.update({"state": "COMPOSED_AND_ADMITTED_CANDIDATE",
                                "admission": admitted,
                                "relay_ids": [item[0] for item in relays],
                                "relay_receipt_sha256s": [item[1] for item in relays],
                                "relay_direction": "PROVIDER_OUTPUT_TO_CONSUMER_INPUT",
                                "active_function_version_unchanged": True})
    except Exception as exc:
        attempt.update({"state": "PROPOSAL_OR_COMPOSITION_FAILED",
                        "error": f"{type(exc).__name__}: {exc}"})
    finally:
        restore = runtime.evaluator.activate(LIVE)

    return finish(attempt, before, restore, candidate_hash)


def finish(attempt: dict, before: dict, restore: dict | None,
           candidate_hash: str) -> int:
    attempt.update({"schema": "viv_candidate_composition_attempt_v1",
                   "created_utc": datetime.now(timezone.utc).isoformat(),
                   "live_before": before, "live_restored": bool(restore and
                       restore.get("active_adapter") == LIVE.name),
                   "candidate_sha256": candidate_hash, "promoted": False,
                   "topology_write": False, "persistent_memory_write": False})
    attempt["receipt_sha256"] = canonical_hash(attempt)
    path = RECEIPTS / f"compose_gregorian_leap_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}_{uuid.uuid4().hex[:8]}.json"
    file_hash = write_authorized_new(path, attempt)
    print(json.dumps({"state": attempt["state"], "receipt": str(path),
                      "receipt_file_sha256": file_hash,
                      "live_restored": attempt["live_restored"],
                      "promoted": False}, ensure_ascii=False, indent=2), flush=True)
    return 0 if attempt["state"] == "COMPOSED_AND_ADMITTED_CANDIDATE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
