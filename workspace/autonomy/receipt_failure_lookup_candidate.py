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


def lookup_failures(result_root, current_source, case: str | None = None, limit: int = 8) -> dict:
    """Retrieve observed receipt failures and source associations without writes."""
    # Validate inputs
    if type(limit) is not int or limit < 1 or limit > 20:
        raise ValueError(f"limit must be an integer in 1..20, got {type(limit)}")

    result_root_path = Path(result_root).expanduser().resolve()
    current_source_path = None
    current_source_sha256 = None

    if current_source is None:
        raise ValueError("current_source_required")
    if current_source is not None:
        current_source_path = Path(current_source).expanduser().resolve()
        # Check drive letter and whitelist D/E/F/L
        if current_source_path.drive[:1].upper() not in ("D", "E", "F", "L"):
            raise ValueError(f"current_source path on forbidden drive: {current_source_path.drive}")

        try:
            with open(current_source_path, "rb") as f:
                source_bytes = f.read()
            current_source_sha256 = hashlib.sha256(source_bytes).hexdigest()
        except Exception as e:
            raise ValueError(f"Cannot read current source file: {e}")

    # Validate result_root is a directory on approved drive
    if result_root_path.drive[:1].upper() not in ("D", "E", "F", "L"):
        raise ValueError(f"result_root path on forbidden drive: {result_root_path.drive}")
    if not result_root_path.is_dir():
        raise ValueError(f"Not a directory: {result_root_path}")

    # Glob and sort result files, no recursion
    try:
        raw_files = list(result_root_path.glob("result_*.json"))
    except Exception as e:
        raise ValueError(f"Cannot glob result files in {result_root}: {e}")

    if len(raw_files) > 128:
        raise ValueError(f"Too many result files ({len(raw_files)}), max is 128")

    # Sort by filename for deterministic order
    sorted_files = sorted(raw_files, key=lambda p: p.name)

    invalid_results_list = []
    total_matches_before_truncation = 0
    failures_rows = []
    current_result_rows = []

    for result_file in sorted_files:
        # Resolve and check escape from result_root
        try:
            resolved_path = result_file.resolve()
            if not resolved_path.is_relative_to(result_root_path):
                raise ValueError(f"Path escapes result root: {resolved_path}")
        except Exception as e:
            invalid_results_list.append({"result_path": str(result_file), "error": f"path resolution error: {e}"})
            continue

        # Check file size before reading (1 MiB = 1_048_576 bytes)
        try:
            file_size = result_file.stat().st_size
            if file_size > 1_048_576:
                invalid_results_list.append({"result_path": str(result_file), "error": f"file size exceeds 1 MiB ({file_size})"})
                continue
        except Exception as e:
            invalid_results_list.append({"result_path": str(result_file), "error": f"stat error: {e}"})
            continue

        # Read bytes and compute record SHA-256
        try:
            with open(result_file, "rb") as f:
                file_bytes = f.read(1_048_577)
            if len(file_bytes) > 1_048_576:
                raise ValueError("result_exceeds_1_mib")
            record_sha256 = hashlib.sha256(file_bytes).hexdigest()
        except Exception as e:
            invalid_results_list.append({"result_path": str(result_file), "error": f"read error: {e}"})
            continue

        # Parse JSON
        try:
            doc = json.loads(file_bytes.decode("utf-8"))
        except Exception as e:
            invalid_results_list.append({"result_path": str(result_file), "error": f"JSON parse error: {e}"})
            continue

        # Validate record structure
        try:
            validate_result(doc)
        except ValueError as error:
            invalid_results_list.append({"result_path": str(result_file), "error": str(error)})
            continue

        # Compute current_source_sha256 comparison for this file
        source_matches_current = doc["source_sha256"] == current_source_sha256

        # Build failure rows (case filter applied later)
        failures_list = doc.get("failed", [])
        for fail in failures_list:
            row_entry = {
                "case": fail["case"],
                "exit": fail["exit"],
                "expected_accept": fail["expected_accept"],
                "output": fail["output"][:500] if len(fail["output"]) > 500 else fail["output"],
                "source_sha256": doc["source_sha256"],
                "source_matches_current": source_matches_current,
                "result_path": str(result_file),
                "record_sha256": record_sha256,
            }

            # Apply case filter if provided
            if case is not None:
                if fail["case"] == case:
                    failures_rows.append(row_entry)
                    total_matches_before_truncation += 1
                else:
                    # The current result summary is independent of this filter.
                    pass
            else:
                failures_rows.append(row_entry)
                total_matches_before_truncation += 1

        # Build current_result_row for this file (even if no matching case)
        failed_count = len(doc.get("failed", []))
        if source_matches_current:
            current_result_rows.append({
                "result_path": str(result_file),
                "record_sha256": record_sha256,
                "cases": doc["cases"],
                "passed": doc["passed"],
                "failed_count": failed_count,
            })

    # Slice arrays to limit when building return dict
    failures = failures_rows[:limit] if len(failures_rows) > limit else failures_rows
    current_results = current_result_rows[:limit] if len(current_result_rows) > limit else current_result_rows
    invalid_results = invalid_results_list[:limit] if len(invalid_results_list) > limit else invalid_results_list

    return {
        "schema": "localcoder_failure_lookup_v1",
        "current_source_sha256": current_source_sha256,
        "scanned_results": len(sorted_files),
        "total_matches": total_matches_before_truncation,
        "failures": failures,
        "current_results": current_results,
        "invalid_results": invalid_results,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="receipt_failure_lookup_candidate")
    parser.add_argument("--root", type=str, default=Path(__file__).resolve().parents[2] / ".opencode/evals/receipt_flags_20261117")
    parser.add_argument("--source", type=str, default=Path(__file__).with_name("typed_composition_receipt_audit_v2_candidate.py"))
    parser.add_argument("--case", type=str, default=None)
    parser.add_argument("--limit", type=int, default=8)

    args = parser.parse_args(argv)

    try:
        result = lookup_failures(
            result_root=args.root,
            current_source=args.source,
            case=args.case,
            limit=args.limit,
        )
        print(json.dumps(result))
        return 0
    except Exception as e:
        error_obj = {"error": str(e)} if isinstance(e, ValueError) else {"error": f"{type(e).__name__}: {e}"}
        print(json.dumps(error_obj))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
