import { Plugin } from "@opencode/plugin"
import { execFileSync } from "node:child_process"
import { mkdir, open } from "node:fs/promises"
import { randomUUID } from "node:crypto"

const PROJECT = "L:\\LocalCoder"
const WORKSPACE = `${PROJECT}\\workspace`
const PYTHON = "L:\\.venv\\Scripts\\python.exe"
const RECEIPTS = `${PROJECT}\\.opencode\\receipts`
const ARCHITECT_GOAL_ID = "01a1d847-3b27-7533-bbc2-c718ace48ae7"
const ROUTER_DB_TARGET = "L:\\LocalCoder\\workspace\\aios_rebuild\\memory\\aios_router\\router.sqlite3"
const ROUTER_DB_TARGETS = [
  ROUTER_DB_TARGET,
  `${ROUTER_DB_TARGET}-wal`,
  `${ROUTER_DB_TARGET}-shm`,
  `${ROUTER_DB_TARGET}-journal`,
]
const PRIVACY_HELPER = `${WORKSPACE}\\autonomy\\privacy_core_router_db_gate_queen_v1_candidate.py`
const ROUTER_MUTATION_TOOLS = new Set([
  "aios_router_open_build_task",
  "aios_router_accept_self_prompt",
  "aios_router_record_turn_result",
  "aios_router_complete_lane",
  "aios_router_stop_task",
])

function executeBodyGate() {
  let raw = ""
  let executionError = ""
  try {
    raw = execFileSync(PYTHON, ["-m", "aios_rebuild.main_core.mind_runtime_gate",
      "--goal-id", ARCHITECT_GOAL_ID], {
      cwd: WORKSPACE,
      encoding: "utf8",
      timeout: 20000,
      windowsHide: true,
    })
  } catch (error: any) {
    raw = error?.stdout?.toString?.() ?? ""
    executionError = error?.message ?? "body_gate_process_failed"
  }

  let verdict: any
  try { verdict = JSON.parse(raw) }
  catch {
    verdict = {
      allowed: false,
      disposition: "HOLD_MIND_RUNTIME",
      authority: "deterministic_aios_body_rust",
      reasons: [executionError || "body_gate_response_invalid_json"],
    }
  }
  if (executionError && verdict.allowed !== true && !Array.isArray(verdict.reasons)) {
    verdict.reasons = [executionError]
  }
  return verdict
}

function executePrivacyCoreGate() {
  let raw = ""
  let executionError = ""
  try {
    raw = execFileSync(PYTHON, ["-B", PRIVACY_HELPER, "--authorize-router-db"], {
      cwd: WORKSPACE,
      encoding: "utf8",
      timeout: 10000,
      windowsHide: true,
    })
  } catch (error: any) {
    raw = error?.stdout?.toString?.() ?? ""
    executionError = error?.message ?? "privacy_core_process_failed"
  }

  let decision: any
  try { decision = JSON.parse(raw) }
  catch {
    return {
      schema: "privacy_core_file_write_decision_v1",
      authority: "PrivacyCore.authorize_file_write",
      target_path: ROUTER_DB_TARGET,
      allowed: false,
      reason: executionError || "privacy_core_response_invalid_json",
    }
  }

  const checkedPaths = Array.isArray(decision?.checked_paths) ? decision.checked_paths : []
  const pathsValid = checkedPaths.length === ROUTER_DB_TARGETS.length
    && checkedPaths.every((entry: any, index: number) => entry?.path === ROUTER_DB_TARGETS[index]
      && entry?.allowed === true && entry?.reason === "file_write_policy_passed")
  const valid = decision?.schema === "privacy_core_file_write_decision_v1"
    && decision?.authority === "PrivacyCore.authorize_file_write"
    && decision?.target_path === ROUTER_DB_TARGET
    && typeof decision?.allowed === "boolean"
    && typeof decision?.reason === "string"
    && pathsValid
  return {
    schema: "privacy_core_file_write_decision_v1",
    authority: "PrivacyCore.authorize_file_write",
    target_path: ROUTER_DB_TARGET,
    allowed: valid && decision.allowed === true && decision.reason === "file_write_policy_passed",
    reason: valid ? decision.reason : (executionError || "privacy_core_decision_invalid"),
    checked_paths: valid ? checkedPaths : [],
  }
}

