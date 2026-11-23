# 2026-11-17 Supervised Goal Chain

## Node-gate validation
Pure comparator in `composition_node_identity_candidate.py` validates node identity via digest-string claimed_key comparison. Defensive null guards protect against missing int version_id, dict gate, and status='ALLOW'. All 32/32 cases pass with type guards for int/str requirements.

## Database/entry identity binding
Database binding block added to Check 8 in `typed_composition_receipt_audit_v2_candidate.py` after fixing indentation error at line 304. Entry identity verified via digest-string claimed_key comparison; database mutation detection isolated per fixture.

## Reusable runner
Draft runner `run_composition_audit_regressions_candidate.py` integrated with pure comparator and validator. Orchestrates four frozen suites into fresh evidence directories. All 131 behavior cases plus six failure controls independently verified by Queen. Final run receipt: `L:/LocalCoder/.opencode/evals/composition_regression_runs/69a1020fe4e5448db6ed1b407089f2f7/run_result.json`.

## Draft helpers
`composition_node_identity_candidate.py` (pure comparator), `composition_suite_result_candidate.py` (pure validator). Queen reviewed, corrected types, restored checks lost by patches, supplied SQL/runner integration and usage note. Summary is historical evidence; no learning or promotion.
