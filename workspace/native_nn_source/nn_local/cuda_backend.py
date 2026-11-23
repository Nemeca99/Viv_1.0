"""ctypes boundary for the custom fixed-point CUDA bucket DLL.

The public native boundary deliberately has no target-bearing argument.
"""

from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DLL = ROOT / "native" / "build" / "nn_bucket_cuda.dll"
CUDA_BIN_CANDIDATES = ()
HEPT_GUIDE_BIAS_MAX = 250_000
ACTIVATION_MAX_INPUT = 14_000_000


class CudaBucketError(RuntimeError):
    pass


class CudaRouteHold(CudaBucketError):
    pass


@dataclass(frozen=True)
class CudaAttempt:
    path: tuple[int, ...]
    strengths: tuple[int, ...]


@dataclass(frozen=True)
class CudaSnapshot:
    heads: tuple[int, ...]
    links: tuple[int, ...]
    uses: tuple[int, ...]
    pass_hits: tuple[int, ...]
    fail_hits: tuple[int, ...]
    link_pass_hits: tuple[int, ...]
    link_fail_hits: tuple[int, ...]


@dataclass(frozen=True)
class HeptAttempt:
    candidate: int
    reflector: int
    strengths: tuple[int, ...]


@dataclass(frozen=True)
class CpuGuideAttempt:
    candidate: int
    reflector: int
    strengths: tuple[int, ...]


@dataclass(frozen=True)
class ActivationProbe:
    inputs: tuple[int, ...]
    sigmoid: tuple[int, ...]
    tanh: tuple[int, ...]
    relu: tuple[int, ...]
    step: tuple[int, ...]


@dataclass(frozen=True)
class CellularTransition:
    active: tuple[int, ...]
    probabilities: tuple[int, ...]


@dataclass(frozen=True)
class CpuRecurrentGuide:
    previous_state: int
    route_activation: int
    next_state: int
    guide_bonus: int


@dataclass(frozen=True)
class HeptSnapshot:
    centers: tuple[int, ...]
    reflectors: tuple[int, ...]
    uses: tuple[int, ...]
    pass_hits: tuple[int, ...]
    fail_hits: tuple[int, ...]


@dataclass(frozen=True)
class GenerationSnapshot:
    keys: tuple[int, ...]
    semantic_signatures: tuple[int, ...]
    parent_slots: tuple[int, ...]
    weights: tuple[int, ...]


@dataclass(frozen=True)
class GenerationUsage:
    capacity: int
    count: int
    allocated_bytes: int


@dataclass(frozen=True)
class PrefixMemorySnapshot:
    keys: tuple[int, ...]
    semantic_signatures: tuple[int, ...]
    parent_keys: tuple[int, ...]
    weights: tuple[int, ...]
    multiplicities: tuple[int, ...]
    pass_hits: tuple[int, ...]
    fail_hits: tuple[int, ...]


@dataclass(frozen=True)
class PrefixMemoryUsage:
    capacity: int
    count: int


def _as_u32(values: Iterable[int], expected: int) -> ctypes.Array:
    data = tuple(int(value) for value in values)
    if len(data) != expected or any(not 0 <= value <= 0xFFFFFFFF for value in data):
        raise ValueError(f"expected {expected} uint32 values")
    return (ctypes.c_uint32 * expected)(*data)


def _as_u64(values: Iterable[int], expected: int) -> ctypes.Array:
    data = tuple(int(value) for value in values)
    if len(data) != expected or any(not 0 <= value <= 0xFFFFFFFFFFFFFFFF for value in data):
        raise ValueError(f"expected {expected} uint64 values")
    return (ctypes.c_uint64 * expected)(*data)


_GLOBAL_DLL_DIRECTORIES: list = []


def _ensure_cuda_dll_directories() -> None:
    global _GLOBAL_DLL_DIRECTORIES
    if _GLOBAL_DLL_DIRECTORIES:
        return
    if hasattr(os, "add_dll_directory"):
        for candidate in CUDA_BIN_CANDIDATES:
            if candidate.is_dir():
                try:
                    _GLOBAL_DLL_DIRECTORIES.append(os.add_dll_directory(str(candidate)))
                except OSError:
                    pass


