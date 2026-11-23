"""Bounded integer recurrent core for topology-anchored sequence traversal.

This module is deliberately proposal-only. It does not read or mutate the
topology database and it cannot authorize a synapse or memory write. Callers
provide integer anchor vectors and receive an integer hidden state/score.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import ast
import json
import sqlite3
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

try:
    import cupy as cp
except Exception:  # pragma: no cover - CPU fallback is intentional.
    cp = None


@dataclass(frozen=True)
class IntegerRNNReceipt:
    steps: int
    hidden: tuple[int, ...]
    backend: str
    scale_bits: int


@dataclass(frozen=True)
class IntegerLearningReceipt:
    transitions: int
    reward: int
    changed_cells: int
    weights_sha256: str


@dataclass(frozen=True)
class HeldOutEvaluation:
    seen_score: int
    held_out_score: int
    negative_score: int
    passed: bool


@dataclass(frozen=True)
class TopologyAnchor:
    neuron_id: str
    vector: tuple[int, ...]


class TopologyIntegerRNN:
    """A fixed-point Elman-style recurrence over integer anchor vectors.

    The recurrence is:

        h_t = clip((W_x @ x_t + W_h @ h_(t-1)) >> scale_bits)

    We use int32 GPU operands and int64 host reference arithmetic. Clipping is
    explicit so overflow cannot silently become a learned route.
    """

    def __init__(
        self,
        input_size: int,
        hidden_size: int,
        *,
        scale_bits: int = 8,
        state_limit: int = 1_000_000,
        use_gpu: bool = True,
    ) -> None:
        if input_size < 1 or hidden_size < 1:
            raise ValueError("network dimensions must be positive")
        if not 0 <= scale_bits <= 20:
            raise ValueError("scale_bits outside bounded range")
        self.input_size = int(input_size)
        self.hidden_size = int(hidden_size)
        self.scale_bits = int(scale_bits)
        self.state_limit = int(state_limit)
        self.use_gpu = bool(use_gpu and cp is not None)
        self.backend = "cupy-int32" if self.use_gpu else "numpy-int64"
        self.weight_input = np.zeros((hidden_size, input_size), dtype=np.int32)
        self.weight_hidden = np.zeros((hidden_size, hidden_size), dtype=np.int32)
        self.hidden = np.zeros(hidden_size, dtype=np.int64)

    def _weights_digest(self) -> str:
        return hashlib.sha256(self.weight_input.tobytes() + self.weight_hidden.tobytes()).hexdigest()

    def save_candidate(self, path: str | Path, *, topology_sha256: str, receipt_ids: Sequence[str]) -> dict:
        """Persist an immutable candidate checkpoint; promotion is external."""
        target = Path(path)
        payload = {
            "format": "viv-topology-integer-rnn-candidate-v1",
            "input_size": self.input_size,
            "hidden_size": self.hidden_size,
            "scale_bits": self.scale_bits,
            "state_limit": self.state_limit,
            "topology_sha256": str(topology_sha256),
            "receipt_ids": list(receipt_ids),
            "weight_input": self.weight_input.astype(int).tolist(),
            "weight_hidden": self.weight_hidden.astype(int).tolist(),
            "weights_sha256": self._weights_digest(),
        }
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")
        temporary.replace(target)
        return {"path": str(target), "weights_sha256": payload["weights_sha256"], "receipt_ids": list(receipt_ids)}

    @classmethod
    def load_candidate(cls, path: str | Path, *, expected_topology_sha256: str | None = None) -> "TopologyIntegerRNN":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload.get("format") != "viv-topology-integer-rnn-candidate-v1":
            raise ValueError("unsupported candidate checkpoint format")
        if expected_topology_sha256 is not None and payload.get("topology_sha256") != expected_topology_sha256:
            raise ValueError("candidate topology hash mismatch")
        network = cls(
            int(payload["input_size"]), int(payload["hidden_size"]),
            scale_bits=int(payload["scale_bits"]), state_limit=int(payload["state_limit"]), use_gpu=True,
        )
        network.set_weights(payload["weight_input"], payload["weight_hidden"])
        if network._weights_digest() != payload.get("weights_sha256"):
            raise ValueError("candidate weight hash mismatch")
        return network

    def set_weights(self, weight_input: Sequence[Sequence[int]], weight_hidden: Sequence[Sequence[int]]) -> None:
        wi = np.asarray(weight_input, dtype=np.int32)
        wh = np.asarray(weight_hidden, dtype=np.int32)
        if wi.shape != self.weight_input.shape or wh.shape != self.weight_hidden.shape:
            raise ValueError("weight shape mismatch")
        self.weight_input[:] = wi
        self.weight_hidden[:] = wh

    def reset(self) -> None:
        self.hidden.fill(0)

    def _step_cpu(self, anchor: np.ndarray) -> np.ndarray:
        total = self.weight_input.astype(np.int64) @ anchor.astype(np.int64)
        total += self.weight_hidden.astype(np.int64) @ self.hidden
        return np.clip(total >> self.scale_bits, -self.state_limit, self.state_limit)

    def _step_gpu(self, anchor: np.ndarray) -> np.ndarray:
        gpu_wi = cp.asarray(self.weight_input)
        gpu_wh = cp.asarray(self.weight_hidden)
        gpu_x = cp.asarray(anchor.astype(np.int32))
        gpu_h = cp.asarray(self.hidden.astype(np.int32))
        total = cp.matmul(gpu_wi, gpu_x) + cp.matmul(gpu_wh, gpu_h)
        next_h = cp.clip(total >> self.scale_bits, -self.state_limit, self.state_limit)
        cp.cuda.Stream.null.synchronize()
        return cp.asnumpy(next_h).astype(np.int64)

    def step(self, anchor: Sequence[int]) -> tuple[int, ...]:
        vector = np.asarray(anchor, dtype=np.int32)
        if vector.shape != (self.input_size,):
            raise ValueError("anchor vector shape mismatch")
        self.hidden = self._step_gpu(vector) if self.use_gpu else self._step_cpu(vector)
        return tuple(int(value) for value in self.hidden)

    def traverse(self, anchors: Iterable[Sequence[int]]) -> IntegerRNNReceipt:
        count = 0
        for anchor in anchors:
            self.step(anchor)
            count += 1
        return IntegerRNNReceipt(count, tuple(int(value) for value in self.hidden), self.backend, self.scale_bits)

    def learn_route(self, anchors: Sequence[Sequence[int]], *, reward: int) -> IntegerLearningReceipt:
        """Apply bounded integer reinforcement to consecutive anchors in memory only."""
        if reward not in (-1, 1):
            raise ValueError("reward must be -1 or 1")
        vectors = [np.asarray(anchor, dtype=np.int64) for anchor in anchors]
        if len(vectors) < 2:
            return IntegerLearningReceipt(0, reward, 0, self._weights_digest())
        if any(vector.shape != (self.input_size,) for vector in vectors):
            raise ValueError("anchor vector shape mismatch")
        changed = 0
        width = min(self.hidden_size, self.input_size)
        for current, following in zip(vectors, vectors[1:]):
            delta = np.outer(following[:width], current[:width]) * reward
            before = self.weight_hidden[:width, :width].copy()
            updated = np.clip(
                before.astype(np.int64) + delta, -self.state_limit, self.state_limit
            ).astype(np.int32)
            self.weight_hidden[:width, :width] = updated
            changed += int(np.count_nonzero(updated != before))
        return IntegerLearningReceipt(len(vectors) - 1, reward, changed, self._weights_digest())

    def route_score(self, anchors: Sequence[Sequence[int]]) -> int:
        """Score learned transition compatibility using integer arithmetic only."""
        vectors = [np.asarray(anchor, dtype=np.int64) for anchor in anchors]
        if any(vector.shape != (self.input_size,) for vector in vectors):
            raise ValueError("anchor vector shape mismatch")
        width = min(self.hidden_size, self.input_size)
        score = 0
        weights = self.weight_hidden[:width, :width].astype(np.int64)
        for current, following in zip(vectors, vectors[1:]):
            predicted = weights @ current[:width]
            score += int(predicted @ following[:width])
        return score

    def evaluate_held_out(
        self,
        seen_route: Sequence[Sequence[int]],
        held_out_route: Sequence[Sequence[int]],
        negative_route: Sequence[Sequence[int]],
    ) -> HeldOutEvaluation:
        seen = self.route_score(seen_route)
        held_out = self.route_score(held_out_route)
        negative = self.route_score(negative_route)
        return HeldOutEvaluation(seen, held_out, negative, held_out > negative and seen > 0)

    def write_learning_receipt(
        self,
        path: str | Path,
        *,
        candidate_path: str | Path,
        topology_sha256: str,
        receipt_ids: Sequence[str],
        evaluation: HeldOutEvaluation,
        stability: dict | None = None,
    ) -> dict:
        """Write a complete candidate/evaluation receipt without promotion."""
        payload = {
            "schema": "viv-integer-rnn-learning-receipt-v1",
            "status": "PASS" if evaluation.passed else "HOLD",
            "candidate_path": str(candidate_path),
            "candidate_weights_sha256": self._weights_digest(),
            "topology_sha256": str(topology_sha256),
            "verified_receipt_ids": list(receipt_ids),
            "evaluation": {
                "seen_score": evaluation.seen_score,
                "held_out_score": evaluation.held_out_score,
                "negative_score": evaluation.negative_score,
                "held_out_margin": evaluation.held_out_score - evaluation.negative_score,
                "passed": evaluation.passed,
            },
            "stability": stability or {},
        }
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")
        temporary.replace(target)
        return payload


class ReadOnlyTopologyAnchors:
    """Deterministically projects verified SQLite neurons into integer anchors."""

    def __init__(self, database: str | Path, *, width: int = 2) -> None:
        if width < 1:
            raise ValueError("anchor width must be positive")
        self.database = Path(database)
        self.width = int(width)

    def _vector(self, row: tuple, degree: int) -> tuple[int, ...]:
        neuron_id, kind, symbol, scope, passes, digest, code_repr = row
        seed = f"{neuron_id}|{kind}|{symbol}|{scope}|{passes}|{digest}".encode()
        raw = hashlib.sha256(seed).digest()
        kind_code = {
            "IMPORT": 11,
            "VARIABLE": 23,
            "FUNCTION": 37,
            "ASSERTION": 53,
        }.get(str(kind).upper(), 71)
        try:
            tree = ast.parse(code_repr or "")
            calls = sum(isinstance(node, ast.Call) for node in ast.walk(tree))
            branches = sum(isinstance(node, (ast.If, ast.For, ast.While)) for node in ast.walk(tree))
            recursive = int(any(isinstance(node, ast.Call) and getattr(node.func, "id", "") == symbol for node in ast.walk(tree)))
            parameters = sum(len(node.args.args) for node in tree.body if isinstance(node, ast.FunctionDef))
        except (SyntaxError, TypeError):
            calls = branches = recursive = parameters = 0
        values = [
            kind_code,
            parameters,
            calls + branches,
            recursive,
            int(degree),
            int(scope or 0),
            int(passes or 0),
            int.from_bytes(raw[:4], "big", signed=False) % 97,
        ]
        return tuple(values[index % len(values)] for index in range(self.width))

    def load(self, neuron_ids: Sequence[str]) -> list[TopologyAnchor]:
        if not neuron_ids:
            return []
        placeholders = ",".join("?" for _ in neuron_ids)
        uri = f"file:{self.database.resolve().as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            rows = conn.execute(
                f"""SELECT neuron_id, kind, symbol_name, scope_depth, pass_count, sha256, code_repr
                    FROM viv_code_neurons WHERE neuron_id IN ({placeholders})""",
                tuple(neuron_ids),
            ).fetchall()
            degrees = dict(conn.execute(
                """SELECT source_id, COUNT(*) FROM viv_code_synapses
                   WHERE source_id IN ({}) GROUP BY source_id""".format(placeholders),
                tuple(neuron_ids),
            ).fetchall())
        by_id = {row[0]: TopologyAnchor(row[0], self._vector(row, degrees.get(row[0], 0))) for row in rows}
        missing = [neuron_id for neuron_id in neuron_ids if neuron_id not in by_id]
        if missing:
            raise KeyError(f"topology neurons not found: {missing}")
        return [by_id[neuron_id] for neuron_id in neuron_ids]


class VerifiedExecutionTeacher:
    """Turns graduated execution receipts into read-only positive route lessons."""

    def __init__(self, database: str | Path, *, anchor_width: int = 2) -> None:
        self.database = Path(database)
        self.anchors = ReadOnlyTopologyAnchors(database, width=anchor_width)

    def primitive_route(self, primitive_id: str) -> list[TopologyAnchor]:
        uri = f"file:{self.database.resolve().as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            row = conn.execute(
                """SELECT intent_description, verified_python_code, test_harness_code,
                          execution_status, pass_count
                   FROM verified_code_primitives WHERE primitive_id = ?""",
                (primitive_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"verified primitive not found: {primitive_id}")
        intent, code, harness, status, pass_count = row
        if status != "VERIFIED_GRADUATE" or int(pass_count or 0) < 1 or not harness:
            raise ValueError("primitive lacks a verified execution receipt")
        tree = ast.parse(code)
        names = [node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        if not names:
            raise ValueError("verified primitive contains no function route")
        ids = [f"neuron:func:{name}" for name in names]
        return self.anchors.load(ids)


__all__ = ["HeldOutEvaluation", "IntegerLearningReceipt", "IntegerRNNReceipt", "TopologyAnchor", "TopologyIntegerRNN", "ReadOnlyTopologyAnchors", "VerifiedExecutionTeacher"]
