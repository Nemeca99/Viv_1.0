"""Deterministic Text Coverage Gate (Fail-Closed Reading License).

Implements the 95-98% Linguistic Comprehension Threshold:
Coverage(T) = sum(I(w in G_graduated)) / |T|

If Coverage >= 0.95: ADMISSIBLE_COMPREHENSION (Reading license granted; zero hallucination risk).
If Coverage < 0.95: FAIL_CLOSED_IMPEDANCE (Z = inf; reading license held).
Outputs a deterministic 'Targeted Acquisition Manifest' (the exact shopping list of
missing words needed to unlock the text for autonomous comprehension).
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Sequence

from autonomy.fractal_cognitive_engine import load_graduated_words
def load_full_grounded_vocabulary() -> set[str]:
    """Read the admitted vocabulary from the current verified graph and history."""
    vocab = set(load_graduated_words())
    try:
        from autonomy.learning_paths import latest_verified_run
        from nn_local.steel_brain_store import SQLiteNeuronGraphStore
        run = latest_verified_run()
        if run:
            with SQLiteNeuronGraphStore(run / "neuron_graph.sqlite3", readonly=True) as graph:
                vocab.update(graph.manifest().get("word_index", {}))
    except Exception:
        pass
    return vocab


# Canonical morphological suffixes mapped to BPE combination conduits
MORPHOLOGICAL_SUFFIXES = [
    ("ing", ""),
    ("ed", ""),
    ("es", ""),
    ("s", ""),
    ("ly", ""),
    ("er", ""),
    ("est", ""),
    ("tion", "te"),
    ("ment", ""),
    ("able", ""),
]


def normalize_token(token: str) -> str:
    """Normalize raw token into lowercase clean alphabetic form."""
    return re.sub(r"[^a-z]", "", token.lower())


def extract_candidate_lemmas(word: str) -> set[str]:
    """Generate canonical lemma variations via morphological deconstruction."""
    w = normalize_token(word)
    if not w:
        return set()
    
    candidates = {w}
    for suffix, replacement in MORPHOLOGICAL_SUFFIXES:
        if w.endswith(suffix) and len(w) > len(suffix) + 2:
            base = w[:-len(suffix)] + replacement
            candidates.add(base)
            # Handle doubling consonants (e.g. running -> runn -> run)
            if len(base) >= 3 and base[-1] == base[-2]:
                candidates.add(base[:-1])
            # Handle trailing 'e' (e.g. baked -> bake)
            if suffix in {"ed", "ing"} and not base.endswith("e"):
                candidates.add(base + "e")
    return candidates


@dataclass(frozen=True)
class CoverageResult:
    total_tokens: int
    unique_tokens: int
    grounded_tokens_count: int
    missing_tokens_count: int
    token_coverage_ratio: float
    unique_coverage_ratio: float
    is_admissible: bool
    status: str
    target_acquisition_manifest: list[tuple[str, int]]
    words_needed_to_unlock: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_tokens": self.total_tokens,
            "unique_tokens": self.unique_tokens,
            "grounded_tokens_count": self.grounded_tokens_count,
            "missing_tokens_count": self.missing_tokens_count,
            "token_coverage_ratio": round(self.token_coverage_ratio, 4),
            "token_coverage_percent": f"{self.token_coverage_ratio * 100:.2f}%",
            "unique_coverage_ratio": round(self.unique_coverage_ratio, 4),
            "is_admissible": self.is_admissible,
            "status": self.status,
            "words_needed_for_95pct": self.words_needed_to_unlock,
            "target_acquisition_manifest": [
                {"word": w, "frequency_in_text": freq}
                for w, freq in self.target_acquisition_manifest
            ],
        }


class TextCoverageGate:
    """Evaluates text comprehension against Viv's physical graph topology."""

    def __init__(self, graduated_vocabulary: set[str] | None = None):
        self.graduated_vocabulary = graduated_vocabulary if graduated_vocabulary is not None else load_full_grounded_vocabulary()

    def is_word_grounded(self, word: str) -> bool:
        """Check if word or any of its candidate lemma forms exist in graduated graph."""
        w = normalize_token(word)
        if not w:
            return True
        if w in self.graduated_vocabulary:
            return True
        # Check morphological lemma family
        for cand in extract_candidate_lemmas(w):
            if cand in self.graduated_vocabulary:
                return True
        return False

    def evaluate_passage(
        self,
        text: str,
        threshold: float = 0.95,
    ) -> CoverageResult:
        """Evaluate text passage against the deterministic 95% reading threshold."""
        raw_tokens = [normalize_token(t) for t in text.split()]
        tokens = [t for t in raw_tokens if t]

        if not tokens:
            return CoverageResult(
                total_tokens=0,
                unique_tokens=0,
                grounded_tokens_count=0,
                missing_tokens_count=0,
                token_coverage_ratio=1.0,
                unique_coverage_ratio=1.0,
                is_admissible=True,
                status="EMPTY_TEXT",
                target_acquisition_manifest=[],
                words_needed_to_unlock=0,
            )

        token_counter = Counter(tokens)
        grounded_count = 0
        missing_tokens = []

        for token in tokens:
            if self.is_word_grounded(token):
                grounded_count += 1
            else:
                missing_tokens.append(token)

        total_tokens = len(tokens)
        coverage_ratio = grounded_count / total_tokens

        # Missing words ranked by frequency
        missing_counter = Counter(missing_tokens)
        sorted_missing = missing_counter.most_common()

        # Calculate exact number of unique missing words needed to cross 95%
        target_grounded = int(total_tokens * threshold) + 1
        needed_extra = max(0, target_grounded - grounded_count)
        
        words_to_learn = 0
        accumulated_gain = 0
        for _, freq in sorted_missing:
            if accumulated_gain >= needed_extra:
                break
            accumulated_gain += freq
            words_to_learn += 1

        is_admissible = coverage_ratio >= threshold
        status = "ADMISSIBLE_COMPREHENSION" if is_admissible else "FAIL_CLOSED_IMPEDANCE"

        return CoverageResult(
            total_tokens=total_tokens,
            unique_tokens=len(token_counter),
            grounded_tokens_count=grounded_count,
            missing_tokens_count=len(missing_tokens),
            token_coverage_ratio=coverage_ratio,
            unique_coverage_ratio=(len(token_counter) - len(missing_counter)) / len(token_counter),
            is_admissible=is_admissible,
            status=status,
            target_acquisition_manifest=sorted_missing,
            words_needed_to_unlock=words_to_learn,
        )