class CudaLibrary:
    def __init__(self, path: str | Path = DEFAULT_DLL):
        dll_path = Path(path).resolve()
        if not dll_path.is_file():
            raise FileNotFoundError(dll_path)
        _ensure_cuda_dll_directories()
        self.path = dll_path
        self.dll = ctypes.CDLL(str(dll_path))
        self._bind()

    def _bind(self) -> None:
        dll = self.dll
        dll.nn_bucket_version.restype = ctypes.c_char_p
        dll.nn_bucket_last_error.restype = ctypes.c_char_p
        dll.nn_cuda_available.restype = ctypes.c_int
        dll.nn_profile_similarity.argtypes = (
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
        )
        dll.nn_profile_similarity.restype = ctypes.c_int
        dll.nn_activation_probe.argtypes = (
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_int32),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_int32),
            ctypes.POINTER(ctypes.c_int32),
            ctypes.POINTER(ctypes.c_uint32),
        )
        dll.nn_activation_probe.restype = ctypes.c_int
        dll.nn_cellular_transition.argtypes = (
            ctypes.c_uint32,
            ctypes.c_uint64,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
        )
        dll.nn_cellular_transition.restype = ctypes.c_int
        dll.nn_cpu_recurrent_guide.argtypes = (
            ctypes.c_int32,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_int32),
            ctypes.POINTER(ctypes.c_uint32),
        )
        dll.nn_cpu_recurrent_guide.restype = ctypes.c_int
        dll.nn_hept_cpu_guide.argtypes = (
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
        )
        dll.nn_hept_cpu_guide.restype = ctypes.c_int
        dll.nn_bucket_create.argtypes = (
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.c_uint64,
        )
        dll.nn_bucket_create.restype = ctypes.c_void_p
        dll.nn_bucket_load.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
        )
        dll.nn_bucket_load.restype = ctypes.c_int
        dll.nn_bucket_set_context_bias.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
        )
        dll.nn_bucket_set_context_bias.restype = ctypes.c_int
        dll.nn_bucket_attempt.argtypes = (
            ctypes.c_void_p,
            ctypes.c_uint64,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
        )
        dll.nn_bucket_attempt.restype = ctypes.c_int
        dll.nn_bucket_apply_verdict.argtypes = (ctypes.c_void_p, ctypes.c_int)
        dll.nn_bucket_apply_verdict.restype = ctypes.c_int
        dll.nn_bucket_export.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_uint64),
        )
        dll.nn_bucket_export.restype = ctypes.c_int
        dll.nn_bucket_export_link_hits.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_uint64),
        )
        dll.nn_bucket_export_link_hits.restype = ctypes.c_int
        dll.nn_bucket_destroy.argtypes = (ctypes.c_void_p,)
        dll.nn_bucket_destroy.restype = None
        dll.nn_hept_create.argtypes = (ctypes.c_uint32, ctypes.c_uint64)
        dll.nn_hept_create.restype = ctypes.c_void_p
        dll.nn_hept_load.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
        )
        dll.nn_hept_load.restype = ctypes.c_int
        dll.nn_hept_set_seed_state.argtypes = (ctypes.c_void_p, ctypes.c_uint64)
        dll.nn_hept_set_seed_state.restype = ctypes.c_int
        dll.nn_hept_set_guide_bias.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
        )
        dll.nn_hept_set_guide_bias.restype = ctypes.c_int
        dll.nn_hept_attempt.argtypes = (
            ctypes.c_void_p,
            ctypes.c_uint64,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
        )
        dll.nn_hept_attempt.restype = ctypes.c_int
        dll.nn_hept_apply_verdict.argtypes = (ctypes.c_void_p, ctypes.c_int)
        dll.nn_hept_apply_verdict.restype = ctypes.c_int
        dll.nn_hept_export.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_uint64),
        )
        dll.nn_hept_export.restype = ctypes.c_int
        dll.nn_hept_destroy.argtypes = (ctypes.c_void_p,)
        dll.nn_hept_destroy.restype = None
        dll.nn_cuda_memory_info.argtypes = (
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_uint64),
        )
        dll.nn_cuda_memory_info.restype = ctypes.c_int
        dll.nn_generation_create.argtypes = (
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint64,
        )
        dll.nn_generation_create.restype = ctypes.c_void_p
        dll.nn_generation_load.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.c_uint32,
        )
        dll.nn_generation_load.restype = ctypes.c_int
        dll.nn_generation_grow.argtypes = (
            ctypes.c_void_p,
            ctypes.c_uint64,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
        )
        dll.nn_generation_grow.restype = ctypes.c_int
        dll.nn_generation_export.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
        )
        dll.nn_generation_export.restype = ctypes.c_int
        dll.nn_generation_compact.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint64),
        )
        dll.nn_generation_compact.restype = ctypes.c_int
        dll.nn_generation_usage.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint64),
        )
        dll.nn_generation_usage.restype = ctypes.c_int
        dll.nn_generation_destroy.argtypes = (ctypes.c_void_p,)
        dll.nn_generation_destroy.restype = None
        dll.nn_prefix_memory_create.argtypes = (ctypes.c_uint32,)
        dll.nn_prefix_memory_create.restype = ctypes.c_void_p
        dll.nn_prefix_memory_append.argtypes = (
            ctypes.c_void_p,
            ctypes.c_uint64,
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.c_uint32,
        )
        dll.nn_prefix_memory_append.restype = ctypes.c_int
        dll.nn_prefix_memory_apply_verdict.argtypes = (
            ctypes.c_void_p,
            ctypes.c_uint64,
            ctypes.c_int,
        )
        dll.nn_prefix_memory_apply_verdict.restype = ctypes.c_int
        dll.nn_prefix_memory_compact.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
        )
        dll.nn_prefix_memory_compact.restype = ctypes.c_int
        dll.nn_prefix_memory_usage.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
        )
        dll.nn_prefix_memory_usage.restype = ctypes.c_int
        dll.nn_prefix_memory_export.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_uint32),
        )
        dll.nn_prefix_memory_export.restype = ctypes.c_int
        dll.nn_prefix_memory_destroy.argtypes = (ctypes.c_void_p,)
        dll.nn_prefix_memory_destroy.restype = None
        dll.nn_sqlite_shard_probe.argtypes = (
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_uint64),
        )
        dll.nn_sqlite_shard_probe.restype = ctypes.c_int
        dll.nn_steel_brain_store_probe.argtypes = (
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_uint64),
        )
        dll.nn_steel_brain_store_probe.restype = ctypes.c_int

    @property
    def version(self) -> str:
        return self.dll.nn_bucket_version().decode("ascii")

    @property
    def available(self) -> bool:
        return bool(self.dll.nn_cuda_available())

    def error(self) -> str:
        value = self.dll.nn_bucket_last_error()
        return value.decode("utf-8", errors="replace") if value else "unknown CUDA error"

    def profile_similarity(self, left: Iterable[int], right: Iterable[int]) -> int:
        left_values = tuple(int(value) for value in left)
        right_values = tuple(int(value) for value in right)
        if not left_values or len(left_values) != len(right_values):
            raise ValueError("profile vectors must have equal nonzero length")
        if any(value < 0 or value > 0xFFFFFFFFFFFFFFFF for value in left_values + right_values):
            raise ValueError("profile vectors must contain uint64 values")
        left_array = (ctypes.c_uint64 * len(left_values))(*left_values)
        right_array = (ctypes.c_uint64 * len(right_values))(*right_values)
        output = ctypes.c_uint32()
        if not self.dll.nn_profile_similarity(
            left_array, right_array, len(left_values), ctypes.byref(output)
        ):
            raise CudaBucketError(self.error())
        return int(output.value)

    def activation_probe(self, inputs: Iterable[int]) -> ActivationProbe:
        values = tuple(int(value) for value in inputs)
        if not 0 < len(values) <= 4096:
            raise ValueError("activation probe requires 1..4096 inputs")
        if any(
            not -ACTIVATION_MAX_INPUT <= value <= ACTIVATION_MAX_INPUT
            for value in values
        ):
            raise ValueError("activation probe input outside fixed-point -14..14")
        count = len(values)
        input_array = (ctypes.c_int32 * count)(*values)
        sigmoid = (ctypes.c_uint32 * count)()
        tanh = (ctypes.c_int32 * count)()
        relu = (ctypes.c_int32 * count)()
        step = (ctypes.c_uint32 * count)()
        if not self.dll.nn_activation_probe(
            count,
            input_array,
            sigmoid,
            tanh,
            relu,
            step,
        ):
            raise CudaBucketError(self.error())
        return ActivationProbe(
            inputs=values,
            sigmoid=tuple(int(sigmoid[index]) for index in range(count)),
            tanh=tuple(int(tanh[index]) for index in range(count)),
            relu=tuple(int(relu[index]) for index in range(count)),
            step=tuple(int(step[index]) for index in range(count)),
        )

    def cellular_transition(
        self,
        *,
        seed: int,
        generation: int,
        current_active: Iterable[int],
        support_strengths: Iterable[int],
        birth_probabilities: Iterable[int],
        survival_probabilities: Iterable[int],
        cpu_masks: Iterable[int],
    ) -> CellularTransition:
        active_values = tuple(int(value) for value in current_active)
        support_values = tuple(int(value) for value in support_strengths)
        birth_values = tuple(int(value) for value in birth_probabilities)
        survival_values = tuple(int(value) for value in survival_probabilities)
        mask_values = tuple(int(value) for value in cpu_masks)
        count = len(active_values)
        if not 0 < count <= 4_194_304 or any(
            len(values) != count
            for values in (support_values, birth_values, survival_values, mask_values)
        ):
            raise ValueError("cellular transition arrays must have equal bounded length")
        if any(value not in (0, 1) for value in active_values + mask_values):
            raise ValueError("cellular active and mask values must be binary")
        if any(
            not 0 <= value <= 1_000_000
            for values in (support_values, birth_values, survival_values)
            for value in values
        ):
            raise ValueError("cellular fixed-point probability outside bounds")
        active_array = (ctypes.c_uint32 * count)(*active_values)
        support_array = (ctypes.c_uint32 * count)(*support_values)
        birth_array = (ctypes.c_uint32 * count)(*birth_values)
        survival_array = (ctypes.c_uint32 * count)(*survival_values)
        mask_array = (ctypes.c_uint32 * count)(*mask_values)
        next_active = (ctypes.c_uint32 * count)()
        probabilities = (ctypes.c_uint32 * count)()
        if not self.dll.nn_cellular_transition(
            count,
            int(seed),
            int(generation),
            active_array,
            support_array,
            birth_array,
            survival_array,
            mask_array,
            next_active,
            probabilities,
        ):
            raise CudaBucketError(self.error())
        return CellularTransition(
            active=tuple(int(next_active[index]) for index in range(count)),
            probabilities=tuple(int(probabilities[index]) for index in range(count)),
        )

    def cpu_recurrent_guide(
        self,
        previous_state: int,
        route_activation: int,
    ) -> CpuRecurrentGuide:
        previous = int(previous_state)
        activation = int(route_activation)
        if not -1_000_000 <= previous <= 1_000_000:
            raise ValueError("CPU recurrent state outside signed fixed-point bounds")
        if not 0 <= activation <= 1_000_000:
            raise ValueError("CPU recurrent route activation outside fixed-point bounds")
        next_state = ctypes.c_int32()
        guide_bonus = ctypes.c_uint32()
        if not self.dll.nn_cpu_recurrent_guide(
            previous,
            activation,
            ctypes.byref(next_state),
            ctypes.byref(guide_bonus),
        ):
            raise CudaBucketError(self.error())
        return CpuRecurrentGuide(
            previous_state=previous,
            route_activation=activation,
            next_state=int(next_state.value),
            guide_bonus=int(guide_bonus.value),
        )

    def cpu_hept_guide(
        self,
        centers: Iterable[int],
        reflectors: Iterable[int],
        contexts: Iterable[int],
        truths: Iterable[int],
        multiplicities: Iterable[int],
        blocked: Iterable[int] | None = None,
    ) -> CpuGuideAttempt:
        center_values = tuple(int(value) for value in centers)
        candidates = len(center_values)
        if candidates == 0:
            raise ValueError("CPU Hept guide requires at least one candidate")
        center_array = _as_u32(center_values, candidates)
        reflector_array = _as_u32(reflectors, candidates * 6)
        context_array = _as_u32(contexts, candidates)
        truth_array = _as_u32(truths, candidates)
        multiplicity_array = _as_u32(multiplicities, candidates)
        blocked_array = _as_u32(
            (0 for _ in range(candidates)) if blocked is None else blocked,
            candidates,
        )
        selected = ctypes.c_uint32()
        reflector = ctypes.c_uint32()
        strengths = (ctypes.c_uint32 * candidates)()
        if not self.dll.nn_hept_cpu_guide(
            candidates,
            center_array,
            reflector_array,
            context_array,
            truth_array,
            multiplicity_array,
            blocked_array,
            ctypes.byref(selected),
            ctypes.byref(reflector),
            strengths,
        ):
            error = self.error()
            if error.startswith("HOLD_"):
                raise CudaRouteHold(error)
            raise CudaBucketError(error)
        return CpuGuideAttempt(
            candidate=int(selected.value),
            reflector=int(reflector.value),
            strengths=tuple(int(strengths[index]) for index in range(candidates)),
        )

    def memory_info(self) -> tuple[int, int]:
        free_bytes = ctypes.c_uint64()
        total_bytes = ctypes.c_uint64()
        if not self.dll.nn_cuda_memory_info(
            ctypes.byref(free_bytes), ctypes.byref(total_bytes)
        ):
            raise CudaBucketError(self.error())
        return int(free_bytes.value), int(total_bytes.value)

    def sqlite_shard_probe(self, path: str | Path) -> dict[str, int]:
        encoded = str(Path(path).resolve()).encode("utf-8")
        row_count = ctypes.c_uint64()
        weight_sum = ctypes.c_uint64()
        multiplicity_sum = ctypes.c_uint64()
        semantic_min = ctypes.c_uint64()
        semantic_max = ctypes.c_uint64()
        if not self.dll.nn_sqlite_shard_probe(
            encoded,
            ctypes.byref(row_count),
            ctypes.byref(weight_sum),
            ctypes.byref(multiplicity_sum),
            ctypes.byref(semantic_min),
            ctypes.byref(semantic_max),
        ):
            raise CudaBucketError(self.error())
        return {
            "row_count": int(row_count.value),
            "weight_sum": int(weight_sum.value),
            "multiplicity_sum": int(multiplicity_sum.value),
            "semantic_min": int(semantic_min.value),
            "semantic_max": int(semantic_max.value),
        }

    def steel_brain_store_probe(self, path: str | Path) -> dict[str, int]:
        encoded = str(Path(path).resolve()).encode("utf-8")
        token_count = ctypes.c_uint64()
        link_count = ctypes.c_uint64()
        resolved_link_count = ctypes.c_uint64()
        weight_sum = ctypes.c_uint64()
        token_min = ctypes.c_uint64()
        token_max = ctypes.c_uint64()
        event_count = ctypes.c_uint64()
        if not self.dll.nn_steel_brain_store_probe(
            encoded,
            ctypes.byref(token_count),
            ctypes.byref(link_count),
            ctypes.byref(resolved_link_count),
            ctypes.byref(weight_sum),
            ctypes.byref(token_min),
            ctypes.byref(token_max),
            ctypes.byref(event_count),
        ):
            raise CudaBucketError(self.error())
        return {
            "token_count": int(token_count.value),
            "link_count": int(link_count.value),
            "resolved_link_count": int(resolved_link_count.value),
            "weight_sum": int(weight_sum.value),
            "token_min": int(token_min.value),
            "token_max": int(token_max.value),
            "event_count": int(event_count.value),
        }


