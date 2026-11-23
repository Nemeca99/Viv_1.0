"""Dynamic Categorization Engine for Viv (AIOS V2).

As Viv learns new words, this engine dynamically categorizes them into active
semantic and syntactic banks (agents, botanical, objects, motion verbs, sensory adjectives, places).
Future sentence synthesis pulls directly from these expanding dynamic pools,
eliminating static scaffolding and enabling organic, self-enriching language generation.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import random
import re
import tempfile
import threading
from typing import Any


CATEGORY_FILE_PATH = Path(r"L:\LocalCoder\workspace\autonomy\learning\dynamic_categories.json")

"""Category names are schema labels; category members must come from the DB."""
CATEGORY_NAMES = ("agents", "objects", "botanical", "motion_verbs", "sensory_adjectives", "perception_verbs", "places")


class DynamicCategoryBank:
    """Thread-safe dynamic category manager that updates in real-time as Viv masters words."""

    def __init__(self, storage_path: Path | None = None, privacy_core=None):
        self.path = storage_path or CATEGORY_FILE_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._thread_lock = threading.RLock()
        if privacy_core is None:
            from aios_rebuild.privacy_core.privacy_core import PrivacyCore
            privacy_core = PrivacyCore()
        self.privacy_core = privacy_core
        self.categories: dict[str, set[str]] = {key: set() for key in CATEGORY_NAMES}
        self._load()

    def _load(self) -> None:
        """Load previously persisted category membership, seeding from canonical dynamic_categories.json if new."""
        source_path = self.path if self.path.exists() else (CATEGORY_FILE_PATH if CATEGORY_FILE_PATH.exists() else None)
        if source_path is not None and source_path.exists():
            try:
                data = json.loads(source_path.read_text(encoding="utf-8"))
                for cat, words in data.items():
                    if cat not in self.categories:
                        self.categories[cat] = set()
                    self.categories[cat].update(words)
            except Exception as e:
                print(f"[CATEGORY BANK WARNING] Error loading {source_path}: {e}")

    def save(self) -> None:
        """Merge under a process lock, then replace from a unique same-directory file."""
        from viv_autonomy import file_lock

        decision = self.privacy_core.authorize_file_write(str(self.path))
        if decision.get("allowed") is not True:
            raise PermissionError(decision.get("reason", "category_write_denied"))
        with self._thread_lock, file_lock(self.path.with_suffix(".lock"), wait=10):
            merged = {key: set(words) for key, words in self.categories.items()}
            if self.path.exists():
                disk = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(disk, dict) or any(not isinstance(v, list) for v in disk.values()):
                    raise ValueError("dynamic category bank schema invalid")
                for key, words in disk.items():
                    merged.setdefault(key, set()).update(words)
            serialized = {key: sorted(words) for key, words in merged.items()}
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".tmp",
                                                 prefix=self.path.stem + ".", dir=self.path.parent,
                                                 delete=False) as stream:
                    temporary = Path(stream.name)
                    json.dump(serialized, stream, indent=2)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
                self.categories = merged
            finally:
                if temporary is not None and temporary.exists():
                    temporary.unlink()

    def categorize_word(self, word: str, domain_hint: str | None = None,
                        save_after: bool = True) -> list[str]:
        with self._thread_lock:
            return self._categorize_word_locked(word, domain_hint, save_after)

    def _categorize_word_locked(
        self,
        word: str,
        domain_hint: str | None = None,
        save_after: bool = True,
    ) -> list[str]:
        """Classify a newly learned word and add to corresponding dynamic category banks."""
        w = word.lower().strip()
        assigned: list[str] = []

        def assign(category: str) -> None:
            self.categories[category].add(w)
            if category not in assigned:
                assigned.append(category)

        # 1. Domain Hint Mapping (Highest Precision from Multi-Daemon Concept Partitions)
        if domain_hint == "sensory_thermal":
            assign("sensory_adjectives")
        elif domain_hint == "kinematic_motion":
            assign("motion_verbs")
        elif domain_hint == "botanical_living":
            assign("botanical")
        elif domain_hint == "structural_material":
            assign("objects")

        # A daemon partition is the primary semantic assertion for this word.
        # Do not let broad historical dictionary senses leak it into unrelated
        # runtime pools (for example, botanical "bloom" into motion verbs).
        if domain_hint:
            if save_after and assigned:
                self.save()
            return assigned

        # Resolve classification from the ontology row, never from a baked word list.
        ontology = Path(__file__).resolve().parent / "data" / "lexicon_ontology.db"
        try:
            import sqlite3
            with sqlite3.connect(f"file:{ontology.resolve()}?mode=ro", uri=True, timeout=1.0) as con:
                row = con.execute(
                    "SELECT part_of_speech, domain FROM lexical_entities WHERE lower(lemma)=? ORDER BY entity_id LIMIT 1",
                    (w,),
                ).fetchone()
            pos, domain = row or (None, None)
            category = {
                "botany": "botanical",
                "mechanics": "objects",
                "zoology": "agents",
                "geography": "places",
                "physics": "sensory_adjectives",
            }.get(str(domain).casefold())
            if not category:
                category = {"verb": "motion_verbs", "adj": "sensory_adjectives"}.get(str(pos).casefold())
            if category:
                assign(category)
        except Exception:
            pass

        if save_after and assigned:
            self.save()

        return assigned

    def get_pool(
        self,
        category: str,
        limit: int | None = None,
        seed: int | None = None,
    ) -> list[str]:
        """Return dynamically randomized words from the requested category pool."""
        with self._thread_lock:
            words = list(self.categories.get(category, []))
        if not words:
            words = []

        rng = random.Random(seed) if seed is not None else random
        shuffled = list(words)
        rng.shuffle(shuffled)
        return shuffled[:limit] if limit is not None else shuffled

    def manifest_summary(self) -> dict[str, int]:
        """Return counts of dynamically categorized words."""
        with self._thread_lock:
            return {k: len(v) for k, v in self.categories.items()}


# Global singleton instance
_GLOBAL_CATEGORY_BANK: DynamicCategoryBank | None = None


def get_category_bank() -> DynamicCategoryBank:
    """Obtain or initialize the global dynamic category bank."""
    global _GLOBAL_CATEGORY_BANK
    if _GLOBAL_CATEGORY_BANK is None:
        _GLOBAL_CATEGORY_BANK = DynamicCategoryBank()
    return _GLOBAL_CATEGORY_BANK
