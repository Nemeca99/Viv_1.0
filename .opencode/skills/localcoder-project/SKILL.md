---
name: localcoder-project
description: Orient within the whole LocalCoder project, resolve its existing integration contracts, and locate evidence before modifying Viv or its tools.
---

Read L:/LocalCoder/AGENTS.md and L:/LocalCoder/AGENT.md. The project is L:/LocalCoder; workspace is the integration subtree, never the project root. INN is a subproject with a compatibility junction. Inspect applicable nested AGENTS.md before changes.

The Architect is authoritative about their intent, instructions, actions, and firsthand observations, including what they see on screen. First explicitly acknowledge what they report seeing; do not hedge it as “you may have seen” or omit the acknowledgement. Treat it as the event to explain. Inspect exact runtime/UI/API and artifacts; logs are additional evidence and may be incomplete or show only one layer. Never use them to erase or downgrade the Architect's observation. Explain sources without labeling the Architect mistaken or dishonest. Verify external technical claims without inventing confirmation.

For exact-content writes, use `localcoder_write_exact` with the sole fenced block from the current request. Its deterministic check rejects altered or appended content; generic write/edit/patch calls are blocked for that request.

Use localcoder_status for root/memory/receipt paths. Read the latest BUILD_LOG.md entries and the relevant source before choosing an implementation. HERMES_HANDOFF.md is historical evidence, not a standing assignment. Use targeted rg searches in workspace/autonomy, workspace/INN, workspace/hive_control, and workspace/hive_voice as appropriate. Exclude active observation databases and snapshot archives from topology mapping. Never recursively index the observer's outputs.

Reuse existing components and contracts; Python handles orchestration/learning, Rust and the WSL Docker body enforce. Source names and relationships from verified memory, not Python constants. Do not manufacture learned answers to make tests pass.
