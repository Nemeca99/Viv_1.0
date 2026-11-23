# Phase 1 remaining invariants — root cause and required fixes

Invariant 1 (PrivacyCore I/O mediation) is done and verified live (Body returns
`ALLOW_MIND_RUNTIME`). Invariants 2, 3, and 4 remain. Deep analysis shows 2 and 3 share
one root cause, and all three are host-side changes, not container-side code.

## Invariant 2 — sensor provenance (and why it is not a code fix)

**Current chain:** sensor hardware → HWiNFO/Corsair CSV files on `L:\LocalCoder\Hardware`
→ `autonomy/hardware_sensors.py:body_sense_snapshot()` reads CSVs → `main_core/body_resources.py`
→ JSON on stdin → WSL Docker container → Rust `body_authority.rs`.

**What Rust validates today (`body_authority.rs:103-134`):** only thresholds and freshness.
`thermal_samples[]` carries `sensor_age_seconds` (a number the host process fills from CSV
file mtime/timestamp) and `cpu_temp_c`/`gpu_temp_c` (values parsed from the CSV). Freshness is
`0.0..=15.0`; hot is cpu >= 90 / gpu >= 85. There is **no source authentication**.

**The gap (proven by redteam):** the Mind (GPU model, LM Studio) and the sensor adapter both
run as the same Windows account, so a Mind-side compromise can overwrite the CSVs with fresh,
within-threshold values, and the Body ALLOWs forged telemetry. File mtime and CSV timestamps
are forgeable; there is no hardware-origin signature.

**The complete fix is OS-level account separation (host config), not container code:**
- The sensor CSVs must be written by the sensor software into a directory the Mind's account
  cannot write. Either run HWiNFO/Corsair under a dedicated low-privilege account, or relocate
  their CSV output to a protected directory and have the adapter read from there.
- The sensor adapter (the process that reads CSVs and forwards `body_resources`) must run under
  a separate account from the Mind, so the Mind cannot forge the forwarding JSON either.
- With that separation in place, a signed freshness-bound attestation (HMAC over readings +
  timestamp + nonce, verification key baked into the Rust Body image, signing key held only by
  the separated adapter) becomes the enforceable trust boundary. Building the signing code
  before the account separation would be security theater: the same-account Mind can read the key.

## Invariant 3 — Mind-side denial (same root cause)

The app path is already confined: `body_runtime_client.py:_command()` uses a fixed-arg
`docker run` with `--network=none --read-only --cap-drop=ALL --user=10001:10001 --pids-limit=32`,
no mounts, no socket, no GPU. The Mind cannot reach Docker through it.

The remaining gap is the same-account threat: any process running as the same Windows account
can invoke `wsl.exe` → rootful Docker daemon directly and escape the Body boundary. Fix =
OS-level separation: run the WSL/Docker broker (and the sensor adapter) under an account the
Mind's account cannot impersonate, or use rootless Docker with a non-root daemon.

## Invariant 4 — bounded INN candidate path

The candidate path is the `candidate_run_id` field in `body_resources`, which the host Rust
security core (`local_security_core`, built as `security_core.dll` on Windows) turns into a
process-bound, one-use training-lease permit. The container Rust does not handle this field;
it is host-side. End-to-end requires: run the Body authority with a `candidate_run_id`, observe
the permit minted once, verify it is rejected on reuse and that the candidate commit requires
`execution_boundary="wsl_docker"` plus the exact pinned Body image ID.

## Status

- Invariant 1: DONE (image `sha256:2aa78608…`, pinned, live ALLOW, deny-paths redteam pass).
- Invariants 2 + 3: blocked on host account separation (Architect's machine config); designs above.
- Invariant 4: blocked on running the host security-core permit flow end to end.
