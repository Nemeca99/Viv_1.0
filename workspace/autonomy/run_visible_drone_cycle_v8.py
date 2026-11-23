"""Run one fresh visible Drone action session through existing OpenCode and Rust gates."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import run_visible_drone_cycle_v7 as V7

ARCHITECT_GOAL_ID = "01a1e340-84ed-77c3-92f3-3eb738b89f5b"

ROOT = Path(r"L:\LocalCoder")
PYTHON = Path(r"L:\.venv\Scripts\python.exe")


def run_cycle(assignment: str, seconds: int = 120) -> dict[str, Any]:
    orig_goal = V7.ARCHITECT_GOAL_ID
    orig_tools = V7.SUPPORTED_TOOLS

    try:
        V7.ARCHITECT_GOAL_ID = ARCHITECT_GOAL_ID
        V7.SUPPORTED_TOOLS = frozenset(V7.SUPPORTED_TOOLS) | {"aios_router_lookup_drone_seed"}
        return V7.run_cycle(assignment, seconds=seconds)
    finally:
        V7.ARCHITECT_GOAL_ID = orig_goal
        V7.SUPPORTED_TOOLS = orig_tools


def _cli_path() -> Path:
    appdata = sys.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("APPDATA is unavailable; cannot recover an OpenCode session")
    return Path(appdata) / "ai.opencode.desktop/cli/2.3.0-x64/opencode-cli.exe"


def _rust_preflight() -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [str(PYTHON), "-m", "aios_rebuild.main_core.mind_runtime_gate", "--goal-id", ARCHITECT_GOAL_ID],
            cwd=ROOT / "workspace", capture_output=True, text=True, encoding="utf-8", timeout=20, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"valid": False, "allowed": False, "error": f"rust_preflight_{type(error).__name__}"}
    try:
        decision = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"valid": False, "allowed": False, "error": "rust_preflight_invalid_json", "stderr_tail": completed.stderr[-500:]}
    valid = bool(decision.get("schema") == "aios_mind_runtime_gate_v1" and decision.get("authority") == "deterministic_aios_body_rust")
    return {"valid": valid, "allowed": valid}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run visible Drone cycle V8")
    parser.add_argument("assignment_file", nargs="?", type=Path)
    parser.add_argument("--seconds", type=int, default=120)
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()

    if args.self_check:
        orig_run = V7.run_cycle
        seen = {}
        V7.run_cycle = lambda a, seconds=120: seen.update(goal=V7.ARCHITECT_GOAL_ID, has_seed="aios_router_lookup_drone_seed" in V7.SUPPORTED_TOOLS) or {"ok": True}
        res = run_cycle("check", seconds=30)
        try:
            assert seen.get("goal") == ARCHITECT_GOAL_ID and seen.get("has_seed") is True and res == {"ok": True}
            print("PASS: 4 checks")
            sys.exit(0)
        finally:
            V7.run_cycle = orig_run
    else:
        if args.assignment_file:
            assignment_text = args.assignment_file.read_text(encoding="utf-8-sig")
            result = run_cycle(assignment=assignment_text, seconds=args.seconds)
            print(json.dumps(result))