class CudaBucket:
    def __init__(
        self,
        library: CudaLibrary,
        *,
        positions: int,
        candidates: int,
        inventory: Iterable[int],
        seed_state: int,
        heads: Iterable[int] | None = None,
        links: Iterable[int] | None = None,
    ):
        self.library = library
        self.positions = int(positions)
        self.candidates = int(candidates)
        inventory_array = _as_u32(inventory, self.candidates)
        handle = library.dll.nn_bucket_create(
            self.positions,
            self.candidates,
            inventory_array,
            int(seed_state),
        )
        if not handle:
            raise CudaBucketError(library.error())
        self.handle = ctypes.c_void_p(handle)
        if heads is not None or links is not None:
            if heads is None or links is None:
                self.close()
                raise ValueError("heads and links must be loaded together")
            self.load(heads, links)

    def _check(self, result: int) -> None:
        if not result:
            raise CudaBucketError(self.library.error())

    def load(self, heads: Iterable[int], links: Iterable[int]) -> None:
        head_values = _as_u32(heads, self.positions * self.candidates)
        link_values = _as_u32(links, (self.candidates + 1) * self.candidates)
        self._check(self.library.dll.nn_bucket_load(self.handle, head_values, link_values))

    def set_context_bias(self, candidate_bias: Iterable[int]) -> None:
        values = _as_u32(candidate_bias, self.candidates)
        if any(value > 1_000_000 for value in values):
            raise ValueError("context bias outside fixed-point bounds")
        self._check(self.library.dll.nn_bucket_set_context_bias(self.handle, values))

    def attempt(self, seed: int) -> CudaAttempt:
        path = (ctypes.c_uint32 * self.positions)()
        strengths = (ctypes.c_uint32 * self.positions)()
        result = self.library.dll.nn_bucket_attempt(self.handle, int(seed), path, strengths)
        if not result:
            message = self.library.error()
            if "HOLD_NO_SUPPORTED_ROUTE" in message:
                raise CudaRouteHold(message)
            raise CudaBucketError(message)
        return CudaAttempt(tuple(path), tuple(strengths))

    def apply_verdict(self, passed: bool) -> None:
        self._check(self.library.dll.nn_bucket_apply_verdict(self.handle, int(bool(passed))))

    def snapshot(self) -> CudaSnapshot:
        head_cells = self.positions * self.candidates
        link_cells = (self.candidates + 1) * self.candidates
        heads = (ctypes.c_uint32 * head_cells)()
        links = (ctypes.c_uint32 * link_cells)()
        uses = (ctypes.c_uint64 * head_cells)()
        pass_hits = (ctypes.c_uint64 * head_cells)()
        fail_hits = (ctypes.c_uint64 * head_cells)()
        link_pass_hits = (ctypes.c_uint64 * link_cells)()
        link_fail_hits = (ctypes.c_uint64 * link_cells)()
        self._check(
            self.library.dll.nn_bucket_export(
                self.handle,
                heads,
                links,
                uses,
                pass_hits,
                fail_hits,
            )
        )
        self._check(
            self.library.dll.nn_bucket_export_link_hits(
                self.handle, link_pass_hits, link_fail_hits
            )
        )
        return CudaSnapshot(
            tuple(heads),
            tuple(links),
            tuple(uses),
            tuple(pass_hits),
            tuple(fail_hits),
            tuple(link_pass_hits),
            tuple(link_fail_hits),
        )

    def close(self) -> None:
        if getattr(self, "handle", None):
            self.library.dll.nn_bucket_destroy(self.handle)
            self.handle = None

    def __enter__(self) -> "CudaBucket":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()


