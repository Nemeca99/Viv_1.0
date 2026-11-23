"""Compatibility facade for Viv's deterministic template coding toolbox.

The former implementation accepted arbitrary Python source, wrote it as a
``.txt`` file, and executed it through stdin.  That was still raw code
generation even though it avoided a ``.py`` file.  This facade deliberately
does not accept source text or source paths.  A coding action must reference an
indexed template selection request, and publication remains behind the normal
Rust security gate.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any, Mapping

from lib.paths import AUTO_ARTIFACTS


REPO_ROOT = Path(__file__).resolve().parents[2]
# The old paths remain read-only compatibility references.  New coder events
# and state snapshots use the Rust-gated ledger below.
CODE_LOG = AUTO_ARTIFACTS / "organism" / "code_writes.jsonl"
CODE_STATE = AUTO_ARTIFACTS / "organism" / "coder_state.json"
CODE_LEDGER = AUTO_ARTIFACTS / "organism" / "code_writes_ledger.jsonl"
SELECTION_REQUEST_SCHEMA = "viv_code_template_selection_request_v1"
REBUILD_SELECTION_SCHEMA = "viv_code_template_rebuild_selection_request_v1"


def _utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_state() -> dict[str, Any]:
    default = {"writes": 0, "runs": 0, "last_tool": None}
    from lib.cpu_execution_envelope import read_verified_audit_rows

    rows = read_verified_audit_rows(CODE_LEDGER)
    for row in reversed(rows):
        if row.get("event") == "state_snapshot" and isinstance(row.get("state"), dict):
            return dict(row["state"])
    if not CODE_STATE.is_file():
        return default
    try:
        value = json.loads(CODE_STATE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else default
    except (OSError, json.JSONDecodeError):
        return default


def _save_state(state: Mapping[str, Any]) -> None:
    _append_log({"event": "state_snapshot", "state": dict(state), "at": _utc()})


def _append_log(row: Mapping[str, Any]) -> None:
    from lib.cpu_execution_envelope import append_audit_receipt

    entry = dict(row)
    entry.setdefault("event_schema", "viv_coder_event_v1")
    entry.setdefault("at", _utc())
    append_audit_receipt(CODE_LEDGER, entry, run_id_prefix="coder")


def _builder():
    root_text = str(REPO_ROOT)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    from build_tools import template_builder_v1

    return template_builder_v1


def next_tool_name(state: Mapping[str, Any] | None = None) -> str:
    """Inspect the catalog for compatibility; callers must still select an ID."""
    del state
    try:
        report = _builder().toolbox_status()
        templates = report.get("templates") or []
        names = [str(row.get("template_id")) for row in templates if row.get("template_id")]
        return names[0] if names else ""
    except Exception:  # noqa: BLE001
        return ""


def _default_selection_request(template_id: str) -> dict[str, Any]:
    status = template_status()
    row = next(
        (
            item
            for item in (status.get("templates") or [])
            if isinstance(item, Mapping) and str(item.get("template_id")) == template_id
        ),
        None,
    )
    if isinstance(row, Mapping):
        target_pillars = list(row.get("target_pillars") or row.get("targets") or [])
        submain_order = list(row.get("submain_order") or [])
    else:
        target_pillars = []
        submain_order = []
    return {
        "schema_version": SELECTION_REQUEST_SCHEMA,
        "templates": [
            {
                "template_id": template_id,
                "target_pillars": target_pillars,
                "submain_order": submain_order,
            }
        ],
    }


def template_status(*, pillar: str | None = None) -> dict[str, Any]:
    """Expose the read-only toolbox status to AIOS callers."""
    try:
        foundation_text = str(REPO_ROOT / "foundation")
        if foundation_text not in sys.path:
            sys.path.insert(0, foundation_text)
        from lib.code_template_runtime import template_status as read_status

        return read_status(pillar)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "state": "HOLD", "reason": f"template_status_error:{exc}"}


def write_sandbox_tool(
    *,
    tool: str | None = None,
    source: str | None = None,
    s_n: float | None = None,
    selection_request: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Publish an approved selection; reject all raw source authoring."""
    if source is not None:
        denial = {
            "ok": False,
            "state": "HOLD",
            "reason": "raw_python_source_forbidden",
            "next": "human_review_create_or_adopt_indexed_template",
        }
        _append_log({"event": "template_publish_denied", "reason": denial["reason"], "source_supplied": True, "at": _utc()})
        return denial
    template_id = (str(tool).strip().lower() if tool else "").strip()
    if not template_id:
        return {"ok": False, "state": "HOLD", "reason": "template_id_required"}
    request = dict(selection_request) if selection_request is not None else _default_selection_request(template_id)
    try:
        report = _builder().publish_generation(selection_request=request)
    except Exception as exc:  # noqa: BLE001
        report = {"ok": False, "state": "HOLD", "reason": f"template_publish_error:{exc}"}
    result = {
        "ok": bool(report.get("ok")),
        "state": report.get("state", "HOLD"),
        "tool": template_id,
        "selection_request": request,
        "security": report.get("security"),
        "generation_id": report.get("generation_id"),
        "reason": report.get("reason"),
        "s_n": s_n,
        "at": _utc(),
    }
    _append_log({"event": "template_publish_request", **result})
    if result["ok"]:
        state = _load_state()
        state["writes"] = int(state.get("writes") or 0) + 1
        state["last_tool"] = template_id
        state["last_write_at"] = result["at"]
        state["last_generation_id"] = result.get("generation_id")
        _save_state(state)
    return result


