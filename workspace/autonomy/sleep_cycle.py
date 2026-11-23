"""The sleep cycle: light sleep makes, deep sleep consolidates.

The Architect's loop, made to run:
  light sleep -> free-flow (training with scene injection -> verbose dreams)
  body filter -> grade + keep the in-character dreams, reject drift (the journal)
  score gate  -> the acceptance rate decides whether consolidation may run
  deep sleep  -> train on the accepted journal + base corpus (consolidation)
  repeat

The generative condense step is intentionally not called: it failed (she cannot
summarize yet). Training is the compaction.

The grader's feedback is real but bounded: an accepted dream is replayed into
the deep-sleep corpus (keep), a rejected dream is excluded and preserved as
evidence (penalty). If acceptance falls below the floor, deep sleep is skipped
so that drift is not consolidated into the weights.

Each phase is a subprocess of the existing scripts. This is the orchestration,
not the model. Run it and it cycles until told to stop.
"""
import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

PY = "L:/.venv/Scripts/python.exe"
AUTO = Path("L:/LocalCoder/workspace/autonomy")
MODELS = Path("L:/LocalCoder/models")
EVALS = Path("L:/LocalCoder/.opencode/evals")

CORPUS = MODELS / "viv_identity_dialogue.txt"
# The mixed corpus (turn pairs + observation pairs + SODA replay). The sleep cycle
# defaulted to identity-only dialogue, which contradicts the guidepost lever
# ("Phase 6-7 fluency, not more identity") and drops the turn/safety replay that
# holds the current checkpoint's behaviour.
MIXED = MODELS / "viv_full_training.txt"
DREAMS = MODELS / "viv_dreams.txt"
GRADES = MODELS / "viv_dream_grades.json"
LIGHT_LOG = EVALS / "viv-cycle-light.log"
DEEP_LOG = EVALS / "viv-cycle-deep.log"
FILTER_LOG = EVALS / "viv-cycle-filter.log"
CYCLE_JOURNAL = EVALS / "viv-sleep-cycle.jsonl"


def run(args: list[str], log: Path) -> int:
    cmd = [PY, "-B"] + args
    print(f"  -> {' '.join(args[-2:])} -> {log.name}", flush=True)
    with log.open("w", encoding="utf-8") as fh:
        return subprocess.call(cmd, stdout=fh, stderr=subprocess.STDOUT)


def latest_checkpoint() -> Path | None:
    dirs = sorted(d for d in (MODELS / "viv_bpe").iterdir() if (d / "model.pt").is_file())
    return dirs[-1] / "model.pt" if dirs else None


