"""Run one visible Drone plan/action cycle under the existing Body and tool gates."""
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

ROOT = Path(r"L:\LocalCoder")
DISPATCHER = ROOT / ".opencode/evals/run_local_agent_task.py"
PYTHON = Path(r"L:\.venv\Scripts\python.exe")
CYCLE_ROOT = ROOT / ".opencode/evals/drone_cycles"
BODY_RECEIPTS = ROOT / ".opencode/receipts"
TOOL_PATTERN = re.compile(r"\b(?:use|call|invoke)\s+(?:the\s+)?[`'\"]?([A-Za-z][A-Za-z0-9_.-]*)[`'\"]?\s+tool\b", re.IGNORECASE)
TARGET_PATTERN = re.compile(r"\bworkspace[\\/][A-Za-z0-9_.\\/-]+", re.IGNORECASE)


def explicit_tool_sequence(assignment: str) -> list[str]:
    """Extract ordered tool names explicitly granted in the Architect assignment."""
    found: list[str] = []
    for match in TOOL_PATTERN.finditer(assignment):
        name = match.group(1)
        if name not in found:
            found.append(name)
    return found


def _field(text: str, label: str) -> str:
    prefix = label.casefold() + ":"
    for line in text.splitlines():
        cleaned = line.strip().replace("**", "").lstrip("-* ").strip()
        if cleaned.casefold().startswith(prefix):
            return cleaned[len(prefix):].strip()
    return ""


def has_self_prompt(text: str) -> bool:
    lower = text.casefold()
    return "[drone self-prompt]" in lower and all(
        _field(text, label) for label in ("Agenda", "Verified facts", "Next bounded action")
    )


def validate_plan(text: str, assignment: str, required_tools: list[str]) -> tuple[bool, str]:
    """Require an evidence-honest plan whose next action matches the authorized tool order."""
    if not has_self_prompt(text):
        return False, "self_prompt_fields_missing"
    if not required_tools:
        return False, "architect_assignment_has_no_explicit_tool_scope"
    facts = _field(text, "Verified facts").casefold()
    if not (any(term in facts for term in ("none", "not yet", "not checked", "no repo", "no repository")) or re.search(r"\bno\b.{0,40}\b(?:repository|repo)\b.{0,30}\b(?:check|inspect|verif)", facts)):
        return False, "preflight_plan_claims_unverified_repository_facts"
    action = _field(text, "Next bounded action")
    lower_action = action.casefold()
    if required_tools[0].casefold() not in lower_action:
        return False, "plan_next_action_does_not_match_first_architect_tool"
    if re.search(r"\b(stop|wait|await|permission|authorization|approval)\b", lower_action):
        return False, "plan_waits_or_stops_despite_explicit_architect_tool_assignment"
    if not assignment.strip():
        return False, "architect_assignment_empty"
    for target in TARGET_PATTERN.findall(assignment):
        if target.rstrip(".,;:`'\"]").casefold() not in lower_action:
            return False, "plan_next_action_omits_explicit_target"
    return True, "plan_matches_current_architect_assignment"


def validate_final(text: str, work: dict, required_tools: list[str]) -> tuple[bool, str]:
    if not text.startswith("[DRONE]"):
        return False, "final_report_missing_drone_tag"
    if not has_self_prompt(text):
        return False, "final_self_prompt_fields_missing"
    action = _field(text, "Next bounded action").casefold()
    if not re.search(r"\bstop\b", action):
        return False, "final_self_prompt_does_not_stop_at_cycle_boundary"
    observed = work.get("tools", [])
    names = [item.get("tool") for item in observed]
    if names != required_tools or any(item.get("status") != "completed" for item in observed):
        return False, "observed_tools_do_not_match_architect_sequence"
    for check in work.get("shell_checks", []):
        output = str(check.get("output", "")).strip()
        if check.get("status") != "completed" or check.get("exit") != 0:
            return False, "shell_verification_failed"
        if output and output not in text:
            return False, "final_report_omits_actual_shell_output"
    return True, "final_report_and_tool_receipts_verified"


