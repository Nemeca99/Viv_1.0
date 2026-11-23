"""What turn length does each corpus actually teach? Read-only.

Phase 5 -> Phase 7 is largely a turn-length problem: a model trained only on
short chat turns cannot produce a long coherent turn, no matter how good the
gate is. Measure the distribution instead of asserting it.
"""
import statistics
from pathlib import Path

MODELS = Path("L:/LocalCoder/models")


def line_words(path: Path, limit_lines: int = 400_000) -> list[int]:
    out = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh):
            if i >= limit_lines:
                break
            s = line.strip()
            if not s:
                continue
            # speaker label counts as words in the model's view; count the utterance
            if ":" in s[:24]:
                s = s.split(":", 1)[1]
            out.append(len(s.split()))
    return out


def report(name: str, words: list[int]) -> None:
    if not words:
        print(f"{name:32} (empty)")
        return
    words_sorted = sorted(words)
    n = len(words_sorted)
    def pct(p: float) -> int:
        return words_sorted[min(n - 1, int(p * n))]
    print(f"{name:32} n={n:>7}  mean={statistics.mean(words):5.1f}  "
          f"median={pct(0.5):3}  p90={pct(0.9):3}  p99={pct(0.99):4}  "
          f"max={words_sorted[-1]:4}")


for label, rel in [
    ("turn pairs (answers)", "viv_turn_pairs.txt"),
    ("observation pairs", "viv_observation_pairs.txt"),
    ("movie/id dialogue", "viv_identity_dialogue.txt"),
    ("SODA social dialogue", "viv_identity_soda.txt"),
    ("scenes", "viv_scenes.txt"),
]:
    p = MODELS / rel
    if p.is_file():
        report(label, line_words(p))
    else:
        print(f"{label:32} MISSING")
