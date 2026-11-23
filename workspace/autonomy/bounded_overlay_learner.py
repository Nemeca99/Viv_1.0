"""Foreground, bounded learner loop over a candidate SQLite overlay."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from deterministic_containment import ContainmentEngine, PARTIAL, NULL, SQLiteOverlayCartridge
from live_learning_cycle import JOURNAL, OVERLAY, SOURCE, make_overlay, digest


CHECKPOINT = Path(r"L:\LocalCoder\workspace\autonomy\.tmp\bounded_overlay_checkpoint.json")


def reload_check() -> None:
    cartridge = SQLiteOverlayCartridge("overlay", OVERLAY, source_path=SOURCE)
    result = ContainmentEngine([cartridge]).query("quantum green")
    if result.state != "CONTAINED":
        raise SystemExit(f"reload checkpoint failed: {result.state}")
    print(json.dumps({"reload": "PASS", "state": result.state, "row_id": result.receipt["candidate"]["row_id"]}))


def main() -> None:
    if "--reload" in sys.argv:
        reload_check()
        return
    make_overlay()
    journal = Path(r"L:\LocalCoder\workspace\autonomy\.tmp\bounded_overlay_learner.jsonl")
    journal.unlink(missing_ok=True)
    cartridge = SQLiteOverlayCartridge("overlay", OVERLAY, source_path=SOURCE)
    engine = ContainmentEngine([cartridge])
    batch = (
        ("The sky is green", "has_candidate_label", "greenish"),
        ("quantum green", "has_learning_label", "greenish"),
        ("xylophone nebula nonexistent", "has_gap_label", "unknown"),
    )
    outcomes = []
    for index, (query, relation, obj) in enumerate(batch, start=1):
        result = engine.query(query)
        if result.state not in {PARTIAL, NULL}:
            raise RuntimeError(f"learner received {result.state} for {query}")
        fact = {"article_id": 820000000 + index, "title": f"{query.lower()} learned", "summary": "bounded learner admission", "subject": query.lower(), "relation": relation, "object": obj}
        decision = engine.learn_after(result, cartridge_id="overlay", fact=fact, journal_path=journal)
        outcomes.append({"query": query, "input_state": result.state, "decision": decision["decision"], "trace_credit": len(engine.trace_counters)})
    checkpoint = {"schema": "viv-bounded-overlay-checkpoint-v1", "source_sha256": digest(SOURCE), "overlay_sha256": digest(OVERLAY), "trace_counters": engine.trace_counters, "outcomes": outcomes}
    CHECKPOINT.write_text(json.dumps(checkpoint, indent=2) + "\n", encoding="utf-8")
    child = subprocess.run([sys.executable, __file__, "--reload"], capture_output=True, text=True, check=True)
    checkpoint["reload"] = json.loads(child.stdout)
    CHECKPOINT.write_text(json.dumps(checkpoint, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "steps": len(outcomes), "checkpoint": str(CHECKPOINT), "reload": checkpoint["reload"]}))


if __name__ == "__main__":
    main()
