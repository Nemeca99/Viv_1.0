"""Integration checks for whole-kernel binding and Dream heartbeat routing."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

AIOS_REBUILD = Path(__file__).resolve().parent
MAIN_CORE = AIOS_REBUILD / "main_core" / "main_core.py"
EXPECTED_CORES = {
    "backup_core",
    "carma_core",
    "consciousness_core",
    "data_core",
    "dream_core",
    "fractal_core",
    "game_core",
    "infra_core",
    "luna_core",
    "privacy_core",
    "rag_core",
    "security_core",
    "utils_core",
}


def load_main_core():
    spec = importlib.util.spec_from_file_location(
        "aios_main_core_integration", MAIN_CORE
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load kernel module: {MAIN_CORE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DreamProbe:
    idle_seconds = 300

    def __init__(self) -> None:
        self.busy_samples: list[bool] = []

    def tick(self, *, system_busy: bool) -> None:
        self.busy_samples.append(system_busy)


def test_kernel_binds_all_thirteen_cores():
    module = load_main_core()
    kernel = module.UnifiedAIOSKernel(dream_core=DreamProbe())
    assert set(kernel.loaded_cores) == EXPECTED_CORES


def test_heartbeat_passes_busy_state_to_the_same_dream_instance():
    module = load_main_core()
    dream = DreamProbe()
    kernel = module.UnifiedAIOSKernel(dream_core=dream)
    kernel.notify_activity()

    def finish_after_one_tick(_seconds: float) -> None:
        kernel.running = False

    with patch.object(module.time, "sleep", side_effect=finish_after_one_tick):
        kernel.run_kernel_loop()

    assert dream.busy_samples == [True]
    assert kernel.health_map["active_cores_count"] == 13
