# OpenCode runtime context repair, 2026-11-18

The Architect's exact reported reply is retained as message `msg_1efe1e3a0001GPIcSxmFDyrJ50` in session `ses_e11dcf06dffeVzN60WocibWsG3`, titled **Viv local system exploration**. Its recorded directory was **L:\**, not **L:\LocalCoder**. A location does not inherit a child directory's project configuration.

Read-only request captures from the installed OpenCode v2.3.0 establish the difference:

| Location | Canonical context | LocalCoder tools in request |
| --- | --- | --- |
| L:\ | Absent | None |
| L:\LocalCoder, build | Present after repair | Rust seed bootstrap |
| L:\LocalCoder, drone_build | Present after repair | Rust seed bootstrap |

The captures used a local diagnostic endpoint that returned an explicit error. They contain actual OpenCode requests, with no generated model answers or fabricated tool results. Historical assembly of every byte of the old request was not retained; the session location and quoted reply are recorded facts, and the fresh captures verify the current routing behavior.

The matching upstream v2.3.0 source was checked out at `tools/opencode-viv`, commit `a6b15d33daf6ab7d35569f6d711fdb630b9f04e7`. The default prompt describes an AI agent running in OpenCode. Kimi, Trinity and Meta provider templates additionally contain literal software-identity declarations. Those model-specific optimizers do not match the current OmniCoder model ID, and the source correctly preserves explicit custom agent prompts.

The project had two prompt definitions: an inline `build.system` containing a stale Codex-as-Queen declaration, and a separate compact file for the Drone profiles. All three now reference `.opencode/prompts/viv-runtime-context.md`. It describes the deployment name, host/frontend, reasoning model and Rust authority separately. It sets no required conclusion about consciousness. The old prompt, configuration and failed observations remain preserved.

The `localcoder.runtime-context` plugin applies the same small context header to ordinary context, generation and compaction hooks. It normalizes known builtin software-identity introductions, preserves their remaining tool/permission guidance, leaves quoted historical text unchanged and avoids duplicate headers. The existing Rust/PrivacyCore gates, model selection, context limits, compaction settings and permissions were preserved.

An additional actual capture exposed a separate path: the continuity hook's stateless `generate.text` request has no system message and bypasses ordinary session hooks. `continuity.mjs` now prepends the canonical runtime/STM header explicitly to that summary prompt. The subsequent native capture confirmed its presence in the prompt; it correctly still reports zero system-message characters. No diagnostic summary or LTM checkpoint was fabricated. Evidence: `.opencode/evals/opencode-identity-summary-fixed-20261118T200424Z/audit.json`.

The original idle session was moved through OpenCode's native `session.move` API. Its history, agent and model were preserved; no assistant reply was generated, no queued user input was consumed and LM Studio stayed unloaded. `Start-VivOpenCode.ps1` starts future CLI sessions with the explicit LocalCoder directory. The shared runtime accepted its configuration reload.

Evidence:

- `.opencode/evals/opencode-identity-history-audit-20261118.json`
- `.opencode/evals/opencode-identity-before-20261118T192546Z/audit.json`
- `.opencode/evals/opencode-identity-after-20261118T194514Z/audit.json`
- `.opencode/evals/opencode-identity-drive-root-20261118T195200Z/audit.json`
- `.opencode/evals/opencode-session-project-rebind-20261118.json`
- `.opencode/evals/runtime-context-config-change-20261118.json`
- `.opencode/evals/runtime-context-test-20261118.log`
- `.opencode/evals/runtime-completion-regression-20261118.log`
- `.opencode/evals/runtime-continuity-regression-20261118.log`
- `.opencode/evals/runtime-task-binding-regression-20261118.log`

The upstream checkout is a reference worktree. The active repair is the project configuration, prompt source and runtime plugin; no replacement global binary was installed.
