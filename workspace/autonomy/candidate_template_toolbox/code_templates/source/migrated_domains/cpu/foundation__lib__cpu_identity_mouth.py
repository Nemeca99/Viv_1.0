"""Read-only CPU-owned identity speech entry point for Viv.

This facade deliberately keeps the small character model in the renderer role:
the CPU routes a reviewed identity intent, chooses the canonical prompt,
provides the authorized meaning, and validates the proposed wording. Unsupported
queries are returned to the caller as unrouted rather than being guessed at.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from lib.cpu_identity_router import route_identity_query
from lib.cpu_mouth_contract import build_render_envelope, render_with_cpu_validation


IDENTITY_MOUTH_VERSION = "cpu_identity_mouth_v3"
IdentityRenderer = Callable[[str], str]


def _envelope(route: Mapping[str, Any], query: str) -> dict[str, Any]:
    intent_id = str(route["intent_id"])
    authorized_text = str(route["authorized_text"])
    values: dict[str, Any] = {
        "query": query,
        "mode": str(route["mode"]),
        "facts": [
            {
                "id": f"identity_{intent_id}",
                "text": authorized_text,
                "source": str(route["router_version"]),
                "confidence": "verified",
                "required_terms": (
                    ("I am Viv", "Adaptive Intelligent Operating System", "not human")
                    if intent_id == "identity"
                    else ()
                ),
            }
        ],
        "decision": {"id": f"identity_{intent_id}_render", "value": "render_cpu_identity_meaning"},
        "provenance": {
            "source": IDENTITY_MOUTH_VERSION,
            "intent_id": intent_id,
            "router_version": str(route["router_version"]),
            "confidence": "verified",
        },
        "fallback_text": authorized_text,
        "identity": {"name": "Viv", "owner": "cpu"},
    }
    if intent_id == "health":
        values["freshness"] = {"state": "unverified", "max_age_s": 3.0}
    return build_render_envelope(**values)


def render_identity_query(
    query: str,
    renderer: IdentityRenderer,
    *,
    retry_renderer: IdentityRenderer | None = None,
) -> dict[str, Any]:
    """Route and safely render one reviewed identity/personality query.

    ``renderer`` receives only the CPU-selected canonical query string. It
    cannot receive live state or authority through this API. The returned
    result is accepted only after the CPU mouth contract validates it; otherwise
    the CPU-authored fallback is returned. An unsupported query is fail-closed
    before any renderer call.
    """
    route = route_identity_query(query)
    if not route.get("ok"):
        return {
            "accepted": False,
            "state": route.get("state"),
            "reason": route.get("reason"),
            "route": route,
            "renderer_called": False,
            "authority": {"decision_authority": "cpu", "renderer_authority": False},
            "identity_mouth_version": IDENTITY_MOUTH_VERSION,
            "live_runtime_mutation": False,
            "deployment_changed": False,
        }

    canonical_query = str(route["canonical_query"])
    envelope = _envelope(route, str(query or ""))
    result = render_with_cpu_validation(
        envelope,
        lambda _, canonical=canonical_query: renderer(canonical),
        retry_renderer=(
            None
            if retry_renderer is None
            else lambda _, canonical=canonical_query: retry_renderer(canonical)
        ),
    )
    result["state"] = "ROUTED"
    result["route"] = route
    result["identity_mouth_version"] = IDENTITY_MOUTH_VERSION
    result["renderer_called"] = True
    result["live_runtime_mutation"] = False
    result["deployment_changed"] = False
    return result


__all__ = ["IDENTITY_MOUTH_VERSION", "render_identity_query"]
