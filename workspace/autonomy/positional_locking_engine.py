"""Positional Locking & Synaptic Mass Gradient Engine for Viv.

Implements the Architect's Vision:
1. Positional Fixed Points: As candidate sequences are sampled, words landing in
   their ground-truth positions are locked in place.
2. Combinatorial Space Collapse: Only unlocked slots are permuted, collapsing
   factorial search O(N!) into rapid iterative contraction O((N-|L|)!).
3. Guaranteed Uniqueness: Each tested permutation is unique across attempts.
4. Distance-Error Loss Gradient:
   - Correct positions (d=0) receive conductance rewards and pass_hit reinforcement.
   - Displaced positions (d>0) receive directional friction proportional to distance error.
5. Next-Token Conductance Priming:
   - Ground-truth transitions are entrenched into the Hept lattice and transition matrix,
     allowing unassisted first-pass mastery.
"""

from __future__ import annotations

import itertools
import random
from typing import Any, Callable, Sequence

from nn_local.steel_brain_store import SQLiteNeuronGraphStore


class PositionalLockingEngine:
    def __init__(
        self,
        graph: SQLiteNeuronGraphStore,
        reward_delta: int = 15000,
        penalty_rate: int = 2500,
    ):
        self.graph = graph
        self.reward_delta = reward_delta
        self.penalty_rate = penalty_rate

    def evaluate_candidate(
        self,
        candidate: Sequence[str],
        target: Sequence[str],
        locked_indices: set[int],
    ) -> tuple[set[int], list[int], bool]:
        """Identify correct positions to lock and calculate distance errors per candidate slot.
        
        Properly handles multisets / duplicate words (e.g. 'A vulture is a bird').
        """
        newly_locked = set(locked_indices)
        n = len(target)
        dist_per_cand = [0] * n

        # 1. Any slot where candidate exactly matches target is locked (dist = 0)
        for idx in range(n):
            if idx < len(candidate) and candidate[idx] == target[idx]:
                newly_locked.add(idx)
                dist_per_cand[idx] = 0

        # 2. For slots that don't match, calculate minimum distance to available target slots
        unmatched_target_slots = [j for j in range(n) if j not in newly_locked]
        for idx in range(n):
            if idx in newly_locked:
                continue
            word = candidate[idx] if idx < len(candidate) else None
            matching_slots = [j for j in unmatched_target_slots if target[j] == word]
            if matching_slots:
                dist = min(abs(idx - j) for j in matching_slots)
            else:
                all_matching = [j for j in range(n) if target[j] == word]
                dist = min(abs(idx - j) for j in all_matching) if all_matching else n
            dist_per_cand[idx] = dist

        all_locked = len(newly_locked) == n
        return newly_locked, dist_per_cand, all_locked

    def apply_synaptic_gradient(
        self,
        candidate: Sequence[str],
        target: Sequence[str],
        cand_distances: list[int],
    ) -> None:
        """Strengthen correct neighbor links and dampen spurious hops proportionally."""
        manifest = self.graph.manifest()
        word_idx = manifest.get("word_index", {})
        conn = self.graph.connection

        target_bigrams = set()
        for i in range(len(target) - 1):
            target_bigrams.add((target[i], target[i + 1]))

        # 1. Reward correct adjacent transitions matching target
        for i in range(len(candidate) - 1):
            c1, c2 = candidate[i], candidate[i + 1]
            if (c1, c2) in target_bigrams and cand_distances[i] == 0 and cand_distances[i + 1] == 0:
                id1, id2 = word_idx.get(c1), word_idx.get(c2)
                if id1 and id2:
                    conn.execute(
                        """UPDATE links SET pass_hits = pass_hits + 1, weight = MIN(990000, weight + ?)
                           WHERE source_id = ? AND peer_id = ?""",
                        (self.reward_delta, id1, id2),
                    )

        # 2. Penalize displaced hops or hops that do not belong to the target sequence
        for i in range(len(candidate) - 1):
            c1, c2 = candidate[i], candidate[i + 1]
            err = max(cand_distances[i], cand_distances[i + 1])
            if (c1, c2) not in target_bigrams or err > 0:
                id1, id2 = word_idx.get(c1), word_idx.get(c2)
                if id1 and id2:
                    penalty = self.penalty_rate * max(1, err)
                    conn.execute(
                        """UPDATE links SET fail_hits = fail_hits + 1, weight = MAX(10000, weight - ?)
                           WHERE source_id = ? AND peer_id = ?""",
                        (penalty, id1, id2),
                    )

        conn.commit()

    def reinforce_ground_truth_route(self, target: Sequence[str]) -> None:
        """Directly entrench the ground truth directional hops in the synaptic lattice."""
        manifest = self.graph.manifest()
        word_idx = manifest.get("word_index", {})
        conn = self.graph.connection

        for i in range(len(target) - 1):
            w1, w2 = target[i], target[i + 1]
            id1, id2 = word_idx.get(w1), word_idx.get(w2)
            if id1 and id2:
                conn.execute(
                    """UPDATE links SET pass_hits = pass_hits + 3, weight = MIN(990000, weight + ?)
                       WHERE source_id = ? AND peer_id = ?""",
                    (self.reward_delta * 2, id1, id2),
                )
        conn.commit()

    def generate_unique_permutation(
        self,
        target: Sequence[str],
        locked_indices: set[int],
        seen_permutations: set[tuple[str, ...]],
        rng: random.Random,
    ) -> list[str]:
        """Keep locked slots frozen; permute only unlocked slots with guaranteed uniqueness."""
        unlocked_slots = [i for i in range(len(target)) if i not in locked_indices]
        if not unlocked_slots:
            return list(target)

        unlocked_words = [target[i] for i in unlocked_slots]
        # Generate all distinct permutations of unlocked words
        all_perms = list(dict.fromkeys(itertools.permutations(unlocked_words)))
        rng.shuffle(all_perms)

        for perm in all_perms:
            candidate = list(target)
            for slot_idx, word in zip(unlocked_slots, perm):
                candidate[slot_idx] = word
            cand_tuple = tuple(candidate)
            if cand_tuple not in seen_permutations:
                seen_permutations.add(cand_tuple)
                return candidate

        # If all permutations have been seen, return target
        seen_permutations.add(tuple(target))
        return list(target)

    def scaffold_sentence(
        self,
        target: Sequence[str],
        *,
        seed: int = 812,
        max_turns: int = 64,
        work_gate: Callable[[str], dict] | None = None,
        score_sink: dict[str, int] | None = None,
        trace_sink: list[dict[str, Any]] | None = None,
        verbose: bool = True,
    ) -> dict:
        """Run the Architect's positional locking & mass gradient scaffold.
        
        Guarantees:
        1. Every tested route is unique.
        2. Correct positions lock in and carry forward across all subsequent turns.
        3. Visual lock-in display shows exact slots locked.
        4. Next-token synaptic highways are primed in the Hept lattice.
        """
        rng = random.Random(seed)
        locked: set[int] = set()
        seen: set[tuple[str, ...]] = set()
        traces = []
        passes = 0
        fails = 0

        for turn in range(1, max_turns + 1):
            if work_gate:
                work_gate("SCAFFOLD")

            cand = self.generate_unique_permutation(target, locked, seen, rng)
            new_locked, dist_list, complete = self.evaluate_candidate(cand, target, locked)
            self.apply_synaptic_gradient(cand, target, dist_list)

            is_exact = tuple(cand) == tuple(target)
            locked = new_locked

            if is_exact:
                passes += 1
                if score_sink is not None:
                    score_sink["passes"] += 1
                feedback = "ACCEPT: matches the input order"
            else:
                fails += 1
                if score_sink is not None:
                    score_sink["fails"] += 1
                feedback = f"DENY: {len(target) - len(locked)} slots misplaced; try another route"

            if verbose:
                locked_desc = ", ".join(f"[{i}: '{target[i]}']" for i in sorted(locked)) if locked else "None"
                print(f"Viv route: {' '.join(cand)} | Locked: {locked_desc} ({len(locked)}/{len(target)}) | Tutor: {feedback}", flush=True)

            row = {
                "turn": turn,
                "candidate": cand,
                "locked_count": len(locked),
                "is_exact": is_exact,
                "feedback": feedback,
            }
            traces.append(row)
            if trace_sink is not None:
                trace_sink.append({"phase": "sentence_order", "candidate": list(cand), "passed": is_exact})

            if complete:
                break

        # Entrench ground-truth route
        self.reinforce_ground_truth_route(target)

        # Record primed route in the session transition matrix
        try:
            from autonomy.learning.neuron_transition_matrix import record_session_lesson
            record_session_lesson(target)
        except Exception:
            pass

        return {
            "locked_count": len(locked),
            "complete": len(locked) == len(target),
            "turns": len(traces),
            "passes": passes,
            "fails": fails,
            "traces": traces,
        }
