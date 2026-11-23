"""Admit the repaired all-XOR-to-contract integer network after the Docker gate."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import uuid

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
sys.path[:0] = [str(WORKSPACE), str(HERE)]

import candidate_marble_gate_v3 as model
import candidate_verified_function_store as store

OUT_DIR = HERE / "learning" / "neural_runs"
TASK_ID = "candidate_marble_gate_xor_to_target_v3"
CONTRACT = {
    "description": "output is 1 exactly when A=1, B=0, C=1",
    "truth_table": [[*inputs, output] for inputs, output in model.CONTRACT.items()],
    "gate_modes": model.ReversibleLogicGate.MODES,
    "network_shape": "3 inputs, two overlapping hidden gates, one output gate",
}
TESTS = r'''network = MarbleGateNetwork(force_xor=True)
initial_modes = network.export_canonical_crystal()
assert initial_modes == (4, 4, 4)
assert network.contract_loss() > 0
result = train_contract(network, 49)
assert result["converged"]
assert result["epochs"] == 1
assert network.export_canonical_crystal() != initial_modes
assert all(network.forward(*inputs) == expected for inputs, expected in CONTRACT.items())
assert network.contract_loss() == 0
'''


def main() -> int:
    source_path = Path(model.__file__).resolve()
    source = source_path.read_text(encoding="utf-8")
    source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    network = model.MarbleGateNetwork(force_xor=True)
    initial_modes = network.export_canonical_crystal()
    initial_loss = network.contract_loss()
    run = model.train_contract(network, 49)
    final_modes = network.export_canonical_crystal()
    final_pass = all(network.forward(*inputs) == expected
                     for inputs, expected in model.CONTRACT.items())
    if not (initial_modes == (4, 4, 4) and initial_loss > 0
            and run["converged"] and final_pass and final_modes != initial_modes):
        raise RuntimeError("ALL_XOR_LEARNING_PRECHECK_FAILED")

    admission = store.admit_integer_network(
        task_id=TASK_ID, network_name="marble_gate_3bit_boolean_v3",
        contract=CONTRACT, mode_indices=final_modes, code=source, tests=TESTS,
        source_path=str(source_path), source_sha256=source_hash,
    )
    active = store.get_active_integer_network("marble_gate_3bit_boolean_v3", CONTRACT)
    payload = {
        "schema": "viv_candidate_marble_gate_admission_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "task_id": TASK_ID,
        "candidate_db": str(store.DB_PATH),
        "contract": CONTRACT,
        "initial_modes": initial_modes,
        "initial_truth_table_errors": initial_loss,
        "trained_epochs": run["epochs"],
        "training_history": run["history"],
        "final_modes": final_modes,
        "final_truth_table_pass": final_pass,
        "gate_admission": admission,
        "active_candidate_state": active,
        "live_viv_modified": False,
        "live_topology_write": False,
        "live_memory_write": False,
        "promoted": False,
    }
    payload["receipt_sha256"] = store.canonical_hash(payload)
    target = OUT_DIR / f"candidate_marble_gate_admission_v3_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}_{uuid.uuid4().hex[:8]}.json"
    authorization = store.PrivacyCore().authorize_file_write(str(target))
    if authorization.get("allowed") is not True:
        raise PermissionError(f"PrivacyCore denied admission receipt: {authorization}")
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"receipt": str(target), "initial_modes": initial_modes,
                      "initial_errors": initial_loss, "final_modes": final_modes,
                      "epochs": run["epochs"], "gate_decision": admission["decision"],
                      "db_version_id": admission["version_id"],
                      "active_state": active, "live_viv_modified": False},
                     ensure_ascii=False, indent=2), flush=True)
    return 0 if admission["decision"] == "ALLOW" else 1


if __name__ == "__main__":
    raise SystemExit(main())
