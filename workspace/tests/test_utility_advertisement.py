import sqlite3

from autonomy.utility_advertisement import UtilityAdvertiser


def _graph(path):
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE neuron_identity (neuron_id TEXT PRIMARY KEY, semantic_key TEXT);
        CREATE TABLE links (
            source_id TEXT, peer_id TEXT, weight INTEGER,
            pass_hits INTEGER, fail_hits INTEGER, hot INTEGER
        );
        """
    )
    conn.executemany(
        "INSERT INTO neuron_identity VALUES (?, ?)",
        [("sky", "sky"), ("blue", "blue"), ("red", "red")],
    )
    conn.executemany(
        "INSERT INTO links VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("sky", "blue", 75000, 8, 0, 1),
            ("sky", "red", 2000, 1, 4, 0),
        ],
    )
    conn.commit()
    conn.close()


def test_graph_advertises_stronger_route(tmp_path):
    graph = tmp_path / "graph.sqlite3"
    _graph(graph)
    advertiser = UtilityAdvertiser(graph)
    blue = advertiser.advertise_route(["sky", "blue"])
    red = advertiser.advertise_route(["sky", "red"])
    assert blue["state"] == "PASS"
    assert red["state"] == "PASS"
    assert blue["utility"] > red["utility"]
    advertiser.close()


def test_missing_topology_fails_closed(tmp_path):
    graph = tmp_path / "graph.sqlite3"
    _graph(graph)
    advertiser = UtilityAdvertiser(graph)
    result = advertiser.advertise_route(["sky", "green"])
    assert result["state"] == "PARTIAL"
    assert result["utility"] == 0.0
    assert result["missing_edges"] == [["sky", "green"]]
    advertiser.close()


def test_path_efficiency_uses_measured_cost_and_bounded_jumps(tmp_path):
    graph = tmp_path / "graph.sqlite3"
    _graph(graph)
    advertiser = UtilityAdvertiser(graph)
    result = advertiser.advertise_route(
        ["sky", "blue"],
        resource_snapshot={
            "gpu_power_w": 20.0,
            "cpu_load_percent": 10.0,
            "sample_window_seconds": 0.05,
            "gpu_temp_c": 50.0,
        },
        traversal_units=99,
    )
    efficiency = result["efficiency"]
    assert efficiency["state"] == "MEASURED"
    assert efficiency["jumps"] == len("skyblue")
    assert efficiency["cost_per_jump"] > 0
    assert efficiency["path_speed"] > 0
    assert efficiency["thermal_entropy_j_per_k"] > 0
    assert efficiency["information_entropy_bits"] == 0
    mapping = result["learning_mapping"]
    assert mapping["loss_distance"] == efficiency["jumps"]
    assert mapping["learning_rate_speed"] == efficiency["path_speed"]
    assert mapping["gradient_norm_cost"] == efficiency["cost_per_jump"]
    assert mapping["edges_total"] == 2
    assert mapping["nodes_total"] == 3
    assert mapping["epoch_progress_edges_per_node"] == 2 / 3


def test_resource_cost_index_is_bounded_with_raw_overflow_receipt(tmp_path):
    graph = tmp_path / "graph.sqlite3"
    _graph(graph)
    advertiser = UtilityAdvertiser(graph)
    result = advertiser.advertise_route(
        ["sky", "blue"],
        resource_snapshot={
            "gpu_power_w": 100.0,
            "cpu_load_percent": 100.0,
            "sample_window_seconds": 1.0,
            "gpu_temp_c": 90.0,
        },
    )
    efficiency = result["efficiency"]
    assert efficiency["resource_cost_raw"] > 1.0
    assert efficiency["resource_cost_index"] == 1.0
    assert efficiency["resource_cost_clamped"] is True
    assert result["learning_mapping"]["topology_phase"] == "sparse_transition"
    advertiser.close()
    advertiser.close()
