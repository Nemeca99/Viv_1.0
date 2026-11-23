"""Read-only verifier for a manifest-complete AIOS candidate tree."""

from __future__ import annotations

import hashlib
import json
import sys
import warnings
from pathlib import Path


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def verify(
    manifest_path: Path, source_root: Path, candidate: Path
) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = manifest["files"]
    expected = {row["path"]: row["sha256"] for row in rows}
    missing: list[str] = []
    mismatched: list[str] = []
    source_changed: list[str] = []
    unexpected: list[str] = []
    syntax_errors: list[dict[str, str]] = []
    syntax_warnings: list[dict[str, str]] = []
    exclusion_rows = manifest.get("compile_exclusions", [])
    if not isinstance(exclusion_rows, list):
        raise ValueError("manifest compile_exclusions must be a list")
    exclusions: dict[str, str] = {}
    for row in exclusion_rows:
        if not isinstance(row, dict):
            raise ValueError("compile exclusion entry must be an object")
        path = row.get("path")
        reason = row.get("reason")
        if (
            not isinstance(path, str)
            or path not in {item["path"] for item in rows}
            or not path.casefold().endswith(".py")
            or not isinstance(reason, str)
            or not reason.strip()
            or path in exclusions
        ):
            raise ValueError("compile exclusion is invalid or not in the manifest")
        exclusions[path] = reason.strip()

    for relative, expected_hash in expected.items():
        src = source_root / relative
        dest = candidate / relative
        if not src.is_file() or not dest.is_file():
            missing.append(relative)
            continue
        if src.is_symlink() or dest.is_symlink():
            mismatched.append(relative)
            continue
        if digest(src) != expected_hash:
            source_changed.append(relative)
        if digest(dest) != expected_hash:
            mismatched.append(relative)
        if dest.suffix.casefold() == ".py" and relative not in exclusions:
            try:
                source = dest.read_text(encoding="utf-8")
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always", SyntaxWarning)
                    compile(source, str(dest), "exec", dont_inherit=True)
                syntax_warnings.extend(
                    {"path": relative, "warning": str(item.message)} for item in caught
                )
            except (OSError, UnicodeError, SyntaxError) as exc:
                syntax_errors.append({"path": relative, "error": str(exc)})

    actual = {
        item.relative_to(candidate).as_posix()
        for item in candidate.rglob("*")
        if item.is_file()
    }
    unexpected = sorted(actual - expected.keys())
    missing = sorted(set(missing) | (expected.keys() - actual))
    passed = not (
        missing or mismatched or source_changed or unexpected or syntax_errors
    )
    return {
        "schema": "aios_full_candidate_verification_v1",
        "status": "PASS" if passed else "HOLD",
        "manifest_file_count": len(rows),
        "candidate_file_count": len(actual),
        "core_count": len(manifest["cores"]),
        "python_syntax_checked": sum(
            name.endswith(".py") and name not in exclusions for name in expected
        ),
        "python_syntax_excluded": exclusions,
        "python_syntax_exclusion_count": len(exclusions),
        "python_syntax_error_count": len(syntax_errors),
        "python_syntax_errors": syntax_errors,
        "python_syntax_warnings": syntax_warnings,
        "missing_files": missing,
        "unexpected_files": unexpected,
        "source_hash_mismatches": source_changed,
        "candidate_hash_mismatches": mismatched,
        "source_modified": False,
        "source_executed": False,
        "candidate_executed": False,
    }


if __name__ == "__main__":
    try:
        result = verify(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        raise SystemExit(0 if result["status"] == "PASS" else 1)
    except Exception as error:  # noqa: BLE001 - command-line verifier emits a clear failure
        print(
            json.dumps(
                {
                    "schema": "aios_full_candidate_verification_v1",
                    "status": "HOLD",
                    "error": f"{type(error).__name__}: {error}",
                }
            )
        )
        raise SystemExit(2)
