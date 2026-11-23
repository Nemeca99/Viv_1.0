"""Run one fresh visible Drone action session through existing OpenCode and Rust gates."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

from run_visible_drone_cycle_v5 import (
    _body_gate_receipts,
    _dispatch,
    _field,
    _intermediate_self_prompts,
    _post_tool_final_text,
    explicit_tool_sequence,
    has_self_prompt,
    validate_final,
)

ROOT = Path(r"L:\LocalCoder")
CYCLE_ROOT = ROOT / ".opencode/evals/drone_cycles"
TASK_RUNS_ROOT = ROOT / ".opencode/evals/task_runs"
PYTHON = Path(r"L:\.venv\Scripts\python.exe")
ARCHITECT_GOAL_ID = "01a1d847-3b27-7533-bbc2-c718ace48ae7"

# Drone write access is intentionally limited to adding Python files.
SUPPORTED_TOOLS = frozenset({
    "read", "glob", "grep", "shell", "skill",
    "localcoder_status", "localcoder_memory_read", "localcoder_add_python",
    "aios_router_router_status", "aios_router_classify_task",
    "aios_router_open_build_task", "aios_router_accept_self_prompt",
    "aios_router_record_turn_result", "aios_router_complete_lane",
    "aios_router_stop_task", "aios_router_queen_summary",
})


def _cli_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("APPDATA is unavailable; cannot recover an OpenCode session")
    return Path(appdata) / "ai.opencode.desktop/cli/2.3.0-x64/opencode-cli.exe"


def _rust_preflight() -> dict[str, Any]:
    """Observe the authoritative Rust gate before creating a visible model session."""
    try:
        completed = subprocess.run(
            [str(PYTHON), "-m", "aios_rebuild.main_core.mind_runtime_gate",
             "--goal-id", ARCHITECT_GOAL_ID],
            cwd=ROOT / "workspace",
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {
            "valid": False,
            "allowed": False,
            "error": f"rust_preflight_{type(error).__name__}",
        }
    try:
        decision = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {
            "valid": False,
            "allowed": False,
            "error": "rust_preflight_invalid_json",
            "stderr_tail": completed.stderr[-500:],
        }
    valid = bool(
        decision.get("schema") == "aios_mind_runtime_gate_v1"
        and decision.get("authority") == "deterministic_aios_body_rust"
        and isinstance(decision.get("allowed"), bool)
        and (
            decision.get("disposition") == "ALLOW_MIND_RUNTIME"
            if decision.get("allowed") is True
            else decision.get("disposition") == "HOLD_MIND_RUNTIME"
        )
    )
    return {
        "valid": valid,
        "allowed": valid and decision.get("allowed") is True,
        "authority": decision.get("authority"),
        "disposition": decision.get("disposition"),
        "reasons": decision.get("reasons", []),
        "resource_diagnostics": decision.get("resource_diagnostics", {}),
        "return_code": completed.returncode,
        **({} if valid else {"error": "rust_preflight_schema_or_authority_invalid"}),
    }


def _cli(args: list[str], timeout: int = 15) -> subprocess.CompletedProcess[str]:
    executable = _cli_path()
    if not executable.is_file():
        raise RuntimeError(f"OpenCode CLI was not found: {executable}")
    return subprocess.run(
        [str(executable), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        check=False,
    )


def _task_run_directory(report: dict[str, Any]) -> tuple[Path | None, str | None]:
    value = report.get("evidence")
    if not isinstance(value, str) or not value.strip():
        return None, "dispatcher_evidence_path_missing"
    directory = Path(value).resolve()
    root = TASK_RUNS_ROOT.resolve()
    if directory.parent != root or not re.fullmatch(r"\d{8}T\d{12}Z", directory.name):
        return None, "dispatcher_evidence_path_outside_expected_task_runs"
    if not directory.is_dir():
        return None, "dispatcher_evidence_directory_missing"
    return directory, None


def _assignment_file_targets(assignment: str) -> tuple[str | None, str | None]:
    """Return the explicit read source and add/create destination, in that order."""
    path_pattern = r"(?<![\w:])(?:[A-Za-z]:[\\/])?(?:[\w.-]+[\\/])+[\w.-]+\.[A-Za-z0-9]{1,8}"
    paths = re.findall(path_pattern, assignment)
    read_paths: list[str] = []
    write_paths: list[str] = []
    for line in assignment.splitlines():
        line_paths = re.findall(path_pattern, line)
        if not line_paths:
            continue
        if re.match(r"^\s*(?:[-*]\s*)?read\b", line, re.IGNORECASE):
            read_paths.append(line_paths[0])
        else:
            read_call = re.search(r"\bread\s+tool\s+(?:for|from|on)\s+`([^`]+)`", line, re.IGNORECASE)
            if read_call:
                read_paths.append(read_call.group(1))
        if re.match(r"^\s*(?:[-*]\s*)?(?:add|create)\b[^`]*\bfile\b", line, re.IGNORECASE):
            write_paths.extend(line_paths)
    read_unique = list(dict.fromkeys(path.casefold() for path in read_paths))
    write_unique = list(dict.fromkeys(path.casefold() for path in write_paths))
    read_target = read_paths[0] if len(read_unique) == 1 else (paths[0] if not read_paths and paths else None)
    assigned_target = write_paths[0] if len(write_unique) == 1 else (
        read_target if not write_paths else None
    )
    return read_target, assigned_target


def _validate_read_evidence(final_text: str, assignment: str,
                            work: dict[str, Any], session_id: str | None) -> tuple[bool, str, dict[str, str]]:
    """Bind a reported Python fact to its read source and assigned output path."""
    read_target, target = _assignment_file_targets(assignment)
    if not read_target:
        return True, "no_explicit_read_path_to_bind", {}
    target = target or read_target
    basename = target.replace("\\", "/").rsplit("/", 1)[-1]
    directory, path_error = _task_run_directory(work)
    if directory is None or not session_id:
        return False, path_error or "read_session_id_missing", {"target": target}
    export_path = directory / f"{session_id}.json"
    try:
        session = json.loads(export_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, "read_session_export_missing_or_invalid", {"target": target}
    outputs: list[str] = []
    for message in session.get("messages", []):
        if not isinstance(message, dict) or message.get("type") != "assistant":
            continue
        for part in message.get("content", []):
            if not isinstance(part, dict) or part.get("type") != "tool" or part.get("name") != "read":
                continue
            state = part.get("state", {})
            if state.get("status") != "completed":
                continue
            outputs.extend(
                item.get("text", "") for item in state.get("content", [])
                if isinstance(item, dict) and isinstance(item.get("text"), str)
            )
    read_output = "\n".join(outputs)
    normalized_output = read_output.replace("\\", "/").casefold()
    normalized_read_target = read_target.replace("\\", "/").casefold()
    if not read_output or normalized_read_target not in normalized_output:
        return False, "read_result_does_not_match_assigned_source", {
            "target": target, "read_target": read_target,
        }

    source_lines = []
    for line in read_output.splitlines():
        numbered = re.match(r"^\s*\d+:\s?(.*)$", line)
        if numbered:
            source_lines.append(numbered.group(1))
    source = "\n".join(source_lines)
    anchor_match = re.search(r"(?m)^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(", source)
    if not anchor_match:
        anchor_match = re.search(r"(?m)^\s*class\s+([A-Za-z_]\w*)\b", source)
    if not anchor_match:
        anchor_match = re.search(r"(?m)^\s*(?:from|import)\s+([A-Za-z_]\w*)\b", source)
    if not anchor_match:
        anchor_match = re.search(r"(?m)^\s*([A-Za-z_]\w*)\s*=(?!=)", source)
    if not anchor_match:
        return False, "read_fact_anchor_unavailable", {
            "target": target, "read_target": read_target,
        }
    anchor = anchor_match.group(1)
    if basename.casefold() not in final_text.casefold():
        return False, "final_report_omits_assigned_filename", {
            "target": target, "read_target": read_target, "fact_anchor": anchor,
        }
    if anchor.casefold() not in final_text.casefold():
        return False, "read_anchor_missing_from_final_report", {
            "target": target, "read_target": read_target, "fact_anchor": anchor,
        }
    return True, "assigned_filename_and_content_fact_verified", {
        "target": target, "read_target": read_target, "fact_anchor": anchor,
    }


def _validate_source_line_limit(assignment: str) -> dict[str, Any] | None:
    """Enforce an explicit under-N-lines constraint on the assigned output file."""
    match = re.search(r"\bunder\s+(\d+)\s+(?:physical\s+)?lines?\b", assignment, re.IGNORECASE)
    if not match:
        return None
    limit = int(match.group(1))
    _, target = _assignment_file_targets(assignment)
    if not target:
        return {"required": True, "passed": False, "reason": "assigned_line_limit_target_missing", "exclusive_limit": limit}
    normalized = target.replace("\\", "/")
    segments = normalized.split("/")
    if not normalized.casefold().startswith("workspace/") or any(
        not segment or segment in {".", ".."} for segment in segments
    ):
        return {"required": True, "passed": False, "reason": "assigned_line_limit_target_invalid", "target": target, "exclusive_limit": limit}
    candidate = (ROOT / Path(*segments)).resolve()
    workspace_root = (ROOT / "workspace").resolve()
    if workspace_root not in candidate.parents:
        return {"required": True, "passed": False, "reason": "assigned_line_limit_target_outside_workspace", "target": target, "exclusive_limit": limit}
    try:
        line_count = len(candidate.read_text(encoding="utf-8").splitlines())
    except (OSError, UnicodeError):
        return {"required": True, "passed": False, "reason": "assigned_line_limit_target_unreadable", "target": target, "exclusive_limit": limit}
    passed = line_count < limit
    return {
        "required": True,
        "passed": passed,
        "reason": "under_assigned_line_limit" if passed else "assigned_source_exceeds_line_limit",
        "target": target,
        "line_count": line_count,
        "exclusive_limit": limit,
    }


def _validate_self_check_output(assignment: str, work: dict[str, Any]) -> dict[str, Any] | None:
    """Require observable PASS output when an assignment explicitly runs --self-check."""
    if "--self-check" not in assignment:
        return None
    checks = work.get("shell_checks")
    if not isinstance(checks, list) or not checks:
        return {"required": True, "passed": False, "reason": "self_check_result_missing"}
    completed = [item for item in checks if isinstance(item, dict) and item.get("status") == "completed"]
    zero_exit = [item for item in completed if item.get("exit") == 0]
    if not zero_exit:
        return {"required": True, "passed": False, "reason": "self_check_nonzero_or_missing_exit"}
    pass_pattern = re.compile(r"PASS(?:\s*[:\-][^\r\n]*)?")
    expected_match = re.search(r"`(PASS:\s*\d+\s+checks)`", assignment)
    if not expected_match:
        return {"required": True, "passed": False, "reason": "expected_pass_marker_missing_from_assignment"}
    expected_pass_line = expected_match.group(1)
    for item in zero_exit:
        output_lines = [line.strip() for line in str(item.get("output", "")).splitlines() if line.strip()]
        payload_lines = [line for line in output_lines if not line.startswith("Exit code:")]
        pass_lines = [line for line in payload_lines if pass_pattern.fullmatch(line)]
        if len(pass_lines) != 1:
            continue
        if pass_lines[0] != expected_pass_line:
            continue
        if payload_lines != pass_lines:
            continue
        return {
            "required": True,
            "passed": True,
            "reason": "exact_expected_pass_line_verified",
            "pass_line": pass_lines[0],
        }
    return {
        "required": True,
        "passed": False,
        "reason": "self_check_output_not_exactly_one_expected_pass_line",
    }


def _save_recovery_export(directory: Path, session_id: str, raw: str) -> str:
    standard = directory / f"{session_id}.json"
    if not standard.exists():
        try:
            with standard.open("x", encoding="utf-8", newline="") as target:
                target.write(raw)
            return str(standard)
        except FileExistsError:
            pass
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    recovery = directory / f"{session_id}.v6-recovery-{stamp}.json"
    with recovery.open("x", encoding="utf-8", newline="") as target:
        target.write(raw)
    return str(recovery)


def _recover_session(report: dict[str, Any]) -> dict[str, Any]:
    """Recover an unstreamed visible session and interrupt it only if still active."""
    directory, path_error = _task_run_directory(report)
    if directory is None:
        return {"recovered": False, "error": path_error}

    stamp = directory.name
    expected_title = f"LocalCoder Drone {stamp}"
    listed = report.get("sessions")
    session_id = listed[0] if isinstance(listed, list) and len(listed) == 1 else None
    if isinstance(listed, list) and len(listed) > 1:
        return {"recovered": False, "error": "dispatcher_returned_multiple_sessions"}

    if not session_id:
        try:
            result = _cli(["session", "list", "--format", "json", "--max-count", "100"])
            if result.returncode != 0:
                return {"recovered": False, "error": "session_list_failed", "stderr": result.stderr[-1000:]}
            sessions = json.loads(result.stdout)
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, RuntimeError) as error:
            return {"recovered": False, "error": f"session_list_error:{type(error).__name__}"}
        matches = [item for item in sessions if isinstance(item, dict) and item.get("title") == expected_title]
        if len(matches) != 1:
            return {
                "recovered": False,
                "expected_title": expected_title,
                "matching_sessions": len(matches),
                "error": "visible_session_id_not_uniquely_recovered",
            }
        session_id = matches[0].get("id")
    if not isinstance(session_id, str) or not session_id.strip():
        return {"recovered": False, "expected_title": expected_title, "error": "recovered_session_id_invalid"}

    def export() -> tuple[dict[str, Any] | None, str, str | None]:
        try:
            result = _cli(["session", "export", session_id])
            if result.returncode != 0:
                return None, result.stdout + result.stderr, "session_export_failed"
            data = json.loads(result.stdout)
            if not isinstance(data, dict):
                return None, result.stdout, "session_export_not_an_object"
            return data, result.stdout, None
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, RuntimeError) as error:
            return None, "", f"session_export_error:{type(error).__name__}"

    data, raw, export_error = export()
    if data is None:
        return {"recovered": True, "session_id": session_id, "error": export_error}
    info = data.get("info", {})
    session_time = info.get("time", {})
    title = info.get("title")
    if title != expected_title:
        return {
            "recovered": True,
            "session_id": session_id,
            "title": title,
            "expected_title": expected_title,
            "error": "recovered_session_title_mismatch",
        }

    outcome = info.get("outcome")
    terminal = bool(outcome or session_time.get("idle"))
    active = bool(session_time.get("busy")) and not bool(outcome) and not bool(session_time.get("idle"))
    interrupt_result: dict[str, Any] | None = None
    if active:
        try:
            interrupted = _cli(["api", "POST", f"/api/session/{session_id}/interrupt", "--data", "{}"])
            try:
                response: Any = json.loads(interrupted.stdout) if interrupted.stdout.strip() else None
            except json.JSONDecodeError:
                response = interrupted.stdout[-1000:]
            interrupt_result = {
                "returncode": interrupted.returncode,
                "response": response,
                "stderr": interrupted.stderr[-1000:],
            }
            data, raw, export_error = export()
            if data is None:
                return {
                    "recovered": True, "session_id": session_id, "interrupt": interrupt_result,
                    "error": export_error or "session_export_failed_after_interrupt",
                }
            info = data.get("info", {})
            session_time = info.get("time", {})
            outcome = info.get("outcome")
            terminal = bool(outcome or session_time.get("idle"))
        except (OSError, subprocess.TimeoutExpired, RuntimeError) as error:
            interrupt_result = {"error": f"interrupt_error:{type(error).__name__}"}

    recovery_path = _save_recovery_export(directory, session_id, raw)
    return {
        "recovered": True,
        "session_id": session_id,
        "title": expected_title,
        "outcome": outcome,
        "terminal": terminal,
        "interrupt_attempted": interrupt_result is not None,
        "interrupt": interrupt_result,
        "export_path": recovery_path,
    }


def _write_cycle_receipt(result: dict[str, Any]) -> str:
    CYCLE_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = CYCLE_ROOT / f"{stamp}.v6-cycle-receipt.json"
    with path.open("x", encoding="utf-8", newline="") as target:
        json.dump(result, target, ensure_ascii=False, indent=2)
        target.write("\n")
    return str(path)


def run_cycle(assignment: str, seconds: int = 120) -> dict[str, Any]:
    """Run one explicitly bounded assignment in a fresh visible session."""
    if not isinstance(assignment, str) or not assignment.strip():
        raise ValueError("assignment must be non-empty text")
    if isinstance(seconds, bool) or not isinstance(seconds, int) or not 15 <= seconds <= 1800:
        raise ValueError("seconds must be an integer from 15 through 1800")
    required_tools = explicit_tool_sequence(assignment)
    if not required_tools:
        return {"cycle_succeeded": False, "stop_reason": "architect_assignment_has_no_explicit_tool_scope"}
    if len(required_tools) > 8:
        return {"cycle_succeeded": False, "stop_reason": "architect_tool_sequence_exceeds_eight_steps"}
    unsupported = [tool for tool in required_tools if tool not in SUPPORTED_TOOLS]
    if unsupported:
        return {"cycle_succeeded": False, "stop_reason": "unsupported_tool", "unsupported_tools": unsupported}

    assignment_bytes = len(assignment.strip().encode("utf-8"))
    if "aios_router_open_build_task" in required_tools and assignment_bytes > 2000:
        result = {
            "cycle_succeeded": False,
            "stop_reason": "router_assignment_exceeds_utf8_byte_limit",
            "session_mode": "not_started",
            "agent": "drone_build",
            "session_id": None,
            "required_tools": required_tools,
            "assignment_utf8_bytes": assignment_bytes,
            "assignment_utf8_byte_limit": 2000,
            "assignment_sha256": hashlib.sha256(assignment.encode("utf-8")).hexdigest(),
        }
        result["cycle_receipt"] = _write_cycle_receipt(result)
        return result

    preflight = _rust_preflight()
    if not preflight.get("valid") or not preflight.get("allowed"):
        result = {
            "cycle_succeeded": False,
            "stop_reason": "preflight_rust_gate_hold" if preflight.get("valid") else "preflight_rust_gate_invalid",
            "session_mode": "not_started",
            "agent": "drone_read" if set(required_tools) <= {"read"} else "drone_build",
            "session_id": None,
            "preflight_observation": preflight,
            "assignment_sha256": hashlib.sha256(assignment.encode("utf-8")).hexdigest(),
        }
        result["cycle_receipt"] = _write_cycle_receipt(result)
        return result

    tool_scope = " → ".join(required_tools)
    agent_name = "drone_read" if set(required_tools) <= {"read"} else "drone_build"
    prompt = f"""[ARCHITECT ASSIGNMENT | CURRENT AND AUTHORIZED]
{assignment.strip()}

