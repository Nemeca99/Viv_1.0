"""Replay epoch 10020's boundary curriculum at higher LR from epoch 10016."""
from pathlib import Path
import train_candidate_rust_boundary_transfer_10020 as experiment

experiment.EPOCH = 10021
experiment.CHECK_PRIOR_FUNCTION_NAMES = False  # Same verified examples; new task IDs; held-out remains disjoint.
experiment.DEST = experiment.ROOT / "epoch_10021"
experiment.DATA = experiment.RUNS / "candidate_rust_training_10021.json"
experiment.PREFLIGHT = experiment.RUNS / "candidate_rust_preflight_10021.json"
experiment.RECEIPT = experiment.RUNS / "candidate_rust_training_run_10021.json"
experiment.LR = 5e-6

if __name__ == "__main__":
    raise SystemExit(experiment.main())
