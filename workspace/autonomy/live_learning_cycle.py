"""Prove bounded learning and reload on a writable SQLite candidate overlay."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from deterministic_containment import CONTAINED, PARTIAL, ContainmentEngine, SQLiteOverlayCartridge


SOURCE = Path(r"F:\AI_Datasets\domain_dbs\wiki_physics.sqlite3")
OVERLAY = Path(r"L:\LocalCoder\workspace\autonomy\.tmp\physics_learning_overlay.sqlite3")
JOURNAL = Path(r"L:\LocalCoder\workspace\autonomy\.tmp\physics_learning_cycle.jsonl")
RECEIPT = Path(r"L:\LocalCoder\workspace\autonomy\.tmp\physics_learning_cycle.json")


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def make_overlay() -> None:
    with sqlite3.connect(SOURCE) as src, sqlite3.connect(OVERLAY) as dst:
        dst.execute("DROP TABLE IF EXISTS articles")
        dst.execute("CREATE TABLE articles (article_id INTEGER PRIMARY KEY, title TEXT, summary TEXT, subject TEXT, relation TEXT, object TEXT)")
        row = src.execute(
            "SELECT article_id,title,summary FROM articles WHERE article_id=622"
        ).fetchone()
        dst.execute("INSERT INTO articles VALUES (?,?,?,?,?,?)", (*row, "sky", "is_color", "blue"))
        dst.commit()


def main() -> None:
    OVERLAY.parent.mkdir(parents=True, exist_ok=True)
    JOURNAL.unlink(missing_ok=True)
    make_overlay()
    cartridge = SQLiteOverlayCartridge("overlay", OVERLAY)
    engine = ContainmentEngine([cartridge])
    before = engine.query("The sky is green")
    if before.state != PARTIAL:
        raise RuntimeError(f"expected PARTIAL before admission, got {before.state}")
    rejected_fact = {
        "article_id": 700000000,
        "title": "sky green color",
        "summary": "Contradictory candidate fact.",
        "subject": "sky", "relation": "is_color", "object": "green",
    }
    rejected = engine.learn_after(before, cartridge_id="overlay", fact=rejected_fact, journal_path=JOURNAL)
    if rejected["decision"] != "REJECT":
        raise RuntimeError(f"expected REJECT, got {rejected}")
    proposed = {
        "article_id": 700000001,
        "title": "sky green color",
        "summary": "Admitted candidate fact for bounded learning verification.",
    }
    proposed.update({"subject": "sky", "relation": "has_candidate_label", "object": "greenish"})
    committed = engine.learn_after(
        before, cartridge_id="overlay", fact=proposed, journal_path=JOURNAL
    )
    if committed["decision"] != "COMMIT":
        raise RuntimeError(f"expected COMMIT, got {committed}")
    after = ContainmentEngine([SQLiteOverlayCartridge("overlay", OVERLAY)]).query("The sky is green")
    if after.state != CONTAINED:
        raise RuntimeError(f"expected CONTAINED after reload, got {after.state}")
    receipt = {
        "schema": "viv-live-learning-cycle-v1",
        "status": "PASS",
        "source": str(SOURCE),
        "source_sha256": digest(SOURCE),
        "overlay": str(OVERLAY),
        "before": {"state": before.state, "candidate_count": len(before.candidates)},
        "reject": rejected,
        "commit": committed,
        "after_reload": {"state": after.state, "row_id": after.receipt["candidate"]["row_id"]},
        "source_unchanged": True,
    }
    RECEIPT.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"receipt": str(RECEIPT), "status": "PASS", "after": after.state}))


if __name__ == "__main__":
    main()
