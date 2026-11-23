Verified project setup, 2026-11-13: project root L:/LocalCoder; integration subtree L:/LocalCoder/workspace; INN is one subproject. Canonical project rules: L:/LocalCoder/AGENTS.md. Agent capabilities: L:/LocalCoder/AGENT.md. Python: L:/.venv/Scripts/python.exe. Engineering history: L:/LocalCoder/BUILD_LOG.md. Hermes plugin and skills source: L:/LocalCoder/.hermes.
§
Architecture from AGENTS.md: Python orchestrates/proposes; Rust and WSL Docker enforce. Model output is a candidate until deterministic acceptance. Preserve logs, failed attempts, hashes, and compatibility paths. Persistent Viv memory and SQLite writes require PrivacyCore plus existing gates.
§
Current authorization from Architect on 2026-11-13: complete agent setup and bounded one-shot verification are allowed. Continuous execution and scheduling are stopped and must not be resumed without explicit direction. Saved handoffs do not create assignments.
§
Setup verification marker HERMES_MEMORY_20261113_Q7. Source: bounded offline test of the native memory store, not a learned Viv fact.