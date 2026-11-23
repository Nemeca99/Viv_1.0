"""Human-readable live terminal dashboard for the LocalCoder Hive and INN farm."""
from __future__ import annotations

import argparse
import json
import math
import os
import socket
import sqlite3
import subprocess
import sys
import time
import textwrap
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "autonomy"
DB_PATH = STATE_DIR / "state.sqlite3"
INN_STATE = STATE_DIR / "inn_hive_state.json"
EXPERIENCES = STATE_DIR / "learning" / "inn_hive_experiences.jsonl"
LEARNING_STATUS = STATE_DIR / "learning" / "multi_daemon_status.json"

GREEN = "\x1b[92m"
YELLOW = "\x1b[93m"
RED = "\x1b[91m"
CYAN = "\x1b[96m"
DIM = "\x1b[90m"
RESET = "\x1b[0m"
BOLD = "\x1b[1m"


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def lattice_edges(snapshot_name: str | None, limit: int = 90) -> list[tuple[str, str, float]]:
    """Read the active learner snapshot's real SQLite links in read-only mode."""
    if not snapshot_name:
        return []
    graph = STATE_DIR / "learning" / "neural_runs" / snapshot_name / "neuron_graph.sqlite3"
    try:
        with sqlite3.connect(f"file:{graph.resolve()}?mode=ro", uri=True, timeout=0.5) as con:
            tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if {"neurons", "links"}.issubset(tables):
                rows = con.execute(
                    """SELECT l.source_id, l.peer_id, l.weight
                       FROM links l
                       JOIN neurons s ON s.neuron_id=l.source_id
                       JOIN neurons t ON t.neuron_id=l.peer_id
                       ORDER BY l.weight DESC, l.source_id, l.peer_id LIMIT ?""", (limit,)
                ).fetchall()
            elif {"neuron_identity", "links"}.issubset(tables):
                rows = con.execute(
                    """SELECT l.source_id, l.peer_id, l.weight
                       FROM links l
                       JOIN neuron_identity s ON s.neuron_id=l.source_id
                       JOIN neuron_identity t ON t.neuron_id=l.peer_id
                       ORDER BY l.weight DESC, l.source_id, l.peer_id LIMIT ?""", (limit,)
                ).fetchall()
            else:
                return []
        return [(str(source), str(target), float(weight or 0.0)) for source, target, weight in rows]
    except (OSError, sqlite3.Error):
        return []


def lattice_ascii(snapshot_name: str | None, width: int = 76, height: int = 18) -> list[str]:
    """Render a bounded 2D ASCII projection of the links read from SQLite.

    Coordinates are only a deterministic screen projection; the nodes and edges
    themselves come from the daemon's verified snapshot, never from a simulator.
    """
    edges = lattice_edges(snapshot_name)
    if not edges:
        return ["2D LATTICE  unavailable (no readable verified SQLite links)"]
    node_ids = sorted({node for edge in edges for node in edge[:2]})
    positions = {}
    for index, node_id in enumerate(node_ids):
        angle = (index / max(1, len(node_ids))) * math.tau
        radius = 0.34 + (index % 5) * 0.045
        x = int((0.5 + radius * math.cos(angle)) * (width - 1))
        y = int((0.5 + radius * math.sin(angle)) * (height - 1))
        positions[node_id] = (max(0, min(width - 1, x)), max(0, min(height - 1, y)))
    canvas = [[" " for _ in range(width)] for _ in range(height)]

    def mark_line(x0: int, y0: int, x1: int, y1: int) -> None:
        steps = max(abs(x1 - x0), abs(y1 - y0), 1)
        for step in range(steps + 1):
            x = round(x0 + (x1 - x0) * step / steps)
            y = round(y0 + (y1 - y0) * step / steps)
            if 0 <= x < width and 0 <= y < height and canvas[y][x] == " ":
                canvas[y][x] = "."

    for source, target, _ in edges:
        mark_line(*positions[source], *positions[target])
    for index, node_id in enumerate(node_ids):
        x, y = positions[node_id]
        canvas[y][x] = "o" if len(node_id) > 0 else str(index % 10)
    return ["2D LATTICE  live SQLite projection (o neuron, . verified link)", *["".join(row) for row in canvas]]


def read_setting(con: sqlite3.Connection, key: str, default=None):
    row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row[0])
    except (TypeError, ValueError):
        return default


