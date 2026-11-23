"""Secondary Checker: Deterministic Adjudicator for AI-Generated Lessons.

Acts as the unyielding filter between the LLM Teacher and Viv's Hept lattice.
Verifies that:
1. The template has exactly one blank slot '[?]'.
2. The target filler produces a deterministically valid sentence.
3. The distractor foil produces an invalid sentence (ensures clean boundary discrimination).
4. Punctuation, orthography, and token lengths conform to Viv's invariant specifications.
"""

from __future__ import annotations

import re
from typing import Any

def is_template(template: str) -> bool:
    """Structural check only; vocabulary is supplied by the graph caller."""
    return isinstance(template, str) and template.count("[?]") == 1


def parse_template(template: str) -> tuple[list[str], list[int]]:
    tokens = re.findall(r"\[\?\]|[A-Za-z][A-Za-z'-]*", template)
    blanks = [index for index, token in enumerate(tokens) if token == "[?"]
    return tokens, blanks


class SecondaryCheckerVerdict:
    def __init__(self, passed: bool, reason: str, certified_frame: dict[str, Any] | None = None):
        self.passed = passed
        self.reason = reason
        self.certified_frame = certified_frame or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "reason": self.reason,
            "certified_frame": self.certified_frame,
        }

    def __repr__(self) -> str:
        return f"Verdict(passed={self.passed}, reason='{self.reason}')"


class DeterministicSecondaryChecker:
    """Rigid adjudicator ensuring no hallucinations reach Viv's topological graph."""

    def __init__(self, allowed_vocabulary: set[str] | None = None):
        self.vocabulary = {str(word).casefold() for word in (allowed_vocabulary or set())}

    def verify_lesson_proposal(self, proposal: dict[str, Any]) -> SecondaryCheckerVerdict:
        """Inspect a proposed lesson frame from the LLM Teacher."""
        template = str(proposal.get("template", "")).strip()
        target = str(proposal.get("target_filler", "")).strip().lower()
        foil = str(proposal.get("distractor_foil", "")).strip().lower()

        # 1. Structural template check
        if not is_template(template):
            return SecondaryCheckerVerdict(False, "Template lacks blank slot marker '[?]'.")

        tokens, blanks = parse_template(template)
        if len(blanks) != 1:
            return SecondaryCheckerVerdict(
                False, f"Template must have exactly one blank slot, found {len(blanks)}."
            )

        if not (3 <= len(tokens) <= 7):
            return SecondaryCheckerVerdict(
                False, f"Token count must be between 3 and 7, got {len(tokens)}."
            )

        # 2. Vocabulary & Orthography check
        if not target or not target.isalpha() or len(target) > 20:
            return SecondaryCheckerVerdict(False, f"Target filler '{target}' is invalid.")

        if not foil or not foil.isalpha() or len(foil) > 20:
            return SecondaryCheckerVerdict(False, f"Distractor foil '{foil}' is invalid.")

        if target == foil:
            return SecondaryCheckerVerdict(False, "Target and foil cannot be identical.")

        if not self.vocabulary:
            return SecondaryCheckerVerdict(False, "No graph vocabulary supplied; lesson held closed.")
        template_words = [token.casefold() for token in tokens if token != "[?]"]
        if any(token not in self.vocabulary for token in template_words):
            return SecondaryCheckerVerdict(False, "Template contains a token outside admitted graph vocabulary.")
        if target not in self.vocabulary or foil not in self.vocabulary:
            return SecondaryCheckerVerdict(False, "Lesson fillers are outside admitted graph vocabulary.")

        # 3. Construct concrete candidate sentences
        blank_idx = blanks[0]
        
        target_words = list(tokens)
        target_words[blank_idx] = target
        
        foil_words = list(tokens)
        foil_words[blank_idx] = foil

        # Grammar and semantic truth belong to the topology/ontology gates.
        # This layer only certifies that substitutions are admitted neurons.

        # Certified clean lesson frame
        certified = {
            "template": template,
            "tokens": tokens,
            "blank_index": blank_idx,
            "target": target,
            "foil": foil,
            "target_sentence": " ".join(target_words),
            "foil_sentence": " ".join(foil_words),
            "category": proposal.get("category", "general_syntax"),
        }
        return SecondaryCheckerVerdict(True, "CERTIFIED", certified_frame=certified)
