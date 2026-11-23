"""Experimental context-ranked spelling proposals for the word/char LM.

This is proposal-only. It does not write learned facts or silently rewrite
inputs. Candidate vocabulary is the frozen tokenizer vocabulary; the causal
LM scores each candidate in its full left/right context. Answer agreement is
strict normalized text equality unless a caller supplies a separately
validated semantic comparator.
"""

from __future__ import annotations

import math
import re
import unicodedata

import torch
import torch.nn.functional as F

from experimental_word_char_lm import WordCharTransformer
from word_char_tokenizer import EncodedPiece, WordCharTokenizer


_LEXICAL = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*\Z", re.UNICODE)


def _edit_distance_at_most_two(left: str, right: str, limit: int) -> int:
    """Bounded Levenshtein distance for candidate generation, not ranking."""
    if abs(len(left) - len(right)) > limit:
        return limit + 1
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        row_min = i
        for j, b in enumerate(right, 1):
            value = min(current[j - 1] + 1, previous[j] + 1, previous[j - 1] + (a != b))
            current.append(value)
            row_min = min(row_min, value)
        if row_min > limit:
            return limit + 1
        previous = current
    return previous[-1]


def _piece_log_probability(model: WordCharTransformer, pieces: list[EncodedPiece]) -> float:
    if len(pieces) < 2:
        return float("-inf")
    device = next(model.parameters()).device
    kind_id = {"WORD": WordCharTokenizer.WORD, "CHAR": WordCharTokenizer.CHAR,
               "FALLBACK_END": WordCharTokenizer.FALLBACK_END}
    kinds = torch.tensor([[kind_id[p.kind] for p in pieces[:-1]]], dtype=torch.long, device=device)
    values = torch.tensor([[
        p.token_id - model.word_count if p.kind == "CHAR" else p.token_id
        for p in pieces[:-1]
    ]], dtype=torch.long, device=device)
    model.eval()
    out = model(kinds, values)
    total = 0.0
    for i, target in enumerate(pieces[1:]):
        k = kind_id[target.kind]
        total += float(F.log_softmax(out["kind"][0, i], dim=-1)[k].item())
        if target.kind == "WORD":
            total += float(F.log_softmax(out["word"][0, i], dim=-1)[target.token_id].item())
        elif target.kind == "CHAR":
            scalar = target.token_id - model.word_count
            for factor, shift in enumerate((14, 7, 0)):
                digit = (scalar >> shift) & 0x7F
                total += float(F.log_softmax(out["char_factors"][0, i, factor], dim=-1)[digit].item())
    return total


