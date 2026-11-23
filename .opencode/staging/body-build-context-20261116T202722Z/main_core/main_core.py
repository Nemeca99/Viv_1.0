"""
main_core.py — Deterministic AIOS body kernel and authority gate for Viv's neural mind.
Discovers body cores, reports health, and holds mind runtime when required controls fail.
"""
from __future__ import annotations

import importlib.util
import importlib.machinery
import json
import logging
import math
import os
import pathlib
import sys
import time

# Path configurations
DEFAULT_WORKSPACE = pathlib.Path("L:/LocalCoder/workspace/aios_rebuild")


def _configured_workspace() -> pathlib.Path:
    return pathlib.Path(os.environ.get("AIOS_WORKSPACE_ROOT", str(DEFAULT_WORKSPACE)))


WORKSPACE = _configured_workspace()
sys.path.insert(0, str(WORKSPACE))


def _expected_core_names(workspace: pathlib.Path) -> list[str]:
    if not workspace.is_dir():
        return []
    return sorted(
        core_dir.name for core_dir in workspace.iterdir()
        if core_dir.is_dir()
        and core_dir.name.endswith("_core")
        and core_dir.name != "main_core"
        and (core_dir / f"{core_dir.name}.py").is_file()
    )

CORE_CLASS_ALIASES = {"support_core": "SupportSystem"}

from dream_core.dream_core import DreamCore  # noqa: E402
from main_core.body_resources import collect_body_resources  # noqa: E402
from main_core import body_runtime_client  # noqa: E402

_rust_authority = None

try:
    from viv_context_store import memory_store
except ImportError:
    memory_store = None


