"""Hydra Protocol — Viv's defensive encryption (the shield, not the sword).

Core primitives of the hydra protocol as Travis specified it:

1. Entropy password vault — mints N passwords from the system's own entropy,
   writes them to a file, and a random pointer marks one line as the current
   password. The pointer is not hardcoded into the code; only the running
   system knows which line is correct in that instant. A wrong guess deletes
   the whole file and remints N+1 fresh passwords, forever.

2. Heartbeat rate limiter — the system ticks once per second. No more than one
   command per second, fail-closed, so an attacker is physically bound to one
   guess per second, forever.

3. Attempt recorder — every attempt (right or wrong) is appended to an
   append-only log, so she learns from what is freely given. The attacker gets
   one free try; after that the attempt is already recorded and adapted to.

All primitives are DEFENSIVE. The same entropy generator could, in principle,
encrypt outward (the counter), but this module only implements the shield side.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import string
import time
from dataclasses import dataclass
from pathlib import Path


# --- entropy password generation -------------------------------------------
# Character set: ASCII + a Unicode subset, enough to satisfy "Unicode + ASCII"
# while staying practical (no unprintable/control characters).
_UNICODE_EXTRA = "".join(chr(cp) for cp in range(0x00A0, 0x00C0))  # Latin-1 supplement (printable)
PASSWORD_ALPHABET = string.ascii_letters + string.digits + string.punctuation + _UNICODE_EXTRA


def generate_passwords(count: int, min_len: int = 1, max_len: int = 100) -> list[str]:
    """Mint `count` passwords from the system's cryptographic entropy."""
    out = []
    for _ in range(count):
        length = secrets.randbelow(max_len - min_len + 1) + min_len
        out.append("".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(length)))
    return out


@dataclass(frozen=True)
class HydraPasswordVault:
    """Holds the rotating password file; only the running instance knows the
    current line. Wrong guess -> remint with +1, forever."""

    path: Path
    start_count: int = 1000
    passwords: tuple[str, ...] = ()
    current_index: int = -1

    @classmethod
    def create(cls, path: Path, count: int = 1000) -> "HydraPasswordVault":
        passwords = generate_passwords(count)
        index = secrets.randbelow(count)
        path.write_text("\n".join(passwords), encoding="utf-8")
        return cls(path=path, start_count=count, passwords=tuple(passwords), current_index=index)

    @property
    def current_password(self) -> str:
        return self.passwords[self.current_index]

    def verify(self, guess: str) -> bool:
        # constant-time-ish compare via digest, no early exit on the plaintext
        a = hashlib.sha256(guess.encode("utf-8")).digest()
        b = hashlib.sha256(self.current_password.encode("utf-8")).digest()
        return secrets.compare_digest(a, b)

    def rotate(self) -> "HydraPasswordVault":
        """Wrong guess: delete the file, remint with +1 passwords."""
        new_count = len(self.passwords) + 1
        self.path.unlink(missing_ok=True)
        return HydraPasswordVault.create(self.path, count=new_count)


class HeartbeatRateLimiter:
    """One command per second, fail-closed. The system ticks at 1 Hz."""

    def __init__(self, interval_seconds: float = 1.0):
        self.interval = interval_seconds
        self._last = 0.0

    def allowed(self) -> bool:
        now = time.monotonic()
        if now - self._last >= self.interval:
            self._last = now
            return True
        return False


class HydraAttemptLog:
    """Append-only record of every attempt, so she learns from what's freely
    given. Never truncated, never overwritten."""

    def __init__(self, path: Path):
        self.path = path

    def record(self, *, guess_digest: str, correct: bool, utc: str) -> None:
        entry = {"guess_sha256": guess_digest, "correct": correct, "utc": utc}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")

    def attempts(self) -> int:
        if not self.path.is_file():
            return 0
        return sum(1 for _ in self.path.read_text(encoding="utf-8").splitlines() if _)


def main():
    import tempfile
    from datetime import datetime, timezone

    # demonstrate the core loop: create -> verify right -> verify wrong -> rotate
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        vault = HydraPasswordVault.create(td / "passwords.txt", count=100)
        limiter = HeartbeatRateLimiter()
        log = HydraAttemptLog(td / "attempts.jsonl")

        correct = vault.current_password
        wrong = "not-the-password"

        print("vault created:", len(vault.passwords), "passwords, current index", vault.current_index)
        print("correct guess accepted:", vault.verify(correct))
        print("wrong guess rejected:", not vault.verify(wrong))

        rotated = vault.rotate()
        print("after wrong guess, reminted:", len(rotated.passwords), "passwords (+1)")

        # rate limiter: first allowed, immediate second denied
        print("rate limiter: first allowed =", limiter.allowed(), "| immediate retry =", limiter.allowed())

        log.record(guess_digest=hashlib.sha256(wrong.encode()).hexdigest(), correct=False,
                   utc=datetime.now(timezone.utc).isoformat())
        print("attempts recorded:", log.attempts())


if __name__ == "__main__":
    raise SystemExit(main())
