"""Wikipedia Rebuild Engine for Viv.

Extracts, compiles, and crystallizes raw Wikipedia encyclopedia articles from
F:\\AI_Datasets\\wikipedia_deduplicated into a high-performance local SQLite database
on Viv's NVMe home: L:\\LocalCoder\\workspace\\autonomy\\data\\wikipedia_emergent_shapes.db.

Architecture:
1. Fast parallel multi-process extraction across batch directories.
2. Deduplication on single-word English entity nouns.
3. Ontological hypernym matching against 25 foundational categories.
4. Direct tracking of learning state: PENDING -> PROTOTYPE_BOUND -> CERTIFIED.
"""

from __future__ import annotations

import concurrent.futures
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
import functools
from typing import Any

WORKSPACE = Path(r"L:\LocalCoder\workspace")
DATASET_ROOT = Path(r"F:\AI_Datasets\wikipedia_deduplicated")
AUTONOMY_DATA = WORKSPACE / "autonomy/data"
DB_PATH = AUTONOMY_DATA / "wikipedia_emergent_shapes.db"

ONTOLOGY_DB = AUTONOMY_DATA / "lexicon_ontology.db"


@functools.lru_cache(maxsize=1)
def _ontology_lemmas() -> frozenset[str]:
    try:
        with sqlite3.connect(f"file:{ONTOLOGY_DB.resolve()}?mode=ro", uri=True, timeout=1.0) as con:
            return frozenset(str(row[0]).casefold() for row in con.execute("SELECT lemma FROM lexical_entities"))
    except sqlite3.Error:
        return frozenset()


def _ontology_category(text: str, entity: str) -> str | None:
    tokens = re.findall(r"[A-Za-z][A-Za-z-]*", text.casefold())
    return next((token for token in reversed(tokens) if token != entity.casefold() and token in _ontology_lemmas()), None)


def clean_wikitext(text: str) -> str:
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<ref[^>]*/>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\{\{[^}]+\}\}", "", text)
    text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"'{2,}", "", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def scan_single_file(filepath: str, batch_num: int) -> dict[str, Any] | None:
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read(5000)
    except Exception:
        return None

    title_m = re.search(r"^Title:\s*(.+)$", content, re.M)
    if not title_m:
        return None
    title = title_m.group(1).strip()

    words = title.split()
    if len(words) != 1 or not title.isascii() or not title.isalpha():
        return None
    if len(title) < 3 or len(title) > 14:
        return None

    desc_m = re.search(r"\{\{Short description\|([^}]+)\}\}", content, re.I)
    short_desc = desc_m.group(1).strip() if desc_m else ""

    category: str | None = None
    lead_sentence = ""
    if short_desc:
        category = _ontology_category(short_desc, title)

    if not category:
        body_start = content.find("\n\n")
        if body_start != -1:
            body_text = clean_wikitext(content[body_start:body_start + 1000])
            sentences = [s.strip() for s in body_text.split(".") if s.strip()]
            if sentences:
                lead_sentence = sentences[0]
                category = _ontology_category(sentences[0], title)

    if not category:
        return None

    entity = title.lower()
    if entity == category:
        return None

    art = "an" if entity[0] in "aeiou" else "a"
    target_sentence = lead_sentence or short_desc
    if not target_sentence:
        return None

    return {
        "shape_type": "TAXONOMY_IS_A",
        "entity": entity,
        "category": category,
        "det": art,
        "target_sentence": target_sentence,
        "focus_words_json": json.dumps([entity, category]),
        "short_desc": short_desc,
        "source_title": title,
        "provenance_batch": batch_num,
        "provenance_file": os.path.basename(filepath),
        "created_utc": datetime.now(timezone.utc).isoformat(),
    }


def scan_batch_worker(batch_num: int) -> list[dict[str, Any]]:
    b_dir = DATASET_ROOT / f"batch_{batch_num:04d}"
    if not b_dir.is_dir():
        return []
    results = []
    try:
        for entry in os.scandir(b_dir):
            if entry.name.endswith(".txt"):
                item = scan_single_file(entry.path, batch_num)
                if item:
                    results.append(item)
    except Exception:
        pass
    return results


class WikipediaRebuildEngine:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS emergent_shapes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    shape_type TEXT NOT NULL,
                    entity TEXT UNIQUE NOT NULL,
                    category TEXT NOT NULL,
                    det TEXT NOT NULL,
                    target_sentence TEXT NOT NULL,
                    focus_words_json TEXT NOT NULL,
                    short_desc TEXT,
                    source_title TEXT,
                    provenance_batch INTEGER,
                    provenance_file TEXT,
                    status TEXT DEFAULT 'PENDING',
                    certified_snapshot TEXT,
                    created_utc TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_category ON emergent_shapes(category)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON emergent_shapes(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_entity ON emergent_shapes(entity)")
            conn.commit()

    def get_existing_entities(self) -> set[str]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT entity FROM emergent_shapes").fetchall()
            return {r[0] for r in rows}

    def compile_range(self, start_batch: int = 0, end_batch: int = 100, max_workers: int = 8) -> int:
        existing = self.get_existing_entities()
        print(f"[REBUILD] Compiling batches {start_batch}..{end_batch} using {max_workers} workers...")
        print(f"[REBUILD] Database: {self.db_path} (Existing entries: {len(existing)})")

        batches = list(range(start_batch, end_batch))
        t0 = time.monotonic()
        total_extracted = 0
        new_items: list[dict[str, Any]] = []

        with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
            future_to_batch = {executor.submit(scan_batch_worker, b): b for b in batches}
            for future in concurrent.futures.as_completed(future_to_batch):
                b_num = future_to_batch[future]
                try:
                    batch_res = future.result()
                    for item in batch_res:
                        ent = item["entity"]
                        if ent not in existing:
                            existing.add(ent)
                            new_items.append(item)
                except Exception as exc:
                    print(f"[ERROR] Batch {b_num} failed: {exc}")

        # Bulk insert into SQLite
        if new_items:
            with sqlite3.connect(self.db_path) as conn:
                conn.executemany("""
                    INSERT OR IGNORE INTO emergent_shapes (
                        shape_type, entity, category, det, target_sentence,
                        focus_words_json, short_desc, source_title,
                        provenance_batch, provenance_file, status, created_utc
                    ) VALUES (
                        :shape_type, :entity, :category, :det, :target_sentence,
                        :focus_words_json, :short_desc, :source_title,
                        :provenance_batch, :provenance_file, 'PENDING', :created_utc
                    )
                """, new_items)
                conn.commit()

        elapsed = time.monotonic() - t0
        print(f"[REBUILD] Extracted {len(new_items)} new emergent shapes in {elapsed:.2f}s ({len(new_items)/max(0.1, elapsed):.1f} shapes/sec).")
        return len(new_items)

    def stats(self) -> dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT count(*) FROM emergent_shapes").fetchone()[0]
            cat_counts = conn.execute("SELECT category, count(*) FROM emergent_shapes GROUP BY category ORDER BY count(*) DESC").fetchall()
            status_counts = conn.execute("SELECT status, count(*) FROM emergent_shapes GROUP BY status").fetchall()
            return {
                "total": total,
                "categories": dict(cat_counts),
                "status": dict(status_counts),
            }


if __name__ == "__main__":
    engine = WikipediaRebuildEngine()
    # Test on first 100 batches
    engine.compile_range(0, 100, max_workers=8)
    print("\n--- DATABASE VITALS ---")
    print(json.dumps(engine.stats(), indent=2))