class UnifiedAIOSKernel:
    def __init__(self, *, memory_store_backend=None, dream_core=None):
        self.logger = self._setup_logger()
        self.running = True
        self.loaded_cores = {}
        self.health_map = {}
        self._last_activity_monotonic = time.monotonic()
        self._dream_had_activity = False

        self.logger.info("Initializing Unified AIOS Kernel Architecture...")
        self._bind_all_cores()
        # Reuse the dynamically bound Dream instance so health reporting and
        # heartbeat scheduling address the same stateful core.
        self.dream_core = (
            dream_core or self.loaded_cores.get("dream_core") or DreamCore()
        )
        self.memory_store = memory_store_backend if memory_store_backend is not None else memory_store

    def _setup_logger(self) -> logging.Logger:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] (Kernel) %(message)s")
        return logging.getLogger("AIOSKernel")

    def _bind_all_cores(self):
        """Discovers, imports, and instantiates every core module authored in workspace."""
        self.logger.info("Binding core modules from workspace...")
        if not WORKSPACE.exists():
            self.logger.error(f"Workspace directory {WORKSPACE} missing!")
            return

        for module_name in _expected_core_names(WORKSPACE):
            core_dir = WORKSPACE / module_name
            py_file = core_dir / f"{module_name}.py"
            try:
                try:
                    mod = importlib.import_module(f"{module_name}.{module_name}")
                except Exception:
                    spec = importlib.util.spec_from_file_location(module_name, py_file)
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)

                class_name = CORE_CLASS_ALIASES.get(
                    module_name,
                    "".join(word.capitalize() for word in module_name.split("_")),
                )
                if hasattr(mod, class_name):
                    cls = getattr(mod, class_name)
                    try:
                        if module_name == "support_core":
                            cache_dir = WORKSPACE / "data_core" / "FractalCache"
                            instance = cls(cache_dir=str(cache_dir))
                        else:
                            instance = cls()
                    except TypeError:
                        instance = cls({})
                    self.loaded_cores[module_name] = instance
                    self.logger.info(f"  [Bound] {module_name} -> {class_name}")
                else:
                    self.loaded_cores[module_name] = mod
                    self.logger.info(f"  [Bound Module] {module_name}")
            except Exception as exc:
                self.logger.error(f"  [Failed Core Bind] {module_name}: {exc}")

        expected_core_count = len(_expected_core_names(WORKSPACE))
        self.logger.info(
            f"Kernel binding complete. Total active cores: "
            f"{len(self.loaded_cores)}/{expected_core_count}"
        )

    def update_short_term_context(self, task: str, step: str, detail: str = ""):
        """Updates STM via central context store."""
        self.notify_activity()
        if self.memory_store is None:
            raise RuntimeError("short-term memory store is not configured")
        self.memory_store.update_short_term(task, step, detail)

    def archive_task_to_ltm(self, summary: str, tags: list[str] = None):
        """Archives completed task from STM to LTM."""
        self.notify_activity()
        if self.memory_store is None:
            raise RuntimeError("long-term memory store is not configured")
        self.memory_store.complete_task_and_migrate_to_ltm(summary, tags)

    def notify_activity(self) -> None:
        """Reset Dream's idle window when a user/task interaction begins."""
        self._last_activity_monotonic = time.monotonic()
        self._dream_had_activity = True

    def get_system_health(self) -> dict:
        """Collects live status reports from every bound core module."""
        health = {
            "kernel": "healthy",
            "active_cores_count": len(self.loaded_cores),
            "cores": {}
        }
        for core_name, instance in self.loaded_cores.items():
            try:
                if hasattr(instance, "get_health_status"):
                    health["cores"][core_name] = instance.get_health_status()
                elif hasattr(instance, "get_status"):
                    health["cores"][core_name] = instance.get_status()
                elif hasattr(instance, "health_check"):
                    health["cores"][core_name] = instance.health_check()
                elif hasattr(instance, "check_health"):
                    health["cores"][core_name] = instance.check_health()
                elif hasattr(instance, "get_system_status"):
                    health["cores"][core_name] = instance.get_system_status()
                elif hasattr(instance, "report_status"):
                    health["cores"][core_name] = instance.report_status()
                else:
                    health["cores"][core_name] = {
                        "status": "unverified",
                        "reason": "core_has_no_health_contract",
                    }
                report = health["cores"][core_name]
                if isinstance(report, str):
                    health["cores"][core_name] = {"status": report.casefold()}
                elif core_name == "game_core" and isinstance(report, dict):
                    alive = report.get("alive") is True
                    numeric_health = report.get("health")
                    healthy = (
                        alive
                        and isinstance(numeric_health, (int, float))
                        and not isinstance(numeric_health, bool)
                        and numeric_health > 0
                    )
                    health["cores"][core_name] = {
                        **report,
                        "status": "healthy" if healthy else "unhealthy",
                    }
            except Exception as e:
                health["cores"][core_name] = f"error: {e}"
        return health

    def get_mind_runtime_gate(self, requested_threads: int = 1, candidate_run_id: str | None = None) -> dict:
        """Ask the WSL Rust Body; mint a host-side one-use lease permit only after ALLOW."""
        request = {
            "body_resources": collect_body_resources(
                workspace_root=WORKSPACE.parent, requested_threads=requested_threads),
        }
        if candidate_run_id is not None:
            request["candidate_run_id"] = candidate_run_id
        try:
            verdict = body_runtime_client.authorize(request)
            if verdict.get("allowed") is not True:
                resources = request["body_resources"]
                memory = resources.get("gpu_memory_percent")
                verdict["resource_diagnostics"] = {
                    "gpu_memory_percent": memory,
                    "gpu_memory_state": ("unavailable_or_stale" if memory is None else
                                         "at_or_above_limit" if memory >= 95 else "below_limit"),
                    "sensor_age_seconds": resources.get("sensor_age_seconds"),
                    "sensor_source": resources.get("sensor_source"),
                }
            if verdict.get("allowed") is True and candidate_run_id is not None:
                ages = []
                for sample in request["body_resources"].get("thermal_samples", []):
                    age = sample.get("sensor_age_seconds")
                    if isinstance(age, (int, float)) and not isinstance(age, bool):
                        age = float(age)
                        if math.isfinite(age) and 0.0 <= age < 15.0:
                            ages.append(age)
                sensor_age = max(ages, default=float("nan"))
                authority = self._get_rust_body_authority()
                verdict["body_runtime_permit"] = authority.issue_body_runtime_permit(
                    float(verdict["stability_sn"]), sensor_age,
                    int(verdict["requested_threads"]), candidate_run_id,
                )
            return verdict
        except Exception as error:
            return {
                "schema": "aios_mind_runtime_gate_v1",
                "authority": "deterministic_aios_body_rust",
                "gate": "rust",
                "execution_boundary": "wsl_docker",
                "allowed": False,
                "disposition": "HOLD_MIND_RUNTIME",
                "reasons": [f"wsl_body_authority_or_permit_unavailable:{type(error).__name__}"],
                "expected_core_count": len(_expected_core_names(WORKSPACE)),
                "bound_core_count": 0,
                "active_without_health_report": [],
                "stability_sn": None,
                "minimum_stability_sn": 0.45,
            }

    @staticmethod
    def _get_rust_body_authority():
        """Load host Rust only for its process-bound one-use training permit API."""
        global _rust_authority
        if _rust_authority is not None:
            return _rust_authority
        library = WORKSPACE / "local_security_core" / "target" / "debug" / "security_core.dll"
        if not library.is_file():
            raise FileNotFoundError("Rust security_core extension is not built")
        loader = importlib.machinery.ExtensionFileLoader("security_core", str(library))
        spec = importlib.util.spec_from_file_location("security_core", library, loader=loader)
        if spec is None:
            raise ImportError("Rust security_core extension spec unavailable")
        module = importlib.util.module_from_spec(spec)
        previous = sys.modules.get("security_core")
        sys.modules["security_core"] = module
        try:
            loader.exec_module(module)
        finally:
            if previous is None:
                sys.modules.pop("security_core", None)
            else:
                sys.modules["security_core"] = previous
        _rust_authority = module
        return module

    def run_kernel_loop(self):
        """Heartbeat loop syncing core vitals and short-term memory state."""
        self.logger.info("AIOS Kernel Heartbeat running at 1Hz...")
        while self.running:
            try:
                # Refresh health map
                self.health_map = self.get_system_health()
                # At startup, consider the process idle only after its explicit
                # idle window. Task and STM ingress methods reset this timer.
                if self._dream_had_activity:
                    idle_for = time.monotonic() - self._last_activity_monotonic
                    busy = idle_for < self.dream_core.idle_seconds
                else:
                    busy = False
                try:
                    self.dream_core.tick(system_busy=busy)
                except Exception:
                    self.logger.exception("Dream heartbeat tick failed")
                time.sleep(1)
            except KeyboardInterrupt:
                self.logger.info("Kernel shutdown signal received.")
                self.running = False
                break

# Singleton Master Kernel Instance
kernel = UnifiedAIOSKernel()

if __name__ == "__main__":
    kernel.run_kernel_loop()
