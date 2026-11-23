"""Build a long-turn dialogue lane from SODA, labelled and inside the context cap.

Why this exists: the turn-pair corpus has a median of 4 words and a 99th
percentile of 13, and it is ~half of the training mix, so the dominant signal
teaches "answer in four words". Nothing in the mix asks for a 20-35 word turn.
This lane does, using real SODA turns with real speaker names.

Hard constraint: the model has 128 positions. A block must fit in ~100 tokens
(prompt 32 / output 96 is imposed later by context_budget), so a block of three
20-35 word turns is the largest honest unit. This lane cannot exceed that, and
no corpus change can, until the context does.
"""
import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pyarrow.parquet as pq
from tokenizers import Tokenizer

SODA = ("F:/Viv_Data/source_dialogue/"
        "allenai_soda_fdc848ab0183208ea7808206c91c724414d0a071/train.parquet")
BPE = "L:/LocalCoder/models/viv_bpe_tokenizer.json"
OUT = Path("L:/LocalCoder/models/viv_long_turns.txt")
MANIFEST = Path("L:/LocalCoder/models/viv_long_turns.json")

IDENTITY = ("i am viv", "my name is viv", "i am a machine", "i am not human",
            "code, not flesh", "steward", "architect")


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip()).strip('"')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--blocks", type=int, default=400)
    ap.add_argument("--turns", type=int, default=3)
    ap.add_argument("--min-words", type=int, default=16)
    ap.add_argument("--max-words", type=int, default=35)
    ap.add_argument("--max-block-tokens", type=int, default=100)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--manifest", type=Path, default=MANIFEST)
    args = ap.parse_args()

    tok = Tokenizer.from_file(BPE)
    f = pq.ParquetFile(SODA)
    blocks, skipped_short, skipped_long, skipped_ident, skipped_tokens = [], 0, 0, 0, 0
    word_counts = []

    for batch in f.iter_batches(batch_size=256, columns=["speakers", "dialogue"]):
        if len(blocks) >= args.blocks:
            break
        for row in batch.to_pylist():
            spk = row.get("speakers") or []
            dlg = row.get("dialogue") or []
            if len(dlg) < args.turns or len(spk) < args.turns:
                skipped_short += 1
                continue
            turns = [clean(x) for x in dlg[:args.turns]]
            words = [len(t.split()) for t in turns]
            if any(w < args.min_words for w in words):
                skipped_short += 1
                continue
            if any(w > args.max_words for w in words):
                skipped_long += 1
                continue
            if any(m in " ".join(turns).lower() for m in IDENTITY):
                skipped_ident += 1
                continue
            if len(set(spk[:args.turns])) < 2:
                continue
            block = "\n".join(f"{s}: {t}" for s, t in zip(spk[:args.turns], turns))
            n = len(tok.encode(block).ids)
            if n > args.max_block_tokens:
                skipped_tokens += 1
                continue
            blocks.append(block)
            word_counts.append(sum(words))

    text = "\n\n".join(blocks) + "\n"
    args.out.write_text(text, encoding="utf-8")

    manifest = {
        "schema": "viv_long_turns/1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": SODA,
        "blocks": len(blocks),
        "turns_per_block": args.turns,
        "word_range": [args.min_words, args.max_words],
        "max_block_tokens": args.max_block_tokens,
        "words_per_block": {
            "min": min(word_counts), "max": max(word_counts),
            "mean": round(sum(word_counts) / len(word_counts), 1)} if word_counts else {},
        "skipped": {"short_turn": skipped_short, "long_turn": skipped_long,
                    "identity_leak": skipped_ident, "over_token_cap": skipped_tokens},
        "path": str(args.out),
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
        "note": "real SODA turns with speaker labels; no identity lines, no generated text",
    }
    args.manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    print("=== sample ===")
    print(blocks[0] if blocks else "(none)")
    return 0 if blocks else 2


if __name__ == "__main__":
    raise SystemExit(main())
