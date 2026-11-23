# Rust completion authority

The local model proposes code and reasons over results. OpenCode translates the current Architect assignment into bound tool calls. Rust owns acceptance criteria, actual verification execution, task state and completion receipts.

## Frozen contract

A routed build assignment includes exactly one single-line `Acceptance JSON:` object. Example:

```json
{"version":1,"kind":"artifacts","artifacts":["workspace/example.py"],"checks":[{"id":"behavior","argv":["/usr/local/bin/python","-B","workspace/tests/check_example.py"],"timeout_seconds":10,"inputs":["workspace/tests/check_example.py"]}]}
```

The Architect or authorized orchestrator supplies the criteria. The model can propose criteria; it cannot replace the frozen contract through tool arguments. Rust binds the contract to the exact assignment hash and pins the declared verification input files when opening the task. Verification dependencies that determine the check must be declared as inputs. Inline `-c` check code is already frozen in the command itself.

`artifacts` are the implementation/output files whose current versions are verified. `inputs` are the verification files the model must not alter to manufacture a pass. All paths are relative to L:/LocalCoder. Missing contracts, traversal, arbitrary executable paths and invalid bounds are rejected. Contract changes require a new authorized task.

An explicitly assigned `{"version":1,"kind":"control_plane"}` contract verifies a control-only lane lifecycle. It makes no claim about code behavior. Legacy tasks without a valid contract cannot be reported as verified completed work.

## Execution and decisions

- `aios_router_acceptance_contract` reads a task's frozen criteria.
- `aios_router_verify_task` runs the frozen checks through a separate instance of the pinned Rust executable, records actual process exits/output hashes and verifies artifact versions. The model supplies no verdict field.
- The verification container has a read-only project mount, no network, no control database/key write mounts and bounded temporary storage/resources. Commands execute from the immutable runtime, with a cleared environment and bounded process groups. Current runtime tools include Python; unavailable executables fail closed.
- OpenCode's before-tool hook only relays the actual Rust result into a fresh Body/PrivacyCore receipt. The control-side Rust checks the executor binary hash, frozen contract hash, exact commands, outcomes and current file hashes.
- `aios_router_complete_lane` requires that evidence before closing a lane. A nonempty prose receipt alone is insufficient.
- Both ordinary and postal task summaries derive completion from current evidence. Editing an artifact or a frozen verification input changes the visible task state to `awaiting_verification`. Merely restoring bytes after a failed check cannot revive an older pass; a fresh verification is required.
- Verification history and contracts are immutable. Failed exits, timeouts, stale versions and rejected claims remain recorded in SQLite/receipts.

Bounds: sixteen artifacts, four checks, thirty seconds per check, ninety seconds total declared check time, and sixty-four MiB per artifact. These are bounded verification operations; agent step count remains uncapped with the existing no-progress checks. Verification proves only the declared criteria and tracked files, not every property of the entire project.

## Integration

- Rust: `workspace/autonomy/aios_router_mcp_v3_postal_candidate/src/completion.rs`.
- Existing MCP executable has an isolated `--verify-contract` mode; no replacement MCP server was created.
- Frontend hook: `.opencode/lib/completion.mjs`, registered after the final trusted binding in `localcoder-drone-assignment-gate.ts`. `.opencode/completion.json` controls activation. The bridge keeps the original Architect sequence through planning and private continuations; its identity preflight is separate from the requested task actions.
- Orchestration: `completion_authority.py`, next to the existing MCP source. All SQL writes remain in gated Rust.
- The exact-target router PrivacyCore adapter retains raw decisions and normalizes its protocol status only after actual allows for the DB and all SQLite sidecars. Its own stricter boundary rejects targets outside those four paths.
- Wikipedia retrieval retains LTM -> STM -> Wikipedia order. No-hit corpus scans are bounded and explicitly mark budget exhaustion; matches use deterministic article order without an expensive whole-corpus exact-title sort.

Snapshots for reversible rollback are under `.opencode/snapshots/completion-verifier-20261118/`. Preserve the databases, contracts, failed attempts and receipts during rollback. Restore the previous pinned configuration and frontend files together; disabling the frontend hook while keeping a contract-requiring server deliberately leaves completion closed.

## Verified release, 2026-11-18

The pinned image is `sha256:bc26b04fb32ffffb54749be70814711f3aa3a4a6da1b723b0cf9a321ce63731d`. Ten Rust tests passed. The real local OpenCode/LM Studio run executed the full gated lane sequence and reported current Rust-verified completion. The separate native lifecycle test rejected prose-only completion, changed artifacts, rewritten verification inputs and a nonzero exit hidden behind printed success text; restoring bytes after failure required fresh verification. The task-binding, completion-hook and STM/LTM regression tests also passed.

Evidence: `.opencode/evals/completion-release-audit.json`, `.opencode/evals/opencode-completion-live-1794994843.json` and `.opencode/evals/completion-live-20261118T090631Z.json`. The shared OpenCode runtime accepted `opencode reload`; its output is `.opencode/evals/completion-live-reload-20261118.txt`. Earlier failed integration attempts remain preserved beside these records. These results establish this bounded pipeline and its declared checks; they do not establish general coding reliability or model learning.