def read_grades() -> dict | None:
    if not GRADES.is_file():
        return None
    try:
        return json.loads(GRADES.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def last_event(log: Path, name: str) -> dict | None:
    """Last JSON line in log carrying this event (None if absent)."""
    if not log.is_file():
        return None
    found = None
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        if f'"event":"{name}"' in line:
            try:
                found = json.loads(line)
            except json.JSONDecodeError:
                continue
    return found


def append_journal(record: dict) -> None:
    CYCLE_JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with CYCLE_JOURNAL.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, separators=(",", ":")) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cycles", nargs="?", type=int, default=3)
    ap.add_argument("light_steps", nargs="?", type=int, default=3000)
    ap.add_argument("light_seconds", nargs="?", type=float, default=3600.0)
    ap.add_argument("deep_steps", nargs="?", type=int, default=8000)
    ap.add_argument("deep_seconds", nargs="?", type=float, default=7200.0)
    ap.add_argument("--min-acceptance", type=float, default=0.5,
                    help="deep sleep is skipped if the filter accepts less than this")
    ap.add_argument("--corpus", type=Path, default=MIXED,
                    help="base corpus for light and deep sleep (default: the mixed "
                         "corpus; identity-only dialogue is the wrong lever now)")
    # These were previously not passed at all, so the trainer fell back to its own
    # defaults: lr 2e-4 (4x the rate every phase since consolidation used) and
    # batch 6 (the activation peak that spilled 1.33 GB over PCIe and tripped the
    # nvlddmkm TDR). Both are now explicit and default to the proven values.
    ap.add_argument("--lr", type=float, default=5e-5)
    ap.add_argument("--batch", type=int, default=3)
    ap.add_argument("--grad-accum", type=int, default=2)
    ap.add_argument("--save-every", type=int, default=250)
    ap.add_argument("--device", default=None)
    args = ap.parse_args()

    if not args.corpus.is_file():
        raise SystemExit(f"corpus not found: {args.corpus}")
    train_flags = ["--lr", str(args.lr), "--batch", str(args.batch),
                   "--grad-accum", str(args.grad_accum),
                   "--save-every", str(args.save_every)]
    if args.device:
        train_flags += ["--device", args.device]

    for c in range(1, args.cycles + 1):
        record = {"cycle": c, "started_at": datetime.now(timezone.utc).isoformat(),
                  "min_acceptance": args.min_acceptance,
                  "corpus": str(args.corpus), "lr": args.lr, "batch": args.batch,
                  "grad_accum": args.grad_accum, "save_every": args.save_every}

        ckpt = latest_checkpoint()
        resume = ["--resume", str(ckpt)] if ckpt else []
        record["light_checkpoint"] = str(ckpt) if ckpt else None
        print(f"\n=== cycle {c} — LIGHT SLEEP (free-flow, makes dreams) ===", flush=True)
        record["light_rc"] = run([str(AUTO / "train_viv_bpe.py"), "--corpus", str(args.corpus),
                                  "--steps", str(args.light_steps),
                                  "--max-seconds", str(args.light_seconds),
                                  *train_flags, *resume], LIGHT_LOG)

        print(f"=== cycle {c} — BODY FILTER (grade + journal) ===", flush=True)
        record["filter_rc"] = run([str(AUTO / "filter_dreams.py"), "--log", str(LIGHT_LOG),
                                   "--out", str(DREAMS), "--grades", str(GRADES)], FILTER_LOG)
        grades = read_grades()
        if record["filter_rc"] != 0 or grades is None:
            record["status"] = "stopped_filter_failed"
            append_journal(record)
            print(f"filter failed (rc={record['filter_rc']}, grades={'present' if grades else 'missing'})"
                  f" — no deep sleep; evidence in {FILTER_LOG}", flush=True)
            return 2

        totals = grades["totals"]
        record["grades"] = {"totals": totals, "by_category": grades["by_category"],
                            "score": grades["score"],
                            "hard_stops": grades["hard_stops"]["count"],
                            "receipt": str(GRADES)}
        print(f"graded {totals['dreams']} dreams | accepted {totals['accepted']}"
              f" | acceptance {totals['acceptance']:.3f} | hard stops"
              f" {grades['hard_stops']['count']}", flush=True)
        if totals["dreams"] == 0:
            record["status"] = "stopped_no_dreams"
            append_journal(record)
            print("no dreams produced — no deep sleep", flush=True)
            return 2
        if totals["acceptance"] < args.min_acceptance:
            record["status"] = "stopped_low_acceptance"
            record["gate_passed"] = False
            append_journal(record)
            print(f"acceptance {totals['acceptance']:.3f} < floor {args.min_acceptance}"
                  f" — refusal to consolidate drift; receipt {GRADES}", flush=True)
            return 2
        record["gate_passed"] = True

        ckpt = latest_checkpoint()
        resume_deep = ["--resume", str(ckpt)] if ckpt else []
        print(f"=== cycle {c} — DEEP SLEEP (consolidate accepted dreams) ===", flush=True)
        record["deep_rc"] = run([str(AUTO / "train_viv_bpe.py"),
                                 "--corpus", str(DREAMS), str(args.corpus),
                                 "--steps", str(args.deep_steps),
                                 "--max-seconds", str(args.deep_seconds),
                                 *train_flags, *resume_deep], DEEP_LOG)
        done = last_event(DEEP_LOG, "done")
        record["deep"] = done if done else {"event": "missing"}
        record["status"] = "complete" if record["deep_rc"] == 0 else "deep_failed"
        append_journal(record)
        if done:
            print(f"deep sleep done — steps {done.get('steps')} loss {done.get('loss')}"
                  f" -> {done.get('checkpoint')}", flush=True)
        else:
            print(f"deep sleep rc={record['deep_rc']} (no done event) — see {DEEP_LOG}",
                  flush=True)

    print("\n=== sleep cycles complete ===", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
