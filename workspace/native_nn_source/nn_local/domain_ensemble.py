"""Parallel AUTO/RID/UML evidence federation for Steel Brain.

Experts emit bounded evidence packets. CPU jurisdiction vetoes and the existing
nested RID settle them; no expert, vote, or transformer acquires authority.
"""
from __future__ import annotations

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .fixed_point import SCALE
from .nested_rid import settle_nested_rid
from .neuronizer import adjudicate_cpu_case

DOMAINS = ("AUTO", "RID", "UML")
PACKET_KEYS = {
    "schema", "domain", "request_sha256", "produced_ns", "verdict",
    "channels", "findings", "claims", "evidence_refs",
}
FINDING_OWNERS = {
    "grammar": "UML",
    "meaning": "UML",
    "truth": "RID",
    "provenance": "UML",
    "contradiction_clearance": "UML",
    "jurisdiction": "AUTO",
    "authority": "AUTO",
}


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest().upper()


def request_hash(request: Mapping[str, Any]) -> str:
    return canonical_hash(dict(request))


@dataclass(frozen=True)
class FederationResult:
    state: str
    reason: str
    master_s_n: int
    settlement: dict[str, Any] | None
    cpu_case: dict[str, Any] | None
    accepted_claims: tuple[str, ...]
    raw_packets: tuple[dict[str, Any], ...]
    durations_ns: dict[str, int]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "NN_DOMAIN_FEDERATION_RESULT_V1", "state": self.state,
            "reason": self.reason, "master_s_n": self.master_s_n,
            "settlement": self.settlement, "cpu_case": self.cpu_case,
            "accepted_claims": list(self.accepted_claims),
            "raw_packets": list(self.raw_packets), "durations_ns": self.durations_ns,
        }


def _hold(reason: str, packets: tuple[dict[str, Any], ...] = (),
          durations: Mapping[str, int] | None = None) -> FederationResult:
    return FederationResult("HOLD", reason, 0, None, None, (), packets, dict(durations or {}))


def validate_packet(packet: Mapping[str, Any], *, expected_domain: str,
                    expected_request: str, now_ns: int, max_age_ns: int) -> dict[str, Any]:
    if set(packet) != PACKET_KEYS or packet.get("schema") != "NN_DOMAIN_EXPERT_PACKET_V1":
        raise ValueError("MALFORMED_PACKET")
    if packet["domain"] != expected_domain or packet["request_sha256"] != expected_request:
        raise ValueError("DOMAIN_OR_REQUEST_MISMATCH")
    produced = packet["produced_ns"]
    if type(produced) is not int or produced > now_ns or now_ns - produced > max_age_ns:
        raise ValueError("STALE_OR_FUTURE_PACKET")
    if packet["verdict"] not in {"PASS", "FAIL", "HOLD"}:
        raise ValueError("INVALID_VERDICT")
    channels = packet["channels"]
    if not isinstance(channels, list) or len(channels) != 3 or any(type(value) is not int or not 0 <= value <= SCALE for value in channels):
        raise ValueError("INVALID_CHANNELS")
    if not isinstance(packet["findings"], dict) or not isinstance(packet["claims"], list):
        raise ValueError("INVALID_CONTENT")
    if not isinstance(packet["evidence_refs"], list) or not packet["evidence_refs"] or any(not isinstance(value, str) or not value for value in packet["evidence_refs"]):
        raise ValueError("MISSING_EVIDENCE")
    return dict(packet)


