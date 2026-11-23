"""Deterministic, read-only graph attention over verified neuron neighbors.

This is a routing scorer, not an authority layer.  It never writes SQLite and
it masks edges that do not already carry verified evidence.
"""
from __future__ import annotations

import json
import math
import sqlite3
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AttentionNeighbor:
    neuron_id: str
    surface: str | None
    attention: float
    edge_weight: int
    truth_compatible: bool


_SCORER_CACHE: dict[tuple[str, float, int, int], tuple[dict[str, dict[str, Any]], dict[str, tuple[str, dict[str, Any]]]]] = {}


class GraphAttentionScorer:
    """Small fixed-QKV attention over a node's verified local neighborhood."""

    def __init__(self, graph_path: Path, *, top_k: int = 8):
        self.graph_path = Path(graph_path)
        self.top_k = max(1, int(top_k))
        resolved = str(self.graph_path.resolve())
        st = self.graph_path.stat()
        cache_key = (resolved, st.st_mtime, st.st_size, self.top_k)
        cached = _SCORER_CACHE.get(cache_key)
        if cached is not None:
            self._payloads, self._by_surface = cached
            return
        self._payloads: dict[str, dict[str, Any]] = {}
        self._by_surface: dict[str, tuple[str, dict[str, Any]]] = {}
        with sqlite3.connect(f"file:{self.graph_path.resolve()}?mode=ro", uri=True) as conn:
            rows = conn.execute("SELECT neuron_id, payload FROM neurons WHERE kind='WORD'").fetchall()
        for neuron_id, blob in rows:
            payload = self._payload(blob)
            self._payloads[neuron_id] = payload
            value = self._surface(payload)
            if value:
                self._by_surface.setdefault(value.casefold(), (neuron_id, payload))
        _SCORER_CACHE[cache_key] = (self._payloads, self._by_surface)

    @staticmethod
    def _payload(blob: bytes) -> dict[str, Any]:
        return json.loads(zlib.decompress(blob).decode("utf-8"))

    @staticmethod
    def _features(payload: dict[str, Any], degree: int) -> tuple[float, ...]:
        activation = payload.get("activation", {})
        passes = float(activation.get("pass_hits", 0))
        fails = float(activation.get("fail_hits", 0))
        total = passes + fails
        reliability = passes / total if total else 0.0
        uses = min(1.0, float(activation.get("uses", 0)) / 1000.0)
        truth = float(payload.get("center_attractor", {}).get("truth_compatibility") or 0) / 1_000_000.0
        return (
            uses,
            reliability,
            min(1.0, float(activation.get("confirmation_passes", 0)) / 3.0),
            truth,
            min(1.0, float(degree) / 32.0),
            1.0 if payload.get("lifecycle") == "STABLE" else 0.0,
        )

    @staticmethod
    def _surface(payload: dict[str, Any]) -> str | None:
        center = payload.get("center_attractor", {})
        value = center.get("learned_surface") or center.get("learned_combination")
        return str(value) if value else None

    def rank(self, surface: str) -> list[AttentionNeighbor]:
        with sqlite3.connect(f"file:{self.graph_path.resolve()}?mode=ro", uri=True) as conn:
            source_item = self._by_surface.get(surface.casefold())
            if source_item is None:
                return []
            source_id, source_payload = source_item
            edges = conn.execute(
                "SELECT peer_id, weight, uses, pass_hits, fail_hits, hot, evidence_count "
                "FROM links WHERE source_id=? ORDER BY weight DESC LIMIT 64",
                (source_id,),
            ).fetchall()
            if not edges:
                return []
            degrees = {peer_id: conn.execute("SELECT count(*) FROM links WHERE source_id=?", (peer_id,)).fetchone()[0] for peer_id, *_ in edges}
            source_degree = len(edges)
            query = self._features(source_payload, source_degree)
            scored: list[tuple[float, AttentionNeighbor]] = []
            scale = math.sqrt(len(query))
            for peer_id, weight, uses, passes, fails, hot, evidence_count in edges:
                # Truth mask: only pre-existing verified evidence may receive
                # attention.  Derived/unverified paths are open-circuit.
                total = passes + fails
                verified = bool(hot and evidence_count > 0 and passes >= fails and total > 0)
                if not verified or peer_id not in self._payloads:
                    continue
                key = self._features(self._payloads[peer_id], degrees.get(peer_id, 0))
                dot = sum(q * k for q, k in zip(query, key)) / scale
                # Edge conductance contributes to the key, but cannot bypass
                # the truth mask.
                score = dot + 0.25 * (float(weight) / 1_000_000.0)
                scored.append((score, AttentionNeighbor(
                    neuron_id=peer_id,
                    surface=self._surface(self._payloads[peer_id]),
                    attention=0.0,
                    edge_weight=int(weight),
                    truth_compatible=True,
                )))
            if not scored:
                return []
            denominator = sum(math.exp(score - max(s for s, _ in scored)) for score, _ in scored)
            ranked: list[AttentionNeighbor] = []
            for score, item in sorted(scored, key=lambda pair: pair[0], reverse=True)[: self.top_k]:
                attention = math.exp(score - max(s for s, _ in scored)) / denominator
                ranked.append(AttentionNeighbor(item.neuron_id, item.surface, attention, item.edge_weight, True))
            return ranked

    @property
    def known_surfaces(self) -> frozenset[str]:
        """Word-neuron surfaces present in the verified graph snapshot."""
        return frozenset(self._by_surface)


__all__ = ["AttentionNeighbor", "GraphAttentionScorer"]
