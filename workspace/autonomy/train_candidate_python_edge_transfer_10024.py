"""Train candidate epoch 10024 from fresh gate-accepted Python edge cases."""
from pathlib import Path
import train_candidate_python_increment_10017 as experiment

RUNS = Path(__file__).resolve().parent / "learning" / "deepseek_candidate_runs"
ROOT = Path(r"F:\LocalCoder_Archive\Viv_model_candidates")
experiment.curriculum.CURRICULUM = experiment.curriculum.EDGE_TRANSFER_CURRICULUM
experiment.EXPECTED_EXAMPLES = 8
experiment.PARENT = ROOT / "epoch_10016"
experiment.DEST = ROOT / "epoch_10024"
experiment.PREFLIGHT_OUT = RUNS / "candidate_python_preflight_10024_retry1.json"
experiment.DATA_OUT = RUNS / "candidate_python_training_10024_retry1.json"
experiment.RUN_OUT = RUNS / "candidate_python_training_run_10024_retry1.json"
experiment.EXCLUDED_PRIOR_DATASETS = {RUNS / "candidate_python_training_10024.json"}
experiment.SEED = 20261145
experiment.LEARNING_RATE = 5e-7
experiment.STEPS = 24
experiment.EPOCH = 10024


if __name__ == "__main__":
    raise SystemExit(experiment.main())
