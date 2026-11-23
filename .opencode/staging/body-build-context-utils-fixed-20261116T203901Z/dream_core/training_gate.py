"""Admission boundary from Dream candidate records to isolated training data."""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any


APPROVED_TARGETS = {"plugin_identity_lora", "skill_specialist_lora"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_INPUT_BYTES = 32 * 1024 * 1024


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stage_admitted_candidates(candidate_path: Path | str, staging_root: Path | str) -> dict[str, Any]:
    """Validate Architect-reviewed examples and materialize isolated JSONL.

    The caller may train only the returned datasets. This function never
    touches the active adapter directory and refuses all pending Dream rows.
    """
    source = Path(candidate_path)
    if not source.is_file():
        raise FileNotFoundError(source)
    if source.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("candidate file exceeds configured size limit")
    grouped: dict[str, list[dict[str, Any]]] = {target: [] for target in APPROVED_TARGETS}
    accepted: list[dict[str, Any]] = []
    for line_number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"candidate line {line_number} is not an object")
        review = row.get("review")
        if (row.get("state") != "ADMITTED_BY_ARCHITECT"
                or row.get("admitted_for_training") is not True
                or not isinstance(review, dict)
                or review.get("reviewer") != "Architect"
                or any(review.get(gate) != "PASS" for gate in ("quality", "correctness", "truth"))
                or not isinstance(review.get("reviewed_at"), str)
                or not isinstance(review.get("evidence"), list)
                or not review["evidence"]):
            continue
        target = row.get("adapter_target")
        if target not in APPROVED_TARGETS:
            raise ValueError(f"candidate line {line_number} has unsupported/missing adapter_target")
        messages = row.get("messages")
        if (not isinstance(messages, list) or len(messages) != 2
                or [m.get("role") for m in messages if isinstance(m, dict)] != ["user", "assistant"]
                or any(not isinstance(m.get("content"), str) or not m["content"].strip()
                       for m in messages if isinstance(m, dict))):
            raise ValueError(f"candidate line {line_number} must contain one user and one assistant turn")
        source_hashes = row.get("source_sha256")
        if (not isinstance(source_hashes, list) or not source_hashes
                or any(not isinstance(value, str) or not SHA256_RE.fullmatch(value) for value in source_hashes)):
            raise ValueError(f"candidate line {line_number} is missing valid source hashes")
        clean = {"messages": messages}
        grouped[target].append(clean)
        accepted.append({
            "candidate_id": row.get("candidate_id"),
            "adapter_target": target,
            "candidate_sha256": _sha256(line.encode("utf-8")),
            "source_ids": row.get("source_ids", []),
            "source_sha256": source_hashes,
            "review": review,
        })
    if not accepted:
        raise ValueError("no candidates passed explicit quality/correctness/truth and Architect admission")

    run_id = str(time.time_ns())
    run_dir = Path(staging_root).resolve() / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    dataset_hashes: dict[str, str] = {}
    dataset_paths: dict[str, str] = {}
    for target, rows in grouped.items():
        if not rows:
            continue
        dataset_path = run_dir / f"{target}.jsonl"
        content = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
        dataset_path.write_text(content, encoding="utf-8")
        dataset_hashes[target] = _sha256(dataset_path.read_bytes())
        dataset_paths[target] = str(dataset_path)
    manifest = {
        "schema": "aios_viv_dream_training_manifest_v1",
        "run_id": run_id,
        "created_from": str(source.resolve()),
        "candidate_file_sha256": _sha256(source.read_bytes()),
        "accepted_candidates": accepted,
        "datasets": dataset_paths,
        "dataset_sha256": dataset_hashes,
        "active_adapter_modified": False,
        "training_started": False,
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest
