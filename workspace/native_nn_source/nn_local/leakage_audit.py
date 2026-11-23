"""Static and serialized-state checks for the target-hidden boundary."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


FORBIDDEN_GPU_KEYS = {
    "target",
    "target_id",
    "target_ids",
    "target_order",
    "answer",
    "answer_id",
    "correct_index",
    "correct_indices",
    "correct_position",
    "valid_answer_mask",
    "role_label",
    "relation_label",
    "correction_position",
}
FORBIDDEN_ABI_WORDS = {
    "target",
    "answer",
    "correct",
    "valid_mask",
    "role",
    "relation",
}
FORBIDDEN_GPU_VALUES = {
    "ADJ", "ADP", "ADV", "AUX", "CCONJ", "DET", "INTJ", "NOUN", "NUM",
    "PART", "PRON", "PROPN", "PUNCT", "SCONJ", "SYM", "VERB", "X",
    "nsubj", "obj", "iobj", "root", "amod", "advmod", "acl", "xcomp",
}


def _walk_keys(value: Any, path: str = "$") -> list[str]:
    violations: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).strip().lower()
            if normalized in FORBIDDEN_GPU_KEYS:
                violations.append(f"{path}.{key}")
            violations.extend(_walk_keys(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            violations.extend(_walk_keys(child, f"{path}[{index}]"))
    # A single-character expert may legitimately represent ``X`` (which is
    # also a UD role label).  Human labels are still rejected when they have
    # label-like multi-character values.
    elif isinstance(value, str) and len(value) != 1 and value in FORBIDDEN_GPU_VALUES:
        # Learned visible language can legitimately spell the same bytes as a
        # hidden annotation (for example the Odyssey trigram ``obj``).  The
        # field provenance matters: permit that collision only in the model's
        # learned surface/combination slots.  Metadata keys such as
        # ``role_label`` and ``relation_label`` remain forbidden above.
        learned_text_slot = path.endswith(".learned_surface") or path.endswith(".learned_combination")
        if not learned_text_slot:
            violations.append(f"{path}=FORBIDDEN_LABEL")
    return violations


def audit_gpu_payload(payload: dict[str, Any]) -> dict[str, Any]:
    violations = _walk_keys(payload)
    return {"state": "PASS" if not violations else "FAIL", "violations": violations}


def audit_native_header(path: str | Path) -> dict[str, Any]:
    source = Path(path).read_text(encoding="utf-8")
    declarations = "\n".join(
        line.strip()
        for line in source.splitlines()
        if line.strip().startswith("NN_API") or line.strip().startswith("uint") or line.strip().startswith("const uint")
    ).lower()
    words = set(re.findall(r"[a-z_]+", declarations))
    violations = sorted(words & FORBIDDEN_ABI_WORDS)
    return {
        "state": "PASS" if not violations else "FAIL",
        "path": str(Path(path).resolve()),
        "violations": violations,
    }


def audit_gpu_state_file(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    result = audit_gpu_payload(payload)
    result["path"] = str(Path(path).resolve())
    return result


__all__ = ["audit_gpu_payload", "audit_gpu_state_file", "audit_native_header"]
