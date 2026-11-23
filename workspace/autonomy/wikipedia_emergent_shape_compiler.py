"""Wikipedia source compiler.

Transforms raw Wikipedia encyclopedia articles into source-preserving lessons:

No sentence shape, category list, or semantic claim is embedded in code.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
import sqlite3
from typing import Any, Generator, Sequence

DATASET_ROOT = Path(r"F:\AI_Datasets\wikipedia_deduplicated")
AUTONOMY_DIR = Path(__file__).resolve().parent
DATA_DIR = AUTONOMY_DIR / "data"
OUTPUT_FILE = DATA_DIR / "wikipedia_emergent_shapes.jsonl"


def clean_wikitext(text: str) -> str:
    """Strip wiki markup, templates, refs, and links into clean prose."""
    # Remove ref tags
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<ref[^>]*/>", "", text, flags=re.IGNORECASE)
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Remove templates {{...}}
    text = re.sub(r"\{\{[^}]+\}\}", "", text)
    # Convert internal links [[Target|Anchor]] -> Anchor, and [[Target]] -> Target
    text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", text)
    # Remove parenthetical pronunciations and citations (...)
    text = re.sub(r"\([^)]*\)", "", text)
    # Remove bold/italics '''...''' and ''...''
    text = re.sub(r"'{2,}", "", text)
    # Collapse multiple spaces
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


ONTOLOGY_DB = DATA_DIR / "lexicon_ontology.db"


def _ontology_category(text: str, entity: str) -> str | None:
    """Choose a category only from verified ontology lemmas."""
    try:
        with sqlite3.connect(f"file:{ONTOLOGY_DB.resolve()}?mode=ro", uri=True, timeout=1.0) as con:
            known = {str(row[0]).casefold() for row in con.execute("SELECT lemma FROM lexical_entities")}
    except sqlite3.Error:
        return None
    tokens = re.findall(r"[A-Za-z][A-Za-z-]*", text.casefold())
    return next((token for token in reversed(tokens) if token != entity.casefold() and token in known), None)


class WikipediaShapeCompiler:
    def __init__(self, dataset_root: Path = DATASET_ROOT, output_file: Path = OUTPUT_FILE):
        self.dataset_root = dataset_root
        self.output_file = output_file
        self.output_file.parent.mkdir(parents=True, exist_ok=True)

    def scan_article(self, filepath: Path) -> dict[str, Any] | None:
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read(6000)
        except Exception:
            return None

        # Extract title
        title_m = re.search(r"^Title:\s*(.+)$", content, re.M)
        if not title_m:
            return None
        title = title_m.group(1).strip()

        # Reject lists, timelines, disambiguations, or complex multi-word titles
        # Restrict entity to clean single-word ASCII nouns
        words = title.split()
        if len(words) != 1 or not title.isascii() or not title.isalpha():
            return None
        if len(title) < 3 or len(title) > 14:
            return None

        # Extract short description
        desc_m = re.search(r"\{\{Short description\|([^}]+)\}\}", content, re.I)
        short_desc = desc_m.group(1).strip() if desc_m else ""

        # Extract lead sentence
        lead_sentence = ""
        body_start = content.find("\n\n")
        if body_start != -1:
            body_text = clean_wikitext(content[body_start:body_start + 1200])
            sentences = [s.strip() for s in body_text.split(".") if s.strip()]
            if sentences:
                lead_sentence = sentences[0]

        return {
            "title": title,
            "short_desc": short_desc,
            "lead_sentence": lead_sentence,
            "file": filepath.name,
        }

    def synthesize_shape_lesson(self, article_info: dict[str, Any]) -> dict[str, Any] | None:
        title = article_info["title"].strip()
        short_desc = article_info["short_desc"].strip()
        lead = article_info["lead_sentence"].strip()

        category: str | None = None

        # 1. Check Short Description head-noun
        if short_desc:
            category = _ontology_category(short_desc, title)

        # 2. Check Lead Sentence if short desc was inconclusive
        if not category and lead:
            category = _ontology_category(lead, title)

        if not category:
            return None

        entity = title.lower()
        if entity == category:
            return None

        # Format clean, developmental 4-5 word developmental sentence
        target_sentence = lead or short_desc
        if not target_sentence:
            return None

        return {
            "shape": "TAXONOMY_IS_A",
            "target_sentence": target_sentence,
            "focus_words": [entity, category],
            "entity": entity,
            "category": category,
            "source_title": title,
            "short_desc": short_desc,
            "provenance": f"{article_info['file']}",
        }

    def compile_batch(self, max_batches: int = 10, max_lessons: int = 50) -> list[dict[str, Any]]:
        lessons: list[dict[str, Any]] = []
        seen_entities: set[str] = set()

        print(f"[COMPILER] Scanning Wikipedia batches 0..{max_batches} on F: drive...")
        for b_idx in range(max_batches):
            b_dir = self.dataset_root / f"batch_{b_idx:04d}"
            if not b_dir.exists():
                continue
            for entry in os.scandir(b_dir):
                if not entry.name.endswith(".txt"):
                    continue
                art = self.scan_article(Path(entry.path))
                if not art:
                    continue
                lesson = self.synthesize_shape_lesson(art)
                if lesson and lesson["entity"] not in seen_entities:
                    seen_entities.add(lesson["entity"])
                    lessons.append(lesson)
                    if len(lessons) >= max_lessons:
                        break
            if len(lessons) >= max_lessons:
                break

        print(f"[COMPILER] Compiled {len(lessons)} clean topological shape lessons.")
        
        # Persist to JSONL
        with open(self.output_file, "w", encoding="utf-8") as f:
            for l in lessons:
                f.write(json.dumps(l) + "\n")
        print(f"[COMPILER] Saved emergent curriculum to: {self.output_file}")
        return lessons


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Wikipedia Emergent Shape Compiler")
    parser.add_argument("--batches", type=int, default=50, help="Number of batch directories to scan")
    parser.add_argument("--lessons", type=int, default=200, help="Target number of lessons to compile")
    args = parser.parse_args()

    compiler = WikipediaShapeCompiler()
    compiler.compile_batch(max_batches=args.batches, max_lessons=args.lessons)


if __name__ == "__main__":
    main()
