# Hermes agent operating guide

Canonical project instructions are [AGENTS.md](AGENTS.md). Hermes loads that filename automatically. This singular AGENT.md is the agent capability/continuity guide, not a competing architecture specification.

## Entry and tools

Launch manually with Start-Hermes.cmd. It opens the visible CLI at L:\LocalCoder through Ori using the configured OpenRouter model. No prompt or job is automatically submitted. Resume a prior conversation through Hermes's session commands when needed; do not assume its old task remains authorized.

Native capabilities configured: terminal/process management, file read/write/patch/search, persistent memory, session search, task planning, skills, web/browser tools, code execution, delegation, computer use, and project UI tools. Service-specific tools depend on their installed backend and credentials; configuration alone is not proof of connectivity. Delegation follows AGENTS.md's constraint on subagents. External messages and new scheduled work require explicit direction.

## Memory and handoffs

Native MEMORY.md and USER.md live at L:\LocalCoder\workspace\aios_rebuild\memory\hermes_agent\memories, exposed to Hermes through its profile memories junction. Memory stores verified facts and preferences; it does not train Viv or grant execution permission. Use memory with explicit provenance and preserve corrections. Native session history remains in Hermes's profile state.db and is searchable with session_search.

Use localcoder_checkpoint(completed, evidence, next_step) after substantial assigned work and before handing off. Each checkpoint is an immutable receipt on L:; the latest is recalled by the context hook. Include artifact paths and actual test results. BUILD_LOG.md remains the engineering history. A next step is a proposal until covered by the current assignment.

## Plugin and hooks

Source: .hermes/plugins/localcoder. Installed into the Hermes user plugin directory by junction. localcoder_status is read-only. Hooks inject project context per turn, authorize native memory changes through PrivacyCore, snapshot direct file edits up to eight MiB, and write tool metadata receipts without raw command/output content. These hooks do not replace Rust/body gates or constitute an OS sandbox. Shell/subprocess mutations must use the appropriate existing project writers.

## Skills

Project skills are in .hermes/skills and installed through a user-skill junction. Read the matching skill before project coding, runtime diagnosis, or continuity work. Existing bundled software-development, debugging, review, research, and GitHub skills remain available; use actual installed prerequisites.

## Stop and verification

Continuous operation is disabled. No startup tasks or cron jobs may be enabled by interpreting this setup as an assignment. Bounded one-shot setup tests are authorized. The setup report under .hermes records tested capabilities and remaining external dependencies. Test success is not proof of Viv learning or broad agent reliability.
