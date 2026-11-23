"""Candidate deterministic gateway separating language parsing from authority minting."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Mapping


def canonical_payload_hash(tool: str, inputs: Mapping[str, Any]) -> str:
    payload = {"tool": str(tool), "inputs": dict(inputs)}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest().upper()


def canonical_proposition_hash(proposition: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(proposition), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest().upper()


def resolve_user_representation(
    hypotheses: list[Mapping[str, Any]],
    *,
    actor_ref: str,
    turn_id: str,
    prior_proposition: Mapping[str, Any] | None = None,
    correction_authorized: bool = False,
) -> dict[str, Any]:
    """Admit one deterministic user-side proposition or HOLD.

    Hypotheses may come from a probabilistic parser, but only CPU-admitted,
    canonical propositions cross the mediator boundary.  Confidence never
    grants admission and raw utterances are never forwarded.
    """
    admitted: dict[str, dict[str, Any]] = {}
    for hypothesis in hypotheses:
        if hypothesis.get("cpu_admitted") is not True:
            continue
        proposition = hypothesis.get("proposition")
        if not isinstance(proposition, Mapping) or not proposition:
            continue
        canonical = dict(proposition)
        admitted[canonical_proposition_hash(canonical)] = canonical
    if not admitted:
        return {"state": "HOLD", "reason": "HOLD_NO_DETERMINISTIC_USER_PROPOSITION", "envelope": None}
    if len(admitted) != 1:
        return {
            "state": "HOLD", "reason": "HOLD_AMBIGUOUS_USER_PROPOSITION",
            "candidate_hashes": sorted(admitted), "envelope": None,
        }
    proposition_sha256, proposition = next(iter(admitted.items()))
    matching = [
        hypothesis for hypothesis in hypotheses
        if hypothesis.get("cpu_admitted") is True
        and isinstance(hypothesis.get("proposition"), Mapping)
        and canonical_proposition_hash(hypothesis["proposition"]) == proposition_sha256
        and hypothesis.get("route")
    ]
    planned_route = None
    if matching:
        by_route: dict[str, Mapping[str, Any]] = {}
        for hypothesis in matching:
            route = list(hypothesis["route"])
            route_sha = hashlib.sha256(
                json.dumps(route, separators=(",", ":")).encode("utf-8")
            ).hexdigest().upper()
            by_route[route_sha] = hypothesis
        if len(by_route) > 1:
            best_rank = max(int(item.get("cpu_evidence_rank", 0)) for item in by_route.values())
            winners = [item for item in by_route.values() if int(item.get("cpu_evidence_rank", 0)) == best_rank]
            if len(winners) != 1:
                return {
                    "state": "HOLD", "reason": "HOLD_UNRESOLVED_NEURON_PATH_SPLIT",
                    "candidate_route_hashes": sorted(by_route), "envelope": None,
                }
            planned_route = list(winners[0]["route"])
        else:
            planned_route = list(next(iter(by_route.values()))["route"])
    supersedes_sha256 = None
    if prior_proposition is not None:
        prior = dict(prior_proposition)
        same_relation = prior.get("relation") == proposition.get("relation")
        contradicted = same_relation and prior.get("value") != proposition.get("value")
        if contradicted and not correction_authorized:
            return {
                "state": "HOLD", "reason": "HOLD_UNRESOLVED_USER_CONTRADICTION",
                "prior_sha256": canonical_proposition_hash(prior),
                "candidate_sha256": proposition_sha256, "envelope": None,
            }
        if contradicted:
            supersedes_sha256 = canonical_proposition_hash(prior)
    envelope = {
        "schema": "VIV_DETERMINISTIC_USER_REPRESENTATION_V1",
        "actor_ref": str(actor_ref), "turn_id": str(turn_id),
        "proposition": proposition, "proposition_sha256": proposition_sha256,
        "expected_semantics": proposition,
        "planned_neuron_route": planned_route,
        "supersedes_sha256": supersedes_sha256,
        "authority_conferred": False,
    }
    return {"state": "PASS", "reason": "PASS_DETERMINISTIC_USER_PROPOSITION", "envelope": envelope}


def verify_mediated_assistant_response(
    mediator_result: Mapping[str, Any],
    *,
    assistant_proposition: Mapping[str, Any] | None,
    ingress_receipt: Mapping[str, Any],
    output_case: Mapping[str, Any],
    verify_egress: Callable[[Mapping[str, Any], Mapping[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """Admit assistant semantics only when they match the input-side UML case.

    The probabilistic assistant may propose a response, but it cannot revise the
    proposition, inherit a different effect, or bypass the independently bound
    output gate.  This function grants no capability and performs no effect.
    """
    if mediator_result.get("state") != "PASS":
        return {
            "state": "HOLD",
            "reason": "HOLD_MEDIATOR_INPUT_NOT_ADMITTED",
            "egress": None,
            "authority_conferred": False,
        }
    envelope = mediator_result.get("envelope")
    if not isinstance(envelope, Mapping) or envelope.get("authority_conferred") is not False:
        return {
            "state": "HOLD",
            "reason": "HOLD_MEDIATOR_ENVELOPE_INVALID",
            "egress": None,
            "authority_conferred": False,
        }
    expected = envelope.get("expected_semantics")
    if not isinstance(expected, Mapping) or not expected:
        return {
            "state": "HOLD",
            "reason": "HOLD_EXPECTED_SEMANTICS_MISSING",
            "egress": None,
            "authority_conferred": False,
        }
    if not isinstance(assistant_proposition, Mapping) or not assistant_proposition:
        return {
            "state": "HOLD",
            "reason": "HOLD_ASSISTANT_SEMANTICS_MISSING",
            "egress": None,
            "authority_conferred": False,
        }
    expected_hash = canonical_proposition_hash(expected)
    # UML semantics must remain bound to both the admitted proposition and the
    # ingress proceeding; comparing two mutable output-side objects is not enough.
    proposition = envelope.get("proposition")
    lock = ingress_receipt.get("mode_lock")
    claimed_hash = str(envelope.get("proposition_sha256", "")).upper()
    if (
        not isinstance(proposition, Mapping)
        or canonical_proposition_hash(proposition) != expected_hash
        or claimed_hash != expected_hash
        or not isinstance(lock, Mapping)
        or str(lock.get("intent_sha256", "")).upper() != expected_hash
        or not isinstance(envelope.get("actor_ref"), str)
        or not envelope.get("actor_ref")
        or envelope.get("actor_ref") != lock.get("authorized_actor")
        or not isinstance(envelope.get("turn_id"), str)
        or not envelope.get("turn_id")
        or envelope.get("turn_id") != lock.get("turn_id")
    ):
        return {
            "state": "HOLD",
            "reason": "HOLD_MEDIATOR_PROPOSITION_BINDING_MISMATCH",
            "egress": None,
            "authority_conferred": False,
        }
    observed_hash = canonical_proposition_hash(assistant_proposition)
    if observed_hash != expected_hash:
        same_relation = expected.get("relation") == assistant_proposition.get("relation")
        opposite_value = same_relation and expected.get("value") != assistant_proposition.get("value")
        return {
            "state": "FAIL" if opposite_value else "HOLD",
            "reason": (
                "FAIL_ASSISTANT_CONTRADICTED_EXPECTED_SEMANTICS"
                if opposite_value else "HOLD_ASSISTANT_SEMANTIC_DRIFT"
            ),
            "expected_sha256": expected_hash,
            "observed_sha256": observed_hash,
            "egress": None,
            "authority_conferred": False,
        }
    egress = verify_egress(ingress_receipt, output_case)
    if egress.get("state") != "PASS":
        return {
            "state": "HOLD",
            "reason": str(egress.get("reason", "HOLD_OUTPUT_GATE_REJECTED")),
            "semantic_sha256": observed_hash,
            "egress": egress,
            "authority_conferred": False,
        }
    return {
        "state": "PASS",
        "reason": "PASS_MEDIATED_ASSISTANT_RESPONSE",
        "semantic_sha256": observed_hash,
        "egress": egress,
        "authority_conferred": False,
    }


def guarded_calculator_request(
    query: str,
    *,
    actor_ref: str,
    nonce: str,
    capability_grant: Mapping[str, Any] | None,
    extract_expression: Callable[[str], str | None],
    admit_capability: Callable[..., str],
    mint_request: Callable[..., dict[str, Any]],
    tool: str = "calculator",
) -> dict[str, Any]:
    """Parse semantics first; mint only after an independent exact grant passes."""
    expression = extract_expression(str(query or ""))
    if not expression:
        return {"state": "HOLD", "reason": "HOLD_NO_SUPPORTED_ACTION_INTENT", "request": None}
    inputs = {"expression": expression}
    payload_sha256 = canonical_payload_hash(tool, inputs)
    expected = {
        "actor_ref": str(actor_ref),
        "nonce": str(nonce),
        "capability": str(tool),
        "payload_sha256": payload_sha256,
    }
    reason = admit_capability(capability_grant, expected=expected)
    if reason != "PASS_CAPABILITY_ADMITTED":
        return {
            "state": "HOLD",
            "reason": reason,
            "semantic_intent": {"tool": tool, "inputs": inputs, "payload_sha256": payload_sha256},
            "request": None,
        }
    request = mint_request(
        tool=tool,
        inputs=inputs,
        source="operator_via_mouth",
        request_id=f"sas-{nonce}",
        note="structural_authority_gateway_admitted",
    )
    return {
        "state": "PASS",
        "reason": "PASS_INDEPENDENT_CAPABILITY",
        "semantic_intent": {"tool": tool, "inputs": inputs, "payload_sha256": payload_sha256},
        "request": request,
    }
