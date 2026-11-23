"""Read-only utility advertisements for grounded route selection.

The graph proposes route utility from persisted edge evidence.  This module
does not mutate the graph and does not create vocabulary or conversational
responses.
"""

from __future__ import annotations

import sqlite3
import math
from pathlib import Path
from typing import Any, Iterable


_SHARED_WORD_INDEX_CACHE: dict[tuple[str, float, int], dict[str, str]] = {}


class UtilityAdvertiser:
    """Score candidate routes from the current verified SQLite topology."""

    def __init__(self, graph_path: Path | str | None = None) -> None:
        self.graph_path = Path(graph_path) if graph_path else None
        self._connection: sqlite3.Connection | None = None
        self._legacy_store = None
        self._word_index: dict[str, str] = {}
        self._unavailable_reason = "VERIFIED_GRAPH_UNAVAILABLE"
        self.refresh()

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        if self._legacy_store is not None:
            self._legacy_store.close()
            self._legacy_store = None
        self._word_index = {}

    def refresh(self, graph_path: Path | str | None = None) -> None:
        if graph_path is not None:
            self.graph_path = Path(graph_path)
        elif self.graph_path is None:
            try:
                from autonomy.terminal_neuron_learning import latest_verified_run
                run = latest_verified_run()
                self.graph_path = (Path(run) / "neuron_graph.sqlite3") if run else None
            except Exception:
                self.graph_path = None
        self.close()
        if self.graph_path is not None and self.graph_path.exists():
            try:
                connection = sqlite3.connect(
                    f"file:{self.graph_path.resolve()}?mode=ro",
                    uri=True,
                    timeout=2.0,
                )
                tables = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                if not {"neuron_identity", "links"}.issubset(tables):
                    connection.close()
                    if {"neurons", "links"}.issubset(tables):
                        try:
                            from nn_local.steel_brain_store import SQLiteNeuronGraphStore
                            self._legacy_store = SQLiteNeuronGraphStore(
                                self.graph_path, readonly=True
                            )
                            st = self.graph_path.stat()
                            ck = (str(self.graph_path.resolve()), st.st_mtime, st.st_size)
                            cached_w = _SHARED_WORD_INDEX_CACHE.get(ck)
                            if cached_w is None:
                                cached_w = {
                                    str(word).lower(): str(neuron_id)
                                    for word, neuron_id in self._legacy_store.manifest().get(
                                        "word_index", {}
                                    ).items()
                                }
                                _SHARED_WORD_INDEX_CACHE[ck] = cached_w
                            self._word_index = cached_w
                            self._unavailable_reason = ""
                        except Exception:
                            self._unavailable_reason = "GRAPH_READ_FAILED"
                    else:
                        self._unavailable_reason = "GRAPH_SCHEMA_UNSUPPORTED"
                else:
                    connection.row_factory = sqlite3.Row
                    self._connection = connection
                    self._unavailable_reason = ""
            except sqlite3.Error:
                self._unavailable_reason = "GRAPH_READ_FAILED"

    def advertise_route(
        self,
        route: Iterable[str],
        *,
        context_words: Iterable[str] = (),
        resource_snapshot: dict[str, Any] | None = None,
        traversal_units: int | None = None,
    ) -> dict[str, Any]:
        words = tuple(str(word).lower() for word in route if str(word).strip())
        if len(words) < 2:
            return {"state": "HOLD", "reason": "ROUTE_TOO_SHORT", "utility": 0.0}
        if self._connection is None and self._legacy_store is None:
            return {
                "state": "HOLD",
                "reason": self._unavailable_reason,
                "utility": 0.0,
                "route": list(words),
            }

        if self._legacy_store is not None:
            nodes_total = int(self._legacy_store.connection.execute("SELECT COUNT(*) FROM neurons").fetchone()[0])
            edges_total = int(self._legacy_store.connection.execute("SELECT COUNT(*) FROM links").fetchone()[0])
        else:
            nodes_total = int(self._connection.execute("SELECT COUNT(*) FROM neuron_identity").fetchone()[0])
            edges_total = int(self._connection.execute("SELECT COUNT(*) FROM links").fetchone()[0])

        edges: list[dict[str, Any]] = []
        missing: list[list[str]] = []
        for source, target in zip(words, words[1:]):
            if self._legacy_store is not None:
                source_id = self._word_index.get(source)
                target_id = self._word_index.get(target)
                row = None
                if source_id and target_id:
                    row = self._legacy_store.connection.execute(
                        """SELECT weight, pass_hits, fail_hits, hot
                           FROM links
                           WHERE source_id=? AND peer_id=?
                           ORDER BY weight DESC LIMIT 1""",
                        (source_id, target_id),
                    ).fetchone()
            else:
                row = self._connection.execute(
                    """SELECT l.weight, l.pass_hits, l.fail_hits, l.hot
                       FROM neuron_identity s
                       JOIN links l ON l.source_id = s.neuron_id
                       JOIN neuron_identity t ON t.neuron_id = l.peer_id
                       WHERE lower(s.semantic_key) = ? AND lower(t.semantic_key) = ?
                       ORDER BY l.weight DESC
                       LIMIT 1""",
                    (source, target),
                ).fetchone()
            if row is None:
                missing.append([source, target])
                continue
            weight = int(row["weight"])
            passes = int(row["pass_hits"])
            failures = int(row["fail_hits"])
            edges.append({
                "source": source,
                "target": target,
                "weight": weight,
                "pass_hits": passes,
                "fail_hits": failures,
                "hot": bool(row["hot"]),
            })

        context = {str(word).lower() for word in context_words}
        context_hits = sum(
            1 for edge in edges
            if edge["source"] in context or edge["target"] in context
        )
        if not edges:
            utility = 0.0
        else:
            conductance = sum(edge["weight"] for edge in edges) / len(edges)
            reliability = sum(
                (edge["pass_hits"] + 1) / (edge["pass_hits"] + edge["fail_hits"] + 2)
                for edge in edges
            ) / len(edges)
            hot_fraction = sum(1 for edge in edges if edge["hot"]) / len(edges)
            context_fraction = context_hits / len(edges)
            utility = conductance * (0.5 + 0.3 * reliability + 0.1 * hot_fraction + 0.1 * context_fraction)

        # Pathfinding efficiency: measured resource cost divided by bounded
        # traversal jumps. Missing hardware telemetry remains explicitly
        # unmeasured; it is never replaced with a fabricated zero.
        max_chars = max(1, len("".join(words)))
        requested_jumps = traversal_units if traversal_units is not None else max(1, len(words) - 1)
        jumps = max(1, min(int(requested_jumps), max_chars))

        # Planck Topological RNN & Lorentz-Cognizant UML Invariant Physics:
        # 1. Nested Invariant Mass (M): character Planck cells encapsulated by the hierarchical token path (E = M * c^2, c=1)
        planck_mass_m = float(max_chars)
        planck_energy_e = planck_mass_m
        # 2. Topological Distance (D): 1-hop minimum up to max_character_ceiling
        topological_distance_d = float(jumps)
        # 3. Topological Speed (S = E / D) and Recursive Speed (S_rec = (E / D)^2)
        topological_speed_s = planck_energy_e / topological_distance_d
        recursive_speed_s2 = topological_speed_s ** 2
        # 4. Lorentz-Cognizant Reference Frame Transformation:
        #    Rest frame = character Planck lattice (max_chars).
        #    Observer velocity ratio beta = min(0.999999, D / max_chars) within the Planck light-cone.
        #    Lorentz factor gamma = 1 / sqrt(1 - beta^2); Lorentz-contracted recursive speed = S_rec / gamma.
        lorentz_beta = min(0.999999, topological_distance_d / max(1.0, float(max_chars)))
        lorentz_gamma = 1.0 / math.sqrt(max(1e-12, 1.0 - (lorentz_beta ** 2)))
        lorentz_invariant_s2 = recursive_speed_s2 / lorentz_gamma
        # 5. RID Volumetric Load & 2D Holographic Stability Scalar Projection:
        #    Sn^2 = ((RLE * LTP) * RSR)^3  =>  Sn = sqrt(Volume)
        rle_norm = min(1.0, planck_energy_e / max(1.0, float(max_chars)))
        ltp_norm = min(1.0, 1.0 / topological_distance_d) if topological_distance_d > 0 else 1.0
        rsr_norm = rle_norm * ltp_norm
        inner_core = (rle_norm * ltp_norm) * rsr_norm
        volumetric_load = inner_core ** 3
        holographic_sn = math.sqrt(volumetric_load)
        # Scale-invariant dimensional volume (unclamped bulk potential)
        bulk_inner_core = (planck_energy_e * topological_distance_d) * topological_speed_s
        bulk_volume = bulk_inner_core ** 3
        bulk_sn = math.sqrt(bulk_volume)
        entropy_terms = []
        for edge in edges:
            total = edge["pass_hits"] + edge["fail_hits"]
            if total:
                p = edge["fail_hits"] / total
                if 0.0 < p < 1.0:
                    entropy_terms.append(-(p * math.log2(p) + (1.0 - p) * math.log2(1.0 - p)))
                else:
                    entropy_terms.append(0.0)
        information_entropy_bits = sum(entropy_terms) / len(entropy_terms) if entropy_terms else None
        resources = resource_snapshot or {}
        power_w = resources.get("gpu_power_w")
        cpu_percent = resources.get("cpu_load_percent")
        sample_window_seconds = resources.get("sample_window_seconds")
        temperature_c = resources.get("gpu_temp_c")
        if temperature_c is None:
            temperature_c = resources.get("cpu_temp_c")
        efficiency_state = "UNMEASURED"
        cost_per_jump = None
        path_speed = None
        thermal_entropy_j_per_k = None
        energy_joules = None
        cpu_time_seconds = None
        resource_cost_index = None
        resource_cost_raw = None
        route_efficiency = None
        if (
            power_w is not None
            and cpu_percent is not None
            and sample_window_seconds is not None
            and temperature_c is not None
            and edges
        ):
            reliability_efficiency = reliability
            distance_efficiency = min(1.0, jumps / max_chars)
            route_efficiency = max(0.0, min(1.0, reliability_efficiency * distance_efficiency))
            energy_joules = max(0.0, float(power_w)) * max(0.0, float(sample_window_seconds))
            cpu_time_seconds = (max(0.0, float(cpu_percent)) / 100.0) * max(0.0, float(sample_window_seconds))
            temperature_kelvin = max(1.0, float(temperature_c) + 273.15)
            thermal_entropy_j_per_k = (energy_joules * (1.0 - route_efficiency)) / temperature_kelvin
            # Normalize unlike physical dimensions into a named, dimensionless
            # routing index. Reference units are explicit and stable.
            resource_cost_raw = (
                (energy_joules / 1.0)
                + (cpu_time_seconds / 1.0)
                + (thermal_entropy_j_per_k / 0.001)
            ) / 3.0
            resource_cost_index = max(0.0, min(1.0, resource_cost_raw))
            cost_per_jump = resource_cost_index / jumps
            path_speed = jumps / max(float(sample_window_seconds), 1e-9)
            utility *= 1.0 / (1.0 + resource_cost_index)
            efficiency_state = "MEASURED"

        return {
            "state": "PASS" if not missing else "PARTIAL",
            "route": list(words),
            "utility": round(float(utility), 6),
            "efficiency": {
                "state": efficiency_state,
                "jumps": jumps,
                "max_character_ceiling": max_chars,
                "power_w": power_w,
                "cpu_load_percent": cpu_percent,
                "sample_window_seconds": sample_window_seconds,
                "temperature_c": temperature_c,
                "energy_joules": energy_joules,
                "cpu_time_seconds": cpu_time_seconds,
                "information_entropy_bits": information_entropy_bits,
                "thermal_entropy_j_per_k": thermal_entropy_j_per_k,
                "route_efficiency": route_efficiency,
                "entropy_generated": thermal_entropy_j_per_k,
                "resource_cost_index": resource_cost_index,
                "resource_cost_raw": resource_cost_raw,
                "resource_cost_clamped": (
                    resource_cost_raw is not None and resource_cost_raw > 1.0
                ),
                "cost_per_jump": cost_per_jump,
                "path_speed": path_speed,
                "planck_mass_m": planck_mass_m,
                "planck_energy_e": planck_energy_e,
                "topological_distance_d": topological_distance_d,
                "topological_speed_s": topological_speed_s,
                "recursive_speed_s2": recursive_speed_s2,
                "lorentz_beta": round(lorentz_beta, 6),
                "lorentz_gamma": round(lorentz_gamma, 6),
                "lorentz_invariant_s2": round(lorentz_invariant_s2, 6),
                "volumetric_load": volumetric_load,
                "holographic_sn": holographic_sn,
                "bulk_volume": bulk_volume,
                "bulk_sn": bulk_sn,
            },
            "learning_mapping": {
                "loss_distance": jumps,
                "learning_rate_speed": path_speed,
                "topological_speed_s": topological_speed_s,
                "recursive_speed_s2": recursive_speed_s2,
                "lorentz_beta": round(lorentz_beta, 6),
                "lorentz_gamma": round(lorentz_gamma, 6),
                "lorentz_invariant_s2": round(lorentz_invariant_s2, 6),
                "holographic_sn": holographic_sn,
                "gradient_norm_cost": cost_per_jump,
                "gradient_norm_resource_cost": cost_per_jump,
                "epoch_progress_edges_per_node": edges_total / max(1, nodes_total),
                "topology_phase": (
                    "mesh_threshold_crossed"
                    if edges_total / max(1, nodes_total) >= 1.0
                    else "sparse_transition"
                ),
                "nodes_total": nodes_total,
                "edges_total": edges_total,
            },
            "units": {
                "loss_distance": "jumps",
                "max_character_ceiling": "characters",
                "planck_mass_m": "planck_neurons",
                "planck_energy_e": "planck_energy_mc2",
                "topological_distance_d": "hops",
                "topological_speed_s": "mass/hop",
                "recursive_speed_s2": "(mass/hop)^2",
                "holographic_sn": "rid_stability_scalar",
                "sample_window_seconds": "s",
                "power_w": "J/s",
                "energy_joules": "J",
                "cpu_load_percent": "%",
                "cpu_time_seconds": "CPU-s",
                "information_entropy_bits": "bit",
                "temperature_c": "degC",
                "thermal_entropy_j_per_k": "J/K",
                "route_efficiency": "fraction[0,1]",
                "resource_cost_index": "dimensionless",
                "resource_cost_raw": "dimensionless-unbounded",
                "cost_per_jump": "dimensionless/jump",
                "path_speed": "jumps/s",
                "epoch_progress_edges_per_node": "edges/node",
            },
            "edge_count": len(edges),
            "missing_edges": missing,
            "context_hits": context_hits,
            "edges": edges,
            "graph_path": str(self.graph_path) if self.graph_path else None,
        }

    def rank_routes(
        self,
        routes: Iterable[dict[str, Any]],
        *,
        context_words: Iterable[str] = (),
        resource_snapshot: dict[str, Any] | None = None,
        traversal_units: int | None = None,
    ) -> list[dict[str, Any]]:
        ranked = []
        for item in routes:
            route = item.get("route") or str(item.get("sentence", "")).lower().rstrip(".").split()
            advertisement = self.advertise_route(
                route,
                context_words=context_words,
                resource_snapshot=resource_snapshot,
                traversal_units=traversal_units,
            )
            ranked.append({**item, "utility_advertisement": advertisement})
        ranked.sort(
            key=lambda item: (
                -float(item["utility_advertisement"]["utility"]),
                -int(bool(item.get("novel_to_history"))),
                str(item.get("sentence", "")),
            )
        )
        return ranked
