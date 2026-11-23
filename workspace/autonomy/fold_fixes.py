"""Fold the Architect's fixes into a training corpus.

Each fix in viv_fixes.jsonl is (prompt, response, fix). The fix is what she
should have said. Fold prompt + fix into plain text so the next sleep teaches
her to produce the fixed answer instead of the mistake. This is the
learn-from-that step of the feedback loop.
"""
import json
from pathlib import Path

FIXES = Path("L:/LocalCoder/models/viv_fixes.jsonl")
OUT = Path("L:/LocalCoder/models/viv_fixes_corpus.txt")


def main() -> int:
    lines = []
    if FIXES.is_file():
        for ln in FIXES.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            try:
                j = json.loads(ln)
            except json.JSONDecodeError:
                continue
            p = j.get("prompt", "").strip()
            f = j.get("fix", "").strip()
            if p:
                lines.append(p)
            if f:
                lines.append(f)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"folded {len(lines) // 2} fixes -> {OUT}")
    for ln in lines[:12]:
        print(" ", ln)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
