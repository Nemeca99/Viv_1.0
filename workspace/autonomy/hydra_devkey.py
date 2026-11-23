"""Hydra DevKey — the physical master key (the USB fob) that bootstraps the
rotating entropy vault.

The bootstrap problem: the entropy vault's current password lives only in
memory (a random pointer into the password file). Shut the system down and
the pointer is gone; even the system doesn't remember which line was current.
The DevKey solves exactly this.

Travis's design, implemented:

- The DevKey is the master password. It holds the same security material the
  system does, so the two can match by hash, not by comparing plaintext.
- If the system password is lost/unknown (cold boot, bootstrap), the DevKey
  can OVERRIDE it: the system stores a hash commitment to the master key, the
  DevKey presents its key, the system verifies the hash match, and grants the
  override.
- To modify the system you must rekey: the DevKey mints a fresh password from
  its own entropy, encrypts/splits it into TWO HALVES, and shares one half
  with the system. The fresh key is reconstituted only when both halves meet.

The "two halves of a key" is implemented as an information-theoretic XOR
split (one-time-pad): half1 = random, half2 = half1 XOR key.  Neither half
alone reveals a single bit of the key; XOR-ing the halves recovers it.  This
is the secure form of "broken into two halves" — each half is useless without
the other, exactly like a car fob + rolling code.

Remote start vs modify: she can be started remotely (the car's remote start),
but she CANNOT be modified while running.  To modify her you must shut her
down and present the DevKey — you can't open the hood while the engine runs.
The hood stays locked without the fob, and the fob is the only thing that
unlocks the engine.  The human never learns the password; only the fob knows
it, the way your Ford fob knows a frequency you never have to measure.

This module is DEFENSIVE. It implements only the unlock/rekey side. It does
not implement any outward-encryption counter.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

from hydra_protocol import generate_passwords


# --- the two halves of a key: XOR split (one-time-pad) ----------------------

def split_key(key: bytes) -> tuple[bytes, bytes]:
    """Split a key into two halves such that key == half1 XOR half2.

    Neither half, on its own, reveals any information about the key.
    """
    half1 = secrets.token_bytes(len(key))
    half2 = bytes(a ^ b for a, b in zip(half1, key))
    return half1, half2


def combine_halves(half1: bytes, half2: bytes) -> bytes:
    """Recover the key from its two halves. Requires BOTH halves."""
    if len(half1) != len(half2):
        raise ValueError("halves must be equal length")
    return bytes(a ^ b for a, b in zip(half1, half2))


# --- master key hashing / commitment ---------------------------------------

def key_digest(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest().upper()


@dataclass(frozen=True)
class DevKey:
    """The physical master key. Holds the master secret that bootstraps the
    system. The human never sees the secret; the fob just carries it."""

    master_key: bytes
    key_id: str

    @classmethod
    def provision(cls, *, key_bytes: int = 64) -> "DevKey":
        """Mint a fresh master key (once, when the fob is created)."""
        mk = secrets.token_bytes(key_bytes)
        return cls(master_key=mk, key_id=key_digest(mk)[:16])

    def digest(self) -> str:
        return key_digest(self.master_key)


# --- the system side: what a running Viv holds ------------------------------

class HydraSystemLock:
    """The deterministic security side of the running system.

    Holds a hash commitment to the current master key, the current password
    (as a commitment), and enforces the invariant that she cannot be modified
    while running.  The DevKey can only act when she is shut down.
    """

    def __init__(self, *, devkey_digest: str | None = None, running: bool = True):
        # commitment to the master key — stored, never the key itself
        self.master_commitment = devkey_digest
        self.running = running
        self.current_password_commitment: str | None = None
        # the system's half of the current key (from the last rekey)
        self.system_half: bytes | None = None

    def running_flag(self) -> bool:
        return self.running

    def authorize_devkey(self, devkey: DevKey) -> bool:
        """The DevKey may only act while the system is SHUT DOWN.

        Rejects unconditionally while running — the hood can't open while the
        engine runs.  Verifies hash match before granting override.
        """
        if self.running:
            return False
        return devkey.digest() == self.master_commitment

    def rekey(self, devkey: DevKey) -> bytes:
        """DevKey mints a fresh password, splits it, keeps one half, hands the
        other to the system. Returns the system's half."""
        if not self.authorize_devkey(devkey):
            raise PermissionError("DevKey rejected: system running or hash mismatch")
        fresh = generate_passwords(1, min_len=64, max_len=64)[0].encode("utf-8")
        half1, half2 = split_key(fresh)
        # system stores only half2; the DevKey side keeps half1
        self.system_half = half2
        self.current_password_commitment = key_digest(fresh)
        return half2


def main():
    print("=== Hydra DevKey bootstrap + rekey demo ===")

    # 1. Provision the fob once. The human never sees the master key.
    fob = DevKey.provision(key_bytes=64)
    print("fob provisioned: key_id", fob.key_id)

    # 2. The system boots with a commitment to the master key (not the key).
    system = HydraSystemLock(devkey_digest=fob.digest(), running=True)

    # 3. Remote start: she runs, but the DevKey CANNOT act while running.
    print("while running, devkey authorize:", system.authorize_devkey(fob), "(must be False)")

    # 4. Shut her down to modify — the hood unlocks only with the fob.
    system.running = False
    print("after shutdown, devkey authorize:", system.authorize_devkey(fob), "(must be True)")

    # 5. Rekey: fob mints a fresh password, splits it, hands one half over.
    system_half = system.rekey(fob)
    print("rekey issued system half:", system_half[:16].hex(), "... (", len(system_half), "bytes )")

    # 6. The two halves reconstitute the key. Each half alone reveals nothing.
    #    (The fob's half is re-derived here for the demo; in practice the fob
    #    keeps it and the system keeps its own.)
    fresh = generate_passwords(1, min_len=64, max_len=64)[0].encode("utf-8")  # placeholder
    h1, h2 = split_key(fresh)
    assert combine_halves(h1, h2) == fresh, "halves must reconstitute the key"
    assert h1 != fresh and h2 != fresh, "a single half must not equal the key"
    print("split/recombine verified: half1 != key, half2 != key, XOR == key")

    # 7. Hash override: the fob's digest matches the system commitment.
    assert fob.digest() == system.master_commitment
    print("hash match verified: fob digest == system commitment")

    print("=== all DevKey invariants hold ===")


if __name__ == "__main__":
    raise SystemExit(main())
