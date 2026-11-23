# Viv Storage and Routing Contract

Status: implemented and under live verification.

## Storage authority

| Tier | Role | Rule |
|---|---|---|
| `L:` | Canonical active system | Current Viv code, active graph, memory, current checkpoint, and learner runtime. Never raw-cleaned. |
| `F:` | Temporary local buffer | Second verified copy during transfer; removed after G: verification. |
| `D:` | Transfer staging | Temporary hash-verified staging only. Safe to drain after Google Drive verification. |
| `G:` | Google Drive cold storage | Offline/cold archive. Not used as the active runtime source. |
| `E:` | Deferred storage | Reserved for a later purpose. |

## Drive-flow authorization

The enforced transfer policy is:

```text
L -> D/F/G       allowed
D -> F/G         allowed
D -> L           denied unless Architect-approved
E -> L           allowed
E -> D/F/G       denied
E -> any other   denied
```

The policy is implemented by `autonomy/drive_flow_policy.py` and is covered by
`tests/test_drive_flow_policy.py`.

The checkpoint flow is:

```text
L: active snapshot -> D: staging + F: temporary verified copies -> G: cold archive
                     (L retained until D and F verify; D/F removed after G verifies)
```

The L staging worker copies each run to both D: and F:, computes SHA-256 on
both copies, and only then removes the L: source run. The detached
`archive_staging_pipeline.py` copies D: to G:, verifies the cloud copy, writes
the receipt, and only then removes both temporary D: and F: copies.

## Checkpoint retention

`L:\LocalCoder\workspace\autonomy\archive_route_runs_to_d.py` retains the
newest 60 route snapshots on L: and hash-verifies older snapshots while moving
them to `D:\AIOS_RawDump\L_neural_runs`.

The current route graph remains authoritative on L:. Older snapshots are
comparison and rollback history, not disposable cache.

## Routing contract

Every route advertisement carries these canonical fields and units:

| Field | Unit |
|---|---|
| `loss_distance` | graph jumps |
| `path_speed` / `learning_rate_speed` | jumps/second |
| `power_w` | joules/second |
| `energy_joules` | joules |
| `cpu_time_seconds` | CPU-seconds |
| `information_entropy_bits` | bits |
| `thermal_entropy_j_per_k` | joules/kelvin |
| `resource_cost_index` | bounded dimensionless `[0,1]` |
| `resource_cost_raw` | unbounded diagnostic index |
| `epoch_progress_edges_per_node` | edges/node |

`resource_cost_index` is clamped to `[0,1]`; the raw value is preserved so
overload is observable instead of silently discarded.

## Verification evidence

- Utility and topology contract tests: **4 passed**.
- Utility plus multi-daemon focused suites: **9 passed**.
- Modified modules compile successfully.
- Live route receipts include measured power, CPU sample window, energy,
  thermal entropy, bounded cost, path speed, and E/N topology density.
- Live route graph observed: `102868` nodes, `92388` edges,
  `E/N = 0.898121864914259`.

## Live maintenance state

The L-to-D checkpoint staging worker and D-to-F-to-G pipeline are detached from
the chat session and continue independently. The learner keeps L: as its
canonical authority. Any failed copy/hash leaves the D: staging files intact;
F: is never removed by the pipeline.