async function recordGate(source: string, sessionID: string, verdict: any) {
  await mkdir(RECEIPTS, { recursive: true })
  const path = `${RECEIPTS}\\${Date.now()}-${randomUUID()}-body-gate.json`
  const handle = await open(path, "wx")
  try {
    await handle.writeFile(JSON.stringify({
      schema: "opencode_body_gate_receipt_v1",
      source,
      session_id: sessionID,
      authority: verdict.authority ?? "deterministic_aios_body_rust",
      disposition: verdict.disposition ?? "HOLD_MIND_RUNTIME",
      allowed: verdict.allowed === true,
      reasons: Array.isArray(verdict.reasons) ? verdict.reasons : ["body_gate_verdict_invalid"],
      body_image: verdict.body_image ?? null,
      resource_diagnostics: verdict.resource_diagnostics ?? null,
      architect_permission: verdict.architect_permission ?? null,
      privacy_core: verdict.privacy_core ?? null,
      captured_at: new Date().toISOString(),
    }, null, 2), "utf8")
    await handle.sync()
  } finally {
    await handle.close()
  }
}

async function requireBodyGate(source: string, sessionID: string) {
  const verdict = executeBodyGate()
  const toolName = source.startsWith("tool:") ? source.slice("tool:".length) : ""
  const requiresPrivacyCore = ROUTER_MUTATION_TOOLS.has(toolName)
  if (requiresPrivacyCore) verdict.privacy_core = executePrivacyCoreGate()
  await recordGate(source, sessionID, verdict)
  const bodyAllowed = verdict.allowed === true
      && verdict.disposition === "ALLOW_MIND_RUNTIME"
      && verdict.authority === "deterministic_aios_body_rust"
  if (!bodyAllowed) {
    const reasons = Array.isArray(verdict.reasons) ? verdict.reasons : []
    throw new Error(`Rust WSL Docker Body gate denied ${source}: ${JSON.stringify(reasons)}`)
  }
  if (requiresPrivacyCore && verdict.privacy_core?.allowed !== true) {
    throw new Error(`PrivacyCore denied ${source}: ${String(verdict.privacy_core?.reason ?? "decision_invalid")}`)
  }

  return
}

function targetPaths(input: any): string[] {
  const values = [input?.path, input?.filePath, input?.file_path, input?.filename]
  if (Array.isArray(input?.changes)) {
    for (const change of input.changes) values.push(change?.path, change?.filePath, change?.file_path)
  }
  return values.filter((value): value is string => typeof value === "string" && value.length > 0)
}

export default Plugin.define({
  id: "localcoder.architect-body-gate",
  async setup(ctx) {
    await ctx.session.hook("http.request", async (event: any) => {
      await requireBodyGate(`model_request:${event.kind}`, String(event.sessionID ?? "unknown"))
    }, { providerID: "lmstudio" })

    await ctx.tool.hook("execute.before", async (event: any) => {
      await requireBodyGate(`tool:${String(event.tool)}`, String(event.sessionID ?? "unknown"))
      const tool = String(event.tool).toLowerCase()
      if (["edit", "write", "patch", "localcoder_patch", "localcoder_write_exact", "localcoder_add_python"].includes(tool)) {
        const paths = targetPaths(event.input)
        if (paths.some(path => !path.toLowerCase().endsWith(".py"))) {
          throw new Error("Drone write policy: only Python files may be written; no file was changed.")
        }
      }
      if (["delete", "remove", "move", "rename", "rmdir"].includes(tool)) {
        throw new Error("Drone write policy: delete, move, and rename operations are Architect-only.")
      }
      if (["shell", "powershell", "bash", "cmd"].includes(tool)) {
        const command = String(event.input?.command ?? event.input?.cmd ?? "")
        const fileMutation = /\b(?:Set-Content|Add-Content|Out-File|Remove-Item|Move-Item|Rename-Item|Copy-Item|New-Item|write_text|write_bytes|unlink|rename|replace)\b|(?:>|>>)\s*[^\s]/i.test(command)
        const nonPythonTarget = /\.(?:rs|ts|tsx|js|jsx|toml|json|jsonc|yaml|yml|md|mdx|bat|cmd|ps1|dll|exe)\b/i.test(command)
        if (fileMutation && nonPythonTarget) {
          throw new Error("Drone write policy: shell command appears to mutate a non-Python file; no command was executed.")
        }
        if (/\b(?:Remove-Item|Move-Item|Rename-Item|unlink|rmdir|del|erase|move|ren|rename)\b/i.test(command)) {
          throw new Error("Drone write policy: shell delete/move/rename is Architect-only; no command was executed.")
        }
      }
    })
  },
})
