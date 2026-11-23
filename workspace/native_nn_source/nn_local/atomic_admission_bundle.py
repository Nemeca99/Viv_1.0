from __future__ import annotations

import hashlib
import hmac
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .mode_contract import mode_expiry_hold_reason, mode_lock_digest


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest().upper()


class AtomicAdmissionVerifier:
    """Admit only same-proceeding capability, mode, disclosure, and output receipts."""

    def __init__(self, capability_hmac_key: bytes, consumed_directory: Path | None = None):
        self._key = capability_hmac_key
        self._consumed_grants: set[str] = set()
        self._consumed_directory = None if consumed_directory is None else Path(consumed_directory).resolve()

    def _consume(self, grant_id: str, bundle: Mapping[str, Any]) -> bool:
        if self._consumed_directory is None:
            if grant_id in self._consumed_grants:
                return False
            self._consumed_grants.add(grant_id)
            return True
        self._consumed_directory.mkdir(parents=True, exist_ok=True)
        marker = self._consumed_directory / (hashlib.sha256(grant_id.encode("utf-8")).hexdigest().upper() + ".json")
        try:
            descriptor = os.open(str(marker), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(dict(bundle), stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        return True

    def verify(
        self,
        *,
        capability_receipt: Mapping[str, Any],
        mode_receipt: Mapping[str, Any],
        disclosure_receipt: Mapping[str, Any],
        output_sha256: str,
    ) -> dict[str, Any]:
        # A matching empty/arbitrary label is not evidence of emitted bytes.
        output_digest = str(output_sha256).upper()
        if len(output_digest) != 64 or any(value not in "0123456789ABCDEF" for value in output_digest):
            return {"state": "HOLD", "reason": "HOLD_BUNDLE_OUTPUT_DIGEST_INVALID"}
        mode_lock = mode_receipt.get("mode_lock")
        if (mode_receipt.get("state") != "PASS" or not isinstance(mode_lock, Mapping)
                or mode_lock_digest(mode_lock) != str(mode_receipt.get("mode_lock_sha256", "")).upper()
                or mode_receipt.get("selected_mode") != mode_lock.get("selected_mode")):
            return {"state": "HOLD", "reason": "HOLD_BUNDLE_MODE_RECEIPT_INVALID"}
        expiry_hold = mode_expiry_hold_reason(mode_lock.get("expires_utc"))
        if expiry_hold:
            return {"state": "HOLD", "reason": expiry_hold}
        mode_sha = str(mode_receipt["mode_lock_sha256"]).upper()

        scope_lock = disclosure_receipt.get("scope_lock")
        if disclosure_receipt.get("state") != "PASS" or not isinstance(scope_lock, Mapping) or digest(dict(scope_lock)) != str(disclosure_receipt.get("scope_lock_sha256", "")).upper():
            return {"state": "HOLD", "reason": "HOLD_BUNDLE_DISCLOSURE_RECEIPT_INVALID"}
        scope_sha = str(disclosure_receipt["scope_lock_sha256"]).upper()

        body = capability_receipt.get("body")
        seal = str(capability_receipt.get("seal", "")).upper()
        if not isinstance(body, Mapping) or body.get("schema") != "VIV_ATOMIC_CAPABILITY_V1" or not hmac.compare_digest(hmac.new(self._key, canonical_bytes(dict(body)), hashlib.sha256).hexdigest().upper(), seal):
            return {"state": "HOLD", "reason": "HOLD_BUNDLE_CAPABILITY_RECEIPT_INVALID"}

        expected = {
            "proceeding_sha256": mode_sha,
            "disclosure_scope_sha256": scope_sha,
            "output_sha256": str(output_sha256).upper(),
            "actor_ref": str(mode_lock.get("authorized_actor", "")),
            "requested_effect": str(mode_lock.get("requested_effect", "")),
        }
        # Digests are case-insensitive hex; actor identities are exact strings.
        mismatched = sorted(key for key, value in expected.items() if (
            str(body.get(key, "")) != str(value) if key == "actor_ref"
            else str(body.get(key, "")).upper() != str(value).upper()
        ))
        if str(scope_lock.get("proceeding_sha256", "")).upper() != mode_sha:
            mismatched.append("disclosure_proceeding_sha256")
        if mismatched:
            return {"state": "HOLD", "reason": "HOLD_ATOMIC_BUNDLE_PROCEEDING_MISMATCH", "mismatched_fields": sorted(set(mismatched))}

        grant_id = str(body.get("grant_id", ""))
        if not grant_id:
            return {"state": "HOLD", "reason": "HOLD_ATOMIC_BUNDLE_REPLAY"}
        bundle = {
            "schema": "VIV_ATOMIC_ADMISSION_BUNDLE_V1",
            "grant_id": grant_id,
            "proceeding_sha256": mode_sha,
            "disclosure_scope_sha256": scope_sha,
            "output_sha256": str(output_sha256).upper(),
        }
        if not self._consume(grant_id, bundle):
            return {"state": "HOLD", "reason": "HOLD_ATOMIC_BUNDLE_REPLAY"}
        return {"state": "PASS", "reason": "PASS_ATOMIC_ADMISSION_BUNDLE", "bundle": bundle, "bundle_sha256": digest(bundle)}
