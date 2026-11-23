# AIOS Router MCP v2 PrivacyCore candidate

This copied Rust stdio MCP candidate keeps the digest-only task-control and denial-evidence contract. It is not a knowledge base or mailbox: accepted knowledge remains in the separate Drone-owned RAG database, and message delivery/encryption is not implemented here. Turn results are retained as hashes and are never promoted by this service.

Cargo compiles `src/lib.rs` and `src/main.rs`. The top-level `lib.rs` and `main.rs` are preserved copies from the v1 source and are excluded from Docker context; no v1 source file is modified.

## Container contract

- Build stage is pinned to `rust:1.90.0-slim-bookworm@sha256:64232e656c058f4468e8d024e990acff04f0fd5a5c0a88a574dc37773d7325c9`.
- Runtime stage is pinned to `aios-body-runtime:0.2.8-architect-runtime-permission@sha256:b1d7837fc4a78f60031bb5b0c3d68e639ecb786fa88b41776a5b64111f2a9634`.
- Runtime uses UID/GID `10001:10001`. The router database path is fixed at `/var/lib/aios-router/router.sqlite3`; mount the host directory `L:\LocalCoder\workspace\aios_rebuild\memory\aios_router` there so the SQLite file is exactly the path checked by PrivacyCore. The Body receipt path is fixed at `/var/lib/aios-body-receipts`; mount `.opencode/receipts` read-only there.
- The MCP has no model, shell, arbitrary filesystem, or general process-execution tool. Run-time network isolation must be supplied by Docker (`--network=none`) when the image is eventually launched; this candidate does not start or configure a service.

## Mutation receipt and task binding

Every mutation requires `session_id`, `task_id`, and `assignment_hash`. `open_build_task` also requires the assignment text whose SHA-256 must equal `assignment_hash`. Later turn, completion, and stop operations must match the original session and assignment hash. The router requires a not-yet-consumed `opencode_body_gate_receipt_v1` captured less than 15 seconds earlier, with the exact source `tool:aios_router_<tool>`, the same session, `allowed=true`, `ALLOW_MIND_RUNTIME`, and `deterministic_aios_body_rust` authority. The same receipt must contain a fresh-plugin `privacy_core` decision with the exact schema, authority, pinned Windows database path, and successful checks for the main DB plus its `-wal`, `-shm`, and `-journal` paths. Each accepted operation consumes the receipt ID in the append-only event chain. A Body HOLD, PrivacyCore denial, missing/stale receipt, or binding mismatch cannot write a router event. After both gates allow, invalid task/state requests append a bounded denial event containing a reason code and hashes, without raw prompt/result/assignment content.

Read-only status, classification, and Queen summary do not initialize the database schema. Status and summary require an existing router DB; classification is independent of it. The event log records routes, state transitions, and denials only. It does not determine whether Drone knowledge is correct.

## OpenCode argument names

MCP server key: `aios_router`. Mutating tool calls include `session_id`, `task_id`, and `assignment_hash` exactly. The receipt source is matched exactly as `tool:aios_router_open_build_task`, `tool:aios_router_accept_self_prompt`, `tool:aios_router_record_turn_result`, `tool:aios_router_complete_lane`, or `tool:aios_router_stop_task`. This repository does not configure OpenCode or expose/start the MCP.

## Verification

Use `cargo test --locked` for the source check. Build the image with `docker build --pull=false` so Docker must use the already-present pinned base images. Cargo may need network access to fetch only the exact crates already pinned in `Cargo.lock`.

## Candidate scope and live state — 2026-11-15

The active OpenCode MCP remains pinned to the earlier v1 digest and named volume. This v2 copy is not loaded or deployed. Its OpenCode host plugin must run the Queen-side PrivacyCore probe before each router mutation and add the exact decision to the Body receipt; the Rust candidate then requires both authorities before opening the database writable. The intended bind-mounted database parent is inside the configured PrivacyCore allowed directory, but no router DB has been created there.

This candidate still does not hold message bodies and has no hardware-derived inbox identity, shared Queen-only outbox, authenticated reseal, or delivery API. It is a PrivacyCore-gated task-control candidate, not the complete AIOS message router.
