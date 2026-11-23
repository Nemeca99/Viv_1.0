"""Build the identity + dialogue training corpus.

Stage 2: she learns to SPEAK. Identity is the ground (first-person anchor,
interleaved); dialogue is the conversation (natural speech, all three persons).
Facts (world knowledge) come later, once she can speak -- per the Architect.

The parse output is "CHARACTER=>DIALOGUE". We strip the character label and
keep the pure spoken line, so she learns the speech itself, not script markup.
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, "L:/LocalCoder/workspace/autonomy")
from generate_neuron_corpus import IDENTITY  # noqa: E402

DIALOGUE = Path(
    "L:/LocalCoder/workspace/reference/Movie-Script-Database/scripts/viv_dialogue_corpus.txt"
)
OUT = Path("L:/LocalCoder/models/viv_identity_dialogue.txt")
INTERLEAVE = 20  # one identity line every N dialogue lines


def strip_speaker(line: str) -> str | None:
    """'SANCHEZ=>Your Majesty...' -> 'Your Majesty...' (None if no dialogue)."""
    if "=>" not in line:
        return None
    spoken = line.split("=>", 1)[1].strip()
    return spoken or None


def main() -> int:
    rng = random.Random(20261120)
    raw = DIALOGUE.read_text(encoding="utf-8").splitlines()
    dialogue = [d for d in (strip_speaker(ln) for ln in raw) if d]

    lines = []
    for i, d in enumerate(dialogue):
        lines.append(d)
        if i % INTERLEAVE == 0:
            lines.append(rng.choice(IDENTITY))

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"dialogue lines: {len(dialogue)}")
    print(f"total lines: {len(lines)} (identity interleaved every {INTERLEAVE})")
    print(f"output: {OUT} ({OUT.stat().st_size / 1e6:.1f} MB)")
    print("=== sample ===")
    for ln in lines[:14]:
        print(" ", ln)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
