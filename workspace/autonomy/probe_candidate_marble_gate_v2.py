"""Deterministic 100-seed check: separate lucky initialization from actual learning."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
sys.path[:0] = [str(WORKSPACE), str(HERE)]
import candidate_marble_gate_v1 as model
from aios_rebuild.privacy_core.privacy_core import PrivacyCore

OUT = HERE / "learning" / "neural_runs" / "candidate_marble_gate_seed_sweep_v2.json"


def table_pass(net: model.MarbleGateNetwork) -> bool:
    return all(net.forward(*inputs) == expected
               for inputs, expected in model.CONTRACT.items())


def main() -> int:
    source = Path(model.__file__).resolve()
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    rows = []
    for seed in range(100):
        net = model.MarbleGateNetwork(seed=seed)
        initial = net.export_canonical_crystal()
        initially_passes = table_pass(net)
        result = model.train_contract(net, 24)
        final = net.export_canonical_crystal()
        changed = sum(a != b for a, b in zip(initial, final))
        rows.append({"seed": seed, "initial_modes": initial,
                     "initial_table_pass": initially_passes,
                     "converged": result["converged"],
                     "convergence_counts_as_learning": bool(result["converged"] and not initially_passes),
                     "epochs": result["epochs"], "final_modes": final,
                     "changed_gate_count": changed})
    xor_net = model.MarbleGateNetwork(force_xor=True)
    xor_start = xor_net.export_canonical_crystal()
    xor_result = model.train_contract(xor_net, 49)
    payload = {
        "schema": "viv_candidate_marble_gate_seed_sweep_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "algorithm_source_sha256": source_hash,
        "contract_sha256": hashlib.sha256(json.dumps(
            [[*inputs, output] for inputs, output in model.CONTRACT.items()],
            separators=(",", ":")).encode()).hexdigest(),
        "sweep_seeds": 100,
        "initial_pass_count": sum(row["initial_table_pass"] for row in rows),
        "eventual_pass_count": sum(row["converged"] for row in rows),
        "learned_from_initial_failure_count": sum(row["convergence_counts_as_learning"] for row in rows),
        "seed_rows": rows,
        "xor_control": {"initial_modes": xor_start,
                        "initial_table_pass": table_pass(model.MarbleGateNetwork(force_xor=True)),
                        "converged": xor_result["converged"],
                        "epochs": xor_result["epochs"],
                        "final_modes": xor_net.export_canonical_crystal()},
        "candidate_db_admission": "none; only initial-pass random cases found so far are not learning evidence",
        "live_viv_modified": False,
    }
    payload["receipt_sha256"] = hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    auth = PrivacyCore().authorize_file_write(str(OUT))
    if auth.get("allowed") is not True:
        raise PermissionError(f"PrivacyCore denied seed sweep receipt: {auth}")
    with OUT.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"receipt": str(OUT),
                      "seeds": 100,
                      "initial_pass": payload["initial_pass_count"],
                      "eventual_pass": payload["eventual_pass_count"],
                      "learned_from_wrong_start": payload["learned_from_initial_failure_count"],
                      "all_xor": payload["xor_control"],
                      "live_viv_modified": False}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
