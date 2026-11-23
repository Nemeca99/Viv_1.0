"""Candidate receipt lookup; implementation is delegated to Viv/Drone."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re


def validate_result(record: dict) -> bool:
    """Validate record structure and constraints; return True if valid, else False. Never mutate inputs."""
    # Must be a dict
    if not isinstance(record, dict):
        return False

    # Required top-level keys
    required_keys = {"source_sha256", "cases", "passed", "db_unchanged", "failed"}
    if not all(k in record for k in required_keys):
        return False

    # source_sha256: 64 lowercase hex chars
    sha = record["source_sha256"]
    if not isinstance(sha, str) or len(sha) != 64 or not re.fullmatch(r"[0-9a-f]{64}", sha):
        return False

    # cases > 0 and passed in 0..cases (both ints)
    try:
        cases = int(record["cases"])
        passed = int(record["passed"])
    except Exception:
        return False
    if cases <= 0 or not isinstance(passed, int) or passed < 0 or passed > cases:
        return False

    # db_unchanged must be exactly True (bool type)
    if record["db_unchanged"] is not True:
        return False

    # failed list length equals cases - passed
    failed_list = record.get("failed", [])
    expected_failed_count = cases - passed
    if len(failed_list) != expected_failed_count or not isinstance(failed_list, list):
        return False

    # Validate each failure entry
    seen_case_names: set[str] = set()
    for i, fail in enumerate(failed_list):
        # Each must be a dict with required keys
        if not isinstance(fail, dict) or not all(k in fail for k in ("case", "exit", "expected_accept", "matched", "output")):
            return False

        # case: nonempty string
        if not isinstance(fail["case"], str) or fail["case"] == "":
            return False
        if fail["case"] in seen_case_names:
            return False
        seen_case_names.add(fail["case"])

        # exit: actual int
        if not isinstance(fail["exit"], int):
            return False

        # expected_accept: exactly True or False (bool)
        if fail["expected_accept"] is not bool:
            return False

        # matched: exactly False (bool)
        if fail["matched"] != False:
            return False

        # output: string
        if not isinstance(fail["output"], str):
            return False

    return True


def lookup_failures(result_root, current_source, case=None, limit=8):
    """Retrieve observed receipt failures and source associations without writes."""
    raise NotImplementedError('lookup_failures')