def run_sandbox_tool(
    *,
    tool: str | None = None,
    path: str | None = None,
    timeout_s: float = 20.0,
    s_n: float | None = None,
    pillar: str = "auto",
    context: Mapping[str, Any] | None = None,
    variable_overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute one verified active template; reject source-path execution."""
    del timeout_s
    if path is not None:
        denial = {
            "ok": False,
            "state": "HOLD",
            "reason": "raw_python_source_execution_forbidden",
            "next": "execute_active_template_by_id_after_human_approved_publish",
        }
        _append_log({"event": "template_execute_denied", "reason": denial["reason"], "path_supplied": True, "at": _utc()})
        return denial
    template_id = (str(tool).strip().lower() if tool else "").strip()
    if not template_id:
        return {"ok": False, "state": "HOLD", "reason": "template_id_required"}
    try:
        foundation_text = str(REPO_ROOT / "foundation")
        if foundation_text not in sys.path:
            sys.path.insert(0, foundation_text)
        from lib.code_template_runtime import execute_template

        result = execute_template(
            template_id,
            pillar,
            context if context is not None else {},
            variable_overrides,
        )
        stdout = json.dumps(result, ensure_ascii=False, default=str)
        ok = True
        reason = None
    except Exception as exc:  # noqa: BLE001
        stdout = ""
        ok = False
        reason = str(exc)
        result = None
    state = _load_state()
    state["runs"] = int(state.get("runs") or 0) + 1
    state["last_run_at"] = _utc()
    state["last_run_ok"] = ok
    _save_state(state)
    report = {
        "ok": ok,
        "state": "PASS" if ok else "HOLD",
        "tool": template_id,
        "pillar": pillar,
        "result": result,
        "stdout": stdout[:4000],
        "stderr": "" if ok else reason,
        "reason": reason,
        "s_n": s_n,
        "at": _utc(),
    }
    _append_log({"event": "template_execute", **report})
    return report


def rebuild_reference_tool(
    *,
    input_path: str | Path | None = None,
    output_path: str | Path | None = None,
    receipt_dir: str | Path | None = None,
    allow_input_fallback: bool = False,
    s_n: float | None = None,
) -> dict[str, Any]:
    """Rebuild a reference module through the CPU exact-span toolbox.

    This is a path-only tool call.  It accepts no source text or generated
    body, fixes the isolation/no-publish guards internally, and delegates all
    copying and missing-function handling to ``template_scale_rebuild_v1``.
    The output is restricted to the isolated rebuild surface under
    ``sandbox/code/template_rebuilds``; production generations and the active
    pointer are not reachable through this facade. The CPU tool submits the
    hypothetical Python write to the Rust membrane; a denied decision creates
    no output. Any sandbox candidate still requires human approval before live
    template insertion.
    """
    if input_path is None or output_path is None:
        result = {"ok": False, "state": "HOLD", "reason": "reference_input_and_output_paths_required"}
        _append_log({"event": "reference_rebuild_denied", **result, "at": _utc()})
        return result
    input_candidate = Path(input_path).resolve(strict=False)
    output_candidate = Path(output_path).resolve(strict=False)
    repo_root = REPO_ROOT.resolve(strict=False)
    allowed_output_root = (REPO_ROOT / "sandbox" / "code" / "template_rebuilds").resolve(strict=False)
    try:
        input_candidate.relative_to(repo_root)
        output_candidate.relative_to(allowed_output_root)
    except ValueError:
        result = {
            "ok": False,
            "state": "HOLD",
            "reason": "reference_rebuild_path_outside_isolated_surface",
            "input_path": str(input_candidate),
            "output_path": str(output_candidate),
        }
        _append_log({"event": "reference_rebuild_denied", **result, "at": _utc()})
        return result
    if input_candidate.suffix.lower() not in {".py", ".pyw", ".pyi"}:
        result = {"ok": False, "state": "HOLD", "reason": "reference_input_must_be_python", "input_path": str(input_candidate)}
        _append_log({"event": "reference_rebuild_denied", **result, "at": _utc()})
        return result
    try:
        from build_tools.template_scale_rebuild_v1 import run_rebuild_cli

        result = run_rebuild_cli(
            input_path=input_candidate,
            output_path=output_candidate,
            receipt_dir=Path(receipt_dir) if receipt_dir is not None else (REPO_ROOT / "foundation" / "artifacts" / "auto" / "code_templates" / "rebuild_tests"),
            isolated=True,
            no_publish=True,
            allow_input_fallback=bool(allow_input_fallback),
        )
    except Exception as exc:  # noqa: BLE001
        result = {"ok": False, "state": "HOLD", "reason": f"reference_rebuild_error:{exc}"}
    report = {
        **result,
        "selection_request_schema": REBUILD_SELECTION_SCHEMA,
        "synthesis_performed": False,
        "isolated": True,
        "no_publish": True,
        "s_n": s_n,
        "at": _utc(),
    }
    _append_log({"event": "reference_rebuild", **report})
    return report


def rebuild_random_file_tool(
    *,
    input_path: str | Path | None = None,
    output_path: str | Path | None = None,
    receipt_dir: str | Path | None = None,
    s_n: float | None = None,
) -> dict[str, Any]:
    """Rebuild a supplied Python file from catalog material only.

    This variant is the explicit random-file operation.  Catalog matches are
    copied from approved spans.  A function absent from the catalog may be
    recreated only from an AST-matched, parameter-compatible catalog body.
    Unmatched functions hold; the authoring-only input-span fallback is not
    reachable through this normal AI/Viv surface.  No model text, synthesized
    body, or source transformation is accepted.
    """
    result = rebuild_reference_tool(
        input_path=input_path,
        output_path=output_path,
        receipt_dir=receipt_dir,
        allow_input_fallback=False,
        s_n=s_n,
    )
    return {**result, "operation": "random_file_rebuild", "synthesis_performed": False}


def write_and_run(
    *,
    tool: str | None = None,
    pillar: str = "auto",
    context: Mapping[str, Any] | None = None,
    variable_overrides: Mapping[str, Any] | None = None,
    selection_request: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Publish one structured selection, then execute it explicitly."""
    publish = write_sandbox_tool(tool=tool, selection_request=selection_request)
    if not publish.get("ok"):
        return {"ok": False, "phase": "template_publish", "write": publish}
    run = run_sandbox_tool(
        tool=str(publish.get("tool") or tool or ""),
        pillar=pillar,
        context=context,
        variable_overrides=variable_overrides,
    )
    return {
        "ok": bool(run.get("ok")),
        "phase": "template_publish_and_run",
        "write": publish,
        "run": {
            "ok": run.get("ok"),
            "stdout": (run.get("stdout") or "")[:400],
            "stderr": (run.get("stderr") or "")[:200],
            "tool": run.get("tool"),
            "result": run.get("result"),
        },
    }


def code_due(*, every_n_beats: int, beat_index: int) -> bool:
    if every_n_beats <= 0:
        return False
    return beat_index > 0 and (beat_index % every_n_beats == 0)


__all__ = [
    "code_due",
    "next_tool_name",
    "rebuild_random_file_tool",
    "rebuild_reference_tool",
    "run_sandbox_tool",
    "template_status",
    "write_and_run",
    "write_sandbox_tool",
]
