"""Build the full mixed corpus for the next training phase.

Layers on top of the last good checkpoint (step 25,250):

- turn pairs (identity, closing, mirror, ack, contrast, greeting, boundary,
  constraint), repeated so they are learnable
- observation pairs (third-person listen -> comprehension -> first-person
  participation), repeated
- SODA replay, so the dialogue layer is not erased

The trainer samples random 128-token windows across the whole file, so the
shares below are token shares.
"""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from tokenizers import Tokenizer

BPE = "L:/LocalCoder/models/viv_bpe_tokenizer.json"
TURN = Path("L:/LocalCoder/models/viv_turn_pairs.txt")
OBS = Path("L:/LocalCoder/models/viv_observation_pairs.txt")
LONG = Path("L:/LocalCoder/models/viv_long_turns.txt")
SODA = Path("L:/LocalCoder/models/viv_identity_soda.txt")
OUT = Path("L:/LocalCoder/models/viv_full_training.txt")
MANIFEST = Path("L:/LocalCoder/models/viv_full_training.json")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--turn-repeat", type=int, default=500)
    ap.add_argument("--obs-repeat", type=int, default=12)
    ap.add_argument("--replay-tokens", type=int, default=10_000_000)
    ap.add_argument("--turn", type=Path, default=TURN)
    ap.add_argument("--obs", type=Path, default=OBS)
    ap.add_argument("--long-lane", type=Path, default=None,
                    help="long-turn dialogue lane (models/viv_long_turns.txt)")
    ap.add_argument("--long-repeat", type=int, default=1)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--manifest", type=Path, default=MANIFEST)
    args = ap.parse_args()

    tok = Tokenizer.from_file(BPE)
    turn_text = args.turn.read_text(encoding="utf-8").rstrip("\n")
    obs_text = args.obs.read_text(encoding="utf-8").rstrip("\n")
    turns = "\n\n".join([turn_text] * args.turn_repeat)
    obs = "\n\n".join([obs_text] * args.obs_repeat)
    turn_tokens = len(tok.encode(turns).ids)
    obs_tokens = len(tok.encode(obs).ids)

    long_text = ""
    long_tokens = 0
    if args.long_lane:
        long_text = ("\n\n".join([args.long_lane.read_text(encoding="utf-8").rstrip("\n")]
                                 * args.long_repeat))
        long_tokens = len(tok.encode(long_text).ids)

    parts = []
    replay_tokens = 0
    with SODA.open("r", encoding="utf-8") as fh:
        while replay_tokens < args.replay_tokens:
            chunk = fh.read(4_000_000)
            if not chunk:
                break
            n = len(tok.encode(chunk).ids)
            if replay_tokens + n > args.replay_tokens:
                keep = int(len(chunk) * (args.replay_tokens - replay_tokens) / max(1, n))
                chunk = chunk[:keep]
                n = len(tok.encode(chunk).ids)
            parts.append(chunk)
            replay_tokens += n
    replay = "".join(parts)

    text = turns + "\n\n" + obs + "\n\n" + long_text + "\n\n" + replay
    args.out.write_text(text, encoding="utf-8")
    total = turn_tokens + obs_tokens + long_tokens + replay_tokens
    manifest = {
        "schema": "viv_full_training/1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": {"turn": str(args.turn), "observation": str(args.obs),
                    "long": str(args.long_lane) if args.long_lane else None,
                    "soda": str(SODA)},
        "turn_repeat": args.turn_repeat,
        "obs_repeat": args.obs_repeat,
        "long_repeat": args.long_repeat,
        "tokens": {"turn": turn_tokens, "observation": obs_tokens,
                   "long": long_tokens, "soda": replay_tokens, "total": total},
        "share": {"turn": round(100 * turn_tokens / total, 2),
                  "observation": round(100 * obs_tokens / total, 2),
                  "long": round(100 * long_tokens / total, 2),
                  "soda": round(100 * replay_tokens / total, 2)},
        "path": str(args.out),
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
    }
    args.manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    print(f"out bytes: {len(text):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
