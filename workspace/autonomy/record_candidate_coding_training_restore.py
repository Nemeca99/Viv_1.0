"""Record verified recovery after candidate-training quiesce terminated the server."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import urllib.request
from pathlib import Path
import uuid

HERE = Path(__file__).resolve().parent
RUNS = HERE / "learning" / "deepseek_candidate_runs"
TRAINING = RUNS / "candidate_coding_training_10010.json"
LIVE = Path(r"E:\Viv_Sandbox\playground\adapters\epoch_10001")
CANDIDATE = Path(r"F:\LocalCoder_Archive\Viv_model_candidates\epoch_10010")
MEMORY = HERE.parent / "aios_rebuild" / "memory" / "persistent_memory.json"
TOPOLOGY = HERE / "viv_code_topology.sqlite3"
API = "http://127.0.0.1:1234/v1/status"
EXPECTED_LIVE = "905964dd529bc415ba1c46bb41ec5262d813a5e667e289f092c6b25245a01511"
EXPECTED_CANDIDATE = "ea2aaffd0e5c7c35422a9b5b3b4e53a4bb74e10d9719ac21cf185721c7ba8178"
LEARNING_PROOF = RUNS / "candidate_memory_proof_10008.json"

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
    training = json.loads(TRAINING.read_text(encoding="utf-8"))
    if training.get("status") != "TRAINED_CANDIDATE" or training.get("candidate_sha256") != EXPECTED_CANDIDATE:
        raise ValueError("candidate training receipt mismatch")
    learning_proof = json.loads(LEARNING_PROOF.read_text(encoding="utf-8"))
    expected_memory = learning_proof["source_memory_sha256_before_after"]
    expected_topology = learning_proof["topology_sha256_before"]
    if expected_topology != learning_proof["topology_sha256_after"]:
        raise ValueError("prior candidate proof does not show an unchanged topology")
    with urllib.request.urlopen(API, timeout=30) as response:
        status = json.load(response)
    hashes = {"live_adapter": file_hash(LIVE / "adapter_model.safetensors"),
              "candidate_adapter": file_hash(CANDIDATE / "adapter_model.safetensors"),
              "persistent_memory": file_hash(MEMORY), "viv_topology": file_hash(TOPOLOGY)}
    expected = {"live_adapter": EXPECTED_LIVE, "candidate_adapter": EXPECTED_CANDIDATE,
                "persistent_memory": expected_memory, "viv_topology": expected_topology}
    if hashes != expected:
        raise ValueError("verified hashes differ: " + json.dumps({"actual": hashes, "expected": expected}))
    if status.get("status") != "ACTIVE" or status.get("active_adapter") != "epoch_10001":
        raise ValueError("live tutor is not restored: " + json.dumps(status))
    payload = {"schema": "viv_candidate_training_restore_recovery_v1",
               "created_utc": datetime.now(timezone.utc).isoformat(),
               "training_receipt": str(TRAINING),
               "automatic_restore_attempt": training.get("restore_error"),
               "recovery_action": "viv_tutor_server.py started in foreground; original epoch_10001 loaded",
               "live_status": status, "hashes": hashes,
               "promoted": False, "persistent_memory_write": False,
               "viv_topology_write": False}
    payload["receipt_sha256"] = object_hash(payload)
    out = RUNS / f"candidate_coding_training_10010_restore_recovery_{uuid.uuid4().hex[:8]}.json"
    with out.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"receipt": str(out), "live_adapter": status["active_adapter"],
                      "hashes": hashes, "receipt_sha256": payload["receipt_sha256"],
                      "promoted": False}, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
