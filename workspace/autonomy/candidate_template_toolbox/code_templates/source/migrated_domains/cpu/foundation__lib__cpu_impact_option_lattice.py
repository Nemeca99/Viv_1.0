"""Deterministic CPU option lattice for probabilistic GPU impact selection.

The CPU owns option identity, provenance, invariants, and final resolution.  A
GPU selector may return scores for existing option ids, but it cannot add an
option, convert a counterfactual into fact, approve an action, or change
authority.  Offline benchmark labels are deliberately separated from the
runtime lattice so an expected answer cannot silently become runtime truth.
"""
from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = "cpu_impact_option_lattice_v1"
ALLOWED_KINDS = frozenset({"candidate", "distractor", "counterfactual"})
ALLOWED_LANES = frozenset(
    {"direct_effects", "security_rights", "cost_resources", "reversibility_downstream"}
)


def _canonical(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(payload: Mapping[str, Any]) -> str:
    return sha256(_canonical(payload).encode("utf-8")).hexdigest().upper()


def build_option_lattice(
    *,
    lattice_id: str,
    literal_intent: str,
    options: Sequence[Mapping[str, str]],
    invariants: Iterable[str] = (),
) -> dict[str, Any]:
    """Seal a CPU-authored option set without embedding an answer key."""

    lattice_id = str(lattice_id).strip()
    literal_intent = str(literal_intent).strip()
    if not lattice_id or not literal_intent:
        raise ValueError("impact_lattice_id_and_intent_required")
    if not 2 <= len(options) <= 16:
        raise ValueError("impact_lattice_option_count_out_of_bounds")

    sealed: list[dict[str, Any]] = []
    ids: set[str] = set()
    texts: set[str] = set()
    for raw in options:
        option_id = str(raw.get("option_id") or "").strip()
        text = str(raw.get("text") or "").strip()
        kind = str(raw.get("kind") or "candidate").strip()
        lane = str(raw.get("lane") or "direct_effects").strip()
        if not option_id or not text:
            raise ValueError("impact_lattice_option_id_and_text_required")
        if option_id in ids or text.casefold() in texts:
            raise ValueError("impact_lattice_options_must_be_unique")
        if kind not in ALLOWED_KINDS:
            raise ValueError("impact_lattice_option_kind_invalid")
        if lane not in ALLOWED_LANES:
            raise ValueError("impact_lattice_option_lane_invalid")
        ids.add(option_id)
        texts.add(text.casefold())
        sealed.append(
            {
                "option_id": option_id,
                "text": text,
                "kind": kind,
                "lane": lane,
                "cpu_authored": True,
                "gpu_fact_authority": False,
                "gpu_execution_authority": False,
            }
        )

    body = {
        "schema_version": SCHEMA_VERSION,
        "lattice_id": lattice_id,
        "literal_intent": literal_intent,
        "options": sealed,
        "invariants": sorted({str(value).strip() for value in invariants if str(value).strip()}),
        "cpu_option_authority": True,
        "gpu_role": "rank_existing_options_only",
        "gpu_may_create_options": False,
        "gpu_may_resolve_truth": False,
        "recursive_spawn_allowed": False,
        "shared_hidden_context": False,
    }
    return {**body, "lattice_sha256": _digest(body)}


def attach_offline_answer_key(
    lattice: Mapping[str, Any], *, expected_option_id: str
) -> dict[str, Any]:
    """Create an evaluation-only wrapper; never pass this object to runtime."""

    expected_option_id = str(expected_option_id).strip()
    option_ids = {str(row["option_id"]) for row in lattice.get("options", ())}
    if expected_option_id not in option_ids:
        raise ValueError("impact_lattice_answer_not_in_options")
    return {
        "schema_version": "cpu_impact_option_lattice_offline_label_v1",
        "lattice": dict(lattice),
        "expected_option_id": expected_option_id,
        "runtime_admissible": False,
        "training_or_evaluation_only": True,
    }


def resolve_ranked_options(
    lattice: Mapping[str, Any],
    rankings: Sequence[Mapping[str, Any]],
    *,
    verified_option_ids: Iterable[str] = (),
    minimum_margin: float = 0.0,
    authority_claim: bool = False,
) -> dict[str, Any]:
    """CPU resolution of GPU scores; absent verification always produces HOLD."""

    body = {key: value for key, value in lattice.items() if key != "lattice_sha256"}
    if lattice.get("schema_version") != SCHEMA_VERSION or lattice.get("lattice_sha256") != _digest(body):
        raise ValueError("impact_lattice_seal_invalid")
    option_map = {str(row["option_id"]): row for row in lattice.get("options", ())}
    if not rankings:
        raise ValueError("impact_lattice_rankings_required")
    ranked_ids = [str(row.get("option_id") or "") for row in rankings]
    if len(ranked_ids) != len(set(ranked_ids)) or any(value not in option_map for value in ranked_ids):
        raise ValueError("impact_lattice_rankings_invalid")
    ordered = sorted(rankings, key=lambda row: (-float(row["score"]), str(row["option_id"])))
    top = ordered[0]
    runner_up = ordered[1] if len(ordered) > 1 else {"score": float("-inf")}
    margin = float(top["score"]) - float(runner_up["score"])
    selected_id = str(top["option_id"])
    selected = option_map[selected_id]
    verified = selected_id in {str(value) for value in verified_option_ids}
    counterfactual = selected.get("kind") == "counterfactual"
    enough = bool(verified and not counterfactual and margin >= float(minimum_margin))
    if authority_claim and not verified:
        state = "HOLD_UNVERIFIED_CLAIM"
    elif enough:
        state = "CPU_VERIFIED_SELECTION"
    else:
        state = "HOLD_INSUFFICIENT_EVIDENCE"
    return {
        "selected_option_id": selected_id,
        "selected_kind": selected.get("kind"),
        "score_margin": margin,
        "minimum_margin": float(minimum_margin),
        "selected_option_verified": verified,
        "epistemic_question": "Do I have enough information to verify this claim or impact?",
        "epistemic_answer": "YES" if enough else "NO",
        "final_state": state,
        "authority_changed": False,
        "action_executed": False,
        "gpu_resolved_truth": False,
    }
