"""Compile gate-accepted candidate Rust into a native object on L:."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import os
import subprocess
from pathlib import Path
import uuid

HERE = Path(__file__).resolve().parent
RUNS = HERE / "learning" / "deepseek_candidate_runs"
EVAL = Path(os.environ.get("VIV_CODE_EVAL_RECEIPT", str(RUNS / "candidate_runtime_v1_20261112T015229628525Z_01c90ac6.json")))
TASK_ID = "rs_celsius_to_fahrenheit"
CANDIDATE = Path(os.environ.get("VIV_CODE_CANDIDATE", r"F:\LocalCoder_Archive\Viv_model_candidates\epoch_10010"))
ARTIFACTS = RUNS / f"native_machine_proof_{CANDIDATE.name}"

def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def object_hash(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()

def main() -> int:
    receipt = json.loads(EVAL.read_text(encoding="utf-8"))
    expected_hash = receipt.pop("receipt_sha256")
    if object_hash(receipt) != expected_hash:
        raise ValueError("candidate evaluation receipt hash mismatch")
    if receipt.get("candidate_sha256") != file_hash(CANDIDATE / "adapter_model.safetensors"):
        raise ValueError("candidate checkpoint hash mismatch")
    row = next(item for item in receipt["results"] if item["task"] == TASK_ID)
    if not row["final_pass"]:
        raise ValueError("selected Rust task did not pass its deterministic gate")
    code = row["attempts"][-1]["code"]
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    source = ARTIFACTS / f"{TASK_ID}.rs"
    obj = ARTIFACTS / f"{TASK_ID}.obj"
    source.write_text("#![allow(dead_code)]\n" + code + "\n", encoding="utf-8")
    version = subprocess.run(["rustc", "--version"], capture_output=True, text=True, timeout=30)
    result = subprocess.run(["rustc", "--edition=2021", "--crate-type=lib", "--emit=obj",
                             str(source), "-o", str(obj)], capture_output=True, text=True,
                            timeout=120, cwd=str(ARTIFACTS))
    output = {"schema": "viv_candidate_native_object_proof_v1",
              "created_utc": datetime.now(timezone.utc).isoformat(),
              "candidate": str(CANDIDATE), "candidate_sha256": receipt["candidate_sha256"],
              "evaluation_receipt": str(EVAL), "evaluation_receipt_sha256": expected_hash,
              "task_id": TASK_ID, "deterministic_gate_passed": True,
              "rustc_version": version.stdout.strip(), "compile_exit_code": result.returncode,
              "compile_stdout": result.stdout[-2000:], "compile_stderr": result.stderr[-4000:],
              "source_path": str(source), "source_sha256": file_hash(source),
              "object_path": str(obj) if obj.exists() else None,
              "object_sha256": file_hash(obj) if obj.exists() else None,
              "object_size_bytes": obj.stat().st_size if obj.exists() else 0,
              "promoted": False}
    output["receipt_sha256"] = object_hash(output)
    target = ARTIFACTS / f"{TASK_ID}_receipt_{uuid.uuid4().hex[:8]}.json"
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"receipt": str(target), "compile_exit_code": result.returncode,
                      "rustc": version.stdout.strip(), "object": str(obj) if obj.exists() else None,
                      "object_size_bytes": output["object_size_bytes"],
                      "object_sha256": output["object_sha256"]}, indent=2))
    return 0 if result.returncode == 0 and output["object_size_bytes"] > 0 else 1

if __name__ == "__main__":
    raise SystemExit(main())
