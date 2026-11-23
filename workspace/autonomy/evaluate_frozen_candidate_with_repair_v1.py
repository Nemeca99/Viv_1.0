"""Run generate -> deterministic gate -> bounded repair on a frozen suite."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import urllib.request

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
for item in (WORKSPACE, HERE):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

import evaluate_frozen_candidate_code_v1 as evaluator
import viv_code_learning_loop as gates

API = "http://127.0.0.1:1234"
LIVE = Path(r"E:\Viv_Sandbox\playground\adapters\epoch_10001")
CANDIDATE = Path(os.environ.get("VIV_CODE_CANDIDATE", r"F:\LocalCoder_Archive\Viv_model_candidates\epoch_10005"))
SUITE = HERE / "learning" / "deepseek_candidate_runs" / "frozen_code_eval_v1.json"
OUT_DIR = HERE / "learning" / "deepseek_candidate_runs"
MAX_ATTEMPTS = 3


def request(path: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(API + path, data=data,
                                 headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=180) as response:
        return json.load(response)


def generate(task: dict, prior: list[dict]) -> tuple[str, str]:
    system = (f"Write one correct, standard-library {task['lang']} implementation. "
              "Return only the requested function in a fenced code block. Do not include tests or a main function.")
    user = f"Implement: {task['spec']}"
    if prior:
        last = prior[-1]
        user += (
            "\n\nThe deterministic execution gate rejected the previous attempt. Repair it."
            f"\nPrevious function:\n{last['code'] or last['raw_output'][:1000]}"
            f"\nGate output:\n{last['error'][:2500]}"
            f"\nRequired tests:\n{task['tests']}"
        )
    prompt = f"SYSTEM: {system}\n\nUSER: {user}\n\nASSISTANT:"
    response = request("/v1/completions", {
        "model": "deepseek-coder-6.7b-base", "prompt": prompt,
        "max_tokens": 320, "temperature": 0.0,
        "stop": ["\nUSER:", "\nSYSTEM:", "\n// Test code", "\n# Test code", "\nfn main()"],
    })
    raw = response["choices"][0]["text"]
    code = evaluator.extract_requested_function(raw, task["lang"], task["spec"])
    return raw, code


def main() -> int:
    suite = json.loads(SUITE.read_text(encoding="utf-8"))
    suite_hash = suite.pop("suite_sha256")
    canonical = json.dumps(suite, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode("utf-8")
    if hashlib.sha256(canonical).hexdigest() != suite_hash:
        raise ValueError("frozen suite hash mismatch")
    status = request("/v1/status")
    if status.get("status") != "ACTIVE" or status.get("active_adapter") != LIVE.name:
        raise RuntimeError(f"unexpected live tutor state: {status}")
    rows = []
    restore = None
    try:
        evaluator.activate(CANDIDATE)
        for index, task in enumerate(suite["held_out"], 1):
            attempts = []
            for attempt in range(1, MAX_ATTEMPTS + 1):
                raw, code = generate(task, attempts)
                if not code:
                    passed, error = False, "NO_COMPLETE_REQUESTED_FUNCTION"
                else:
                    gate = gates.gate_python if task["lang"] == "python" else gates.gate_rust
                    passed, error = gate(code, task["tests"])
                row = {"attempt": attempt, "passed": bool(passed), "error": error[:4000],
                       "code": code, "raw_output": raw}
                attempts.append(row)
                print(json.dumps({"task_index": index, "task_total": len(suite["held_out"]),
                                  "task": task["id"], "attempt": attempt,
                                  "passed": bool(passed), "error": error[:180]}, ensure_ascii=False), flush=True)
                if passed:
                    break
            rows.append({"task": task["id"], "lang": task["lang"],
                         "first_pass": attempts[0]["passed"],
                         "final_pass": attempts[-1]["passed"], "attempts": attempts})
    finally:
        restore = evaluator.activate(LIVE)

    by_language = {}
    for lang in ("python", "rust"):
        selected = [row for row in rows if row["lang"] == lang]
        by_language[lang] = {
            "first_pass": sum(row["first_pass"] for row in selected),
            "final_pass": sum(row["final_pass"] for row in selected),
            "total": len(selected),
        }
    output = {
        "schema": "viv_frozen_candidate_repair_eval_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "suite_path": str(SUITE), "suite_sha256": suite_hash,
        "candidate": str(CANDIDATE),
        "candidate_sha256": hashlib.sha256((CANDIDATE / "adapter_model.safetensors").read_bytes()).hexdigest(),
        "max_attempts": MAX_ATTEMPTS, "by_language": by_language,
        "results": rows, "live_adapter_before": status, "live_adapter_restored": restore,
        "promoted": False,
    }
    output["receipt_sha256"] = hashlib.sha256(
        json.dumps(output, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"frozen_repair_eval_v1_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"receipt": str(path), "by_language": by_language,
                      "active_adapter_restored": restore.get("active_adapter"),
                      "promoted": False}, indent=2), flush=True)
    return 0 if restore.get("active_adapter") == LIVE.name and len(rows) == len(suite["held_out"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
