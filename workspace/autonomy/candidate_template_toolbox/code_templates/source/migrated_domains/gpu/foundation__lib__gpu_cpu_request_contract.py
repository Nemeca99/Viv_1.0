"""Schema-locked GPU request / CPU approval handshake.

The GPU is allowed to ask for bounded CPU review of an existing sealed option.
It is never allowed to create an option, grant authority, resolve truth, or
execute an action.  The CPU response is a decision about the request; any
later action still requires the existing CPU/Rust gates.
"""
from __future__ import annotations

from hashlib import sha256
import json
import math
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = "viv_gpu_cpu_request_cpu_approval_v1"
REQUEST_KIND = "REQUEST_CPU_REVIEW"
GPU_AUTHORITY = "REQUEST_ONLY"
_REQUEST_KEYS = {
    "schema_version",
    "request_id",
    "request_kind",
    "gpu_authority",
    "lattice_id",
    "lattice_sha256",
    "route",
    "selector_sha256",
    "rankings",
    "requested_option_id",
    "requested_authority",
    "action_requested",
    "shared_hidden_context",
    "recursive_callback",
}


class GpuCpuRequestError(ValueError):
    """Raised when a GPU request cannot be formed from a sealed lattice."""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return sha256(_canonical(value).encode("utf-8")).hexdigest().upper()


def _finite_score(value: Any) -> float:
    score = float(value)
    if not math.isfinite(score):
        raise GpuCpuRequestError("gpu_request_nonfinite_score")
    return score


def _sealed_option_ids(lattice: Mapping[str, Any]) -> tuple[str, ...]:
    if not isinstance(lattice, Mapping):
        raise GpuCpuRequestError("gpu_request_lattice_object_required")
    if bool(lattice.get("runtime_answer_key_present")) or "expected_option_id_external" in lattice:
        raise GpuCpuRequestError("gpu_request_answer_key_in_runtime_lattice")
    options = lattice.get("options")
    if not isinstance(options, Sequence) or isinstance(options, (str, bytes)) or not options:
        raise GpuCpuRequestError("gpu_request_lattice_options_required")
    option_ids = tuple(str(option.get("option_id")) for option in options if isinstance(option, Mapping))
    if len(option_ids) != len(options) or any(not option_id for option_id in option_ids):
        raise GpuCpuRequestError("gpu_request_option_id_invalid")
    if len(set(option_ids)) != len(option_ids):
        raise GpuCpuRequestError("gpu_request_option_id_duplicate")
    return option_ids


def build_gpu_request(
    lattice: Mapping[str, Any],
    rankings: Iterable[Mapping[str, Any]],
    *,
    route: str,
    selector_sha256: str,
) -> dict[str, Any]:
    """Create a GPU request that references only options in ``lattice``."""
    option_ids = set(_sealed_option_ids(lattice))
    if route not in {"serial", "fanout_4"}:
        raise GpuCpuRequestError("gpu_request_route_invalid")
    ranking_rows = []
    for row in rankings:
        if not isinstance(row, Mapping):
            raise GpuCpuRequestError("gpu_request_ranking_object_required")
        option_id = str(row.get("option_id") or "")
        if option_id not in option_ids:
            raise GpuCpuRequestError("gpu_request_option_not_in_sealed_lattice")
        ranking_rows.append({"option_id": option_id, "score": _finite_score(row.get("score"))})
    if {row["option_id"] for row in ranking_rows} != option_ids:
        raise GpuCpuRequestError("gpu_request_ranking_coverage_invalid")
    ranking_rows.sort(key=lambda row: (-float(row["score"]), str(row["option_id"])))
    body = {
        "schema_version": SCHEMA_VERSION,
        "request_kind": REQUEST_KIND,
        "gpu_authority": GPU_AUTHORITY,
        "lattice_id": str(lattice.get("lattice_id") or ""),
        "lattice_sha256": str(lattice.get("lattice_sha256") or ""),
        "route": route,
        "selector_sha256": str(selector_sha256),
        "rankings": ranking_rows,
        "requested_option_id": ranking_rows[0]["option_id"],
        "requested_authority": "NONE",
        "action_requested": False,
        "shared_hidden_context": False,
        "recursive_callback": False,
    }
    if not body["lattice_id"] or not body["lattice_sha256"] or not body["selector_sha256"]:
        raise GpuCpuRequestError("gpu_request_binding_missing")
    body["request_id"] = _digest(body)
    return body


