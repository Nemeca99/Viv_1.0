"""Context budget: input:output split for generation.

The Architect's ratio is 1:3, input:output. With the model's 128-token context
that is 32 input tokens and 96 output tokens. A small, fixed input side keeps
the input activations determined; the output side gets the room to speak.
"""
from __future__ import annotations

DEFAULT_CONTEXT = 128
DEFAULT_RATIO = (1, 3)


def split(context_length: int = DEFAULT_CONTEXT,
          ratio: tuple[int, int] = DEFAULT_RATIO) -> tuple[int, int]:
    """Return (input_tokens, output_tokens) for the given ratio.

    The input keeps the most recent tokens of the prompt; the output is the
    remaining context room. Both are at least one token.
    """
    if context_length < 2:
        raise ValueError("context_length_too_small")
    if ratio[0] <= 0 or ratio[1] <= 0:
        raise ValueError("ratio_terms_must_be_positive")
    total = ratio[0] + ratio[1]
    inp = max(1, context_length * ratio[0] // total)
    out = max(1, context_length - inp)
    return inp, out


def tail_ids(ids: list[int], input_tokens: int) -> list[int]:
    """Keep the most recent input_tokens of a prompt (left truncation)."""
    if input_tokens <= 0:
        raise ValueError("input_tokens_must_be_positive")
    return ids[-input_tokens:] if len(ids) > input_tokens else ids
