from __future__ import annotations

import base64
import json
import unittest

import numpy as np

from numpy_backend import array_contract_summary, create_training_state, train_steps


class NumpyBackendTests(unittest.TestCase):
    def test_array_shape_dtype_indexing_and_memory_semantics(self) -> None:
        result = array_contract_summary()
        self.assertEqual(result["base_shape"], [3, 4])
        self.assertEqual(result["base_dtype"], "int32")
        self.assertEqual(result["astype_dtype"], "float64")
        self.assertTrue(result["astype_is_copy"])
        self.assertTrue(result["slice_is_view"])
        self.assertTrue(result["advanced_index_is_copy"])
        self.assertTrue(result["reshape_shares_memory"])
        self.assertEqual(result["broadcast_shape"], [3, 4])
        self.assertEqual(result["axis0_sum"], [12, 15, 18, 21])
        self.assertEqual(result["elementwise_shape"], [2, 2])
        self.assertEqual(result["matrix_product"], [[11.0]])

    def test_vectorization_broadcasting_and_axis_aggregation(self) -> None:
        values = np.arange(12, dtype=np.float64).reshape(3, 4)
        column_bias = np.array([0.5, 1.5, 2.5, 3.5], dtype=np.float64)
        vectorized = values * 2.0 + column_bias
        loop_result = np.array(
            [
                [values[row, column] * 2.0 + column_bias[column] for column in range(4)]
                for row in range(3)
            ],
            dtype=np.float64,
        )
        np.testing.assert_array_equal(vectorized, loop_result)
        np.testing.assert_array_equal(np.sum(values, axis=0), [12, 15, 18, 21])
        np.testing.assert_array_equal(np.max(values, axis=1), [3, 7, 11])
        self.assertEqual(vectorized.shape, (3, 4))

    def test_seeded_synthetic_arrays_replay_and_retain_rng_state(self) -> None:
        first = create_training_state(0xA105, samples=96)
        replay = create_training_state(0xA105, samples=96)
        different = create_training_state(0xA106, samples=96)

        self.assertIsInstance(first.x, np.ndarray)
        self.assertEqual(first.x.shape, (96, 2))
        self.assertEqual(first.y.shape, (96, 1))
        self.assertEqual(first.x.dtype, np.dtype(np.float64))
        np.testing.assert_array_equal(first.x, replay.x)
        np.testing.assert_array_equal(first.y, replay.y)
        self.assertFalse(np.array_equal(first.x, different.x))
        state = json.loads(base64.b64decode(first.rng_state_b64).decode("utf-8"))
        self.assertEqual(state["bit_generator"], "PCG64")
        self.assertEqual(first.bit_generator, "PCG64")

        rng_a = np.random.default_rng(0xC0FFEE)
        rng_b = np.random.default_rng(0xC0FFEE)
        sample_a = rng_a.choice(first.x.shape[0], size=16, replace=False)
        sample_b = rng_b.choice(first.x.shape[0], size=16, replace=False)
        np.testing.assert_array_equal(sample_a, sample_b)

    def test_vectorized_gradient_updates_reduce_loss_and_gradient(self) -> None:
        state = create_training_state(0xBEEF, samples=96)
        loss_after_forward, gradient_after_forward = train_steps(state, 120, 0.04)
        loss_after_feedback, gradient_after_feedback = train_steps(state, 240, 0.04)

        self.assertLess(loss_after_forward, state.initial_loss)
        self.assertLess(loss_after_feedback, loss_after_forward)
        self.assertLess(gradient_after_feedback, gradient_after_forward)
        self.assertTrue(np.isfinite(state.weights).all())
        self.assertTrue(np.isfinite(state.bias).all())


if __name__ == "__main__":
    unittest.main()
