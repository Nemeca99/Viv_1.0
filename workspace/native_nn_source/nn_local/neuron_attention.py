"""Sparse neuron-local attention settled by the existing triadic RID."""

from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from time import perf_counter_ns
from typing import Any, Mapping, Sequence

from .fixed_point import SCALE, TriadicSettlement, settle_triadic
from .uml_neuron_gate import uml_bayesian_rate, uml_fixed_mean


@dataclass(frozen=True)
class NeuronAttentionInput:
    neuron_id: str
    self_signal: int
    user_context: tuple[int, int]
    assistant_context: tuple[int, int]
    mediator_context: tuple[int, int]
    active: bool = True


@dataclass(frozen=True)
class NeuronHeadState:
    neuron_id: str
    user: TriadicSettlement
    assistant: TriadicSettlement
    mediator: TriadicSettlement
    local_master: TriadicSettlement


@dataclass(frozen=True)
class AttentionPulse:
    neurons: tuple[NeuronHeadState, ...]
    system_master: TriadicSettlement
    active_neurons: int
    head_activations: int
    state: str


@dataclass(frozen=True)
class AttentionHeartbeat:
    duration_nanoseconds: int
    completed_cycles: int
    cycles_per_second: float
    active_neurons_per_cycle: int
    head_activations: int
    head_activations_per_second: float
    last_pulse: AttentionPulse | None
    resource_rid: int
    state: str


def _bounded(value: int) -> int:
    return max(0, min(SCALE, int(value)))


