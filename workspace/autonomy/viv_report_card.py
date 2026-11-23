"""Viv report card: grades derived only from code_learning_receipts.jsonl.

Per subject (python, rust):
  Mastery      - fraction of assignments eventually passed
  Accuracy     - fraction of all attempts that passed
  First-try    - fraction of assignments passed on attempt 1 (in a task's first run)
  Improvement  - pass rate of the latest half of attempts minus the earlier half
  Persistence  - assignments that were failed at first but later passed
Syntax/compile failures are counted separately from logic failures.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

RECEIPTS = Path(__file__).resolve().parent / "learning" / "code_learning_receipts.jsonl"
OUT = Path(__file__).resolve().parent / "learning" / "viv_report_card.md"


def letter(pct: float) -> str:
    for cut, g in [(97, "A+"), (93, "A"), (90, "A-"), (87, "B+"), (83, "B"), (80, "B-"),
                   (77, "C+"), (73, "C"), (70, "C-"), (60, "D")]:
        if pct >= cut:
            return g
    return "F"


def load() -> list[dict]:
    rows = []
    if RECEIPTS.exists():
        for line in RECEIPTS.read_text(encoding="utf-8").splitlines():
            try:
                j = json.loads(line)
            except ValueError:
                continue
            if j.get("stage") == "GATE_REJECTED" and "no fenced code block" in j.get("error", ""):
                continue  # harness formatting bug, not the student's mistake
            if j.get("stage") in ("ACCEPTED", "GATE_REJECTED"):
                rows.append(j)
    return rows


def infer_lang(row: dict) -> str:
    return row.get("lang") or ("rust" if row["task"].startswith("rs_") else "python")


def kind(err: str) -> str:
    e = err.lower()
    if "syntaxerror" in e or "error[e" in e or "error:" in e or "no fenced" in e or "invalid syntax" in e:
        return "syntax/compile"
    return "logic/runtime"


def grade() -> str:
    rows = load()
    subjects = defaultdict(lambda: defaultdict(list))
    for r in rows:
        subjects[infer_lang(r)][r["task"]].append(r)
    lines = ["# Viv Report Card", "", f"Attempts on record: {len(rows)}", ""]
    gpas = []
    for subj in sorted(subjects):
        tasks = subjects[subj]
        atts = [a for t in tasks.values() for a in t]
        passed_tasks = [t for t, a in tasks.items() if any(x["stage"] == "ACCEPTED" for x in a)]
        mastery = 100 * len(passed_tasks) / len(tasks)
        accuracy = 100 * sum(x["stage"] == "ACCEPTED" for x in atts) / len(atts)
        first = 100 * sum(1 for a in tasks.values() if a[0]["stage"] == "ACCEPTED") / len(tasks)
        half = len(atts) // 2
        if half:
            early = 100 * sum(x["stage"] == "ACCEPTED" for x in atts[:half]) / half
            late = 100 * sum(x["stage"] == "ACCEPTED" for x in atts[half:]) / (len(atts) - half)
        else:
            early = late = accuracy
        improvement = late - early
        recovered = [t for t, a in tasks.items() if a[0]["stage"] != "ACCEPTED" and t in passed_tasks]
        fails = [x for x in atts if x["stage"] == "GATE_REJECTED"]
        syn = sum(kind(x["error"]) == "syntax/compile" for x in fails)
        # Weighted: mastery 50, accuracy 20, first-try 15, improvement 15 (capped 0..100 around 50 baseline)
        imp_score = max(0.0, min(100.0, 50 + improvement))
        final = 0.5 * mastery + 0.2 * accuracy + 0.15 * first + 0.15 * imp_score
        gpas.append(final)
        lines += [f"## {subj.title()}  —  **{letter(final)}** ({final:.0f}%)", "",
                  "| Criterion | Score | Grade |", "|---|---|---|",
                  f"| Mastery (assignments eventually passed) | {len(passed_tasks)}/{len(tasks)} | {letter(mastery)} |",
                  f"| Accuracy (attempts that passed) | {accuracy:.0f}% | {letter(accuracy)} |",
                  f"| First-try | {first:.0f}% | {letter(first)} |",
                  f"| Improvement (late vs early attempts) | {improvement:+.0f} pts | {letter(imp_score)} |",
                  f"| Persistence (failed first, then passed) | {len(recovered)} | - |", "",
                  f"Failures: {syn} syntax/compile, {len(fails) - syn} logic/runtime.", ""]
        for t, a in tasks.items():
            ok = [i + 1 for i, x in enumerate(a) if x["stage"] == "ACCEPTED"]
            lines.append(f"- `{t}`: {len(a)} attempts, " + (f"passed on #{ok[0]}" if ok else "not yet passed"))
        lines.append("")
    if gpas:
        overall = sum(gpas) / len(gpas)
        lines += [f"## Overall: **{letter(overall)}** ({overall:.0f}%)", "",
                  "Not yet graded: understanding (explaining failures and predicting output) and conversation."]
    else:
        lines.append("No graded attempts yet.")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    text = grade()
    OUT.write_text(text, encoding="utf-8")
    print(text)
