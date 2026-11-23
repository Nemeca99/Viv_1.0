"""Read-only structural measurements of a verified route snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from autonomy.terminal_neuron_learning import latest_verified_run, verify_run


def measure(run: Path) -> dict:
    run = Path(run)
    receipt = verify_run(run)
    graph = run / "neuron_graph.sqlite3"
    connection = sqlite3.connect(graph.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        nodes = {row[0] for row in connection.execute("SELECT neuron_id FROM neurons")}
        parent = {node: node for node in nodes}
        size = {node: 1 for node in nodes}
        active = set()

        def root(node):
            while parent[node] != node:
                parent[node] = parent[parent[node]]
                node = parent[node]
            return node

        edges = 0
        valid_edges = 0
        for source, peer in connection.execute("SELECT source_id, peer_id FROM links"):
            edges += 1
            if source not in nodes or peer not in nodes:
                continue
            valid_edges += 1
            active.update((source, peer))
            left, right = root(source), root(peer)
            if left != right:
                if size[left] < size[right]:
                    left, right = right, left
                parent[right] = left
                size[left] += size[right]
        largest = max(size.values(), default=0)
        components = sum(1 for node in nodes if parent[node] == node)
        return {
            "run": run.name,
            "parent_run": Path(receipt["parent_run"]).name if receipt.get("parent_run") else None,
            "snapshot_verified": True,
            "neurons": len(nodes),
            "edges": edges,
            "edge_to_neuron_ratio": round(edges / len(nodes), 6) if nodes else None,
            "edges_with_existing_peers": valid_edges,
            "active_nodes": len(active),
            "weak_components": components,
            "largest_weak_component": largest,
        }
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("runs", nargs="*", type=Path)
    args = parser.parse_args()
    runs = args.runs or [latest_verified_run()]
    if any(run is None for run in runs):
        raise RuntimeError("No verified route snapshot available")
    print(json.dumps([measure(run) for run in runs], indent=2))


if __name__ == "__main__":
    main()