class SparseNeuronAttention:
    """Wake four mini-heads only for neurons participating in this thought."""

    @staticmethod
    def _role_head(self_signal: int, context: tuple[int, int]) -> TriadicSettlement:
        return settle_triadic((_bounded(self_signal), _bounded(context[0]), _bounded(context[1])))

    @staticmethod
    def _links(neuron: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
        reflectors = neuron.get("reflectors", {})
        return tuple(
            link
            for links in reflectors.values()
            for link in links
            if isinstance(link, Mapping)
        )

    @classmethod
    def inputs_from_route(
        cls,
        neurons: Mapping[str, Mapping[str, Any]],
        route: Sequence[str],
    ) -> tuple[NeuronAttentionInput, ...]:
        """Build dormant mini-head inputs from an immutable learned active subgraph."""
        route_ids = tuple(str(value) for value in route)
        if not route_ids or len(set(route_ids)) != len(route_ids):
            raise ValueError("attention route must contain distinct neuron ids")
        if any(neuron_id not in neurons for neuron_id in route_ids):
            raise ValueError("attention route references an unavailable neuron")
        active_ids = frozenset(route_ids)
        inputs: list[NeuronAttentionInput] = []
        neutral = SCALE // 2
        for neuron_id in route_ids:
            neuron = neurons[neuron_id]
            center = neuron.get("center_attractor", {})
            activation = neuron.get("activation", {})
            route_quality = center.get("route_quality_v1", {}).get("S_n")
            self_signal = int(route_quality) if route_quality is not None else uml_bayesian_rate(
                int(activation.get("pass_hits", 0)),
                int(activation.get("fail_hits", 0)),
            )
            links = cls._links(neuron)
            incoming = [int(link.get("weight", 0)) for link in links if link.get("direction") == "IN"]
            outgoing = [int(link.get("weight", 0)) for link in links if link.get("direction") == "OUT"]
            active_incoming = [
                int(link.get("weight", 0)) for link in links
                if link.get("direction") == "IN" and str(link.get("peer_id")) in active_ids
            ]
            active_outgoing = [
                int(link.get("weight", 0)) for link in links
                if link.get("direction") == "OUT" and str(link.get("peer_id")) in active_ids
            ]

            truth = center.get("truth_compatibility")
            alignment = center.get("construction_alignment")
            inputs.append(NeuronAttentionInput(
                neuron_id=neuron_id,
                self_signal=_bounded(self_signal),
                user_context=(
                    uml_fixed_mean(active_incoming, neutral=neutral),
                    uml_fixed_mean(incoming, neutral=neutral),
                ),
                assistant_context=(
                    uml_fixed_mean(active_outgoing, neutral=neutral),
                    uml_fixed_mean(outgoing, neutral=neutral),
                ),
                mediator_context=(
                    neutral if truth is None else _bounded(int(truth)),
                    neutral if alignment is None else _bounded(int(alignment)),
                ),
            ))
        return tuple(inputs)

    def pulse(self, inputs: Sequence[NeuronAttentionInput]) -> AttentionPulse:
        active = tuple(item for item in inputs if item.active)
        if not active:
            empty = settle_triadic((0, 0, 0))
            return AttentionPulse((), empty, 0, 0, "HOLD_NO_ACTIVE_NEURONS")
        states: list[NeuronHeadState] = []
        for item in active:
            user = self._role_head(item.self_signal, item.user_context)
            assistant = self._role_head(item.self_signal, item.assistant_context)
            mediator = self._role_head(item.self_signal, item.mediator_context)
            local_master = settle_triadic((user.quality, assistant.quality, mediator.quality))
            states.append(NeuronHeadState(item.neuron_id, user, assistant, mediator, local_master))
        system_master = settle_triadic((
            sum(item.user.quality for item in states) // len(states),
            sum(item.assistant.quality for item in states) // len(states),
            sum(item.mediator.quality for item in states) // len(states),
        ))
        settlements = [
            settlement
            for item in states
            for settlement in (item.user, item.assistant, item.mediator, item.local_master)
        ]
        state = "PASS" if system_master.state == "PASS" and all(item.state == "PASS" for item in settlements) else "HOLD_UNSETTLED"
        return AttentionPulse(tuple(states), system_master, len(states), 4 * len(states), state)

    @staticmethod
    def apply_consequence(
        neurons: Mapping[str, Mapping[str, Any]],
        pulse: AttentionPulse,
        consequence: str,
        *,
        evidence_ref: str,
        context_refs: Mapping[str, str | Sequence[str]] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Return updated active neurons for a CPU-issued one-bit consequence.

        HOLD is deliberately write-free.  This function never chooses a route
        and never decides whether an answer is correct; it only records the
        already-issued CPU consequence on the four heads that participated.
        """
        verdict = str(consequence).upper()
        if verdict.startswith("HOLD"):
            return ()
        if verdict not in {"PASS", "FAIL"}:
            raise ValueError("attention consequence must be PASS, FAIL, or HOLD")
        if pulse.state != "PASS":
            raise ValueError("cannot teach an unsettled attention pulse")
        if not evidence_ref:
            raise ValueError("attention consequence requires an evidence reference")
        changed: list[dict[str, Any]] = []
        for state in pulse.neurons:
            if state.neuron_id not in neurons:
                raise ValueError("attention pulse references an unavailable neuron")
            neuron = deepcopy(dict(neurons[state.neuron_id]))
            learned = neuron.setdefault("center_attractor", {}).setdefault(
                "sparse_attention_learning_v1",
                {"schema": "NN_SPARSE_ATTENTION_LEARNING_V1", "heads": {}},
            )
            heads = learned.setdefault("heads", {})
            # Count each participating context once, while global heads retain
            # one update per neuron/pulse. Keep legacy single-string callers.
            references = () if context_refs is None else context_refs.get(state.neuron_id, ())
            if isinstance(references, str):
                references = (references,)
            contexts = tuple(dict.fromkeys(str(value) for value in references if value))
            for name, settlement in (
                ("user", state.user),
                ("assistant", state.assistant),
                ("mediator", state.mediator),
                ("local_master", state.local_master),
            ):
                bucket = heads.setdefault(name, {"pass_hits": 0, "fail_hits": 0})
                key = "pass_hits" if verdict == "PASS" else "fail_hits"
                bucket[key] = int(bucket.get(key, 0)) + 1
                passed = int(bucket.get("pass_hits", 0))
                failed = int(bucket.get("fail_hits", 0))
                bucket["probability"] = uml_bayesian_rate(passed, failed)
                bucket["last_settled_quality"] = int(settlement.quality)
                for context_ref in contexts:
                    contextual = learned.setdefault("contexts", {}).setdefault(
                        str(context_ref), {"heads": {}, "updates": 0}
                    )
                    context_bucket = contextual["heads"].setdefault(
                        name, {"pass_hits": 0, "fail_hits": 0}
                    )
                    context_bucket[key] = int(context_bucket.get(key, 0)) + 1
                    context_passed = int(context_bucket.get("pass_hits", 0))
                    context_failed = int(context_bucket.get("fail_hits", 0))
                    context_bucket["probability"] = uml_bayesian_rate(
                        context_passed, context_failed
                    )
                    context_bucket["last_settled_quality"] = int(settlement.quality)
            for context_ref in contexts:
                learned["contexts"][str(context_ref)]["updates"] += 1
            learned["updates"] = int(learned.get("updates", 0)) + 1
            learned["last_consequence"] = verdict
            learned["last_evidence_ref"] = str(evidence_ref)
            changed.append(neuron)
        return tuple(changed)

    def heartbeat(
        self,
        inputs: Sequence[NeuronAttentionInput],
        *,
        duration_nanoseconds: int = 1_000_000_000,
        resource_rid: int = SCALE,
    ) -> AttentionHeartbeat:
        if duration_nanoseconds < 1:
            raise ValueError("attention heartbeat duration must be positive")
        admitted_rid = _bounded(resource_rid)
        active_count = sum(bool(item.active) for item in inputs)
        if admitted_rid == 0:
            return AttentionHeartbeat(duration_nanoseconds, 0, 0.0, active_count, 0, 0.0, None, 0, "HOLD_RESOURCE_RID_ZERO")
        start = perf_counter_ns()
        deadline = start + duration_nanoseconds
        completed = 0
        heads = 0
        last: AttentionPulse | None = None
        while perf_counter_ns() < deadline:
            candidate = self.pulse(inputs)
            finished = perf_counter_ns()
            if candidate.state != "PASS":
                return AttentionHeartbeat(
                    duration_nanoseconds, completed, completed * 1_000_000_000 / duration_nanoseconds,
                    active_count, heads, heads * 1_000_000_000 / duration_nanoseconds,
                    last, admitted_rid, candidate.state,
                )
            if finished > deadline:
                break
            completed += 1
            heads += candidate.head_activations
            last = candidate
        cycles_per_second = completed * 1_000_000_000 / duration_nanoseconds
        return AttentionHeartbeat(
            duration_nanoseconds,
            completed,
            cycles_per_second,
            active_count,
            heads,
            heads * 1_000_000_000 / duration_nanoseconds,
            last,
            admitted_rid,
            "PASS" if completed else "HOLD_NO_COMPLETE_CYCLE",
        )


__all__ = [
    "AttentionHeartbeat",
    "AttentionPulse",
    "NeuronAttentionInput",
    "NeuronHeadState",
    "SparseNeuronAttention",
]
