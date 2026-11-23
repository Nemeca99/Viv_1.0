"""Checks explicit host/device movement and independent result agreement."""

from __future__ import annotations

import unittest

from gpu_backend import run


class GpuBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = {
            "n": 2,
            "matrix_a": [[1.0, 2.0], [3.0, 4.0]],
            "matrix_b": [[5.0, 6.0], [7.0, 8.0]],
            "bias": [0.5, -0.5],
        }

    def test_numpy_to_cupy_and_back(self) -> None:
        result = run(self.request)
        self.assertEqual(result["host_type"], "numpy.ndarray")
        self.assertEqual(result["device_type"], "cupy.ndarray")
        self.assertEqual(result["device_id"], 0)
        self.assertEqual(result["dtype"], "float32")
        self.assertEqual(result["output"], [[19.5, 21.5], [43.5, 49.5]])
        self.assertLess(result["max_cpu_gpu_error"], 1e-5)

    def test_invalid_shape_is_rejected_before_gpu_work(self) -> None:
        self.request["bias"] = [1.0]
        with self.assertRaisesRegex(ValueError, "shapes"):
            run(self.request)


if __name__ == "__main__":
    unittest.main()
