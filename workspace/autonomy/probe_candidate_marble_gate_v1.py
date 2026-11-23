"""Measure both Architect-provided initializations without touching Viv state."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
sys.path[:0] = [str(WORKSPACE), str(HERE)]

import candidate_marble_gate_v1 as model
from aios_rebuild.privacy_core.privacy_core import PrivacyCore

OUT_DIR = HERE / "learning" / "neural_runs"


def main() -> int:
    source_path = Path(model.__file__).resolve()
    source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    variants = []
    for label, net, limit in (
        ("seed_7_random_modes", model.MarbleGateNetwork(seed=7), 24),
        ("all_xor_start", model.MarbleGateNetwork(force_xor=True), 49),
    ):
        result = model.train_contract(net, limit)
        variants.append({"label": label, "initial_modes": net.initial_modes,
                         "converged": result["converged"], "epochs": result["epochs"],
                         "final_modes": net.export_canonical_crystal(),
                         "history": result["history"]})
    payload = {
        "schema": "viv_candidate_marble_gate_probe_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_sha256": source_hash,
        "contract": {"truth_table": [[*inputs, out] for inputs, out in model.CONTRACT.items()],
                     "description": "output is 1 exactly when A=1, B=0, C=1"},
        "variants": variants,
        "sqlite_admission": "deferred_until_full_truth_table_gate_passes",
        "live_viv_modified": False,
    }
    payload["receipt_sha256"] = hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    target = OUT_DIR / "candidate_marble_gate_probe_v1.json"
    privacy = PrivacyCore()
    authorization = privacy.authorize_file_write(str(target))
    if authorization.get("allowed") is not True:
        raise PermissionError(f"PrivacyCore denied probe receipt: {authorization}")
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"receipt": str(target),
                      "variants": [{k: v[k] for k in ("label", "initial_modes", "converged", "epochs", "final_modes")}
                                   for v in variants],
                      "live_viv_modified": False}, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
