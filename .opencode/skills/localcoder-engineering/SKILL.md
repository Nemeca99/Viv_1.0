---
name: localcoder-engineering
description: Implement and verify assigned LocalCoder changes while preserving native architecture, prior work, and deterministic evidence.
---

Inspect repository status and relevant code before editing. Preserve uncommitted user work. Use L:\.venv\Scripts\python.exe. PowerShell is the host shell. Prefer saved scripts over fragile multiline python -c. Use absolute paths and forward slashes in tool JSON.

Choose one hypothesis and the smallest change that can establish it. Freeze evaluation gates. Save pre-edit copies/hashes for substantial changes; the LocalCoder plugin snapshots direct write_file/patch calls, but shell-based edits require explicit snapshots. Preserve failed outputs. A passing compiler or unit test proves only its checked property.

For Viv persistent memory or SQLite writes, call the existing PrivacyCore.authorize_file_write and Rust/body-gated writer; do not directly replace these files. Read logs and SQLite schema before diagnosing. Use at most three retries with backoff/jitter for busy commits or snapshot mismatches, rereading the verified parent before replay.

Run checks appropriate to the assigned change. Do not launch unrelated learning campaigns. Append L:/LocalCoder/BUILD_LOG.md with exact files, commands, results, remaining uncertainty, and next step. `localcoder_checkpoint` is available in Hermes only; OpenCode must use its configured tool receipts and BUILD_LOG.md instead of claiming a checkpoint call. Promotion requires the Architect's direction and existing acceptance gates.