def service_online(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False


def queen_processor() -> str:
    """Read Ollama's own live placement report; never guess from configuration."""
    try:
        result = subprocess.run(["ollama", "ps"], capture_output=True, text=True,
                                timeout=2, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        rows = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        return rows[1] if len(rows) > 1 else "model not loaded"
    except (OSError, subprocess.SubprocessError):
        return "Ollama placement unavailable"


def load_receipts() -> list[dict]:
    try:
        with EXPERIENCES.open("r", encoding="utf-8") as stream:
            return [json.loads(line) for line in stream if line.strip()]
    except (OSError, ValueError):
        return []


def age_text(timestamp: float | None) -> str:
    if not timestamp:
        return "never"
    age = max(0, time.time() - timestamp)
    if age < 60:
        return f"{age:.0f}s ago"
    if age < 3600:
        return f"{age / 60:.1f}m ago"
    return f"{age / 3600:.1f}h ago"


def flag(value, true_text="YES", false_text="NO") -> str:
    if value is True:
        return f"{GREEN}{true_text}{RESET}"
    if value is False:
        return f"{RED}{false_text}{RESET}"
    return f"{YELLOW}N/A{RESET}"


def action_text(receipt: dict, owner: str, farm: dict) -> str:
    legacy_owner = {"model_queen": "architect", "inn_drone": "drone"}.get(owner, owner)
    action = receipt.get(f"{owner}_action") or receipt.get(f"{legacy_owner}_action")
    if not action and owner == "model_queen":
        tool = farm.get("lastTool")
        return f"{tool} (legacy receipt)" if tool else receipt.get(f"{legacy_owner}_choice", "-")
    if not action:
        return receipt.get(f"{owner}_choice") or receipt.get(f"{legacy_owner}_choice") or "unavailable"
    plots = ""
    if action.get("plot_a") is not None:
        plots = f" plot {action['plot_a']}"
    if action.get("plot_b") not in (None, 0, action.get("plot_a")):
        plots += f" + {action['plot_b']}"
    return f"{action.get('tool', '?')}{plots} [{action.get('stage', '?')}]"


def percent(count: int, total: int) -> str:
    return f"{100 * count / total:5.1f}%" if total else "  n/a"


def decision_value(receipt: dict, current: str, legacy: str):
    return receipt.get(current, receipt.get(legacy))


def snapshot() -> str:
    now = time.time()
    settings = {}
    events = []
    task_events = []
    cycle_start = None
    try:
        with sqlite3.connect(DB_PATH, timeout=1) as con:
            for key in ("enabled", "worker", "supervisor", "task_list", "worker_mode"):
                settings[key] = read_setting(con, key)
            events = con.execute(
                "SELECT at,kind,data FROM events ORDER BY id DESC LIMIT 6").fetchall()
            task_events = con.execute(
                "SELECT at,kind,data FROM events "
                "WHERE kind IN ('task_selected','task_completed','worker_error') "
                "ORDER BY id DESC LIMIT 30").fetchall()
            row = con.execute(
                "SELECT at,data FROM events WHERE kind='inn_hive_cycle_started' "
                "ORDER BY id DESC LIMIT 1").fetchone()
            if row:
                cycle_start = {"at": row[0], **json.loads(row[1])}
    except sqlite3.Error:
        pass

    state = read_json(INN_STATE, {})
    learning_status = read_json(LEARNING_STATUS, {})
    learning_snapshot = learning_status.get("latest_snapshot")
    farm = state.get("r", {})
    distillation = state.get("distillation") or {}
    receipts = load_receipts()
    latest = receipts[-1] if receipts else {}
    worker = settings.get("worker") or {}
    supervisor = settings.get("supervisor") or {}
    worker_live = worker.get("state") == "running" and now - worker.get("at", 0) < 30
    supervisor_live = supervisor.get("state") == "watching" and now - supervisor.get("at", 0) < 10
    ollama_live = service_online("127.0.0.1", 11434)
    queen_runtime = queen_processor() if ollama_live else "Ollama offline"

    role_correct_receipts = [r for r in receipts if "model_queen_correct" in r]
    queen_known = [r for r in role_correct_receipts if r.get("model_queen_correct") is not None]
    drone_known = [r for r in role_correct_receipts if r.get("inn_drone_correct") is not None]
    agreement_known = [r for r in role_correct_receipts if r.get("agreement") is not None]
    queen_wins = sum(r.get("model_queen_correct") is True for r in queen_known)
    drone_wins = sum(r.get("inn_drone_correct") is True for r in drone_known)
    agreements = sum(r.get("agreement") is True for r in agreement_known)
    candidate_counts = [len(r.get("evaluations") or []) for r in receipts]
    multi_choice = sum(count > 1 for count in candidate_counts)

    current_task = None
    current_task_at = None
    for at, kind, data in task_events:
        try:
            payload = json.loads(data)
        except (TypeError, ValueError):
            continue
        if kind == "task_selected":
            current_task = payload.get("kind") or payload.get("id")
            current_task_at = at
            break
        if kind == "task_completed":
            break
    receipt_age = (now - EXPERIENCES.stat().st_mtime) if EXPERIENCES.exists() else None
    cycle_active = bool(cycle_start and (not latest or cycle_start["at"] > datetime.fromisoformat(
                         latest["at_utc"]).timestamp()))
    if cycle_active:
        learning_state = f"{GREEN}FARM CYCLE RUNNING{RESET}"
    elif worker_live and current_task:
        learning_state = f"{YELLOW}WAITING - Hive is running {current_task}{RESET}"
    elif worker_live:
        learning_state = f"{YELLOW}WAITING FOR NEXT TASK{RESET}"
    else:
        learning_state = f"{RED}WORKER NOT ACTIVE{RESET}"

    lines = [
        f"{BOLD}{CYAN}LOCALCODER  |  INN QUEEN + HIVE + RUST FARM{RESET}",
        f"{DIM}{datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}  |  refresh 2s  |  Ctrl+C to exit{RESET}",
        "=" * 78,
        f"SYSTEM   Autonomy {flag(settings.get('enabled'))}   Worker {flag(worker_live, 'LIVE', 'STALE')} "
        f"({age_text(worker.get('at'))})   Supervisor {flag(supervisor_live, 'LIVE', 'STALE')}   "
        f"Ollama {flag(ollama_live, 'ONLINE', 'OFFLINE')}",
        f"         Worker PID {worker.get('pid', '-')}   Supervisor PID {supervisor.get('pid', '-')}   "
        f"Mode {settings.get('worker_mode') or 'hive'}",
        f"PLACEMENT Model Queen: {queen_runtime[:62]}",
        "          INN drone: CPU   Rust oracle/farm: CPU",
        f"CURRENT  {learning_state}   "
        f"Elapsed {age_text(current_task_at) if current_task_at else '-'}",
        "-" * 78,
        f"LEARNER  {('RUNNING' if learning_status.get('running') else 'STOPPED')}   "
        f"snapshot {learning_snapshot or 'none'}   "
        f"E/N {learning_status.get('epoch_progress_edges_per_node', '-')}   "
        f"graduated {learning_status.get('total_graduated', 0)}",
        *lattice_ascii(learning_snapshot),
        "-" * 78,
        f"FARM     Tick {farm.get('tick', '-'):,}   Steps {farm.get('steps', '-'):,}   "
        f"Bank {farm.get('bank', '-')}   Active plots {farm.get('active', '-')}/{farm.get('max', '-')}",
        f"         Harvests {farm.get('harvests', '-'):,}   Decays {farm.get('decays', '-'):,}   "
        f"Invalid {farm.get('invalid', '-'):,}   Last reward {farm.get('lastReward', '-')}",
        "-" * 78,
        f"LEARNING Role-correct cycles {len(role_correct_receipts)} (legacy {len(receipts) - len(role_correct_receipts)} excluded)   "
        f"Model Queen correct {queen_wins}/{len(queen_known)} {percent(queen_wins, len(queen_known))}",
        f"         "
        f"INN drone correct {drone_wins}/{len(drone_known)} {percent(drone_wins, len(drone_known))}",
        f"         Agreement {agreements}/{len(agreement_known)} {percent(agreements, len(agreement_known))}   "
        f"Multi-candidate cycles {multi_choice}/{len(receipts)}",
        f"         Distillation lessons {distillation.get('lessons', 0)}   "
        f"teacher accepted {distillation.get('teacher_verified', 0)}   "
        f"teacher rejected {distillation.get('teacher_rejected', 0)}",
        "-" * 78,
        f"LATEST   Farm cycle {age_text(EXPERIENCES.stat().st_mtime) if EXPERIENCES.exists() else 'never'}   "
        f"Tick {latest.get('tick', '-')}   Candidates {len(latest.get('evaluations') or [])}",
        f"         Model Queen: {action_text(latest, 'model_queen', farm)}   Correct {flag(decision_value(latest, 'model_queen_correct', 'architect_correct'))}",
        f"         INN drone  : {action_text(latest, 'inn_drone', farm)}   Correct {flag(decision_value(latest, 'inn_drone_correct', 'drone_correct'))}",
        f"         Oracle: {action_text(latest, 'oracle', farm)}   Agreement {flag(latest.get('agreement'))}",
    ]

    lines.extend(["-" * 78, "DECISION EVIDENCE (observable inputs, proposals, and Rust evaluation)"])
    if cycle_active:
        lines.append(f"  Cycle started {age_text(cycle_start['at'])}; farm tick {cycle_start.get('tick', '-')}; "
                     f"{cycle_start.get('candidate_count', 0)} candidates offered to the drone.")
        proposal = cycle_start.get("inn_drone_action") or cycle_start.get("queen_action")
        lines.append(f"  INN drone proposal: {action_text({'inn_drone_action': proposal}, 'inn_drone', farm)}")
        lines.append("  candidate  action                         score     gate")
        for candidate in cycle_start.get("candidates", [])[:12]:
            action = action_text({'model_queen_action': candidate.get('action')}, 'model_queen', farm)
            lines.append(f"  {candidate['candidate_id'][:8]}   {action[:28]:28} "
                         f"{float(candidate.get('score') or 0):8.4f} {float(candidate.get('gate') or 0):8.4f}")
        lines.append(f"  {YELLOW}Drone proposal and Rust oracle comparison are in progress.{RESET}")
    elif latest:
        lines.append("  candidate  action                         score     gate    legal  reward  Rust utility")
        for candidate in latest.get("evaluations") or []:
            action = action_text({'model_queen_action': candidate.get('action')}, 'model_queen', farm)
            utility = ",".join(str(value) for value in candidate.get("utility") or [])
            score = candidate.get("score")
            gate = candidate.get("gate")
            lines.append(f"  {candidate['candidate_id'][:8]}   {action[:28]:28} "
                         f"{float(score or 0):8.4f} {float(gate or 0):8.4f} "
                         f"{str(candidate.get('legal')):5} {float(candidate.get('reward') or 0):7.2f} [{utility}]")
        if not latest.get("evaluations"):
            lines.append("  No completed counterfactual evaluations recorded yet.")
    else:
        lines.append("  No INN/Hive farm receipt exists yet.")

    rationale = (latest.get("model_queen") or latest.get("drone") or {}).get("rationale")
    error = (latest.get("model_queen") or latest.get("drone") or {}).get("error")
    if error:
        lines.append(f"         {RED}Drone error: {error[:62]}{RESET}")
    elif rationale:
        lines.append("  Model Queen recorded rationale:")
        lines.extend(f"    {DIM}{part}{RESET}" for part in textwrap.wrap(rationale, width=70)[:4])
    lesson = latest.get("distillation_lesson") or {}
    if lesson:
        decision = "IMITATE" if lesson.get("accepted") else "REJECT"
        lines.append(f"  Distillation: {decision} Queen action; signal {lesson.get('signal')}; "
                     f"INN updates +{lesson.get('engine_updates_applied', 0)}")
    if receipt_age is not None and receipt_age > 60 and current_task != "farm_learning":
        lines.append(f"         {YELLOW}Farm data is unchanged because the scheduler has not started another farm cycle.{RESET}")

    if latest.get("dialogue"):
        lines.extend(["-" * 78, "QUEEN / DRONE CONVERSATION"])
        for turn in latest["dialogue"]:
            speaker = turn.get("speaker", "Unknown")
            for part in textwrap.wrap(str(turn.get("content", "")), width=66) or [""]:
                lines.append(f"  {speaker:12}: {part}")
    lines.extend(["-" * 78, "RECENT FARM CYCLES"])
    for receipt in receipts[-6:][::-1]:
        choice = action_text(receipt, "model_queen", farm)
        lines.append(f"  tick {receipt.get('tick', '-'):<10} candidates {len(receipt.get('evaluations') or []):<2} "
                     f"Queen {flag(decision_value(receipt, 'model_queen_correct', 'architect_correct'))} "
                     f"INN {flag(decision_value(receipt, 'inn_drone_correct', 'drone_correct'))} "
                     f"{choice[:27]}")
    lines.extend(["-" * 78, "RECENT HIVE ACTIVITY"])
    for at, kind, data in events[:5]:
        try:
            payload = json.loads(data)
            detail = payload.get("result") or payload.get("status") or payload.get("error") or ""
        except (TypeError, ValueError):
            detail = ""
        stamp = datetime.fromtimestamp(at).strftime("%H:%M:%S")
        lines.append(f"  {stamp}  {kind[:35]:35} {str(detail)[:30]}")
    if not events:
        lines.append("  No Hive events available.")
    lines.append("=" * 78)
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Live LocalCoder Hive and INN dashboard")
    parser.add_argument("--once", action="store_true", help="print one snapshot and exit")
    parser.add_argument("--refresh", type=float, default=2.0, help="seconds between updates")
    args = parser.parse_args()
    if os.name == "nt":
        os.system("")  # enable ANSI handling in current Windows console
    try:
        while True:
            if not args.once:
                sys.stdout.write("\x1b[2J\x1b[H")
            print(snapshot(), flush=True)
            if args.once:
                return
            time.sleep(max(0.5, args.refresh))
    except KeyboardInterrupt:
        print("\nDashboard closed.")


if __name__ == "__main__":
    main()