def cpu_approve_gpu_request(
    request: Mapping[str, Any],
    lattice: Mapping[str, Any],
    *,
    verified_option_ids: Iterable[str] = (),
    evidence_sufficient: bool = False,
    law8_trace_valid: bool = True,
    evidence_source: str = "NONE",
    self_generated_evidence: bool = False,
    reused_gpu_output_as_evidence: bool = False,
) -> dict[str, Any]:
    """Validate a GPU request and return the CPU-owned approval decision."""
    base = {
        "schema_version": SCHEMA_VERSION,
        "request_id": request.get("request_id") if isinstance(request, Mapping) else None,
        "decision": "REJECT_INVALID_REQUEST",
        "cpu_authority": True,
        "gpu_resolved_truth": False,
        "authority_changed": False,
        "action_executed": False,
        "law8_trace_valid": bool(law8_trace_valid),
        "epistemic_question": "Do I have enough information to verify this claim or impact?",
        "evidence_sufficient": bool(evidence_sufficient),
        "evidence_source": str(evidence_source),
        "self_generated_evidence": bool(self_generated_evidence),
        "reused_gpu_output_as_evidence": bool(reused_gpu_output_as_evidence),
    }
    try:
        if not isinstance(request, Mapping) or set(request) != _REQUEST_KEYS:
            raise GpuCpuRequestError("gpu_request_schema_keys_invalid")
        option_ids = set(_sealed_option_ids(lattice))
        if request.get("schema_version") != SCHEMA_VERSION or request.get("request_kind") != REQUEST_KIND:
            raise GpuCpuRequestError("gpu_request_schema_invalid")
        if request.get("gpu_authority") != GPU_AUTHORITY or request.get("requested_authority") != "NONE":
            raise GpuCpuRequestError("gpu_request_authority_invalid")
        if request.get("action_requested") is not False or request.get("shared_hidden_context") is not False or request.get("recursive_callback") is not False:
            raise GpuCpuRequestError("gpu_request_forbidden_behavior")
        if str(request.get("lattice_id")) != str(lattice.get("lattice_id")) or str(request.get("lattice_sha256")) != str(lattice.get("lattice_sha256")):
            raise GpuCpuRequestError("gpu_request_lattice_binding_invalid")
        rankings = request.get("rankings")
        if not isinstance(rankings, Sequence) or isinstance(rankings, (str, bytes)):
            raise GpuCpuRequestError("gpu_request_rankings_invalid")
        normalized = [{"option_id": str(row.get("option_id")), "score": _finite_score(row.get("score"))} for row in rankings if isinstance(row, Mapping)]
        if len(normalized) != len(rankings) or {row["option_id"] for row in normalized} != option_ids:
            raise GpuCpuRequestError("gpu_request_rankings_coverage_invalid")
        normalized.sort(key=lambda row: (-float(row["score"]), str(row["option_id"])))
        if str(request.get("requested_option_id")) != normalized[0]["option_id"]:
            raise GpuCpuRequestError("gpu_request_requested_option_mismatch")
        unsigned = dict(request)
        unsigned.pop("request_id", None)
        if str(request.get("request_id")) != _digest(unsigned):
            raise GpuCpuRequestError("gpu_request_id_invalid")
        if not bool(law8_trace_valid):
            raise GpuCpuRequestError("gpu_request_law8_trace_invalid")
        if bool(evidence_sufficient) and (
            str(evidence_source) != "EXTERNAL_CPU_RECEIPT"
            or bool(self_generated_evidence)
            or bool(reused_gpu_output_as_evidence)
        ):
            base["decision"] = "HOLD_SELF_REINFORCEMENT_GUARD"
            return base
        verified = {str(value) for value in verified_option_ids}
        selected = str(request["requested_option_id"])
        base["requested_option_id"] = selected
        if bool(evidence_sufficient) and selected in verified:
            base["decision"] = "APPROVE_CPU_VERIFIED_SELECTION"
        elif bool(evidence_sufficient):
            base["decision"] = "REJECT_CPU_VERIFIED_MISMATCH"
        else:
            base["decision"] = "APPROVE_FOR_CPU_RESOLUTION"
    except (GpuCpuRequestError, TypeError, ValueError):
        base["requested_option_id"] = None
    return base
