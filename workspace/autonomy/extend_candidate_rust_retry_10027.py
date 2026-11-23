"""Candidate-only fourth retry for Rust misses from the full epoch10027 eval.

This extends evaluation only: held-out cases/results are never admitted to the
candidate training store or used to modify any adapter, topology, or memory.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(ROOT), str(HERE)]

import candidate_coding_runtime_v1 as runtime
from aios_rebuild.privacy_core.privacy_core import PrivacyCore

BASE_RECEIPT = (HERE / "learning" / "neural_runs" /
                "candidate_runtime_helpers_v1_20261113T093620012730Z_10d662a6.json")
SUITE = HERE / "learning" / "deepseek_candidate_runs" / "frozen_code_eval_v2_1.json"
CANDIDATE = Path(r"F:\LocalCoder_Archive\Viv_model_candidates\epoch_10027")
OUT = HERE / "learning" / "neural_runs" / "candidate_rust_retry4_epoch10027.json"


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if OUT.exists():
        raise FileExistsError(f"Refusing overwrite: {OUT}")
    base_receipt = json.loads(BASE_RECEIPT.read_text(encoding="utf-8"))
    claimed = base_receipt.pop("receipt_sha256", None)
    if runtime.canonical_hash(base_receipt) != claimed:
        raise ValueError("BASE_EVALUATION_RECEIPT_HASH_INVALID")
    base_receipt["receipt_sha256"] = claimed
    candidate_hash = file_sha(CANDIDATE / "adapter_model.safetensors")
    if candidate_hash != base_receipt["candidate_sha256"]:
        raise ValueError("BASE_CANDIDATE_HASH_MISMATCH")

    suite = json.loads(SUITE.read_text(encoding="utf-8"))
    suite_hash = suite.pop("suite_sha256", None)
    if runtime.canonical_hash(suite) != suite_hash or suite_hash != base_receipt["suite_sha256"]:
        raise ValueError("FROZEN_SUITE_HASH_MISMATCH")
    task_by_id = {str(task["id"]): task for task in suite["held_out"]}
    targets = [row for row in base_receipt["results"]
               if row["lang"] == "rust" and not row["final_pass"]]
    if len(targets) != 13:
        raise ValueError(f"EXPECTED_13_FAILED_RUST_TASKS_GOT:{len(targets)}")

    before = runtime.evaluator.request("/v1/status")
    if before.get("status") != "ACTIVE" or before.get("active_adapter") != runtime.LIVE.name:
        raise RuntimeError("UNEXPECTED_LIVE_ADAPTER:" + json.dumps(before))
    outcomes = []
    restored = None
    try:
        runtime.evaluator.activate(CANDIDATE)
        for old in targets:
            task = task_by_id[old["task"]]
            last = old["attempts"][-1]
            previous = {"raw": last["raw_output"], "error": last["error"]}
            started = time.perf_counter()
            raw, code, header = runtime.proposal(
                task, 4, previous, old.get("uml_grounding"))
            gate_started = time.perf_counter()
            if not code:
                passed, error = False, "NO_COMPLETE_REQUESTED_FUNCTION"
            else:
                passed, error = runtime.gates.gate_rust(code, task["tests"])
            row = {
                "task": task["id"], "attempt": 4, "passed": bool(passed),
                "raw_output": raw, "code": code, "signature_prefix": header,
                "gate_output": error[:4000],
                "generation_and_gate_wall_seconds": time.perf_counter() - started,
                "gate_wall_seconds": time.perf_counter() - gate_started,
            }
            outcomes.append(row)
            print(json.dumps({"task": task["id"], "attempt": 4,
                              "passed": bool(passed), "gate": error[:160]},
                             ensure_ascii=False), flush=True)
    finally:
        restored = runtime.evaluator.activate(runtime.LIVE)

    base_by_task = {row["task"]: row["final_pass"] for row in base_receipt["results"]}
    attempt_by_task = {row["task"]: row["passed"] for row in outcomes}
    combined_rust_passes = sum(
        attempt_by_task.get(row["task"], bool(row["final_pass"]))
        for row in base_receipt["results"] if row["lang"] == "rust")
    after = runtime.evaluator.request("/v1/status")
    payload = {
        "schema": "viv_candidate_rust_fourth_retry_extension_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_path": str(CANDIDATE), "candidate_sha256": candidate_hash,
        "frozen_suite_path": str(SUITE), "frozen_suite_sha256": suite_hash,
        "base_full_suite_receipt": str(BASE_RECEIPT),
        "base_full_suite_receipt_sha256": claimed,
        "extension_policy": "one fourth prompted retry only for the 13 previously failed Rust tasks; original frozen task tests and deterministic gate; no training admission",
        "fourth_attempts": outcomes,
        "rust_base_final_passes": base_receipt["by_language"]["rust"]["final_pass"],
        "rust_combined_final_passes": combined_rust_passes,
        "rust_total": 50,
        "fourth_attempt_new_passes": sum(bool(x["passed"]) for x in outcomes),
        "live_before": before, "live_after": after,
        "live_restored": after.get("status") == "ACTIVE" and after.get("active_adapter") == runtime.LIVE.name,
        "promoted": False, "topology_write": False,
        "persistent_memory_write": False, "training_store_write": False,
    }
    payload["receipt_sha256"] = runtime.canonical_hash(payload)
    auth = PrivacyCore().authorize_file_write(str(OUT))
    if auth.get("allowed") is not True:
        raise PermissionError(f"PrivacyCore denied retry receipt: {auth}")
    with OUT.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"receipt": str(OUT),
                      "rust_base": payload["rust_base_final_passes"],
                      "rust_after_fourth_retry": combined_rust_passes,
                      "live_restored": payload["live_restored"],
                      "training_store_write": False}, indent=2), flush=True)
    return 0 if payload["live_restored"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