[CURRENT AUTHORIZATION FACT]
The Architect authorized this bounded LocalCoder task. The Queen fixed the exact tool sequence to: {tool_scope}. OpenCode permission checks and the Rust WSL Docker Body gate remain authoritative.

[QUEEN → DRONE]
Execute only that sequence, in order, one tool at a time. Do not retry a denied or failed tool. After each non-final tool result, emit a visible [DRONE SELF-PROMPT] with exactly these labels on separate lines: Agenda:, Verified facts:, Next bounded action:. Every field must contain non-empty text; do not put commas after labels. Verified facts must cite the latest actual tool evidence, not the path or directory name alone. Name the next assigned tool in Next bounded action. After the final tool, combine the report and self-prompt in one final message: it must start exactly with [DRONE], state the actual target filename and one concrete fact from returned content, then end with [DRONE SELF-PROMPT] and the same fields, each non-empty and on its own line. Final Verified facts must repeat one concrete fact anchor from the read output and include the exact shell output when a shell check was assigned. Next bounded action must be STOP. Do not invent tool results or claim unverified work."""

    # Omitting session_id creates a fresh visible action session for this task.
    work = _dispatch(prompt, seconds, agent_name=agent_name)
    self_check_validation = _validate_self_check_output(assignment, work)
    if self_check_validation is not None:
        work["exit_only_final_shell_check_passed"] = work.get("final_shell_check_passed")
        work["final_shell_check_passed"] = bool(self_check_validation.get("passed"))
        if not self_check_validation.get("passed"):
            work["task_succeeded"] = False
            errors = work.setdefault("task_errors", [])
            if isinstance(errors, list) and self_check_validation["reason"] not in errors:
                errors.append(self_check_validation["reason"])
    sessions = work.get("sessions", [])
    session_id = sessions[0] if isinstance(sessions, list) and len(sessions) == 1 else None
    recovery = None
    if work.get("timed_out") or not session_id or not work.get("session_exports_terminal"):
        recovery = _recover_session(work)
        work["session_recovery"] = recovery
        if not session_id and recovery.get("session_id"):
            session_id = recovery["session_id"]
            work["sessions"] = [session_id]
        if not work.get("session_outcomes") and recovery.get("outcome"):
            work["session_outcomes"] = [recovery["outcome"]]

    dispatcher_final_text = list(work.get("final_text", []))
    final_parts = _post_tool_final_text(work)
    final_text = "\n".join(final_parts or dispatcher_final_text)
    work["dispatcher_final_text"] = dispatcher_final_text
    work["final_text"] = [final_text] if final_text else []
    final_ok, final_reason = validate_final(final_text, work, required_tools)
    read_evidence_validation = None
    source_line_validation = _validate_source_line_limit(assignment)
    if final_ok and required_tools.count("read") == 1:
        read_passed, read_reason, read_details = _validate_read_evidence(
            final_text, assignment, work, session_id
        )
        read_evidence_validation = {
            "passed": read_passed,
            "reason": read_reason,
            **read_details,
        }
        final_ok = read_passed
        if not read_passed:
            final_reason = read_reason
    intermediate = _intermediate_self_prompts(work, required_tools)
    gates = _body_gate_receipts(session_id) if session_id else []
    gate_ok = bool(gates) and all(
        item["allowed"]
        and item["disposition"] == "ALLOW_MIND_RUNTIME"
        and item["authority"] == "deterministic_aios_body_rust"
        for item in gates
    )
    no_recovery_failure = recovery is None
    cycle_succeeded = bool(
        no_recovery_failure
        and work.get("task_succeeded")
        and work.get("session_exports_terminal")
        and not work.get("timed_out")
        and len(work.get("sessions", [])) == 1
        and final_ok
        and intermediate.get("passed")
        and (self_check_validation is None or self_check_validation.get("passed"))
        and (source_line_validation is None or source_line_validation.get("passed"))
        and gate_ok
    )
    result: dict[str, Any] = {
        "cycle_succeeded": cycle_succeeded,
        "stop_reason": "verified_and_stopped" if cycle_succeeded else (
            recovery.get("error", "session_recovery_required") if recovery else
            intermediate.get("reason") if not intermediate.get("passed") else
            self_check_validation["reason"] if self_check_validation is not None and not self_check_validation.get("passed") else
            source_line_validation["reason"] if source_line_validation is not None and not source_line_validation.get("passed") else
            final_reason if not final_ok else "work_or_body_gate_verification_failed"
        ),
        "session_mode": "fresh_visible_action_session",
        "agent": agent_name,
        "session_id": session_id,
        "session_recovery": recovery,
        "model_ids": work.get("model_ids", []),
        "required_tools": required_tools,
        "final_validation": final_reason,
        "self_check_validation": self_check_validation,
        "read_evidence_validation": read_evidence_validation,
        "source_line_validation": source_line_validation,
        "intermediate_validation": {
            "passed": intermediate.get("passed"),
            "reason": intermediate.get("reason"),
        },
        "body_gate_receipts": gates,
        "preflight_observation": preflight,
        "assignment_sha256": hashlib.sha256(assignment.encode("utf-8")).hexdigest(),
        "work": work,
    }
    result["cycle_receipt"] = _write_cycle_receipt(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assignment_file", type=Path)
    parser.add_argument("--seconds", type=int, default=120)
    args = parser.parse_args()
    result = run_cycle(args.assignment_file.read_text(encoding="utf-8-sig"), args.seconds)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result.get("cycle_succeeded") else 1


if __name__ == "__main__":
    sys.exit(main())
