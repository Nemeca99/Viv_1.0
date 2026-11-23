"""Numerical backend for the Rust -> Python -> NumPy -> Python -> Rust proof."""

from __future__ import annotations

import base64
import json
import math
from dataclasses import dataclass

import numpy as np


@dataclass
class TrainingState:
    seed: int
    x: np.ndarray
    y: np.ndarray
    weights: np.ndarray
    bias: np.ndarray
    rng_state_b64: str
    bit_generator: str
    initial_loss: float


def _loss_and_gradients(
    x: np.ndarray, y: np.ndarray, weights: np.ndarray, bias: np.ndarray
) -> tuple[float, np.ndarray, np.ndarray]:
    prediction = x @ weights + bias  # (samples, features) @ (features, 1)
    error = prediction - y
    loss = float(np.mean(error * error))
    weight_gradient = (2.0 / x.shape[0]) * (x.T @ error)
    bias_gradient = 2.0 * np.mean(error, axis=0, keepdims=True)
    return loss, weight_gradient, bias_gradient


def create_training_state(seed: int, samples: int = 96) -> TrainingState:
    """Build a seeded synthetic regression task using typed NumPy arrays."""
    if samples < 8:
        raise ValueError("samples must be at least 8")

    rng = np.random.default_rng(seed)
    x_source = rng.normal(0.0, 1.0, size=(samples, 2))
    true_weights = np.array([[1.5], [-2.0]], dtype=np.float64)
    true_bias = np.array([[0.35]], dtype=np.float64)
    y_source = x_source @ true_weights + true_bias  # bias broadcasts over rows

    permutation = rng.permutation(samples)
    x = x_source[permutation].astype(np.float64, copy=False)
    y = y_source[permutation].astype(np.float64, copy=False)
    weights = rng.normal(0.0, 0.5, size=(2, 1)).astype(np.float64, copy=False)
    bias = np.zeros((1, 1), dtype=np.float64)

    rng_state = json.dumps(
        rng.bit_generator.state, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    rng_state_b64 = base64.b64encode(rng_state).decode("ascii")
    bit_generator = type(rng.bit_generator).__name__
    initial_loss, _, _ = _loss_and_gradients(x, y, weights, bias)

    if x.shape != (samples, 2) or y.shape != (samples, 1):
        raise AssertionError("unexpected generated array shape")
    if x.dtype != np.float64 or y.dtype != np.float64 or weights.dtype != np.float64:
        raise AssertionError("unexpected generated array dtype")
    if not all(np.isfinite(a).all() for a in (x, y, weights, bias)):
        raise AssertionError("non-finite synthetic data")

    return TrainingState(
        seed=seed,
        x=x,
        y=y,
        weights=weights,
        bias=bias,
        rng_state_b64=rng_state_b64,
        bit_generator=bit_generator,
        initial_loss=initial_loss,
    )


def train_steps(
    state: TrainingState, steps: int, learning_rate: float
) -> tuple[float, float]:
    """Vectorized full-batch gradient descent; loops only over update steps."""
    if steps < 1:
        raise ValueError("steps must be positive")
    if not math.isfinite(learning_rate) or learning_rate <= 0.0:
        raise ValueError("learning_rate must be finite and positive")

    for _ in range(steps):
        _, weight_gradient, bias_gradient = _loss_and_gradients(
            state.x, state.y, state.weights, state.bias
        )
        state.weights -= learning_rate * weight_gradient
        state.bias -= learning_rate * bias_gradient

    loss, weight_gradient, bias_gradient = _loss_and_gradients(
        state.x, state.y, state.weights, state.bias
    )
    gradient_norm = float(
        np.sqrt(
            np.sum(weight_gradient * weight_gradient)
            + np.sum(bias_gradient * bias_gradient)
        )
    )
    if not math.isfinite(loss) or not math.isfinite(gradient_norm):
        raise FloatingPointError("training produced a non-finite result")
    return loss, gradient_norm


def array_contract_summary() -> dict[str, object]:
    """Small deterministic examples for shape, dtype, views, copies and axes."""
    base = np.arange(12, dtype=np.int32).reshape(3, 4)
    basic_slice = base[:, 1:3]
    advanced = base[:, [1, 3]]
    reshaped = base.reshape(2, 6)
    converted = base.astype(np.float64)
    row_bias = np.array([0.5, 1.5, 2.5, 3.5], dtype=np.float64)
    broadcast = base.astype(np.float64) + row_bias
    aggregate_axis0 = np.sum(base, axis=0)
    elementwise = np.multiply(np.array([[1.0, 2.0]]), np.array([[3.0], [4.0]]))
    matrix_product = np.array([[1.0, 2.0]]) @ np.array([[3.0], [4.0]])

    return {
        "base_shape": list(base.shape),
        "base_dtype": str(base.dtype),
        "astype_dtype": str(converted.dtype),
        "astype_is_copy": not np.shares_memory(base, converted),
        "slice_is_view": bool(np.shares_memory(base, basic_slice)),
        "advanced_index_is_copy": not np.shares_memory(base, advanced),
        "reshape_shares_memory": bool(np.shares_memory(base, reshaped)),
        "broadcast_shape": list(broadcast.shape),
        "axis0_sum": aggregate_axis0.tolist(),
        "elementwise_shape": list(elementwise.shape),
        "matrix_product": matrix_product.tolist(),
    }
