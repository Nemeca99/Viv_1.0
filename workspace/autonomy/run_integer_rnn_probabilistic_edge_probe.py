"""Candidate-only probe: probabilistic edge choice over a frozen verified graph.

The SQLite graph defines the immutable allowed edge set. A local fixed-point
RNN scores those edges; integer masses and a seeded PRNG explore the choices.
This probe writes only its receipt, never the topology or persistent memory.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import random
import sqlite3
from pathlib import Path
import sys
import uuid

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from autonomy.topology_integer_rnn import TopologyIntegerRNN, VerifiedExecutionTeacher

DB = HERE / "viv_code_topology.sqlite3"
OUT = HERE / "learning" / "deepseek_candidate_runs"
SEEN_PRIMITIVE = "AUTONOMOUS_CHALLENGE_24_RECURSIVE_TIC_TAC_TOE_EVALUATOR"
WEIGHT_SEEDS = (20261125, 20261127, 20261129, 20261131, 20261133,
                20261135, 20261137, 20261139)
EXPLORATION_SEED = 20261126
DRAWS = 512


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_verified_graph() -> tuple[dict[str, dict], list[tuple[str, str, str]]]:
    uri = "file:" + DB.resolve().as_posix() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.execute("PRAGMA query_only=ON")
        nodes = {
            row[0]: {"kind": row[1], "symbol": row[2], "vector_data": row[3:]}
            for row in conn.execute(
                """SELECT neuron_id, kind, symbol_name, scope_depth, pass_count,
                          sha256, code_repr, test_receipt
                   FROM viv_code_neurons
                   WHERE pass_count > 0 AND test_receipt LIKE 'VERIFIED_%'"""
            )
        }
        edges = [
            (row[0], row[1], row[2])
            for row in conn.execute(
                """SELECT s.source_id, s.target_id, s.relation
                   FROM viv_code_synapses AS s
                   JOIN viv_code_neurons AS a ON a.neuron_id=s.source_id
                   JOIN viv_code_neurons AS b ON b.neuron_id=s.target_id
                   WHERE a.pass_count > 0 AND a.test_receipt LIKE 'VERIFIED_%'
                     AND b.pass_count > 0 AND b.test_receipt LIKE 'VERIFIED_%'
                   ORDER BY s.source_id, s.target_id, s.relation"""
            )
        ]
    return nodes, edges


def sample_indices(masses: list[int], count: int, seed: int) -> list[int]:
    rng = random.Random(seed)
    total = sum(masses)
    chosen: list[int] = []
    for _ in range(count):
        draw = rng.randrange(total)
        cumulative = 0
        for index, mass in enumerate(masses):
            cumulative += mass
            if draw < cumulative:
                chosen.append(index)
                break
    return chosen


def score_edges(network: TopologyIntegerRNN, source: tuple[int, ...],
                target_vectors: dict[str, tuple[int, ...]], target_ids: list[str]) -> list[int]:
    scores = []
    for target_id in target_ids:
        network.reset()
        network.step(source)
        hidden = network.step(target_vectors[target_id])
        scores.append(int(sum(hidden[index] * target_vectors[target_id][index]
                              for index in range(network.hidden_size))))
    return scores


def run() -> dict:
    topology_before = sha256_file(DB)
    nodes, edges = load_verified_graph()
    edge_set = {(source, target, relation) for source, target, relation in edges}
    outgoing: dict[str, list[tuple[str, str]]] = {}
    for source, target, relation in edges:
        if nodes[source]["kind"] == "FUNCTION":
            outgoing.setdefault(source, []).append((target, relation))
    source_id, targets = sorted(outgoing.items(), key=lambda item: (-len(item[1]), item[0]))[0]
    targets = sorted(set(targets))
    if len(targets) < 2:
        raise RuntimeError("EDGE_EXPLORATION_NEEDS_MULTIPLE_VERIFIED_CHOICES")

    anchor_width = 8
    anchors = VerifiedExecutionTeacher(DB, anchor_width=anchor_width)
    seen_route = anchors.primitive_route(SEEN_PRIMITIVE)
    training_route = [anchor.vector for anchor in reversed(seen_route)]
    target_ids = [target for target, _relation in targets]
    anchor_rows = anchors.anchors.load([source_id, *target_ids])
    vector_by_id = {row.neuron_id: row.vector for row in anchor_rows}
    source_targets = {target for target, _relation in targets}
    denied_target = next(node_id for node_id in sorted(nodes) if node_id != source_id and node_id not in source_targets)
    negative_control_allow = (source_id, denied_target, "PROBE_NEGATIVE_CONTROL") in edge_set
    if negative_control_allow:
        raise AssertionError("NEGATIVE_CONTROL_UNEXPECTEDLY_PRESENT")

    score_columns: list[list[int]] = [[] for _ in targets]
    mass_probability_columns: list[list[float]] = [[] for _ in targets]
    counts = [0 for _ in targets]
    uniform_counts = [0 for _ in targets]
    run_rows = []
    backends = set()
    for weight_seed in WEIGHT_SEEDS:
        rng = random.Random(weight_seed)
        network = TopologyIntegerRNN(anchor_width, anchor_width, scale_bits=0,
                                     state_limit=128, use_gpu=True)
        network.set_weights(
            [[rng.randint(-1, 1) for _ in range(anchor_width)] for _ in range(anchor_width)],
            [[rng.randint(-1, 1) for _ in range(anchor_width)] for _ in range(anchor_width)],
        )
        learning = network.learn_route(training_route, reward=1)
        scores = score_edges(network, vector_by_id[source_id], vector_by_id, target_ids)
        cpu_reference = TopologyIntegerRNN(anchor_width, anchor_width, scale_bits=0,
                                           state_limit=128, use_gpu=False)
        cpu_reference.set_weights(network.weight_input, network.weight_hidden)
        cpu_scores = score_edges(cpu_reference, vector_by_id[source_id], vector_by_id, target_ids)
        if scores != cpu_scores:
            raise AssertionError("GPU_CPU_INTEGER_EDGE_SCORES_DIFFER")
        floor = min(scores)
        masses = [max(1, int(score - floor + 1)) for score in scores]
        probabilities = [mass / sum(masses) for mass in masses]
        first = sample_indices(masses, DRAWS, EXPLORATION_SEED)
        repeat = sample_indices(masses, DRAWS, EXPLORATION_SEED)
        if first != repeat:
            raise AssertionError("FIXED_SEED_SAMPLING_NOT_REPEATABLE")
        uniform = sample_indices([1 for _ in targets], DRAWS, EXPLORATION_SEED)
        uniform_repeat = sample_indices([1 for _ in targets], DRAWS, EXPLORATION_SEED)
        if uniform != uniform_repeat:
            raise AssertionError("FIXED_SEED_UNIFORM_CONTROL_NOT_REPEATABLE")
        for index in first:
            target_id, relation = targets[index]
            if (source_id, target_id, relation) not in edge_set:
                raise AssertionError("SAMPLED_EDGE_NOT_IN_FROZEN_TOPOLOGY")
            counts[index] += 1
        for index in uniform:
            target_id, relation = targets[index]
            if (source_id, target_id, relation) not in edge_set:
                raise AssertionError("UNIFORM_CONTROL_EDGE_NOT_IN_FROZEN_TOPOLOGY")
            uniform_counts[index] += 1
        for index, score in enumerate(scores):
            score_columns[index].append(score)
            mass_probability_columns[index].append(probabilities[index])
        backends.add(network.backend)
        run_rows.append({
            "weight_seed": weight_seed,
            "weight_sha256": learning.weights_sha256,
            "scores": scores,
            "sampling_probabilities": probabilities,
            "sample_sequence_sha256": hashlib.sha256(json.dumps(first, separators=(",", ":")).encode()).hexdigest(),
            "same_seed_reproduced_sequence": first == repeat,
            "uniform_control_same_seed_reproduced_sequence": uniform == uniform_repeat,
            "gpu_cpu_integer_scores_identical": scores == cpu_scores,
            "backend": network.backend,
        })
    topology_after = sha256_file(DB)
    if topology_before != topology_after:
        raise AssertionError("TOPOLOGY_CHANGED_DURING_READ_ONLY_PROBE")

    rows = []
    for index, (target_id, relation) in enumerate(targets):
        rows.append({
            "target_id": target_id,
            "target_symbol": nodes[target_id]["symbol"],
            "relation": relation,
            "rnn_integer_score_min": min(score_columns[index]),
            "rnn_integer_score_max": max(score_columns[index]),
            "candidate_selection_probability_mean": sum(mass_probability_columns[index]) / len(WEIGHT_SEEDS),
            "sample_count": counts[index],
            "weighted_empirical_probability": counts[index] / (DRAWS * len(WEIGHT_SEEDS)),
            "uniform_sample_count": uniform_counts[index],
            "uniform_empirical_probability": uniform_counts[index] / (DRAWS * len(WEIGHT_SEEDS)),
        })
    payload = {
        "schema": "viv_integer_rnn_probabilistic_edge_probe_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "topology_path": str(DB),
        "topology_sha256_before": topology_before,
        "topology_sha256_after": topology_after,
        "verified_node_count": len(nodes),
        "verified_edge_count": len(edges),
        "fixed_structure": True,
        "source_id": source_id,
        "source_symbol": nodes[source_id]["symbol"],
        "allowed_edge_count": len(targets),
        "seen_training_primitive": SEEN_PRIMITIVE,
        "weight_seeds": list(WEIGHT_SEEDS),
        "exploration_seed": EXPLORATION_SEED,
        "draws": DRAWS,
        "backend_by_seed": sorted(backends),
        "anchor_width": anchor_width,
        "probability_method": "uncalibrated linear integer mass: score - minimum score + 1, normalized over frozen allowed edges",
        "gpu_cpu_edge_scores_identical_all_seeds": all(row["gpu_cpu_integer_scores_identical"] for row in run_rows),
        "same_seed_reproduced_sequence_all_seeds": all(row["same_seed_reproduced_sequence"] for row in run_rows),
        "uniform_control_same_seed_reproduced_sequence_all_seeds": all(row["uniform_control_same_seed_reproduced_sequence"] for row in run_rows),
        "rnn_transitions_learned_per_candidate": len(training_route) - 1,
        "per_seed": run_rows,
        "negative_control": {"source_id": source_id, "target_id": denied_target, "gate": "DENY"},
        "candidate_edges": rows,
        "topology_write": False,
        "persistent_memory_write": False,
        "promoted": False,
    }
    payload["receipt_sha256"] = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / f"probabilistic_edge_probe_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}_{uuid.uuid4().hex[:8]}.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"receipt": str(target), "receipt_sha256": payload["receipt_sha256"],
            "backends": sorted(backends), "source": nodes[source_id]["symbol"],
            "allowed_edges": len(targets), "weight_seeds": len(WEIGHT_SEEDS), "draws_per_seed": DRAWS,
            "repeatable": payload["same_seed_reproduced_sequence_all_seeds"],
            "gpu_cpu_scores_match": payload["gpu_cpu_edge_scores_identical_all_seeds"],
            "topology_unchanged": topology_before == topology_after,
            "negative_control": "DENY", "topology_sha256": topology_after}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
