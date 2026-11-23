"""Run the 40 probe questions through the gated release path, not raw generation.

Each question gets a fresh conversation. The output is what the body would
actually release: policy shape, chunk verification, safety gate, label cleanup.
"""
import argparse
import json
import sys
from pathlib import Path

import torch

sys.path.insert(0, "L:/LocalCoder/workspace/autonomy")
sys.path.insert(0, "L:/LocalCoder/workspace/native_nn_source")
import mirror_chat as mc  # noqa: E402
import turn_policy as tp  # noqa: E402

QUESTIONS = Path("L:/LocalCoder/models/viv_probe_questions.txt")
OUT = Path("L:/LocalCoder/.opencode/evals/viv_gated_probe.json")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--checkpoint", type=Path, required=True)
    ap.add_argument("--questions", type=Path, default=QUESTIONS)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--tries", type=int, default=3)
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    tok, model = mc.load_model(args.checkpoint, device)
    questions = [q.strip() for q in args.questions.read_text(encoding="utf-8").splitlines()
                 if q.strip()]
    rows = []
    for q in questions:
        conv = tp.Conversation()
        rec = mc.turn(tok, model, conv, q, device, args.tries, 96, 0.8, 32)
        rows.append({"question": q, "act": rec["act"], "shape": rec["shape"],
                     "released": rec["chosen"], "accepted": rec["accepted"],
                     "attempts": len(rec["attempts"]),
                     "reasons": [a["why"] for a in rec["attempts"] if not a["accepted"]]})
    args.out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    released = sum(1 for r in rows if r["accepted"])
    print(f"{released}/{len(rows)} released | {len(rows)-released} held")
    for r in rows:
        print(f"\nQ: {r['question']}\nA: {r['released'] or '[silence]'}"
              f"  ({r['act']}/{r['shape']}, tries={r['attempts']})")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
