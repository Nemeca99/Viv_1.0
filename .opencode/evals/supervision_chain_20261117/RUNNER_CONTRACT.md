# Milestone 3: bounded regression workflow

Create `workspace/autonomy/run_composition_audit_regressions_candidate.py`.
Use Python standard library, no model calls, SQLite writes, shell commands, training, or schedules.

The four frozen suites are:
- flags: `.opencode/evals/verify_receipt_flags_20261117.py`, 53 cases, output attribute OUTPUT.
- relays: `.opencode/evals/verify_relay_identity_20261117.py`, 11 cases, output attribute OUT.
- nodes: `.opencode/evals/verify_node_gates_20261117.py`, 32 cases, output attribute OUT.
- circuit: `.opencode/evals/verify_circuit_identity_20261117.py`, 35 cases, output attribute OUT.

Resolve root from this script's location (parents[2]).
Read `.opencode/evals/supervision_chain_20261117/frozen_checkers.json` and verify all four checker hashes BEFORE importing any checker. Paths must be the four fixed paths above.
Refuse Python optimization mode because frozen checks use assertions.
Create one fresh UUID directory under `.opencode/evals/composition_regression_runs/` for each invocation. Never overwrite an earlier run.
Import each fixed suite with importlib.util; change only its output-directory attribute to a fresh suite subdirectory. Do not change TARGET, fixtures, tests, or acceptance logic.
Call its main(), capturing stdout into a suite log. Require status 0 and exactly one result_*.json in that fresh suite directory.
Validate that result has actual integer cases/passed equal to the expected count, failed == [], db_unchanged is True, and source_sha256 equals the actual audit source hash.
Hash the audit source and real candidate database before/after the whole run; require both unchanged.
Stop at the first failure or exception; preserve logs, suite artifacts, and the final report.
Write run_result.json with schema localcoder_composition_regressions_v1, ok boolean, source/database hashes, suite summaries, and any error. Print its path and an honest result. Exit 0 only for all four successful suites and unchanged source/database; otherwise exit 1.

This runs 131 behavior cases once. It records evidence, not learning, promotion, permission, or a daemon.
