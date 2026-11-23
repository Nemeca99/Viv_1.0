"""Compose the baseline sweep with corrected-task replacements, preserving both receipts."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = HERE / "learning" / "deepseek_candidate_runs"
BASE_RECEIPT = RUNS / "candidate_runtime_v1_20261112T002438017320Z_821ffe65.json"
DELTA_RECEIPT = RUNS / "candidate_runtime_v1_20261112T003006104453Z_57895f74.json"
BASE_SUITE = RUNS / "frozen_code_eval_v2.json"
FINAL_SUITE = RUNS / "frozen_code_eval_v2_1.json"
DELTA_SUITE = RUNS / "frozen_code_eval_v2_1_delta.json"
OUT = RUNS / "candidate_coding_eval_v2_1_composite.json"
REPLACED = {"py_adjacent_duplicate", "py_diagonal_difference",
            "rs_diagonal_difference", "rs_matrix_trace"}

def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()

def read_receipt(path: Path) -> tuple[dict, str]:
    value = json.loads(path.read_text(encoding="utf-8"))
    expected = value.pop("receipt_sha256")
    if digest(value) != expected:
        raise ValueError(f"receipt hash mismatch: {path}")
    return value, expected

def read_suite(path: Path) -> tuple[dict, str]:
    value = json.loads(path.read_text(encoding="utf-8"))
    expected = value.pop("suite_sha256")
    if digest(value) != expected:
        raise ValueError(f"suite hash mismatch: {path}")
    return value, expected

def main() -> int:
    base, base_receipt_hash = read_receipt(BASE_RECEIPT)
    delta, delta_receipt_hash = read_receipt(DELTA_RECEIPT)
    old, old_hash = read_suite(BASE_SUITE)
    final, final_hash = read_suite(FINAL_SUITE)
    delta_suite, delta_hash = read_suite(DELTA_SUITE)
    if base["suite_sha256"] != old_hash or delta["suite_sha256"] != delta_hash:
        raise ValueError("source receipt/suite mismatch")
    if delta_suite.get("parent_suite_sha256") != final_hash:
        raise ValueError("corrected suite lineage mismatch")
    if base["candidate_sha256"] != delta["candidate_sha256"]:
        raise ValueError("candidate weights differ across runs")
    if base["live_restored"].get("active_adapter") != "epoch_10001" or delta["live_restored"].get("active_adapter") != "epoch_10001":
        raise ValueError("live tutor restoration missing")
    old_tasks = {task["id"]: task for task in old["held_out"]}
    final_tasks = {task["id"]: task for task in final["held_out"]}
    delta_ids = {task["id"] for task in delta_suite["held_out"]}
    if delta_ids != {"py_has_adjacent_duplicate", "py_diagonal_difference",
                     "rs_diagonal_difference", "rs_matrix_trace"}:
        raise ValueError("unexpected corrected-task set")
    base_rows = {row["task"]: row for row in base["results"]}
    delta_rows = {row["task"]: row for row in delta["results"]}
    if set(base_rows) != set(old_tasks) or set(delta_rows) != delta_ids:
        raise ValueError("task receipts do not match frozen suite")
    if {task_id for task_id in old_tasks.keys() | final_tasks.keys()
        if old_tasks.get(task_id) != final_tasks.get(task_id)} != (
            REPLACED | {"py_has_adjacent_duplicate"}):
        raise ValueError("corrected suite changed unreviewed tasks")
    combined = [row for task_id, row in base_rows.items() if task_id not in REPLACED]
    combined.extend(delta_rows.values())
    if len({row["task"] for row in combined}) != 100:
        raise ValueError("composed task count is not 100 unique cases")
    by_language = {}
    for lang in ("python", "rust"):
        rows = [row for row in combined if row["lang"] == lang]
        by_language[lang] = {"first_pass": sum(row["first_pass"] for row in rows),
                             "final_pass": sum(row["final_pass"] for row in rows),
                             "total": len(rows)}
    payload = {"schema": "viv_candidate_coding_eval_v2_1_composite_v1",
               "created_utc": datetime.now(timezone.utc).isoformat(),
               "suite_path": str(FINAL_SUITE), "suite_sha256": final_hash,
               "candidate_path": base["candidate_path"],
               "candidate_sha256": base["candidate_sha256"],
               "by_language": by_language, "results": combined,
               "source_receipts": [
                   {"path": str(BASE_RECEIPT), "receipt_sha256": base_receipt_hash,
                    "suite_sha256": old_hash, "prompt_contract": "baseline v1"},
                   {"path": str(DELTA_RECEIPT), "receipt_sha256": delta_receipt_hash,
                    "suite_sha256": delta_hash,
                    "prompt_contract": delta.get("prompt_contract")}],
               "corrected_tasks": sorted(delta_ids),
               "superseded_invalid_task": "py_adjacent_duplicate",
               "promoted": False,
               "measurement_note": "96 unchanged task outcomes plus four corrected-task replacements; corrected replacements used the tightened self-contained-function prompt and are identified separately."}
    payload["receipt_sha256"] = digest(payload)
    with OUT.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"receipt": str(OUT), "receipt_sha256": payload["receipt_sha256"],
                      "suite_sha256": final_hash, "by_language": by_language,
                      "candidate_sha256": payload["candidate_sha256"], "promoted": False}, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
