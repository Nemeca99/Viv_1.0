"""Verify a complete source-derived candidate with declared transformations."""

from __future__ import annotations

import hashlib
import json
import warnings
from pathlib import Path
from typing import Any


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(manifest_path: Path, candidate: Path, transform_receipt_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    transform = json.loads(transform_receipt_path.read_text(encoding="utf-8"))
    if transform.get("status") != "PASS" or transform.get("source_modified") is not False:
        raise ValueError("vendor normalization receipt is not an immutable-source PASS")
    if transform.get("receipt_sha256") != hashlib.sha256(
        json.dumps({k: v for k, v in transform.items() if k != "receipt_sha256"},
                   ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest():
        raise ValueError("vendor normalization receipt digest mismatch")
    rows = manifest["files"]
    declared = {row["path"]: row for row in transform["transforms"]}
    if len(declared) != len(transform["transforms"]):
        raise ValueError("duplicate transform path")
    by_source = {row["path"]: row["sha256"] for row in rows}
    mismatches: list[dict[str, str]] = []
    missing: list[str] = []
    for rel, row in by_source.items():
        path = candidate / Path(rel)
        if not path.is_file():
            missing.append(rel)
            continue
        expected_source = row
        transformed = declared.get(rel)
        if transformed:
            if transformed.get("source_sha256") != expected_source:
                mismatches.append({"path": rel, "kind": "transform_source_hash"})
            expected = transformed["after_candidate_sha256"]
        else:
            expected = expected_source
        if sha(path) != expected:
            mismatches.append({"path": rel, "kind": "candidate_hash"})
    actual = {p.relative_to(candidate).as_posix() for p in candidate.rglob("*") if p.is_file()}
    unexpected = sorted(actual - set(by_source))
    compile_exclusions = {row["path"]: row["reason"] for row in transform["compile_exclusions"]}
    syntax_errors: list[dict[str, str]] = []
    syntax_warnings: list[dict[str, str]] = []
    checked = 0
    for rel in by_source:
        if not rel.endswith(".py") or rel in compile_exclusions:
            continue
        checked += 1
        path = candidate / Path(rel)
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", SyntaxWarning)
                compile(path.read_text(encoding="utf-8"), str(path), "exec", dont_inherit=True)
            syntax_warnings.extend({"path": rel, "warning": str(w.message)} for w in caught)
        except (OSError, UnicodeError, SyntaxError) as error:
            syntax_errors.append({"path": rel, "error": str(error)})
    passed = not (mismatches or missing or unexpected or syntax_errors)
    receipt = {
        "schema": "aios_derived_candidate_verification_v1",
        "status": "PASS" if passed else "HOLD",
        "source_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "transform_receipt_sha256": transform["receipt_sha256"],
        "catalogued_file_count": len(rows),
        "candidate_file_count": len(actual),
        "source_modified": False,
        "source_code_executed": False,
        "candidate_executed": False,
        "transformed_file_count": len(declared),
        "compile_exclusion_count": len(compile_exclusions),
        "python_syntax_checked": checked,
        "python_syntax_error_count": len(syntax_errors),
        "python_syntax_errors": syntax_errors,
        "python_syntax_warning_count": len(syntax_warnings),
        "python_syntax_warnings": syntax_warnings,
        "missing_files": missing,
        "unexpected_files": unexpected,
        "hash_mismatches": mismatches,
    }
    return receipt


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--transform-receipt", required=True, type=Path)
    args = parser.parse_args()
    result = verify(args.manifest, args.candidate, args.transform_receipt)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["status"] == "PASS" else 1)
