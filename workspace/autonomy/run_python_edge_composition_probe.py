"""Measure learned RNN edge preference against a fixed Python composition gate."""
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
WORKSPACE = HERE.parent
sys.path[:0] = [str(WORKSPACE), str(HERE)]
import python_edge_curriculum_test_10017 as curriculum
import viv_code_learning_loop as gates
from autonomy.topology_integer_rnn import TopologyIntegerRNN

DB = HERE / "viv_code_topology.sqlite3"
OUT = HERE / "learning" / "deepseek_candidate_runs"
DRAWS = 4096
SEED = 20261141


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical_sha256(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def topology_sha256() -> str:
    uri = "file:" + DB.resolve().as_posix() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.execute("PRAGMA query_only=ON")
        row = conn.execute("PRAGMA quick_check").fetchone()
        if not row or row[0] != "ok":
            raise RuntimeError("TOPOLOGY_QUICK_CHECK_FAILED")
    return file_sha256(DB)


def chain_is_type_valid(route: list[str], primitives: dict) -> bool:
    return all(primitives[left]["output"] == primitives[right]["input"]
               for left, right in zip(route, route[1:]))


def make_code(primitives: dict, route: list[str], function_name: str) -> str:
    definitions = "\n\n".join(primitives[name]["code"] for name in primitives)
    expression = "value"
    for name in route:
        expression = f"{name}({expression})"
    return f"{definitions}\n\ndef {function_name}(value):\n    return {expression}\n"


def draw(masses: list[int], count: int, seed: int) -> list[int]:
    rng = random.Random(seed)
    total = sum(masses)
    result = []
    for _ in range(count):
        ticket = rng.randrange(total)
        for index, mass in enumerate(masses):
            if ticket < mass:
                result.append(index)
                break
            ticket -= mass
    return result


def main() -> int:
    spec = curriculum.EDGE_COMPOSITION
    primitives = spec["primitives"]
    training_route = spec["training"]["route"]
    held_route = spec["held_out"]["route"]
    candidate_edges = list(spec["candidate_edges"])
    if not chain_is_type_valid(training_route, primitives):
        raise ValueError("TRAINING_ROUTE_TYPE_MISMATCH")
    if not chain_is_type_valid(held_route, primitives):
        raise ValueError("HELDOUT_ROUTE_TYPE_MISMATCH")
    output_type = primitives[held_route[-1]]["output"]
    allowed_edges = [name for name in candidate_edges
                     if primitives[name]["input"] == primitives["increment"]["output"]
                     and primitives[name]["output"] == primitives["square"]["output"]]
    if set(allowed_edges) != set(candidate_edges) or output_type != "str":
        raise ValueError("CANDIDATE_EDGE_TYPE_FILTER_MISMATCH")

    topology_before = topology_sha256()
    test_file = HERE / "python_edge_curriculum_test_10017.py"
    test_hash = file_sha256(test_file)

    train_tests = spec["training"]["tests"].replace("compose_train", "compose_reference")
    train_code = make_code(primitives, training_route, "compose_reference")
    train_ok, train_error = gates.gate_python(train_code, train_tests)
    if not train_ok:
        raise RuntimeError("GATE_REJECTED_VERIFIED_EDGE_TRAINING_ROUTE:" + train_error[:1000])

    # Deterministic gate outcomes for each possible middle edge in both the
    # learned (retrieval) route and the held-out (recombination) route.
    correct_edge_by_gate = {}
    candidate_gate_rows = []
    training_gate_rows = []
    for name in allowed_edges:
        train_route = ["increment", name, "is_even", "bool_label"]
        train_candidate_code = make_code(primitives, train_route, "compose_train")
        train_passed, train_error = gates.gate_python(train_candidate_code, spec["training"]["tests"])
        training_gate_rows.append({"edge": name, "type_compatible": True,
                                   "gate": "ALLOW" if train_passed else "DENY",
                                   "error": train_error[:1000]})

        route = ["increment", name, "is_even", "bool_label"]
        code = make_code(primitives, route, "compose_candidate")
        passed, error = gates.gate_python(code, spec["held_out"]["tests"])
        correct_edge_by_gate[name] = bool(passed)
        candidate_gate_rows.append({"edge": name, "type_compatible": True,
                                    "gate": "ALLOW" if passed else "DENY",
                                    "error": error[:1000]})

    # Simple deterministic function-role anchors in a candidate-only graph.
    # The topology database stays read-only and is hash-checked before/after.
    names = ["increment", *allowed_edges, "is_even", "bool_label"]
    names = list(dict.fromkeys(names))
    width = len(names)
    vectors = {name: tuple(1 if index == position else 0 for index in range(width))
               for position, name in enumerate(names)}
    gpu = TopologyIntegerRNN(width, width, scale_bits=0, state_limit=16, use_gpu=True)
    if gpu.backend != "cupy-int32":
        raise RuntimeError("GPU_BACKEND_UNAVAILABLE:" + gpu.backend)
    cpu = TopologyIntegerRNN(width, width, scale_bits=0, state_limit=16, use_gpu=False)
    identity = [[int(row == col) for col in range(width)] for row in range(width)]
    zero = [[0 for _ in range(width)] for _ in range(width)]
    gpu.set_weights(identity, zero)
    gpu_learning = gpu.learn_route([vectors[name] for name in training_route], reward=1)
    cpu.set_weights(gpu.weight_input, gpu.weight_hidden)

    gpu.reset()
    gpu.step(vectors["increment"])
    # A zero-input recurrent step applies W_h to the current state, producing
    # the next-edge prediction learned from verified transitions.
    hidden_gpu = gpu.step([0] * width)
    gpu_scores = [sum(hidden_gpu[i] * vectors[name][i] for i in range(width))
                  for name in allowed_edges]
    cpu.reset()
    cpu.step(vectors["increment"])
    hidden_cpu = cpu.step([0] * width)
    cpu_scores = [sum(hidden_cpu[i] * vectors[name][i] for i in range(width))
                  for name in allowed_edges]
    if gpu_scores != cpu_scores:
        raise AssertionError("GPU_CPU_EDGE_SCORE_MISMATCH")
    minimum = min(gpu_scores)
    masses = [max(1, score - minimum + 1) for score in gpu_scores]
    if len(masses) != len(allowed_edges) or any(mass <= 0 for mass in masses):
        raise AssertionError("INVALID_EDGE_PROBABILITY_MASS")

    # Proposal sampling remains probabilistic. The gate's ALLOW set is
    # deterministic, so a walk only commits a transition after membership in
    # that set is confirmed. Renormalize proposal mass across ALLOW edges and
    # retain the raw acceptance probability/expected rejection count.
    training_allowed = [row["edge"] for row in training_gate_rows if row["gate"] == "ALLOW"]
    held_out_allowed = [row["edge"] for row in candidate_gate_rows if row["gate"] == "ALLOW"]
    if not training_allowed or not held_out_allowed:
        raise RuntimeError("DETERMINISTIC_GATE_HAS_NO_ALLOWED_EDGE")
    mass_by_edge = dict(zip(allowed_edges, masses))

    def conditioned_distribution(accepted_edges: list[str]) -> dict:
        accepted_mass = sum(mass_by_edge[name] for name in accepted_edges)
        return {name: (mass_by_edge[name] / accepted_mass if name in accepted_edges else 0.0)
                for name in allowed_edges}

    training_conditioned = conditioned_distribution(training_allowed)
    held_out_conditioned = conditioned_distribution(held_out_allowed)
    raw_total_mass = sum(masses)
    training_raw_acceptance = sum(mass_by_edge[name] for name in training_allowed) / raw_total_mass
    held_out_raw_acceptance = sum(mass_by_edge[name] for name in held_out_allowed) / raw_total_mass

    weighted = draw(masses, DRAWS, SEED)
    weighted_repeat = draw(masses, DRAWS, SEED)
    uniform = draw([1] * len(allowed_edges), DRAWS, SEED)
    uniform_repeat = draw([1] * len(allowed_edges), DRAWS, SEED)
    if weighted != weighted_repeat or uniform != uniform_repeat:
        raise AssertionError("FIXED_SEED_SAMPLING_NOT_REPEATABLE")

    # Control: collapse int->int operations onto a shared typed anchor. This
    # tests whether the first result depended on one-hot identity memorization.
    type_vectors = {
        "increment": (1, 0, 0), "double": (1, 0, 0), "square": (1, 0, 0),
        "is_even": (0, 1, 0), "bool_label": (0, 0, 1),
    }
    type_gpu = TopologyIntegerRNN(3, 3, scale_bits=0, state_limit=16, use_gpu=True)
    if type_gpu.backend != "cupy-int32":
        raise RuntimeError("TYPE_CONTROL_GPU_BACKEND_UNAVAILABLE")
    type_cpu = TopologyIntegerRNN(3, 3, scale_bits=0, state_limit=16, use_gpu=False)
    type_identity = [[int(row == col) for col in range(3)] for row in range(3)]
    type_zero = [[0 for _ in range(3)] for _ in range(3)]
    type_gpu.set_weights(type_identity, type_zero)
    type_learning = type_gpu.learn_route([type_vectors[name] for name in training_route], reward=1)
    type_cpu.set_weights(type_gpu.weight_input, type_gpu.weight_hidden)
    type_gpu.reset()
    type_gpu.step(type_vectors["increment"])
    type_hidden_gpu = type_gpu.step([0, 0, 0])
    type_scores = [sum(type_hidden_gpu[i] * type_vectors[name][i] for i in range(3))
                   for name in allowed_edges]
    type_cpu.reset()
    type_cpu.step(type_vectors["increment"])
    type_hidden_cpu = type_cpu.step([0, 0, 0])
    type_cpu_scores = [sum(type_hidden_cpu[i] * type_vectors[name][i] for i in range(3))
                       for name in allowed_edges]
    if type_scores != type_cpu_scores or len(set(type_scores)) != 1:
        raise AssertionError("TYPE_ONLY_CONTROL_DID_NOT_COLLAPSE_INT_TO_INT_SCORES")
    type_masses = [1] * len(allowed_edges)
    type_weighted = draw(type_masses, DRAWS, SEED)
    type_uniform = draw([1] * len(allowed_edges), DRAWS, SEED)
    if type_weighted != type_uniform:
        raise AssertionError("TYPE_ONLY_CONTROL_DIVERGED_FROM_UNIFORM")

    def summarize(indices: list[int]) -> dict:
        counts = [indices.count(index) for index in range(len(allowed_edges))]
        accepted = sum(count for count, name in zip(counts, allowed_edges)
                       if correct_edge_by_gate[name])
        return {
            "counts_by_edge": dict(zip(allowed_edges, counts)),
            "empirical_probabilities": {name: count / DRAWS
                                         for name, count in zip(allowed_edges, counts)},
            "gate_accepted_draws": accepted,
            "gate_acceptance_rate": accepted / DRAWS,
        }

    topology_after = topology_sha256()
    if topology_before != topology_after:
        raise AssertionError("TOPOLOGY_CHANGED")
    payload = {
        "schema": "viv_candidate_python_edge_composition_probe_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_only": True,
        "curriculum_file": str(test_file),
        "curriculum_sha256": test_hash,
        "topology_sha256_before": topology_before,
        "topology_sha256_after": topology_after,
        "training_task": spec["training"]["id"],
        "training_route": training_route,
        "training_route_gate": "ALLOW",
        "held_out_task": spec["held_out"]["id"],
        "candidate_edge_set": allowed_edges,
        "edge_type_rule": "previous output type equals next input type; only int-to-int middle edges are candidates",
        "deterministic_walk_rule": "RNN proposes a typed edge; the deterministic Python gate must ALLOW the completed route before the edge is traversed; rejected proposals are discarded",
        "training_candidate_gate_results": training_gate_rows,
        "training_gate_allowed_edges": training_allowed,
        "candidate_gate_results": candidate_gate_rows,
        "rnn": {
            "backend": gpu.backend,
            "weights_sha256": gpu_learning.weights_sha256,
            "trained_transitions": gpu_learning.transitions,
            "integer_scores": gpu_scores,
            "cpu_gpu_equal": True,
            "edge_score_method": "score target against W_h-propagated hidden state after a zero-input recurrent step",
            "probability_rule": "positive integer mass = score - minimum score + 1",
            "selection_probabilities": {name: mass / sum(masses)
                                        for name, mass in zip(allowed_edges, masses)},
        },
        "type_only_control": {
            "backend": type_gpu.backend,
            "weights_sha256": type_learning.weights_sha256,
            "trained_transitions": type_learning.transitions,
            "integer_scores": type_scores,
            "cpu_gpu_equal": True,
            "selection_probabilities": {name: 1 / len(allowed_edges) for name in allowed_edges},
            "same_seed_sequence_as_uniform": True,
            "weighted": summarize(type_weighted),
        },
        "draws": DRAWS,
        "seed": SEED,
        "same_seed_reproduced": True,
        "weighted": summarize(weighted),
        "uniform_control": summarize(uniform),
        "deterministic_gate_conditioning": {
            "retrieval": {
                "allowed_edges": training_allowed,
                "raw_probability_mass_accepted_per_proposal": training_raw_acceptance,
                "expected_proposals_per_accepted_edge": 1 / training_raw_acceptance,
                "renormalized_selection_probabilities": training_conditioned,
                "deterministic_outcome": training_allowed[0] if len(training_allowed) == 1 else None,
            },
            "held_out_recombination": {
                "allowed_edges": held_out_allowed,
                "raw_probability_mass_accepted_per_proposal": held_out_raw_acceptance,
                "expected_proposals_per_accepted_edge": 1 / held_out_raw_acceptance,
                "renormalized_selection_probabilities": held_out_conditioned,
                "deterministic_outcome": held_out_allowed[0] if len(held_out_allowed) == 1 else None,
            },
            "structure_commits_only_after_gate_allow": True,
        },
        "promoted": False,
        "topology_write": False,
        "persistent_memory_write": False,
    }
    payload["receipt_sha256"] = canonical_sha256(payload)
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / f"python_edge_composition_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{uuid.uuid4().hex[:8]}.json"
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"receipt": str(target), "receipt_sha256": payload["receipt_sha256"],
                      "gate_results": candidate_gate_rows,
                      "weighted_acceptance": payload["weighted"]["gate_acceptance_rate"],
                      "uniform_acceptance": payload["uniform_control"]["gate_acceptance_rate"],
                      "gpu_scores": gpu_scores, "topology_unchanged": topology_before == topology_after,
                      "promoted": False}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
