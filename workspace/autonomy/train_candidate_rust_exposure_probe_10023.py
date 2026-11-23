"""Measure a doubled exposure dose on epoch 10022's gate-accepted Rust examples."""
import train_candidate_rust_structure_transfer_10022 as source

experiment = source.experiment

renamed = []
for name, spec, code, checks in experiment.EXAMPLES:
    replay_name = "dose10023_" + name
    renamed.append((
        replay_name,
        spec.replace(name, replay_name),
        code.replace(name, replay_name),
        checks.replace(name, replay_name),
    ))

experiment.EPOCH = 10023
experiment.CHECK_PRIOR_FUNCTION_NAMES = True
experiment.DEST = experiment.ROOT / "epoch_10023"
experiment.DATA = experiment.RUNS / "candidate_rust_training_10023.json"
experiment.PREFLIGHT = experiment.RUNS / "candidate_rust_preflight_10023.json"
experiment.RECEIPT = experiment.RUNS / "candidate_rust_training_run_10023.json"
experiment.EXAMPLES = renamed
# Keep the training parent and optimizer conditions fixed; double each
# already gate-accepted example's exposure and the resulting bounded steps.
experiment.SEED = 20261143
experiment.LR = 5e-6
experiment.REPEATS = 6
experiment.STEPS = 48


if __name__ == "__main__":
    raise SystemExit(experiment.main())
