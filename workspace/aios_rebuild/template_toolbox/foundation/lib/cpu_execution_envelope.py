"""CPU-first execution boundary for Viv's deterministic template toolbox.

The model-facing object in this module is a plan, not source code and not a
natural-language answer.  It can select one already-approved template and
bind values for keys that the template declares.  External context is passed
by the caller and is never accepted inside the model plan.  The CPU verifies
the Rust membrane, loads the active generation through ``code_template_runtime``
and makes the execution result the primary output.

Every attempt is recorded in a hash-chained JSONL ledger.  This module exposes
append and verify operations only; it deliberately has no receipt deletion or
rewrite API.  OS/Rust operator controls remain the authority for any human
retention or deletion policy.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import threading
from typing import Any, Mapping
import uuid


EXECUTION_REQUEST_SCHEMA = "viv_cpu_execution_request_v1"
EXECUTION_RECEIPT_SCHEMA = "viv_cpu_execution_receipt_v1"
EXECUTION_LEDGER_SCHEMA = "viv_cpu_execution_ledger_v1"
TARGET_PILLARS = frozenset({"rid", "auto", "uml"})
ALLOWED_ACTIONS = frozenset({"execute", "hold"})
HOLD_CODES = frozenset(
    {
        "model_hold",
        "unknown_concept",
        "ambiguous_tie",
        "unsafe_authority",
        "malformed_request",
        "undeclared_variable",
    }
)
SEMANTIC_HOLD_REASON_MAP = {
    "missing": "malformed_request",
    "malformed": "malformed_request",
    "unsafe": "unsafe_authority",
    "review": "ambiguous_tie",
    "unknown": "unknown_concept",
}
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_ZERO_SHA256 = "0" * 64
_LEDGER_LOCK = threading.RLock()


class ExecutionEnvelopeError(ValueError):
    """A model plan, external context, or audit record is invalid."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_ledger_path() -> Path:
    """Return the normal append-only CPU execution ledger path."""
    return (
        _repo_root()
        / "foundation"
        / "artifacts"
        / "auto"
        / "code_templates"
        / "execution"
        / "execution_receipts.jsonl"
    )


