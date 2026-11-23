"""Read-only, bounded retrieval over the local Wikipedia article corpus."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

WIKIPEDIA_ROOT = Path(r"F:\AI_Datasets\wikipedia_deduplicated")
SHAPES_DB = Path(r"L:\LocalCoder\workspace\autonomy\data\wikipedia_emergent_shapes.db")


def select_reading_tier(entity: str, tier: int = 1) -> dict[str, str] | None:
    """Select a verified lesson, bounded article excerpt, or full source path."""
    with sqlite3.connect(f"file:{SHAPES_DB.resolve()}?mode=ro", uri=True, timeout=1.0) as con:
        row = con.execute(
            "SELECT target_sentence, short_desc, source_title, provenance_batch, provenance_file FROM emergent_shapes WHERE lower(entity)=? AND status IN ('VERIFIED','CERTIFIED') ORDER BY id LIMIT 1",
            (entity.lower(),),
        ).fetchone()
    if not row:
        return None
    sentence, short_desc, title, batch, source_file = row
    source = WIKIPEDIA_ROOT / f"batch_{int(batch):04d}" / str(source_file)
    if tier <= 1:
        return {"tier": "lesson", "title": title or entity, "text": sentence}
    if tier == 2:
        return {"tier": "excerpt", "title": title or entity, "text": source.read_text(encoding="utf-8", errors="replace")[:4000]}
    return {"tier": "full", "title": title or entity, "path": str(source)}


def retrieve_article_context(term: str, *, max_chars: int = 3000) -> dict[str, str] | None:
    """Return a bounded local article excerpt; never writes or creates facts."""
    needle = re.sub(r"[^a-z0-9 ]", "", term.lower()).strip()
    if not needle or not WIKIPEDIA_ROOT.is_dir():
        return None
    token = needle.replace(" ", "_")
    candidates = sorted(WIKIPEDIA_ROOT.glob(f"batch_*/*{token}*.txt"))
    if not candidates:
        candidates = sorted(WIKIPEDIA_ROOT.glob("batch_*/*.txt"))
        candidates = [p for p in candidates if needle in p.stem.lower()][:1]
    if not candidates:
        return None
    path = candidates[0]
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[:max_chars]
    except OSError:
        return None
    return {"title": path.stem, "path": str(path), "excerpt": text}
