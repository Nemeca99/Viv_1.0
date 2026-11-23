"""Crash a private standby worker and verify handle-based recovery and pause.

This checks lifecycle recovery with an explicitly seeded interrupted task, not
learning quality. It does not terminate the production worker.
"""
from pathlib import Path
import json
import os
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from viv_autonomy import Store, seed_task


def until(fn, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = fn()
        if value:
            return value
        time.sleep(0.2)
    raise TimeoutError("Supervisor proof condition not reached")


proof = ROOT / "autonomy" / "proofs" / ("supervisor_" + str(time.time_ns()))
store = Store(proof)
store.set("worker_mode", "standby")
task_id = store.add(seed_task())
with store.connect() as con:
    con.execute("UPDATE tasks SET status='running' WHERE id=?", (task_id,))
env = dict(os.environ, VIV_AUTONOMY_STATE=str(proof))
with (proof / "supervisor.log").open("wb") as log:
    process = subprocess.Popen([sys.executable, str(ROOT / "viv_autonomy.py"), "supervise"], env=env,
                               stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        original = until(lambda: (store.get("worker") or {}).get("pid"))
        until(lambda: store.status()["tasks"][0]["status"] == "retry")
        initial_launches = until(lambda: (store.get("supervisor") or {}).get("launches"))
        store.set("worker", {"pid": original, "at": 0, "state": "running"})
        time.sleep(2)
        assert store.get("supervisor")["launches"] == initial_launches, "Stale heartbeat caused a duplicate"
        os.kill(original, signal.SIGTERM)
        replacement = until(lambda: ((store.get("worker") or {}).get("pid")
                                     if (store.get("worker") or {}).get("pid") != original else None))
        until(lambda: store.get("supervisor")["launches"] > initial_launches)
        receipt = {"passed": True, "original_worker_pid": original, "replacement_worker_pid": replacement,
                   "restarted_after_real_process_exit": True, "stale_heartbeat_did_not_restart": True,
                   "seeded_interrupted_task_recovered": True, "workload": "private_standby_worker"}
    finally:
        store.set("enabled", False)
        store.set("supervisor_stop", True)
        process.wait(timeout=20)
    assert store.get("supervisor")["state"] == "stopped"
    receipt["pause_and_supervisor_shutdown_verified"] = True
    (proof / "verification.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps({"passed": True, "receipt": str(proof / "verification.json")}))
