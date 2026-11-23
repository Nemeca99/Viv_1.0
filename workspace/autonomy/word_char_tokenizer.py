"""Experimental word-first tokenizer with deterministic Unicode fallback.

This is an isolated preprocessing prototype. It does not alter Viv, INN, or
any admitted model/tokenizer checkpoint. Build a frozen vocabulary from the
training corpus, then use character IDs only for out-of-vocabulary words.
Whitespace and punctuation are retained as ordinary word-level pieces so
decode(encode(text)) is lossless for every Unicode scalar string.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Iterable


_PIECE = re.compile(r"\s+|[^\W\d_]+(?:['’][^\W\d_]+)*|\d+|[^\w\s]", re.UNICODE)


@dataclass(frozen=True)
class EncodedPiece:
    kind: str  # WORD, CHAR, or FALLBACK_END
    token_id: int


class WordCharTokenizer:
    """Frozen word vocabulary plus a universal Unicode-scalar fallback."""

    SCHEMA = "viv_word_char_tokenizer_v1"
    WORD = 0
    CHAR = 1
    FALLBACK_END = 2

    def __init__(self, words: Iterable[str]):
        vocabulary = sorted({word for word in words if word})
        if any(_PIECE.fullmatch(word) is None for word in vocabulary):
            raise ValueError("vocabulary entries must each be one lexical piece")
        self.words = tuple(vocabulary)
        self.word_to_id = {word: idx for idx, word in enumerate(self.words)}
        self.char_base = len(self.words)
        self.fallback_end_id = self.char_base + 0x110000
        self.vocab_size = self.fallback_end_id + 1

    @classmethod
    def from_texts(cls, texts: Iterable[str], *, min_frequency: int = 1) -> "WordCharTokenizer":
        if min_frequency < 1:
            raise ValueError("min_frequency must be >= 1")
        counts: Counter[str] = Counter()
        for text in texts:
            if not isinstance(text, str):
                raise TypeError("tokenizer corpus must contain strings")
            for match in _PIECE.finditer(text):
                piece = match.group(0)
                # Keep spacing and punctuation lossless as dedicated word pieces.
                counts[piece] += 1
        return cls(piece for piece, count in counts.items() if count >= min_frequency)

    def _pieces(self, text: str) -> list[str]:
        pieces = [m.group(0) for m in _PIECE.finditer(text)]
        if "".join(pieces) != text:
            raise ValueError("text contains an invalid Unicode scalar")
        return pieces

    def encode(self, text: str) -> list[EncodedPiece]:
        output: list[EncodedPiece] = []
        for piece in self._pieces(text):
            word_id = self.word_to_id.get(piece)
            if word_id is not None:
                output.append(EncodedPiece("WORD", word_id))
            else:
                output.extend(EncodedPiece("CHAR", self.char_base + ord(ch)) for ch in piece)
                output.append(EncodedPiece("FALLBACK_END", self.fallback_end_id))
        return output

    def decode(self, encoded: Iterable[EncodedPiece]) -> str:
        result: list[str] = []
        fallback: list[str] = []
        for item in encoded:
            if item.kind == "WORD":
                if fallback:
                    raise ValueError("unterminated character fallback")
                if not 0 <= item.token_id < len(self.words):
                    raise ValueError("word token ID out of range")
                result.append(self.words[item.token_id])
            elif item.kind == "CHAR":
                cp = item.token_id - self.char_base
                if not 0 <= cp <= 0x10FFFF or 0xD800 <= cp <= 0xDFFF:
                    raise ValueError("invalid Unicode scalar fallback ID")
                fallback.append(chr(cp))
            elif item.kind == "FALLBACK_END":
                if item.token_id != self.fallback_end_id or not fallback:
                    raise ValueError("invalid or empty fallback terminator")
                result.append("".join(fallback))
                fallback.clear()
            else:
                raise ValueError("unknown token kind")
        if fallback:
            raise ValueError("unterminated character fallback")
        return "".join(result)

    def manifest(self) -> dict:
        body = {
            "schema": self.SCHEMA,
            "normalization": "exact_surface_match; fallback_preserves_original_unicode",
            "fallback": "unicode_scalar_ids",
            "words": list(self.words),
            "char_base": self.char_base,
            "fallback_end_id": self.fallback_end_id,
            "vocab_size": self.vocab_size,
        }
        body["sha256"] = hashlib.sha256(
            json.dumps(body, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
        ).hexdigest()
        return body

    @classmethod
    def from_manifest(cls, manifest: dict) -> "WordCharTokenizer":
        if manifest.get("schema") != cls.SCHEMA:
            raise ValueError("unsupported tokenizer manifest")
        tokenizer = cls(manifest["words"])
        if tokenizer.manifest() != manifest:
            raise ValueError("tokenizer manifest hash or structure mismatch")
        return tokenizer


def describe_encoding(tokenizer: WordCharTokenizer, text: str) -> dict:
    encoded = tokenizer.encode(text)
    return {
        "text": text,
        "tokens": [{"kind": item.kind, "id": item.token_id} for item in encoded],
        "round_trip": tokenizer.decode(encoded),
        "fallback_piece_count": sum(item.kind == "FALLBACK_END" for item in encoded),
        "tokenizer_sha256": tokenizer.manifest()["sha256"],
    }
