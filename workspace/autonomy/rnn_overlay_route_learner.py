"""Route-proposal bridge: integer RNN proposes, containment retires or flushes."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from deterministic_containment import CONTAINED, ContainmentEngine, SQLiteOverlayCartridge
from live_learning_cycle import OVERLAY, SOURCE, make_overlay, digest
from topology_integer_rnn import TopologyIntegerRNN


OUT = Path(r"L:\LocalCoder\workspace\autonomy\.tmp\rnn_overlay_route_receipt.json")
CANDIDATE = Path(r"L:\LocalCoder\workspace\autonomy\.tmp\rnn_overlay_route_candidate.json")


def anchor(text: str) -> tuple[int, int]:
    raw = hashlib.sha256(text.encode()).digest()
    return (int(raw[0]) - 128, int(raw[1]) - 128)


def reload_candidate() -> None:
    model = TopologyIntegerRNN.load_candidate(CANDIDATE, expected_topology_sha256=digest(SOURCE))
    print(json.dumps({"reload": "PASS", "weights_sha256": model._weights_digest()}))


def main() -> None:
    if "--reload" in sys.argv:
        reload_candidate()
        return
    make_overlay()
    engine = ContainmentEngine([SQLiteOverlayCartridge("overlay", OVERLAY, source_path=SOURCE)])
    model = TopologyIntegerRNN(2, 2, use_gpu=True)
    routes = []
    for query in ("Rayleigh scattering", "The sky is green"):
        result = engine.query(query)
        route = [anchor(item) for item in result.trace[:2]] or [anchor(query)]
        model.reset()
        proposal = model.traverse(route)
        accepted = result.state == CONTAINED
        learning = model.learn_route(route, reward=1 if accepted else -1)
        routes.append({"query": query, "state": result.state, "gate": "ALLOW" if accepted else "DENY", "proposal_steps": proposal.steps, "flushed": not accepted, "credit_reward": learning.reward, "changed_cells": learning.changed_cells})
    model.save_candidate(CANDIDATE, topology_sha256=digest(SOURCE), receipt_ids=["rnn-route-allow", "rnn-route-deny"])
    child = subprocess.run([sys.executable, __file__, "--reload"], capture_output=True, text=True, check=True)
    receipt = {"schema": "viv-rnn-overlay-route-receipt-v1", "status": "PASS", "source_read_only": True, "routes": routes, "candidate": str(CANDIDATE), "candidate_sha256": model._weights_digest(), "reload": json.loads(child.stdout)}
    OUT.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
