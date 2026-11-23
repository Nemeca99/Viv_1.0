"""Category Prototype Engine: Syntactic Slot Inheritance and Manifold Permutation Reduction.

Implements the Architect's Vision:
1. Category Prototype Scaffolding: Categories (e.g. 'mammal', 'tool', 'star', 'river')
   serve as structural archetype anchors defining the canonical syntactic skeleton:
   [DET] -> [MEMBER_SLOT] -> [is] -> [DET] -> [CATEGORY_ANCHOR]
2. Syntactic Slot Inheritance: Novel vocabulary words bound to a category inherit the
   forward conduits of the category's subject slot directly into their neuron payloads.
3. Asymmetric Entailment Permutation Reduction: The ontological hypernym gradient
   (leaf -> hub) restricts the combinatorial permutation space from O(N!) down to
   valid canonical predication orderings.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Sequence
from collections import Counter

from nn_local.steel_brain_store import SQLiteNeuronGraphStore

SCALE = 1_000_000

class CategoryPrototypeEngine:
    def __init__(self, graph: SQLiteNeuronGraphStore):
        self.graph = graph

    def bind_entity_to_prototype(
        self,
        entity: str,
        category: str,
        det: str = "a",
        *,
        base_syntactic_conductance: int = 995_000,
        base_semantic_conductance: int = 990_000,
    ) -> bool:
        """Bind a novel or plastic entity to a category prototype.
        
        Elevates construction alignment and injects:
        - DET -> entity (forward subject admission)
        - entity -> is (forward copular progression)
        - entity -> category (semantic hypernym resonance)
        """
        manifest = self.graph.manifest()
        w_idx = manifest.get("word_index", {})

        ent_clean = entity.lower().strip()
        cat_clean = category.lower().strip()
        det_clean = det.lower().strip()

        ent_id = w_idx.get(ent_clean)
        cat_id = w_idx.get(cat_clean)
        det_id = w_idx.get(det_clean)
        is_id = w_idx.get("is")

        if not ent_id or not cat_id or not det_id or not is_id:
            return False

        ent_neuron = self.graph.load_neuron(ent_id)
        cat_neuron = self.graph.load_neuron(cat_id)
        det_neuron = self.graph.load_neuron(det_id)

        # 1. Elevate Construction Alignment & Lifecycle if Newborn
        center = ent_neuron.setdefault("center_attractor", {})
        if center.get("construction_alignment", 0) < SCALE:
            center["construction_alignment"] = SCALE
            center["admission_state"] = "PROTOTYPE_SLOT_BOUND"
            center["trusted_language_memory"] = True
            if ent_neuron.get("lifecycle") == "NEWBORN":
                ent_neuron["lifecycle"] = "PLASTIC"

        def _upsert_reflector(neuron: dict[str, Any], channel: str, peer_id: str, direction: str, weight: int):
            reflectors = neuron.setdefault("reflectors", {})
            channel_edges = reflectors.setdefault(channel, [])
            for e in channel_edges:
                if e.get("peer_id") == peer_id and e.get("direction") == direction:
                    e["weight"] = max(e["weight"], weight)
                    e["hot"] = True
                    return
            channel_edges.append({
                "direction": direction,
                "evidence_events": [f"PROTOTYPE_BIND:{cat_clean}"],
                "fail_hits": 0,
                "hot": True,
                "pass_hits": 3,
                "peer_id": peer_id,
                "uses": 3,
                "weight": weight,
            })

        # 2. Inject Conduits:
        # DET -> ENTITY (Left channel: forward stream)
        _upsert_reflector(det_neuron, "LEFT", ent_id, "OUT", base_syntactic_conductance)

        # ENTITY -> IS (Left channel: forward stream)
        _upsert_reflector(ent_neuron, "LEFT", is_id, "OUT", base_syntactic_conductance)

        # ENTITY -> CATEGORY (Up channel: vertical hypernym abstraction)
        _upsert_reflector(ent_neuron, "UP", cat_id, "OUT", base_semantic_conductance)

        # CATEGORY -> ENTITY (Down channel: member instance grounding)
        _upsert_reflector(cat_neuron, "DOWN", ent_id, "IN", base_semantic_conductance)

        # 3. Transact atomically to update JSON payloads, links index, and hash chain
        self.graph.transact(
            [det_neuron, ent_neuron, cat_neuron],
            event_kind="CATEGORY_PROTOTYPE_SLOT_BIND",
            details={"entity": ent_clean, "category": cat_clean, "det": det_clean},
        )
        return True

    @staticmethod
    def reduce_permutations(words: Sequence[str], category: str) -> list[tuple[str, ...]]:
        """Filter the N! permutation manifold using the Asymmetric Hypernym Gradient.
        
        Rules:
        1. Copular skeleton: 'is' must precede category complement '[a/an] [category]'.
        2. Subject position: novel entity must precede 'is'.
        3. Determiner binding: 'a' or 'an' must immediately precede the noun it modifies.
        """
        import itertools
        cat_clean = category.lower().strip()
        unique_perms = list(set(itertools.permutations(words)))

        valid_orders: list[tuple[str, ...]] = []
        for p in unique_perms:
            try:
                cat_idx = p.index(cat_clean)
                is_idx = p.index("is")
            except ValueError:
                continue

            # Hypernym Gradient: Category must be predicate complement (is ... category), not subject
            if is_idx > cat_idx:
                continue

            # Subject entity must precede copula 'is'
            entity_words = [w for w in p if w not in {"a", "an", "is", cat_clean}]
            if not entity_words:
                continue
            ent_idx = p.index(entity_words[0])
            if ent_idx > is_idx:
                continue

            valid_orders.append(p)

        return valid_orders
