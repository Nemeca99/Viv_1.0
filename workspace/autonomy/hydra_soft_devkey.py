"""Hydra Soft DevKey — the software placeholder for the physical USB fob.

Travis: "we already built the house... now we can finish the lock for the
house."  The DevKey is the lock.  Until he has the USB drive, this is the
SOFT DevKey: the same master key, persisted to disk, write-once and
immutable-by-policy, so the system has a real bootstrap key to work against
today.

Immutability contract (software-enforced, fail-closed):
- WRITE-ONCE: create() refuses if the key file already exists. The key is
  minted exactly once and can never be silently regenerated.
- READ-ONLY: the key file is set read-only on disk after creation.
- INTEGRITY: a sidecar digest records the key's hash; load() re-verifies and
  fails closed on any mismatch (tamper detection).

This is SOFTWARE immutability — enforced by policy, not physics.  The USB fob
later adds HARDWARE immutability (the fob is off-machine and physically
write-protected).  Same key material, stronger envelope.  The human never sees
the key; only the file holds it, the way the Ford fob holds a frequency.

DEFENSIVE ONLY. No outward-encryption primitive exists here.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path

DEFAULT_KEY_PATH = Path("L:/LocalCoder/workspace/security/devkey/master.key")


def key_digest(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest().upper()


def _set_readonly(path: Path) -> None:
    """Set a file read-only. On Windows this sets the read-only attribute."""
    os.chmod(path, stat.S_IREAD)


class KeyIntegrityError(Exception):
    """Raised when a soft DevKey fails integrity verification (fail closed)."""


@dataclass(frozen=True)
class SoftDevKey:
    """The disk-backed master key. Drop-in compatible with DevKey (in-memory)."""

    key_path: Path
    master_key: bytes
    key_id: str

    def digest(self) -> str:
        return key_digest(self.master_key)

    @property
    def digest_path(self) -> Path:
        return self.key_path.with_suffix(self.key_path.suffix + ".digest")

    @classmethod
    def create(cls, key_path: Path = DEFAULT_KEY_PATH, *, key_bytes: int = 64) -> "SoftDevKey":
        """Mint the master key ONCE. Fail closed if it already exists."""
        key_path = Path(key_path)
        if key_path.exists():
            raise FileExistsError(
                f"soft DevKey already exists at {key_path}; it is write-once and "
                f"cannot be regenerated. Delete it only with the Architect's explicit "
                f"authorization."
            )
        key_path.parent.mkdir(parents=True, exist_ok=True)
        mk = secrets.token_bytes(key_bytes)
        key_path.write_bytes(mk)
        _set_readonly(key_path)
        key_path.with_suffix(key_path.suffix + ".digest").write_text(
            key_digest(mk), encoding="utf-8"
        )
        _set_readonly(key_path.with_suffix(key_path.suffix + ".digest"))
        return cls(key_path=key_path, master_key=mk, key_id=key_digest(mk)[:16])

    @classmethod
    def load(cls, key_path: Path = DEFAULT_KEY_PATH) -> "SoftDevKey":
        """Load and verify the key. Fail closed on any tamper."""
        key_path = Path(key_path)
        if not key_path.exists():
            raise FileNotFoundError(f"soft DevKey missing at {key_path}")
        mk = key_path.read_bytes()
        expected = key_path.with_suffix(key_path.suffix + ".digest").read_text(
            encoding="utf-8"
        ).strip()
        if key_digest(mk) != expected:
            raise KeyIntegrityError(
                f"soft DevKey at {key_path} FAILED integrity check — tamper detected."
            )
        return cls(key_path=key_path, master_key=mk, key_id=key_digest(mk)[:16])


def main():
    import sys

    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_KEY_PATH
    print("=== Hydra Soft DevKey (the lock for the house) ===")

    # 1. Create the real soft DevKey — write-once.
    try:
        softkey = SoftDevKey.create(path, key_bytes=64)
        print("created soft DevKey:", softkey.key_path)
        print("key_id:", softkey.key_id)
        print("digest (commitment, safe to show):", softkey.digest())
    except FileExistsError as e:
        print("ALREADY EXISTS (write-once holds):", e)

    # 2. Prove write-once: a second create must fail closed.
    try:
        SoftDevKey.create(path, key_bytes=64)
        print("ERROR: write-once was violated (second create succeeded)")
    except FileExistsError:
        print("write-once verified: second create refused (fail closed)")

    # 3. Load + integrity check on the real key.
    loaded = SoftDevKey.load(path)
    print("load verified: digest matches, key_id", loaded.key_id)

    # 4. Tamper detection (in a throwaway temp dir, NOT the real key).
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        k = SoftDevKey.create(td / "master.key", key_bytes=32)
        os.chmod(k.key_path, stat.S_IWRITE)  # simulate an attacker flipping the bit
        k.key_path.write_bytes(b"tampered")
        try:
            SoftDevKey.load(k.key_path)
            print("ERROR: tamper was not detected")
        except KeyIntegrityError:
            print("tamper detection verified: corrupted key rejected (fail closed)")

    print("=== soft DevKey lock is in place ===")


if __name__ == "__main__":
    raise SystemExit(main())
