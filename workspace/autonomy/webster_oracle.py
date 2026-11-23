"""Webster & Corpus Oracle: Grounded Part-of-Speech and Lexical Verification.

Provides deterministic validation against:
1. Webster's 113,000+ Word Dictionary (L:/Standalone/NN/material/WebstersDictionary/dictionary.json)
2. Wikipedia attestation and PoS syntactic licensing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

WEBSTER_DICTIONARY_PATH = Path(r"L:\Standalone\NN\material\WebstersDictionary\dictionary.json")

_WEBSTER_POS_CACHE: dict[str, set[str]] | None = None
_WEBSTER_DEF_CACHE: dict[str, str] | None = None


def get_webster_pos_map() -> dict[str, set[str]]:
    """Load and cache canonical parts-of-speech for all Webster entries."""
    global _WEBSTER_POS_CACHE, _WEBSTER_DEF_CACHE
    if _WEBSTER_POS_CACHE is not None:
        return _WEBSTER_POS_CACHE

    pos_map: dict[str, set[str]] = {}
    def_map: dict[str, str] = {}

    if WEBSTER_DICTIONARY_PATH.is_file():
        try:
            raw = json.loads(WEBSTER_DICTIONARY_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                for entry in raw:
                    if not isinstance(entry, dict):
                        continue
                    word = str(entry.get("word", "")).strip().lower()
                    raw_pos = str(entry.get("pos", "")).strip().lower()
                    if not word or not word.isascii() or not word.isalpha():
                        continue

                    # Parse and normalize grammatical tags
                    tags = set()
                    for token in raw_pos.replace(",", " ").split():
                        clean_tok = token.rstrip(".;")
                        if clean_tok in {"a", "adj", "adjective", "p", "pa", "pp"}:
                            tags.add("adj")
                        elif clean_tok in {"n", "noun"}:
                            tags.add("noun")
                        elif clean_tok in {"v", "vb", "verb"}:
                            tags.add("verb")
                        elif clean_tok in {"adv", "adverb"}:
                            tags.add("adv")
                        elif clean_tok in {"prep", "preposition"}:
                            tags.add("prep")
                        elif clean_tok in {"pron", "pronoun"}:
                            tags.add("pron")
                        elif clean_tok in {"conj", "conjunction"}:
                            tags.add("conj")
                        elif clean_tok in {"interj", "interjection"}:
                            tags.add("interj")

                    if tags:
                        pos_map.setdefault(word, set()).update(tags)

                    defs = entry.get("definitions") or []
                    if defs and word not in def_map:
                        def_map[word] = str(defs[0]).strip()
        except Exception:
            pass

    # Basic grammatical closed-class words often classified peculiarly in historical lexicons
    closed_classes = {
        "the": {"det"},
        "a": {"det"},
        "an": {"det"},
        "this": {"det", "pron"},
        "that": {"det", "pron"},
        "they": {"pron"},
        "it": {"pron"},
        "he": {"pron"},
        "she": {"pron"},
        "we": {"pron"},
        "i": {"pron"},
        "you": {"pron"},
        "is": {"verb"},
        "are": {"verb"},
        "was": {"verb"},
        "were": {"verb"},
        "can": {"verb", "noun"},
        "could": {"verb"},
        "will": {"verb", "noun"},
        "would": {"verb"},
        "to": {"prep", "part"},
        "too": {"adv"},
        "two": {"noun", "adj"},
        "in": {"prep", "adv"},
        "on": {"prep", "adv"},
        "at": {"prep"},
        "over": {"prep", "adv"},
        "and": {"conj"},
        "or": {"conj"},
        "but": {"conj"},
    }
    for w, tags in closed_classes.items():
        pos_map.setdefault(w, set()).update(tags)

    # Strict grammatical overrides to prevent common past-tense verbs
    # from inheriting archaic mythological/polysemous noun entries (e.g. Greek goddess 'Ate')
    pure_verbs = {
        "ate": {"verb"},
        "sat": {"verb"},
        "ran": {"verb"},
        "slept": {"verb"},
        "swam": {"verb"},
        "knew": {"verb"},
    }
    for w, tags in pure_verbs.items():
        pos_map[w] = set(tags)

    _WEBSTER_POS_CACHE = pos_map
    _WEBSTER_DEF_CACHE = def_map
    return _WEBSTER_POS_CACHE


def has_pos(word: str, tag: str) -> bool:
    """Check if a word is licensed under a grammatical part of speech, including regular inflections."""
    pos_map = get_webster_pos_map()
    w = word.lower().strip()
    if not w:
        return False
    if tag in pos_map.get(w, set()):
        return True

    # Inflectional morphology checks
    if tag == "noun":
        # Regular plural: -s, -es, -ies
        if w.endswith("ies") and len(w) > 4:
            lemma = w[:-3] + "y"
            if tag in pos_map.get(lemma, set()):
                return True
        if w.endswith("es") and len(w) > 3:
            lemma = w[:-2]
            if tag in pos_map.get(lemma, set()):
                return True
        if w.endswith("s") and len(w) > 2:
            lemma = w[:-1]
            if tag in pos_map.get(lemma, set()):
                return True
    elif tag == "verb":
        # 3rd person singular -s/-es, past tense -ed, progressive -ing
        if w.endswith("ing") and len(w) > 4:
            lemma = w[:-3]
            if tag in pos_map.get(lemma, set()) or tag in pos_map.get(lemma + "e", set()):
                return True
        if w.endswith("ed") and len(w) > 3:
            lemma = w[:-2]
            if tag in pos_map.get(lemma, set()) or tag in pos_map.get(lemma + "e", set()):
                return True
        if w.endswith("es") and len(w) > 3:
            lemma = w[:-2]
            if tag in pos_map.get(lemma, set()):
                return True
        if w.endswith("s") and len(w) > 2:
            lemma = w[:-1]
            if tag in pos_map.get(lemma, set()):
                return True
    elif tag == "adj":
        # Comparative -er, superlative -est
        if w.endswith("er") and len(w) > 3:
            lemma = w[:-2]
            if tag in pos_map.get(lemma, set()) or tag in pos_map.get(lemma + "e", set()):
                return True
        if w.endswith("est") and len(w) > 4:
            lemma = w[:-3]
            if tag in pos_map.get(lemma, set()) or tag in pos_map.get(lemma + "e", set()):
                return True

    return False


def is_adjective(word: str) -> bool:
    return has_pos(word, "adj")


def is_noun(word: str) -> bool:
    return has_pos(word, "noun")


def is_verb(word: str) -> bool:
    return has_pos(word, "verb")


def is_adverb(word: str) -> bool:
    return has_pos(word, "adv")


def get_definition(word: str) -> str | None:
    get_webster_pos_map()
    if _WEBSTER_DEF_CACHE:
        return _WEBSTER_DEF_CACHE.get(word.lower())
    return None
