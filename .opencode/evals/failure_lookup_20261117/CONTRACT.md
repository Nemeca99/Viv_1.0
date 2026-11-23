# Receipt failure lookup contract

Implement `lookup_failures(result_root, current_source, case=None, limit=8)` in
`workspace/autonomy/receipt_failure_lookup_candidate.py` using Python stdlib.
Paths may be strings or pathlib.Path. This function returns a dict and never writes.

Read only direct children named `result_*.json`, sorted by filename. No recursion.
Resolve file paths and skip links escaping the result root, recording an error.
Reject a missing root/source, C: roots/sources, or a limit that is not an actual
integer in 1..20. At most 128 result files; raise ValueError beyond that bound.
Skip documents larger than 1 MiB and record an error. A malformed document must
be reported in invalid_results, not silently accepted or crash the whole lookup.

For each document require:
- a dict; source_sha256 is 64 lowercase hex characters;
- actual integer cases > 0, actual integer passed in 0..cases;
- db_unchanged is exactly True;
- failed is a list of length cases - passed;
- each failure is a dict with a nonempty string case, actual integer exit,
  boolean expected_accept, matched is exactly False, and string output;
- failure case names are distinct within a document.

Calculate the current source SHA-256 from its bytes. Calculate each result
document's record_sha256 from its original bytes; do not trust filenames.
Return these fields:
- schema: `localcoder_failure_lookup_v1`
- current_source_sha256: computed current source hash
- scanned_results: number of direct result files considered
- total_matches: count of matching failure entries before truncation
- failures: at most limit rows, in sorted-file / original-entry order
- current_results: at most limit valid results whose source hash equals current
- invalid_results: at most limit {result_path, error} objects

Each failure row contains exactly the observed case, exit, expected_accept,
output (at most 500 characters), source_sha256, source_matches_current (bool),
result_path (absolute), and record_sha256. If case is supplied, match it exactly.
Each current_results row contains result_path, record_sha256, cases, passed,
and failed_count. Include current results even when case filters failure rows.

Never invent a reason from a case name. Never claim a case was resolved or
learned: these records describe results and source versions, not training.
Do not replace strict receipt gates. No SQLite, memory writes, subprocesses,
network, model calls, mutation of inputs, or scanning archives/active databases.
The first task is this function only; the CLI and OpenCode tool come later.
