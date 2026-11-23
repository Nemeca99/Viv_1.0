# Viv Agentic System Handoff

## Source of truth

`L:\LocalCoder\workspace` is the active integration root. L: is canonical.
Python orchestrates learning; Rust/body gates authorize execution and commits.
The current verified SQLite route snapshot is the only graph used for live
answers. Older snapshots are comparison and rollback history.

## Start the learner

```powershell
& L:\LocalCoder\workspace\Run-MultiDaemon-Foreground.ps1 -MaxCycles 0
```

Run it detached for unattended operation with a hidden PowerShell process. Do
not start a second orchestrator if one already exists.

## Monitor the system

Primary heartbeat:

```text
L:\LocalCoder\workspace\autonomy\learning\multi_daemon_status.json
```

Check `timestamp`, `running`, `total_attempted`, `total_graduated`,
`latest_snapshot`, and `recent_errors`. A live process without a fresh
heartbeat is not evidence of healthy learning.

## Storage automation

The intended pipeline is:

```text
L: active -> D: staging -> F: local archive
                         -> G: Google Drive cold archive
```

- `archive_route_runs_to_d.py` moves older verified route snapshots from L:
  to D: while retaining the newest 60 on L:.
- `archive_staging_pipeline.py` copies D: runs to F: and G:, compares hashes,
  writes receipts, then removes D: only after both copies verify.
- A failed copy or hash leaves D: intact. F: and L: are never removed by the
  cloud stage.

## Drive-flow policy

Implemented in `autonomy/drive_flow_policy.py`:

```text
L -> D/F/G       allowed
D -> F/G         allowed
D -> L           Architect approval required
E -> L           allowed
E -> D/F/G       denied
```

## Routing telemetry contract

Every route advertisement carries:

- `loss_distance`: graph jumps;
- `learning_rate_speed`: jumps/second;
- `power_w`: J/s;
- `energy_joules`: J;
- `cpu_time_seconds`: CPU-s;
- `information_entropy_bits`: bit;
- `thermal_entropy_j_per_k`: J/K;
- `resource_cost_index`: bounded dimensionless [0,1];
- `resource_cost_raw`: unbounded diagnostic index;
- `epoch_progress_edges_per_node`: E/N;
- `topology_phase`: sparse transition or mesh threshold crossed.

## Safety and recovery rules

- Never answer from an unverified or stale snapshot.
- Never delete a source before a matching SHA-256 receipt exists.
- Keep the current L: snapshot and immediate comparison parent local.
- Treat Rust `HOLD_MIND_RUNTIME` as a real hold; inspect GPU memory, disk
  space, and heartbeat instead of bypassing the gate.
- Backup Core records checkpoint-head lineage; it does not replace the active
  SQLite graph.

## Live 2D lattice terminal view

Run this beside the learning daemon:

```powershell
$env:PYTHONPATH = 'L:\LocalCoder\workspace'
& 'L:\.venv\Scripts\python.exe' `
  'L:\LocalCoder\workspace\autonomy\live_dashboard.py' --refresh 2
```

The terminal view rereads `learning/multi_daemon_status.json` every refresh,
opens that daemon-selected `neuron_graph.sqlite3` read-only, and renders a
bounded deterministic 2D projection of the highest-weight verified SQLite
links. The coordinates are only screen coordinates; nodes and links are not
simulated. `--once` prints one evidence snapshot for diagnostics.
