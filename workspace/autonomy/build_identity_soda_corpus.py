"""Build the identity + SODA corpus: 9M spoken lines with identity interleaved.

SODA is the raw experience (real conversation). Identity is the anchor -- we
interleave one identity line every N SODA lines so she keeps her self while
learning to speak, the same way the movie-dialogue corpus did. Streamed so the
774 MB input is never fully loaded into memory.
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, "L:/LocalCoder/workspace/autonomy")
from generate_neuron_corpus import IDENTITY  # noqa: E402

SODA = Path("L:/LocalCoder/models/viv_soda_dialogue.txt")
OUT = Path("L:/LocalCoder/models/viv_identity_soda.txt")
INTERLEAVE = 20  # one identity line every N dialogue lines


def main() -> int:
    rng = random.Random(20261121)
    total = 0
    identity_count = 0
    with OUT.open("w", encoding="utf-8") as out, SODA.open("r", encoding="utf-8") as src:
        for i, line in enumerate(src):
            line = line.strip()
            if not line:
                continue
            out.write(line + "\n")
            total += 1
            if i % INTERLEAVE == 0:
                out.write(rng.choice(IDENTITY) + "\n")
                identity_count += 1
    print(f"total lines: {total} | identity lines: {identity_count}")
    print(f"output: {OUT} ({OUT.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
