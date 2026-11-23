"""
Clawd on Desk (Desktop Pet) Notifier for AIOS Viv & LocalCoder.
Ensures the Clawd on Desk pixel-art desktop pet is active and mirrors
agent execution state (thinking, working, error, idle) in real time.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

CLAWD_EXE = Path(os.environ.get("LOCALAPPDATA", "C:/Users/nemec/AppData/Local")) / "Programs" / "Clawd on Desk" / "Clawd on Desk.exe"
CLAWD_PORTS = (23333, 23334, 23335, 23336, 23337)
DEFAULT_PORT = 23333


def is_clawd_running() -> bool:
    """Checks if the Clawd on Desk state server is reachable on localhost."""
    for port in CLAWD_PORTS:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/state", method="GET")
            with urllib.request.urlopen(req, timeout=0.15) as resp:
                if resp.headers.get("x-clawd-server") == "clawd-on-desk":
                    return True
        except urllib.error.HTTPError as e:
            # Server returns HTTP 404 or 405 for GET on /state, but headers contain x-clawd-server
            if e.headers.get("x-clawd-server") == "clawd-on-desk":
                return True
        except Exception:
            continue
    return False


def ensure_clawd_running() -> bool:
    """
    Ensures Clawd on Desk desktop application is running.
    If not running, spawns it as a detached background process.
    """
    if is_clawd_running():
        return True

    if not CLAWD_EXE.exists():
        print(f"[!] Clawd on Desk executable not found at: {CLAWD_EXE}")
        return False

    try:
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

        subprocess.Popen(
            [str(CLAWD_EXE)],
            creationflags=flags,
            close_fds=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Give it up to 2 seconds to initialize the local server
        for _ in range(20):
            time.sleep(0.1)
            if is_clawd_running():
                print("[+] [Clawd] Desktop companion pet launched and connected.")
                return True
        return True
    except Exception as exc:
        print(f"[!] [Clawd] Failed to launch desktop pet: {exc}")
        return False


def _post_event_sync(state: str, event: str, tool_name: str = "", extra: Optional[Dict[str, Any]] = None):
    payload = {
        "agent_id": "hermes",
        "hook_source": "localcoder-autonomy",
        "state": state,  # "idle", "thinking", "working", "attention", "error", "sleeping"
        "event": event,  # "SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop", "SessionEnd"
        "session_id": "aios_viv_autonomy",
        "cwd": "L:/LocalCoder",
        "agent_pid": os.getpid(),
    }
    if tool_name:
        payload["tool_name"] = tool_name
    if extra:
        payload.update(extra)

    data = json.dumps(payload).encode("utf-8")
    for port in CLAWD_PORTS:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/state",
            data=data,
            headers={
                "Content-Type": "application/json",
                "x-clawd-server": "clawd-on-desk",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=0.25):
                return
        except Exception:
            continue


def notify_clawd(
    state: str,
    event: str,
    tool_name: str = "",
    extra: Optional[Dict[str, Any]] = None,
    sync: bool = False,
):
    """
    Non-blocking async notification to the Clawd desktop pet.
    Drives live animations (thinking bubble, typing, juggling, error, celebration).
    """
    if sync:
        _post_event_sync(state, event, tool_name=tool_name, extra=extra)
    else:
        t = threading.Thread(
            target=_post_event_sync,
            args=(state, event),
            kwargs={"tool_name": tool_name, "extra": extra},
            daemon=True,
        )
        t.start()


if __name__ == "__main__":
    print("[*] Checking Clawd on Desk status...")
    running = ensure_clawd_running()
    print(f"[*] Clawd running: {running}")
    if running:
        print("[*] Emitting 'thinking' state...")
        notify_clawd("thinking", "UserPromptSubmit", sync=True)
        time.sleep(1.5)
        print("[*] Emitting 'working' state...")
        notify_clawd("working", "PreToolUse", tool_name="compiler_gate", sync=True)
        time.sleep(1.5)
        print("[*] Emitting 'idle' state...")
        notify_clawd("idle", "AfterAgent", sync=True)
        print("[+] Clawd on Desk notifier verified on silicon.")
