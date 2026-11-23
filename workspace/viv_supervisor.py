"""Observe actual child-process exit and restart the local autonomous worker.

Heartbeat age alone never triggers replacement. An OS lock prevents competing
supervisors; worker handles and the worker's own OS lock prevent duplicate work.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

from viv_autonomy import ROOT, STATE, Store, file_lock, launch_worker_process, worker_alive


def supervisor_alive():
    try:
        with file_lock(STATE / "supervisor.lock"):
            return False
    except RuntimeError:
        return True


def start_supervisor():
    store = Store()
    if not store.get("enabled"):
        return "Autonomy paused."
    if supervisor_alive():
        return "Autonomous supervisor is running."
    with (STATE / "supervisor.log").open("ab") as log:
        process = subprocess.Popen([sys.executable, str(ROOT / "viv_autonomy.py"), "supervise"], cwd=ROOT,
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                   creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
    return f"Autonomous supervisor launched (PID {process.pid})."


def supervise():
    store = Store()
    with file_lock(STATE / "supervisor.lock"):
        child = None
        launches = 0
        failures = 0
        next_launch = 0.0
        launched_at = 0.0
        store.event("supervisor_started", {"pid": os.getpid()})
        try:
            while True:
                now = time.time()
                if child is not None and child.poll() is not None:
                    exit_code = child.returncode
                    store.event("worker_process_exited", {"launcher_pid": child.pid, "exit_code": exit_code})
                    failures = (failures + 1) if now - launched_at < 60 else 0
                    next_launch = now + (min(60, 2 ** failures) if exit_code else 1)
                    child = None
                enabled = store.get("enabled") is True
                alive = worker_alive()
                if store.get("supervisor_stop") and child is None and not alive:
                    break
                # Adopt observation of an existing worker, without assuming a
                # stale heartbeat proves process death or attempting to kill it.
                if enabled and child is None and not alive and now >= next_launch:
                    launched = launch_worker_process()
                    if isinstance(launched, subprocess.Popen):
                        child = launched
                        launched_at = now
                        launches += 1
                        store.event("supervisor_launched_worker", {"launcher_pid": child.pid, "launch": launches})
                store.set("supervisor", {"pid": os.getpid(), "at": now,
                          "state": "watching" if enabled else "paused",
                          "child_launcher_pid": child.pid if child else None, "launches": launches,
                          "restart_backoff_seconds": max(0, round(next_launch - now))})
                time.sleep(1)
        finally:
            store.set("supervisor", {"pid": os.getpid(), "at": time.time(), "state": "stopped"})
