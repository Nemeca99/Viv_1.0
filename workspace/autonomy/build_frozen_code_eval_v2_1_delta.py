"""Build the tiny supplemental suite for corrected v2.1 task definitions."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = HERE / "learning" / "deepseek_candidate_runs"
OLD = RUNS / "frozen_code_eval_v2.json"
NEW = RUNS / "frozen_code_eval_v2_1.json"
OUT = RUNS / "frozen_code_eval_v2_1_delta.json"
REPLACED = {"py_has_adjacent_duplicate", "py_diagonal_difference",
            "rs_diagonal_difference", "rs_matrix_trace"}

def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()

def load_verified(path: Path) -> tuple[dict, str]:
    value = json.loads(path.read_text(encoding="utf-8"))
    expected = value.pop("suite_sha256")
    if digest(value) != expected:
        raise ValueError(f"suite hash mismatch: {path}")
    return value, expected

def main() -> int:
    old, old_hash = load_verified(OLD)
    new, new_hash = load_verified(NEW)
    before = {task["id"]: task for task in old["held_out"]}
    after = {task["id"]: task for task in new["held_out"]}
    changed = {task_id for task_id in before.keys() | after.keys()
               if before.get(task_id) != after.get(task_id)}
    if changed != {"py_adjacent_duplicate", "py_has_adjacent_duplicate",
                   "py_diagonal_difference", "rs_diagonal_difference", "rs_matrix_trace"}:
        raise ValueError(f"unexpected suite delta: {sorted(changed)}")
    tasks = [after[task_id] for task_id in sorted(REPLACED)]
    payload = {"schema": "viv_frozen_candidate_code_eval_v2_1_delta",
               "parent_suite_sha256": new_hash,
               "superseded_suite_sha256": old_hash,
               "held_out": tasks,
               "by_language": {"python": 2, "rust": 2}}
    payload["suite_sha256"] = digest(payload)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"delta_path": str(OUT), "suite_sha256": payload["suite_sha256"],
                      "parent_suite_sha256": new_hash, "replaced_ids": sorted(REPLACED),
                      "task_count": len(tasks)}, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
