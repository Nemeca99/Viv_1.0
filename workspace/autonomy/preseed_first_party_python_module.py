"""Seed a real first-party Python module and its existing tests as a bundle."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
sys.path.insert(0, str(HERE))

import candidate_verified_function_store as store
import viv_code_learning_loop as gates

SOURCE = WORKSPACE / "build_aios_source_baseline.py"
TEST_SOURCE = WORKSPACE / "test_build_aios_source_baseline.py"
DOMAIN = "python.source_graph"
SPEC = ("def build_manifest(root: Path = SOURCE_ROOT) -> dict: "
        "build the existing read-only source catalog and dependency graph")
TASK_ID = "first_party_seed_build_aios_source_baseline_v1"
RECEIPT_DIR = HERE / "learning" / "neural_runs" / "source_seed_receipts"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_test_harness(raw: str) -> str:
    """Keep the existing test cases; remove only module import and future line."""
    lines = raw.splitlines()
    cleaned = []
    removed_import = 0
    for line in lines:
        if line.strip() == "from __future__ import annotations":
            continue
        if line.strip() == "from build_aios_source_baseline import CORE_NAMES, build_manifest":
            removed_import += 1
            continue
        if line.strip() == "unittest.main()":
            line = line.replace("unittest.main()", "unittest.main(exit=False)")
        cleaned.append(line)
    if removed_import != 1:
        raise ValueError("EXPECTED_TEST_MODULE_IMPORT_NOT_FOUND_ONCE")
    return "\n".join(cleaned) + "\n"


def make_source_bundle(source: str) -> str:
    """Load the unchanged source as its own module so its CLI guard stays inert."""
    return (
        "import types as _viv_types\n"
        "_viv_source_module = _viv_types.ModuleType('viv_seeded_source_module')\n"
        f"_viv_source_module.__file__ = {str(SOURCE)!r}\n"
        f"exec(compile({source!r}, {str(SOURCE)!r}, 'exec'), "
        "vars(_viv_source_module))\n"
        "CORE_NAMES = _viv_source_module.CORE_NAMES\n"
        "build_manifest = _viv_source_module.build_manifest\n"
    )


def main() -> None:
    source_bytes = SOURCE.read_bytes()
    test_bytes = TEST_SOURCE.read_bytes()
    source = source_bytes.decode("utf-8")
    raw_tests = test_bytes.decode("utf-8")
    code = make_source_bundle(source)
    tests = make_test_harness(raw_tests)
    source_hash = sha256(source_bytes)
    raw_test_hash = sha256(test_bytes)
    harness_hash = sha256(tests.encode("utf-8"))

    passed, output = gates.gate_python(code, tests)
    if not passed:
        raise SystemExit("FIRST_PARTY_SOURCE_TESTS_DENIED: " + output)

    admitted = store.admit_candidate(
        task_id=TASK_ID,
        lang="python",
        domain=DOMAIN,
        spec=SPEC,
        code=code,
        tests=tests,
        source_kind=f"first_party_module:{SOURCE}",
        source_sha256=source_hash,
    )
    active = store.get_active(lang="python", domain=DOMAIN, spec=SPEC)
    if admitted["decision"] != "ALLOW" or active is None:
        raise SystemExit(json.dumps({"admission": admitted,
                                     "retrieved": active is not None}, indent=2))
    if sha256(active["code"].encode("utf-8")) != active["code_sha256"]:
        raise SystemExit("PERSISTED_MODULE_HASH_MISMATCH")
    retrieved_pass, retrieved_output = gates.gate_python(active["code"], tests)
    if not retrieved_pass:
        raise SystemExit("RETRIEVED_MODULE_TESTS_DENIED: " + retrieved_output)

    receipt = {
        "schema": "viv_first_party_python_module_seed_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "task_id": TASK_ID,
        "language": "python",
        "domain": DOMAIN,
        "function_name": "build_manifest",
        "bundle_contract": "existing full module; helper calls and source graph preserved",
        "source_path": str(SOURCE),
        "source_sha256": source_hash,
        "source_embedded_verbatim_in_loader": True,
        "test_source_path": str(TEST_SOURCE),
        "test_source_sha256": raw_test_hash,
        "test_harness_sha256": harness_hash,
        "test_harness_changes": [
            "removed the test file's future import (module source already has it)",
            "removed import of the supplied source module",
            "used unittest.main(exit=False) so gate sentinel can be emitted",
        ],
        "admission": admitted["decision"],
        "version_id": admitted.get("version_id"),
        "function_key": admitted["function_key"],
        "code_sha256": admitted["code_sha256"],
        "gate_receipt_sha256": admitted["gate_receipt_sha256"],
        "retrieval_gate": "ALLOW",
        "source_graph_tests_output": retrieved_output,
        "candidate_database": str(store.DB_PATH),
        "live_viv_modified": False,
        "promoted": False,
    }
    receipt["receipt_sha256"] = store.canonical_hash(receipt)
    RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
    target = RECEIPT_DIR / "first_party_python_source_graph_v1.json"
    target.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(json.dumps({"result": "SOURCE_MODULE_SEEDED_RETRIEVED_AND_RETESTED",
                      "admission": admitted["decision"],
                      "module_source_sha256": source_hash,
                      "original_test_sha256": raw_test_hash,
                      "stored_code_sha256": admitted["code_sha256"],
                      "tests": retrieved_output,
                      "version_id": admitted.get("version_id"),
                      "receipt": str(target),
                      "receipt_sha256": sha256(target.read_bytes()),
                      "live_viv_modified": False,
                      "promoted": False}, indent=2), flush=True)


if __name__ == "__main__":
    main()
