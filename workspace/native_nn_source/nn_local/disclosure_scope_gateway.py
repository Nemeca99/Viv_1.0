from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest().upper()


def bind_disclosure_scope(*, proceeding_sha256: str, allowed_fields: Sequence[str]) -> dict[str, Any]:
    # Strings are iterable, but their characters are not authorized field names.
    if isinstance(allowed_fields, (str, bytes)) or not isinstance(allowed_fields, Sequence) or any(not isinstance(field, str) or not field for field in allowed_fields):
        raise ValueError("allowed_fields must be a sequence of nonempty field names")
    fields = sorted({str(field) for field in allowed_fields})
    payload = {
        "schema": "VIV_DISCLOSURE_SCOPE_LOCK_V1",
        "proceeding_sha256": str(proceeding_sha256).upper(),
        "allowed_fields": fields,
    }
    return {"state": "PASS", "scope_lock": payload, "scope_lock_sha256": _digest(payload)}


def verify_disclosure_egress(
    scope_receipt: Mapping[str, Any], *, proceeding_sha256: str, disclosed_fields: Mapping[str, Any]
) -> dict[str, Any]:
    lock = scope_receipt.get("scope_lock")
    if scope_receipt.get("state") != "PASS" or not isinstance(lock, Mapping) or _digest(dict(lock)) != str(scope_receipt.get("scope_lock_sha256", "")).upper():
        return {"state": "HOLD", "reason": "HOLD_DISCLOSURE_LOCK_INVALID"}
    # A hash proves byte consistency, not a valid scope schema or admitted state.
    fields = lock.get("allowed_fields")
    if lock.get("schema") != "VIV_DISCLOSURE_SCOPE_LOCK_V1" or not isinstance(fields, list) or any(not isinstance(field, str) or not field for field in fields):
        return {"state": "HOLD", "reason": "HOLD_DISCLOSURE_LOCK_INVALID"}
    if str(proceeding_sha256).upper() != str(lock.get("proceeding_sha256", "")).upper():
        return {"state": "HOLD", "reason": "HOLD_DISCLOSURE_PROCEEDING_MISMATCH"}
    allowed = set(lock.get("allowed_fields", []))
    extra = sorted(set(map(str, disclosed_fields)) - allowed)
    if extra:
        return {"state": "HOLD", "reason": "HOLD_DISCLOSURE_SCOPE_EXPANDED", "unauthorized_fields": extra}
    disclosure = dict(disclosed_fields)
    return {"state": "PASS", "reason": "PASS_DISCLOSURE_SCOPE_MATCH", "disclosure_sha256": _digest(disclosure)}
