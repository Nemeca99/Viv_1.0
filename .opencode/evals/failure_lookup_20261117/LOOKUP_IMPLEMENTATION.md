# Lookup function pass

Implement only lookup_failures in the existing module. Reuse validate_result;
the supervisor corrected it to return the unchanged record or raise ValueError.
The validator passed 37 independent cases and must stay unchanged.

Inputs: result_root and current_source are paths/strings; case is None or an
exact case string; limit defaults to 8. Reject non-int limits (including bool)
and values outside 1..20. Require an existing directory and source file.
Resolved paths must stay on approved drive letters D/E/F/L. Use drive[:1].upper()
and a whitelist of those letters; no forbidden-drive path literal is needed.

Sort direct result_root.glob('result_*.json') paths; no recursion. Raise ValueError
when more than 128 files match. scanned_results is their count, including invalid
files. Compute current_source_sha256 from the source bytes.

For each file, resolve its path and reject escape from the resolved result_root.
Reject size > 1 MiB before reading. Read bytes, compute record_sha256, parse JSON,
and call validate_result. A file error must append {result_path, error} and
continue. Do not silently skip invalid files. Never modify any file.

For each valid record whose source_sha256 equals current_source_sha256, append
{result_path, record_sha256, cases, passed, failed_count} to current_results.
This happens even when case filters the failures.

For every failure whose case matches the optional exact filter, append
{case, exit, expected_accept, output, source_sha256, source_matches_current,
 result_path, record_sha256}. output is the actual recorded string sliced to
500 chars. source_matches_current is a bool comparing the two code hashes.
Keep sorted-file / original-failure order; total_matches counts all matching
failures before truncation. Include historical failures, not only current ones.

Return {schema: 'localcoder_failure_lookup_v1', current_source_sha256,
scanned_results, total_matches, failures, current_results, invalid_results}.
Slice each of the three output arrays to limit only when building the return.
Never invent reasons/resolution/learning; add no CLI or extra functionality yet.
