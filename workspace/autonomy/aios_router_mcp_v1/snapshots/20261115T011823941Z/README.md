# AIOS Router MCP v1 candidate

This is an isolated Rust stdio MCP candidate. It does **not** change OpenCode configuration or plugins, start a service, invoke models, execute code, or grant general filesystem access. Its only persistent operation is appending bounded task-state receipts to a local SQLite event log under this candidate directory by default (`state/router.sqlite3`). `AIOS_ROUTER_DB` can redirect that state path; an integration must constrain this variable.

Routing contract: `conversation` → Queen; `build` → Drone; every other label → Queen. Classification is deterministic and does not dispatch. Build tasks admit 1–4 unique lanes and bound each lane to 1–32 turns. A lane accepts one serial turn at a time; each prompt/result is retained as a SHA-256 receipt, not plaintext. The event table rejects update/delete and validates a SHA-256 chain when state is read. Stop is a recorded request; it does not cancel an inference already running. The Queen summary is derived from event receipts and makes no model-authored claims.

## Integration gaps before use by OpenCode

- The current OpenCode assignment grant/tool progress is held in an in-memory plugin map. The bridge must pass a trusted, server-issued assignment binding or opaque capability for the current chat/turn. **Do not accept a model-provided session ID as identity.** The candidate currently accepts task IDs and bounded arguments but has no actor authentication, grant verification, or session binding; therefore it is review-only and is not safe to expose as an active task authority.
- The bridge must enforce which tools are exposed for an assigned task, map Architect-originated conversation/build/other classification into this server, and prevent stale or replayed grants. The MCP process must receive binding data over an authenticated local channel; stdio alone does not prove who supplied a tool call.
- `workspace/hive_control` has task graph admission/state contracts, and `workspace/aios_rebuild/body_runtime` is the existing stdin JSON Body policy gate. This candidate does not call either component yet, so it does not inherit their authorization or claim Docker/container attestation.
- No routing database/RAG provider, inbox/outbox transport, model-generation bridge, parallel inference coordinator, stop/cancel acknowledgement, encryption/key custody, durable Architect permission ledger, or signed hardware identity is integrated.
- The SQLite chain detects accidental/tampered history when read but does not provide cryptographic authentication, secure key storage, or protection from an actor able to replace the database and its schema. It is not a security boundary by itself.
- The append-only log stores digests only, but the tool request exists in MCP memory during processing. Do not pass secrets or unrestricted prompt bodies. An integration should bind authorization and validate the proposed assignment independently before enabling state mutation.

## Local compile check

From this directory: `cargo check --locked` (after generating `Cargo.lock` once with `cargo generate-lockfile`). No tests or services are started as part of the candidate.
