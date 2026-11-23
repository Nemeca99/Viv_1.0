"""Schema-locked RID_MAIN trigger emitted by the CPU automation boundary.

The trigger is an explanation envelope, not a training command. It carries
only the minimum read-only Master RID evidence needed for the Training-side
cascade governor to decide whether a bounded review may be queued. It does
not carry prompts, expert contents, weights, or authority to mutate anything.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "viv_rid_learning_trigger_v1"
PHASE = "RID_MAIN"
DOWNSTREAM_PHASES = ("RID_LEARN", "RID_TRAINING")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _closed_authority() -> dict[str, bool]:
    return {
        "training_authorized": False,
        "run_authorized": False,
        "promotion_authorized": False,
        "deployment_authorized": False,
        "dream_cycle_authorized": False,
        "live_model_changed": False,
        "rid_state_changed": False,
        "master_s_n_mutation": False,
        "knowledge_admission": False,
    }


def _master_dict(master: Any) -> Mapping[str, Any]:
    if isinstance(master, Mapping):
        return master
    to_dict = getattr(master, "to_dict", None)
    if callable(to_dict):
        value = to_dict()
        if isinstance(value, Mapping):
            return value
    return {
        "timestamp": getattr(master, "timestamp", None),
        "master_s_n": getattr(master, "master_s_n", None),
        "status": getattr(master, "status", None),
        "n_subsystems": getattr(master, "n_subsystems", None),
        "subsystems": getattr(master, "subsystems", None),
    }


def _bounded_score(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("rid_main_trigger_master_s_n_missing") from exc
    if not math.isfinite(score) or not 0.0 <= score <= 1.0:
        raise ValueError("rid_main_trigger_master_s_n_outside_unit_interval")
    return round(score, 6)


def build_main_trigger(master: Any, *, source: str) -> dict[str, Any]:
    """Build a content-minimized RID_MAIN trigger from a read-only snapshot."""
    if not str(source).strip():
        raise ValueError("rid_main_trigger_source_required")
    data = _master_dict(master)
    emitted_utc = _utc_now()
    observed_utc = str(data.get("timestamp") or "")
    master_s_n = _bounded_score(data.get("master_s_n"))
    status = str(data.get("status") or "UNKNOWN")
    subsystems = data.get("subsystems")
    if isinstance(subsystems, Mapping):
        subsystem_count = len(subsystems)
    else:
        try:
            subsystem_count = int(data.get("n_subsystems") or 0)
        except (TypeError, ValueError):
            subsystem_count = 0
    identity = {
        "schema_version": SCHEMA_VERSION,
        "phase": PHASE,
        "source": str(source),
        "observed_utc": observed_utc,
        "emitted_utc": emitted_utc,
        "master_s_n": master_s_n,
        "status": status,
    }
    trigger_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest().upper()
    return {
        "schema_version": SCHEMA_VERSION,
        "trigger_id": trigger_id,
        "phase": PHASE,
        "source": str(source),
        "emitted_utc": emitted_utc,
        "pulse_role": "begin_prompt_local_thinking_window",
        "thinking_window": {
            "same_prompt": True,
            "shared_context_ephemeral": True,
            "flush_after_prompt": True,
            "node_contents_transmitted": False,
        },
        "reason_code": "MASTER_RID_PULSE_OBSERVED",
        "reason": "read_only_master_observation_available_for_bounded_learning_review",
        "evidence": {
            "master_s_n": master_s_n,
            "master_status": status,
            "master_observed_utc": observed_utc,
            "subsystem_count": max(0, subsystem_count),
            "previous_master_s_n": None,
            "delta_from_previous": None,
            "drop_from_previous": 0.0,
        },
        "downstream_phases": list(DOWNSTREAM_PHASES),
        "authority_closed": True,
        "authority": _closed_authority(),
        "training_start_requested": False,
        "weights_created": False,
        "live_model_changed": False,
        "master_s_n_mutation": False,
        "knowledge_admission": False,
        "prompt_content_included": False,
        "expert_content_included": False,
    }


def read_previous_master_s_n(path: Path) -> float | None:
    """Read only the prior pulse's Master S_n telemetry, if present."""
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = raw.get("master_s_n")
    if value is None:
        trigger = raw.get("rid_learning_trigger")
        evidence = trigger.get("evidence") if isinstance(trigger, Mapping) else None
        value = evidence.get("master_s_n") if isinstance(evidence, Mapping) else None
    if value is None:
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return round(score, 6) if math.isfinite(score) and 0.0 <= score <= 1.0 else None


def _with_previous(
    trigger: dict[str, Any],
    previous_master_s_n: float | None,
) -> dict[str, Any]:
    if previous_master_s_n is None:
        return trigger
    previous = _bounded_score(previous_master_s_n)
    current = float(trigger["evidence"]["master_s_n"])
    delta = round(current - previous, 6)
    trigger["evidence"]["previous_master_s_n"] = previous
    trigger["evidence"]["delta_from_previous"] = delta
    trigger["evidence"]["drop_from_previous"] = round(max(0.0, -delta), 6)
    canonical = {
        key: value for key, value in trigger.items() if key != "trigger_id"
    }
    trigger["trigger_id"] = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest().upper()
    return trigger


def attach_main_trigger(
    payload: Mapping[str, Any],
    master: Any,
    *,
    source: str,
    previous_master_s_n: float | None = None,
) -> dict[str, Any]:
    """Attach one trigger to an existing CPU pulse payload."""
    result = dict(payload)
    result["rid_learning_trigger"] = _with_previous(
        build_main_trigger(master, source=source),
        previous_master_s_n,
    )
    return result


def self_test() -> dict[str, Any]:
    master = {
        "timestamp": "2026-08-09T00:00:00Z",
        "master_s_n": 0.81234567,
        "status": "ACTIVE",
        "subsystems": {"cpu": {}, "gpu": {}},
    }
    trigger = build_main_trigger(master, source="test:auto_main")
    attached = attach_main_trigger(
        {"master_s_n": 0.8123},
        master,
        source="test:auto_main",
        previous_master_s_n=0.75,
    )
    authority = trigger["authority"]
    ok = (
        trigger["phase"] == PHASE
        and trigger["downstream_phases"] == list(DOWNSTREAM_PHASES)
        and trigger["evidence"]["master_s_n"] == 0.812346
        and trigger["authority_closed"] is True
        and all(value is False for value in authority.values())
        and len(attached["rid_learning_trigger"]["trigger_id"]) == 64
        and attached["rid_learning_trigger"]["evidence"]["delta_from_previous"] == 0.062346
        and trigger["prompt_content_included"] is False
        and trigger["expert_content_included"] is False
    )
    return {
        "status": "PASS" if ok else "FAIL",
        "schema_version": SCHEMA_VERSION,
        "phase": PHASE,
        "training_start_requested": trigger["training_start_requested"],
        "workspace_writes": False,
    }


__all__ = [
    "DOWNSTREAM_PHASES",
    "PHASE",
    "SCHEMA_VERSION",
    "attach_main_trigger",
    "build_main_trigger",
    "self_test",
]


if __name__ == "__main__":
    print(json.dumps(self_test(), sort_keys=True))
