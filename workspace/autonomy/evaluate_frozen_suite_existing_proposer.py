"""Evaluate the existing code proposer and its gate-feedback loop without writes."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
for item in (WORKSPACE, HERE):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

import evaluate_frozen_candidate_code_v1 as evaluator
import viv_code_learning_loop as gates

LIVE = Path(r"E:\Viv_Sandbox\playground\adapters\epoch_10001")
CANDIDATE = Path(os.environ.get("VIV_CODE_CANDIDATE", str(LIVE)))
SUITE = HERE / "learning" / "deepseek_candidate_runs" / "frozen_code_eval_v1.json"
OUT_DIR = HERE / "learning" / "deepseek_candidate_runs"
MAX_ATTEMPTS = 3


def main() -> int:
    suite = json.loads(SUITE.read_text(encoding="utf-8"))
    digest = suite.pop("suite_sha256")
    canonical = json.dumps(suite, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode("utf-8")
    if hashlib.sha256(canonical).hexdigest() != digest:
        raise ValueError("frozen suite hash mismatch")
    initial = evaluator.request("/v1/status")
    if initial.get("status") != "ACTIVE" or initial.get("active_adapter") != LIVE.name:
        raise RuntimeError(f"unexpected live state: {initial}")
    results, restored = [], None
    try:
        evaluator.activate(CANDIDATE)
        for task_index, task in enumerate(suite["held_out"], 1):
            attempts = []
            for attempt in range(1, MAX_ATTEMPTS + 1):
                raw = gates.propose(task, prior=attempts, examples=[])
                code = evaluator.extract_requested_function(raw, task["lang"], task["spec"])
                if not code:
                    passed, error = False, "NO_COMPLETE_REQUESTED_FUNCTION"
                else:
                    gate = gates.gate_python if task["lang"] == "python" else gates.gate_rust
                    passed, error = gate(code, task["tests"])
                row = {"attempt": attempt, "passed": bool(passed), "error": error[:4000],
                       "code": code, "raw_output": raw}
                attempts.append(row)
                print(json.dumps({"task_index": task_index, "task_total": len(suite["held_out"]),
                                  "task": task["id"], "attempt": attempt,
                                  "passed": bool(passed), "error": error[:180]}, ensure_ascii=False), flush=True)
                if passed:
                    break
            results.append({"task": task["id"], "lang": task["lang"],
                            "first_pass": attempts[0]["passed"],
                            "final_pass": attempts[-1]["passed"], "attempts": attempts})
    finally:
        restored = evaluator.activate(LIVE)

    summary = {}
    for lang in ("python", "rust"):
        rows = [row for row in results if row["lang"] == lang]
        summary[lang] = {"first_pass": sum(row["first_pass"] for row in rows),
                         "final_pass": sum(row["final_pass"] for row in rows),
                         "total": len(rows)}
    output = {
        "schema": "viv_existing_proposer_frozen_eval_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "suite_path": str(SUITE), "suite_sha256": digest,
        "candidate": str(CANDIDATE),
        "candidate_sha256": hashlib.sha256((CANDIDATE / "adapter_model.safetensors").read_bytes()).hexdigest(),
        "max_attempts": MAX_ATTEMPTS, "by_language": summary, "results": results,
        "live_adapter_before": initial, "live_adapter_restored": restored, "promoted": False,
    }
    output["receipt_sha256"] = hashlib.sha256(
        json.dumps(output, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"existing_proposer_eval_v1_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"receipt": str(path), "by_language": summary,
                      "active_adapter_restored": restored.get("active_adapter"), "promoted": False}, indent=2), flush=True)
    return 0 if len(results) == len(suite["held_out"]) and restored.get("active_adapter") == LIVE.name else 1


if __name__ == "__main__":
    raise SystemExit(main())
