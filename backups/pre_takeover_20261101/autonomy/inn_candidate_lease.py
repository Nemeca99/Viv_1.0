"""Narrow Python adapter for Rust-owned INN candidate write leases."""
from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
RUST_EXTENSION = WORKSPACE / "aios_rebuild" / "local_security_core" / "target" / "debug" / "security_core.dll"
POINTERS = {
    WORKSPACE / "autonomy" / "learning" / "neural_status.json",
    WORKSPACE / "autonomy" / "learning" / "farm_corpus_latest.json",
    WORKSPACE / "autonomy" / "learning" / "neural_candidate.json",
}
_CORE = None


def _rust_core():
    global _CORE
    if _CORE is not None:
        return _CORE
    if not RUST_EXTENSION.is_file():
        raise RuntimeError("Rust security_core extension is not built")
    loader = importlib.machinery.ExtensionFileLoader("security_core", str(RUST_EXTENSION))
    spec = importlib.util.spec_from_file_location("security_core", RUST_EXTENSION, loader=loader)
    if spec is None:
        raise RuntimeError("Rust security_core extension spec unavailable")
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get("security_core")
    sys.modules["security_core"] = module
    try:
        loader.exec_module(module)
    finally:
        if previous is None:
            sys.modules.pop("security_core", None)
        else:
            sys.modules["security_core"] = previous
    _CORE = module
    return module


class InnCandidateLeaseExpired(RuntimeError):
    pass


class LeaseAwareRuntimeGuard:
    def __init__(self, body_guard, lease, *, lease_poll_seconds: float = 5.0):
        self._body_guard = body_guard
        self._lease = lease
        self._lease_poll_seconds = lease_poll_seconds
        self._next_lease_check = 0.0

    def __getattr__(self, name):
        return getattr(self._body_guard, name)

    def check(self, *, force: bool = False):
        verdict = self._body_guard.check(force=force)
        now = time.monotonic()
        if not self._lease.committed and (force or now >= self._next_lease_check):
            self._lease.assert_active()
            self._next_lease_check = now + self._lease_poll_seconds
        return verdict


@dataclass
class InnCandidateLease:
    token: str
    run_id: str
    stage_root: Path
    final_root: Path
    common: dict
    committed: bool = False

    @classmethod
    def begin(cls, run_id: str, source_hashes: list[str], stability_sn: float,
              body_runtime_permit: str | None = None, requested_threads: int | None = None,
              max_vram_mib: int = 0):
        common = _common(run_id, source_hashes, stability_sn)
        common["body_requested_threads"] = requested_threads
        common["max_vram_mib"] = max_vram_mib
        request = {
            **common,
            "action": "BEGIN_INN_CANDIDATE",
            "body_runtime_permit": body_runtime_permit,
            "paths": [
                f"L:/LocalCoder/workspace/autonomy/learning/neural_candidate_staging/{run_id}",
                f"L:/LocalCoder/workspace/autonomy/learning/neural_runs/{run_id}",
            ],
        }
        verdict = _rust_core().begin_training_lease(_encode(request))
        if not verdict.get("allowed") or not verdict.get("lease_token"):
            raise PermissionError(f"Rust denied INN candidate lease: {verdict.get('rule')} {verdict.get('reason')}")
        stage_root = Path(verdict["staging_root"])
        final_root = Path(verdict["final_root"])
        if stage_root.name != run_id or final_root.name != run_id:
            raise PermissionError("Rust lease returned unexpected candidate roots")
        return cls(verdict["lease_token"], run_id, stage_root, final_root, common)

    def commit(self):
        request = {
            **self.common,
            "action": "COMMIT_INN_CANDIDATE",
            "paths": [str(self.stage_root).replace("\\", "/"), str(self.final_root).replace("\\", "/")],
        }
        verdict = _rust_core().commit_training_lease(self.token, _encode(request))
        if not verdict.get("allowed") or Path(verdict.get("final_root", "")) != self.final_root:
            raise PermissionError(f"Rust denied INN candidate commit: {verdict.get('rule')} {verdict.get('reason')}")
        self.committed = True
        return self.final_root

    def assert_active(self):
        if not _rust_core().training_lease_active(self.token):
            raise InnCandidateLeaseExpired("Rust candidate lease expired, was consumed, or is not process-bound")

    def write_artifact(self, path: Path, payload: bytes):
        relative = Path(path).resolve().relative_to(self.stage_root.resolve())
        _rust_core().write_inn_candidate_artifact(self.token, str(relative), payload)

    def write_json(self, path: Path, value):
        payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        self.write_artifact(path, payload)

    def authorize_pointer(self, path: Path):
        path = path.resolve()
        if path not in POINTERS:
            raise PermissionError(f"Pointer is outside the explicit INN candidate scope: {path}")
        request = {
            **self.common,
            "action": "PUBLISH_INN_POINTER",
            "artifact_class": "inn_candidate_pointer",
            "paths": [str(path).replace("\\", "/")],
        }
        verdict = _rust_core().authorize_training(_encode(request))
        if not verdict.get("allowed"):
            raise PermissionError(f"Rust denied INN pointer write: {verdict.get('rule')} {verdict.get('reason')}")

    def publish_pointer(self, path: Path, value):
        path = path.resolve()
        if path not in POINTERS:
            raise PermissionError(f"Pointer is outside the explicit INN candidate scope: {path}")
        request = {
            **self.common,
            "action": "PUBLISH_INN_POINTER",
            "artifact_class": "inn_candidate_pointer",
            "paths": [str(path).replace("\\", "/")],
        }
        payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        verdict = _rust_core().publish_inn_pointer(self.token, _encode(request), payload)
        if not verdict.get("allowed"):
            raise PermissionError(f"Rust denied INN pointer publication: {verdict.get('rule')} {verdict.get('reason')}")


