"""Verify a candidate whose only source delta is one declared overlay file."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(
    manifest_path: Path,
    base_candidate: Path,
    overlay_candidate: Path,
    overlay_relative: str,
) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = manifest["files"]
    overlay_path = overlay_candidate / overlay_relative
    base_overlay_path = base_candidate / overlay_relative
    if not overlay_path.is_file() or not base_overlay_path.is_file():
        raise FileNotFoundError(overlay_relative)
    parent_hash = sha(base_overlay_path)
    overlay_hash = sha(overlay_path)
    mismatches: list[str] = []
    for row in rows:
        relative = row["path"]
        target = overlay_candidate / relative
        if not target.is_file():
            mismatches.append(f"missing:{relative}")
            continue
        expected = overlay_hash if relative == overlay_relative else row["sha256"]
        if sha(target) != expected:
            mismatches.append(f"hash:{relative}")
    compile(overlay_path.read_text(encoding="utf-8"), str(overlay_path), "exec")
    passed = not mismatches and overlay_hash != parent_hash
    return {
        "schema": "hive_declared_overlay_verification_v1",
        "status": "PASS" if passed else "HOLD",
        "parent_manifest_sha256": sha(manifest_path),
        "parent_candidate": str(base_candidate),
        "overlay_candidate": str(overlay_candidate),
        "overlay_path": overlay_relative,
        "parent_file_sha256": parent_hash,
        "overlay_file_sha256": overlay_hash,
        "manifest_files_checked": len(rows),
        "mismatches": mismatches,
        "source_modified": False,
    }


if __name__ == "__main__":
    try:
        result = verify(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4])
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        raise SystemExit(0 if result["status"] == "PASS" else 1)
    except Exception as error:  # noqa: BLE001 - verifier produces a machine-readable HOLD
        print(json.dumps({"schema": "hive_declared_overlay_verification_v1", "status": "HOLD", "error": f"{type(error).__name__}: {error}"}))
        raise SystemExit(2)
