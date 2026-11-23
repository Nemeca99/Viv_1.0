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

from lib.paths import AUTO_ARTIFACTS, SANDBOX_ROOT


REPO_ROOT = Path(__file__).resolve().parents[2]
# These two paths are retained as read-only historical compatibility paths.
# New events and state snapshots go only to the Rust-gated ledger below.
CODE_LOG = AUTO_ARTIFACTS / "organism" / "code_writes.jsonl"
CODE_STATE = AUTO_ARTIFACTS / "organism" / "coder_state.json"
CODE_LEDGER = SANDBOX_ROOT / "code" / "audit" / "code_writes_ledger.jsonl"
OFFLINE_CODER_LEDGER = AUTO_ARTIFACTS / "code_templates" / "offline_coder" / "candidate_assemblies.jsonl"
SELECTION_REQUEST_SCHEMA = "viv_code_template_selection_request_v1"
REBUILD_SELECTION_SCHEMA = "viv_code_template_rebuild_selection_request_v1"


def _utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_state() -> dict[str, Any]:
    default = {"writes": 0, "runs": 0, "last_tool": None}
    try:
        from lib.cpu_execution_envelope import read_verified_audit_rows

        rows = read_verified_audit_rows(CODE_LEDGER)
    except Exception:
        # A tampered or unreadable ledger is not silently replaced.  Callers
        # must hold rather than trust an unverified coding state.
        raise
    for row in reversed(rows):
        if row.get("event") != "state_snapshot":
            continue
        value = row.get("state")
        if isinstance(value, dict):
            return value
    # The old state file is historical input only.  It is never rewritten.
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
    """Execute one verified active template; reject source-path execution.

    The CPU execution envelope is the normal output boundary: the caller can
    provide only a template ID and declared variable overrides, while the
    execution result (not generated model text) becomes the primary output.
    """
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
        from lib.cpu_execution_envelope import EXECUTION_REQUEST_SCHEMA, execute_model_plan

        execution = execute_model_plan(
            {
                "schema_version": EXECUTION_REQUEST_SCHEMA,
                "action": "execute",
                "template_id": template_id,
                "pillar": pillar,
                "variable_overrides": dict(variable_overrides or {}),
            },
            context if context is not None else {},
        )
        result = execution.get("result")
        stdout = json.dumps(result, ensure_ascii=False, default=str) if execution.get("ok") else ""
        ok = bool(execution.get("ok"))
        reason = execution.get("reason") or execution.get("receipt", {}).get("reason")
    except Exception as exc:  # noqa: BLE001
        execution = {
            "ok": False,
            "state": "HOLD",
            "result": None,
            "receipt": None,
            "ledger": None,
        }
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
        "execution_state": execution.get("state"),
        "execution_receipt": execution.get("receipt"),
        "execution_ledger": execution.get("ledger"),
        "primary_output": "cpu_execution_result" if ok else "none",
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


def assemble_candidate_tool(
    *,
    candidate_id: str,
    blocks: list[Mapping[str, Any]],
    pillar: str = "auto",
    variable_overrides: Mapping[str, Any] | None = None,
    s_n: float | None = None,
) -> dict[str, Any]:
    """Request an isolated file assembled only from indexed template blocks.

    This is the bounded self-repair exception.  It accepts no source text and
    no target path.  She may rewrite her own isolated candidate by changing
    VARIABLES, and she may add indexed function spans, but she cannot delete
    functions, keys, or the file, and she cannot change the skeleton.
    Publication still requires the Rust Python-write membrane and human
    approval before registry insertion.
    """
    result: dict[str, Any]
    try:
        from build_tools.cpu_candidate_assembler_v1 import (
            CANDIDATE_REQUEST_SCHEMA,
            assemble_candidate,
        )

        request = {
            "schema_version": CANDIDATE_REQUEST_SCHEMA,
            "candidate_id": candidate_id,
            "pillar": pillar,
            "blocks": blocks,
            "variable_overrides": dict(variable_overrides or {}),
        }
        result = assemble_candidate(
            request,
            isolated=True,
            no_publish=True,
            master_s_n=s_n,
            bind_variable_overrides=True,
        )
    except Exception as exc:  # noqa: BLE001 - normal AI path holds on errors
        result = {"ok": False, "state": "HOLD", "reason": f"candidate_assembly_error:{exc}"}
    report = {
        **result,
        "candidate_only": True,
        "human_approval_required_before_template_insertion": True,
        "s_n": s_n,
        "at": _utc(),
    }
    _append_log({"event": "template_candidate_assembly", **{k: v for k, v in report.items() if k != "assembled_source"}})
    return report


