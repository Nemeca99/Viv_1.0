"""Read-only audit for the expanded candidate coding suite."""
from __future__ import annotations
import ast
import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = HERE / "learning" / "deepseek_candidate_runs"
SUITE = RUNS / "frozen_code_eval_v2_1.json"
TRAIN = RUNS / "clean_function_training_v2.json"

def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()

def function_name(spec: str) -> str:
    match = re.search(r"(?:def|pub\s+fn)\s+([A-Za-z_]\w*)\s*\(", spec)
    if not match:
        raise ValueError("function signature absent")
    return match.group(1)

def main() -> int:
    suite = json.loads(SUITE.read_text(encoding="utf-8"))
    suite_hash = suite.pop("suite_sha256")
    if digest(suite) != suite_hash:
        raise ValueError("suite hash mismatch")
    train = json.loads(TRAIN.read_text(encoding="utf-8"))
    train_hash = train.pop("receipt_sha256")
    if digest(train) != train_hash:
        raise ValueError("training receipt hash mismatch")
    if digest(train["samples"]) != train["training_sha256"]:
        raise ValueError("training sample hash mismatch")
    train_ids = {row["id"] for row in train["samples"]}
    train_names = {"python": set(), "rust": set()}
    for row in train["samples"]:
        lang = "rust" if row["category"].startswith("rust_") else "python"
        train_names[lang].add(function_name(row["prompt"]))
    seen_ids = set()
    seen_names = {"python": set(), "rust": set()}
    counts = {"python": 0, "rust": 0}
    for task in suite["held_out"]:
        lang = task["lang"]
        name = function_name(task["spec"])
        if task["id"] in seen_ids or task["id"] in train_ids:
            raise ValueError(f"task ID overlap/duplicate: {task['id']}")
        if name in seen_names[lang] or name in train_names[lang]:
            raise ValueError(f"function overlap/duplicate: {lang}:{name}")
        if not task.get("tests"):
            raise ValueError(f"missing deterministic cases: {task['id']}")
        if lang == "python":
            ast.parse(task["tests"], filename=task["id"] + ".tests.py")
        elif lang != "rust":
            raise ValueError(f"unknown language: {lang}")
        seen_ids.add(task["id"])
        seen_names[lang].add(name)
        counts[lang] += 1
    if counts != {"python": 50, "rust": 50}:
        raise ValueError(f"wrong split size: {counts}")
    print(json.dumps({"suite_sha256": suite_hash, "training_receipt_sha256": train_hash,
                      "counts": counts, "training_id_overlap": sorted(seen_ids & train_ids),
                      "python_test_syntax": "PASS", "receipt_hashes": "PASS"}, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
