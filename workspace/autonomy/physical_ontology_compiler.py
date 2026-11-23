"""Compatibility entry point for the source-driven ontology.

Physical relations are compiled from dictionary/Wikipedia evidence by
``lexicon_ontology_builder``. This module intentionally contains no embedded
fact table and never injects synthetic edges into the learning graph.
"""
from __future__ import annotations

from pathlib import Path
import sqlite3

WORKSPACE = Path(__file__).resolve().parent.parent
DB_PATH = WORKSPACE / "autonomy/data/lexicon_ontology.db"


def compile_physical_ontology(db_path: Path = DB_PATH) -> int:
    """Validate the persisted topology and report existing physical edges."""
    if not Path(db_path).exists():
        raise FileNotFoundError(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT count(*) FROM semantic_relations WHERE relation_type NOT IN ('IS_A','PART_OF','DERIVED_FROM')"
        ).fetchone()
    return int(row[0] if row else 0)


if __name__ == "__main__":
    print(f"Source-driven physical relation count: {compile_physical_ontology()}")