def offline_coder_turn(
    *,
    template_id: str = "",
    variable_overrides: Mapping[str, Any] | None = None,
    context: Mapping[str, Any] | None = None,
    candidate_id: str | None = None,
    execute: bool = True,
    blocks: list[Mapping[str, Any]] | None = None,
    pillar: str = "auto",
    s_n: float | None = None,
    ledger_path: Path | None = None,
    use_existing: bool = False,
    rewrite_own: bool = False,
) -> dict[str, Any]:
    """Minimum offline coder: compose allowed functions into a real tool file, then use it.

    Allowed functions come from the registered toolbox.  She may combine those
    indexed spans into a new isolated ``.py`` under
    ``sandbox/code/template_candidates``.  That file is a tool she built; she
    can rewrite its VARIABLES, add indexed function spans, and run it later.
    She cannot invent function bodies, change the skeleton, or delete the file.
    Production registry/pointer stay unchanged until you promote a candidate.
    """
    template_id = (str(template_id).strip().lower() if template_id else "").strip()
    cid = (str(candidate_id).strip().lower() if candidate_id else "")
    from build_tools.cpu_candidate_assembler_v1 import (
        CANDIDATE_REQUEST_SCHEMA,
        assemble_candidate,
        default_blocks_for_template,
        execute_candidate_file,
        isolated_candidate_root,
        list_candidate_tools,
        rewrite_own_candidate_variables,
    )

    if use_existing:
        if not cid:
            return {"ok": False, "state": "HOLD", "reason": "candidate_id_required_to_use_existing_tool"}
        tool_path = isolated_candidate_root() / cid / f"{cid}.py"
        executed = execute_candidate_file(
            tool_path,
            candidate_id=cid,
            context=context,
            variable_overrides=variable_overrides,
        )
        report = {
            "ok": bool(executed.get("ok")),
            "state": executed.get("state") or "HOLD",
            "candidate_id": cid,
            "template_id": None,
            "used_existing_tool": True,
            "output_path": str(tool_path).replace("\\", "/") if tool_path.is_file() else None,
            "source_file_remains": bool(executed.get("source_file_remains")),
            "execute": executed,
            "generated_file_created": False,
            "active_pointer_changed": False,
            "candidate_only": True,
            "cpu_writes_code": False,
            "model_output_scope": "variable_slots_only",
            "at": _utc(),
        }
        _append_log({"event": "offline_coder_use_tool", "candidate_id": cid, "ok": report["ok"], "state": report["state"], "at": _utc()})
        return report

    if rewrite_own:
        if not cid:
            return {"ok": False, "state": "HOLD", "reason": "candidate_id_required_to_rewrite_own_tool"}
        ledger = Path(ledger_path) if ledger_path is not None else OFFLINE_CODER_LEDGER
        ledger.parent.mkdir(parents=True, exist_ok=True)
        rewritten = rewrite_own_candidate_variables(
            cid,
            dict(variable_overrides or {}),
            isolated=True,
            no_publish=True,
            persist_isolated_candidate=True,
            master_s_n=s_n,
            ledger_path=ledger,
        )
        executed: dict[str, Any] | None = None
        output_path = Path(str(rewritten.get("output_path") or isolated_candidate_root() / cid / f"{cid}.py"))
        if execute and rewritten.get("ok") and output_path.is_file():
            executed = execute_candidate_file(output_path, candidate_id=cid, context=context)
        report = {
            "ok": bool(rewritten.get("ok") and (executed is None or executed.get("ok"))),
            "state": (executed or rewritten).get("state"),
            "candidate_id": cid,
            "template_id": None,
            "used_existing_tool": False,
            "own_file_rewrite": True,
            "structure_locked": True,
            "output_path": rewritten.get("output_path"),
            "source_file_remains": bool(rewritten.get("source_file_remains")),
            "assembly": rewritten,
            "execute": executed,
            "generated_file_created": bool(rewritten.get("generated_file_created")),
            "active_pointer_changed": False,
            "candidate_only": True,
            "cpu_writes_code": True,
            "model_output_scope": "variable_slots_only",
            "at": _utc(),
        }
        _append_log({"event": "offline_coder_rewrite_own", "candidate_id": cid, "ok": report["ok"], "state": report["state"], "at": _utc()})
        return report

    if not template_id and not blocks:
        return {"ok": False, "state": "HOLD", "reason": "template_id_or_blocks_required"}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ").lower()
    cid = cid or f"offline_{template_id.replace('.', '_')}_{stamp}"
    try:
        selected_blocks = list(blocks) if blocks is not None else default_blocks_for_template(template_id)
        ledger = Path(ledger_path) if ledger_path is not None else OFFLINE_CODER_LEDGER
        ledger.parent.mkdir(parents=True, exist_ok=True)
        assembly = assemble_candidate(
            {
                "schema_version": CANDIDATE_REQUEST_SCHEMA,
                "candidate_id": cid,
                "pillar": pillar,
                "blocks": selected_blocks,
                "variable_overrides": dict(variable_overrides or {}),
            },
            isolated=True,
            no_publish=True,
            master_s_n=s_n,
            bind_variable_overrides=True,
            persist_isolated_candidate=True,
            ledger_path=ledger,
        )
    except Exception as exc:  # noqa: BLE001
        result = {"ok": False, "state": "HOLD", "reason": f"offline_coder_assembly_error:{exc}"}
        _append_log({"event": "offline_coder_turn", **result, "at": _utc()})
        return result
    executed: dict[str, Any] | None = None
    source = assembly.get("assembled_source")
    output_path = Path(str(assembly.get("output_path") or ""))
    assembly_state = str(assembly.get("state") or "")
    can_execute = assembly_state in {
        "HOLD_SECURITY",
        "PASS_ISOLATED_CANDIDATE_ONLY",
        "PASS_ISOLATED_CANDIDATE_WITH_SECURITY_HOLD",
    } and bool(assembly.get("compile", {}).get("ok"))
    if execute and can_execute and output_path.is_file():
        executed = execute_candidate_file(output_path, candidate_id=cid, context=context)
    if executed is not None:
        ok = bool(executed.get("ok"))
        state = executed.get("state")
    elif can_execute:
        ok = True
        state = assembly_state
    else:
        ok = False
        state = assembly_state or "HOLD"
    report = {
        "ok": ok,
        "state": state,
        "candidate_id": cid,
        "template_id": template_id or None,
        "used_existing_tool": False,
        "blocks": selected_blocks,
        "variable_overrides": dict(variable_overrides or {}),
        "assembly": {k: v for k, v in assembly.items() if k != "assembled_source"},
        "assembled_source": source,
        "execute": executed,
        "generated_file_created": bool(assembly.get("generated_file_created")),
        "output_path": assembly.get("output_path"),
        "source_file_remains": output_path.is_file() if str(output_path) else False,
        "built_tools": list_candidate_tools(),
        "active_pointer_changed": False,
        "candidate_only": True,
        "human_approval_required_before_template_insertion": True,
        "model_output_scope": "variable_slots_only",
        "cpu_writes_code": True,
        "at": _utc(),
    }
    _append_log(
        {
            "event": "offline_coder_turn",
            **{k: v for k, v in report.items() if k not in {"assembled_source", "assembly", "execute", "built_tools"}},
            "assembly_state": assembly.get("state"),
            "execute_ok": None if executed is None else bool(executed.get("ok")),
            "generated_sha256": assembly.get("generated_sha256"),
            "at": _utc(),
        }
    )
    return report