def synthesize(request: Mapping[str, Any], packets: list[Mapping[str, Any]], *,
               now_ns: int | None = None, max_age_ns: int = 1_000_000_000,
               minimum_master_s_n: int = 700_000,
               durations_ns: Mapping[str, int] | None = None) -> FederationResult:
    expected = request_hash(request)
    current = time.monotonic_ns() if now_ns is None else int(now_ns)
    raw = tuple(dict(packet) for packet in packets)
    if len(raw) != 3 or {str(packet.get("domain")) for packet in raw} != set(DOMAINS):
        return _hold("MISSING_OR_DUPLICATE_DOMAIN", raw, durations_ns)
    by_domain: dict[str, dict[str, Any]] = {}
    try:
        for domain in DOMAINS:
            matches = [packet for packet in raw if packet.get("domain") == domain]
            if len(matches) != 1:
                raise ValueError("MISSING_OR_DUPLICATE_DOMAIN")
            by_domain[domain] = validate_packet(matches[0], expected_domain=domain,
                                                expected_request=expected, now_ns=current,
                                                max_age_ns=max_age_ns)
    except ValueError as exc:
        return _hold(str(exc), raw, durations_ns)

    # AUTO: domain failures cannot be averaged away by two unrelated passes.
    for domain in DOMAINS:
        if by_domain[domain]["verdict"] != "PASS":
            state = "FAIL" if by_domain[domain]["verdict"] == "FAIL" else "HOLD"
            return FederationResult(state, f"{domain}_{by_domain[domain]['verdict']}", 0,
                                    None, None, (), raw, dict(durations_ns or {}))

    findings: dict[str, Any] = {}
    for key, owner in FINDING_OWNERS.items():
        if key not in by_domain[owner]["findings"]:
            return _hold(f"MISSING_{owner}_{key.upper()}", raw, durations_ns)
        findings[key] = by_domain[owner]["findings"][key]
    try:
        cpu_case = adjudicate_cpu_case(findings)
    except ValueError:
        return _hold("INVALID_CPU_CASE", raw, durations_ns)
    if cpu_case["state"] != "PASS":
        return FederationResult(cpu_case["state"], cpu_case["reason"], 0, None,
                                cpu_case, (), raw, dict(durations_ns or {}))

    settlement = settle_nested_rid(*(tuple(by_domain[domain]["channels"]) for domain in DOMAINS))
    master_s_n = int(settlement.master.quality)
    if settlement.state != "PASS":
        return FederationResult("HOLD", "RID_UNSETTLED", master_s_n,
                                settlement.as_dict(), cpu_case, (), raw, dict(durations_ns or {}))
    if master_s_n < minimum_master_s_n:
        return FederationResult("HOLD", "MASTER_S_N_BELOW_FLOOR", master_s_n,
                                settlement.as_dict(), cpu_case, (), raw, dict(durations_ns or {}))
    # AUTO: synthesis accepts only claims independently exposed by every domain;
    # one expert cannot smuggle an unchecked segment into the final surface.
    claim_sets = [set(str(claim) for claim in by_domain[domain]["claims"] if str(claim)) for domain in DOMAINS]
    claims = tuple(sorted(set.intersection(*claim_sets)))
    if not claims:
        return _hold("NO_CROSS_DOMAIN_CLAIM_CONSENSUS", raw, durations_ns)
    return FederationResult("PASS", "CPU_ACCEPTED_DOMAIN_FEDERATION", master_s_n,
                            settlement.as_dict(), cpu_case, claims, raw, dict(durations_ns or {}))


def run_parallel(request: Mapping[str, Any], experts: Mapping[str, Callable[[Mapping[str, Any]], Mapping[str, Any]]], *,
                 timeout_seconds: float = 1.0, minimum_master_s_n: int = 700_000) -> FederationResult:
    if set(experts) != set(DOMAINS) or timeout_seconds <= 0:
        return _hold("INVALID_EXPERT_SET_OR_TIMEOUT")
    executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="nn-domain")
    started: dict[str, int] = {}
    futures = {}
    for domain in DOMAINS:
        started[domain] = time.monotonic_ns()
        futures[executor.submit(experts[domain], dict(request))] = domain
    done, pending = wait(futures, timeout=timeout_seconds)
    durations = {futures[future]: time.monotonic_ns() - started[futures[future]] for future in done}
    if pending:
        for future in pending:
            future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        return _hold("EXPERT_TIMEOUT", durations=durations)
    packets = []
    try:
        for future in done:
            packets.append(dict(future.result()))
    except Exception as exc:
        executor.shutdown(wait=True)
        return _hold("EXPERT_EXCEPTION:" + type(exc).__name__, durations=durations)
    executor.shutdown(wait=True)
    return synthesize(request, packets, minimum_master_s_n=minimum_master_s_n,
                      durations_ns=durations)


def majority_baseline(packets: list[Mapping[str, Any]]) -> str:
    """Deliberately weak comparison: demonstrates why voting is insufficient."""
    return "PASS" if sum(packet.get("verdict") == "PASS" for packet in packets) >= 2 else "HOLD"


__all__ = ["DOMAINS", "FederationResult", "majority_baseline", "request_hash", "run_parallel", "synthesize", "validate_packet"]
