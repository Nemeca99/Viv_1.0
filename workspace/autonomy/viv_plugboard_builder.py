"""
Viv Enigma Plugboard (Steckerbrett) Builder
==========================================
Architect: Travis (Nox Forge / AIOS V2)
Purpose:
  Extracts Wikipedia redirect/alias pairs from batches 0 through 200 into
  F:\AI_Datasets\domain_dbs\wiki_plugboard.sqlite3.
  Provides coordinate-swapping alias translation before the rotors spin.
"""

from __future__ import annotations

import os
import re
import sqlite3
import sys
import time
from pathlib import Path

DATA_DIR = Path(r"F:\AI_Datasets\wikipedia_deduplicated")
PLUGBOARD_DB = Path(r"F:\AI_Datasets\domain_dbs\wiki_plugboard.sqlite3")

# Core historical & scientific canonical aliases
CORE_CANONICAL_ALIASES = [
    ("Honest Abe", "Abraham Lincoln"),
    ("Abe Lincoln", "Abraham Lincoln"),
    ("Father of His Country", "George Washington"),
    ("First President of the United States", "George Washington"),
    ("First US President", "George Washington"),
    ("1st US President", "George Washington"),
    ("16th US President", "Abraham Lincoln"),
    ("16th President of the United States", "Abraham Lincoln"),
    ("NASA", "National Aeronautics and Space Administration"),
    ("c", "Speed of light"),
    ("Light speed", "Speed of light"),
    ("AI", "Artificial intelligence"),
    ("ML", "Machine learning"),
    ("NLP", "Natural language processing"),
    ("CPU", "Central processing unit"),
    ("GPU", "Graphics processing unit"),
    ("RAM", "Random-access memory"),
    ("WWI", "World War I"),
    ("WWII", "World War II"),
    ("FDR", "Franklin D. Roosevelt"),
    ("JFK", "John F. Kennedy"),
    ("USA", "United States"),
    ("US", "United States"),
    ("UK", "United Kingdom"),
    ("USSR", "Soviet Union"),
]


def init_db(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS plugboard (
        alias TEXT PRIMARY KEY,
        target TEXT,
        source TEXT
    );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_plugboard_alias ON plugboard(alias);")
    conn.commit()


def build_plugboard(start_batch: int = 0, end_batch: int = 200):
    t0 = time.perf_counter()
    print(f"[*] Building Enigma Plugboard across Batches {start_batch} through {end_batch}...")
    print(f"    Target: {PLUGBOARD_DB}")

    conn = sqlite3.connect(str(PLUGBOARD_DB))
    init_db(conn)
    cur = conn.cursor()

    # Seed core canonical aliases
    cur.executemany(
        "INSERT OR REPLACE INTO plugboard (alias, target, source) VALUES (?, ?, 'canonical')",
        CORE_CANONICAL_ALIASES,
    )
    conn.commit()
    print(f"[+] Seeded {len(CORE_CANONICAL_ALIASES)} core canonical aliases.")

    total_redirects = 0
    redirect_pattern = re.compile(r"#REDIRECT\s+\[\[(.*?)\]\]", re.IGNORECASE)

    for b in range(start_batch, end_batch + 1):
        batch_dir = DATA_DIR / f"batch_{b:04d}"
        if not batch_dir.exists():
            continue

        batch_pairs = []
        for entry in os.scandir(batch_dir):
            if entry.is_file() and entry.name.endswith(".txt") and entry.stat().st_size < 1024:
                try:
                    with open(entry.path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read(512)
                    m = redirect_pattern.search(content)
                    if m:
                        target = m.group(1).split("|")[0].split("#")[0].strip()
                        # Extract title from first line
                        first_line = content.split("\n", 1)[0]
                        if first_line.startswith("Title: "):
                            title = first_line[7:].strip()
                        else:
                            title = entry.name.split("_", 1)[-1][:-4].strip()

                        if title and target and title.lower() != target.lower():
                            batch_pairs.append((title, target, f"batch_{b:04d}"))
                except Exception:
                    pass

        if batch_pairs:
            cur.executemany(
                "INSERT OR REPLACE INTO plugboard (alias, target, source) VALUES (?, ?, ?)",
                batch_pairs,
            )
            conn.commit()
            total_redirects += len(batch_pairs)

        if b % 25 == 0 or b == end_batch:
            print(f"[*] Processed through Batch {b:04d} | Accumulated Redirects: {total_redirects:,}")

    conn.close()
    dur = time.perf_counter() - t0
    print(f"[+] Plugboard compilation complete in {dur:.2f}s!")
    print(f"    Total Active Alias Pairs: {total_redirects + len(CORE_CANONICAL_ALIASES):,}")


if __name__ == "__main__":
    build_plugboard(0, 200)
