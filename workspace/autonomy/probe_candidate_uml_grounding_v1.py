"""Candidate-only canary: does UML-grounded context help Python proposals?

This development probe is outside the frozen evaluation split and is never
admitted to training storage. Its output is gated by the existing Docker body.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
sys.path[:0] = [str(WORKSPACE), str(HERE)]

import candidate_coding_runtime_v1 as runtime
from candidate_uml_grounding_v1 import UML_ENGINE_PATH
from aios_rebuild.privacy_core.privacy_core import PrivacyCore

CANDIDATE = Path(r"F:\LocalCoder_Archive\Viv_model_candidates\epoch_10026")
LIVE = runtime.LIVE
OUT = HERE / "learning" / "neural_runs" / "candidate_uml_grounding_canary_10026_v2.json"
TASK = {
    "id": "dev_uml_exact_multiple_zero_guard_v1",
    "lang": "python",
    "spec": (
        "def exact_multiple(numerator: int, denominator: int) -> bool: "
        "return False when denominator is zero; otherwise return whether numerator "
        "is an exact multiple of denominator"
    ),
    "tests": (
        "assert exact_multiple(12, 3) is True\n"
        "assert exact_multiple(13, 3) is False\n"
        "assert exact_multiple(0, 7) is True\n"
        "assert exact_multiple(0, 0) is False, exact_multiple(0, 0)\n"
        "assert exact_multiple(4, 0) is False, exact_multiple(4, 0)"
    ),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def main() -> int:
    if OUT.exists():
        raise FileExistsError(OUT)
    if not (CANDIDATE / "adapter_model.safetensors").is_file():
        raise FileNotFoundError(CANDIDATE / "adapter_model.safetensors")
    before = runtime.evaluator.request("/v1/status")
    if before.get("status") != "ACTIVE" or before.get("active_adapter") != LIVE.name:
        raise RuntimeError("UNEXPECTED_LIVE_ADAPTER:" + json.dumps(before))
    candidate_hash = sha256(CANDIDATE / "adapter_model.safetensors")
    result = None
    restored = None
    try:
        runtime.evaluator.activate(CANDIDATE)
        result = runtime.run_task(TASK, CANDIDATE)
    finally:
        restored = runtime.evaluator.activate(LIVE)

    receipt = {
        "schema": "viv_candidate_uml_grounding_canary_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_path": str(CANDIDATE), "candidate_sha256": candidate_hash,
        "task": TASK, "result": result,
        "uml_engine_path": str(UML_ENGINE_PATH), "uml_engine_sha256": sha256(UML_ENGINE_PATH),
        "live_before": before, "live_restored": restored,
        "training_write": False, "function_store_write": False,
        "topology_write": False, "persistent_memory_write": False,
        "promoted": False,
    }
    receipt["receipt_sha256"] = canonical_hash(receipt)
    authorization = PrivacyCore().authorize_file_write(str(OUT))
    if authorization.get("allowed") is not True:
        raise PermissionError(f"PrivacyCore denied canary receipt: {authorization}")
    with OUT.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    passed = bool(result and result.get("final_pass") is True
                  and restored.get("active_adapter") == LIVE.name)
    print(json.dumps({
        "receipt": str(OUT), "candidate_sha256": candidate_hash,
        "first_pass": None if result is None else result.get("first_pass"),
        "final_pass": None if result is None else result.get("final_pass"),
        "uml_engine_sha256": receipt["uml_engine_sha256"],
        "active_adapter": restored.get("active_adapter"),
        "training_write": False, "promoted": False,
    }, ensure_ascii=False, indent=2), flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