def list_built_tools() -> dict[str, Any]:
    from build_tools.cpu_candidate_assembler_v1 import list_candidate_tools

    rows = list_candidate_tools()
    return {"ok": True, "candidate_only": True, "production_registry": False, "tools": rows, "count": len(rows)}


def delete_own_tool(candidate_id: str) -> dict[str, Any]:
    from build_tools.cpu_candidate_assembler_v1 import delete_isolated_candidate

    result = delete_isolated_candidate(candidate_id)
    _append_log({"event": "offline_coder_delete_denied", **result, "at": _utc()})
    return result


def rewrite_own_tool(candidate_id: str, variable_overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return offline_coder_turn(
        candidate_id=candidate_id,
        variable_overrides=variable_overrides,
        rewrite_own=True,
        execute=False,
    )


def append_own_tool(
    candidate_id: str,
    extra_blocks: list[Mapping[str, Any]],
    *,
    pillar: str = "auto",
    s_n: float | None = None,
    ledger_path: Path | None = None,
) -> dict[str, Any]:
    from build_tools.cpu_candidate_assembler_v1 import append_indexed_sections

    ledger = Path(ledger_path) if ledger_path is not None else OFFLINE_CODER_LEDGER
    ledger.parent.mkdir(parents=True, exist_ok=True)
    result = append_indexed_sections(
        candidate_id,
        extra_blocks,
        pillar=pillar,
        isolated=True,
        no_publish=True,
        persist_isolated_candidate=True,
        master_s_n=s_n,
        ledger_path=ledger,
    )
    _append_log(
        {
            "event": "offline_coder_append_indexed",
            "candidate_id": candidate_id,
            "ok": result.get("ok"),
            "state": result.get("state"),
            "reason": result.get("reason"),
            "at": _utc(),
        }
    )
    return result


def clone_own_tool(
    src_id: str,
    dest_id: str,
    *,
    s_n: float | None = None,
    ledger_path: Path | None = None,
) -> dict[str, Any]:
    from build_tools.cpu_candidate_assembler_v1 import clone_isolated_candidate

    ledger = Path(ledger_path) if ledger_path is not None else OFFLINE_CODER_LEDGER
    ledger.parent.mkdir(parents=True, exist_ok=True)
    result = clone_isolated_candidate(
        src_id,
        dest_id,
        isolated=True,
        no_publish=True,
        persist_isolated_candidate=True,
        master_s_n=s_n,
        ledger_path=ledger,
    )
    _append_log(
        {
            "event": "offline_coder_clone",
            "src_id": src_id,
            "dest_id": dest_id,
            "ok": result.get("ok"),
            "state": result.get("state"),
            "reason": result.get("reason"),
            "source_file_remains": result.get("source_file_remains"),
            "dest_file_created": result.get("dest_file_created"),
            "active_pointer_changed": False,
            "at": _utc(),
        }
    )
    return result


def rename_own_tool(src_id: str, dest_id: str) -> dict[str, Any]:
    from build_tools.cpu_candidate_assembler_v1 import rename_isolated_candidate

    result = rename_isolated_candidate(src_id, dest_id)
    _append_log({"event": "offline_coder_rename_denied", **result, "at": _utc()})
    return result


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
    "append_own_tool",
    "assemble_candidate_tool",
    "clone_own_tool",
    "delete_own_tool",
    "offline_coder_turn",
    "list_built_tools",
    "next_tool_name",
    "rebuild_random_file_tool",
    "rebuild_reference_tool",
    "rename_own_tool",
    "rewrite_own_tool",
    "run_sandbox_tool",
    "template_status",
    "write_and_run",
    "write_sandbox_tool",
]
