"""Dynamic route-snapshot path resolution without curriculum constants."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

RUNS = Path(r"L:\LocalCoder\workspace\autonomy\learning\neural_runs")


def latest_run() -> Path | None:
    candidates = sorted(RUNS.glob("language-routes-*"), reverse=True)
    return candidates[0] if candidates else None


_VERIFIED_RUN_CACHE: dict[str, tuple[tuple, dict]] = {}


def verify_run(run: Path) -> dict:
    run = Path(run).resolve()
    if run.parent != RUNS.resolve() or not run.name.startswith("language-routes-"):
        raise ValueError("resume_requires_committed_language_route")
    learning_path = run / "learning.json"
    record = json.loads(learning_path.read_text(encoding="utf-8"))
    if not record.get("snapshot_verified"):
        raise ValueError("route_snapshot_not_verified")
    sig_parts = [learning_path.stat().st_mtime]
    for name in sorted(record.get("snapshot_hashes", {})):
        target = run / name
        if not target.is_file():
            raise ValueError(f"route_snapshot_missing:{name}")
        st = target.stat()
        sig_parts.extend([st.st_mtime, st.st_size])
    cache_key = str(run)
    sig = tuple(sig_parts)
    cached = _VERIFIED_RUN_CACHE.get(cache_key)
    if cached is not None and cached[0] == sig:
        return cached[1]
    for name, expected in record.get("snapshot_hashes", {}).items():
        target = run / name
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if digest != expected:
            raise ValueError(f"route_snapshot_hash_mismatch:{name}")
    _VERIFIED_RUN_CACHE[cache_key] = (sig, record)
    return record


def latest_verified_run() -> Path | None:
    for candidate in sorted(RUNS.glob("language-routes-*"), reverse=True):
        try:
            verify_run(candidate)
        except (ValueError, KeyError, OSError, json.JSONDecodeError):
            continue
        return candidate
    return None

