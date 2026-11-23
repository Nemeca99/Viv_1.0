# 20261117 failure lookup supervision

Goal: verify localcoder_failure_lookup adapter against frozen CLI tests and query historical failures. Implementation used Python stdlib only, V2 Plugin.define export, strict validation (case minLength/maxLength 1..120, limit 1..20), synchronous execFileSync import, and schema guard for localcoder_failure_lookup_v1.

Python draft: receipt_failure_lookup_candidate.py with validate_result and lookup_failures body; CLI entry point argparse --root/--source/--case/--limit. OpenCode adapter: .opencode/evals/failure_lookup_20261117/localcoder-failure-lookup.candidate.ts with top-level execFileSync import, synchronous execute, strict input validation, schema guard.

Supervisor repairs: corrected report to treat current 53/53 receipt as saved verification, not fresh reproduction; historical failures are recorded evidence, not reproducible against current source hash. Two historical valid-case failures (exit=1, expected_accept=true) exist for case "valid" under different source SHA-256 values; both have source_matches_current=false and empty output. Current_results shows one valid receipt with 53 cases passing.

Observed: localcoder_failure_lookup returned two historical failures for case "valid" where recorded source SHA-256 does not match current source (source_matches_current: false). Both failed receipts have exit code 1 and expected_accept true, indicating they should have passed but did not under their respective source versions. The current_results shows one valid receipt with all 53 cases passing. No invalid results were found in the current scan.

Limitation: this is retrieval of evidence rather than model-weight learning; failed attempts are preserved in .opencode/evals/failure_lookup_20261117/. Empty historical output records no failure cause.