import { Plugin } from "@opencode/plugin"
import { execFileSync } from "node:child_process"
import { mkdir, open } from "node:fs/promises"
import { randomUUID } from "node:crypto"
import { scopedProviders } from "../lib/provider-scope.mjs"

const PROJECT = "L:\\LocalCoder"
const WORKSPACE = `${PROJECT}\\workspace`
const PYTHON = "L:\\.venv\\Scripts\\python.exe"
const RECEIPTS = `${PROJECT}\\.opencode\\receipts`
const ARCHITECT_GOAL_ID = "01a1e340-84ed-77c3-92f3-3eb738b89f5b"
const ROUTER_DB_TARGET = "L:\\LocalCoder\\workspace\\aios_rebuild\\memory\\aios_router\\router.sqlite3"
const ROUTER_DB_TARGETS = [
  ROUTER_DB_TARGET,
  `${ROUTER_DB_TARGET}-wal`,
  `${ROUTER_DB_TARGET}-shm`,
  `${ROUTER_DB_TARGET}-journal`,
]
const PRIVACY_HELPER = `${WORKSPACE}\\autonomy\\privacy_core_router_db_gate_queen_v1_candidate.py`
const DRONE_POSTAL_TOOLS = new Set([
  "aios_router_postal_register_drone",
  "aios_router_postal_drone_submit",
  "aios_router_postal_drone_read_inbox",
])
const MULTI_LANGUAGE_DRONE_WRITE_TOOLS = new Set([
  "edit",
  "write",
  "patch",
  "localcoder_patch",
  "localcoder_write_exact",
])
const QUEEN_POSTAL_TOOLS = new Set([
  "aios_router_postal_queen_list_drones",
  "aios_router_postal_queen_list_outbox",
  "aios_router_postal_queen_read_outbox",
  "aios_router_postal_queen_dispatch",
  "aios_router_postal_queen_summary",
])
const POSTAL_TOOLS = new Set([...DRONE_POSTAL_TOOLS, ...QUEEN_POSTAL_TOOLS])
const ROUTER_MUTATION_TOOLS = new Set([
  "aios_router_assign_drone_seed",
  "aios_router_open_build_task",
  "aios_router_accept_self_prompt",
  "aios_router_record_turn_result",
  "aios_router_complete_lane",
  "aios_router_verify_task",
  "aios_router_stop_task",
  ...POSTAL_TOOLS,
])
const DRONE_AGENT_IDS: Record<string, string> = {
  build: "localcoder-viv-drone-01",
  drone_build: "localcoder-viv-drone-01",
  drone_read: "localcoder-viv-drone-01",
}
type PostalActor = { role: "drone"; agent_id: string }
const postalActorsBySession = new Map<string, PostalActor>()

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

async function executeBodyGateWithRetry() {
  let verdict = executeBodyGate()
  let retryCount = 0
  const timedOut = (value: any) => Array.isArray(value?.reasons)
    && value.reasons.some((reason: unknown) => String(reason).includes("wsl_body_request_timed_out"))
  if (timedOut(verdict)) {
    await new Promise((resolve) => setTimeout(resolve, 250))
    retryCount = 1
    verdict = executeBodyGate()
  }
  return { ...verdict, gate_retry_count: retryCount }
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

async function recordGate(source: string, sessionID: string, verdict: any, postalActor?: PostalActor) {
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
      gate_retry_count: Number.isInteger(verdict.gate_retry_count) ? verdict.gate_retry_count : 0,
      ...(postalActor ? { postal_actor: postalActor } : {}),
      captured_at: new Date().toISOString(),
    }, null, 2), "utf8")
    await handle.sync()
  } finally {
    await handle.close()
  }
}

