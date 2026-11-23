# 20261117 failure lookup supervision

Goal: verify localcoder_failure_lookup adapter against frozen CLI tests and query historical failures. Implementation used Python stdlib only, V2 Plugin.define export, strict validation (case minLength/maxLength 1..120, limit 1..20), synchronous execFileSync import, and schema guard for localcoder_failure_lookup_v1.

Python draft: receipt_failure_lookup_candidate.py with validate_result and lookup_failures body; CLI entry point argparse --root/--source/--case/--limit. OpenCode adapter: .opencode/evals/failure_lookup_20261117/localcoder-failure-lookup.candidate.ts with top-level execFileSync import, synchronous execute, strict input validation, schema guard.

Supervisor repairs: Codex fixed validator API/types, missing dependencies, CLI defaults/argv, and V2 adapter registration, import, binary/argv, input validation and schema checks. The 53/53 receipt is saved verification for the current source. No fresh reproduction test was performed by the lookup. Historical failures are associated with different source hashes; their reproducibility is untested. Codex corrected this summary after Viv repeated an unsupported reproducibility claim.

Observed: localcoder_failure_lookup returned two historical failures for case "valid" where recorded source SHA-256 does not match current source (source_matches_current: false). Both failed receipts have exit code 1 and expected_accept true, indicating they should have passed but did not under their respective source versions. The current_results shows one valid receipt with all 53 cases passing. No invalid results were found in the current scan.

Limitation: this is retrieval of evidence rather than model-weight learning; failed attempts are preserved in .opencode/evals/failure_lookup_20261117/. Empty historical output records no failure cause.
