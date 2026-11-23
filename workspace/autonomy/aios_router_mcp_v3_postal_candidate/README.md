# AIOS Router MCP v3 postal candidate

This is an isolated Rust candidate copied from the v2 PrivacyCore router. The active OpenCode MCP configuration remains unchanged and continues to point at the earlier image. This candidate is not deployed.

## Postal contract

- A Drone must already have its unique OS-CSPRNG seed in `drone_identity_seed` before it can register one inbox. Inbox IDs are generated from OS CSPRNG entropy and are unique in the router registry. A Drone receives only its own inbox ID; the Queen list tool can see all registered IDs.
- Drone submission has no recipient argument: it can only enter the Queen shared outbox. There is no direct Drone-to-Drone route.
- Outbox and inbox bodies are encrypted with AES-256-GCM before SQLite insertion. The SQLite event chain contains hashes, IDs, turn metadata, and denial reasons, not message bodies.
- The Queen must read and authenticate an outbox message before dispatch. Dispatch reseals the Queen's reply into the selected registered Drone inbox and requires both the Drone ID and inbox ID handshake.
- An unknown Drone or mismatched inbox handshake creates an encrypted bounce for the original sender with a stable reason code. The Queen can correct the route and retry the same outbox message.
- Postal turns use the existing Router's zero-based turn numbering. Each Drone submission must match the active lane turn and is committed atomically with the task's `turn_result`. `max_turns_per_lane` remains the hard bound; completion still uses the existing Router lane completion tool.
- The Queen summary is generated from Router and postal receipts. It does not turn Drone prose into a verified success claim.

## Role and write gates required for integration

Every postal tool requires a fresh `opencode_body_gate_receipt_v1`, under 15 seconds old, with the exact tool source, current session, `ALLOW_MIND_RUNTIME`, the deterministic Rust Body authority, an exact PrivacyCore allow for the pinned router DB and its `-wal`, `-shm`, and `-journal` paths, and a `postal_actor` object:

```json
{"role":"drone","agent_id":"localcoder-viv-drone-01"}
```

or, for Queen tools:

```json
{"role":"queen","agent_id":"queen"}
```

The current `architect-body-gate.ts` does not emit `postal_actor`, and the current Drone assignment gate does not recognize these tool names or enforce the Queen role. Therefore the candidate correctly fails closed until the two existing OpenCode gate plugins are updated. The Queen role is reserved for an OpenCode agent named `queen`; the current MCP tool bridge does not let the local Drone claim that role.

## Persistence and key custody

- Router database: `/var/lib/aios-router/router.sqlite3`, mapped to `L:\LocalCoder\workspace\aios_rebuild\memory\aios_router\router.sqlite3` so PrivacyCore checks the established DB target.
- Body receipts: `/var/lib/aios-body-receipts`, mounted read-only.
- Master key: `/var/lib/aios-router-key/postal.master-key-v1`, on a separate persistent Docker named volume with Linux mode `0600`. The key is never returned to tools, stored in SQLite, or included in receipts. The key volume must survive image rebuilds; losing it makes existing encrypted bodies unreadable.
- The message database and the separate key volume are local trusted storage. This protects message contents from model context and SQLite-only disclosure; it does not protect against a host administrator or compromised Docker daemon.
- Runtime remains network-isolated (`--network=none`), read-only root, non-root UID/GID `10001:10001`, no capabilities, and bounded CPU/memory/pids.

## Source verification

`cargo test --locked` passes four tests on Windows: two inherited PrivacyCore checks, AES-GCM tamper rejection, and an isolated two-turn mailbox round trip covering Queen outbox read, correct delivery, invalid-handshake bounce, corrected retry, private inbox read, and receipt-derived completion summary. These tests use temporary databases and synthetic receipts; they are not evidence that the active OpenCode gates or deployed MCP are integrated.

Build the pinned candidate image with `docker build --pull=false -t aios-router-mcp-v3-postal-candidate:0.3.0 .` after the Docker context can access the pinned base images. No daemon or scheduler is part of this candidate.

## Live deployment reconciliation and exact integration targets

The current `opencode mcp list` reports `aios_router` connected. WSL Docker shows the live process as container `0e847d46492b34259840898da8d92adf0ec5498cfbcbf839b8bfb59e04f9a57b`, image `sha256:349682dbd6449d877569606bb086f66e088b9e7861b799461c09a6d010037316`, still running with the original DB and read-only receipt mounts. `opencode.json` still points at that image. The read-only DB inspection found 75 `router_event` rows, the existing seed `localcoder-viv-drone-01 = 915703687`, and zero `postal_*` tables. This v3 image was built locally but has not replaced it.

To integrate v3, the required existing targets are `L:\LocalCoder\.opencode\plugins\architect-body-gate.ts`, `L:\LocalCoder\.opencode\plugins\localcoder-drone-assignment-gate.ts`, and `L:\LocalCoder\opencode.json`. The first must add postal tool PrivacyCore checks and actor fields; the second must inject trusted Drone identity and deny Queen-only tools to Drone agents; the third must pin the v3 image digest and mount the separate named key volume. The router must not be switched until those gates are updated and reviewed.

The current configured agents are `title`, `build`, `drone_read`, and `drone_build`; all Drone IDs map to `localcoder-viv-drone-01`. No Queen identity is configured, and this Codex session is not a client of the local `aios_router` MCP. A future integration must establish how the Architect-designated Codex Queen gets a trusted local actor receipt. Assigning the Queen role to a new local model agent would change the current role designation and is not assumed here.