class CudaHept:
    """One attractor with six learned reflector channels."""

    def __init__(
        self,
        library: CudaLibrary,
        *,
        candidates: int,
        seed_state: int,
        centers: Iterable[int] | None = None,
        reflectors: Iterable[int] | None = None,
        contexts: Iterable[int] | None = None,
        truths: Iterable[int] | None = None,
        multiplicities: Iterable[int] | None = None,
    ):
        self.library = library
        self.candidates = int(candidates)
        handle = library.dll.nn_hept_create(self.candidates, int(seed_state))
        if not handle:
            raise CudaBucketError(library.error())
        self.handle = ctypes.c_void_p(handle)
        supplied = (centers, reflectors, contexts, truths, multiplicities)
        if any(item is not None for item in supplied):
            if any(item is None for item in supplied):
                self.close()
                raise ValueError("all Hept state arrays must be supplied together")
            self.load(centers, reflectors, contexts, truths, multiplicities)

    def _check(self, result: int) -> None:
        if not result:
            raise CudaBucketError(self.library.error())

    def load(
        self,
        centers: Iterable[int],
        reflectors: Iterable[int],
        contexts: Iterable[int],
        truths: Iterable[int],
        multiplicities: Iterable[int],
    ) -> None:
        center_values = _as_u32(centers, self.candidates)
        reflector_values = _as_u32(reflectors, self.candidates * 6)
        context_values = _as_u32(contexts, self.candidates)
        truth_values = _as_u32(truths, self.candidates)
        multiplicity_values = _as_u32(multiplicities, self.candidates)
        if any(value > 1_000_000 for value in (*center_values, *reflector_values, *context_values, *truth_values)):
            raise ValueError("Hept fixed-point weight outside bounds")
        self._check(
            self.library.dll.nn_hept_load(
                self.handle,
                center_values,
                reflector_values,
                context_values,
                truth_values,
                multiplicity_values,
            )
        )

    def set_seed_state(self, seed_state: int) -> None:
        if not 0 <= int(seed_state) <= 0xFFFFFFFFFFFFFFFF:
            raise ValueError("Hept seed state must be uint64")
        self._check(
            self.library.dll.nn_hept_set_seed_state(self.handle, int(seed_state))
        )

    def set_guide_bias(self, guide_bias: Iterable[int]) -> None:
        """Set a bounded, target-free CPU prior for the next route attempt."""

        values = _as_u32(guide_bias, self.candidates)
        if any(value > HEPT_GUIDE_BIAS_MAX for value in values):
            raise ValueError("Hept guide bias exceeds the bounded fixed-point limit")
        self._check(self.library.dll.nn_hept_set_guide_bias(self.handle, values))

    def attempt(self, seed: int) -> HeptAttempt:
        candidate = ctypes.c_uint32()
        reflector = ctypes.c_uint32()
        strengths = (ctypes.c_uint32 * self.candidates)()
        result = self.library.dll.nn_hept_attempt(
            self.handle,
            int(seed),
            ctypes.byref(candidate),
            ctypes.byref(reflector),
            strengths,
        )
        if not result:
            message = self.library.error()
            if "HOLD_NO_SUPPORTED_HEPT_ROUTE" in message:
                raise CudaRouteHold(message)
            raise CudaBucketError(message)
        return HeptAttempt(int(candidate.value), int(reflector.value), tuple(strengths))

    def apply_verdict(self, passed: bool) -> None:
        self._check(self.library.dll.nn_hept_apply_verdict(self.handle, int(bool(passed))))

    def snapshot(self) -> HeptSnapshot:
        centers = (ctypes.c_uint32 * self.candidates)()
        reflectors = (ctypes.c_uint32 * (self.candidates * 6))()
        uses = (ctypes.c_uint64 * self.candidates)()
        pass_hits = (ctypes.c_uint64 * self.candidates)()
        fail_hits = (ctypes.c_uint64 * self.candidates)()
        self._check(
            self.library.dll.nn_hept_export(
                self.handle, centers, reflectors, uses, pass_hits, fail_hits
            )
        )
        return HeptSnapshot(
            tuple(centers), tuple(reflectors), tuple(uses), tuple(pass_hits), tuple(fail_hits)
        )

    def close(self) -> None:
        if getattr(self, "handle", None):
            self.library.dll.nn_hept_destroy(self.handle)
            self.handle = None

    def __enter__(self) -> "CudaHept":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()


