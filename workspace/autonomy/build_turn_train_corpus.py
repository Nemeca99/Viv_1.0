"""Build the turn-pair training corpus for the next phase.

The curated turn pairs are tiny (134 pairs). Repeat them enough to be learnable,
then append a bounded SODA replay slice so the dialogue layer is not erased.
The trainer samples random 128-token windows across the whole file, so the
replay:turn ratio is the token ratio.

Target mix: ~12% turn pairs, ~88% SODA replay.
"""
import argparse
import hashlib
from pathlib import Path

from tokenizers import Tokenizer

BPE = "L:/LocalCoder/models/viv_bpe_tokenizer.json"
TURN = Path("L:/LocalCoder/models/viv_turn_pairs.txt")
SODA = Path("L:/LocalCoder/models/viv_identity_soda.txt")
OUT = Path("L:/LocalCoder/models/viv_turn_train.txt")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repeat", type=int, default=100)
    ap.add_argument("--replay-tokens", type=int, default=1_000_000)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    tok = Tokenizer.from_file(BPE)
    turn_text = TURN.read_text(encoding="utf-8").rstrip("\n")
    turns = "\n\n".join([turn_text] * args.repeat)
    turn_tokens = len(tok.encode(turns).ids)

    parts = []
    replay_tokens = 0
    with SODA.open("r", encoding="utf-8") as fh:
        while replay_tokens < args.replay_tokens:
            chunk = fh.read(4_000_000)
            if not chunk:
                break
            n = len(tok.encode(chunk).ids)
            if replay_tokens + n > args.replay_tokens:
                # keep a proportional prefix of this chunk
                keep = int(len(chunk) * (args.replay_tokens - replay_tokens) / max(1, n))
                chunk = chunk[:keep]
                n = len(tok.encode(chunk).ids)
            parts.append(chunk)
            replay_tokens += n
    replay = "".join(parts)

    text = turns + "\n\n" + replay
    args.out.write_text(text, encoding="utf-8")
    total = turn_tokens + replay_tokens
    print(f"turn pairs: {TURN} x{args.repeat} = {turn_tokens:,} tokens")
    print(f"SODA replay: {replay_tokens:,} tokens")
    print(f"total: {total:,} tokens | turn share {100*turn_tokens/max(1,total):.2f}%")
    print(f"bytes: {len(text):,} | sha256 {hashlib.sha256(text.encode()).hexdigest()}")
    print(f"out: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
