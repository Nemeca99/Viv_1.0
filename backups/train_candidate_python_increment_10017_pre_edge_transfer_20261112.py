"""Train an isolated Python-first candidate from one gate-checked curriculum file."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import random
import re
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
sys.path[:0] = [str(WORKSPACE), str(HERE)]

import python_edge_curriculum_test_10017 as curriculum
import viv_code_learning_loop as gates
import viv_sleep_trainer as trainer

API = "http://127.0.0.1:1234"
LIVE = Path(r"E:\Viv_Sandbox\playground\adapters\epoch_10001")
ROOT = Path(r"F:\LocalCoder_Archive\Viv_model_candidates")
PARENT = ROOT / "epoch_10016"
DEST = ROOT / "epoch_10017"
RUNS = HERE / "learning" / "deepseek_candidate_runs"
SUITE = RUNS / "frozen_code_eval_v2_1.json"
DATA_OUT = RUNS / "candidate_python_training_10017.json"
PREFLIGHT_OUT = RUNS / "candidate_python_preflight_10017.json"
RUN_OUT = RUNS / "candidate_python_training_run_10017.json"
SEED, LEARNING_RATE, STEPS = 20261127, 5e-7, 24
EOS = "<｜end▁of▁sentence｜>"
FENCE = chr(96) * 3


def canonical_hash(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def request(path: str, payload: dict | None = None) -> dict:
    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(API + path, data=body,
                                 headers={"Content-Type": "application/json"} if body else {})
    with urllib.request.urlopen(req, timeout=300) as response:
        return json.load(response)


def function_name(text: str) -> str | None:
    match = re.search(r"\bdef\s+([A-Za-z_]\w*)\s*\(", text)
    return match.group(1) if match else None


def main() -> int:
    for path in (DATA_OUT, PREFLIGHT_OUT, RUN_OUT):
        if path.exists():
            raise FileExistsError(path)
    if DEST.exists():
        raise FileExistsError(DEST)
    if not PARENT.is_dir() or not (PARENT / "adapter_model.safetensors").is_file():
        raise FileNotFoundError(PARENT)

    suite = json.loads(SUITE.read_text(encoding="utf-8"))
    suite_hash = suite.pop("suite_sha256", None)
    if suite_hash != canonical_hash(suite):
        raise ValueError("FROZEN_SUITE_HASH_MISMATCH")
    held_ids = {row["id"] for row in suite["held_out"]}
    held_names = {function_name(row["spec"]) for row in suite["held_out"] if row["lang"] == "python"}

    previous_ids: set[str] = set()
    previous_names: set[str] = set()
    for source in RUNS.glob("*training*.json"):
        if source in (DATA_OUT, PREFLIGHT_OUT, RUN_OUT):
            continue
        try:
            prior = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for row in prior.get("samples", []):
            if not isinstance(row, dict):
                continue
            if row.get("id"):
                previous_ids.add(str(row["id"]))
            name = function_name(str(row.get("completion", "")))
            if name:
                previous_names.add(name)

    examples = curriculum.CURRICULUM
    if len(examples) != 12:
        raise ValueError(f"expected 12 curriculum examples, got {len(examples)}")
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    samples: list[dict] = []
    gate_rows: list[dict] = []
    for item in examples:
        task_id, spec, code, tests = item["id"], item["spec"], item["code"], item["tests"]
        name = function_name(spec)
        if not name or function_name(code) != name:
            raise ValueError(f"FUNCTION_SPEC_CODE_MISMATCH:{task_id}")
        if task_id in held_ids or task_id in previous_ids or task_id in seen_ids:
            raise ValueError(f"TRAINING_ID_OVERLAP:{task_id}")
        if name in held_names or name in previous_names or name in seen_names:
            raise ValueError(f"TRAINING_FUNCTION_OVERLAP:{name}")
        passed, error = gates.gate_python(code, tests)
        gate_rows.append({"id": task_id, "function": name, "passed": bool(passed), "error": error[:2000]})
        print(json.dumps({"preflight_task": task_id, "passed": bool(passed), "error": error[:160]}, ensure_ascii=False), flush=True)
        if not passed:
            continue
        prompt = (
            "SYSTEM: Write one self-contained, correct, standard-library python function. "
            "Do not depend on other top-level helpers. Return only one fenced code block; "
            "no tests or explanation.\n\nUSER: Implement: " + spec + "\n\nASSISTANT:"
        )
        samples.append({
            "id": task_id,
            "category": "python_basic_loop_recursion_gate_verified_v1",
            "prompt": prompt,
            "completion": f"{FENCE}python\n{code}\n{FENCE}{EOS}",
            "source_kind": "single_file_reference_passed_existing_python_gate",
            "spec_sha256": hashlib.sha256(spec.encode()).hexdigest(),
            "code_sha256": hashlib.sha256(code.encode()).hexdigest(),
            "tests_sha256": hashlib.sha256(tests.encode()).hexdigest(),
        })
        seen_ids.add(task_id)
        seen_names.add(name)

    if len(samples) != len(examples) or not all(row["passed"] for row in gate_rows):
        raise RuntimeError("CURRICULUM_GATE_OR_COUNT_FAILURE")

    preflight = {
        "schema": "viv_candidate_python_preflight_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "curriculum_file": str(HERE / "python_edge_curriculum_test_10017.py"),
        "curriculum_sha256": file_hash(HERE / "python_edge_curriculum_test_10017.py"),
        "parent": str(PARENT),
        "heldout_suite_sha256": suite_hash,
        "unique_examples": len(samples),
        "heldout_id_overlap": sorted(set(row["id"] for row in samples) & held_ids),
        "heldout_function_name_overlap": sorted(seen_names & held_names),
        "prior_training_id_overlap": sorted(seen_ids & previous_ids),
        "prior_training_function_overlap": sorted(seen_names & previous_names),
        "gate_results": gate_rows,
        "all_gates_passed": True,
    }
    preflight["receipt_sha256"] = canonical_hash(preflight)
    PREFLIGHT_OUT.write_text(json.dumps(preflight, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    dataset = {
        "schema": "viv_candidate_python_training_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "parent_candidate": str(PARENT),
        "curriculum_file": preflight["curriculum_file"],
        "curriculum_sha256": preflight["curriculum_sha256"],
        "heldout_suite_sha256": suite_hash,
        "heldout_task_count": len(suite["held_out"]),
        "heldout_id_overlap": [],
        "heldout_function_name_overlap": [],
        "python_unique": len(samples),
        "gate_results": gate_rows,
        "samples": samples,
        "training_sha256": canonical_hash(samples),
    }
    dataset["receipt_sha256"] = canonical_hash(dataset)
    DATA_OUT.write_text(json.dumps(dataset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    before = request("/v1/status")
    if before.get("status") != "ACTIVE" or before.get("active_adapter") != LIVE.name:
        raise RuntimeError("UNEXPECTED_LIVE_ADAPTER:" + json.dumps(before))
    trainer.ADAPTERS_ROOT = ROOT
    trainer.RECEIPTS_FILE = ROOT / "training_receipts.jsonl"
    training_rows = samples * 2
    run = {
        "schema": "viv_candidate_python_training_run_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": str(DATA_OUT),
        "dataset_receipt_sha256": dataset["receipt_sha256"],
        "training_sha256": canonical_hash(training_rows),
        "unique_examples": len(samples),
        "training_rows": len(training_rows),
        "seed": SEED,
        "learning_rate": LEARNING_RATE,
        "steps_requested": STEPS,
        "parent": str(PARENT),
        "parent_sha256": file_hash(PARENT / "adapter_model.safetensors"),
        "heldout_suite_sha256": suite_hash,
        "live_before": before,
        "promoted": False,
        "topology_write": False,
        "persistent_memory_write": False,
    }
    quiesced = False
    error = None
    try:
        state = request("/v1/quiesce", {})
        if state.get("status") != "QUIESCED":
            raise RuntimeError("QUIESCE_FAILED:" + json.dumps(state))
        quiesced = True
        import torch
        from transformers import set_seed
        random.seed(SEED)
        torch.manual_seed(SEED)
        set_seed(SEED)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(SEED)
        result = trainer.run_sleep_training(
            epoch=10017, steps=STEPS, lr=LEARNING_RATE,
            parent_adapter=PARENT, training_samples=training_rows,
        )
        if not result.get("ok"):
            raise RuntimeError("TRAINING_FAILED:" + json.dumps(result))
        run["training"] = result
        run["candidate_sha256"] = file_hash(DEST / "adapter_model.safetensors")
        run["status"] = "TRAINED_CANDIDATE"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        run["status"] = "TRAINING_FAILED"
        run["training_error"] = error
    finally:
        if quiesced:
            try:
                request("/v1/resume", {"adapter_dir": str(LIVE)})
            except Exception as exc:
                run["restore_error"] = f"{type(exc).__name__}: {exc}"
    try:
        after = request("/v1/status")
        run["live_after"] = after
        run["live_restored"] = after.get("status") == "ACTIVE" and after.get("active_adapter") == LIVE.name
    except Exception as exc:
        run["live_restored"] = False
        run["restore_status_error"] = f"{type(exc).__name__}: {exc}"
    run["receipt_sha256"] = canonical_hash(run)
    RUN_OUT.write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "preflight_receipt": str(PREFLIGHT_OUT),
        "dataset_receipt": str(DATA_OUT),
        "training_receipt": str(RUN_OUT),
        "unique_examples": len(samples),
        "training_rows": len(training_rows),
        "status": run["status"],
        "candidate_sha256": run.get("candidate_sha256"),
        "live_restored": run.get("live_restored"),
        "active_adapter": run.get("live_after", {}).get("active_adapter"),
        "error": error,
        "promoted": False,
    }, indent=2), flush=True)
    return 0 if run["status"] == "TRAINED_CANDIDATE" and run.get("live_restored") else 1


if __name__ == "__main__":
    raise SystemExit(main())
