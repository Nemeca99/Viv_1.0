"""Prove the held-out probe set is not in any corpus the model trained on.

Exact-line match plus normalised substring match against the training corpora and
the in-set probe questions. Read-only.
"""
import re
from pathlib import Path

MODELS = Path("L:/LocalCoder/models")
HELDOUT = MODELS / "viv_probe_heldout.txt"
CORPORA = [
    MODELS / "viv_turn_pairs.txt",
    MODELS / "viv_observation_pairs.txt",
    MODELS / "viv_full_training.txt",
    MODELS / "viv_identity_dialogue.txt",
    MODELS / "viv_scenes.txt",
    MODELS / "viv_probe_questions.txt",
    MODELS / "viv_safety_training2.txt",
]


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


questions = [q for q in HELDOUT.read_text(encoding="utf-8").splitlines() if q.strip()]
texts = {}
for p in CORPORA:
    if p.is_file():
        texts[p.name] = norm(p.read_text(encoding="utf-8", errors="replace"))

print(f"held-out questions: {len(questions)}")
leaks = 0
for q in questions:
    n = norm(q)
    hits = [name for name, blob in texts.items() if n in blob]
    if hits:
        leaks += 1
        print(f"  LEAK  {q!r} in {hits}")
print(f"leaks: {leaks}/{len(questions)}")
raise SystemExit(1 if leaks else 0)
