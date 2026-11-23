"""Admit one real first-party function through Viv's candidate body gate."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import candidate_verified_function_store as store
import viv_code_learning_loop as curriculum

SOURCE = HERE / "viv_verified_rust" / "rs_is_prime.rs"
LANG = "rust"
DOMAIN = "rust.integer"
SPEC = ("pub fn is_prime(n: u64) -> bool: classify integers using the "
        "existing code-learning curriculum contract")
TASK_ID = "first_party_seed_rs_is_prime_v1"
RECEIPT_DIR = HERE / "learning" / "neural_runs" / "source_seed_receipts"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    source_bytes = SOURCE.read_bytes()
    source_text = source_bytes.decode("utf-8")
    task = next(row for row in curriculum.CURRICULUM
                if row["id"] == "rs_is_prime")
    tests = task["tests"]
    expected_hash = sha256(source_bytes)

    admitted = store.admit_candidate(
        task_id=TASK_ID,
        lang=LANG,
        domain=DOMAIN,
        spec=SPEC,
        code=source_text,
        tests=tests,
        source_kind=f"first_party_source:{SOURCE}",
        source_sha256=expected_hash,
    )
    active = store.get_active(lang=LANG, domain=DOMAIN, spec=SPEC)
    if admitted["decision"] != "ALLOW" or active is None:
        raise SystemExit(json.dumps({"admission": admitted,
                                     "retrieved": active is not None}, indent=2))

    # Recheck the exact persisted bytes and rerun the same deterministic body gate.
    if sha256(active["code"].encode("utf-8")) != active["code_sha256"]:
        raise SystemExit("PERSISTED_CODE_HASH_MISMATCH")
    passed, output = curriculum.gate_rust(active["code"], tests)
    if not passed:
        raise SystemExit("RETRIEVED_FUNCTION_GATE_DENIED: " + output)

    receipt = {
        "schema": "viv_first_party_function_seed_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "task_id": TASK_ID,
        "language": LANG,
        "domain": DOMAIN,
        "specification": SPEC,
        "source_path": str(SOURCE),
        "source_sha256": expected_hash,
        "source_kind": f"first_party_source:{SOURCE}",
        "tests_source": "existing viv_code_learning_loop.CURRICULUM[rs_is_prime]",
        "tests_sha256": sha256(tests.encode("utf-8")),
        "decision": admitted["decision"],
        "version_id": admitted.get("version_id"),
        "function_key": admitted["function_key"],
        "code_sha256": admitted["code_sha256"],
        "gate_receipt_sha256": admitted["gate_receipt_sha256"],
        "retrieval_gate": "ALLOW",
        "retrieval_gate_output": output,
        "candidate_database": str(store.DB_PATH),
        "live_viv_modified": False,
        "promoted": False,
    }
    receipt["receipt_sha256"] = store.canonical_hash(receipt)
    RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
    target = RECEIPT_DIR / "first_party_rs_is_prime_v1.json"
    target.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(json.dumps({"result": "SOURCE_SEEDED_AND_RETRIEVED",
                      "admission": admitted["decision"],
                      "retrieval_gate": "ALLOW",
                      "source_sha256": expected_hash,
                      "code_sha256": admitted["code_sha256"],
                      "version_id": admitted.get("version_id"),
                      "receipt": str(target),
                      "receipt_sha256": sha256(target.read_bytes()),
                      "live_viv_modified": False,
                      "promoted": False}, indent=2), flush=True)


if __name__ == "__main__":
    main()
