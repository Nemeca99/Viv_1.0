"""Revalidate and assemble a broader, leakage-free candidate SFT corpus."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
for item in (WORKSPACE, HERE):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

import viv_code_learning_loop as gates
import viv_sleep_trainer as trainer
from transformers import PreTrainedTokenizerFast

GRADUATED = Path(r"E:\Viv_Sandbox\playground\training\graduated_successes.jsonl")
SUITE = HERE / "learning" / "deepseek_candidate_runs" / "frozen_code_eval_v1.json"
OUT = HERE / "learning" / "deepseek_candidate_runs" / "verified_multidomain_training_v1.json"
TOKEN_LIMIT = 512


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_obj(value: object) -> str:
    return sha_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                separators=(",", ":")).encode("utf-8"))


def main() -> int:
    if OUT.exists():
        raise FileExistsError(OUT)
    if not GRADUATED.is_file() or not SUITE.is_file():
        raise FileNotFoundError("graduated corpus or frozen evaluation suite missing")

    accepted_module_spec = importlib.util.spec_from_file_location("accepted_receipt_rows", HERE / "run_deepseek_candidate_e2e.py")
    accepted_module = importlib.util.module_from_spec(accepted_module_spec)
    assert accepted_module_spec and accepted_module_spec.loader
    accepted_module_spec.loader.exec_module(accepted_module)
    receipt_rows, receipt_lineage = accepted_module.accepted_training_samples()
    py_rows = [row for row in receipt_rows if not row["category"].startswith("rs_")]

    trainer_module_spec = importlib.util.spec_from_file_location("rust_gate_examples", HERE / "train_rust_balanced_candidate_epoch10005.py")
    trainer_module = importlib.util.module_from_spec(trainer_module_spec)
    assert trainer_module_spec and trainer_module_spec.loader
    trainer_module_spec.loader.exec_module(trainer_module)
    rust_rows, rust_proofs = trainer_module.additional_rust_examples()

    suite = json.loads(SUITE.read_text(encoding="utf-8"))
    held_ids = {row["id"] for row in suite["held_out"]}
    forbidden = ("numpy", "pandas", "subprocess", "socket", "input(", "open(", "os.system")
    raw_lines = GRADUATED.read_text(encoding="utf-8", errors="strict").splitlines()
    graduated = [json.loads(line) for line in raw_lines if line.strip()]
    tokenizer = PreTrainedTokenizerFast.from_pretrained(
        str(trainer.DEFAULT_BASE_MODEL), local_files_only=True)
    python_proofs = []
    seen_codes = {hashlib.sha256(row["completion"].encode()).hexdigest() for row in py_rows}
    corpus_rows = []
    for index, row in enumerate(graduated):
        code = str(row.get("code", ""))
        spec = str(row.get("spec", ""))
        lowered = code.casefold()
        if not code or not spec or any(token in lowered for token in forbidden):
            continue
        code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
        if code_hash in seen_codes:
            continue
        prompt = f"USER: {spec}\n\nASSISTANT:\n"
        full = prompt + code.rstrip() + "\n"
        token_count = len(tokenizer(full, add_special_tokens=False, truncation=False)["input_ids"])
        if token_count > TOKEN_LIMIT:
            continue
        passed, error = gates.gate_python(code, "")
        python_proofs.append({"source_line": index + 1, "category": row.get("category"),
                              "spec": spec, "code_sha256": code_hash,
                              "token_count": token_count, "gate_passed": bool(passed),
                              "gate_error": error[:1200]})
        if not passed:
            continue
        seen_codes.add(code_hash)
        corpus_rows.append({"category": f"graduated_{index + 1}", "prompt": prompt,
                            "completion": code.rstrip() + "\n"})

    py_rows.extend(corpus_rows)
    if not py_rows or not rust_rows:
        raise RuntimeError("verified multimodal corpus lacks Python or Rust examples")
    samples = py_rows + rust_rows
    overlap = sorted(held_ids.intersection(row["category"] for row in samples))
    if overlap:
        raise RuntimeError(f"held-out leak: {overlap}")
    payload = {
        "schema": "viv_verified_multidomain_training_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "graduated_source": str(GRADUATED),
        "graduated_source_sha256": sha_bytes(GRADUATED.read_bytes()),
        "graduated_source_row_count": len(graduated),
        "receipt_verified_code_lineage": receipt_lineage,
        "graduated_python_gate_proofs": python_proofs,
        "verified_rust_gate_proofs": rust_proofs,
        "python_sample_count": len(py_rows), "rust_sample_count": len(rust_rows),
        "sample_count": len(samples), "token_limit": TOKEN_LIMIT,
        "frozen_suite_path": str(SUITE), "frozen_suite_sha256": sha_bytes(SUITE.read_bytes()),
        "held_out_overlap": overlap, "samples": samples,
    }
    payload["training_sha256"] = sha_obj(samples)
    payload["receipt_sha256"] = sha_obj(payload)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"dataset": str(OUT), "dataset_sha256": payload["receipt_sha256"],
                      "python_samples": len(py_rows), "rust_samples": len(rust_rows),
                      "graduates_revalidated": sum(x["gate_passed"] for x in python_proofs),
                      "graduates_rejected": sum(not x["gate_passed"] for x in python_proofs),
                      "held_out_overlap": overlap,
                      "training_sha256": payload["training_sha256"]}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