class CudaGenerationWorkspace:
    """Contiguous Rust-owned CUDA workspace for generation-scale neurons."""

    def __init__(
        self,
        library: CudaLibrary,
        *,
        capacity: int,
        semantic_bins: int,
        seed_state: int,
    ):
        self.library = library
        self.capacity = int(capacity)
        self.semantic_bins = int(semantic_bins)
        handle = library.dll.nn_generation_create(
            self.capacity, self.semantic_bins, int(seed_state)
        )
        if not handle:
            raise CudaBucketError(library.error())
        self.handle = ctypes.c_void_p(handle)

    def _check(self, result: int) -> None:
        if not result:
            raise CudaBucketError(self.library.error())

    def load(
        self,
        keys: Iterable[int],
        semantic_signatures: Iterable[int],
        weights: Iterable[int],
    ) -> None:
        key_values = tuple(int(value) for value in keys)
        semantic_values = tuple(int(value) for value in semantic_signatures)
        weight_values = tuple(int(value) for value in weights)
        count = len(key_values)
        if not count or len(semantic_values) != count or len(weight_values) != count:
            raise ValueError("generation seed arrays must have equal nonzero length")
        if count > self.capacity:
            raise ValueError("generation seeds exceed workspace capacity")
        keys_array = _as_u64(key_values, count)
        semantics_array = _as_u64(semantic_values, count)
        weights_array = _as_u32(weight_values, count)
        if any(value > 1_000_000 for value in weight_values):
            raise ValueError("generation weight outside fixed-point bounds")
        self._check(
            self.library.dll.nn_generation_load(
                self.handle,
                keys_array,
                semantics_array,
                weights_array,
                count,
            )
        )

    def grow(self, *, seed: int, requested: int) -> tuple[int, int]:
        count_after = ctypes.c_uint32()
        grew = ctypes.c_uint32()
        self._check(
            self.library.dll.nn_generation_grow(
                self.handle,
                int(seed),
                int(requested),
                ctypes.byref(count_after),
                ctypes.byref(grew),
            )
        )
        return int(count_after.value), int(grew.value)

    def usage(self) -> GenerationUsage:
        capacity = ctypes.c_uint32()
        count = ctypes.c_uint32()
        allocated_bytes = ctypes.c_uint64()
        self._check(
            self.library.dll.nn_generation_usage(
                self.handle,
                ctypes.byref(capacity),
                ctypes.byref(count),
                ctypes.byref(allocated_bytes),
            )
        )
        return GenerationUsage(
            int(capacity.value), int(count.value), int(allocated_bytes.value)
        )

    def compact(self) -> tuple[int, int, int]:
        count_before = ctypes.c_uint32()
        count_after = ctypes.c_uint32()
        last_key = ctypes.c_uint64()
        self._check(
            self.library.dll.nn_generation_compact(
                self.handle,
                ctypes.byref(count_before),
                ctypes.byref(count_after),
                ctypes.byref(last_key),
            )
        )
        return int(count_before.value), int(count_after.value), int(last_key.value)

    def snapshot(self) -> GenerationSnapshot:
        keys = (ctypes.c_uint64 * self.capacity)()
        semantics = (ctypes.c_uint64 * self.capacity)()
        parents = (ctypes.c_uint32 * self.capacity)()
        weights = (ctypes.c_uint32 * self.capacity)()
        count = ctypes.c_uint32()
        self._check(
            self.library.dll.nn_generation_export(
                self.handle,
                keys,
                semantics,
                parents,
                weights,
                ctypes.byref(count),
            )
        )
        size = int(count.value)
        return GenerationSnapshot(
            tuple(keys[:size]),
            tuple(semantics[:size]),
            tuple(parents[:size]),
            tuple(weights[:size]),
        )

    def close(self) -> None:
        if getattr(self, "handle", None):
            self.library.dll.nn_generation_destroy(self.handle)
            self.handle = None

    def __enter__(self) -> "CudaGenerationWorkspace":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()


