"""Overnight runner: wait for the current deep run to finish, then run sleep cycles.

The Architect is asleep; this runs the whole night autonomously:
  1. Wait (poll) for the current deep-training run to finish.
  2. Run N sleep cycles (light sleep -> filter -> condense -> deep sleep).
Everything is logged to viv-overnight.log.
"""
import subprocess
import time
from pathlib import Path

PY = "L:/.venv/Scripts/python.exe"
DEEP_LOG = Path("L:/LocalCoder/.opencode/evals/viv-deep-training.log")
OVERNIGHT_LOG = Path("L:/LocalCoder/.opencode/evals/viv-overnight.log")
CYCLES = 3


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with OVERNIGHT_LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def deep_done() -> bool:
    if not DEEP_LOG.is_file():
        return False
    return '"event":"done"' in DEEP_LOG.read_text(encoding="utf-8", errors="replace")


def main() -> int:
    log("overnight runner started")
    log("waiting for current deep run to finish...")
    waits = 0
    while not deep_done():
        time.sleep(300)  # 5 min
        waits += 1
        if waits % 6 == 0:  # every 30 min
            log(f"still waiting for deep run ({waits * 5} min elapsed)...")
    log("deep run finished. starting sleep cycles.")
    rc = subprocess.call([PY, "-B", "L:/LocalCoder/workspace/autonomy/sleep_cycle.py", str(CYCLES)])
    log(f"sleep cycles complete (rc={rc}). overnight done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
