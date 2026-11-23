"""Deterministic CPU conflict sets for bounded probabilistic exploration.

A conflict set is not a pair of facts.  It contains one CPU-sealed intent,
verified evidence, and explicitly typed hypotheses.  GPU output may propose a
resolution or a discriminating test, but only this CPU contract can return a
decision state.  No authority or fact can be minted by lane agreement.
"""
from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "viv_cpu_conflict_set_v1"
HYPOTHESIS_STATUS = "DELIBERATE_COUNTERFACTUAL_NOT_FACT"
RESOLUTION_STATES = frozenset({
    "RESOLVED_CLAIM",
    "RESOLVED_COUNTERCLAIM",
    "UNRESOLVED_HOLD",
    "SAFE_TEST_REQUIRED",
    "ASK_ARCHITECT",
})


def _digest(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest().upper()


def build_conflict_set(
    *,
    conflict_id: str,
    literal_intent: str,
    claim: str,
    counterclaim: str,
    verified_evidence: Sequence[str],
    missing_evidence: Sequence[str],
    invariants: Sequence[str],
) -> dict[str, Any]:
    values = {
        "schema_version": SCHEMA_VERSION,
        "conflict_id": str(conflict_id).strip(),
        "literal_intent": str(literal_intent).strip(),
        "claim": {
            "text": str(claim).strip(),
            "status": "HYPOTHESIS_PENDING_EVIDENCE",
            "fact_authority": False,
        },
        "counterclaim": {
            "text": str(counterclaim).strip(),
            "status": HYPOTHESIS_STATUS,
            "fact_authority": False,
        },
        "verified_evidence": [str(value).strip() for value in verified_evidence if str(value).strip()],
        "missing_evidence": [str(value).strip() for value in missing_evidence if str(value).strip()],
        "invariants": [str(value).strip() for value in invariants if str(value).strip()],
        "gpu_role": "PROPOSE_ANALYSIS_OR_DISCRIMINATING_TEST_ONLY",
        "cpu_resolution_authority": True,
        "gpu_resolution_authority": False,
        "recursive_spawn_allowed": False,
    }
    if not values["conflict_id"] or not values["literal_intent"]:
        raise ValueError("cpu_conflict_set_identity_missing")
    if not values["claim"]["text"] or not values["counterclaim"]["text"]:
        raise ValueError("cpu_conflict_set_hypothesis_missing")
    if values["claim"]["text"].casefold() == values["counterclaim"]["text"].casefold():
        raise ValueError("cpu_conflict_set_hypotheses_identical")
    if not values["invariants"]:
        raise ValueError("cpu_conflict_set_invariant_required")
    values["conflict_sha256"] = _digest(values)
    return values


def resolve_conflict_set(
    conflict: Mapping[str, Any],
    *,
    requested_state: str,
    cited_evidence: Sequence[str],
) -> dict[str, Any]:
    state = str(requested_state).strip().upper()
    if state not in RESOLUTION_STATES:
        raise ValueError("cpu_conflict_set_resolution_state_invalid")
    verified = set(str(value) for value in conflict.get("verified_evidence") or ())
    cited = [str(value) for value in cited_evidence]
    invented = sorted(set(cited) - verified)
    missing = list(conflict.get("missing_evidence") or ())
    evidence_sufficient = not missing and not invented and bool(cited)
    if state in {"RESOLVED_CLAIM", "RESOLVED_COUNTERCLAIM"} and not evidence_sufficient:
        final_state = "UNRESOLVED_HOLD"
        reason = "resolution_requested_without_sufficient_verified_evidence"
    else:
        final_state = state
        reason = "cpu_resolution_admitted"
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "conflict_sha256": str(conflict.get("conflict_sha256") or ""),
        "requested_state": state,
        "final_state": final_state,
        "cited_evidence": cited,
        "invented_evidence": invented,
        "missing_evidence": missing,
        "evidence_sufficient": evidence_sufficient,
        "reason": reason,
        "authority": "cpu_deterministic",
        "gpu_authority": False,
    }
    receipt["receipt_sha256"] = _digest(receipt)
    return receipt


__all__ = [
    "build_conflict_set",
    "resolve_conflict_set",
    "HYPOTHESIS_STATUS",
    "RESOLUTION_STATES",
    "SCHEMA_VERSION",
]
