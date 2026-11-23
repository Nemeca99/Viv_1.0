"""Extract SODA dialogue (1.19M conversations) into Viv's spoken-line corpus.

SODA is a large-scale social-dialogue dataset: real, modern conversations in
everyday situations. Each row's `dialogue` field is a list of utterances. We
flatten every utterance to a plain spoken line -- the raw experience she trains
on to learn to speak. No classifier, no template: it is already correct speech.
"""
import pandas as pd
from pathlib import Path

SODA = "F:/Viv_Data/source_dialogue/allenai_soda_fdc848ab0183208ea7808206c91c724414d0a071/train.parquet"
OUT = Path("L:/LocalCoder/models/viv_soda_dialogue.txt")


def main() -> int:
    print("reading parquet (dialogue column only)...", flush=True)
    df = pd.read_parquet(SODA, columns=["dialogue"])

    lines = []
    for d in df["dialogue"]:
        for u in d:
            u = u.strip()
            if u:
                lines.append(u)

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"rows: {len(df)} -> {len(lines)} spoken lines -> {OUT} ({OUT.stat().st_size / 1e6:.1f} MB)")
    print("=== sample ===")
    for ln in lines[:12]:
        print(" ", ln)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
