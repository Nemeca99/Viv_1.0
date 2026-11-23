"""Train an isolated adapter on receipt-accepted examples with Rust balancing."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import sys
import urllib.request

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
for item in (WORKSPACE, HERE):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

import viv_code_learning_loop as gates
import viv_sleep_trainer as trainer
from viv_reference_examples import REFERENCE

API = "http://127.0.0.1:1234"
LIVE = Path(r"E:\Viv_Sandbox\playground\adapters\epoch_10001")
PARENT = Path(os.environ.get("VIV_CANDIDATE_PARENT", r"F:\LocalCoder_Archive\Viv_model_candidates\epoch_10002"))
ROOT = Path(r"F:\LocalCoder_Archive\Viv_model_candidates")
SUITE = HERE / "learning" / "deepseek_candidate_runs" / "frozen_code_eval_v1.json"
EPOCH = int(os.environ.get("VIV_CANDIDATE_EPOCH", "10005"))
STEPS = int(os.environ.get("VIV_CANDIDATE_STEPS", "60"))
LEARNING_RATE = float(os.environ.get("VIV_CANDIDATE_LR", "1e-5"))
SEED = int(os.environ.get("VIV_CANDIDATE_SEED", "20261113"))
DEST = ROOT / f"epoch_{EPOCH:05d}"


def request(path: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(API + path, data=data,
                                 headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=240) as response:
        return json.load(response)


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def sha_obj(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def additional_rust_examples() -> tuple[list[dict], list[dict]]:
    curriculum = {row["id"]: row for row in gates.CURRICULUM}
    specs = {
        "rs_fib": ("pub fn fib(n: u32) -> u64: Fibonacci; fib(0)=0 and fib(1)=1", REFERENCE["rs_fib"]),
        "rs_reverse": ("pub fn reverse(s: &str) -> String: reverse Unicode characters", REFERENCE["rs_reverse"]),
        "rs_sum_to": ("pub fn sum_to(n: u64) -> u64: sum integers from one through n; zero returns zero", "pub fn sum_to(n: u64) -> u64 { (1..=n).sum() }"),
        "rs_count_char": ("pub fn count_char(s: &str, c: char) -> usize: count exact Unicode characters", "pub fn count_char(s: &str, c: char) -> usize { s.chars().filter(|&x| x == c).count() }"),
        "rs_max_of": ("pub fn max_of(xs: &[i32]) -> Option<i32>: maximum value or None for empty input", "pub fn max_of(xs: &[i32]) -> Option<i32> { xs.iter().copied().max() }"),
        "rs_gcd": ("pub fn gcd(a: u64, b: u64) -> u64: greatest common divisor; gcd(0,0)=0", "pub fn gcd(mut a: u64, mut b: u64) -> u64 { while b != 0 { let t=b; b=a%b; a=t; } a }"),
    }
    extra_tests = {
        "rs_sum_to": "#[cfg(test)] mod t { use super::*; #[test] fn p(){ assert_eq!(sum_to(0),0); assert_eq!(sum_to(1),1); assert_eq!(sum_to(10),55); } }",
        "rs_count_char": "#[cfg(test)] mod t { use super::*; #[test] fn p(){ assert_eq!(count_char(\"banana\",'a'),3); assert_eq!(count_char(\"\",'a'),0); assert_eq!(count_char(\"🙂🙂x\",'🙂'),2); } }",
        "rs_max_of": "#[cfg(test)] mod t { use super::*; #[test] fn p(){ assert_eq!(max_of(&[1,8,2]),Some(8)); assert_eq!(max_of(&[]),None); assert_eq!(max_of(&[-7,-2]),Some(-2)); } }",
        "rs_gcd": "#[cfg(test)] mod t { use super::*; #[test] fn p(){ assert_eq!(gcd(12,18),6); assert_eq!(gcd(7,0),7); assert_eq!(gcd(0,0),0); assert_eq!(gcd(17,5),1); } }",
    }
    rows, proof = [], []
    for task_id, (spec, code) in specs.items():
        tests = curriculum[task_id]["tests"] if task_id in curriculum else extra_tests[task_id]
        passed, error = gates.gate_rust(code, tests)
        if not passed:
            raise RuntimeError(f"gate rejected training source {task_id}: {error}")
        rows.append({"category": task_id, "prompt": f"USER: {spec}\n\nASSISTANT:\n",
                     "completion": code + "\n"})
        proof.append({"task": task_id, "gate": "rustc --test isolated Docker", "passed": True,
                      "code_sha256": hashlib.sha256(code.encode()).hexdigest(),
                      "tests_sha256": hashlib.sha256(tests.encode()).hexdigest()})
    return rows, proof


def main() -> int:
    if DEST.exists():
        raise FileExistsError(DEST)
    if not (PARENT / "adapter_model.safetensors").is_file():
        raise FileNotFoundError(PARENT)
    if not SUITE.is_file():
        raise FileNotFoundError(SUITE)
    suite = json.loads(SUITE.read_text(encoding="utf-8"))
    held_ids = {row["id"] for row in suite["held_out"]}
    status = request("/v1/status")
    if status.get("status") != "ACTIVE" or status.get("active_adapter") != LIVE.name:
        raise RuntimeError(f"unexpected live adapter: {status}")

    spec = importlib.util.spec_from_file_location("candidate_training_rows", HERE / "run_deepseek_candidate_e2e.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    accepted, accepted_lineage = module.accepted_training_samples()
    extra_rust, rust_proofs = additional_rust_examples()
    if any(row["category"] in held_ids for row in accepted + extra_rust):
        raise RuntimeError("held-out task leakage detected")
    python_rows = [row for row in accepted if not row["category"].startswith("rs_")]
    rust_rows = [row for row in accepted if row["category"].startswith("rs_")] + extra_rust
    if not python_rows or not rust_rows:
        raise RuntimeError("missing training examples for one language")
    rust_balanced = (rust_rows * ((len(python_rows) + len(rust_rows) - 1) // len(rust_rows)))[:len(python_rows)]
    samples = (python_rows + rust_balanced) * 2
    receipt_path = HERE / "learning" / "deepseek_candidate_runs" / f"rust_balanced_training_{EPOCH}.json"
    if receipt_path.exists():
        raise FileExistsError(receipt_path)
    preflight = {
        "schema": "viv_rust_balanced_candidate_training_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "live_adapter_before": status, "parent": str(PARENT),
        "parent_sha256": sha_file(PARENT / "adapter_model.safetensors"),
        "suite_sha256": sha_file(SUITE), "accepted_training_lineage": accepted_lineage,
        "additional_rust_gate_proofs": rust_proofs,
        "python_unique_sources": len(python_rows), "rust_unique_sources": len(rust_rows),
        "balanced_replayed_sample_count": len(samples), "training_sha256": sha_obj(samples),
        "held_out_overlap": sorted(held_ids.intersection(row["category"] for row in samples)),
        "seed": SEED, "learning_rate": LEARNING_RATE, "max_steps": STEPS,
        "candidate_path": str(DEST), "promoted": False,
    }
    print(json.dumps({"phase": "preflight", "python_sources": len(python_rows),
                      "rust_sources": len(rust_rows), "balanced_samples": len(samples),
                      "held_out_overlap": preflight["held_out_overlap"],
                      "candidate": str(DEST)}, indent=2), flush=True)

    quiesced = False
    training = None
    restored = None
    try:
        state = request("/v1/quiesce", {})
        if state.get("status") != "QUIESCED":
            raise RuntimeError(f"tutor did not quiesce: {state}")
        quiesced = True
        import torch
        from transformers import set_seed
        random.seed(SEED)
        torch.manual_seed(SEED)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(SEED)
        set_seed(SEED)
        trainer.ADAPTERS_ROOT = ROOT
        trainer.RECEIPTS_FILE = ROOT / "training_receipts.jsonl"
        training = trainer.run_sleep_training(epoch=EPOCH, steps=STEPS, lr=LEARNING_RATE,
                                             parent_adapter=PARENT, training_samples=samples)
        if not training.get("ok"):
            raise RuntimeError(f"trainer failed: {training}")
    finally:
        if quiesced:
            request("/v1/resume", {"adapter_dir": str(LIVE)})
            restored = request("/v1/status")
            if restored.get("status") != "ACTIVE" or restored.get("active_adapter") != LIVE.name:
                raise RuntimeError(f"live adapter restoration failed: {restored}")

    result = {**preflight, "training": training,
              "candidate_sha256": sha_file(DEST / "adapter_model.safetensors"),
              "live_adapter_restored": restored, "trained": True, "promoted": False}
    result["receipt_sha256"] = sha_obj(result)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"phase": "complete", "receipt": str(receipt_path),
                      "candidate": str(DEST), "candidate_sha256": result["candidate_sha256"],
                      "steps": training["receipt"]["steps_completed"],
                      "loss": training["receipt"]["final_loss"],
                      "live_adapter": restored.get("active_adapter"), "promoted": False}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
