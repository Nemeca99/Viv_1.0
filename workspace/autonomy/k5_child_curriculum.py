"""Compatibility wrapper for topology-backed curriculum selection.

The former hand-authored K-5 lesson registry was removed.  Curriculum items
must be sourced from verified SQLite/Wikipedia data and verbalized by the
local tutor; this module therefore fails closed when no such item is supplied.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ChildLesson:
    grade: int
    unit: int
    lesson_id: str
    title: str
    target_sentence: str
    focus_words: list[str] = field(default_factory=list)
    word_family: str | None = None
    conceptual_category: str | None = None
    pedagogical_goal: str = ""
    anti_parroting_mask: list[str] = field(default_factory=list)


class ChildCurriculumEngine:
    def __init__(self, history_file: Path | None = None):
        self.history_file = history_file or Path(__file__).resolve().parent / "logs" / "k5_curriculum_history.jsonl"
        self.history_file.parent.mkdir(parents=True, exist_ok=True)

    def get_completed_lesson_ids(self) -> set[str]:
        return set()

    def get_next_lesson(self, grade: int | None = None) -> ChildLesson | None:
        del grade
        return None

    def execute_lesson(self, lesson: ChildLesson) -> dict[str, Any]:
        raise RuntimeError(f"Curriculum lesson {lesson.lesson_id!r} lacks a verified topology-backed tutor proposal")

    def run_continuous(self, max_lessons: int = 10, stop_on_hold: bool = True) -> list[dict[str, Any]]:
        del max_lessons, stop_on_hold
        print("[CURRICULUM HOLD] No static lessons are permitted; await a verified topology candidate.", flush=True)
        return []


if __name__ == "__main__":
    ChildCurriculumEngine().run_continuous()
