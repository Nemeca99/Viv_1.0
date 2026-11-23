"""Enumerate 6^3 integer gate states and measure their 3-input truth-table capacity."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import itertools
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
sys.path[:0] = [str(WORKSPACE), str(HERE)]
import candidate_marble_gate_v3 as model
from aios_rebuild.privacy_core.privacy_core import PrivacyCore

OUT = HERE / "learning" / "neural_runs" / "candidate_marble_gate_capacity_v1.json"
INPUTS = list(itertools.product((0, 1), repeat=3))


def main() -> int:
    implementations: dict[tuple[int, ...], list[tuple[int, int, int]]] = {}
    target = tuple(model.CONTRACT[inputs] for inputs in INPUTS)
    for state in itertools.product(range(6), repeat=3):
        net = model.MarbleGateNetwork()
        net.g_h1.mode_idx, net.g_h2.mode_idx, net.g_out.mode_idx = state
        truth = tuple(net.forward(*inputs) for inputs in INPUTS)
        implementations.setdefault(truth, []).append(state)
    target_states = implementations.get(target, [])
    payload = {
        "schema": "viv_candidate_marble_gate_capacity_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_sha256": hashlib.sha256(Path(model.__file__).read_bytes()).hexdigest(),
        "mode_count_per_gate": len(model.ReversibleLogicGate.MODES),
        "gate_count": 3,
        "state_tuple_count": 6 ** 3,
        "possible_three_input_boolean_contracts": 2 ** (2 ** 3),
        "distinct_truth_tables_representable": len(implementations),
        "unrepresentable_truth_table_count": 2 ** 8 - len(implementations),
        "target_contract": [[*inputs, output] for inputs, output in zip(INPUTS, target)],
        "target_contract_representable": bool(target_states),
        "target_mode_tuple_count": len(target_states),
        "target_mode_tuples": target_states,
        "candidate_db_mutated": False,
        "live_viv_modified": False,
    }
    payload["receipt_sha256"] = hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    authorization = PrivacyCore().authorize_file_write(str(OUT))
    if authorization.get("allowed") is not True:
        raise PermissionError(f"PrivacyCore denied capacity receipt: {authorization}")
    with OUT.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: payload[k] for k in (
        "receipt_sha256", "state_tuple_count", "possible_three_input_boolean_contracts",
        "distinct_truth_tables_representable", "unrepresentable_truth_table_count",
        "target_mode_tuple_count", "target_mode_tuples")}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
