"""Compile and execute Rust emitted by a passing model evaluation receipt."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(r"L:\LocalCoder\workspace")
COMPARISON = ROOT / "autonomy" / "learning" / "deepseek_candidate_runs" / "comparison_20261111T012039Z.json"
OUT_DIR = Path(r"F:\LocalCoder_Archive\Viv_model_candidates\compiled_machine_proofs\epoch_10002_rs_fib_20261110")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if OUT_DIR.exists():
        raise FileExistsError(OUT_DIR)
    receipt = json.loads(COMPARISON.read_text(encoding="utf-8"))
    provided_hash = receipt.pop("receipt_sha256")
    canonical = json.dumps(receipt, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode("utf-8")
    if hashlib.sha256(canonical).hexdigest() != provided_hash:
        raise ValueError("comparison receipt hash mismatch")
    selected = next((row for row in receipt["candidate"] if row.get("task") == "rs_fib"), None)
    if not selected or selected.get("passed") is not True:
        raise ValueError("candidate has no passing generated rs_fib result")
    code = selected.get("code", "").strip()
    if "pub fn fib" not in code:
        raise ValueError("receipt code does not contain generated fib function")

    OUT_DIR.mkdir(parents=True)
    source = OUT_DIR / "generated_fib.rs"
    tests = OUT_DIR / "generated_fib_tests.rs"
    binary = OUT_DIR / "generated_fib_tests.exe"
    object_file = OUT_DIR / "generated_fib.obj"
    source.write_text(code + "\n", encoding="utf-8")
    tests.write_text(code + "\n" + r'''
#[cfg(test)]
mod generated_tests {
    use super::fib;
    #[test]
    fn known_values_and_boundary() {
        assert_eq!(fib(0), 0);
        assert_eq!(fib(1), 1);
        assert_eq!(fib(10), 55);
        assert_eq!(fib(20), 6765);
    }
}
fn main() {
    assert_eq!(fib(0), 0);
    assert_eq!(fib(1), 1);
    assert_eq!(fib(10), 55);
    assert_eq!(fib(20), 6765);
}
''', encoding="utf-8")
    compile_test = subprocess.run(["rustc", "--test", "--edition", "2021", str(tests), "-o", str(binary)],
                                  capture_output=True, text=True, timeout=90)
    run_test = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30) if compile_test.returncode == 0 else None
    compile_obj = subprocess.run(["rustc", "--crate-type", "lib", "--emit=obj", "--edition", "2021",
                                  str(source), "-o", str(object_file)],
                                 capture_output=True, text=True, timeout=90)
    passed = bool(compile_test.returncode == 0 and run_test and run_test.returncode == 0
                  and compile_obj.returncode == 0 and object_file.is_file() and object_file.stat().st_size > 0)
    result = {
        "schema": "viv_generated_rust_machine_code_proof_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_comparison_receipt": str(COMPARISON), "source_receipt_sha256": provided_hash,
        "adapter": selected.get("adapter"), "task": selected.get("task"),
        "model_generated_rust": code, "test_compile_exit": compile_test.returncode,
        "test_compile_stderr": compile_test.stderr[-4000:],
        "test_run_exit": None if run_test is None else run_test.returncode,
        "test_run_stdout": "" if run_test is None else run_test.stdout[-4000:],
        "test_run_stderr": "" if run_test is None else run_test.stderr[-4000:],
        "object_compile_exit": compile_obj.returncode,
        "object_compile_stderr": compile_obj.stderr[-4000:],
        "object_path": str(object_file) if object_file.exists() else None,
        "object_size": object_file.stat().st_size if object_file.exists() else 0,
        "object_sha256": sha(object_file) if object_file.exists() else None,
        "passed": passed, "promoted": False,
    }
    result_path = OUT_DIR / "receipt.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": passed, "test_compile_exit": compile_test.returncode,
                      "test_run_exit": result["test_run_exit"],
                      "object_compile_exit": compile_obj.returncode,
                      "object_size": result["object_size"], "object_sha256": result["object_sha256"],
                      "receipt": str(result_path)}, indent=2), flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
