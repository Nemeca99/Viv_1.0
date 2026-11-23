"""Unit tests for the Deterministic Text Coverage Gate (Fail-Closed Reading License)."""

from __future__ import annotations

import pytest
from autonomy.coverage_gate import TextCoverageGate, extract_candidate_lemmas, normalize_token


def test_token_normalization():
    assert normalize_token("Hello,") == "hello"
    assert normalize_token("WORLD!!!") == "world"
    assert normalize_token("  word-neuron  ") == "wordneuron"


def test_morphological_lemma_extraction():
    # Suffix deconstruction
    assert "run" in extract_candidate_lemmas("running")
    assert "bake" in extract_candidate_lemmas("baked")
    assert "cat" in extract_candidate_lemmas("cats")
    assert "quick" in extract_candidate_lemmas("quickly")
    assert "fast" in extract_candidate_lemmas("faster")


def test_100_percent_coverage_admissible():
    # Controlled vocabulary
    vocab = {"the", "cat", "saw", "their", "fish", "and", "dog", "is", "big"}
    gate = TextCoverageGate(graduated_vocabulary=vocab)

    text = "The cat saw their fish. The dog is big."
    res = gate.evaluate_passage(text, threshold=0.95)

    assert res.is_admissible is True
    assert res.status == "ADMISSIBLE_COMPREHENSION"
    assert res.token_coverage_ratio == 1.0
    assert len(res.target_acquisition_manifest) == 0
    assert res.words_needed_to_unlock == 0


def test_fail_closed_under_95_percent():
    vocab = {"the", "cat", "is"}
    gate = TextCoverageGate(graduated_vocabulary=vocab)

    text = "The cat is watching the mysterious spaceship flying towards quantum galaxies."
    res = gate.evaluate_passage(text, threshold=0.95)

    assert res.is_admissible is False
    assert res.status == "FAIL_CLOSED_IMPEDANCE"
    assert res.token_coverage_ratio < 0.95
    assert len(res.target_acquisition_manifest) > 0
    assert res.words_needed_to_unlock > 0

    missing_words = [w for w, _ in res.target_acquisition_manifest]
    assert "mysterious" in missing_words
    assert "spaceship" in missing_words
    assert "galaxies" in missing_words


def test_morphological_derivation_counts_towards_grounding():
    # Base lemma in vocab
    vocab = {"run", "the", "dog"}
    gate = TextCoverageGate(graduated_vocabulary=vocab)

    # 'running' and 'runs' should match 'run' via morphological lemma extraction
    text = "The dog runs. The dog is running."
    res = gate.evaluate_passage(text, threshold=0.50)

    assert gate.is_word_grounded("runs") is True
    assert gate.is_word_grounded("running") is True
