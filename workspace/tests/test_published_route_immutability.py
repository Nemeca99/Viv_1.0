"""Published route graphs cannot be reopened for direct mutation."""

from pathlib import Path
import sys

import pytest

STANDALONE = Path(r"L:\Standalone\NN")
if str(STANDALONE) not in sys.path:
    sys.path.insert(0, str(STANDALONE))

from nn_local.steel_brain_store import SQLiteNeuronGraphStore


def test_published_route_rejects_writable_open(tmp_path):
    target = tmp_path / "neural_runs" / "language-routes-test" / "neuron_graph.sqlite3"
    with pytest.raises(PermissionError, match="immutable"):
        SQLiteNeuronGraphStore(target, readonly=False)
