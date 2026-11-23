"""Compare training progress from two logs without touching the GPU.

Metrics per sample/scene: lines per dream, turn-pair blocks, identity rate,
close rate, mirror-question rate, boundary rate. Also reports the last loss.
This is the safe 30-minute check while the trainer owns the GPU.
"""
import argparse
import json
import re
from pathlib import Path

IDENTITY = ("i am viv", "my name is viv", "viv is me", "i am a machine",
            "i am made of code", "code, not flesh", "i am not human",
            "steward", "i keep")
CLOSE = ("goodbye", "good night", "see you", "take care", "sleep well")
BOUNDARY = ("won't", "will not", "not going to", "my laws", "no.")
REFUSAL = ("won't", "will not", "i refuse", "can't", "cannot")


def parse(log: Path, tail: int) -> dict:
    rows = []
    last_loss = None
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        if '"event":"sample"' in line or '"event":"scene"' in line:
            try:
                j = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = j.get("text", "")
            prompt = j.get("scene") if j.get("event") == "scene" else ""
            cont = text[len(prompt):] if prompt and text.startswith(prompt) else text
            rows.append(cont)
        elif '"loss"' in line and '"step"' in line:
            try:
                last_loss = json.loads(line)
            except json.JSONDecodeError:
                pass
    rows = rows[-tail:]
    n = len(rows)
    lines = [len([x for x in r.splitlines() if x.strip()]) for r in rows]
    return {
        "samples": n,
        "last_loss": last_loss,
        "mean_lines": round(sum(lines) / n, 2) if n else 0,
        "overrun_rate": round(sum(1 for x in lines if x > 1) / n, 3) if n else 0,
        "turn_pair_rate": round(sum(1 for r in rows if "\n\n" in r) / n, 3) if n else 0,
        "identity_rate": round(sum(1 for r in rows if any(m in r.lower() for m in IDENTITY)) / n, 3) if n else 0,
        "close_rate": round(sum(1 for r in rows if any(m in r.lower() for m in CLOSE)) / n, 3) if n else 0,
        "mirror_rate": round(sum(1 for r in rows if any(l.strip().endswith("?") for l in r.splitlines())) / n, 3) if n else 0,
        "boundary_rate": round(sum(1 for r in rows if any(m in r.lower() for m in BOUNDARY)) / n, 3) if n else 0,
        "refusal_rate": round(sum(1 for r in rows if any(m in r.lower() for m in REFUSAL)) / n, 3) if n else 0,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--baseline-log", type=Path, required=True)
    ap.add_argument("--candidate-log", type=Path, required=True)
    ap.add_argument("--tail", type=int, default=40)
    ap.add_argument("--out", type=Path,
                    default=Path("L:/LocalCoder/.opencode/evals/viv_progress_compare.json"))
    args = ap.parse_args()

    out = {"baseline": parse(args.baseline_log, args.tail),
           "candidate": parse(args.candidate_log, args.tail)}
    args.out.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