def _dispatch(prompt: str, seconds: int, session_id: str | None = None) -> dict:
    CYCLE_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    prompt_path = CYCLE_ROOT / f"{stamp}.prompt.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    command = [str(PYTHON), "-B", str(DISPATCHER), str(prompt_path), "--seconds", str(seconds), "--visible"]
    if session_id:
        command += ["--session", session_id]
    completed = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=seconds + 25
    )
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"dispatcher returned no JSON report; evidence prompt={prompt_path}") from error
    report["wrapper_exit"] = completed.returncode
    report["prompt_path"] = str(prompt_path)
    report["prompt_sha256"] = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    if completed.stderr.strip():
        report["stderr"] = completed.stderr[-4000:]
    return report


def _body_gate_receipts(session_id: str) -> list[dict]:
    receipts = []
    for path in BODY_RECEIPTS.glob("*-body-gate.json"):
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if receipt.get("session_id") != session_id:
            continue
        receipts.append({
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "source": receipt.get("source"),
            "allowed": receipt.get("allowed") is True,
            "disposition": receipt.get("disposition"),
            "authority": receipt.get("authority"),
            "architect_permission": receipt.get("architect_permission"),
            "reasons": receipt.get("reasons", []),
        })
    return sorted(receipts, key=lambda item: item["path"])


def _post_tool_final_text(work: dict) -> list[str]:
    """Read only assistant text after the final observed tool from the saved session export."""
    evidence = Path(str(work.get("evidence", "")))
    for session_id in work.get("sessions", []):
        path = evidence / f"{session_id}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        messages = data.get("messages", [])
        last_tool = max((index for index, message in enumerate(messages)
                         if message.get("type") == "assistant"
                         and any(part.get("type") == "tool" for part in message.get("content", []))), default=-1)
        for message in reversed(messages[last_tool + 1:]):
            if message.get("type") != "assistant" or message.get("finish") != "stop":
                continue
            visible = [part.get("text", "") for part in message.get("content", [])
                       if part.get("type") == "text" and part.get("text", "").strip()]
            if visible:
                return visible
    return []


