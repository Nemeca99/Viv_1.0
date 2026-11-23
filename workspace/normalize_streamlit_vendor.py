"""Normalize known AIOS-injected Unicode bootstraps in a staged vendor tree.

This only edits a run-scoped candidate. It preserves the F: source and records
both original and resulting file hashes. Deliberately invalid vendor fixtures
and cookiecutter templates are retained and listed as compile exclusions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BOOTSTRAP_PATTERNS = (
    re.compile(
        r"(?ms)^# CRITICAL: Import Unicode safety layer FIRST[^\n]*\n"
        r"import sys\nfrom pathlib import Path\n"
        r"sys\.path\.append\(str\(Path\(__file__\)(?:\.parent)*\)\)\n"
        r"from utils\.unicode_safe_output import setup_unicode_safe_output\n"
        r"setup_unicode_safe_output\(\)\n?"
    ),
    re.compile(
        r"(?ms)^# CRITICAL: Import Unicode safety layer FIRST[^\n]*\n"
        r"from utils_core\.base\.unicode_safety import setup_unicode_safe_output\n"
        r"setup_unicode_safe_output\(\)\n?"
    ),
)
LINK_STUB = re.compile(r"(?s)^#![^\n]*\n\s*\.\./(?:\.\./)+[^\s]+\s*$")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def normalize(
    candidate: Path, source_root: Path, overlays: list[tuple[str, Path]] | None = None
) -> dict[str, Any]:
    vendor = candidate / "streamlit_core"
    if not vendor.is_dir():
        raise FileNotFoundError(f"candidate has no Streamlit vendor root: {vendor}")
    entries: list[dict[str, str]] = []
    compile_exclusions: list[dict[str, str]] = []
    failures: list[dict[str, str]] = []
    for path in sorted(vendor.rglob("*.py")):
        relative = path.relative_to(candidate).as_posix()
        try:
            before = path.read_bytes()
            text = before.decode("utf-8")
            original_source = source_root / Path(relative)
            source_hash = sha(original_source.read_bytes())
            reason = None
            if "{{" in relative or "}}" in relative:
                reason = "cookiecutter_template"
            elif "compilation_error_dialog.py" in relative:
                reason = "intentional_syntax_error_fixture"
            normalized = text.replace("\r\n", "\n")
            did_transform = normalized != text
            for pattern in BOOTSTRAP_PATTERNS:
                normalized, replacements = pattern.subn("", normalized)
                did_transform = did_transform or replacements > 0
            if reason:
                compile_exclusions.append({"path": relative, "reason": reason})
                continue
            if LINK_STUB.fullmatch(normalized):
                filename = Path(normalized.strip().splitlines()[-1]).name
                known = {
                    "animation_demo.py": "animation_demo.py",
                    "mapping_demo.py": "mapping_demo.py",
                    "plotting_demo.py": "plotting_demo.py",
                }
                target_name = known.get(filename)
                target = (
                    candidate / "streamlit_core" / "streamlit_main" / "lib"
                    / "streamlit" / "hello" / target_name
                    if target_name
                    else None
                )
                if target is None or not target.is_file():
                    failures.append({"path": relative, "error": "unresolved relative source link"})
                    continue
                linked = target.read_bytes().decode("utf-8").replace("\r\n", "\n")
                normalized = linked
                for pattern in BOOTSTRAP_PATTERNS:
                    normalized = pattern.sub("", normalized)
                after = normalized.encode("utf-8")
                path.write_bytes(after)
                entries.append({
                    "path": relative,
                    "source_sha256": source_hash,
                    "before_candidate_sha256": sha(before),
                    "after_candidate_sha256": sha(after),
                    "transform": f"materialized_verified_local_link:{target.relative_to(candidate).as_posix()}",
                })
                continue
            after = normalized.encode("utf-8")
            if did_transform:
                path.write_bytes(after)
                entries.append({
                    "path": relative,
                    "source_sha256": source_hash,
                    "before_candidate_sha256": sha(before),
                    "after_candidate_sha256": sha(after),
                    "transform": "remove_nonstandard_unicode_bootstrap_from_vendor_source",
                })
        except Exception as error:  # record every failure for candidate admission
            failures.append({"path": relative, "error": f"{type(error).__name__}: {error}"})
    for relative, overlay_path in overlays or []:
        target = candidate / Path(relative)
        original = source_root / Path(relative)
        if not target.is_file() or not original.is_file() or not overlay_path.is_file():
            failures.append({"path": relative, "error": "overlay input or target missing"})
            continue
        before = target.read_bytes()
        replacement = overlay_path.read_bytes()
        if before == replacement:
            failures.append({"path": relative, "error": "overlay did not change candidate"})
            continue
        target.write_bytes(replacement)
        entries.append({
            "path": relative,
            "source_sha256": sha(original.read_bytes()),
            "before_candidate_sha256": sha(before),
            "after_candidate_sha256": sha(replacement),
            "transform": f"declared_candidate_overlay:{overlay_path}",
        })
    receipt: dict[str, Any] = {
        "schema": "aios_streamlit_vendor_normalization_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_root": str(candidate),
        "source_root": str(source_root),
        "python_file_count": sum(1 for _ in vendor.rglob("*.py")),
        "transformed_file_count": len(entries),
        "transforms": entries,
        "compile_exclusions": compile_exclusions,
        "failure_count": len(failures),
        "failures": failures,
        "source_modified": False,
        "status": "PASS" if not failures else "HOLD",
    }
    body = json.dumps(receipt, ensure_ascii=False, sort_keys=True).encode("utf-8")
    receipt["receipt_sha256"] = sha(body)
    (candidate.parent / "streamlit_vendor_normalization_receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument(
        "--overlay",
        action="append",
        default=[],
        help="declared candidate overlay as source-relative/path/to/file=overlay-file",
    )
    args = parser.parse_args()
    overlays: list[tuple[str, Path]] = []
    for item in args.overlay:
        relative, separator, overlay_path = item.partition("=")
        if not separator or not relative or not overlay_path:
            raise SystemExit(f"invalid --overlay value: {item}")
        rel = Path(relative)
        if rel.is_absolute() or ".." in rel.parts:
            raise SystemExit(f"unsafe overlay target: {relative}")
        overlays.append((rel.as_posix(), Path(overlay_path).resolve(strict=True)))
    receipt = normalize(
        args.candidate.resolve(), args.source.resolve(strict=True), overlays
    )
    print(json.dumps({k: v for k, v in receipt.items() if k != "transforms"}, ensure_ascii=False))
    return 0 if receipt["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
