"""Candidate-only loop: exact retrieval -> model proposal -> deterministic gate -> admission."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import candidate_coding_runtime_v1 as model_runtime
import candidate_verified_function_store as store

LIVE = model_runtime.LIVE
CANDIDATE = Path(os.environ.get(
    "VIV_CODE_CANDIDATE",
    r"F:\LocalCoder_Archive\Viv_model_candidates\epoch_10024"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def learn_one(task: dict[str, Any], *, domain: str = "python.core",
              candidate: Path = CANDIDATE) -> dict[str, Any]:
    """Retrieve an exact admitted implementation or learn/admit a new version.

    Held-out evaluation IDs are rejected before model generation, retrieval, or
    database admission so this path cannot consume the frozen evaluation split.
    """
    if task.get("id") in store._task_ids():
        raise ValueError("HELD_OUT_TASK_ACCESS_DENIED")
    required = {"id", "lang", "spec", "tests"}
    if not required.issubset(task):
        raise ValueError("TASK_CONTRACT_FIELDS_REQUIRED")
    lang = task["lang"]
    active = store.get_active(lang=lang, domain=domain, spec=task["spec"])
    if active:
        tests_hash = hashlib.sha256(task["tests"].encode("utf-8")).hexdigest()
        if tests_hash == active["tests_sha256"]:
            gate = store.gates.gate_python if lang == "python" else store.gates.gate_rust
            passed, error = gate(active["code"], task["tests"])
            if passed:
                return {"state": "RETRIEVED", "function_key": active["function_key"],
                        "version_id": active["version_id"], "code": active["code"],
                        "code_sha256": active["code_sha256"],
                        "gate_status": "ALLOW", "proposal_count": 0}
            previous = {"raw": active["code"], "error": error}
        else:
            previous = None
    else:
        previous = None

    before = model_runtime.evaluator.request("/v1/status")
    if before.get("status") != "ACTIVE" or before.get("active_adapter") != LIVE.name:
        raise RuntimeError("UNEXPECTED_LIVE_ADAPTER:" + json.dumps(before))
    if not (candidate / "adapter_model.safetensors").is_file():
        raise FileNotFoundError(candidate / "adapter_model.safetensors")
    candidate_hash = _sha(candidate / "adapter_model.safetensors")
    task_record = {"id": task["id"], "lang": lang, "spec": task["spec"],
                   "tests": task["tests"]}
    attempts: list[dict[str, Any]] = []
    restore: dict[str, Any] | None = None
    try:
        model_runtime.evaluator.activate(candidate)
        for attempt in range(1, model_runtime.MAX_ATTEMPTS + 1):
            raw, code, _ = model_runtime.proposal(task_record, attempt, previous)
            result = store.admit_candidate(
                task_id=task["id"], lang=lang, domain=domain, spec=task["spec"],
                code=code or "# NO_COMPLETE_REQUESTED_FUNCTION",
                tests=task["tests"],
                source_kind=f"model_proposal_{candidate.name}",
                source_sha256=candidate_hash,
            )
            row = {"attempt": attempt, "decision": result["decision"],
                   "code_sha256": result["code_sha256"],
                   "gate_output": result["output"][:1000],
                   "version_id": result.get("version_id"), "raw_output": raw,
                   "code": code}
            attempts.append(row)
            print(json.dumps({"task": task["id"], "attempt": attempt,
                              "decision": result["decision"],
                              "version_id": result.get("version_id")}), flush=True)
            if result["decision"] == "ALLOW":
                state = "ADMITTED_ACTIVE" if result.get("version_id") == (
                    store.get_active(lang=lang, domain=domain,
                                     spec=task["spec"]) or {}).get("version_id") else "ADMITTED_CANDIDATE"
                return {"state": state, "function_key": result["function_key"],
                        "version_id": result["version_id"], "code": code,
                        "code_sha256": result["code_sha256"], "gate_status": "ALLOW",
                        "proposal_count": attempt, "attempts": attempts,
                        "candidate_sha256": candidate_hash}
            previous = {"raw": raw, "error": result["output"]}
    finally:
        restore = model_runtime.evaluator.activate(LIVE)
    return {"state": "NO_ADMITTED_VERSION", "function_key": store._function_identity(
            lang, domain, task["spec"])[0], "proposal_count": len(attempts),
            "attempts": attempts, "candidate_sha256": candidate_hash,
            "live_restored": restore.get("active_adapter") if restore else None}
