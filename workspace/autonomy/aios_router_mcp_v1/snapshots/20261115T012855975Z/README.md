# AIOS Router MCP v1 candidate

The candidate is a Rust stdio MCP packaged in Docker on the existing Rust Body runtime image. It is a digest-only router event log and denial-evidence store. It is not a knowledge base: accepted/correct knowledge belongs only in the separate Drone-owned SQLite RAG database. Turn results are retained as hashes and are never promoted by this service.

## Container contract

- Build stage is pinned to `rust:1.90.0-slim-bookworm@sha256:64232e656c058f4468e8d024e990acff04f0fd5a5c0a88a574dc37773d7325c9`.
- Runtime stage is pinned to `aios-body-runtime:0.2.8-architect-runtime-permission@sha256:b1d7837fc4a78f60031bb5b0c3d68e639ecb786fa88b41776a5b64111f2a9634`.
- Runtime uses UID/GID `10001:10001`. The router database path is fixed at `/var/lib/aios-router/router.sqlite3`; mount a named volume there. The Body receipt path is fixed at `/var/lib/aios-body-receipts`; mount `.opencode/receipts` read-only there.
- The MCP has no model, shell, arbitrary filesystem, or general process-execution tool. Run-time network isolation must be supplied by Docker (`--network=none`) when the image is eventually launched; this candidate does not start or configure a service.

## Mutation receipt and task binding

Every mutation requires `session_id`, `task_id`, and `assignment_hash`. `open_build_task` also requires the assignment text whose SHA-256 must equal `assignment_hash`. Later turn, completion, and stop operations must match the original session and assignment hash. The router requires a not-yet-consumed `opencode_body_gate_receipt_v1` captured less than 15 seconds earlier, with the exact source `tool:aios_router_<tool>`, the same session, `allowed=true`, `ALLOW_MIND_RUNTIME`, and `deterministic_aios_body_rust` authority. Each accepted operation consumes the receipt ID in the append-only event chain. A Body HOLD, missing/stale receipt, or binding mismatch cannot write a router event. After a fresh ALLOW, invalid task/state requests append a bounded denial event containing a reason code and hashes, without raw prompt/result/assignment content.

Read-only status, classification, and Queen summary do not initialize the database schema. Status and summary require an existing router DB; classification is independent of it. The event log records routes, state transitions, and denials only. It does not determine whether Drone knowledge is correct.

## OpenCode argument names

MCP server key: `aios_router`. Mutating tool calls include `session_id`, `task_id`, and `assignment_hash` exactly. The receipt source is matched exactly as `tool:aios_router_open_build_task`, `tool:aios_router_accept_self_prompt`, `tool:aios_router_record_turn_result`, `tool:aios_router_complete_lane`, or `tool:aios_router_stop_task`. This repository does not configure OpenCode or expose/start the MCP.

## Verification

Use `cargo check --locked` for the source check. The Docker image build uses the pinned build/runtime stages and should be run with Docker build networking disabled when all locked dependencies are cached. No tests or service startup are part of this candidate task.