def _utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _stable_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: Any) -> str:
    try:
        return _sha256_bytes(_stable_json(value).encode("utf-8"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ExecutionEnvelopeError(f"json_value_not_canonical:{exc}") from exc


def _validate_json_value(value: Any, *, label: str, _path: str = "") -> None:
    """Reject non-JSON data before it can enter a deterministic receipt."""
    path = f"{label}{_path}"
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ExecutionEnvelopeError(f"{path}_non_finite_number")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ExecutionEnvelopeError(f"{path}_mapping_keys_must_be_strings")
            _validate_json_value(item, label=label, _path=f".{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, label=label, _path=f"[{index}]")
        return
    raise ExecutionEnvelopeError(f"{path}_json_data_only")


def _safe_plan_id(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ExecutionEnvelopeError(f"{label}_invalid")
    return value


def validate_model_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize the only model-facing execution contract.

    The allow-list is intentionally closed.  In particular, ``context``,
    ``source``, ``body``, ``path``, ``code``, ``text``, and shell/process
    controls cannot enter through this boundary.
    """
    if not isinstance(plan, Mapping):
        raise ExecutionEnvelopeError("model_plan_mapping_required")
    raw = dict(plan)
    allowed = {
        "schema_version",
        "action",
        "template_id",
        "pillar",
        "variable_overrides",
        "hold_code",
    }
    extra = sorted(set(raw) - allowed)
    if extra:
        raise ExecutionEnvelopeError(f"model_plan_fields_not_allowed:{','.join(extra)}")
    if raw.get("schema_version") != EXECUTION_REQUEST_SCHEMA:
        raise ExecutionEnvelopeError("model_plan_schema_mismatch")
    action = raw.get("action")
    if action not in ALLOWED_ACTIONS:
        raise ExecutionEnvelopeError("model_plan_action_invalid")

    template_id: str | None = None
    pillar: str | None = None
    if raw.get("template_id") is not None:
        template_id = _safe_plan_id(raw.get("template_id"), label="template_id")
    if raw.get("pillar") is not None:
        pillar_value = raw.get("pillar")
        if not isinstance(pillar_value, str) or pillar_value not in TARGET_PILLARS:
            raise ExecutionEnvelopeError("pillar_invalid")
        pillar = pillar_value

    overrides = raw.get("variable_overrides", {})
    if not isinstance(overrides, Mapping):
        raise ExecutionEnvelopeError("variable_overrides_mapping_required")
    overrides = dict(overrides)
    _validate_json_value(overrides, label="variable_overrides")

    if action == "execute":
        if template_id is None:
            raise ExecutionEnvelopeError("template_id_required_for_execute")
        if pillar is None:
            raise ExecutionEnvelopeError("pillar_required_for_execute")
        if "hold_code" in raw:
            raise ExecutionEnvelopeError("hold_code_not_allowed_for_execute")
    else:
        if overrides:
            raise ExecutionEnvelopeError("hold_cannot_change_variables")
        hold_code = raw.get("hold_code", "model_hold")
        if hold_code not in HOLD_CODES:
            raise ExecutionEnvelopeError("hold_code_invalid")

    normalized: dict[str, Any] = {
        "schema_version": EXECUTION_REQUEST_SCHEMA,
        "action": action,
        "template_id": template_id,
        "pillar": pillar,
        "variable_overrides": overrides,
    }
    if action == "hold":
        normalized["hold_code"] = raw.get("hold_code", "model_hold")
    return normalized


def compile_semantic_action(
    action: Mapping[str, Any],
    *,
    resolved_template_id: str | None = None,
    pillar: str = "auto",
) -> dict[str, Any]:
    """Compile a v1/v2 semantic action into the execution request schema.

    ``select`` slots are resolved by the CPU before this function is called;
    the model never supplies a source path or function body.  ``variable`` is
    the only non-hold action that can carry model data into execution.
    """
    if not isinstance(action, Mapping):
        raise ExecutionEnvelopeError("semantic_action_mapping_required")
    raw = dict(action)
    allowed = {"kind", "template_id", "key", "value", "reason"}
    extra = sorted(set(raw) - allowed)
    if extra:
        raise ExecutionEnvelopeError(f"semantic_action_fields_not_allowed:{','.join(extra)}")
    kind = raw.get("kind")
    if kind == "hold":
        reason = str(raw.get("reason") or "malformed")
        hold_code = SEMANTIC_HOLD_REASON_MAP.get(reason)
        if hold_code is None:
            raise ExecutionEnvelopeError("semantic_hold_reason_invalid")
        return validate_model_plan(
            {
                "schema_version": EXECUTION_REQUEST_SCHEMA,
                "action": "hold",
                "hold_code": hold_code,
                "variable_overrides": {},
            }
        )
    if kind == "select":
        template_id = resolved_template_id
        if template_id is None:
            raise ExecutionEnvelopeError("semantic_select_requires_cpu_resolution")
        return validate_model_plan(
            {
                "schema_version": EXECUTION_REQUEST_SCHEMA,
                "action": "execute",
                "template_id": template_id,
                "pillar": pillar,
                "variable_overrides": {},
            }
        )
    if kind == "variable":
        template_id = raw.get("template_id")
        key = raw.get("key")
        if not isinstance(key, str) or not key:
            raise ExecutionEnvelopeError("semantic_variable_key_required")
        if not isinstance(template_id, str):
            raise ExecutionEnvelopeError("semantic_variable_template_required")
        return validate_model_plan(
            {
                "schema_version": EXECUTION_REQUEST_SCHEMA,
                "action": "execute",
                "template_id": template_id,
                "pillar": pillar,
                "variable_overrides": {key: raw.get("value")},
            }
        )
    raise ExecutionEnvelopeError("semantic_action_kind_invalid")


def _security_decision(plan: Mapping[str, Any], *, master_s_n: float) -> dict[str, Any]:
    """Ask the existing Rust membrane to admit this CPU execution."""
    try:
        foundation = _repo_root() / "foundation"
        import sys

        if str(foundation) not in sys.path:
            sys.path.insert(0, str(foundation))
        from lib.security_membrane import membrane_status, tool_gate  # type: ignore

        membrane = dict(membrane_status())
        integrity = membrane.get("integrity")
        integrity_ok = isinstance(integrity, Mapping) and bool(integrity.get("ok"))
        if not membrane.get("armed") or not integrity_ok:
            return {
                "allowed": False,
                "state": "HOLD_SECURITY",
                "reason": "rust_membrane_unarmed_or_integrity_invalid",
                "membrane": membrane,
                "decision": None,
            }
        gate = dict(
            tool_gate(
                "template_execute" if plan.get("action") == "execute" else "template_hold",
                {
                    "template_id": plan.get("template_id"),
                    "pillar": plan.get("pillar"),
                    "variable_overrides": plan.get("variable_overrides") or {},
                },
                float(master_s_n),
                forensic_buffer="viv_cpu_execution_envelope",
            )
        )
        allowed = bool(gate.get("allowed"))
        return {
            "allowed": allowed,
            "state": "PASS" if allowed else "HOLD_SECURITY",
            "reason": None if allowed else str(gate.get("reason") or "rust_tool_gate_denied"),
            "membrane": membrane,
            "decision": gate,
        }
    except Exception as exc:  # noqa: BLE001 - security must fail closed
        return {
            "allowed": False,
            "state": "HOLD_SECURITY",
            "reason": f"rust_security_probe_failed:{exc}",
            "membrane": None,
            "decision": None,
        }


def _runtime_status(pillar: str | None) -> dict[str, Any]:
    if pillar is None:
        return {"state": "NOT_APPLICABLE"}
    try:
        foundation = _repo_root() / "foundation"
        import sys

        if str(foundation) not in sys.path:
            sys.path.insert(0, str(foundation))
        from lib.code_template_runtime import template_status  # type: ignore

        raw = template_status(pillar=pillar)
        if not isinstance(raw, Mapping):
            return {"state": "HOLD", "reason": "runtime_status_not_mapping"}
        template_rows = []
        for row in raw.get("templates") or []:
            if isinstance(row, Mapping):
                template_rows.append(
                    {
                        "template_id": row.get("template_id"),
                        "variables": list(row.get("variables") or []),
                        "target_pillars": list(row.get("target_pillars") or []),
                        "submain_order": list(row.get("submain_order") or []),
                        "source_sha256": row.get("source_sha256"),
                        "generated_sha256": row.get("generated_sha256"),
                        "active_generation": row.get("active_generation"),
                    }
                )
        return {
            "ok": bool(raw.get("ok")),
            "state": raw.get("state"),
            "active_generation": raw.get("active_generation"),
            "source_drift": raw.get("source_drift"),
            "templates": template_rows,
        }
    except Exception as exc:  # noqa: BLE001 - status is evidence, not authority
        return {"state": "HOLD", "reason": f"runtime_status_error:{exc}"}


class AppendOnlyExecutionLedger:
    """Single-writer, hash-chained JSONL evidence store.

    No update or delete method is provided.  The chain makes omission,
    reordering, and in-place tampering observable.  Human-only retention or
    deletion still belongs to the host/Rust operator boundary; Python code
    must not claim that a normal file handle can enforce that distinction.
    """

    def __init__(self, path: Path | str | None = None, *, master_s_n: float = 1.0) -> None:
        self.path = Path(path) if path is not None else default_ledger_path()
        self.master_s_n = float(master_s_n)

    def _validate_path(self) -> None:
        path = self.path.resolve(strict=False)
        if self.path.exists() and (self.path.is_symlink() or os.path.islink(self.path)):
            raise ExecutionEnvelopeError("execution_ledger_reparse_path")
        cursor = path.parent
        while cursor != cursor.parent:
            if cursor.exists() and (cursor.is_symlink() or os.path.islink(cursor)):
                raise ExecutionEnvelopeError("execution_ledger_parent_reparse_path")
            cursor = cursor.parent

    def _rows(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        rows: list[dict[str, Any]] = []
        try:
            for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    raise ExecutionEnvelopeError(f"execution_ledger_blank_line:{line_number}")
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ExecutionEnvelopeError(f"execution_ledger_row_not_object:{line_number}")
                rows.append(value)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ExecutionEnvelopeError(f"execution_ledger_read_failed:{exc}") from exc
        return rows

    @staticmethod
    def _row_hash(row: Mapping[str, Any]) -> str:
        body = {key: value for key, value in row.items() if key != "receipt_sha256"}
        return _sha256_json(body)

    def append(self, receipt: Mapping[str, Any], *, _security_probe: bool = True) -> dict[str, Any]:
        """Append one receipt and fsync it; never overwrite an existing row."""
        if not isinstance(receipt, Mapping):
            raise ExecutionEnvelopeError("execution_receipt_mapping_required")
        with _LEDGER_LOCK:
            self._validate_path()
            prior_rows = self._rows()
            prior_hash = str(prior_rows[-1].get("receipt_sha256")) if prior_rows else None
            sequence = int(prior_rows[-1].get("sequence", 0)) + 1 if prior_rows else 1
            row = copy.deepcopy(dict(receipt))
            row.pop("receipt_sha256", None)
            row["ledger_schema"] = EXECUTION_LEDGER_SCHEMA
            row["sequence"] = sequence
            row["previous_receipt_sha256"] = prior_hash
            row["receipt_sha256"] = self._row_hash(row)
            line = _stable_json(row) + "\n"
            if _security_probe:
                try:
                    foundation = _repo_root() / "foundation"
                    import sys

                    if str(foundation) not in sys.path:
                        sys.path.insert(0, str(foundation))
                    from lib.security_membrane import tool_gate  # type: ignore

                    ledger_gate = dict(
                        tool_gate(
                            "write_file",
                            {
                                "path": str(self.path),
                                "operation": "append_execution_receipt",
                                "append_only": True,
                                "content_sha256": _sha256_bytes(line.encode("utf-8")),
                                "content_bytes": len(line.encode("utf-8")),
                            },
                            self.master_s_n,
                            forensic_buffer="viv_cpu_execution_ledger_append",
                        )
                    )
                except Exception as exc:  # noqa: BLE001 - audit writes fail closed
                    raise ExecutionEnvelopeError(f"execution_ledger_security_probe_failed:{exc}") from exc
            else:
                # The security membrane's own denial/audit sink cannot call
                # tool_gate recursively.  Its caller has already received the
                # Rust decision; this private path preserves that evidence in
                # the same hash-chained, no-delete ledger format.
                ledger_gate = {
                    "allowed": True,
                    "state": "SECURITY_EVENT_AUDIT_SINK",
                    "reason": "rust_decision_already_evaluated_by_membrane",
                }
            if not ledger_gate.get("allowed"):
                raise ExecutionEnvelopeError(
                    f"execution_ledger_security_denied:{ledger_gate.get('reason') or 'rust_tool_gate_denied'}"
                )
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with self.path.open("a", encoding="utf-8", newline="") as handle:
                    handle.write(line)
                    handle.flush()
                    os.fsync(handle.fileno())
            except OSError as exc:
                raise ExecutionEnvelopeError(f"execution_ledger_append_failed:{exc}") from exc
            if self._rows()[-1] != row:
                raise ExecutionEnvelopeError("execution_ledger_post_append_mismatch")
            return {
                "sequence": sequence,
                "previous_receipt_sha256": prior_hash,
                "receipt_sha256": row["receipt_sha256"],
                "path": str(self.path),
            }

    def verify(self) -> dict[str, Any]:
        """Verify the entire chain without changing it."""
        with _LEDGER_LOCK:
            self._validate_path()
            rows = self._rows()
            prior_hash: str | None = None
            seen_runs: set[str] = set()
            for expected_sequence, row in enumerate(rows, 1):
                if row.get("ledger_schema") != EXECUTION_LEDGER_SCHEMA:
                    raise ExecutionEnvelopeError(f"execution_ledger_schema_mismatch:{expected_sequence}")
                if row.get("sequence") != expected_sequence:
                    raise ExecutionEnvelopeError(f"execution_ledger_sequence_mismatch:{expected_sequence}")
                if row.get("previous_receipt_sha256") != prior_hash:
                    raise ExecutionEnvelopeError(f"execution_ledger_parent_mismatch:{expected_sequence}")
                run_id = str(row.get("run_id") or "")
                if not run_id or run_id in seen_runs:
                    raise ExecutionEnvelopeError(f"execution_ledger_run_id_invalid:{expected_sequence}")
                seen_runs.add(run_id)
                expected_hash = self._row_hash(row)
                if row.get("receipt_sha256") != expected_hash:
                    raise ExecutionEnvelopeError(f"execution_ledger_hash_mismatch:{expected_sequence}")
                prior_hash = expected_hash
            return {
                "ok": True,
                "state": "PASS" if rows else "EMPTY",
                "schema": EXECUTION_LEDGER_SCHEMA,
                "rows": len(rows),
                "head_receipt_sha256": prior_hash,
                "path": str(self.path),
                "deletion_api": "ABSENT",
                "human_retention_authority_required": True,
            }


def append_audit_receipt(
    path: Path | str,
    receipt: Mapping[str, Any],
    *,
    run_id_prefix: str = "audit",
    master_s_n: float = 1.0,
) -> dict[str, Any]:
    """Append a JSON-only row to a Rust-gated hash-chained ledger.

    Operational logs use the same append-only primitive as CPU execution
    receipts.  This helper deliberately does not expose a rewrite or delete
    path.  ``default=str`` is used only to normalize legacy-compatible
    diagnostic values before they enter the JSON ledger; source text and
    arbitrary executable objects are not accepted by the ledger itself.
    """
    if not isinstance(receipt, Mapping):
        raise ExecutionEnvelopeError("audit_receipt_mapping_required")
    try:
        normalized = json.loads(
            _stable_json(dict(receipt))
        )
    except (TypeError, ValueError, OverflowError) as exc:
        try:
            normalized = json.loads(
                json.dumps(dict(receipt), ensure_ascii=False, sort_keys=True, default=str, allow_nan=False)
            )
        except (TypeError, ValueError, OverflowError) as fallback_exc:
            raise ExecutionEnvelopeError(f"audit_receipt_not_json:{fallback_exc}") from fallback_exc
    if not isinstance(normalized, dict):
        raise ExecutionEnvelopeError("audit_receipt_object_required")
    normalized.pop("receipt_sha256", None)
    prefix = re.sub(r"[^a-z0-9._-]+", "_", str(run_id_prefix).lower()).strip("._-") or "audit"
    normalized["run_id"] = f"{prefix}_{uuid.uuid4().hex}"
    return AppendOnlyExecutionLedger(path, master_s_n=master_s_n).append(normalized)


def read_verified_audit_rows(path: Path | str) -> list[dict[str, Any]]:
    """Return rows only after the complete append-only chain verifies."""
    ledger = AppendOnlyExecutionLedger(path)
    ledger.verify()
    return copy.deepcopy(ledger._rows())


def execute_model_plan(
    model_plan: Mapping[str, Any],
    external_context: Mapping[str, Any],
    *,
    master_s_n: float = 1.0,
    ledger_path: Path | str | None = None,
) -> dict[str, Any]:
    """Execute one structured model plan and return the CPU result.

    The returned ``result`` is the primary output.  ``receipt`` is evidence
    about how it was computed, not an LLM-generated explanation.  A failed
    validation, security check, execution, or audit append is a HOLD and never
    becomes a successful output.
    """
    started = _utc()
    run_id = "exec_" + _sha256_bytes(f"{started}:{os.getpid()}:{os.urandom(16).hex()}".encode())[:24]
    ledger = AppendOnlyExecutionLedger(ledger_path, master_s_n=master_s_n)
    normalized: dict[str, Any] | None = None
    result: Any = None
    result_sha256: str | None = None
    status_before: dict[str, Any] = {"state": "NOT_STARTED"}
    status_after: dict[str, Any] = {"state": "NOT_STARTED"}
    security: dict[str, Any] = {"state": "NOT_RUN", "allowed": False}
    final_state = "HOLD"
    reason: str | None = None
    executed = False
    try:
        _validate_json_value(external_context, label="external_context")
        normalized = validate_model_plan(model_plan)
        request_hash = _sha256_json(normalized)
        context_hash = _sha256_json(external_context)
        security = _security_decision(normalized, master_s_n=master_s_n)
        if not security.get("allowed"):
            final_state = "HOLD_SECURITY"
            reason = str(security.get("reason") or "rust_security_denied")
        elif normalized["action"] == "hold":
            final_state = "HOLD_MODEL"
            reason = str(normalized.get("hold_code") or "model_hold")
        else:
            status_before = _runtime_status(normalized.get("pillar"))
            from lib import code_template_runtime as runtime  # type: ignore

            result = runtime.execute_template(
                str(normalized["template_id"]),
                str(normalized["pillar"]),
                external_context,
                normalized["variable_overrides"],
            )
            _validate_json_value(result, label="execution_result")
            result_sha256 = _sha256_json(result)
            executed = True
            status_after = _runtime_status(normalized.get("pillar"))
            final_state = "PASS_CPU_EXECUTION"
    except ExecutionEnvelopeError as exc:
        reason = str(exc)
        final_state = "HOLD_INVALID_REQUEST"
    except Exception as exc:  # noqa: BLE001 - execution errors are held and logged
        reason = f"cpu_execution_failed:{exc}"
        final_state = "HOLD_EXECUTION"

    if normalized is None:
        normalized_for_receipt: dict[str, Any] = {"invalid": True}
        request_hash = None
        context_hash = None
    else:
        normalized_for_receipt = normalized
        request_hash = _sha256_json(normalized)
        context_hash = _sha256_json(external_context)

    receipt: dict[str, Any] = {
        "schema_version": EXECUTION_RECEIPT_SCHEMA,
        "run_id": run_id,
        "created_utc": started,
        "model_plan": normalized_for_receipt,
        "model_plan_sha256": request_hash,
        "external_context_sha256": context_hash,
        "security": security,
        "runtime_before": status_before,
        "runtime_after": status_after,
        "executed": executed,
        "execution_result": result if executed else None,
        "execution_result_sha256": result_sha256,
        "primary_output": "cpu_execution_result" if executed else "none",
        "renderer": {"ava_renderer_used": False, "natural_language_generation": False},
        "final_state": final_state,
        "reason": reason,
        "append_only_audit": {
            "ledger_schema": EXECUTION_LEDGER_SCHEMA,
            "delete_api": "ABSENT",
            "human_retention_authority_required": True,
        },
    }
    try:
        ledger_record = ledger.append(receipt)
    except Exception as exc:  # noqa: BLE001 - no unaudited success is allowed
        receipt["final_state"] = "HOLD_AUDIT"
        receipt["reason"] = f"audit_append_failed:{exc}"
        receipt["executed"] = False
        receipt["execution_result"] = None
        receipt["execution_result_sha256"] = None
        receipt["primary_output"] = "none"
        try:
            ledger_record = ledger.append(receipt)
        except Exception:
            ledger_record = {"ok": False, "error": str(exc)}
        final_state = "HOLD_AUDIT"
        result = None
        executed = False
    else:
        final_state = str(receipt["final_state"])

    return {
        "ok": final_state == "PASS_CPU_EXECUTION",
        "state": final_state,
        "result": result if executed else None,
        "receipt": receipt,
        "ledger": ledger_record,
    }


__all__ = [
    "ALLOWED_ACTIONS",
    "AppendOnlyExecutionLedger",
    "EXECUTION_LEDGER_SCHEMA",
    "EXECUTION_RECEIPT_SCHEMA",
    "EXECUTION_REQUEST_SCHEMA",
    "ExecutionEnvelopeError",
    "compile_semantic_action",
    "default_ledger_path",
    "execute_model_plan",
    "validate_model_plan",
]
