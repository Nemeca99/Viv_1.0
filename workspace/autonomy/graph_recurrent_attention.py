"""CPU topology recurrent state over the verified graph-attention signal.

This is a routing proposal layer only.  It never creates or authorizes edges;
the existing SQLite/Rust commit gates remain authoritative.  Inputs are built
from GraphAttentionScorer neighbors, so no vocabulary or sentence templates
are embedded in the recurrent layer.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
import math
from typing import Any

from autonomy.graph_attention import GraphAttentionScorer

try:  # torch is optional for compatibility with CPU-only environments.
    import torch
    from torch import nn
except Exception:  # pragma: no cover - exercised only on minimal installs.
    torch = None
    nn = None


class TopologyRecurrentAttention:
    """A deterministic Elman RNN whose inputs are verified graph attention."""

    def __init__(self, scorer: GraphAttentionScorer, *, context_limit: int = 32):
        self.scorer = scorer
        self.context_limit = max(1, int(context_limit))
        self.context: list[str] = []
        self._rnn: Any = None
        if nn is not None:
            self._rnn = nn.RNN(input_size=4, hidden_size=8, nonlinearity="tanh", batch_first=True)
            self._rnn.eval()
            with torch.no_grad():
                for parameter in self._rnn.parameters():
                    parameter.zero_()
                # Deterministic identity projection from graph features and a
                # stable recurrent carry. No random weights or learned words.
                self._rnn.weight_ih_l0[:4, :4] = torch.eye(4)
                self._rnn.weight_hh_l0[:8, :8] = torch.eye(8) * 0.5

    def _feature(self, surface: str, position: int) -> list[float]:
        ranked = self.scorer.rank(surface)
        if not ranked:
            return [0.0, 0.0, 0.0, float(position)]
        top = ranked[0]
        return [
            float(top.attention),
            min(1.0, float(top.edge_weight) / 1_000_000.0),
            1.0 if top.truth_compatible else 0.0,
            float(position),
        ]

    def score(self, surfaces: Sequence[str]) -> float:
        """Return a bounded recurrent route score for a candidate sequence."""
        if not surfaces:
            return 0.0
        route = list(surfaces)[-self.context_limit :]
        features = [self._feature(surface, index / max(1, len(route) - 1)) for index, surface in enumerate(route)]
        if self._rnn is not None:
            with torch.no_grad():
                values = torch.tensor([features], dtype=torch.float32)
                output, _ = self._rnn(values)
                return float(torch.sigmoid(output[0, -1].mean()).item())
        hidden = [0.0] * 4
        for vector in features:
            hidden = [math.tanh(vector[index] + 0.5 * hidden[index]) for index in range(4)]
        return (sum(hidden) / len(hidden) + 1.0) / 2.0

    def rank(self, candidates: Iterable[str]) -> dict[str, float]:
        """Score candidates conditioned on the retained topological context."""
        return {candidate: self.score([*self.context, candidate]) for candidate in candidates}

    def observe(self, surface: str) -> None:
        """Advance recurrent context after a cycle receipt is produced."""
        if surface:
            self.context.append(str(surface).casefold())
            del self.context[:-self.context_limit]


__all__ = ["TopologyRecurrentAttention"]
