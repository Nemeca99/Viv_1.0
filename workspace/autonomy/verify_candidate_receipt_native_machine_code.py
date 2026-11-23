"""Rebuild a passing frozen-suite Rust proposal and emit a native object file."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()

    receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    claimed_receipt_hash = receipt.pop("receipt_sha256", None)
    if canonical_sha256(receipt) != claimed_receipt_hash:
        raise ValueError("EVALUATION_RECEIPT_HASH_MISMATCH")
    if receipt.get("language") != "rust" or receipt.get("promoted") is not False:
        raise ValueError("RECEIPT_LANGUAGE_OR_PROMOTION_STATE_INVALID")
    candidate = Path(receipt["candidate_path"])
    adapter_path = candidate / "adapter_model.safetensors"
    candidate_hash = sha256(adapter_path)
    if candidate_hash != receipt.get("candidate_sha256"):
        raise ValueError("CANDIDATE_ADAPTER_HASH_MISMATCH")

    suite = json.loads(args.suite.read_text(encoding="utf-8"))
    suite_hash = suite.pop("suite_sha256", None)
    if canonical_sha256(suite) != suite_hash or suite_hash != receipt.get("suite_sha256"):
        raise ValueError("FROZEN_SUITE_HASH_MISMATCH")
    tasks = {row["id"]: row for row in suite["held_out"] if row["lang"] == "rust"}
    passing = next((row for row in receipt["results"]
                    if row.get("final_pass") is True and row.get("task") in tasks), None)
    if passing is None:
        raise ValueError("NO_PASSING_RUST_PROPOSAL_IN_RECEIPT")
    attempt = next((row for row in reversed(passing["attempts"]) if row.get("passed") is True), None)
    if attempt is None or not attempt.get("code"):
        raise ValueError("PASSING_ATTEMPT_HAS_NO_CODE")

    task = tasks[passing["task"]]
    source_text = attempt["code"].rstrip() + "\n"
    test_text = source_text + "\n" + task["tests"].strip() + "\n"
    out = args.output_root / f"{candidate.name}_{passing['task']}_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    out.mkdir(parents=True, exist_ok=False)
    source = out / "model_generated.rs"
    tests = out / "model_generated_tests.rs"
    binary = out / "model_generated_tests.exe"
    obj = out / "model_generated.obj"
    source.write_text(source_text, encoding="utf-8", newline="\n")
    tests.write_text(test_text, encoding="utf-8", newline="\n")

    compile_tests = subprocess.run(["rustc", "--test", "--edition", "2021", str(tests), "-o", str(binary)],
                                   capture_output=True, text=True, timeout=120)
    run_tests = (subprocess.run([str(binary)], capture_output=True, text=True, timeout=45)
                 if compile_tests.returncode == 0 else None)
    compile_obj = subprocess.run(["rustc", "--crate-type", "lib", "--emit=obj", "--edition", "2021",
                                  str(source), "-o", str(obj)],
                                 capture_output=True, text=True, timeout=120)
    passed = bool(compile_tests.returncode == 0 and run_tests is not None
                  and run_tests.returncode == 0 and compile_obj.returncode == 0
                  and obj.is_file() and obj.stat().st_size > 0)
    result = {
        "schema": "viv_candidate_native_machine_code_proof_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "evaluation_receipt": str(args.receipt),
        "evaluation_receipt_sha256": claimed_receipt_hash,
        "suite_sha256": suite_hash,
        "candidate_path": str(candidate),
        "candidate_sha256": candidate_hash,
        "task": passing["task"],
        "model_generated_code": attempt["code"],
        "test_compile_exit": compile_tests.returncode,
        "test_compile_stderr": compile_tests.stderr[-3000:],
        "test_run_exit": None if run_tests is None else run_tests.returncode,
        "test_run_stdout": "" if run_tests is None else run_tests.stdout[-3000:],
        "test_run_stderr": "" if run_tests is None else run_tests.stderr[-3000:],
        "object_compile_exit": compile_obj.returncode,
        "object_compile_stderr": compile_obj.stderr[-3000:],
        "object_path": str(obj) if obj.is_file() else None,
        "object_size": obj.stat().st_size if obj.is_file() else 0,
        "object_sha256": sha256(obj) if obj.is_file() else None,
        "passed": passed,
        "promoted": False,
    }
    result["receipt_sha256"] = canonical_sha256(result)
    receipt_path = out / "receipt.json"
    receipt_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": passed, "task": passing["task"],
                      "test_compile_exit": compile_tests.returncode,
                      "test_run_exit": result["test_run_exit"],
                      "object_compile_exit": compile_obj.returncode,
                      "object_size": result["object_size"],
                      "object_sha256": result["object_sha256"],
                      "receipt": str(receipt_path), "promoted": False}, indent=2), flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