async function requireBodyGate(source: string, sessionID: string) {
  const toolName = source.startsWith("tool:") ? source.slice("tool:".length) : ""
  if (QUEEN_POSTAL_TOOLS.has(toolName)) {
    throw new Error("Queen-only postal tools are available only through the Architect-designated Queen bridge.")
  }
  const postalActor = DRONE_POSTAL_TOOLS.has(toolName) ? postalActorsBySession.get(sessionID) : undefined
  if (DRONE_POSTAL_TOOLS.has(toolName) && !postalActor) {
    throw new Error("Postal Drone tool requires a trusted Drone identity from this OpenCode session.")
  }
  if (toolName.startsWith("aios_router_postal_") && !POSTAL_TOOLS.has(toolName)) {
    throw new Error("Unrecognized postal tool is denied by the OpenCode Body gate.")
  }
  const verdict = await executeBodyGateWithRetry()
  const requiresPrivacyCore = ROUTER_MUTATION_TOOLS.has(toolName)
  if (requiresPrivacyCore) verdict.privacy_core = executePrivacyCoreGate()
  await recordGate(source, sessionID, verdict, postalActor)
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

// 8-law enforcement (enforce_morality) bridge, OFF by default. Set VIV_ENFORCE_LAWS=1
// to mount the Rust 8-law wall on every tool call. Fail-closed while on: a checker
// error denies the tool. Off = no-op (bootstrap phase).
const ENFORCE_LAWS = process.env.VIV_ENFORCE_LAWS === "1"
const ENFORCE_LAWS_CLI = `${WORKSPACE}\\autonomy\\enforce_laws_cli.py`

function enforceLaws(tool: string, input: any): { allowed: boolean; reason: string } {
  if (!ENFORCE_LAWS) return { allowed: true, reason: "laws_toggle_off" }
  let raw = ""
  try {
    raw = execFileSync(PYTHON, ["-B", ENFORCE_LAWS_CLI,
      "--tool-name", tool,
      "--params-json", JSON.stringify(input ?? {}),
      "--s-n", "1.0",
      "--forensic-buffer", "",
      "--raw-input", ""], {
      cwd: PROJECT,
      encoding: "utf8",
      timeout: 15000,
      windowsHide: true,
    })
  } catch (error: any) {
    raw = error?.stdout?.toString?.() ?? ""
  }
  try {
    const verdict = JSON.parse(raw)
    return { allowed: verdict.allowed !== false, reason: verdict.reason ?? "law_verdict_invalid" }
  } catch {
    return { allowed: !ENFORCE_LAWS, reason: "law_enforcement_unavailable" }
  }
}

export default Plugin.define({
  id: "localcoder.architect-body-gate",
  async setup(ctx) {
    // The hook API scopes one provider per registration, so a multi-provider
    // scope registers the same callback once per provider.
    const scopedHook = async (name: string, callback: (event: any) => Promise<void> | void) => {
      for (const providerID of scopedProviders()) await (ctx.session.hook as any)(name, callback, { providerID })
    }
    await scopedHook("context", async (event: any) => {
      const sessionID = String(event.sessionID ?? "")
      if (!sessionID) return
      const agentID = DRONE_AGENT_IDS[String(event.agent ?? "").toLowerCase()]
      if (!agentID) {
        postalActorsBySession.delete(sessionID)
        return
      }
      postalActorsBySession.set(sessionID, { role: "drone", agent_id: agentID })
      while (postalActorsBySession.size > 128) {
        postalActorsBySession.delete(postalActorsBySession.keys().next().value!)
      }
    })

    await scopedHook("http.request", async (event: any) => {
      await requireBodyGate(`model_request:${event.kind}`, String(event.sessionID ?? "unknown"))
    })

    await ctx.tool.hook("execute.before", async (event: any) => {
      await requireBodyGate(`tool:${String(event.tool)}`, String(event.sessionID ?? "unknown"))
      const laws = enforceLaws(String(event.tool), event.input)
      if (!laws.allowed) {
        throw new Error(`Rust 8-law enforcement denied ${String(event.tool)}: ${laws.reason}`)
      }
      const tool = String(event.tool).toLowerCase()
      if (["edit", "write", "patch", "localcoder_patch", "localcoder_write_exact", "localcoder_add_python", "delete", "remove", "move", "rename", "rmdir"].includes(tool)) {
        const paths = targetPaths(event.input)
        const allowedExtensions = [".py", ".rs", ".toml", ".json", ".md", ".txt", ".ps1", ".bat", ".sh", ".sql", ".yaml", ".yml", ".c", ".cpp", ".h", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".jsonc"]
        const sessionID = String(event.sessionID ?? "")
        const droneMultiLanguageWrite = postalActorsBySession.get(sessionID)?.role === "drone"
          && MULTI_LANGUAGE_DRONE_WRITE_TOOLS.has(tool)
        if (paths.length && !droneMultiLanguageWrite && !paths.some(path => allowedExtensions.some(ext => path.toLowerCase().endsWith(ext)))) {
          throw new Error(`Drone write policy: only project files (${allowedExtensions.join(", ")}) may be written; no file was changed.`)
        }
      }
    })
  },
})
