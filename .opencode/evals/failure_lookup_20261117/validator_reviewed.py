"""Candidate receipt lookup; implementation is delegated to Viv/Drone."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re


def validate_result(record: dict) -> dict:
    """Return a valid record unchanged, otherwise raise ValueError."""
    # Must be a dict
    if not isinstance(record, dict):
        raise ValueError("record_not_object")

    # Required top-level keys
    required_keys = {"source_sha256", "cases", "passed", "db_unchanged", "failed"}
    if not all(k in record for k in required_keys):
        raise ValueError("required_fields_missing")

    # source_sha256: 64 lowercase hex chars
    sha = record["source_sha256"]
    if not isinstance(sha, str) or len(sha) != 64 or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise ValueError("invalid_source_sha256")

    # cases > 0 and passed in 0..cases (both ints)
    cases, passed = record["cases"], record["passed"]
    if type(cases) is not int or type(passed) is not int or cases <= 0 or passed < 0 or passed > cases:
        raise ValueError("invalid_counts")

    # db_unchanged must be exactly True (bool type)
    if record["db_unchanged"] is not True:
        raise ValueError("database_changed_or_unverified")

    # failed list length equals cases - passed
    failed_list = record.get("failed", [])
    expected_failed_count = cases - passed
    if not isinstance(failed_list, list) or len(failed_list) != expected_failed_count:
        raise ValueError("invalid_failed_list")

    # Validate each failure entry
    seen_case_names: set[str] = set()
    for i, fail in enumerate(failed_list):
        # Each must be a dict with required keys
        if not isinstance(fail, dict) or not all(k in fail for k in ("case", "exit", "expected_accept", "matched", "output")):
            raise ValueError("invalid_failure_row")

        # case: nonempty string
        if not isinstance(fail["case"], str) or fail["case"] == "":
            raise ValueError("invalid_case")
        if fail["case"] in seen_case_names:
            raise ValueError("duplicate_case")
        seen_case_names.add(fail["case"])

        # exit: actual int
        if type(fail["exit"]) is not int:
            raise ValueError("invalid_exit")

        # expected_accept: exactly True or False (bool)
        if type(fail["expected_accept"]) is not bool:
            raise ValueError("invalid_expected_accept")

        # matched: exactly False (bool)
        if fail["matched"] is not False:
            raise ValueError("invalid_matched")

        # output: string
        if not isinstance(fail["output"], str):
            raise ValueError("invalid_output")

    return record


def lookup_failures(result_root, current_source, case=None, limit=8):
    """Retrieve observed receipt failures and source associations without writes."""
    raise NotImplementedError('lookup_failures')
