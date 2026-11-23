"""Train one candidate from gate-accepted off-split functions and relay evidence."""
from __future__ import annotations

from datetime import datetime, timezone
import ast
import hashlib
import json
import random
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
sys.path[:0] = [str(WORKSPACE), str(HERE)]

import candidate_verified_function_store as store
import candidate_coding_runtime_v1 as runtime
import candidate_compose_verified_helper_v1 as composition
import viv_sleep_trainer as trainer
from aios_rebuild.privacy_core.privacy_core import PrivacyCore

ROOT = Path(r"F:\LocalCoder_Archive\Viv_model_candidates")
PARENT = ROOT / "epoch_10027"
DEST = ROOT / "epoch_10029"
RUNS = HERE / "learning" / "neural_runs"
DATA_OUT = RUNS / "candidate_composed_store_training_10029.json"
RUN_OUT = RUNS / "candidate_composed_store_training_run_10029.json"
SUITE = store.SUITE_PATH
CURRICULUM = HERE / "python_edge_curriculum_test_10017.py"
SEED = 20261113
LR = 5e-7
PY_REPEATS = 1
RS_REPEATS = 4
EOS = "<｜end▁of▁sentence｜>"
FENCE = chr(96) * 3
COMPOSED_TASK_ID = "offsplit_composed_gregorian_leap_v1"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canon(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def write_new(path: Path, value: dict) -> dict:
    decision = PrivacyCore().authorize_file_write(str(path))
    if decision.get("allowed") is not True:
        raise PermissionError(f"PrivacyCore denied {path}: {decision}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    return decision


def extract_top_level_function(code: str, name: str) -> str:
    tree = ast.parse(code)
    node = next((item for item in tree.body
                 if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and item.name == name), None)
    if node is None:
        raise ValueError("TOP_LEVEL_FUNCTION_MISSING:" + name)
    return "\n".join(code.splitlines()[node.lineno - 1:node.end_lineno])


def load_curriculum() -> list[dict]:
    import importlib.util
    spec = importlib.util.spec_from_file_location("candidate_edge_curriculum", CURRICULUM)
    if spec is None or spec.loader is None:
        raise RuntimeError("CURRICULUM_IMPORT_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.CURRICULUM + module.EDGE_TRANSFER_CURRICULUM


def rust_body(code: str, name: str) -> str:
    match = re.search(rf"\bpub\s+fn\s+{re.escape(name)}\s*\(", code)
    if not match:
        raise ValueError("RUST_FUNCTION_NOT_FOUND:" + name)
    opening = code.find("{", match.end())
    closing = code.rfind("}")
    if opening < 0 or closing <= opening:
        raise ValueError("RUST_FUNCTION_BODY_INVALID:" + name)
    return code[opening + 1:closing].strip()


def gate_receipt_valid(row: tuple) -> bool:
    (task_id, language, function_key, code_hash, tests_hash, gate_name,
     gate_status, gate_output, receipt_hash, created_utc) = row
    expected = {
        "task_id": task_id, "language": language, "function_key": function_key,
        "code_sha256": code_hash, "tests_sha256": tests_hash, "gate": gate_name,
        "status": gate_status, "output": gate_output, "created_utc": created_utc,
    }
    return canon(expected) == receipt_hash


def main() -> int:
    for path in (PARENT / "adapter_model.safetensors", store.DB_PATH, SUITE, CURRICULUM):
        if not path.is_file():
            raise FileNotFoundError(path)
    for path in (DEST, DATA_OUT, RUN_OUT):
        if path.exists():
            raise FileExistsError(f"Refusing overwrite: {path}")

    suite = json.loads(SUITE.read_text(encoding="utf-8"))
    suite_hash = suite.pop("suite_sha256", None)
    if canon(suite) != suite_hash:
        raise ValueError("FROZEN_SUITE_HASH_MISMATCH")
    held_ids = {str(row["id"]) for row in suite["held_out"]}
    held_names = set()
    for task in suite["held_out"]:
        match = re.search(r"\b(?:pub\s+fn|def)\s+([A-Za-z_]\w*)\s*\(",
                          task.get("spec", ""))
        if match:
            held_names.add((task["lang"], match.group(1)))

    db_hash = sha(store.DB_PATH)
    uri = store.DB_PATH.as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("CANDIDATE_STORE_QUICK_CHECK_FAILED")
        rows = db.execute("""
            SELECT f.function_key,f.language,f.domain,f.function_name,f.specification,
                   v.version_id,v.task_id,v.source_kind,v.source_sha256,v.code,
                   v.code_sha256,v.tests_sha256,v.gate_name,v.gate_status,
                   v.gate_output,v.gate_receipt_sha256,v.admitted_utc
            FROM function_versions v JOIN functions f USING(function_key)
            WHERE v.gate_status='ALLOW'
            ORDER BY v.version_id
        """).fetchall()
        relays = db.execute("""
            SELECT relay_id,provider_version_id,consumer_version_id,
                   provider_function_key,consumer_function_key,direction,
                   provider_output_pin,consumer_input_pin,callsite_json,
                   callsite_sha256,proposal_sha256,tests_sha256,receipt_sha256,
                   created_utc
            FROM function_relays ORDER BY relay_id
        """).fetchall()
        by_version = {row[5]: row for row in rows}

    # Select the newest accepted version per exact function contract. A module
    # bundle is retained in SQLite but is not an individual-function SFT sample.
    latest_by_key: dict[str, tuple] = {}
    for row in rows:
        key, language, domain, name, spec, version_id, task_id, source_kind = row[:8]
        if task_id in held_ids or (language, name) in held_names:
            raise ValueError(f"HELDOUT_OVERLAP:{task_id}:{name}")
        if source_kind.startswith("first_party_module:"):
            continue
        prior = latest_by_key.get(key)
        if prior is None or version_id > prior[5]:
            latest_by_key[key] = row

    # Keep the prior overflow-tested Rust is_prime contract; the newly seeded
    # first-party file has only the older basic curriculum tests and a duplicate
    # language/name, so it remains available in SQLite but out of this SFT pass.
    selected = []
    excluded = []
    for row in latest_by_key.values():
        if row[2] == "rust.integer" and row[3] == "is_prime":
            excluded.append({"version_id": row[5], "reason": "duplicate function name; weaker boundary test contract"})
            continue
        selected.append(row)

    # The candidate composed version replaces its earlier form for training;
    # bind the exact accepted provider and directed relay to the prompt/target.
    relays_by_consumer: dict[int, list[tuple]] = {}
    for relay in relays:
        relays_by_consumer.setdefault(relay[2], []).append(relay)
    curriculum = {row["id"]: row for row in load_curriculum()}
    samples = []
    seen_names = set()
    for row in sorted(selected, key=lambda item: (item[1], item[3])):
        (function_key, language, domain, name, specification, version_id,
         task_id, source_kind, source_hash, code, code_hash, tests_hash,
         gate_name, gate_status, gate_output, gate_receipt_hash, admitted_utc) = row
        if (language, name) in seen_names:
            raise ValueError(f"DUPLICATE_SELECTED_FUNCTION:{language}:{name}")
        seen_names.add((language, name))
        if hash_text(code) != code_hash:
            raise ValueError(f"CODE_HASH_MISMATCH:{version_id}")
        receipt_fields = (task_id, language, function_key, code_hash, tests_hash,
                         gate_name, gate_status, gate_output, gate_receipt_hash,
                         admitted_utc)
        if gate_status != "ALLOW" or not gate_receipt_valid(receipt_fields):
            raise ValueError(f"GATE_RECEIPT_INVALID:{version_id}")

        dependency = None
        target_code = code
        if version_id in relays_by_consumer:
            version_relays = relays_by_consumer[version_id]
            provider_versions = {edge[1] for edge in version_relays}
            if len(provider_versions) != 1:
                raise ValueError(f"MULTIPLE_PROVIDER_VERSIONS_UNSUPPORTED:{version_id}")
            provider_version = next(iter(provider_versions))
            provider_row = by_version.get(provider_version)
            if provider_row is None:
                raise ValueError(f"RELAY_PROVIDER_INVALID:{version_id}")
            provider_name = provider_row[3]
            provider_code = provider_row[9]
            caller_code = extract_top_level_function(code, name)
            target_code = caller_code
            relay_evidence = []
            for edge in version_relays:
                (relay_id, provider_id, consumer_id, provider_key, consumer_key,
                 direction, output_pin, input_pin, callsite_json, callsite_hash,
                 proposal_hash, relay_tests_hash, relay_receipt_hash,
                 relay_created_utc) = edge
                callsite = json.loads(callsite_json)
                if hash_text(callsite_json) != callsite_hash:
                    raise ValueError(f"RELAY_CALLSITE_HASH_MISMATCH:{relay_id}")
                expected_relay = {
                    "schema": "viv_candidate_function_relay_v1",
                    "relay_id": relay_id,
                    "provider_version_id": provider_id,
                    "consumer_version_id": consumer_id,
                    "provider_function_key": provider_key,
                    "consumer_function_key": consumer_key,
                    "direction": direction,
                    "provider_output_pin": output_pin,
                    "consumer_input_pin": input_pin,
                    "callsite": callsite,
                    "callsite_sha256": callsite_hash,
                    "proposal_sha256": proposal_hash,
                    "tests_sha256": relay_tests_hash,
                    "created_utc": relay_created_utc,
                }
                if canon(expected_relay) != relay_receipt_hash:
                    raise ValueError(f"RELAY_RECEIPT_HASH_MISMATCH:{relay_id}")
                if (direction != "PROVIDER_OUTPUT_TO_CONSUMER_INPUT"
                        or output_pin != "return:bool"
                        or input_pin != "call-result:bool"
                        or relay_tests_hash != tests_hash):
                    raise ValueError(f"RELAY_CONTRACT_MISMATCH:{relay_id}")
                relay_evidence.append({
                    "relay_id": relay_id, "direction": direction,
                    "provider_output_pin": output_pin,
                    "consumer_input_pin": input_pin,
                    "callsite": callsite, "callsite_sha256": callsite_hash,
                    "relay_receipt_sha256": relay_receipt_hash,
                })
            observed_calls = composition.function_call_sites(
                caller_code, name, provider_name)
            stored_calls = [item["callsite"] for item in relay_evidence]
            if observed_calls != stored_calls:
                raise ValueError(f"RELAY_CALLSITES_DO_NOT_MATCH_SOURCE:{version_id}")
            dependency = {
                "provider_function": provider_name,
                "provider_version_id": provider_version,
                "provider_function_key": provider_row[0],
                "provider_code_sha256": provider_row[10],
                "direction": "PROVIDER_OUTPUT_TO_CONSUMER_INPUT",
                "relay_edges": relay_evidence,
            }
            task = curriculum.get("py24_gregorian_leap_rule")
            if task is None or hash_text(task["tests"]) != tests_hash:
                raise ValueError("COMPOSED_CURRICULUM_TEST_BINDING_INVALID")
            prompt = (
                "SYSTEM: Implement one Python function. The verified helper below is "
                "available and may be called directly; do not redefine it. Return only "
                "the requested function in a fenced block.\n\n"
                "Verified helper source:\n" + provider_code + "\n\n"
                "USER: Implement: " + specification + "\n\nASSISTANT:")
            completion = f"{FENCE}python\n{caller_code}\n{FENCE}{EOS}"
        elif language == "python":
            prompt = (
                "SYSTEM: Write one self-contained, correct, standard-library Python "
                "function. Return only one fenced code block; no tests or explanation.\n\n"
                "USER: Implement: " + specification + "\n\nASSISTANT:")
            completion = f"{FENCE}python\n{code}\n{FENCE}{EOS}"
        elif language == "rust":
            parsed = runtime.rust_signature(specification)
            if not parsed:
                raise ValueError("RUST_SIGNATURE_PARSE_FAILED:" + name)
            header, description = parsed
            body = rust_body(code, name)
            grounding = runtime.uml_context_for_task({"spec": specification})
            note = "" if not grounding.get("prompt_context") else (
                "# Deterministic UML reference:\n" + "\n".join(
                    "# " + line for line in grounding["prompt_context"].splitlines()) + "\n")
            prompt = ("# Implement one self-contained, correct standard-library Rust function. "
                      "Do not depend on other top-level helpers. Handle empty and boundary inputs.\n"
                      + note + f"# Task: {description}\n{header}\n")
            completion = body + "\n}\n" + EOS
        else:
            raise ValueError("UNSUPPORTED_TRAINING_LANGUAGE:" + language)

        samples.append({
            "id": f"candidate_store_v{version_id}_{task_id}",
            "language": language, "domain": domain, "function_name": name,
            "prompt": prompt, "completion": completion,
            "function_code": target_code, "stored_composed_code": code,
            "code_sha256": code_hash, "tests_sha256": tests_hash,
            "gate_name": gate_name, "gate_status": gate_status,
            "gate_receipt_sha256": gate_receipt_hash,
            "function_key": function_key, "version_id": version_id,
            "source_kind": source_kind, "source_sha256": source_hash,
            "dependency": dependency,
        })

    counts = {lang: sum(sample["language"] == lang for sample in samples)
              for lang in ("python", "rust")}
    if counts != {"python": 9, "rust": 5}:
        raise ValueError("UNEXPECTED_SELECTED_COUNTS:" + json.dumps(counts))
    py = [sample for sample in samples if sample["language"] == "python"]
    rs = [sample for sample in samples if sample["language"] == "rust"]
    training_rows = py * PY_REPEATS + rs * RS_REPEATS
    random.Random(SEED).shuffle(training_rows)

    before = runtime.evaluator.request("/v1/status")
    if before.get("status") != "ACTIVE" or before.get("active_adapter") != runtime.LIVE.name:
        raise RuntimeError("UNEXPECTED_LIVE_ADAPTER:" + json.dumps(before))
    if sha(store.DB_PATH) != db_hash:
        raise RuntimeError("CANDIDATE_STORE_CHANGED_DURING_DATA_BUILD")
    if sha(PARENT / "adapter_model.safetensors") == "":
        raise RuntimeError("PARENT_HASH_EMPTY")

    dataset = {
        "schema": "viv_candidate_composed_store_training_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_store": str(store.DB_PATH), "candidate_store_sha256": db_hash,
        "parent_candidate": str(PARENT),
        "parent_sha256": sha(PARENT / "adapter_model.safetensors"),
        "frozen_suite_path": str(SUITE), "frozen_suite_sha256": suite_hash,
        "accepted_function_versions_read": len(rows),
        "selected_unique_examples": len(samples), "language_counts": counts,
        "repeat_policy": {"python": PY_REPEATS, "rust": RS_REPEATS},
        "training_rows": len(training_rows),
        "training_sha256": canon(training_rows),
        "heldout_id_overlap": [], "heldout_function_name_overlap": [],
        "excluded_accepted_rows": excluded,
        "bundle_exclusion": "first_party_module is retained in the store but excluded from single-function SFT format",
        "samples": samples, "live_adapter_at_build": before.get("active_adapter"),
        "promoted": False, "topology_write": False,
        "persistent_memory_write": False,
    }
    dataset["receipt_sha256"] = canon(dataset)
    authorization = write_new(DATA_OUT, dataset)

    import torch
    from transformers import set_seed
    random.seed(SEED)
    torch.manual_seed(SEED)
    set_seed(SEED)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(SEED)
    trainer.ADAPTERS_ROOT = ROOT
    trainer.RECEIPTS_FILE = ROOT / "training_receipts.jsonl"
    run = {
        "schema": "viv_candidate_composed_store_training_run_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": str(DATA_OUT), "dataset_receipt_sha256": dataset["receipt_sha256"],
        "training_sha256": dataset["training_sha256"],
        "candidate_store_sha256_before": db_hash,
        "selected_examples": len(samples), "language_counts": counts,
        "training_rows": len(training_rows), "seed": SEED, "learning_rate": LR,
        "parent": str(PARENT), "parent_sha256": dataset["parent_sha256"],
        "frozen_suite_sha256": suite_hash, "live_before": before,
        "privacy_authorization": authorization, "promoted": False,
        "topology_write": False, "persistent_memory_write": False,
    }
    quiesced = False
    try:
        response = runtime.evaluator.request("/v1/quiesce", {})
        if response.get("status") != "QUIESCED":
            raise RuntimeError("QUIESCE_FAILED:" + json.dumps(response))
        quiesced = True
        result = trainer.run_sleep_training(
            epoch=10029, steps=len(training_rows), lr=LR,
            parent_adapter=PARENT, training_samples=training_rows)
        if not result.get("ok"):
            raise RuntimeError("TRAINING_FAILED:" + json.dumps(result))
        run["training"] = result
        run["candidate_sha256"] = sha(DEST / "adapter_model.safetensors")
        run["status"] = "TRAINED_CANDIDATE"
    except Exception as exc:
        run["status"] = "TRAINING_FAILED"
        run["training_error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if quiesced:
            try:
                run["restore_response"] = runtime.evaluator.request(
                    "/v1/resume", {"adapter_dir": str(runtime.LIVE)})
            except Exception as exc:
                run["restore_error"] = f"{type(exc).__name__}: {exc}"
    try:
        after = runtime.evaluator.request("/v1/status")
        run["live_after"] = after
        run["live_restored"] = (after.get("status") == "ACTIVE"
                                 and after.get("active_adapter") == runtime.LIVE.name)
    except Exception as exc:
        run["live_restored"] = False
        run["restore_status_error"] = f"{type(exc).__name__}: {exc}"
    run["candidate_store_sha256_after"] = sha(store.DB_PATH)
    run["candidate_store_unchanged_during_training"] = (
        run["candidate_store_sha256_after"] == db_hash)
    run["receipt_sha256"] = canon(run)
    write_new(RUN_OUT, run)
    print(json.dumps({
        "dataset_receipt": str(DATA_OUT), "training_receipt": str(RUN_OUT),
        "status": run["status"], "candidate_sha256": run.get("candidate_sha256"),
        "unique_examples": len(samples), "python_rows": len(py) * PY_REPEATS,
        "rust_rows": len(rs) * RS_REPEATS, "training_rows": len(training_rows),
        "live_restored": run.get("live_restored"),
        "active_adapter": run.get("live_after", {}).get("active_adapter"),
        "store_unchanged": run["candidate_store_unchanged_during_training"],
        "promoted": False,
    }, indent=2), flush=True)
    return 0 if (run["status"] == "TRAINED_CANDIDATE" and run.get("live_restored")
                 and run["candidate_store_unchanged_during_training"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