class PrefixMemory:
    """Rust-owned, target-free memory for model-generated sentence prefixes."""

    def __init__(self, library: CudaLibrary, *, capacity: int):
        self.library = library
        self.capacity = int(capacity)
        self.handle = library.dll.nn_prefix_memory_create(self.capacity)
        if not self.handle:
            raise CudaBucketError(self.library.error())

    def _check(self, result: int) -> None:
        if not result:
            raise CudaBucketError(self.library.error())

    def append(
        self,
        *,
        attempt_id: int,
        keys: Iterable[int],
        semantic_signatures: Iterable[int],
        parent_keys: Iterable[int],
        weights: Iterable[int],
    ) -> None:
        key_values = tuple(int(value) for value in keys)
        semantic_values = tuple(int(value) for value in semantic_signatures)
        parent_values = tuple(int(value) for value in parent_keys)
        weight_values = tuple(int(value) for value in weights)
        count = len(key_values)
        if not count:
            raise ValueError("prefix append requires at least one generated neuron")
        self._check(
            self.library.dll.nn_prefix_memory_append(
                self.handle,
                int(attempt_id),
                _as_u64(key_values, count),
                _as_u64(semantic_values, count),
                _as_u64(parent_values, count),
                _as_u32(weight_values, count),
                count,
            )
        )

    def apply_verdict(self, *, attempt_id: int, passed: bool) -> None:
        self._check(
            self.library.dll.nn_prefix_memory_apply_verdict(
                self.handle, int(attempt_id), int(bool(passed))
            )
        )

    def compact(self) -> tuple[int, int]:
        before = ctypes.c_uint32()
        after = ctypes.c_uint32()
        self._check(
            self.library.dll.nn_prefix_memory_compact(
                self.handle, ctypes.byref(before), ctypes.byref(after)
            )
        )
        return int(before.value), int(after.value)

    def usage(self) -> PrefixMemoryUsage:
        capacity = ctypes.c_uint32()
        count = ctypes.c_uint32()
        self._check(
            self.library.dll.nn_prefix_memory_usage(
                self.handle, ctypes.byref(capacity), ctypes.byref(count)
            )
        )
        return PrefixMemoryUsage(int(capacity.value), int(count.value))

    def snapshot(self) -> PrefixMemorySnapshot:
        size = self.capacity
        keys = (ctypes.c_uint64 * size)()
        semantics = (ctypes.c_uint64 * size)()
        parents = (ctypes.c_uint64 * size)()
        weights = (ctypes.c_uint32 * size)()
        multiplicities = (ctypes.c_uint32 * size)()
        pass_hits = (ctypes.c_uint64 * size)()
        fail_hits = (ctypes.c_uint64 * size)()
        count = ctypes.c_uint32()
        self._check(
            self.library.dll.nn_prefix_memory_export(
                self.handle,
                keys,
                semantics,
                parents,
                weights,
                multiplicities,
                pass_hits,
                fail_hits,
                ctypes.byref(count),
            )
        )
        used = int(count.value)
        return PrefixMemorySnapshot(
            tuple(keys[:used]),
            tuple(semantics[:used]),
            tuple(parents[:used]),
            tuple(weights[:used]),
            tuple(multiplicities[:used]),
            tuple(pass_hits[:used]),
            tuple(fail_hits[:used]),
        )

    def close(self) -> None:
        if getattr(self, "handle", None):
            self.library.dll.nn_prefix_memory_destroy(self.handle)
            self.handle = None

    def __enter__(self) -> "PrefixMemory":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()


__all__ = [
    "ACTIVATION_MAX_INPUT",
    "ActivationProbe",
    "CpuGuideAttempt",
    "CpuRecurrentGuide",
    "CudaAttempt",
    "CudaBucket",
    "CudaBucketError",
    "CudaRouteHold",
    "CudaLibrary",
    "CudaSnapshot",
    "DEFAULT_DLL",
    "CudaHept",
    "HEPT_GUIDE_BIAS_MAX",
    "CudaGenerationWorkspace",
    "GenerationSnapshot",
    "GenerationUsage",
    "HeptAttempt",
    "HeptSnapshot",
    "PrefixMemory",
    "PrefixMemorySnapshot",
    "PrefixMemoryUsage",
]
