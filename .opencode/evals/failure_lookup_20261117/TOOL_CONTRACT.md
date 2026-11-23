# Native OpenCode lookup tool

Create `.opencode/evals/failure_lookup_20261117/localcoder-failure-lookup.candidate.ts`.
This candidate is reviewed before it is copied into `.opencode/plugins/`.

Use the installed V2 shape:
`import { Plugin } from "@opencode/plugin"`
`export default Plugin.define({ id: "localcoder.failure-lookup", async setup(ctx) { ... } })`
Register one tool with `await ctx.tool.transform(editor => { editor.add({...}) })`.

Tool name: `localcoder_failure_lookup`.
Description: retrieve actual saved receipt failures, code hashes, and current
recorded results. Records are engineering evidence; never infer failure causes,
per-case resolution, training, or permission from them.
Input JSON schema: object with optional `case` (string, minLength 1, maxLength 120)
and `limit` (integer, minimum 1, maximum 20, default 8), no additional properties.
Use `options: { codemode: false }`.

Import `execFileSync` from `node:child_process`. The execute handler must validate
case and limit again (a bool is not an integer). Reject any extra input keys.
Invoke `L:/.venv/Scripts/python.exe` with an argv array:
`["-B", "L:/LocalCoder/workspace/autonomy/receipt_failure_lookup_candidate.py",
  "--limit", String(limit)]`, appending `["--case", input.case]` when present.
Use `{ cwd: "L:/LocalCoder", encoding: "utf8", timeout: 15000,
maxBuffer: 131072, windowsHide: true }`. No shell or model-selected file paths.

Parse stdout as JSON, require schema `localcoder_failure_lookup_v1`, then return
`{ content: JSON.stringify(result) }`. Invalid JSON/schema or subprocess errors
must fail the tool clearly. Do not turn an error into an empty success result.
No persistent writes, timers, model calls, environment changes, or UI effects.