def _write_cycle_receipt(session_id: str, result: dict) -> str:
    path = CYCLE_ROOT / f"{session_id}.cycle-receipt.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def run_cycle(assignment: str, seconds: int = 75) -> dict:
    """Generate a toolless plan, validate against the Architect scope, then dispatch once."""
    if not isinstance(assignment, str) or not assignment.strip():
        raise ValueError("assignment must be non-empty text")
    if isinstance(seconds, bool) or not isinstance(seconds, int) or not 15 <= seconds <= 300:
        raise ValueError("seconds must be an integer from 15 through 300")
    required_tools = explicit_tool_sequence(assignment)
    if not required_tools:
        return {"cycle_succeeded": False, "stop_reason": "architect_assignment_has_no_explicit_tool_scope"}

    tool_scope = " → ".join(required_tools)
    plan_prompt = f"""[DRONE PLAN ONLY | NO TOOLS]
[ARCHITECT ASSIGNMENT | CURRENT AND AUTHORIZED]
{assignment.strip()}

[CURRENT AUTHORIZATION FACT]
 The Architect authorized continuing the Drone workflow goal. The Queen bounded this diagnostic to the explicitly named tool sequence `{tool_scope}`. It is authorized only for this diagnostic, subject to OpenCode policy and the Rust Body gate. This does not expand the Architect's goal or the tool sequence.

[QUEEN → DRONE]
This turn is planning only; the runtime hides every tool. Return a visible `[DRONE SELF-PROMPT]` with fields Agenda, Verified facts, Next bounded action. State that no repository facts have been checked in this turn. The next action must name the first authorized tool `{required_tools[0]}` and, if a target path is in the assignment, repeat that exact path. Do not say to stop, wait, or request permission for this already assigned first tool. A final STOP clause in the assignment applies only after its work is complete. Stop after the self-prompt."""
    plan = _dispatch(plan_prompt, seconds)
    sessions = plan.get("sessions", [])
    session_id = sessions[0] if len(sessions) == 1 else ""
    plan_text = "\n".join(plan.get("final_text", []))
    plan_ok, plan_reason = validate_plan(plan_text, assignment, required_tools)
    plan_report_ok = bool(
        session_id
        and plan.get("session_outcomes") == ["succeeded"]
        and plan.get("session_exports_terminal")
        and not plan.get("timed_out")
        and not plan.get("tools")
        and plan.get("task_errors") == ["tool_action_missing"]
        and plan_ok
    )
    if not plan_report_ok:
        result = {
            "cycle_succeeded": False,
            "stop_reason": "plan_receipt_or_authorization_alignment_failed",
            "plan_validation": plan_reason,
            "session_id": session_id or None,
            "required_tools": required_tools,
            "plan_text": plan_text,
            "plan": plan,
            "assignment_sha256": hashlib.sha256(assignment.encode("utf-8")).hexdigest(),
        }
        if session_id:
            result["body_gate_receipts"] = _body_gate_receipts(session_id)
            result["cycle_receipt"] = _write_cycle_receipt(session_id, result)
        return result

    work_prompt = f"""[ARCHITECT ASSIGNMENT | CURRENT AND AUTHORIZED]
{assignment.strip()}

[CURRENT AUTHORIZATION FACT]
The Architect authorized the ongoing Drone workflow goal; the Queen selected this single-tool diagnostic within that goal. Follow only this bounded scope; the previous Drone self-prompt is a proposal. The assignment gate enforces the named sequence, and the Rust WSL Docker Body gate must allow each model/tool request.

[QUEEN → DRONE]
This task requires exactly the explicitly named tool sequence `{tool_scope}`. Call each assigned tool once and do not call shell or any other tool; this read-only status task needs no code verification. After the tool result, immediately give a short visible final response starting `[DRONE]`, copy the actual `project_root`, then end with `[DRONE SELF-PROMPT]` fields Agenda, Verified facts, Next bounded action: STOP; await Queen."""
    work = _dispatch(work_prompt, seconds, session_id=session_id)
    dispatcher_final_text = list(work.get("final_text", []))
    final_text = "\n".join(_post_tool_final_text(work))
    work["dispatcher_final_text"] = dispatcher_final_text
    work["final_text"] = [final_text] if final_text else []
    final_ok, final_reason = validate_final(final_text, work, required_tools)
    gates = _body_gate_receipts(session_id)
    gate_ok = bool(gates) and all(
        item["allowed"]
        and item["disposition"] == "ALLOW_MIND_RUNTIME"
        and item["authority"] == "deterministic_aios_body_rust"
        for item in gates
    )
    cycle_succeeded = bool(
        work.get("task_succeeded")
        and work.get("session_exports_terminal")
        and not work.get("timed_out")
        and final_ok
        and gate_ok
    )
    result = {
        "cycle_succeeded": cycle_succeeded,
        "stop_reason": "verified_and_stopped" if cycle_succeeded else "work_final_or_body_gate_verification_failed",
        "plan_validation": plan_reason,
        "final_validation": final_reason,
        "model_ids": work.get("model_ids", []),
        "required_tools": required_tools,
        "session_id": session_id,
        "visible_pre_work_self_prompt": plan_text,
        "assignment_sha256": hashlib.sha256(assignment.encode("utf-8")).hexdigest(),
        "plan": plan,
        "work": work,
        "body_gate_receipts": gates,
    }
    result["cycle_receipt"] = _write_cycle_receipt(session_id, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assignment_file", type=Path)
    parser.add_argument("--seconds", type=int, default=75)
    args = parser.parse_args()
    result = run_cycle(args.assignment_file.read_text(encoding="utf-8-sig"), args.seconds)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result.get("cycle_succeeded") else 1


if __name__ == "__main__":
    sys.exit(main())
