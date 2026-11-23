"""Read-only Game-of-Life projection over a verified Viv snapshot."""
from __future__ import annotations

import glob
import os
import sqlite3
from collections import Counter
from pathlib import Path


def simulate(snapshot: str | None = None, *, width: int = 32, height: int = 32, seed_count: int = 27, generations: int = 10) -> dict:
    runs = glob.glob(r"L:/LocalCoder/workspace/autonomy/learning/neural_runs/language-routes-*/neuron_graph.sqlite3")
    path = Path(snapshot or max(runs, key=os.path.getmtime))
    limit = width * height
    with sqlite3.connect(path) as con:
        active = {r[0] for r in con.execute("SELECT neuron_id FROM neurons WHERE lifecycle IN ('STABLE','PLASTIC')")}
        degree = Counter()
        for src, peer, weight in con.execute("SELECT source_id,peer_id,weight FROM links WHERE hot=1 ORDER BY weight DESC"):
            degree[src] += int(weight)
            degree[peer] += int(weight)
    selected = [node for node, _ in sorted(degree.items(), key=lambda item: (-item[1], item[0]))[:limit]]
    cells = {(idx % width, idx // width): node for idx, node in enumerate(selected)}
    # Simulation seed: the alphabet lattice plus SHIFT, represented by the
    # first 27 verified projected nodes. Persistent lifecycle is not mutated.
    live = set(list(cells)[:seed_count])
    neighbors = lambda x, y: [(x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx or dy)]
    counts = Counter(n for cell in live for n in neighbors(*cell) if n in cells)
    history = []
    next_live = live
    for _ in range(generations):
        counts = Counter(n for cell in next_live for n in neighbors(*cell) if n in cells)
        born = {cell for cell, count in counts.items() if cell not in next_live and count == 3}
        survived = {cell for cell in next_live if counts[cell] in (2, 3)}
        history.append({"active": len(next_live), "births": len(born), "deactivations": len(next_live - survived)})
        next_live = survived | born
    return {
        "snapshot": path.parent.name,
        "grid": [width, height],
        "projected_nodes": len(cells),
        "initial_active": len(live),
        "seed_count": seed_count,
        "generations": generations,
        "history": history,
        "next_active": len(next_live),
    }


if __name__ == "__main__":
    print(simulate())
