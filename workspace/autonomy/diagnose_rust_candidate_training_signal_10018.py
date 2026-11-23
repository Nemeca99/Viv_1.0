"""Compare parent/child candidate behavior on epoch 10018 gate-accepted examples."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import urllib.request

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
sys.path[:0] = [str(WORKSPACE), str(HERE)]

import evaluate_frozen_candidate_code_v1 as evaluator
import train_candidate_rust_increment_10018 as curriculum
import viv_code_learning_loop as gates

API = "http://127.0.0.1:1234"
ROOT = Path(r"F:\LocalCoder_Archive\Viv_model_candidates")
LIVE = Path(r"E:\Viv_Sandbox\playground\adapters\epoch_10001")
PARENT = ROOT / "epoch_10016"
CHILD = ROOT / (sys.argv[1] if len(sys.argv) > 1 else "epoch_10018")
DATA = HERE / "learning" / "deepseek_candidate_runs" / "candidate_rust_training_10018.json"
OUT = HERE / "learning" / "deepseek_candidate_runs"
SELECTED = {"sum_odd_positions", "chunk_sums", "binary_string", "rising_prefix_length"}


def request(path: str, payload: dict | None = None, timeout: int = 240) -> dict:
    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(API + path, data=body,
                                 headers={"Content-Type": "application/json"} if body else {})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical_hash(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def activate(path: Path) -> dict:
    request("/v1/reload_adapter", {"adapter_dir": str(path)})
    status = request("/v1/status")
    if status.get("status") != "ACTIVE" or status.get("active_adapter") != path.name:
        raise RuntimeError("ADAPTER_ACTIVATION_MISMATCH:" + json.dumps(status))
    return status


def main() -> int:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    examples = {row[0]: row for row in curriculum.EXAMPLES}
    samples = [row for row in data["samples"] if row["id"].removeprefix("rust10018_") in SELECTED]
    if len(samples) != len(SELECTED):
        raise ValueError("SELECTED_TRAINING_SAMPLE_COUNT_MISMATCH")
    before = request("/v1/status")
    if before.get("status") != "ACTIVE" or before.get("active_adapter") != LIVE.name:
        raise RuntimeError("LIVE_ADAPTER_NOT_ACTIVE:" + json.dumps(before))

    results = []
    try:
        for adapter in (PARENT, CHILD):
            active = activate(adapter)
            for sample in samples:
                name = sample["id"].removeprefix("rust10018_")
                _, spec, _, checks = examples[name]
                completion = request("/v1/completions", {
                    "model": "deepseek-coder-6.7b-base", "prompt": sample["prompt"],
                    "max_tokens": 320, "temperature": 0.0,
                    "stop": ["\n#[cfg(test)]", "\n# Test code", "\n// Test code", "\nfn main()"],
                })
                raw = completion["choices"][0]["text"]
                header, _ = curriculum.rust_signature(spec)
                full = header + raw
                code = evaluator.extract_requested_function(full, "rust", spec)
                tests = "#[cfg(test)] mod t { use super::*; #[test] fn cases(){ " + checks + " } }"
                passed, error = gates.gate_rust(code, tests) if code else (False, "NO_COMPLETE_REQUESTED_FUNCTION")
                result = {"adapter": adapter.name, "adapter_sha256": sha256(adapter / "adapter_model.safetensors"),
                          "active_status": active, "task": sample["id"], "raw_output": raw,
                          "extracted_code": code, "gate_passed": bool(passed), "gate_error": error[:2500]}
                results.append(result)
                print(json.dumps({"adapter": adapter.name, "task": sample["id"],
                                  "gate_passed": bool(passed), "code_extracted": bool(code)}),
                      flush=True)
    finally:
        restored = activate(LIVE)

    by_adapter = {}
    for adapter in (PARENT.name, CHILD.name):
        rows = [row for row in results if row["adapter"] == adapter]
        by_adapter[adapter] = {"gate_passed": sum(row["gate_passed"] for row in rows),
                               "total": len(rows)}
    comparisons = []
    for sample in samples:
        task = sample["id"]
        parent_row = next(row for row in results if row["adapter"] == PARENT.name and row["task"] == task)
        child_row = next(row for row in results if row["adapter"] == CHILD.name and row["task"] == task)
        comparisons.append({"task": task, "raw_identical": parent_row["raw_output"] == child_row["raw_output"],
                            "parent_gate": parent_row["gate_passed"], "child_gate": child_row["gate_passed"]})
    payload = {
        "schema": "viv_candidate_rust_training_signal_diagnostic_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "parent": str(PARENT), "parent_sha256": sha256(PARENT / "adapter_model.safetensors"),
        "child": str(CHILD), "child_sha256": sha256(CHILD / "adapter_model.safetensors"),
        "training_data_sha256": sha256(DATA), "selected_tasks": sorted(SELECTED),
        "generation": {"temperature": 0.0, "do_sample": False},
        "by_adapter": by_adapter, "comparisons": comparisons, "results": results,
        "live_before": before, "live_restored": restored,
        "candidate_only": True, "promoted": False, "topology_write": False,
        "persistent_memory_write": False,
    }
    payload["receipt_sha256"] = canonical_hash(payload)
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / f"candidate_rust_training_signal_{CHILD.name}_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"receipt": str(target), "receipt_sha256": payload["receipt_sha256"],
                      "by_adapter": by_adapter, "comparisons": comparisons,
                      "live_restored": restored.get("active_adapter"), "promoted": False}, indent=2))
    return 0 if restored.get("active_adapter") == LIVE.name else 1


if __name__ == "__main__":
    raise SystemExit(main())