class ContextualCorrection:
    def __init__(self, tokenizer: WordCharTokenizer, model: WordCharTransformer,
                 *, max_candidates: int = 128):
        if len(tokenizer.words) != model.word_count:
            raise ValueError("tokenizer/model vocabulary mismatch")
        if max_candidates < 2:
            raise ValueError("max_candidates must be at least two")
        self.tokenizer = tokenizer
        self.model = model
        self.max_candidates = max_candidates
        self.lexicon = [w for w in tokenizer.words if _LEXICAL.fullmatch(w)]

    def propose(self, text: str) -> dict:
        pieces = self.tokenizer._pieces(text)
        suspects = [i for i, piece in enumerate(pieces)
                    if _LEXICAL.fullmatch(piece) and piece not in self.tokenizer.word_to_id]
        if not suspects:
            return {"status": "NO_OOV_WORD", "original": text, "corrected": text,
                    "candidate": None, "margin": None, "ranked": []}
        candidates = []
        for index in suspects:
            suspect = pieces[index]
            folded = suspect.casefold()
            limit = 1 if len(folded) <= 5 else 2
            for word in self.lexicon:
                normalized = word.casefold()
                distance = _edit_distance_at_most_two(folded, normalized, limit)
                if 0 < distance <= limit:
                    candidate = word
                    if suspect[:1].isupper():
                        candidate = candidate[:1].upper() + candidate[1:]
                    if candidate in self.tokenizer.word_to_id:
                        candidates.append((distance, candidate, index, suspect))
        candidates = sorted(set(candidates), key=lambda item: (item[0], item[1], item[2]))[:self.max_candidates]
        if not candidates:
            return {"status": "NO_CANDIDATE", "original": text, "corrected": text,
                    "candidate": None, "margin": None, "gain": None, "ranked": []}
        original_score = _piece_log_probability(self.model, self.tokenizer.encode(text))
        scored = []
        for distance, candidate, index, suspect in candidates:
            replaced = pieces.copy()
            replaced[index] = candidate
            encoded = self.tokenizer.encode("".join(replaced))
            scored.append({"candidate": candidate, "edit_distance": distance,
                           "suspect": suspect, "suspect_index": index,
                           "log_probability": _piece_log_probability(self.model, encoded)})
        scored.sort(key=lambda row: (-row["log_probability"], row["edit_distance"], row["suspect_index"], row["candidate"]))
        best = scored[0]
        # Confidence is measured against both the runner-up correction and
        # leaving the original input unchanged. A unique candidate must still
        # beat the unchanged-text baseline to have a positive margin.
        runner_up = scored[1]["log_probability"] if len(scored) > 1 else float("-inf")
        margin = best["log_probability"] - max(runner_up, original_score)
        index = best["suspect_index"]
        corrected = "".join(pieces[:index] + [best["candidate"]] + pieces[index + 1:])
        return {"status": "PROPOSED", "original": text, "corrected": corrected,
                "suspect": best["suspect"], "candidate": best["candidate"], "margin": margin,
                "original_log_probability": original_score,
                "candidate_log_probability": best["log_probability"],
                "gain": best["log_probability"] - original_score,
                "ranked": scored}

    def verify(self, text: str, answer_fn, *, min_margin: float,
               answers_equivalent=None) -> dict:
        """Return a correction only after score-margin and answer-agreement gates."""
        if not math.isfinite(min_margin) or min_margin < 0:
            raise ValueError("min_margin must be finite and non-negative")
        proposal = self.propose(text)
        if proposal["status"] != "PROPOSED":
            return {**proposal, "decision": "KEEP_ORIGINAL", "reason": proposal["status"]}
        original_answer = answer_fn(text)
        corrected_answer = answer_fn(proposal["corrected"])
        comparison = None
        if answers_equivalent is None:
            normalize = lambda value: " ".join(unicodedata.normalize("NFKC", str(value)).casefold().split())
            agrees = normalize(original_answer) == normalize(corrected_answer)
            comparison_state = "AGREES" if agrees else "CONTRADICTS"
            comparison = {"state": comparison_state, "reason": "normalized_exact_text"}
        else:
            comparison = answers_equivalent(original_answer, corrected_answer)
            if isinstance(comparison, dict):
                comparison_state = comparison.get("state", "UNKNOWN")
            elif comparison is True:
                comparison_state = "AGREES"
            elif comparison is False:
                comparison_state = "CONTRADICTS"
            else:
                comparison_state = "UNKNOWN"
        if proposal["gain"] <= 0:
            decision, reason = "KEEP_ORIGINAL", "NO_LIKELIHOOD_GAIN_OVER_ORIGINAL"
        elif proposal["margin"] < min_margin:
            decision, reason = "KEEP_ORIGINAL", "BELOW_SCORE_MARGIN"
        elif comparison_state == "AGREES":
            decision, reason = "ACCEPT_CORRECTION", "ANSWER_FRAMES_AGREE"
        else:
            decision = "KEEP_ORIGINAL"
            reason = "ANSWER_" + comparison_state
        return {**proposal, "decision": decision, "reason": reason,
                "original_answer": original_answer, "corrected_answer": corrected_answer,
                "answers_agree": comparison_state == "AGREES",
                "agreement_method": "frame_comparator" if answers_equivalent else "normalized_exact_text",
                "answer_comparison": comparison}

