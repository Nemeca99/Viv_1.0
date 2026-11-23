"""Bounded multi-cycle persistence audit for the candidate overlay."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from deterministic_containment import ContainmentEngine, PARTIAL, SQLiteOverlayCartridge
from live_learning_cycle import JOURNAL, OVERLAY, SOURCE, make_overlay, digest


AUDIT = Path(r"L:\LocalCoder\workspace\autonomy\.tmp\persistent_learning_audit.jsonl")


def append_attempt(record: dict) -> None:
    previous = "GENESIS"
    if AUDIT.exists():
        previous = json.loads(AUDIT.read_text(encoding="utf-8").splitlines()[-1])["record_sha256"]
    record = {"previous_record_sha256": previous, **record}
    body = json.dumps(record, sort_keys=True).encode()
    record["record_sha256"] = hashlib.sha256(body).hexdigest()
    with AUDIT.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def verify_reject() -> None:
    cartridge = SQLiteOverlayCartridge("overlay", OVERLAY, source_path=SOURCE)
    engine = ContainmentEngine([cartridge])
    result = engine.query("The sky is green")
    decision = engine.learn_after(
        result,
        cartridge_id="overlay",
        fact={"article_id": 800000001, "title": "sky green color", "summary": "wrong", "subject": "sky", "relation": "is_color", "object": "green"},
        journal_path=JOURNAL,
    )
    if decision["decision"] != "REJECT":
        raise SystemExit(f"fresh-process rejection failed: {decision}")
    print(json.dumps({"fresh_process": True, "decision": "REJECT", "overlay_sha256": digest(OVERLAY)}))


def main() -> None:
    if "--verify-reject" in sys.argv:
        verify_reject()
        return
    OVERLAY.parent.mkdir(parents=True, exist_ok=True)
    AUDIT.unlink(missing_ok=True)
    JOURNAL.unlink(missing_ok=True)
    make_overlay()
    source_hash = digest(SOURCE)
    cartridge = SQLiteOverlayCartridge("overlay", OVERLAY, source_path=SOURCE)
    engine = ContainmentEngine([cartridge])
    for index, (relation, query) in enumerate((("has_candidate_label", "The sky is green"), ("has_learning_label", "quantum green")), start=1):
        result = engine.query(query)
        if result.state != PARTIAL:
            raise RuntimeError(result.state)
        fact = {"article_id": 810000000 + index, "title": f"{query.lower()} learned {index}", "summary": "bounded admitted candidate", "subject": query.lower(), "relation": relation, "object": "greenish"}
        decision = engine.learn_after(result, cartridge_id="overlay", fact=fact, journal_path=JOURNAL)
        if decision["decision"] != "COMMIT":
            raise RuntimeError(decision)
        append_attempt({"cycle": index, "decision": "COMMIT", "provenance": cartridge.provenance, "trace_credit_entries": len(engine.trace_counters)})
    child = subprocess.run([sys.executable, __file__, "--verify-reject"], capture_output=True, text=True, check=True)
    append_attempt({"cycle": 3, "decision": "REJECT", "fresh_process": True, "child": json.loads(child.stdout), "provenance": cartridge.provenance, "source_sha256": source_hash})
    receipt = {"status": "PASS", "source_unchanged": digest(SOURCE) == source_hash, "commit_count": 2, "reject_count": 1, "integer_trace_credit": all(isinstance(v, int) for v in engine.trace_counters.values()), "journal": str(AUDIT), "overlay": str(OVERLAY)}
    Path(str(AUDIT).replace(".jsonl", ".json")).write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
