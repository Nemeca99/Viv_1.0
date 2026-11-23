"""Bounded read-only audit of the real domain cartridges."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

CORPUS = Path(r"F:\AI_Datasets\domain_dbs")
OUT = Path(r"L:\LocalCoder\workspace\autonomy\.tmp\live_containment_audit.json")
PROBE = "compiler"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inventory(path: Path) -> tuple[int, list[dict[str, str]]]:
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "articles" not in tables:
            return 0, []
        count = int(conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0])
        rows = conn.execute(
            "SELECT article_id,title FROM articles "
            "WHERE lower(title) LIKE ? OR lower(summary) LIKE ? LIMIT 5",
            (f"%{PROBE}%", f"%{PROBE}%"),
        ).fetchall()
    return count, [{"row_id": str(row_id), "title": title} for row_id, title in rows]


def main() -> None:
    cartridges = sorted(CORPUS.glob("wiki_*.sqlite3"))
    entries = []
    for path in cartridges:
        print(f"AUDIT {path.name}", flush=True)
        count, probes = inventory(path)
        entries.append({
            "path": str(path),
            "sha256": sha256(path),
            "article_count": count,
            "probe": {"term": PROBE, "rows": probes},
        })
    receipt = {
        "schema": "viv-live-containment-audit-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "corpus_path": str(CORPUS),
        "cartridge_count": len(entries),
        "probe": PROBE,
        "cartridges": entries,
        "limitations": [
            "Each query is evaluated independently against each cartridge.",
            "This is a bounded query audit, not an exhaustive claim over every possible query.",
            "Existing Viv Network and source SQLite files are not modified.",
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "receipt": str(OUT),
        "cartridge_count": len(entries),
        "total_articles": sum(entry["article_count"] for entry in entries),
        "sha256_recorded": True,
    }))


if __name__ == "__main__":
    main()
