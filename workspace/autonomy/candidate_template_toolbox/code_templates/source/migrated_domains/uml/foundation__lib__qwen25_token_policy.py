"""Explicit Qwen2.5 training/runtime token policy.

The upstream HF tokenizer and the converted GGUF expose different generic
EOS/PAD metadata.  This module keeps the semantic response terminator,
training padding choice, generation stop IDs, and converter metadata separate
so no caller can silently collapse them into one ``eos_token_id`` field.

This is a pure CPU-side policy helper.  It does not load weights, call Ollama,
open a lease, train, or change a model.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "qwen25_token_policy_v1"

# Semantic assistant-response terminator in the Qwen2.5 chat template.
IM_END_ID = 151645

# Training-side padding choice for the upstream HF lane.  It is deliberately
# not treated as the GGUF runtime padding metadata.
TRAINING_PAD_ID = 151643

# Metadata values retained for diagnosis, never used as semantic boundary
# definitions.
HF_EOS_METADATA_ID = 151643
HF_PAD_METADATA_ID = 151643
GGUF_EOS_METADATA_ID = 151645
GGUF_PADDING_METADATA_ID = 151645

# Generation must stop at the semantic assistant turn boundary.  The generic
# runtime EOS metadata is recorded separately above.
GENERATION_STOP_IDS = (IM_END_ID,)
IGNORE_INDEX = -100


def build_policy_record() -> dict[str, Any]:
    """Return the immutable policy facts used by parity/training audits."""
    return {
        "schema_version": SCHEMA_VERSION,
        "semantic_response_terminator_id": IM_END_ID,
        "training_pad_id": TRAINING_PAD_ID,
        "generation_stop_ids": list(GENERATION_STOP_IDS),
        "hf_metadata": {
            "eos_token_id": HF_EOS_METADATA_ID,
            "pad_token_id": HF_PAD_METADATA_ID,
        },
        "gguf_metadata": {
            "eos_token_id": GGUF_EOS_METADATA_ID,
            "padding_token_id": GGUF_PADDING_METADATA_ID,
        },
        "metadata_disagreement": True,
        "generic_eos_is_not_response_boundary": True,
        "conversion_policy": {
            "training_tokenizer_authority": "upstream_hf_tokenizer",
            "training_pad_id": TRAINING_PAD_ID,
            "training_eos_metadata_is_diagnostic_only": True,
            "semantic_response_terminator_id": IM_END_ID,
            "generation_stop_ids": list(GENERATION_STOP_IDS),
            "gguf_eos_metadata_is_runtime_diagnostic": True,
            "gguf_padding_metadata_is_runtime_diagnostic": True,
            "gguf_padding_must_not_be_reused_as_training_pad": True,
            "response_mask_must_supervise_im_end": True,
            "llama_cpp_trace_disposition": "PASS_READ_ONLY_GGUF_TOKEN_AND_TEMPLATE_PARITY",
            "training_release": "SEPARATE_AUTHORIZATION_REQUIRED",
        },
        "training_authorized": False,
        "run_authorized": False,
        "deployment_changed": False,
    }


def build_response_only_labels(
    input_ids: Sequence[int],
    response_mask: Sequence[bool],
    attention_mask: Sequence[bool],
    *,
    require_im_end: bool = True,
) -> list[int]:
    """Mask prompt/padding positions while supervising the response terminator.

    The function accepts plain sequences so it can be tested without torch and
    reused by a collator.  Standard causal-LM implementations perform the
    next-token shift internally; this helper therefore does not shift labels.
    """
    if not (len(input_ids) == len(response_mask) == len(attention_mask)):
        raise ValueError("token_policy_sequence_lengths_must_match")
    labels = [int(token) for token in input_ids]
    valid_indices = [
        index
        for index, (response, attended) in enumerate(zip(response_mask, attention_mask))
        if bool(response) and bool(attended)
    ]
    if require_im_end:
        if not valid_indices:
            raise ValueError("token_policy_response_mask_empty")
        if labels[valid_indices[-1]] != IM_END_ID:
            raise ValueError("token_policy_response_must_end_with_im_end")
    valid = set(valid_indices)
    return [token if index in valid else IGNORE_INDEX for index, token in enumerate(labels)]


def validate_runtime_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Compare runtime metadata without changing the canonical policy."""
    observed_eos = metadata.get("eos_token_id")
    observed_pad = metadata.get("padding_token_id", metadata.get("pad_token_id"))
    return {
        "schema_version": SCHEMA_VERSION,
        "observed": {
            "eos_token_id": observed_eos,
            "padding_token_id": observed_pad,
        },
        "semantic_response_terminator_id": IM_END_ID,
        "training_pad_id": TRAINING_PAD_ID,
        "eos_matches_semantic_response_terminator": observed_eos == IM_END_ID,
        "padding_matches_training_pad": observed_pad == TRAINING_PAD_ID,
        "metadata_requires_explicit_policy": (
            observed_eos != IM_END_ID or observed_pad != TRAINING_PAD_ID
        ),
    }


__all__ = [
    "GENERATION_STOP_IDS",
    "GGUF_EOS_METADATA_ID",
    "GGUF_PADDING_METADATA_ID",
    "HF_EOS_METADATA_ID",
    "HF_PAD_METADATA_ID",
    "IM_END_ID",
    "IGNORE_INDEX",
    "SCHEMA_VERSION",
    "TRAINING_PAD_ID",
    "build_policy_record",
    "build_response_only_labels",
    "validate_runtime_metadata",
]
