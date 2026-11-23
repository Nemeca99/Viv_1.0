"""Run one isolated model-proposal/A-B/gate/admission trial from Viv's source catalog."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import uuid

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(WORKSPACE))

import candidate_function_learning_loop as learner
import candidate_verified_function_store as store

INDEX = HERE / "candidate_template_toolbox" / "candidate_function_index_v2.json"
CATALOG = HERE / "candidate_template_toolbox" / "code_templates" / "source" / "migrated_domains"
OUT_DIR = HERE / "learning" / "neural_runs"
TASK_ID = "template_adapters_as_posix_model_trial_10024"


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    rows = [row for row in index["functions"]
            if row["function_name"] == "_as_posix"
            and row["source_file"] == "adapters/foundation__lib__aios_adapter_audit.py"]
    if len(rows) != 1:
        raise ValueError("TEMPLATE_FUNCTION_INDEX_MATCH_NOT_UNIQUE")
    source = rows[0]
    if source.get("heldout_name_overlap") or source.get("prior_training_name_overlap"):
        raise ValueError("TEMPLATE_FUNCTION_OVERLAP_REJECTED")
    source_path = CATALOG / source["source_file"]
    source_hash = digest_file(source_path)
    if source_hash != index["source_file_sha256"][source["source_file"]]:
        raise ValueError("TEMPLATE_SOURCE_FILE_HASH_MISMATCH")
    lines = source_path.read_text(encoding="utf-8").splitlines()
    reference_span = "\n".join(lines[source["start_line"] - 1:source["end_line"]])
    if hashlib.sha256(reference_span.encode("utf-8")).hexdigest() != source["source_span_sha256"]:
        # The index span hash covers AST-normalized source on some records; keep
        # the authoritative whole-file hash and indexed span hash in the receipt.
        span_check = "INDEXED_SPAN_HASH_RETAINED"
    else:
        span_check = "EXACT"

    task = {
        "id": TASK_ID,
        "lang": "python",
        "spec": "def _as_posix(p: str) -> str: convert a Windows-style path string to POSIX separators by stringifying p and replacing each backslash with a forward slash",
        "tests": r'''def _as_posix_reference(p):
    return str(p).replace("\\", "/")
path = r'C:\Users\Viv\file.py'
actual = _as_posix(path)
reference = _as_posix_reference(path)
assert actual == reference, (actual, reference)
assert actual == 'C:/Users/Viv/file.py', actual
path = 'already/posix'
assert _as_posix(path) == _as_posix_reference(path) == 'already/posix'
path = r'\\server\share'
actual = _as_posix(path)
reference = _as_posix_reference(path)
assert actual == reference, (actual, reference)
assert actual == '//server/share', actual
''',
    }
    result = learner.learn_one(task, domain=source["domain"])
    payload = {
        "schema": "viv_candidate_template_function_trial_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "task_id": TASK_ID,
        "domain": source["domain"],
        "reference_function": source["qualified_name"],
        "reference_catalog": str(source_path),
        "reference_source_file_sha256": source_hash,
        "reference_span_sha256": source["source_span_sha256"],
        "reference_span_check": span_check,
        "template_index_sha256": digest_file(INDEX),
        "candidate_store": str(store.DB_PATH),
        "result": result,
        "promoted_to_live": False,
        "live_topology_write": False,
        "live_memory_write": False,
    }
    payload["receipt_sha256"] = store.canonical_hash(payload)
    target = OUT_DIR / f"template_function_trial_10024_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}_{uuid.uuid4().hex[:8]}.json"
    authorization = store.PrivacyCore().authorize_file_write(str(target))
    if authorization.get("allowed") is not True:
        raise PermissionError(f"PrivacyCore denied trial receipt: {authorization}")
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"receipt": str(target), "result": result,
                      "reference_source_sha256": source_hash,
                      "promoted_to_live": False}, ensure_ascii=False, indent=2), flush=True)
    return 0 if result["state"] in {"RETRIEVED", "ADMITTED_ACTIVE", "ADMITTED_CANDIDATE"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
