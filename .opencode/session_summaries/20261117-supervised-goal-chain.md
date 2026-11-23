# 2026-11-17 Supervised Goal Chain

## Node-gate validation
Check 6 rejects malformed nodes and gates unless status is ALLOW and output is a string: 32/32 cases pass. Viv wrote guards; Codex restored status/output checks lost in a later patch.

## Database/entry identity binding
The large Drone SQL draft was rejected and the verified parent restored. Viv then wrote `composition_node_identity_candidate.py`. Codex corrected strict types, copied its comparator into the audit, and added read-only SQL/version/endpoint/order binding in Check 6: 35/35 cases pass. This compares recorded identities; relay-key hashing remains in Check 7.

## Reusable runner
Viv supplied the suite list, hash helper and result validator. Codex repaired orchestration. All 131 cases and six workflow controls pass. Viv's fresh receipt: `.opencode/evals/composition_regression_runs/69a1020fe4e5448db6ed1b407089f2f7/run_result.json`.

Failed drafts and Viv's original handoff are preserved. Codex corrected this summary's rejected-draft claims. Historical evidence only; no learning, promotion or new authorization.
