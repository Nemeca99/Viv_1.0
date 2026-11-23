"""Explicit NumPy host <-> CuPy device computation for a bounded bridge proof."""

from __future__ import annotations

import time
from typing import Any

import cupy as cp
import numpy as np


def run(request: dict[str, Any]) -> dict[str, Any]:
    n = request["n"]
    if not isinstance(n, int) or not 1 <= n <= 64:
        raise ValueError("matrix width outside bounded proof")
    a = np.asarray(request["matrix_a"], dtype=np.float32)
    b = np.asarray(request["matrix_b"], dtype=np.float32)
    bias = np.asarray(request["bias"], dtype=np.float32)
    if a.shape != (n, n) or b.shape != (n, n) or bias.shape != (n,):
        raise ValueError("invalid NumPy input shapes")
    if not all(np.isfinite(value).all() for value in (a, b, bias)):
        raise ValueError("non-finite input")

    started = time.perf_counter()
    gpu_a = cp.asarray(a)
    gpu_b = cp.asarray(b)
    gpu_bias = cp.asarray(bias)
    cp.cuda.Stream.null.synchronize()
    uploaded = time.perf_counter()
    gpu_result = gpu_a @ gpu_b + gpu_bias
    cp.cuda.Stream.null.synchronize()
    computed = time.perf_counter()
    host_result = cp.asnumpy(gpu_result)
    cp.cuda.Stream.null.synchronize()
    downloaded = time.perf_counter()

    cpu_reference = a @ b + bias
    error = float(np.max(np.abs(host_result - cpu_reference)))
    properties = cp.cuda.runtime.getDeviceProperties(gpu_result.device.id)
    gpu_name = properties["name"]
    if isinstance(gpu_name, bytes):
        gpu_name = gpu_name.decode("utf-8")
    output = host_result.astype(np.float64).tolist()
    if request.get("inject_fault"):
        output[0][0] += 1.0
    return {
        "n": n,
        "dtype": str(host_result.dtype),
        "numpy_version": np.__version__,
        "cupy_version": cp.__version__,
        "host_type": f"{type(a).__module__}.{type(a).__name__}",
        "device_type": f"{type(gpu_result).__module__}.{type(gpu_result).__name__}",
        "device_id": gpu_result.device.id,
        "device_name": gpu_name,
        "max_cpu_gpu_error": error,
        "upload_ms": (uploaded - started) * 1000,
        "compute_ms": (computed - uploaded) * 1000,
        "download_ms": (downloaded - computed) * 1000,
        "output": output,
    }
