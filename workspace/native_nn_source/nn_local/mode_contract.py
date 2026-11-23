"""Shared byte encoding and expiry checks for the existing CPU mode lock."""
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Mapping


def mode_lock_digest(lock: Mapping[str, Any]) -> str:
    # Match the original mode producer exactly, including non-ASCII actor IDs.
    raw = json.dumps(dict(lock), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest().upper()


def mode_expiry_hold_reason(value: Any) -> str | None:
    # Expiry must be enforced at admission, not merely copied into evidence.
    if not isinstance(value, str):
        return "HOLD_MODE_EXPIRY_INVALID"
    try:
        expires = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if expires.tzinfo is None or expires.utcoffset() is None:
            return "HOLD_MODE_EXPIRY_INVALID"
        if expires <= datetime.now(timezone.utc):
            return "HOLD_MODE_EXPIRED"
    except (ValueError, OverflowError):
        return "HOLD_MODE_EXPIRY_INVALID"
    return None