def write_verification_receipt(run: Path, candidate: dict, receipt: dict, stability_sn: float | None):
    run = run.resolve()
    run_id = run.name
    payload = json.dumps(receipt, sort_keys=True, separators=(",", ":"))
    candidate_hashes = [candidate["engine_sha256"], candidate["evaluation_sha256"]]
    request = {
        "action": "WRITE_INN_CANDIDATE_RECEIPT",
        "stage_id": "inn_candidate",
        "run_id": run_id,
        "model_role": "inn_candidate_verifier",
        "manifest_hash": hashlib.sha256(payload.encode()).hexdigest(),
        "source_hashes": candidate_hashes,
        "paths": [f"L:/LocalCoder/workspace/autonomy/learning/neural_runs/{run_id}/recheck.json"],
        "artifact_class": "inn_candidate_receipt",
        "master_s_n": float(stability_sn) if stability_sn is not None else 0.0,
        "process_id": os.getpid(),
        "max_duration_s": 60,
        "max_vram_mib": 0,
        "max_ram_mib": 1024,
        "max_disk_mib": 1,
        "sequence_cap": 384,
        "lora_rank": 0,
    }
    verdict = _rust_core().write_inn_candidate_receipt(_encode(request), payload)
    if not verdict.get("allowed"):
        raise PermissionError(f"Rust denied INN verification receipt: {verdict.get('rule')} {verdict.get('reason')}")


def _common(run_id: str, source_hashes: list[str], stability_sn: float) -> dict:
    binding = json.dumps({"run_id": run_id, "source_hashes": sorted(source_hashes)}, sort_keys=True, separators=(",", ":"))
    return {
        "stage_id": "inn_candidate",
        "run_id": run_id,
        "model_role": "inn_candidate_trainer",
        "manifest_hash": hashlib.sha256(binding.encode()).hexdigest(),
        "source_hashes": sorted(source_hashes),
        "artifact_class": "inn_candidate_bundle",
        "master_s_n": float(stability_sn),
        "process_id": __import__("os").getpid(),
        "max_duration_s": 4 * 60 * 60,
        "max_vram_mib": 0,
        "max_ram_mib": 8192,
        "max_disk_mib": 8192,
        "sequence_cap": 384,
        "lora_rank": 0,
    }


def _encode(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
