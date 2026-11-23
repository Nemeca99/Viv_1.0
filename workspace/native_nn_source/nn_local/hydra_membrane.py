"""Minimal live Hydra route membrane for the Steel Brain learner."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Sequence

from .fixed_point import SCALE
from .neuron_graph import CurriculumStore


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest().upper()


class HydraRouteMembrane:
    """Compile an ordered hard mask from earned consequence evidence only."""

    MAX_POLICY_CANDIDATES = 128

    def __init__(
        self,
        curriculum: CurriculumStore,
        binary: Path,
        trace_path: Path,
        *,
        evidence_level: str = "WORD",
    ):
        self.curriculum = curriculum
        self.binary = binary.resolve()
        self.trace_path = trace_path.resolve()
        self.evidence_level = str(evidence_level)
        if not self.evidence_level:
            raise ValueError("Hydra evidence level is required")
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache: dict[str, list[int]] = {}
        self.cache_bundle_hashes: dict[str, str] = {}
        self.compilations = 0
        self.cache_hits = 0
        self.denied_candidates = 0

    def __call__(self, payload: dict[str, Any]) -> Sequence[int]:
        candidate_rows = list(payload["candidates"])
        if len(candidate_rows) > self.MAX_POLICY_CANDIDATES:
            # The Rust policy compiler intentionally bounds one request to 128
            # candidates.  Preserve the original frontier order while applying
            # the same causal policy independently to each bounded slice; the
            # recursive Hept chooser consumes the concatenated mask afterward.
            truths: list[int] = []
            for offset in range(0, len(candidate_rows), self.MAX_POLICY_CANDIDATES):
                chunk = dict(payload)
                chunk["candidates"] = candidate_rows[
                    offset : offset + self.MAX_POLICY_CANDIDATES
                ]
                truths.extend(self(chunk))
            return truths
        candidate_ids = [str(row["candidate_id"]) for row in candidate_rows]
        assembly_context_hash = str(
            payload.get("assembly_context_hash", payload["inventory_context_hash"])
        )
        assembly = [
            self.curriculum.assembly_evidence(
                self.evidence_level, assembly_context_hash, list(row["complete_route"])
            )
            if bool(row["terminal"]) else (0, 0)
            for row in candidate_rows
        ]
        request = {
            "schema": "HYDRA_ROUTE_CAUSAL_POLICY_REQUEST_V1",
            "context_hash": str(payload["context_hash"]),
            "candidates": [
                {
                    "candidate_id": candidate_id,
                    "terminal": bool(row["terminal"]),
                    "complete_route_pass_hits": int(passes),
                    "complete_route_fail_hits": int(failures),
                    "authority_denied": False,
                }
                for row, candidate_id, (passes, failures) in zip(
                    candidate_rows, candidate_ids, assembly
                )
            ],
        }
        request_hash = _canonical_hash(request)
        if request_hash in self.cache:
            truths = self.cache[request_hash]
            record = {
                "schema": "HYDRA_LIVE_ROUTE_POLICY_TRACE_V1",
                "request_sha256": request_hash,
                "context_hash": str(payload["context_hash"]),
                "assembly_context_hash": assembly_context_hash,
                "candidate_ids": candidate_ids,
                "terminal": [bool(row["terminal"]) for row in candidate_rows],
                "complete_route_evidence": [[int(p), int(f)] for p, f in assembly],
                "truths": truths,
                "bundle_sha256": self.cache_bundle_hashes[request_hash],
                "compiler_exit_code": 0,
                "cache_hit": True,
                "target_fields_present": False,
            }
            with self.trace_path.open("a", encoding="utf-8", buffering=1) as trace:
                trace.write(json.dumps(record, separators=(",", ":")) + "\n")
            self.cache_hits += 1
            return truths
        with tempfile.TemporaryDirectory(prefix="steel_brain_hydra_") as temporary:
            request_path = Path(temporary) / "request.json"
            bundle_path = Path(temporary) / "bundle.json"
            request_path.write_text(
                json.dumps(request, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            process = subprocess.run(
                [str(self.binary), "compile-route-causal-policy", str(request_path), str(bundle_path)],
                capture_output=True,
                text=True,
                check=False,
            )
            if process.returncode != 0 or not bundle_path.is_file():
                raise RuntimeError(
                    "HOLD_HYDRA_POLICY_COMPILER " + (process.stderr.strip() or str(process.returncode))
                )
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        if bundle.get("candidate_ids") != candidate_ids:
            raise RuntimeError("HOLD_HYDRA_CANDIDATE_ORDER_CHANGED")
        truths = [int(value) for value in bundle.get("truths", [])]
        if len(truths) != len(candidate_ids) or any(value not in {0, SCALE} for value in truths):
            raise RuntimeError("HOLD_HYDRA_INVALID_ROUTE_MASK")
        record = {
            "schema": "HYDRA_LIVE_ROUTE_POLICY_TRACE_V1",
            "request_sha256": request_hash,
            "context_hash": str(payload["context_hash"]),
            "assembly_context_hash": assembly_context_hash,
            "candidate_ids": candidate_ids,
            "terminal": [bool(row["terminal"]) for row in candidate_rows],
            "complete_route_evidence": [[int(p), int(f)] for p, f in assembly],
            "truths": truths,
            "bundle_sha256": _canonical_hash(bundle),
            "compiler_exit_code": process.returncode,
            "cache_hit": False,
            "target_fields_present": False,
        }
        with self.trace_path.open("a", encoding="utf-8", buffering=1) as trace:
            trace.write(json.dumps(record, separators=(",", ":")) + "\n")
        self.compilations += 1
        self.denied_candidates += sum(value == 0 for value in truths)
        self.cache[request_hash] = truths
        self.cache_bundle_hashes[request_hash] = str(record["bundle_sha256"])
        return truths

    def metrics(self) -> dict[str, object]:
        return {
            "enabled": True,
            "evidence_level": self.evidence_level,
            "binary": str(self.binary),
            "trace": str(self.trace_path),
            "compilations": self.compilations,
            "cache_hits": self.cache_hits,
            "denied_candidates": self.denied_candidates,
        }