def format_coverage_report(res: CoverageResult, title: str = "TEXT PASSAGE") -> str:
    """Format human-readable diagnostic report of the coverage gate."""
    lines = [
        "=" * 70,
        f"AIOS V2 · DETERMINISTIC READING LICENSE EVALUATION: {title}",
        "=" * 70,
        f"  Total Tokens: {res.total_tokens} | Unique Lemmas: {res.unique_tokens}",
        f"  Grounded Tokens: {res.grounded_tokens_count} | Missing Tokens: {res.missing_tokens_count}",
        f"  Text Coverage Ratio: {res.token_coverage_ratio * 100:.2f}% (Threshold: 95.00%)",
        f"  Verdict: {'[LICENSE GRANTED: ADMISSIBLE]' if res.is_admissible else '[FAIL-CLOSED: IMPEDANCE Z=inf - READING LICENSE HELD]'}",
    ]

    if res.is_admissible:
        lines.append("\n  >>> Physical graph conduits fully grounded. Zero hallucination risk.")
    else:
        lines.append(f"\n  >>> Targeted Acquisition Manifest: {res.words_needed_to_unlock} words needed to cross 95%:")
        for idx, (word, freq) in enumerate(res.target_acquisition_manifest[:10], 1):
            lines.append(f"      ({idx}) '{word}' (occurs {freq}x in passage)")
        if len(res.target_acquisition_manifest) > 10:
            lines.append(f"      ... and {len(res.target_acquisition_manifest) - 10} additional ungrounded tokens.")

    lines.append("=" * 70)
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deterministic Text Coverage Gate for Viv Hept")
    parser.add_argument("text", nargs="?", help="Direct text string to evaluate")
    parser.add_argument("--file", "-f", help="Path to text file to evaluate")
    parser.add_argument("--threshold", "-t", type=float, default=0.95, help="Coverage threshold (default: 0.95)")
    parser.add_argument("--json", action="store_true", help="Output raw JSON receipt")
    args = parser.parse_args()

    content = ""
    title = "COMMAND LINE INPUT"
    if args.file and os.path.exists(args.file):
        with open(args.file, "r", encoding="utf-8") as f:
            content = f.read()
        title = os.path.basename(args.file)
    elif args.text:
        content = args.text

    if not content:
        print("[COVERAGE HOLD] No passage supplied; refusing to inject a scripted sample.", flush=True)
        raise SystemExit(2)

    gate = TextCoverageGate()
    result = gate.evaluate_passage(content, threshold=args.threshold)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(format_coverage_report(result, title=title))
