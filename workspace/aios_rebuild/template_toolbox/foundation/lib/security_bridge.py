"""Bridge from Viv Python foundation to Rust security_core.

Fail-closed if the installed .pyd does not match the audit hash sidecar
(self-tamper / module-swap protection).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

_RUST = None
_RUST_ERROR: str | None = None
_INTEGRITY: dict[str, Any] = {"ok": False, "detail": "not_checked"}

_LOCAL_PYD = Path(__file__).with_name("security_core.pyd")
_LOCAL_HASH = Path(__file__).with_name("security_core.pyd.sha256")
# The LocalCoder candidate never falls back to the moved Viv runtime.
_LEGACY_PYD = _LOCAL_PYD
_LEGACY_HASH = _LOCAL_HASH
_HASH_AUDIT = _LOCAL_HASH


def _select_runtime() -> tuple[Path, Path]:
    if _LOCAL_PYD.is_file():
        return _LOCAL_PYD, _LOCAL_HASH
    return _LEGACY_PYD, _LEGACY_HASH


_PYD, _HASH_SIDE = _select_runtime()


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().lower()


def _expected_hash() -> str | None:
    for path in (_HASH_SIDE, _HASH_AUDIT):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        if text.startswith("sha256="):
            for line in text.splitlines():
                if line.startswith("sha256="):
                    return line.split("=", 1)[1].strip().lower()
        if len(text) == 64 and all(c in "0123456789abcdef" for c in text.lower()):
            return text.lower()
    return None


def _verify_integrity() -> tuple[bool, str]:
    if not _PYD.is_file():
        return False, "security_core.pyd missing"
    expected = _expected_hash()
    if expected is None:
        return False, "integrity hash sidecar missing — rebuild with scripts/build.ps1"
    actual = _file_sha256(_PYD)
    if actual != expected:
        return False, f"pyd hash mismatch (expected {expected[:12]}… got {actual[:12]}…) — possible tamper"
    return True, f"sha256={actual} path={_PYD}"


try:
    ok, detail = _verify_integrity()
    _INTEGRITY = {"ok": ok, "detail": detail}
    if not ok:
        _RUST_ERROR = f"integrity_fail: {detail}"
    else:
        spec = importlib.util.spec_from_file_location("security_core", _PYD)
        if spec is None or spec.loader is None:
            raise ImportError(f"unable to load security_core from {_PYD}")
        module = importlib.util.module_from_spec(spec)
        sys.modules["security_core"] = module
        spec.loader.exec_module(module)
        _RUST = module
except (ImportError, OSError) as exc:
    _RUST_ERROR = str(exc)
    _INTEGRITY = {"ok": False, "detail": str(exc)}


def rust_available() -> bool:
    return _RUST is not None and bool(_INTEGRITY.get("ok"))


def rust_module() -> Any:
    """Return the verified Viv-local Rust module for operator surfaces."""
    if not rust_available():
        raise RuntimeError(f"security_core unavailable: {_RUST_ERROR}")
    return _RUST


def runtime_path() -> str:
    """Return the selected runtime module path for evidence and diagnostics."""
    return str(_PYD)


def rust_error() -> str | None:
    return _RUST_ERROR


def integrity_status() -> dict[str, Any]:
    return dict(_INTEGRITY)


def check_ingress(text: str, s_n: float) -> dict[str, Any]:
    if not rust_available():
        return {
            "allowed": False,
            "direction": "IN",
            "stage": "security_in",
            "reason": f"security_core unavailable: {_RUST_ERROR}",
            "s_n": s_n,
        }
    return dict(_RUST.check_ingress(text, float(s_n)))


def check_egress(text: str, s_n: float) -> dict[str, Any]:
    if not rust_available():
        return {
            "allowed": False,
            "direction": "OUT",
            "stage": "security_out",
            "reason": f"security_core unavailable: {_RUST_ERROR}",
            "s_n": s_n,
        }
    return dict(_RUST.check_egress(text, float(s_n)))


def enforce_morality(
    tool_name: str,
    params: dict[str, Any] | str,
    s_n: float,
    forensic_buffer: str = "",
    raw_input: str = "",
) -> dict[str, Any]:
    if not rust_available():
        return {
            "allowed": False,
            "reason": f"security_core unavailable: {_RUST_ERROR}",
            "law": "membrane",
        }
    params_json = params if isinstance(params, str) else json.dumps(params)
    return dict(
        _RUST.enforce_morality(
            tool_name,
            params_json,
            float(s_n),
            forensic_buffer,
            raw_input or None,
        )
    )


def dormancy_threshold() -> float:
    if not rust_available():
        return 0.45
    return float(_RUST.dormancy_threshold())


def check_growth(actuator: str, proposed_r: float, max_r: float) -> dict[str, Any] | None:
    """Rust growth ceiling veto. Returns None if Rust unavailable (Python policy still applies)."""
    if not rust_available():
        return None
    fn = getattr(_RUST, "check_growth", None)
    if fn is None:
        return None
    return dict(fn(str(actuator), float(proposed_r), float(max_r)))


def authorize_backup(request: dict[str, Any] | str) -> dict[str, Any]:
    """Authorize one typed backup operation through the Rust membrane."""
    if not rust_available():
        return {
            "allowed": False,
            "disposition": "DENY",
            "reason": f"security_core unavailable: {_RUST_ERROR}",
            "rule": "membrane",
        }
    fn = getattr(_RUST, "authorize_backup", None)
    if fn is None:
        return {
            "allowed": False,
            "disposition": "DENY",
            "reason": "installed security_core lacks backup security API",
            "rule": "api_version",
        }
    raw = request if isinstance(request, str) else json.dumps(request, separators=(",", ":"))
    return dict(fn(raw))


def verify_backup_ledger() -> dict[str, Any]:
    """Return the Rust backup-ledger hash-chain status."""
    if not rust_available():
        return {"ok": False, "error": f"security_core unavailable: {_RUST_ERROR}"}
    fn = getattr(_RUST, "verify_backup_ledger", None)
    if fn is None:
        return {"ok": False, "error": "installed security_core lacks backup ledger API"}
    try:
        return dict(json.loads(str(fn())))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": f"malformed backup ledger status: {exc}"}


def authorize_training(request: dict[str, Any] | str) -> dict[str, Any]:
    if not rust_available():
        return {
            "allowed": False,
            "disposition": "DENY",
            "reason": f"security_core unavailable: {_RUST_ERROR}",
            "rule": "membrane",
        }
    fn = getattr(_RUST, "authorize_training", None)
    if fn is None:
        return {
            "allowed": False,
            "disposition": "DENY",
            "reason": "installed security_core lacks training security API",
            "rule": "api_version",
        }
    raw = request if isinstance(request, str) else json.dumps(request, separators=(",", ":"))
    return dict(fn(raw))


def begin_training_lease(request: dict[str, Any] | str) -> dict[str, Any]:
    if not rust_available():
        return authorize_training(request)
    fn = getattr(_RUST, "begin_training_lease", None)
    if fn is None:
        return authorize_training(request)
    raw = request if isinstance(request, str) else json.dumps(request, separators=(",", ":"))
    return dict(fn(raw))


def commit_training_lease(token: str, request: dict[str, Any] | str) -> dict[str, Any]:
    if not rust_available():
        return authorize_training(request)
    fn = getattr(_RUST, "commit_training_lease", None)
    if fn is None:
        return authorize_training(request)
    raw = request if isinstance(request, str) else json.dumps(request, separators=(",", ":"))
    return dict(fn(str(token), raw))


def freeze_training_registry(request: dict[str, Any] | str, payload: str) -> dict[str, Any]:
    if not rust_available():
        return authorize_training(request)
    fn = getattr(_RUST, "freeze_training_registry", None)
    if fn is None:
        return {
            "allowed": False, "disposition": "DENY",
            "reason": "installed security_core lacks freeze API", "rule": "api_version",
        }
    raw = request if isinstance(request, str) else json.dumps(request, separators=(",", ":"))
    return dict(fn(raw, str(payload)))


def quarantine_training_payload(token: str, record_id: str, plaintext: str) -> dict[str, Any]:
    if not rust_available():
        return {
            "allowed": False, "disposition": "DENY",
            "reason": f"security_core unavailable: {_RUST_ERROR}", "rule": "membrane",
        }
    fn = getattr(_RUST, "quarantine_training_payload", None)
    if fn is None:
        return {
            "allowed": False, "disposition": "DENY",
            "reason": "installed security_core lacks quarantine API", "rule": "api_version",
        }
    return dict(fn(str(token), str(record_id), str(plaintext)))


def read_training_quarantine(token: str, record_id: str) -> dict[str, Any]:
    if not rust_available():
        return {
            "allowed": False, "disposition": "DENY",
            "reason": f"security_core unavailable: {_RUST_ERROR}", "rule": "membrane",
        }
    fn = getattr(_RUST, "read_training_quarantine", None)
    if fn is None:
        return {
            "allowed": False, "disposition": "DENY",
            "reason": "installed security_core lacks quarantine API", "rule": "api_version",
        }
    return dict(fn(str(token), str(record_id)))


def verify_training_ledger() -> dict[str, Any]:
    if not rust_available():
        return {"ok": False, "error": f"security_core unavailable: {_RUST_ERROR}"}
    fn = getattr(_RUST, "verify_training_ledger", None)
    if fn is None:
        return {"ok": False, "error": "installed security_core lacks ledger API"}
    try:
        return dict(json.loads(str(fn())))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": f"malformed ledger status: {exc}"}


def authorize_runtime_control(request: dict[str, Any] | str) -> dict[str, Any]:
    """Authorize one typed operator runtime-control request through Rust.

    The Python caller is only a request client.  If the verified native module
    lacks this API, the action is denied rather than falling back to the
    generic governor or an unguarded process operation.
    """
    if not rust_available():
        return {
            "allowed": False,
            "disposition": "DENY",
            "reason": f"security_core unavailable: {_RUST_ERROR}",
            "rule": "membrane",
            "autonomous_access": False,
            "ledger_recorded": False,
        }
    fn = getattr(_RUST, "authorize_runtime_control", None)
    if fn is None:
        return {
            "allowed": False,
            "disposition": "DENY",
            "reason": "installed security_core lacks runtime-control API",
            "rule": "api_version",
            "autonomous_access": False,
            "ledger_recorded": False,
        }
    raw = request if isinstance(request, str) else json.dumps(request, separators=(",", ":"))
    return dict(fn(raw))


def runtime_control_available() -> bool:
    """Return whether the verified native module exposes the typed API."""
    return rust_available() and getattr(_RUST, "authorize_runtime_control", None) is not None


def authorize_python_write(request: dict[str, Any] | str) -> dict[str, Any]:
    """Ask Rust whether Viv's autonomous Python-only writer may proceed.

    This is deliberately fail-closed.  The current Rust capability is compiled
    closed, so a missing or stale native API can never fall back to Python.
    """
    if not rust_available():
        return {
            "allowed": False,
            "disposition": "DENY",
            "reason": f"security_core unavailable: {_RUST_ERROR}",
            "rule": "membrane",
            "autonomous_access": False,
            "ledger_recorded": False,
        }
    fn = getattr(_RUST, "authorize_python_write", None)
    if fn is None:
        return {
            "allowed": False,
            "disposition": "DENY",
            "reason": "installed security_core lacks Python-write API",
            "rule": "api_version",
            "autonomous_access": False,
            "ledger_recorded": False,
        }
    raw = request if isinstance(request, str) else json.dumps(request, separators=(",", ":"))
    return dict(fn(raw))


def authorize_human_approved_python_write(
    request: dict[str, Any] | str,
    approval: dict[str, Any] | str,
) -> dict[str, Any]:
    """Ask Rust to verify a separately authored Architect approval.

    This is intentionally distinct from :func:`authorize_python_write`: the
    autonomous writer remains compiled closed, and pointer adoption is never
    implied by this approval route.  Missing native support or malformed input
    fails closed rather than falling back to Python.
    """
    if not rust_available():
        return {
            "allowed": False,
            "disposition": "DENY",
            "reason": f"security_core unavailable: {_RUST_ERROR}",
            "rule": "membrane",
            "autonomous_access": False,
            "ledger_recorded": False,
        }
    fn = getattr(_RUST, "authorize_human_approved_python_write", None)
    if fn is None:
        return {
            "allowed": False,
            "disposition": "DENY",
            "reason": "installed security_core lacks human-approval API",
            "rule": "api_version",
            "autonomous_access": False,
            "ledger_recorded": False,
        }
    request_raw = request if isinstance(request, str) else json.dumps(request, separators=(",", ":"))
    approval_raw = approval if isinstance(approval, str) else json.dumps(approval, separators=(",", ":"))
    return dict(fn(request_raw, approval_raw))


def _authorize_human_approved_additive(
    native_name: str,
    request: dict[str, Any] | str,
    approval: dict[str, Any] | str,
    missing_reason: str,
) -> dict[str, Any]:
    """Call one additive approval-bound Rust route and fail closed if absent."""

    if not rust_available():
        return {
            "allowed": False,
            "disposition": "DENY",
            "reason": f"security_core unavailable: {_RUST_ERROR}",
            "rule": "membrane",
            "autonomous_access": False,
            "ledger_recorded": False,
        }
    fn = getattr(_RUST, native_name, None)
    if fn is None:
        return {
            "allowed": False,
            "disposition": "DENY",
            "reason": missing_reason,
            "rule": "api_version",
            "autonomous_access": False,
            "ledger_recorded": False,
        }
    request_raw = request if isinstance(request, str) else json.dumps(request, separators=(",", ":"))
    approval_raw = approval if isinstance(approval, str) else json.dumps(approval, separators=(",", ":"))
    try:
        return dict(fn(request_raw, approval_raw))
    except Exception as exc:  # noqa: BLE001 - authority must fail closed
        return {
            "allowed": False,
            "disposition": "DENY",
            "reason": f"{native_name}_failed:{type(exc).__name__}:{exc}",
            "rule": "membrane",
            "autonomous_access": False,
            "ledger_recorded": False,
        }


def authorize_human_approved_registry_write(
    request: dict[str, Any] | str,
    approval: dict[str, Any] | str,
) -> dict[str, Any]:
    """Ask Rust to authorize the exact active template registry target."""

    return _authorize_human_approved_additive(
        "authorize_human_approved_registry_write",
        request,
        approval,
        "installed security_core lacks human-approved registry API",
    )


def authorize_human_approved_template_source_write(
    request: dict[str, Any] | str,
    approval: dict[str, Any] | str,
) -> dict[str, Any]:
    """Ask Rust to authorize the exact companion template source target."""

    return _authorize_human_approved_additive(
        "authorize_human_approved_template_source_write",
        request,
        approval,
        "installed security_core lacks human-approved template-source API",
    )


def authorize_human_approved_pointer_adoption(
    request: dict[str, Any] | str,
    approval: dict[str, Any] | str,
) -> dict[str, Any]:
    """Ask Rust to authorize the separate active-generation pointer transition.

    Generated artifacts and registry insertion do not imply pointer authority;
    this route requires the dedicated second approval schema in Rust.
    """

    return _authorize_human_approved_additive(
        "authorize_human_approved_pointer_adoption",
        request,
        approval,
        "installed security_core lacks human-approved pointer-adoption API",
    )


def python_write_control_available() -> bool:
    """Return whether the verified native module exposes the Python-write API."""
    return rust_available() and getattr(_RUST, "authorize_python_write", None) is not None


def epistemic_axioms() -> dict[str, Any]:
    """Return the compile-time Rust axiom registry or a fail-closed HOLD."""
    if not rust_available():
        return {
            "status": "HOLD",
            "available": False,
            "axioms": [],
            "reason": f"security_core unavailable: {_RUST_ERROR}",
        }
    fn = getattr(_RUST, "get_axioms", None)
    if fn is None:
        return {
            "status": "HOLD",
            "available": False,
            "axioms": [],
            "reason": "installed security_core lacks epistemic-axiom API",
        }
    try:
        rows = list(fn())
    except Exception as exc:  # noqa: BLE001 - security boundary fails closed
        return {
            "status": "HOLD",
            "available": False,
            "axioms": [],
            "reason": f"epistemic_axiom_read_failed:{type(exc).__name__}:{exc}",
        }
    if not rows or not all(isinstance(row, dict) for row in rows):
        return {
            "status": "HOLD",
            "available": False,
            "axioms": [],
            "reason": "epistemic_axiom_registry_malformed",
        }
    return {"status": "PASS", "available": True, "axioms": rows}


def assess_possibility(request: dict[str, Any] | str) -> dict[str, Any]:
    """Apply Rust-only evidence discipline to a possibility disposition.

    Python never upgrades UNKNOWN, DIFFICULT, or IMPOSSIBLE on its own. A
    missing, stale, or malformed native API returns HOLD.
    """
    if not rust_available():
        return {
            "admitted": False,
            "effective_disposition": "HOLD",
            "reason": f"security_core unavailable: {_RUST_ERROR}",
        }
    fn = getattr(_RUST, "assess_possibility", None)
    if fn is None:
        return {
            "admitted": False,
            "effective_disposition": "HOLD",
            "reason": "installed security_core lacks possibility-assessment API",
        }
    raw = request if isinstance(request, str) else json.dumps(
        request, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    try:
        result = dict(fn(raw))
    except Exception as exc:  # noqa: BLE001 - security boundary fails closed
        return {
            "admitted": False,
            "effective_disposition": "HOLD",
            "reason": f"possibility_assessment_failed:{type(exc).__name__}:{exc}",
        }
    if result.get("effective_disposition") not in {
        "HOLD", "UNKNOWN", "DIFFICULT", "PROVEN_IMPOSSIBLE"
    } or not isinstance(result.get("admitted"), bool):
        return {
            "admitted": False,
            "effective_disposition": "HOLD",
            "reason": "possibility_assessment_response_malformed",
        }
    return result


def constitution() -> dict[str, Any]:
    if not rust_available():
        return {
            "architect": "Travis Miner",
            "version": "unavailable",
            "armed": False,
            "error": _RUST_ERROR,
            "integrity": integrity_status(),
        }
    fn = getattr(_RUST, "get_constitution", None) or getattr(_RUST, "constitution", None)
    if fn is None:
        return {
            "architect": "Travis Miner",
            "armed": True,
            "version": getattr(_RUST, "__version__", "?"),
            "integrity": integrity_status(),
        }
    data = dict(fn())
    data["armed"] = True
    data["integrity"] = integrity_status()
    return data
