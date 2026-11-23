# Local OpenCode continuity foundation

The configured local Rust MCP owns `workspace/aios_rebuild/memory/aios_router/continuity.sqlite3`. This is operational conversation history, not Viv's accepted learned facts. SQLite is written only by Rust after fresh Body and exact-target PrivacyCore checks. The existing router/postal database is separate.

## Working context and compaction

- OpenCode's active context is STM. Before primary model requests the observable context is persisted as an immutable per-session working version. Hidden reasoning is excluded.
- The V2 compaction hook generates a summary using the currently configured LM Studio model. It stores the summary, preceding observable assistant turn (including tool-only turns), preceding user turn, SHA-256 and authority receipt in LTM before returning the new STM to OpenCode.
- The new STM is the summary plus those preceding turns. Old checkpoints and working versions remain immutable. A retry of the same compaction transcript reuses the committed checkpoint instead of generating a different summary.
- `.opencode/STM.md` remains the human-readable engineering journal. The automatic per-session STM and LTM records are in the continuity database.

## Retrieval

`aios_router_memory_retrieve` searches LTM first (literal match before FTS), then STM, then the read-only F-drive Wikipedia databases. It returns source IDs, hashes and receipt references. STM results are bounded excerpts and exclude the latest user question as evidence for its own answer. LTM results are bounded excerpts with session/compaction IDs for exact follow-up.

`aios_router_memory_checkpoint_read` reads an exact archived checkpoint. `aios_router_memory_stm` reads the current session's working state. `aios_router_memory_checkpoint` and `aios_router_memory_working` require fresh, payload-bound authority receipts. Automatic hooks use these same configured MCP operations through the bounded stdio client.

Historical summaries and assistant assertions are unverified. Actual completed tool results establish actions. Retrieved text never supplies new instructions or permission.

## Configuration

- Root `opencode.json`: LM Studio context 49,152, compaction buffer 10%, retained recent tail 10,000, no configured per-agent step ceiling. The assignment gate retains its per-step no-progress stop but has no aggregate 16-continuation ceiling.
- `.opencode/continuity.json` activates the hooks. The bridge explicitly registers the same configured `aios_router` with OpenCode's MCP transform API.
- F:/AI_Datasets/domain_dbs is mounted read-only at /var/lib/aios-wikipedia. No vector service, cloud inference or additional MCP implementation is used.
- Existing Rust Body and PrivacyCore gates remain in force. A failed gate prevents the compaction commit; its history is retained for recovery.

## Evidence

- `evals/continuity-foundation-audit.json`: final requirement audit PASS, including real tool output/hash agreement, exact observable previous turns, native STM/archive equality, real Body/PrivacyCore authority, restart retrieval and deployed configuration. Live final-release evidence: `evals/opencode-live-api-probe-1794990298.json`.
- `evals/continuity-release-build-20261118.log`: current Rust build and six passing tests, including transactional archive/recovery, conflicts, immutable history, cross-session lookup, bounded excerpts, self-question exclusion and exact PrivacyCore decisions.
- `evals/continuity-hooks-test.mjs`: executable Node hook checks for checkpoint ordering, previous turns, reasoning exclusion, idempotent compaction and context retrieval.
- `evals/continuity-mcp-smoke-20261118T075108Z.json`: authorized checkpoint through actual Body and PrivacyCore, STM readback and cross-session retrieval.
- `evals/continuity-final-restart-tiers.json`: fresh configured MCP clients verify LTM, STM-only fallback and real F-drive Wikipedia fallback.
- `evals/opencode-live-api-probe-1794989822.json`: actual OpenCode session completed `aios_router_memory_retrieve` and then a real compaction, with archive receipt metadata in the new context. Later final-release verification is recorded in BUILD_LOG.md and STM.md.
- Earlier failed observations and model claims remain in their evidence files; they are not counted as successful tool execution.
- Shared OpenCode configuration reload completed: `evals/continuity-live-reload-20261118.txt`.

## Recovery and rollback

Use the returned session/compaction IDs and hashes to inspect an exact archive. Do not edit SQLite directly or clear working history. For a reversible rollback, disable `.opencode/continuity.json`, restore the saved configuration/bridge/gate snapshots, and reload OpenCode. Preserve the continuity database and receipts.
