"""Import the eight non-held-out, gate-verified 10024 Python examples once."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import python_edge_curriculum_test_10017 as curriculum
import candidate_verified_function_store as store

DATASET = HERE / "learning" / "deepseek_candidate_runs" / "candidate_python_training_10024_retry1.json"
RUNS = HERE / "learning" / "neural_runs"
RECEIPT = RUNS / "candidate_function_store_seed_10024.json"


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def code_from_completion(text: str) -> str:
    match = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.S)
    if not match:
        raise ValueError("TRAINING_COMPLETION_NOT_FENCED")
    return match.group(1).strip()


def main() -> int:
    if RECEIPT.exists():
        raise FileExistsError(RECEIPT)
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    recorded = dataset.pop("receipt_sha256", None)
    actual = store.canonical_hash(dataset)
    if recorded != actual:
        raise ValueError("TRAINING_DATASET_RECEIPT_HASH_MISMATCH")
    curriculum_rows = {row["id"]: row for row in curriculum.EDGE_TRANSFER_CURRICULUM}
    dataset_rows = {row["id"]: row for row in dataset["samples"]}
    if len(dataset_rows) != 8 or len(curriculum_rows) != 8 or set(dataset_rows) != set(curriculum_rows):
        raise ValueError("SEED_DATASET_CURRICULUM_MISMATCH")
    if dataset.get("heldout_id_overlap") or dataset.get("heldout_function_name_overlap"):
        raise ValueError("HELD_OUT_OVERLAP_RECORDED")
    source_path = HERE / "python_edge_curriculum_test_10017.py"
    source_hash = file_sha(source_path)
    inserted = []
    store.initialize()
    for task_id, row in curriculum_rows.items():
        sample = dataset_rows[task_id]
        code = code_from_completion(sample["completion"])
        if hashlib.sha256(code.encode("utf-8")).hexdigest() != sample["code_sha256"]:
            raise ValueError(f"TRAINING_CODE_HASH_MISMATCH:{task_id}")
        result = store.admit_candidate(
            task_id=task_id, lang="python", domain="python.core",
            spec=row["spec"], code=code, tests=row["tests"],
            source_kind="epoch_10024_gate_passed_training_example",
            source_sha256=source_hash,
        )
        if result["decision"] != "ALLOW":
            raise RuntimeError(f"CANDIDATE_ADMISSION_DENIED:{task_id}:{result}")
        inserted.append({"task_id": task_id, "function_key": result["function_key"],
                         "version_id": result["version_id"],
                         "code_sha256": result["code_sha256"],
                         "gate_receipt_sha256": result["gate_receipt_sha256"]})
        print(json.dumps({"task": task_id, "decision": result["decision"],
                          "version_id": result["version_id"]}), flush=True)
    payload = {
        "schema": "viv_candidate_function_store_seed_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "store_path": str(store.DB_PATH),
        "training_dataset": str(DATASET),
        "training_dataset_receipt_sha256": recorded,
        "curriculum_sha256": source_hash,
        "heldout_suite_sha256": dataset["heldout_suite_sha256"],
        "admitted": inserted,
        "admitted_count": len(inserted),
        "live_topology_write": False,
        "live_memory_write": False,
        "promoted": False,
    }
    payload["receipt_sha256"] = store.canonical_hash(payload)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    privacy_decision = store.PrivacyCore().authorize_file_write(str(RECEIPT))
    if privacy_decision.get("allowed") is not True:
        raise PermissionError(f"PrivacyCore denied seed receipt: {privacy_decision}")
    with RECEIPT.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
    print(json.dumps({"receipt": str(RECEIPT), "store": str(store.DB_PATH),
                      "admitted_count": len(inserted), "promoted": False}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
