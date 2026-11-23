"""Compute RLE = correct * exp(-(alpha*energy + beta*hops)) for a real task.

Wraps a command: samples baseline power, runs it, samples again, and produces a
real RLE reading.

    correct = 1 if the command exited 0 (the verifier's verdict)
    energy  = marginal power above idle * duration (joules)
    hops    = task path length (supplied; a probe/step count is the first proxy)

Run:
    L:.venv/Scripts/python.exe -B L:/LocalCoder/workspace/autonomy/rle.py --hops N -- <command...>
"""
import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from telemetry import sample  # noqa: E402

ALPHA = 1e-3   # cost of one joule against correctness (tunable)
BETA = 1e-2    # cost of one hop against correctness (tunable)


def _total_w(s):
    return (s.get("cpu_package_power_w") or 0.0) + (s.get("gpu_power_w") or 0.0)


def measure(command, hops):
    before = sample()
    p0 = _total_w(before)
    t0 = time.perf_counter()
    proc = subprocess.run(command, capture_output=True, text=True)
    t1 = time.perf_counter()
    after = sample()
    p1 = _total_w(after)
    duration = t1 - t0
    marginal_w = max(0.0, p1 - p0)
    energy = marginal_w * duration
    correct = 1 if proc.returncode == 0 else 0
    rle = correct * math.exp(-(ALPHA * energy + BETA * hops))
    return {
        "correct": correct,
        "exit_code": proc.returncode,
        "duration_s": round(duration, 4),
        "idle_w": round(p0, 2),
        "during_w": round(p1, 2),
        "marginal_w": round(marginal_w, 2),
        "energy_j": round(energy, 4),
        "hops": hops,
        "alpha": ALPHA,
        "beta": BETA,
        "RLE": round(rle, 6),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--hops", type=int, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not args.command or args.command[0] == "--":
        args.command = args.command[1:]
    if not args.command:
        print("no command supplied"); sys.exit(2)
    print(json.dumps(measure(args.command, args.hops), indent=2, default=str))
