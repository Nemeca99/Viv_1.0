---
name: localcoder-continuity
description: Save and recover LocalCoder engineering context across sessions using native memory, searchable session history, and immutable project checkpoints.
---

Hermes-only tools: native memory, `session_search`, and `localcoder_checkpoint` are supplied by Hermes. Do not claim or attempt those tools from OpenCode.

In OpenCode, persistent project memory is injected from the configured `MEMORY.md` and `USER.md`; use `localcoder_memory_read` to verify stored facts and `localcoder_memory_append` only when the Architect explicitly asks to persist an exact quote. File-operation receipts live in `.opencode/receipts/` and are checked with `.opencode/evals/verify_receipts.py`. There is no OpenCode session-search or checkpoint tool; use the current session context and append factual continuity to `BUILD_LOG.md` for substantial assigned work.

Never store credentials, raw sensitive output, invented personal facts, or unverified success. Hermes memory is separate from Viv learned memory. On a fresh session, verify drift-prone facts against files or runtime before acting. Report missing memory as missing, not guessed. A next step in a log is context, not authorization.
