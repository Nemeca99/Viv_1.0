"""
Viv Wikipedia Domain Sieve (Multi-Cartridge Ontological Sorter)
==============================================================
Architect: Travis (Nox Forge / AIOS V2)
Purpose:
  Streams through the 80 GB / 2-million-article Wikipedia dataset on Drive F:,
  classifies each article into its primary domain using category tags and keywords,
  cleans wikimarkup into pure ground-truth summaries, and stores them in
  dedicated domain SQLite databases for subsequent .vtm cartridge compilation.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

WIKI_DIR = Path(r"F:\AI_Datasets\wikipedia_deduplicated")
OUTPUT_DB_DIR = Path(r"F:\AI_Datasets\domain_dbs")
OUTPUT_DB_DIR.mkdir(parents=True, exist_ok=True)

# Regex Patterns for Parsing
RE_TITLE = re.compile(r"^Title:\s*(.*)", re.MULTILINE)
RE_REDIRECT = re.compile(r"#REDIRECT", re.IGNORECASE)
RE_CATEGORY = re.compile(r"\[\[Category:([^\]|]+)", re.MULTILINE)

# Wikimarkup Cleaning Regexes
RE_TEMPLATES = re.compile(r"\{\{[^}]*\}\}")
RE_FILE_LINKS = re.compile(r"\[\[(?:File|Image):[^\]]*\]\]", re.IGNORECASE)
RE_WIKI_LINKS = re.compile(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]")
RE_FORMATTING = re.compile(r"'''+|''+")

# Domain Ontological Signatures
DOMAINS = {
    "PHYSICS": [
        "physics", "quantum", "relativity", "astronomy", "astrophysics", "mechanics",
        "optics", "thermodynamics", "cosmology", "electromagnetism", "particle",
        "gravity", "gravitation", "atomic", "nuclear", "photon", "radiation",
        "telescope", "galaxy", "star", "planet", "orbit", "spectroscopy",
    ],
    "COMP_SCI": [
        "computer", "software", "programming", "algorithm", "cryptography", "data structure",
        "operating system", "network", "database", "compiler", "internet", "web",
        "artificial intelligence", "machine learning", "cybersecurity", "protocol",
        "hardware", "microprocessor", "linux", "unix", "programming language",
    ],
    "BIOLOGY": [
        "biology", "medicine", "disease", "genetics", "anatomy", "zoology", "botany",
        "protein", "cell", "organism", "physiology", "pathology", "pharmacology",
        "virus", "bacteria", "dna", "rna", "species", "mammal", "bird", "insect",
        "plant", "medical", "surgery", "health", "biochemistry", "ecology",
    ],
    "MATHEMATICS": [
        "mathematics", "algebra", "calculus", "geometry", "topology", "number theory",
        "differential", "integral", "equation", "theorem", "probability", "statistic",
        "linear algebra", "vector space", "combinatorics", "arithmetic", "matrix",
    ],
    "ENGINEERING": [
        "engineering", "robotics", "electronics", "aerospace", "mechanical", "civil engineering",
        "electrical", "materials science", "propulsion", "turbine", "automotive",
        "manufacturing", "semiconductor", "telecommunication", "circuit", "engine",
    ],
    "HISTORY": [
        "history", "century", "war", "battle", "empire", "dynasty", "ancient", "medieval",
        "archaeology", "treaty", "revolution", "rebellion", "monarchy", "president",
        "historical", "colonial", "military history", "conflict",
    ],
    "PHILOSOPHY": [
        "philosophy", "logic", "ethics", "epistemology", "metaphysics", "political",
        "anarchism", "socialism", "capitalism", "ideology", "democracy", "justice",
        "jurisprudence", "law", "constitution", "governance", "legal",
    ],
    "GEOGRAPHY": [
        "geography", "geology", "country", "city", "mountain", "river", "lake",
        "ocean", "island", "climate", "volcano", "plate tectonics", "mineral",
        "earthquake", "town", "province", "continent", "valley", "desert",
    ],
}


def clean_summary_text(raw_text: str) -> str:
    """Extracts first 2-3 clean summary paragraphs from wikimarkup."""
    # Strip templates & media
    text = RE_TEMPLATES.sub("", raw_text)
    text = RE_FILE_LINKS.sub("", text)
    text = RE_WIKI_LINKS.sub(r"\1", text)
    text = RE_FORMATTING.sub("", text)

    clean_lines = []
    for line in text.splitlines():
        line_s = line.strip()
        if len(line_s) < 30:
            continue
        # Skip section headers, wiki templates, or list bullets
        if line_s.startswith(("Title:", "==", "{{", "|", "*", "#", "!", "<!--")):
            continue
        clean_lines.append(line_s)
        if len(clean_lines) >= 3:
            break

    return " ".join(clean_lines)


def classify_domain(title: str, categories: List[str], text_sample: str) -> str:
    """Scores domain affinities and returns the best matching domain or 'GENERAL'."""
    haystack = (title + " " + " ".join(categories) + " " + text_sample).lower()
    
    scores = Counter()
    for domain_name, keywords in DOMAINS.items():
        score = sum(haystack.count(kw) for kw in keywords)
        if score > 0:
            scores[domain_name] = score

    if not scores:
        return "GENERAL"

    best_domain, top_score = scores.most_common(1)[0]
    return best_domain if top_score >= 2 else "GENERAL"


class WikipediaDomainSieve:
    def __init__(self, output_dir: Path | str = OUTPUT_DB_DIR):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.connections: Dict[str, sqlite3.Connection] = {}
        self.buffers: Dict[str, List[Tuple]] = {}
        self._init_databases()

    def _init_databases(self):
        all_domains = list(DOMAINS.keys()) + ["GENERAL"]
        for d in all_domains:
            db_path = self.output_dir / f"wiki_{d.lower()}.sqlite3"
            conn = sqlite3.connect(db_path, timeout=60)
            conn.execute("PRAGMA synchronous = OFF")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA temp_store = MEMORY")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS articles (
                    article_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    categories TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    char_count INTEGER NOT NULL,
                    batch_source TEXT NOT NULL,
                    file_name TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_title ON articles(title)")
            self.connections[d] = conn
            self.buffers[d] = []

    def flush_buffer(self, domain: str):
        buf = self.buffers.get(domain, [])
        if not buf:
            return
        conn = self.connections[domain]
        conn.executemany("""
            INSERT INTO articles (title, domain, categories, summary, char_count, batch_source, file_name)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, buf)
        conn.commit()
        self.buffers[domain] = []

    def flush_all(self):
        for d in self.connections.keys():
            self.flush_buffer(d)

    def close(self):
        self.flush_all()
        for conn in self.connections.values():
            conn.close()

    def process_batch(self, batch_idx: int) -> Dict[str, int]:
        batch_dir = WIKI_DIR / f"batch_{batch_idx:04d}"
        if not batch_dir.is_dir():
            print(f"[-] Batch directory not found: {batch_dir}")
            return {}

        counts = Counter()
        redirects = 0
        total_files = 0

        for entry in os.scandir(batch_dir):
            if not entry.name.endswith(".txt"):
                continue
            total_files += 1

            try:
                with open(entry.path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()

                # Fast redirect filter
                if RE_REDIRECT.search(content[:300]):
                    redirects += 1
                    continue

                # Extract title
                title_m = RE_TITLE.search(content[:300])
                title = title_m.group(1).strip() if title_m else entry.name[:-4]

                # Extract categories
                cats = RE_CATEGORY.findall(content)
                
                # Extract clean summary
                summary = clean_summary_text(content[:8192])
                if len(summary) < 40:
                    continue  # Skip stubs with no usable text

                # Classify
                domain = classify_domain(title, cats, summary)

                row = (
                    title,
                    domain,
                    json.dumps(cats[:10], ensure_ascii=False),
                    summary,
                    len(content),
                    batch_dir.name,
                    entry.name,
                )

                self.buffers[domain].append(row)
                counts[domain] += 1

                if len(self.buffers[domain]) >= 500:
                    self.flush_buffer(domain)

            except Exception:
                continue

        self.flush_all()
        counts["_TOTAL_FILES"] = total_files
        counts["_REDIRECTS"] = redirects
        return counts


def run_sieve(start_batch: int = 0, end_batch: int = 5):
    print("=" * 70)
    print(" Viv Sovereign Wikipedia Multi-Domain Sieve")
    print(f" Source: {WIKI_DIR}")
    print(f" Target: {OUTPUT_DB_DIR}")
    print(f" Batches: {start_batch} through {end_batch} (Inclusive)")
    print("=" * 70)

    sieve = WikipediaDomainSieve()
    t_start = time.perf_counter()
    total_stats = Counter()

    try:
        for b in range(start_batch, end_batch + 1):
            t0 = time.perf_counter()
            batch_counts = sieve.process_batch(b)
            t1 = time.perf_counter()

            for k, v in batch_counts.items():
                total_stats[k] += v

            content_cnt = sum(v for k, v in batch_counts.items() if not k.startswith("_"))
            dur = t1 - t0
            rate = content_cnt / max(dur, 0.001)

            print(f"[*] Batch {b:04d} Complete: {content_cnt:,} content articles ({batch_counts.get('_REDIRECTS', 0):,} redirects) in {dur:.2f}s ({rate:.0f} articles/s)")

    finally:
        sieve.close()

    total_dur = time.perf_counter() - t_start
    total_content = sum(v for k, v in total_stats.items() if not k.startswith("_"))

    print("\n" + "=" * 70)
    print(f"[+] Sieve Completed in {total_dur:.2f}s! Total Articles Processed: {total_stats['_TOTAL_FILES']:,}")
    print(f"    Redirects Skipped: {total_stats['_REDIRECTS']:,}")
    print(f"    Content Articles Classified: {total_content:,}")
    print("\n--- Domain Distribution ---")
    for d, cnt in total_stats.most_common():
        if not d.startswith("_"):
            pct = (cnt / max(total_content, 1)) * 100
            print(f"  {d:<18}: {cnt:>6,} articles ({pct:5.1f}%) -> wiki_{d.lower()}.sqlite3")
    print("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int, default=5)
    args = parser.parse_args()

    run_sieve(start_batch=args.start, end_batch=args.end)
