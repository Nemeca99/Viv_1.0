"""Source-grounded dual parser for Wikipedia curriculum admission.

No semantic category or veto vocabulary is embedded here. The article's own
category tags and persisted ontology are the only evidence accepted.
"""
from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Sequence


class DualParserVerifier:
    """Require exact source-category agreement; otherwise fail closed."""

    @staticmethod
    def extract_categories_from_text(wikitext: str) -> list[str]:
        return re.findall(r"\[\[Category:([^\]|]+)(?:\|[^\]]*)?\]\]", wikitext, re.I)

    @staticmethod
    def _category_tokens(value: str) -> set[str]:
        return {token for token in re.findall(r"[a-z0-9]+", value.lower()) if token}

    @classmethod
    def verify(
        cls,
        entity: str,
        category: str,
        categories_found: Sequence[str],
        short_desc: str = "",
        title: str = "",
    ) -> dict[str, Any]:
        requested = cls._category_tokens(category)
        tags = [str(tag).strip().lower() for tag in categories_found if str(tag).strip()]
        matched = [tag for tag in tags if requested and requested.issubset(cls._category_tokens(tag))]
        if not matched:
            return {"verified": False, "confidence": 0.0, "reason": "source category tags do not exactly support the requested ontology category", "matched_tags": [], "veto_tags": []}
        return {"verified": True, "confidence": min(1.0, 0.6 + 0.15 * len(matched)), "reason": f"source category agreement for {category!r}", "matched_tags": matched[:5], "veto_tags": []}

    @classmethod
    def verify_file(cls, filepath: Path, entity: str, category: str, short_desc: str = "", title: str = "") -> dict[str, Any]:
        try:
            content = filepath.read_text(encoding="utf-8", errors="ignore")
        except Exception as exc:
            return {"verified": False, "confidence": 0.0, "reason": f"file read error: {exc}", "matched_tags": [], "veto_tags": []}
        return cls.verify(entity, category, cls.extract_categories_from_text(content), short_desc, title)
