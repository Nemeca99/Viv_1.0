"""Bounded recovery candidate using the original learner and frozen comparisons."""
import copy
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE / "INN"))
from inn.cli import probe_learned
from inn.engine import Simulation, StabilizedSourceEngine
from inn.farm import Farm
from autonomy.inn_hive import _atomic_json


def main():
    state_path = WORKSPACE / "autonomy" / "inn_hive_state.json"
    state = json.loads(state_path.read_text())
    pointer = WORKSPACE / "INN" / "latest-learned-policy.json"
    parent_state = json.loads(pointer.read_text())["engine"]
    config = copy.deepcopy(state["config"])
    engine = StabilizedSourceEngine(copy.deepcopy(config), parent_state)
    engine.config.update(learningAlpha=0.005, epsilonMin=0.0)
    with Farm() as farm:
        simulation = Simulation(farm, engine, None, seed=1)
        simulation.r["epsilon"] = 0.0
        for _ in range(10000):
            simulation.step()
    engine.config = copy.deepcopy(config)
    parent = StabilizedSourceEngine(copy.deepcopy(config), parent_state)
    comparisons = [{"steps": n, "candidate": probe_learned(engine, config, steps=n),
                    "parent": probe_learned(parent, config, steps=n)}
                   for n in (1000, 3000, 10000)]
    passed = all(row["candidate"]["score"] > row["parent"]["score"]
                 and row["candidate"]["decays"] <= row["parent"]["decays"]
                 for row in comparisons)
    receipt = {"at_utc": datetime.now(timezone.utc).isoformat(), "passed": passed,
               "parent_sha256": hashlib.sha256(pointer.read_bytes()).hexdigest(),
               "comparisons": comparisons,
               "scope": "original farm TD learner recovery; not language or model-teacher distillation proof",
               "training": {"steps": 10000, "learningAlpha": 0.005, "epsilon": 0.0}}
    _atomic_json(WORKSPACE / "autonomy" / "learning" / "recovery_evaluation.json", receipt)
    if passed:
        _atomic_json(WORKSPACE / "autonomy" / "learning" / "verified_recovery_policy.json",
                     {"engine": engine.state(), "receipt": receipt})
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
