"""composition_suite_result_candidate.py — pure result validator."""


def valid_suite_result(record: dict, expected_count: int, source_sha256: str) -> bool:
    """Validate a suite result record against schema and counts.

    Returns True only if all checks pass; False otherwise.
    No I/O, imports with side effects, prints, or main block.
    """
    # Require record to be a dict
    if not isinstance(record, dict):
        return False

    # Required keys must exist
    required_keys = ("cases", "passed", "failed", "db_unchanged", "source_sha256")
    for key in required_keys:
        if key not in record:
            return False

    # Require expected_count to be int and positive
    if not isinstance(expected_count, int) or expected_count <= 0:
        return False

    # Verify cases and passed are int, equal to each other, and equal to expected_count
    cases = record.get("cases")
    passed = record.get("passed")

    if not isinstance(cases, int) or not isinstance(passed, int):
        return False
    if cases != passed:
        return False
    if cases != expected_count:
        return False

    # Require failed to be an empty list
    failed = record.get("failed")
    if not isinstance(failed, list) or len(failed) != 0:
        return False

    # Require db_unchanged to be exactly True
    if record.get("db_unchanged") is not True:
        return False

    # Require source_sha256 to be a string equal to the provided hash
    record_hash = record.get("source_sha256")
    if not isinstance(record_hash, str) or record_hash != source_sha256:
        return False

    return True
