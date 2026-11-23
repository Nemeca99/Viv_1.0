"""Independent generated-graph check for the model-written task scheduler."""
from pathlib import Path
import hashlib
import json
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from viv_autonomy import STATE, Store
from viv_project_builder import head, invoke_project

rng = random.Random(20261004)
store = Store()
version = head(store, "viv_task_scheduler")
if not version:
    raise SystemExit("No tested project head")

receipt = {
    "schema": "viv_task_scheduler_independent_graph_eval_v1",
    "project_version": version["version"],
    "model_authored_examples_used": False,
    "seed": 20261004,
    "cases": [],
    "started": time.time(),
}

for case_number in range(40):
    count = rng.randint(0, 16)
    ids = [f"g{case_number:02d}_t{index:02d}" for index in range(count)]
    statuses = ["queued", "retry", "tested", "running", "failed", "cancelled", "unknown"]
    rows = []
    for task_id in ids:
        rows.append({
            "id": task_id,
            "status": rng.choice(statuses),
            "priority": rng.randint(-10, 15),
            "dependencies": rng.sample(ids + ["missing_dependency"], rng.randint(0, min(4, count + 1))),
            "extra": "input must remain data; no side effects",
        })

    by_id = {row["id"]: row for row in rows}
    expected = sorted(
        (
            row for row in rows
            if row["status"] in {"queued", "retry"}
            and all(dep in by_id and by_id[dep]["status"] == "tested" for dep in row["dependencies"])
        ),
        key=lambda row: (-row["priority"], row["id"]),
    )
    expected_order = [row["id"] for row in expected]
    before = json.dumps(rows, sort_keys=True)
    output = invoke_project(store, "viv_task_scheduler", {"data": rows, "options": {}})
    actual = output["output"].get("order") if isinstance(output["output"], dict) else None
    passed = actual == expected_order and json.dumps(rows, sort_keys=True) == before
    receipt["cases"].append({
        "case": case_number, "passed": passed, "input_sha256": hashlib.sha256(before.encode()).hexdigest(),
        "expected": expected_order, "actual": actual,
    })
    if not passed:
        break

receipt["passed"] = len(receipt["cases"]) == 40 and all(row["passed"] for row in receipt["cases"])
receipt["finished"] = time.time()
store.event("independent_scheduler_evaluation", {
    "version": version["version"], "passed": receipt["passed"],
    "cases": len(receipt["cases"]), "oracle": "separately_authored_python_reference",
})
output_dir = STATE / "project_evaluations" / f"viv_task_scheduler_{time.time_ns()}"
output_dir.mkdir(parents=True)
path = output_dir / "independent_evaluation.json"
path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
if not receipt["passed"]:
    raise SystemExit(f"Independent evaluation failed: {path}")
print(json.dumps({"passed": True, "cases": len(receipt["cases"]), "receipt": str(path)}))
