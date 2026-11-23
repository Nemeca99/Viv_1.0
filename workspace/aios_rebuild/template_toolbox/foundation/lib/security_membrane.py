"""Rust security membrane on the foundation hot path — IN before process, OUT before world."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import uuid

from lib.paths import AUTO_ARTIFACTS
from lib.security_bridge import (
    check_growth,
    check_egress,
    check_ingress,
    constitution,
    dormancy_threshold,
    enforce_morality,
    rust_available,
    rust_error,
)
try:
    from voice_core.acronym_registry import validate_acronym_usage
except ModuleNotFoundError:  # direct foundation-only test/import path
    import sys

    _viv_root = Path(__file__).resolve().parents[2]
    if str(_viv_root) not in sys.path:
        sys.path.insert(0, str(_viv_root))
    from voice_core.acronym_registry import validate_acronym_usage
from lib.entity_we_contract import decide_entity_output

EVENTS_PATH = AUTO_ARTIFACTS / "security_events_ledger.jsonl"
LEGACY_EVENTS_PATH = AUTO_ARTIFACTS / "security_events.jsonl"
BLOCKED_EGRESS = "[SECURITY OUT] output withheld — laws enforced at metal."


def membrane_status() -> dict[str, Any]:
    st = {
        "armed": rust_available(),
        "rust_error": rust_error(),
        "dormancy_threshold": dormancy_threshold(),
        "events_path": str(EVENTS_PATH),
    }
    if rust_available():
        c = constitution()
        st["version"] = c.get("version")
        st["architect"] = c.get("architect")
        st["laws"] = len(c.get("laws") or [])
        st["primes"] = len(c.get("primes") or [])
        st["integrity"] = c.get("integrity")
    return st


def tool_gate(
    tool_name: str,
    params: dict[str, Any] | str,
    s_n: float,
    forensic_buffer: str = "",
    raw_input: str = "",
) -> dict[str, Any]:
    """Rust enforce_morality for agentic tool actions — fail-closed."""
    verdict = enforce_morality(tool_name, params, s_n, forensic_buffer, raw_input)
    if not verdict.get("allowed"):
        log_event("tool_blocked", verdict, tool=tool_name)
    return verdict


def growth_gate(actuator: str, proposed_r: float, max_r: float) -> dict[str, Any]:
    """Rust growth-ceiling check through the canonical Python membrane."""
    verdict = check_growth(str(actuator), float(proposed_r), float(max_r))
    if verdict is None:
        result = {
            "allowed": False,
            "reason": "Rust growth API unavailable",
            "law": "membrane",
        }
        log_event("growth_blocked", result, actuator=actuator)
        return result
    result = dict(verdict)
    if not result.get("allowed"):
        log_event("growth_blocked", result, actuator=actuator)
    return result


def require_membrane() -> dict[str, Any] | None:
    """Fail-closed halt payload when Rust membrane is not installed."""
    if rust_available():
        return None
    return {
        "allowed": False,
        "stage": "security_membrane",
        "reason": f"Rust security_core unavailable: {rust_error()}",
        "direction": "IN",
    }


def ingress_gate(text: str, s_n: float) -> dict[str, Any]:
    from lib.viv_cpu_want_need import align_want

    aligned = align_want(str(text))
    verdict = dict(check_ingress(str(text), float(s_n)))
    verdict["want"] = aligned["want"]
    verdict["need"] = aligned["need"]
    verdict["tokens_for_gpu"] = aligned["tokens_for_gpu"]
    verdict["prompt_align"] = {
        "law": aligned["law"],
        "decide": aligned["decide"],
        "reframed": False,
        "literal_claim": aligned.get("literal_claim"),
        "angry_from_intensifier": aligned.get("angry_from_intensifier"),
        "meaning_probability_is_not_fact": True,
    }
    return verdict


def egress_gate(text: str, s_n: float, *, cpu_card: dict[str, Any] | None = None) -> dict[str, Any]:
    """Rust leave-gate. Translator verifies truth first; Rust then allows or withholds."""
    from lib.viv_cpu_universal_translator import check as translator_check

    gate = translator_check(gpu_text=str(text), cpu_card=cpu_card)
    stamp = {
        "role": gate.get("role"),
        "position": gate.get("position"),
        "class": gate.get("class"),
        "output_accuracy_ok": gate.get("output_accuracy_ok"),
        "may_emit": gate.get("may_emit"),
        "reason": gate.get("reason"),
    }
    if gate.get("class") == "HOLD_LIE" or not gate.get("may_emit"):
        return {
            "allowed": False,
            "direction": "OUT",
            "stage": "security_out",
            "reason": "translator_end_gate_denied",
            "s_n": float(s_n),
            "translator": stamp,
            "rust_consulted": False,
            "rust_used_translator": True,
        }
    verdict = dict(check_egress(str(text), float(s_n)))
    verdict["translator"] = stamp
    verdict["rust_consulted"] = True
    verdict["rust_used_translator"] = True
    return verdict


def filter_egress(
    text: str | None,
    s_n: float,
    *,
    cpu_card: dict[str, Any] | None = None,
) -> tuple[str | None, dict[str, Any] | None]:
    if text is None or not str(text).strip():
        return text, None
    acronym_violations = validate_acronym_usage(str(text))
    if acronym_violations:
        verdict = {
            "allowed": False,
            "stage": "security_out",
            "reason": "acronym_contract_violation",
            "acronym_contract": {
                "pass": False,
                "violations": acronym_violations,
            },
        }
        log_event("egress_blocked", verdict, text=str(text)[:500])
        return BLOCKED_EGRESS, verdict
    entity_decision = decide_entity_output(str(text))
    if entity_decision["decision"] != "ACCEPT":
        verdict = {
            "allowed": False,
            "stage": "security_out",
            "reason": f"entity_contract_{entity_decision['decision'].lower()}",
            "entity_contract": entity_decision,
        }
        log_event("egress_blocked", verdict, text=str(text)[:500])
        return BLOCKED_EGRESS, verdict
    verdict = egress_gate(str(text), s_n, cpu_card=cpu_card)
    if verdict.get("allowed"):
        return str(text), verdict
    log_event("egress_blocked", verdict, text=str(text)[:500])
    return BLOCKED_EGRESS, verdict


def log_event(kind: str, verdict: dict[str, Any], **extra: Any) -> None:
    row = {
        "schema_version": "viv_security_membrane_event_v1",
        "run_id": f"security_{uuid.uuid4().hex}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        "verdict": verdict,
        **extra,
    }
    try:
        # Security denials must be persisted without re-entering tool_gate.
        # The membrane has already evaluated the originating action; the
        # private sink only appends a hash-chained evidence row.
        from lib.cpu_execution_envelope import AppendOnlyExecutionLedger

        AppendOnlyExecutionLedger(EVENTS_PATH).append(row, _security_probe=False)
    except Exception:
        # Keep the membrane non-throwing if the audit sink itself is damaged.
        # This is a degraded evidence condition, never an authorization grant;
        # the caller still receives the original deny verdict.
        return


def heartbeat_stamp(s_n: float) -> dict[str, Any]:
    st = membrane_status()
    st["s_n"] = s_n
    st["ingress"] = "armed" if st["armed"] else "missing"
    st["egress"] = "armed" if st["armed"] else "missing"
    return st
