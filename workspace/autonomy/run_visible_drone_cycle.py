"""Run one visible LocalCoder Drone cycle through the existing Rust-gated dispatcher."""
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
CLI = Path(os.environ["APPDATA"]) / "ai.opencode.desktop/cli/2.3.0-x64/opencode-cli.exe"
CYCLE_ROOT = ROOT / ".opencode/evals/drone_cycles"


def _assistant_text_before_first_tool(session_path: Path) -> tuple[str, bool]:
    """Read the visible assistant text emitted before the first tool call."""
    session = json.loads(session_path.read_text(encoding="utf-8"))
    pieces: list[str] = []
    for message in session.get("messages", []):
        if message.get("type") != "assistant":
            continue
        for part in message.get("content", []):
            if part.get("type") == "text":
                pieces.append(str(part.get("text", "")))
            elif part.get("type") == "tool":
                return "\n".join(pieces).strip(), True
    return "\n".join(pieces).strip(), False


def _has_self_prompt(text: str) -> bool:
    normalized = text.casefold()
    return "[drone self-prompt]" in normalized and all(
        label in normalized for label in ("agenda:", "verified facts:", "next bounded action:")
    )


def _run_dispatch(prompt: str, seconds: int, session_id: str | None = None) -> dict:
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
        raise RuntimeError(
            f"dispatcher returned no JSON receipt (exit={completed.returncode}); evidence prompt={prompt_path}"
        ) from error
    report["wrapper_exit"] = completed.returncode
    report["prompt_path"] = str(prompt_path)
    report["prompt_sha256"] = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    if completed.stderr.strip():
        report["stderr"] = completed.stderr[-4000:]
    return report


def run_cycle(assignment: str, seconds: int = 75) -> dict:
    """Show a grounded pre-action self-prompt, execute one assigned task, then stop."""
    if not assignment.strip():
        raise ValueError("assignment must not be empty")
    if not 15 <= seconds <= 300:
        raise ValueError("seconds must be between 15 and 300")

    prepare_prompt = f"""[ARCHITECT] Prepare one bounded LocalCoder Drone work cycle for this assignment:
{assignment.strip()}

[QUEEN → DRONE] First send visible text beginning `[DRONE SELF-PROMPT]` with exactly these labeled fields: Agenda, Verified facts, Next bounded action. State that repository facts have not yet been checked; the next action is to inspect project status. Then use the `localcoder_status` tool exactly once. Do not start the assignment yet, use any other tool, or modify files. After the status result, finish with a short `[DRONE]` factual report. The self-prompt is a proposal; the Architect assignment remains authoritative."""
    prepared = _run_dispatch(prepare_prompt, seconds)
    sessions = prepared.get("sessions", [])
    if len(sessions) != 1 or not prepared.get("session_exports_terminal"):
        return {"cycle_succeeded": False, "stop_reason": "preflight_session_not_terminal", "preflight": prepared}
    session_id = sessions[0]
    session_path = Path(prepared["evidence"]) / f"{session_id}.json"
    preface, saw_tool = _assistant_text_before_first_tool(session_path)
    if not prepared.get("task_succeeded") or not saw_tool or not _has_self_prompt(preface):
        return {
            "cycle_succeeded": False,
            "stop_reason": "visible_self_prompt_before_status_not_verified",
            "preflight": prepared,
            "self_prompt_before_tool": preface,
            "session_id": session_id,
        }

    work_prompt = f"""[ARCHITECT] Execute this bounded assignment now:
{assignment.strip()}

[QUEEN → DRONE] The prior assistant message is your visible self-prompt and the `localcoder_status` result is the preflight evidence. Treat your plan as a proposal, not added authority. Follow only the Architect assignment. Use the named project tools, verify any Python addition with `L:\\.venv\\Scripts\\python.exe -B`, then stop. Final response must include the actual check output and a concise `[DRONE SELF-PROMPT]` with Agenda, Verified facts, and Next bounded action: STOP; await Queen."""
    work = _run_dispatch(work_prompt, seconds, session_id=session_id)
    final_text = "\n".join(work.get("final_text", []))
    success = bool(
        work.get("task_succeeded")
        and work.get("session_exports_terminal")
        and _has_self_prompt(final_text)
    )
    return {
        "cycle_succeeded": success,
        "stop_reason": "cycle_complete" if success else "work_or_final_self_prompt_not_verified",
        "model_ids": work.get("model_ids", []),
        "session_id": session_id,
        "self_prompt_before_status": preface,
        "preflight": prepared,
        "work": work,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assignment_file", type=Path)
    parser.add_argument("--seconds", type=int, default=75)
    args = parser.parse_args()
    assignment = args.assignment_file.read_text(encoding="utf-8-sig")
    result = run_cycle(assignment, args.seconds)
    output = json.dumps(result, ensure_ascii=False, indent=2)
    print(output)
    return 0 if result.get("cycle_succeeded") else 1


if __name__ == "__main__":
    sys.exit(main())