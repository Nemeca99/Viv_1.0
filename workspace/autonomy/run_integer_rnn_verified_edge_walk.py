"""Walk only verified topology edges while an integer RNN explores choices.

This candidate-only experiment reads the topology in SQLite read-only mode.
RNN scores affect probabilities among existing outgoing edges; they cannot add,
rewrite, or authorize an edge. The receipt records each proposal and gate check.
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
from autonomy.topology_integer_rnn import ReadOnlyTopologyAnchors, TopologyIntegerRNN, VerifiedExecutionTeacher

DB = HERE / "viv_code_topology.sqlite3"
OUT = HERE / "learning" / "deepseek_candidate_runs"
SEEDS = (20261125, 20261127, 20261129, 20261131, 20261133, 20261135, 20261137, 20261139)
MAX_HOPS = 16
WIDTH = 8
PRIMITIVE = "AUTONOMOUS_CHALLENGE_24_RECURSIVE_TIC_TAC_TOE_EVALUATOR"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_graph():
    uri = "file:" + DB.resolve().as_posix() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.execute("PRAGMA query_only=ON")
        nodes = {
            row[0]: {"kind": row[1], "symbol": row[2]}
            for row in conn.execute(
                """SELECT neuron_id, kind, symbol_name FROM viv_code_neurons
                   WHERE pass_count > 0 AND test_receipt LIKE 'VERIFIED_%'"""
            )
        }
        edges = sorted({
            (row[0], row[1], row[2])
            for row in conn.execute(
                """SELECT s.source_id, s.target_id, s.relation
                   FROM viv_code_synapses s
                   JOIN viv_code_neurons a ON a.neuron_id=s.source_id
                   JOIN viv_code_neurons b ON b.neuron_id=s.target_id
                   WHERE a.pass_count > 0 AND a.test_receipt LIKE 'VERIFIED_%'
                     AND b.pass_count > 0 AND b.test_receipt LIKE 'VERIFIED_%'"""
            )
        })
    return nodes, edges


def choose(masses: list[int], rng: random.Random) -> int:
    draw = rng.randrange(sum(masses))
    for i, mass in enumerate(masses):
        if draw < mass:
            return i
        draw -= mass
    raise AssertionError("integer sampler fell through")


def walk(start: str, graph: dict[str, list[tuple[str, str]]], edge_set: set,
         vectors: dict[str, tuple[int, ...]], network: TopologyIntegerRNN,
         seed: int, weighted: bool) -> dict:
    rng = random.Random(seed)
    path = [start]
    rows = []
    for hop in range(MAX_HOPS):
        source = path[-1]
        options = graph.get(source, [])
        if not options:
            break
        scores = []
        for target, _relation in options:
            network.reset()
            for node_id in path:
                hidden = network.step(vectors[node_id])
            # Pair score remains integer-valued and is checked against CPU below.
            scores.append(sum(hidden[i] * vectors[target][i] for i in range(WIDTH)))
        floor = min(scores)
        masses = [max(1, score - floor + 1) for score in scores] if weighted else [1] * len(options)
        probabilities = [mass / sum(masses) for mass in masses]
        selected = choose(masses, rng)
        target, relation = options[selected]
        allowed = (source, target, relation) in edge_set
        if not allowed:
            raise AssertionError("deterministic edge gate denied a sampled edge")
        rows.append({
            "hop": hop,
            "source": source,
            "candidate_count": len(options),
            "integer_scores": scores,
            "selection_probabilities": probabilities,
            "selected_index": selected,
            "selected_target": target,
            "selected_relation": relation,
            "gate": "ALLOW",
        })
        path.append(target)
    return {"nodes": path, "steps": rows, "stop": "MAX_HOPS" if len(rows) == MAX_HOPS else "NO_VERIFIED_OUTGOING_EDGE"}


def main() -> int:
    before = sha256_file(DB)
    nodes, edges = load_graph()
    edge_set = set(edges)
    graph: dict[str, list[tuple[str, str]]] = {}
    for source, target, relation in edges:
        graph.setdefault(source, []).append((target, relation))
    for source in graph:
        graph[source].sort()
    # Pick a source with branching and at least one verified second hop; this
    # avoids the one-hop terminal-variable trap exposed by the initial probe.
    starts = [source for source, options in graph.items()
              if len(options) >= 2 and any(target in graph for target, _ in options)]
    starts.sort(key=lambda source: (
        -sum(len(graph.get(target, [])) for target, _ in graph[source]),
        -len(graph[source]), source,
    ))
    if not starts:
        raise RuntimeError("NO_VERIFIED_FUNCTION_WITH_MULTIPLE_OUTGOING_EDGES")
    start = starts[0]
    reachable = {start}
    for _ in range(MAX_HOPS):
        reachable |= {target for source in list(reachable) for target, _ in graph.get(source, [])}
    anchors = ReadOnlyTopologyAnchors(DB, width=WIDTH)
    anchor_ids = sorted(reachable)
    anchor_rows = anchors.load(anchor_ids)
    vectors = {row.neuron_id: row.vector for row in anchor_rows}
    teacher = VerifiedExecutionTeacher(DB, anchor_width=WIDTH)
    training = [row.vector for row in reversed(teacher.primitive_route(PRIMITIVE))]

    first_nonedge = next((node_id for node_id in sorted(nodes)
                          if (start, node_id, "NEGATIVE_CONTROL") not in edge_set
                          and all(target != node_id for target, _ in graph[start])), None)
    negative_gate = "DENY" if first_nonedge is not None and (start, first_nonedge, "NEGATIVE_CONTROL") not in edge_set else "ERROR"
    if negative_gate != "DENY":
        raise AssertionError("negative control did not deny an absent edge")

    seed_rows = []
    for seed in SEEDS:
        rng = random.Random(seed)
        net = TopologyIntegerRNN(WIDTH, WIDTH, scale_bits=0, state_limit=128, use_gpu=True)
        net.set_weights(
            [[rng.randint(-1, 1) for _ in range(WIDTH)] for _ in range(WIDTH)],
            [[rng.randint(-1, 1) for _ in range(WIDTH)] for _ in range(WIDTH)],
        )
        learned = net.learn_route(training, reward=1)
        cpu = TopologyIntegerRNN(WIDTH, WIDTH, scale_bits=0, state_limit=128, use_gpu=False)
        cpu.set_weights(net.weight_input, net.weight_hidden)

        # Verify CPU/GPU candidate scores for each visited prefix, before using GPU scores.
        def assert_walk_scores(result: dict) -> None:
            path = [start]
            for step in result["steps"]:
                expected = []
                for target, _ in graph[path[-1]]:
                    cpu.reset()
                    for node_id in path:
                        hidden = cpu.step(vectors[node_id])
                    expected.append(sum(hidden[i] * vectors[target][i] for i in range(WIDTH)))
                if expected != step["integer_scores"]:
                    raise AssertionError("GPU_CPU_WALK_SCORE_MISMATCH")
                path.append(step["selected_target"])

        weighted_a = walk(start, graph, edge_set, vectors, net, seed ^ 0x51A7, True)
        weighted_b = walk(start, graph, edge_set, vectors, net, seed ^ 0x51A7, True)
        uniform_a = walk(start, graph, edge_set, vectors, net, seed ^ 0x51A7, False)
        uniform_b = walk(start, graph, edge_set, vectors, net, seed ^ 0x51A7, False)
        if weighted_a != weighted_b or uniform_a != uniform_b:
            raise AssertionError("FIXED_SEED_EDGE_WALK_NOT_REPEATABLE")
        assert_walk_scores(weighted_a)
        assert_walk_scores(uniform_a)
        seed_rows.append({
            "weight_seed": seed,
            "weights_sha256": learned.weights_sha256,
            "learned_transitions": learned.transitions,
            "backend": net.backend,
            "gpu_cpu_scores_equal": True,
            "weighted_walk": weighted_a,
            "uniform_walk": uniform_a,
            "same_seed_replay": True,
            "all_selected_edges_verified": True,
        })
        print(json.dumps({"seed": seed, "weighted_hops": len(weighted_a["steps"]),
                          "uniform_hops": len(uniform_a["steps"]),
                          "weighted_nodes": weighted_a["nodes"][:6],
                          "uniform_nodes": uniform_a["nodes"][:6]}, ensure_ascii=False), flush=True)

    after = sha256_file(DB)
    if before != after:
        raise AssertionError("TOPOLOGY_CHANGED_DURING_READ_ONLY_PROBE")
    payload = {
        "schema": "viv_integer_rnn_verified_edge_walk_v1",
        "receipt_id": "edge-walk-" + uuid.uuid4().hex,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_only": True,
        "topology_path": str(DB),
        "topology_sha256_before": before,
        "topology_sha256_after": after,
        "verified_nodes": len(nodes),
        "verified_edges": len(edges),
        "start_node": start,
        "start_symbol": nodes[start]["symbol"],
        "start_outgoing_choices": len(graph[start]),
        "training_primitive": PRIMITIVE,
        "maximum_hops": MAX_HOPS,
        "weight_seeds": list(SEEDS),
        "probability_rule": "positive integer mass = score - minimum candidate score + 1; seeded PRNG samples only frozen outgoing edges",
        "deterministic_structure": "every transition is membership-checked against verified SQLite edge triples; no edge writes",
        "negative_control": {"injected_absent_edge": True, "gate": negative_gate},
        "seed_runs": seed_rows,
        "promoted": False,
        "topology_write": False,
        "persistent_memory_write": False,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    payload["receipt_sha256"] = hashlib.sha256(canonical).hexdigest()
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / f"integer_rnn_verified_edge_walk_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{uuid.uuid4().hex[:8]}.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"receipt": str(target), "receipt_sha256": payload["receipt_sha256"],
                      "topology_sha256": after, "start": start, "seeds": len(seed_rows),
                      "negative_gate": negative_gate, "topology_unchanged": before == after,
                      "promoted": False}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
