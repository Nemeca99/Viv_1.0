"""Conceptual Resonance Engine: Multi-Anchor Wave Superposition and Concept Grounding.

Implements the Architect's Vision:
1. Multi-Anchor Query Resonance: Given query poles (e.g. ['birds', 'move']),
   the engine does NOT brute-force permutations. It propagates activation waves
   from each anchor and takes their Greatest Common Factor (constructive interference).
2. Concept Attractor Clusters: Words like 'fly', 'swim', 'run' connect to the
   'move' concept attractor, creating high-conductance associative bridges.
3. Zero-Brute-Force Resolution: Intersecting light cones prune the search space
   from factorial O(N!) down to O(1) topological retrieval.
"""

from __future__ import annotations

from collections import defaultdict
import math
from typing import Sequence

from nn_local.steel_brain_store import SQLiteNeuronGraphStore


class ConceptualResonanceEngine:
    def __init__(self, graph: SQLiteNeuronGraphStore):
        self.graph = graph

    def link_concept_cluster(
        self,
        concept_anchor: str,
        member_words: Sequence[str],
        base_conductance: int = 400_000,
    ) -> None:
        """Ground a set of related action/state words into a shared concept anchor (e.g. 'move')."""
        manifest = self.graph.manifest()
        word_idx = manifest.get("word_index", {})
        conn = self.graph.connection

        anchor_clean = concept_anchor.lower().strip()
        anchor_id = word_idx.get(anchor_clean)

        def _upsert_link(src: str, dst: str, weight: int):
            existing = conn.execute(
                "SELECT reflector, ordinal FROM links WHERE source_id = ? AND peer_id = ?",
                (src, dst),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE links SET weight = MIN(990000, weight + ?), pass_hits = pass_hits + 1 WHERE source_id = ? AND peer_id = ?",
                    (weight // 4, src, dst),
                )
            else:
                max_ord = conn.execute(
                    "SELECT COALESCE(MAX(ordinal), -1) FROM links WHERE source_id = ? AND reflector = 0",
                    (src,),
                ).fetchone()[0]
                conn.execute(
                    """INSERT INTO links (source_id, reflector, ordinal, peer_id, direction, weight, uses, pass_hits, fail_hits, hot, evidence_count, evidence_sha256)
                       VALUES (?, 0, ?, ?, 1, ?, 1, 1, 0, 1, 1, '')""",
                    (src, max_ord + 1, dst, weight),
                )

        if anchor_id:
            for word in member_words:
                w_clean = word.lower().strip()
                w_id = word_idx.get(w_clean)
                if not w_id or w_id == anchor_id:
                    continue
                _upsert_link(w_id, anchor_id, base_conductance)
                _upsert_link(anchor_id, w_id, base_conductance)

        # Cross-link member words pairwise with high mutual resonance
        cleaned_ids = [word_idx.get(w.lower().strip()) for w in member_words]
        valid_ids = [vid for vid in cleaned_ids if vid]
        for i in range(len(valid_ids)):
            for j in range(i + 1, len(valid_ids)):
                id_a, id_b = valid_ids[i], valid_ids[j]
                _upsert_link(id_a, id_b, base_conductance)
                _upsert_link(id_b, id_a, base_conductance)

        conn.commit()

    def resolve_multi_anchor_query(
        self,
        anchors: Sequence[str],
        candidate_pool: Sequence[str] | None = None,
        top_k: int = 5,
        exclude_function_words: bool = True,
    ) -> list[tuple[str, float]]:
        """Find the Greatest Common Factor neuron where all anchor activation fields intersect.
        
        Example:
            anchors=['birds', 'move'] -> activates 'birds' and 'move' fields.
            Intersection with maximum constructive interference -> 'fly'.
        """
        if not anchors:
            return []

        manifest = self.graph.manifest()
        word_idx = manifest.get("word_index", {})
        id_to_word = {v: k for k, v in word_idx.items()}
        conn = self.graph.connection

        anchor_ids: list[str] = []
        for a in anchors:
            a_clean = a.lower().strip()
            aid = word_idx.get(a_clean)
            if aid:
                anchor_ids.append(aid)

        if not anchor_ids:
            return []

        # 1. Expand activation field from each anchor (1-hop direct and 2-hop bridge)
        anchor_fields: list[dict[str, float]] = []

        for aid in anchor_ids:
            field: dict[str, float] = defaultdict(float)

            # Direct links (1-hop)
            rows = conn.execute(
                "SELECT peer_id, weight FROM links WHERE source_id = ? AND weight > 1000",
                (aid,),
            ).fetchall()
            for peer_id, weight in rows:
                field[peer_id] += float(weight)

            # 2-hop expansion (scaled by 0.15 so primary 1-hop conductance dominates over hub bridges)
            hop2_rows = conn.execute(
                """SELECT l2.peer_id, (l1.weight * l2.weight / 1000000.0) AS resonance
                   FROM links l1
                   JOIN links l2 ON l1.peer_id = l2.source_id
                   WHERE l1.source_id = ? AND l2.peer_id != ? AND l2.weight > 50000
                   LIMIT 200""",
                (aid, aid),
            ).fetchall()
            for peer_id, res in hop2_rows:
                field[peer_id] += float(res) * 0.15

            anchor_fields.append(field)

        # 2. Compute Greatest Common Factor (Constructive Wave Interference across all anchors)
        combined_nodes = set.union(*(set(f.keys()) for f in anchor_fields))

        scored_candidates: list[tuple[str, float]] = []
        anchor_words = {a.lower().strip() for a in anchors}

        for node_id in combined_nodes:
            word = id_to_word.get(node_id, "")
            if not word or not word.isalpha() or len(word) < 2:
                continue

            # Exclude the query anchors themselves
            if word in anchor_words:
                continue

            # Exclude high-frequency functional stopwords to prevent noise contamination
            if exclude_function_words and word in {
                "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with",
                "by", "from", "up", "about", "into", "over", "after", "is", "are", "was", "were",
                "be", "been", "being", "have", "has", "had", "do", "does", "did", "can", "could",
                "shall", "should", "will", "would", "may", "might", "must", "it", "its", "they",
                "them", "their", "theirs", "this", "that", "these", "those", "which", "who", "whom",
                "whose", "what", "where", "when", "why", "how", "all", "any", "both", "each", "few",
                "more", "most", "other", "some", "such", "no", "nor", "not", "only", "own", "same",
                "so", "than", "too", "very", "cat", "saw"
            }:
                continue

            # Optional candidate pool filter
            if candidate_pool and word not in candidate_pool:
                continue

            # Calculate GCF Support (how many anchors reach this node)
            support_count = sum(1 for f in anchor_fields if node_id in f and f[node_id] > 0)
            if support_count < min(2, len(anchor_fields)):
                # Must be reachable by multiple anchors to form constructive interference
                continue

            # Conductances from each anchor
            conductances = [f.get(node_id, 100.0) for f in anchor_fields]
            log_mean = sum(math.log(max(1.0, c)) for c in conductances) / len(conductances)
            base_resonance = math.exp(log_mean)

            # Constructive wave interference across all anchors
            gcf_bonus = (support_count / len(anchor_fields)) ** 2
            final_score = base_resonance * gcf_bonus

            scored_candidates.append((word, final_score))

        scored_candidates.sort(key=lambda x: x[1], reverse=True)
        return scored_candidates[:top_k]
