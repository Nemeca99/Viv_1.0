"""One-shot, visible, self-prompt-gated Drone cycle using the existing dispatcher."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(r"L:\LocalCoder")
DISPATCHER = ROOT / ".opencode/evals/run_local_agent_task.py"
PYTHON = Path(r"L:\.venv\Scripts\python.exe")
CYCLE_ROOT = ROOT / ".opencode/evals/drone_cycles"


def _dispatch(prompt: str, seconds: int, session_id: str | None = None) -> dict:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    CYCLE_ROOT.mkdir(parents=True, exist_ok=True)
    prompt_path = CYCLE_ROOT / f"{stamp}.prompt.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    command = [str(PYTHON), "-B", str(DISPATCHER), str(prompt_path), "--seconds", str(seconds), "--visible"]
    if session_id:
        command += ["--session", session_id]
    completed = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=seconds + 25
    )
    report = json.loads(completed.stdout)
    report["wrapper_exit"] = completed.returncode
    report["prompt_path"] = str(prompt_path)
    report["prompt_sha256"] = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    if completed.stderr.strip():
        report["stderr"] = completed.stderr[-4000:]
    return report


def _self_prompt(text: str) -> bool:
    lower = text.casefold()
    return "[drone self-prompt]" in lower and all(
        field in lower for field in ("agenda:", "verified facts:", "next bounded action:")
    )


def run_cycle(assignment: str, seconds: int = 75) -> dict:
    """Require a visible plan-only turn before dispatching the Architect task once."""
    if not isinstance(assignment, str) or not assignment.strip():
        raise ValueError("assignment must be non-empty text")
    if isinstance(seconds, bool) or not isinstance(seconds, int) or not 15 <= seconds <= 300:
        raise ValueError("seconds must be an integer from 15 through 300")

    plan_prompt = f"""[ARCHITECT] Prepare a visible self-prompt for this bounded assignment:
{assignment.strip()}

[QUEEN → DRONE] This is the planning turn. Do not call tools or execute actions. Return only a concise visible `[DRONE SELF-PROMPT]` with exactly these labeled fields: Agenda, Verified facts, Next bounded action. Say that no repository facts have been checked in this turn. Choose one next step that follows the Architect assignment. Treat this self-prompt as a proposal, not authority; stop after writing it."""
    plan = _dispatch(plan_prompt, seconds)
    sessions = plan.get("sessions", [])
    plan_text = "\n".join(plan.get("final_text", []))
    expected_plan_receipt = (
        len(sessions) == 1
        and plan.get("session_outcomes") == ["succeeded"]
        and plan.get("session_exports_terminal")
        and plan.get("tools") == []
        and plan.get("task_errors") == ["tool_action_missing"]
        and _self_prompt(plan_text)
    )
    if not expected_plan_receipt:
        return {
            "cycle_succeeded": False,
            "stop_reason": "plan_turn_receipt_or_self_prompt_invalid",
            "plan": plan,
            "plan_text": plan_text,
        }

    session_id = sessions[0]
    work_prompt = f"""[ARCHITECT] Execute this bounded assignment now:
{assignment.strip()}

[QUEEN → DRONE] Your immediately preceding assistant message is the visible self-prompt proposal. Follow the Architect assignment exactly; do not expand scope from your own plan. After every tool result, emit a concise `[DRONE SELF-PROMPT]` containing one verified fact and the next bounded action before any further tool call. Verify requested Python work with `L:\\.venv\\Scripts\\python.exe -B`. Stop after the assignment is verified. Final response must report actual outputs and finish with `[DRONE SELF-PROMPT]` fields Agenda, Verified facts, Next bounded action: STOP; await Queen."""
    work = _dispatch(work_prompt, seconds, session_id=session_id)
    final_text = "\n".join(work.get("final_text", []))
    success = bool(work.get("task_succeeded") and work.get("session_exports_terminal") and _self_prompt(final_text))
    result = {
        "cycle_succeeded": success,
        "stop_reason": "verified_and_stopped" if success else "work_receipt_or_final_self_prompt_invalid",
        "model_ids": work.get("model_ids", []),
        "session_id": session_id,
        "visible_pre_work_self_prompt": plan_text,
        "plan": plan,
        "work": work,
        "assignment_sha256": hashlib.sha256(assignment.encode("utf-8")).hexdigest(),
    }
    receipt_path = CYCLE_ROOT / f"{session_id}.cycle-receipt.json"
    receipt_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["cycle_receipt"] = str(receipt_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assignment_file", type=Path)
    parser.add_argument("--seconds", type=int, default=75)
    args = parser.parse_args()
    result = run_cycle(args.assignment_file.read_text(encoding="utf-8-sig"), args.seconds)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("cycle_succeeded") else 1


if __name__ == "__main__":
    sys.exit(main())