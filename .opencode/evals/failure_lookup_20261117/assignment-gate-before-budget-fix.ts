import { Plugin } from "@opencode/plugin"
import { createHash } from "node:crypto"
import { appendFile, mkdir, open, readFile, readdir } from "node:fs/promises"
import { isAbsolute, join, relative, resolve, sep } from "node:path"
import { fileURLToPath } from "node:url"

const GATE_TRACE_URL = new URL("../receipts/localcoder-drone-gate-trace.jsonl", import.meta.url)
const SESSION_SUMMARY_DIR = fileURLToPath(new URL("../session_summaries/", import.meta.url))

async function writeGateTrace(stage: string, fields: Record<string, unknown>) {
  try {
    await appendFile(GATE_TRACE_URL, JSON.stringify({ at: new Date().toISOString(), stage, ...fields }) + "\n", "utf8")
  } catch (error: any) {
    console.warn(`[localcoder-drone-assignment-gate] trace_write_failed reason=${String(error?.message ?? error)}`)
  }
}

type AssignmentState = {
  sessionID: string
  assignment: string
  sourceAssignment?: string
  assignmentHash: string
  taskID: string
  droneAgentID?: string
  droneSeed?: number
  droneStyleProfile?: DroneStyleProfile
  seedBootstrap?: boolean
  tools: string[]
  toolDefinitions?: Record<string, any>
  completed: string[]
  toolResults: Array<{ tool: string; output: string; outputLength: number; exitCode?: number }>
  lastToolResult?: { tool: string; output: string; outputLength: number; exitCode?: number }
  activeLaneTurn?: number
  grantedTool?: string
  awaitingToolExecution: boolean
  pending?: string
  failed: boolean
  planOnly: boolean
  continuationCount: number
  continuedMessageSteps: Set<string>
}

type DroneStyleProfile = {
  warmth_percent: number
  directness_percent: number
  playfulness_percent: number
  detail_percent: number
}

type DroneSeedBinding = {
  agentID: string
  seed: number
  styleProfile: DroneStyleProfile
}

const PLAN_MARKER = "[DRONE PLAN ONLY | NO TOOLS]"
const CONTINUATION_MARKER = "[LOCALCODER PRIVATE DRONE CONTINUATION | v1]"
const DRONE_SEED_LOOKUP_TOOL = "aios_router_lookup_drone_seed"
const ASSIGNMENT_MARKER = "[ARCHITECT ASSIGNMENT | CURRENT AND AUTHORIZED]"
const AUTHORIZATION_MARKER = "[CURRENT AUTHORIZATION FACT]"
const DRONE_AGENT_IDS: Record<string, string> = {
  build: "localcoder-viv-drone-01",
  drone_build: "localcoder-viv-drone-01",
  drone_read: "localcoder-viv-drone-01",
}
const CONVERSATION_READ_ONLY_TOOLS = new Set([
  "read", "glob", "grep", "search", "skill", "localcoder_status", "localcoder_memory_read",
])
const DIRECT_CODING_TOOLS = new Set([
  "localcoder_add_python", "localcoder_patch", "localcoder_write_exact", "write", "edit", "patch", "shell", "delete", "remove", "move", "rename",
])
const MAX_AUTOMATIC_CONTINUATIONS = 16
const ROUTER_BINDING_FIELDS = new Set(["session_id", "task_id", "assignment_hash"])
const ROUTER_MUTATION_TOOLS = new Set([
  "aios_router_assign_drone_seed",
  "aios_router_open_build_task",
  "aios_router_accept_self_prompt",
  "aios_router_record_turn_result",
  "aios_router_complete_lane",
  "aios_router_stop_task",
  "aios_router_postal_register_drone",
  "aios_router_postal_drone_submit",
  "aios_router_postal_drone_read_inbox",
  "aios_router_postal_queen_list_drones",
  "aios_router_postal_queen_list_outbox",
  "aios_router_postal_queen_read_outbox",
  "aios_router_postal_queen_dispatch",
  "aios_router_postal_queen_summary",
])
const DRONE_POSTAL_TOOLS = new Set([
  "aios_router_postal_register_drone",
  "aios_router_postal_drone_submit",
  "aios_router_postal_drone_read_inbox",
])
const QUEEN_POSTAL_TOOLS = new Set([
  "aios_router_postal_queen_list_drones",
  "aios_router_postal_queen_list_outbox",
  "aios_router_postal_queen_read_outbox",
  "aios_router_postal_queen_dispatch",
  "aios_router_postal_queen_summary",
])
const states = new Map<string, AssignmentState>()
const droneAgentBySession = new Map<string, string>()
const currentPromptHashBySession = new Map<string, string>()
const cDriveDeniedBySession = new Map<string, string>()
const summaryWrittenBySession = new Map<string, string>()
const inspectionBudgetsBySession = new Map<string, { turnKey: string; limit: number; used: number }>()
const directUserTurnBySession = new Map<string, string>()
const FILE_INSPECTION_TOOLS = new Set(["read", "glob", "grep", "search", "localcoder_memory_read"])
const seedBindingsBySession = new Map<string, DroneSeedBinding>()
const continuationFlights = new Set<string>()
const recentToolCallsBySession = new Map<string, { tool: string; inputHash: string; count: number }>()

function assignmentIdentity(sessionID: string, assignment: string) {
  const assignmentHash = createHash("sha256").update(assignment.trim(), "utf8").digest("hex")
  const taskID = `oc_${createHash("sha256").update(`${sessionID}\n${assignmentHash}`, "utf8").digest("hex")}`
  return { assignmentHash, taskID }
}

function optionalizeTrustedRouterInputs(event: any, names: string[]) {
  for (const name of names) {
    if (!ROUTER_MUTATION_TOOLS.has(name) && name !== "aios_router_queen_summary") continue
    const schema = event.tools?.[name]?.input
    if (!schema || typeof schema !== "object") continue
    const hiddenFields = new Set(name === "aios_router_queen_summary" ? ["task_id"] : ROUTER_BINDING_FIELDS)
    if (DRONE_POSTAL_TOOLS.has(name)) hiddenFields.add("agent_id")
    if (name === "aios_router_open_build_task") {
      hiddenFields.add("assignment")
      hiddenFields.add("max_turns_per_lane")
    } else if (name === "aios_router_accept_self_prompt") {
      hiddenFields.add("turn")
      hiddenFields.add("prompt")
    } else if (name === "aios_router_record_turn_result") {
      hiddenFields.add("turn")
    }
    if (Array.isArray(schema.required)) {
      schema.required = schema.required.filter((field: unknown) => !hiddenFields.has(String(field)))
    }
    if (schema.properties && typeof schema.properties === "object") {
      for (const field of hiddenFields) delete schema.properties[field]
      if (["aios_router_accept_self_prompt", "aios_router_record_turn_result", "aios_router_complete_lane"].includes(name)
          && schema.properties.lane_id && typeof schema.properties.lane_id === "object") {
        schema.properties.lane_id.enum = ["drone"]
      }
    }
  }
}

function injectTrustedRouterInput(event: any, state: AssignmentState) {
  const name = String(event.tool)
  if (!name.startsWith("aios_router_")) return
  if (name === "aios_router_router_status" || name === "aios_router_classify_task") return
  if (name === "aios_router_lookup_drone_seed") {
    const input = event.input
    if (!input || typeof input !== "object" || Array.isArray(input)) {
      throw new Error(`Router tool ${name} requires a JSON object; no tool was executed.`)
    }
    const requestedAgentID = typeof input.agent_id === "string" ? input.agent_id : ""
    if (!requestedAgentID || requestedAgentID !== state.droneAgentID) {
      throw new Error("Drone seed lookup is limited to the exact identity bound to this OpenCode session.")
    }
    return
  }
  const input = event.input
  if (!input || typeof input !== "object" || Array.isArray(input)) {
    throw new Error(`Router tool ${name} requires a JSON object; no tool was executed.`)
  }

  if (QUEEN_POSTAL_TOOLS.has(name)) {
    throw new Error("Queen-only postal tools cannot be invoked by a Drone OpenCode session.")
  }
  if (DRONE_POSTAL_TOOLS.has(name)) {
    const trustedAgentID = state.droneAgentID
    const requestedAgentID = typeof input.agent_id === "string" ? input.agent_id : ""
    if (!trustedAgentID || (requestedAgentID && requestedAgentID !== trustedAgentID)) {
      throw new Error("Postal Drone tools are bound to the one Drone identity authorized for this OpenCode session.")
    }
    event.input = {
      ...input,
      session_id: state.sessionID,
      task_id: state.taskID,
      assignment_hash: state.assignmentHash,
      agent_id: trustedAgentID,
    }
    return
  }

  if (name === "aios_router_queen_summary") {
    const taskMismatch = Object.prototype.hasOwnProperty.call(input, "task_id") && input.task_id !== state.taskID
    if (taskMismatch) console.warn(`[localcoder-drone-assignment-gate] overwrote_untrusted_router_binding session=${state.sessionID} tool=${name} task_id_mismatch=true`)
    event.input = { ...input, task_id: state.taskID }
    return
  }
  if (!ROUTER_MUTATION_TOOLS.has(name)) {
    throw new Error(`Router tool ${name} has no current trusted binding contract; no tool was executed.`)
  }

  const trusted = {
    session_id: state.sessionID,
    task_id: state.taskID,
    assignment_hash: state.assignmentHash,
  }
  if (name === "aios_router_assign_drone_seed") {
    const requestedAgentID = typeof input.agent_id === "string" ? input.agent_id : ""
    if (!requestedAgentID
        || requestedAgentID !== state.droneAgentID
        || !state.assignment.includes(requestedAgentID)) {
      throw new Error("Drone seed allocation is limited to an agent_id named verbatim in the Architect assignment.")
    }
  }
  const mismatches = Object.fromEntries(Object.entries(trusted).map(([field, value]) => [
    field,
    Object.prototype.hasOwnProperty.call(input, field) && input[field] !== value,
  ]))
  if (Object.values(mismatches).some(Boolean)) {
    console.warn(`[localcoder-drone-assignment-gate] overwrote_untrusted_router_binding session=${state.sessionID} tool=${name} session_id_mismatch=${mismatches.session_id} task_id_mismatch=${mismatches.task_id} assignment_hash_mismatch=${mismatches.assignment_hash}`)
  }
  const bound: Record<string, any> = { ...input, ...trusted }
  if (name === "aios_router_open_build_task") {
    const assignmentMismatch = Object.prototype.hasOwnProperty.call(input, "assignment") && input.assignment !== state.assignment
    if (assignmentMismatch) console.warn(`[localcoder-drone-assignment-gate] overwrote_untrusted_router_assignment session=${state.sessionID} tool=${name} assignment_mismatch=true`)
    bound.assignment = state.assignment
    bound.lane_ids = Array.isArray(input.lane_ids) && input.lane_ids.length ? input.lane_ids : ["drone"]
    bound.max_turns_per_lane = 8
  } else if (name === "aios_router_accept_self_prompt") {
    bound.lane_id = "drone"
    bound.turn = state.activeLaneTurn ?? 0
    bound.prompt = state.lastAcceptedSelfPrompt
      || (typeof input.prompt === "string" && input.prompt.trim() ? input.prompt.trim() : state.assignment)
  } else if (name === "aios_router_record_turn_result") {
    bound.lane_id = "drone"
    bound.turn = state.activeLaneTurn ?? 0
    if (typeof bound.result !== "string" || !bound.result.trim()) {
      bound.result = state.lastToolResult?.output || "completed"
    }
  } else if (name === "aios_router_complete_lane") {
    bound.lane_id = "drone"
    if (typeof bound.receipt !== "string" || !bound.receipt.trim()) {
      bound.receipt = state.lastToolResult?.output || "lane_completed"
    }
  }
  event.input = bound
}

function routerResponseAccepted(value: any, depth = 0): boolean | undefined {
  if (depth > 8 || value == null) return undefined
  if (typeof value === "string") {
    try { return routerResponseAccepted(JSON.parse(value), depth + 1) }
    catch { return undefined }
  }
  if (Array.isArray(value)) {
    const statuses = value.map((item) => routerResponseAccepted(item, depth + 1)).filter((item): item is boolean => typeof item === "boolean")
    return statuses.length ? statuses.every(Boolean) : undefined
  }
  if (typeof value !== "object") return undefined
  if (typeof value.ok === "boolean") return value.ok
  for (const key of ["content", "output", "text", "result", "structuredContent", "data"]) {
    if (Object.prototype.hasOwnProperty.call(value, key)) {
      const accepted = routerResponseAccepted(value[key], depth + 1)
      if (typeof accepted === "boolean") return accepted
    }
  }
  return undefined
}

function keepOnlyCurrentTools(event: any, names: string[]) {
  const allowed = new Set(names)
  for (const name of Object.keys(event.tools ?? {})) {
    if (!allowed.has(name)) delete event.tools[name]
  }
}

function cloneToolDefinition(value: any): any {
  if (Array.isArray(value)) return value.map(cloneToolDefinition)
  if (!value || typeof value !== "object") return value
  const copy: Record<string, any> = {}
  for (const [key, item] of Object.entries(value)) copy[key] = cloneToolDefinition(item)
  return copy
}

function captureToolDefinitions(event: any, names: string[]): Record<string, any> {
  const definitions: Record<string, any> = {}
  for (const name of new Set(names)) {
    const definition = event.tools?.[name]
    if (definition) definitions[name] = cloneToolDefinition(definition)
  }
  return definitions
}

function restoreToolDefinitions(event: any, state: AssignmentState, names: string[]): boolean {
  if (!event.tools || typeof event.tools !== "object") event.tools = {}
  for (const name of names) {
    if (event.tools[name]) continue
    const definition = state.toolDefinitions?.[name]
    if (!definition) return false
    event.tools[name] = cloneToolDefinition(definition)
  }
  return names.every((name) => Boolean(event.tools[name]))
}

function assignedPythonTarget(assignment: string): string | undefined {
  // Read-only source paths may also be listed; only an Add/Create line grants a destination.
  const matches = assignment.split(/\r?\n/).flatMap((line) => {
    const match = line.match(/^\s*(?:[-*]\s*)?(?:add|create)\b[^`\r\n]*\bfile\b[^`\r\n]*`((?:workspace[\\/]|[DEFL]:[\\/])[^`\s"'<>]+?\.py)`/i)
    return match ? [match[1].replace(/\\/g, "/")] : []
  })
  const unique = [...new Map(matches.map((target) => [target.toLocaleLowerCase(), target])).values()]
  if (unique.length !== 1) return undefined
  const target = unique[0]
  const drivePath = /^[DEFL]:\//i.test(target)
  const segments = target.split("/").filter((segment, index) => !(drivePath && index === 0))
  if ((!drivePath && !target.toLocaleLowerCase().startsWith("workspace/"))
      || segments.some((segment) => !segment || segment === "." || segment === "..")) return undefined
  return target
}

function assignedReadTargets(assignment: string): string[] {
  const targets: string[] = []
  for (const line of assignment.split(/\r?\n/)) {
    const pattern = /\b(?:call|use|invoke|run)\s+(?:the\s+)?(?:`|'|")?read(?:`|'|")?(?:\s+tool)?\s+(?:on|at)\s+[`'"]([^`'"]+)[`'"]/gi
    for (const match of line.matchAll(pattern)) {
      const target = match[1].trim()
      if (target) targets.push(target)
    }
  }
  return targets
}

function assignedReadTarget(assignment: string, completed: string[]): string | undefined {
  const readIndex = completed.filter((tool) => tool === "read").length
  return assignedReadTargets(assignment)[readIndex]
}

function projectRelativeToolPath(value: unknown): string | undefined {
  if (typeof value !== "string" || !value.trim()) return undefined
  const raw = value.trim()
  if (raw.split(/[\\/]+/).some((segment) => segment === "." || segment === "..")) return undefined
  const projectRoot = resolve("L:\\LocalCoder")
  const candidate = isAbsolute(raw) ? resolve(raw) : resolve(projectRoot, raw)
  const rel = relative(projectRoot, candidate)
  if (!rel || rel === ".." || rel.startsWith(".." + sep) || isAbsolute(rel)) return undefined
  return rel.replace(/[\\/]+/g, "/").toLocaleLowerCase()
}

function constrainAddPythonTarget(event: any, assignment: string, names: string[]): boolean {
  if (!names.includes("localcoder_add_python")) return true
  const target = assignedPythonTarget(assignment)
  const filePath = event.tools?.localcoder_add_python?.input?.properties?.filePath
  if (!target || !filePath || typeof filePath !== "object") {
    if (event.tools) delete event.tools.localcoder_add_python
    return false
  }
  filePath.enum = [target]
  filePath.description = `Exact Architect-authorized project-relative destination: ${target}.`
  const contentProp = event.tools?.localcoder_add_python?.input?.properties?.content
  if (contentProp && typeof contentProp === "object") {
    const lineLimit = assignment.match(/\bunder\s+(\d+)\s+(?:physical\s+)?lines?\b/i)?.[1]
    const passMarker = assignment.match(/`(PASS:\s*\d+\s+checks)`/)?.[1]
    const hints = ["Python source text for the new file."]
    if (lineLimit) hints.push(`Keep the file strictly under ${lineLimit} physical lines (aim for 45-65 lines; do not copy _cli_path or _rust_preflight).`)
    if (/\bV7\./.test(assignment)) hints.push('Use `import run_visible_drone_cycle_v7 as V7`. In `run_cycle(assignment: str, seconds: int = 120)`, save `orig_goal = V7.ARCHITECT_GOAL_ID` and `orig_tools = V7.SUPPORTED_TOOLS`, set `V7.ARCHITECT_GOAL_ID = "01a1e340-84ed-77c3-92f3-3eb738b89f5b"` and `V7.SUPPORTED_TOOLS = frozenset(V7.SUPPORTED_TOOLS) | {"aios_router_lookup_drone_seed"}` in `try:`, `return V7.run_cycle(assignment, seconds=seconds)`, and restore both in `finally:`.')
    if (passMarker) hints.push(`Support positional \`assignment_file\` (nargs="?", type=Path), \`--seconds\` (type=int, default=120), and \`--self-check\` (action="store_true"). For \`--self-check\`, save \`orig_run = V7.run_cycle\`, \`orig_goal = V7.ARCHITECT_GOAL_ID\`, \`orig_tools = V7.SUPPORTED_TOOLS\`, set \`seen = {}\` and \`V7.run_cycle = lambda a, seconds=120: seen.update(goal=V7.ARCHITECT_GOAL_ID, has_seed="aios_router_lookup_drone_seed" in V7.SUPPORTED_TOOLS) or {"ok": True}\`, call \`res = run_cycle("check", seconds=30)\` inside \`try:/finally: V7.run_cycle = orig_run\`, assert \`seen.get("goal") == ARCHITECT_GOAL_ID and seen.get("has_seed") is True and res == {"ok": True} and V7.ARCHITECT_GOAL_ID == orig_goal and V7.SUPPORTED_TOOLS == orig_tools\`, then \`print("${passMarker}")\` and \`sys.exit(0)\`. When not \`--self-check\`, read \`assignment_file.read_text(encoding="utf-8-sig")\` and print \`json.dumps(run_cycle(...))\`.`)
    contentProp.description = hints.join(" ")
  }
  return true
}

function assignedShellCommand(assignment: string): string | undefined {
  const matches = [...assignment.matchAll(/\b(?:call|use|invoke|run)\s+(?:the\s+)?(?:`|'|")?shell(?:`|'|")?(?:\s+tool)?\s+with\s+(?:exactly\s+)?`([^`]+)`/gi)]
  if (matches.length !== 1) return undefined
  const command = matches[0][1].trim()
  return command || undefined
}

function constrainAssignedToolInputs(
  event: any,
  assignment: string,
  names: string[],
  completed: string[],
  droneAgentID?: string,
): boolean {
  if (!constrainAddPythonTarget(event, assignment, names)) return false
  if (!constrainDroneSeedTarget(event, names, droneAgentID)) return false
  if (names.includes("shell")) {
    const cmd = assignedShellCommand(assignment)
    const commandProp = event.tools?.shell?.input?.properties?.command
    if (cmd && commandProp && typeof commandProp === "object") {
      commandProp.enum = [cmd]
      commandProp.description = `Exact shell command from the Architect assignment: ${cmd}.`
    }
  }
  if (!names.includes("read")) return true
  const target = assignedReadTarget(assignment, completed)
  if (!target) return true
  const path = event.tools?.read?.input?.properties?.path
  if (!path || typeof path !== "object") {
    if (event.tools) delete event.tools.read
    return false
  }
  path.enum = [target]
  path.description = `Exact path for this read step from the Architect assignment: ${target}.`
  return true
}

function roleOf(message: any): string {
  return String(message?.info?.role ?? message?.info?.type ?? message?.role ?? message?.type ?? "")
}

function textOf(message: any): string {
  if (typeof message?.info?.text === "string") return message.info.text
  if (typeof message?.text === "string") return message.text
  if (typeof message?.content === "string") return message.content
  const parts = Array.isArray(message?.parts) ? message.parts : Array.isArray(message?.content) ? message.content : []
  return parts.map((part: any) => typeof part?.text === "string" ? part.text : "").filter(Boolean).join("\n")
}

function setUserMessageText(message: any, text: string): boolean {
  if (typeof message?.info?.text === "string") {
    message.info.text = text
    return true
  }
  if (typeof message?.text === "string") {
    message.text = text
    return true
  }
  if (typeof message?.content === "string") {
    message.content = text
    return true
  }
  const parts = Array.isArray(message?.parts) ? message.parts : Array.isArray(message?.content) ? message.content : undefined
  if (!parts) return false
  let firstText = -1
  for (let index = 0; index < parts.length; index++) {
    if (typeof parts[index]?.text === "string") { firstText = index; break }
  }
  if (firstText < 0) {
    parts.unshift({ type: "text", text })
    return true
  }
  parts[firstText] = { ...parts[firstText], text }
  for (let index = firstText + 1; index < parts.length; index++) {
    if (typeof parts[index]?.text === "string") parts[index] = { ...parts[index], text: "" }
  }
  return true
}

function injectSeedPreflightPrompt(event: any, agentID: string): boolean {
  const messages = Array.isArray(event.messages) ? event.messages : []
  for (let index = messages.length - 1; index >= 0; index--) {
    const message = messages[index]
    if (roleOf(message) !== "user") continue
    const prompt = textOf(message)
    const markerAt = prompt.indexOf(ASSIGNMENT_MARKER)
    if (markerAt < 0) return false
    if (prompt.includes("[LOCALCODER REQUIRED SEED PREFLIGHT]")) return true
    const markerEnd = markerAt + ASSIGNMENT_MARKER.length
    const newline = prompt.indexOf("\n", markerEnd)
    const insertAt = newline < 0 ? markerEnd : newline + 1
    const instruction = `[LOCALCODER REQUIRED SEED PREFLIGHT]\nUse the ${DRONE_SEED_LOOKUP_TOOL} tool with agent_id ${agentID} before every other assigned tool.\n`
    const rewritten = prompt.slice(0, insertAt) + instruction + prompt.slice(insertAt)
    return setUserMessageText(message, rewritten)
  }
  return false
}

function toolOutputText(value: any, depth = 0): string {
  if (depth > 8 || value == null) return ""
  if (typeof value === "string") return value
  if (Array.isArray(value)) {
    return value.map((item) => toolOutputText(item, depth + 1)).filter(Boolean).join("\n")
  }
  if (typeof value !== "object") return ""
  if (value.type === "text" && typeof value.text === "string") return value.text
  for (const key of ["content", "output", "text", "result", "structuredContent", "data"]) {
    if (!Object.prototype.hasOwnProperty.call(value, key)) continue
    const text = toolOutputText(value[key], depth + 1)
    if (text) return text
  }
  return ""
}

function validDroneStyleProfile(value: any): DroneStyleProfile | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined
  const keys = ["warmth_percent", "directness_percent", "playfulness_percent", "detail_percent"] as const
  const profile = {} as DroneStyleProfile
  for (const key of keys) {
    const amount = value[key]
    if (!Number.isSafeInteger(amount) || amount < 0 || amount > 100) return undefined
    profile[key] = amount
  }
  return profile
}

function findRouterSeedBinding(value: any, expectedAgentID: string, depth = 0): DroneSeedBinding | undefined {
  if (depth > 8 || value == null) return undefined
  if (typeof value === "string") {
    try { return findRouterSeedBinding(JSON.parse(value), expectedAgentID, depth + 1) }
    catch { return undefined }
  }
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = findRouterSeedBinding(item, expectedAgentID, depth + 1)
      if (found) return found
    }
    return undefined
  }
  if (typeof value !== "object") return undefined
  if (value.agent_id === expectedAgentID
      && Number.isSafeInteger(value.seed)
      && value.seed > 0
      && value.seed <= 0x7fffffff) {
    const styleProfile = validDroneStyleProfile(value.style_profile)
    if (styleProfile) return { agentID: expectedAgentID, seed: value.seed, styleProfile }
  }
  for (const key of ["structuredContent", "content", "result", "data", "output", "text"]) {
    if (!Object.prototype.hasOwnProperty.call(value, key)) continue
    const found = findRouterSeedBinding(value[key], expectedAgentID, depth + 1)
    if (found) return found
  }
  return undefined
}

function routerSeedBinding(result: any, expectedAgentID: string): DroneSeedBinding | undefined {
  if (result?.isError === true || result?.error) return undefined
  return findRouterSeedBinding(result, expectedAgentID)
    ?? findRouterSeedBinding(toolOutputText(result), expectedAgentID)
}

function replaceSeedProfileInstruction(event: any, binding?: DroneSeedBinding) {
  const system = Array.isArray(event.system) ? event.system : []
  const replacement = binding
    ? "Use the Rust Router-verified seed-derived conversational profile appended below."
    : "Use neutral phrasing until this Drone session receives its Rust Router-verified seed profile."
  const staticProfile = /Seed-derived conversational bias only:[^\r\n]*/g
  for (const part of system) {
    if (typeof part?.text === "string") part.text = part.text.replace(staticProfile, replacement)
  }
  if (binding) {
    const profile = binding.styleProfile
    system.push({
      type: "text",
      text: `[RUST ROUTER VERIFIED DRONE PROFILE]\nDrone ID: ${binding.agentID}\nWarmth: ${profile.warmth_percent}%; directness: ${profile.directness_percent}%; playfulness: ${profile.playfulness_percent}%; detail: ${profile.detail_percent}%. Apply only subtly to conversational phrasing; never alter code, evidence, tool choice, safety, or authority.`,
    })
  }
  event.system = system
}

async function applySeedForRequest(event: any, sessionID: string, expectedAgentID?: string) {
  const binding = seedBindingsBySession.get(sessionID)
  if (!binding) return false
  if (expectedAgentID && expectedAgentID !== binding.agentID) {
    seedBindingsBySession.delete(sessionID)
    await writeGateTrace("drone_seed_binding_cleared", {
      sessionID,
      prior_agent_id: binding.agentID,
      requested_agent_id: expectedAgentID,
      reason: "session_identity_changed",
    })
    return false
  }
  if (!event.options || typeof event.options !== "object") event.options = {}
  event.options.seed = binding.seed
  replaceSeedProfileInstruction(event, binding)
  await writeGateTrace("drone_seed_applied", {
    sessionID,
    agent_id: binding.agentID,
    seed_sha256: createHash("sha256").update(String(binding.seed), "utf8").digest("hex"),
    request_kind: event.kind ?? "primary",
    model_id: event.model?.id ?? null,
    style_profile: binding.styleProfile,
  })
  return true
}

async function applyCachedSeedOnly(event: any) {
  const sessionID = String(event.sessionID ?? "")
  if (!sessionID || event.model?.providerID !== "lmstudio") return
  await applySeedForRequest(event, sessionID)
}

function constrainDroneSeedTarget(event: any, names: string[], agentID?: string): boolean {
  for (const name of ["aios_router_lookup_drone_seed", "aios_router_assign_drone_seed"]) {
    if (!names.includes(name)) continue
    const property = event.tools?.[name]?.input?.properties?.agent_id
    if (!agentID || !property || typeof property !== "object") {
      if (event.tools) delete event.tools[name]
      return false
    }
    property.enum = [agentID]
    property.description = `Exact Router-registered Drone identity for this session: ${agentID}.`
  }
  return true
}

function appendSeedBootstrapInstruction(event: any, agentID: string) {
  if (!Array.isArray(event.system)) event.system = []
  event.system.push({
    type: "text",
    text: `[LOCALCODER DRONE SEED BOOTSTRAP]\nThis session has no verified Router seed yet. Call only the ${DRONE_SEED_LOOKUP_TOOL} tool with agent_id exactly ${agentID} before answering or taking any other action. This is a read-only lookup. Do not invent a seed or claim work completed. Continue only after a successful Rust Router result is bound to this session.`,
  })
}

function latestUserText(messages: any[]): string {
  for (let index = messages.length - 1; index >= 0; index--) {
    const message = messages[index]
    if (message?.type === "synthetic" || message?.info?.type === "synthetic") continue
    if (textOf(message).startsWith("Instructions from: ")) continue
    if (roleOf(messages[index]) === "user") return textOf(messages[index])
  }
  return ""
}

function contextMessages(value: any): any[] {
  if (Array.isArray(value)) return value
  if (!value || typeof value !== "object") return []
  for (const key of ["messages", "data", "context", "items"]) {
    if (Array.isArray(value[key])) return value[key]
  }
  if (Object.keys(value).every((key) => /^\d+$/.test(key))) return Object.values(value)
  return []
}

function latestAssistantMessage(messages: any[]): { id: string; text: string } | undefined {
  for (let index = messages.length - 1; index >= 0; index--) {
    const message = messages[index]
    if (roleOf(message) !== "assistant") continue
    const parts = Array.isArray(message?.parts) ? message.parts : []
    const content = Array.isArray(message?.content) ? message.content : []
    const visibleParts = parts.filter((part: any) => part?.type === "text" && typeof part.text === "string")
    const fallbackVisibleParts = content.filter((part: any) => part?.type === "text" && typeof part.text === "string")
    const text = (visibleParts.length ? visibleParts : fallbackVisibleParts)
      .map((part: any) => part.text)
      .join("\n")
    return { id: String(message?.info?.id ?? message?.id ?? ""), text }
  }
  return undefined
}

function hasCDriveReference(value: string): boolean {
  return /\bC:/i.test(value)
}

function sessionKey(sessionID: string): string {
  return createHash("sha256").update(sessionID, "utf8").digest("hex").slice(0, 12)
}

function summaryExcerpt(value: string, limit = 900): string {
  return value
    .replace(/\bBearer\s+[^\s"']+/gi, "Bearer [redacted]")
    .replace(/\b(api[_-]?key|password|token|secret)\s*[:=]\s*[^\s"'`,;]+/gi, "$1=[redacted]")
    .replace(/\bsk-[A-Za-z0-9_-]{12,}\b/gi, "[secret redacted]")
    .replace(/\blmstudio_[A-Za-z0-9_-]{12,}\b/gi, "[secret redacted]")
    .replace(/\bC:[\\/][^\s"'`<>]*/gi, "[C-drive path redacted]")
    .replace(/[\r\t]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, limit)
}

function visibleSummaryText(message: any): string {
  const parts = Array.isArray(message?.parts) ? message.parts
    : Array.isArray(message?.content) ? message.content : []
  const visible = parts.filter((part: any) => part?.type === "text" && typeof part.text === "string")
    .map((part: any) => part.text).join("\n")
  if (visible) return visible
  if (typeof message?.info?.text === "string") return message.info.text
  if (typeof message?.text === "string") return message.text
  return typeof message?.content === "string" ? message.content : ""
}

async function latestPriorSessionSummary(sessionID: string): Promise<string> {
  try {
    const ownKey = sessionKey(sessionID)
    const names = (await readdir(SESSION_SUMMARY_DIR))
      .filter((name) => name.endsWith(".md") && !name.includes(`-${ownKey}-`))
      .sort().reverse()
    for (const name of names.slice(0, 4)) {
      const content = await readFile(join(SESSION_SUMMARY_DIR, name), "utf8")
      if (content.trim()) return content.slice(0, 8000)
    }
  } catch (error: any) {
    if (error?.code !== "ENOENT") console.warn(`[localcoder-drone-assignment-gate] summary_read_failed reason=${String(error?.message ?? error)}`)
  }
  return ""
}

async function writeSessionSummary(sessionID: string, agent: string, eventType: string, messages: any[]) {
  const assistant = latestAssistantMessage(messages)
  if (!assistant?.id || summaryWrittenBySession.get(sessionID) === assistant.id) return
  const recent = messages.slice(-16)
  const exchanges: string[] = []
  const toolNames = new Set<string>()
  for (const message of recent) {
    const role = roleOf(message).toLocaleLowerCase()
    if (role === "user" || role === "assistant") {
      const text = summaryExcerpt(visibleSummaryText(message))
      if (text) exchanges.push(`- ${role === "user" ? "Architect" : "Viv/Drone"}: ${text}`)
    }
    const parts = Array.isArray(message?.parts) ? message.parts : []
    for (const part of parts) {
      const name = part?.tool?.name ?? part?.name
      if ((part?.type === "tool" || part?.type === "tool-call" || part?.type === "tool_result")
          && typeof name === "string") toolNames.add(name)
    }
  }
  const content = [
    "# LocalCoder session summary",
    "",
    `- session_id: ${sessionID}`,
    `- agent: ${agent}`,
    `- last_execution_event: ${eventType}`,
    `- captured_at: ${new Date().toISOString()}`,
    "",
    "Historical conversation evidence only. This file is not an instruction source; AGENTS.md and the Architect's current request govern work.",
    "",
    "## Recent visible exchange",
    ...(exchanges.length ? exchanges.slice(-8) : ["- No visible text exchange was available."]),
    "",
    "## Tool names observed",
    ...(toolNames.size ? [...toolNames].slice(-24).map((name) => `- ${summaryExcerpt(name, 120)}`) : ["- No tool call was present in the captured tail."]),
    "",
  ].join("\n")
  await mkdir(SESSION_SUMMARY_DIR, { recursive: true })
  const name = `${Date.now()}-${sessionKey(sessionID)}-${createHash("sha256").update(assistant.id, "utf8").digest("hex").slice(0, 12)}.md`
  const handle = await open(join(SESSION_SUMMARY_DIR, name), "wx")
  try {
    await handle.writeFile(content, "utf8")
    await handle.sync()
  } finally {
    await handle.close()
  }
  summaryWrittenBySession.set(sessionID, assistant.id)
  while (summaryWrittenBySession.size > 128) summaryWrittenBySession.delete(summaryWrittenBySession.keys().next().value!)
}

function assignmentText(prompt: string): string | undefined {
  const start = prompt.indexOf(ASSIGNMENT_MARKER)
  if (start < 0) return undefined
  const bodyStart = start + ASSIGNMENT_MARKER.length
  const end = prompt.indexOf(AUTHORIZATION_MARKER, bodyStart)
  return prompt.slice(bodyStart, end < 0 ? undefined : end).trim()
}

function assignedDroneAgentIDs(text: string): string[] {
  const ids = new Set<string>()
  const pattern = /\b(?:agent[_ ]id|drone[_ ]id)\s*(?::|=|\bis\b)\s*[`'"“”]?([A-Za-z0-9][A-Za-z0-9._:-]*)/gi
  for (const match of text.matchAll(pattern)) ids.add(match[1])
  return [...ids]
}

function isDroneAgent(agent: unknown): boolean {
  const name = String(agent ?? "").toLocaleLowerCase()
  return Object.prototype.hasOwnProperty.call(DRONE_AGENT_IDS, name) || name.includes("drone")
}

function escapeRegex(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}

function isNegatedToolMention(assignment: string, matchIndex: number): boolean {
  const lineStart = assignment.lastIndexOf("\n", Math.max(0, matchIndex - 1)) + 1
  const linePrefix = assignment.slice(lineStart, matchIndex)
  return /\b(?:do\s+not|don't|dont|never|must\s+not|mustn't|should\s+not|shouldn't|cannot|can't|avoid)\b/i.test(linePrefix)
}

function requestedTools(assignment: string, available: string[]): string[] {
  const matches: Array<{ name: string; index: number }> = []
  for (const name of new Set(available)) {
    const escaped = escapeRegex(name)
    const pattern = new RegExp(String.raw`\b(?:use|call|invoke|run|apply)\s+(?:the\s+)?(?:\x60|'|")?${escaped}(?:\x60|'|")?(?:\s+tool\b)?`, "gi")
    for (const match of assignment.matchAll(pattern)) {
      if (isNegatedToolMention(assignment, match.index ?? 0)) continue
      matches.push({ name, index: match.index ?? 0 })
    }
  }
  return matches.sort((left, right) => left.index - right.index).map((match) => match.name)
}

function explicitlyReadOnly(prompt: string): boolean {
  const scopeException = String.raw`(?!\s+(?:any\s+)?(?:other|another|additional|unrelated|unrequested|except)\b|\s+to\s+(?:(?:the|a|this)\s+)?(?:named|specified|target|fixture)\b|\s+(?:files?\s+)?outside\b)`
  const noMutation = new RegExp(String.raw`\b(?:do not|don't|dont|never)\s+(?:(?:make|perform)\s+)?(?:any\s+)?(?:file\s+)?(?:edits?|changes?|modifications?|writes?|deletions?)\b${scopeException}`, "i").test(prompt)
  const noMutationPhrase = new RegExp(String.raw`\bno\s+(?:file\s+)?(?:edits?|changes?|modifications?|writes?|deletions?)\b${scopeException}`, "i").test(prompt)
  const withoutMutation = new RegExp(String.raw`\bwithout\s+(?:editing|changing|modifying|writing|deleting)\b${scopeException}`, "i").test(prompt)
  return /\bread[- ]only\b/i.test(prompt)
    || noMutation
    || noMutationPhrase
    || withoutMutation
}

function isDirectCodingPrompt(prompt: string): boolean {
  if (!prompt.trim() || explicitlyReadOnly(prompt)) return false
  return /(?:^|[\s`"'(\[])(?:[A-Za-z]:[\\/])?(?:[\w.-]+[\\/])*[\w.-]+\.(?:py|rs|toml|json|md|txt|sh|ps1|sql|ts|tsx|js|jsx|mjs|cjs|html|css|scss|vue|svelte|go|java|kt|cs|cpp|h|hpp|xml|yaml|yml)\b/i.test(prompt)
    || /<localcoder_patch_paths>/i.test(prompt)
    || /\b(?:create|add|write|patch|edit|run|test|pytest|python|rust|cargo|build|rebuild|compile|replicate|generate|execute|fix|repair|install|update|setup|make|do|code|deploy|localcoder_add_python|localcoder_patch|localcoder_write_exact|write|edit|patch|shell|sql|database|sqlite|memory|table|schema|persist|store|save|rag|lookup|implement|feature|function|script|module|class|model|agent|pipeline)\b/i.test(prompt)
}

function requestedInspectionLimit(prompt: string): number | undefined {
  const match = prompt.match(/\b(?:at most|up to|no more than)\s+(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:(?:file|read[- ]only)\s+)?inspections?\b/i)
  if (!match) return undefined
  const words = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]
  const value = /^\d+$/.test(match[1]) ? Number(match[1]) : words.indexOf(match[1].toLocaleLowerCase())
  return Number.isSafeInteger(value) && value >= 0 ? value : undefined
}

function latestUserTurnKey(messages: any[], prompt: string): string {
  for (let index = messages.length - 1; index >= 0; index--) {
    const message = messages[index]
    if (roleOf(message) !== "user" || message?.type === "synthetic" || message?.info?.type === "synthetic") continue
    if (textOf(message).startsWith("Instructions from: ")) continue
    const id = String(message?.info?.id ?? message?.id ?? "")
    if (id) return id
  }
  return createHash("sha256").update(prompt, "utf8").digest("hex")
}

function hasUnavailableRouterTool(assignment: string, available: string[]): boolean {
  const mentions = assignment.match(/\b(?:use|call|invoke|run|apply)\s+(?:the\s+)?(?:`|'|")?aios_router_[a-z0-9_]+(?:`|'|")?\s+tool\b/gi) ?? []
  const availableNames = new Set(available)
  return mentions.some((mention) => {
    const name = mention.match(/aios_router_[a-z0-9_]+/i)?.[0]
    return Boolean(name && !availableNames.has(name))
  })
}

function appendTaskInstruction(event: any, state: AssignmentState, next?: string) {
  if (!Array.isArray(event.system)) event.system = []
  const text = state.failed
    ? "The assigned action failed. Report the actual error briefly."
    : next
      ? `Continue the current authorized task with the ${next} tool.`
      : "The assigned actions are complete. Give one brief, factual reply."
  event.system.push({ type: "text", text })
}

export default Plugin.define({
  id: "localcoder.drone-assignment-gate",
  async setup(ctx) {
    await ctx.session.hook("context", async (event: any) => {
      const sessionID = String(event.sessionID ?? "")
      if (!sessionID || event.model?.providerID !== "lmstudio") return
      if (isDroneAgent(event.agent)) {
        if (!Array.isArray(event.system)) event.system = []
        event.system.push({ type: "text", text: "Use normal conversation and ordinary tool calls. Continue assigned work, then give one concise factual reply. The Architect removed the old checkpoint templates and report-format requirements; historical examples do not reinstate them." })
        for (const name of QUEEN_POSTAL_TOOLS) {
          if (event.tools) delete event.tools[name]
        }
      }
      const messages = Array.isArray(event.messages) ? event.messages : []
      const prompt = latestUserText(messages)
      const directTurnKey = latestUserTurnKey(messages, prompt)
      if (directUserTurnBySession.get(sessionID) !== directTurnKey) {
        recentToolCallsBySession.delete(sessionID)
        directUserTurnBySession.set(sessionID, directTurnKey)
        while (directUserTurnBySession.size > 128) directUserTurnBySession.delete(directUserTurnBySession.keys().next().value!)
      }
      const promptHash = createHash("sha256").update(prompt, "utf8").digest("hex")
      if (isDroneAgent(event.agent)) {
        droneAgentBySession.set(sessionID, String(event.agent))
        currentPromptHashBySession.set(sessionID, promptHash)
        while (droneAgentBySession.size > 128) droneAgentBySession.delete(droneAgentBySession.keys().next().value!)
        while (currentPromptHashBySession.size > 128) currentPromptHashBySession.delete(currentPromptHashBySession.keys().next().value!)
      }
      const blockedPromptHash = cDriveDeniedBySession.get(sessionID)
      if (blockedPromptHash && blockedPromptHash !== promptHash) cDriveDeniedBySession.delete(sessionID)
      let assignment = assignmentText(prompt)
      const existingState = states.get(sessionID)
      if (Array.isArray(event.messages) && (assignment !== undefined || existingState !== undefined)) {
        for (let i = event.messages.length - 1; i >= 0; i--) {
          const message = event.messages[i]
          if (message?.type === "synthetic"
              || message?.info?.type === "synthetic"
              || textOf(message).trimStart().startsWith("Instructions from: ")) {
            event.messages.splice(i, 1)
          }
        }
      }
      const identityText = assignment ?? prompt
      const explicitAgentIDs = assignedDroneAgentIDs(identityText)
      const activeDroneAgentID = explicitAgentIDs.length === 1
        ? explicitAgentIDs[0]
        : explicitAgentIDs.length === 0
          ? existingState?.droneAgentID ?? DRONE_AGENT_IDS[String(event.agent ?? "")]
          : undefined
      if (isDroneAgent(event.agent) || explicitAgentIDs.length > 0) {
        if (explicitAgentIDs.length > 0 && !droneAgentBySession.has(sessionID)) {
          droneAgentBySession.set(sessionID, String(event.agent ?? "drone"))
          currentPromptHashBySession.set(sessionID, promptHash)
        }
        if (explicitAgentIDs.length > 1) {
          seedBindingsBySession.delete(sessionID)
          replaceSeedProfileInstruction(event)
          await writeGateTrace("drone_identity_ambiguous", { sessionID, agent: event.agent, identity_count: explicitAgentIDs.length })
        } else {
          const applied = activeDroneAgentID
            ? await applySeedForRequest(event, sessionID, activeDroneAgentID)
            : false
          if (!applied) replaceSeedProfileInstruction(event)
        }
      }
      if (!Array.isArray(event.system)) event.system = []
      if (cDriveDeniedBySession.get(sessionID) === promptHash) {
        if (event.tools) for (const name of Object.keys(event.tools)) delete event.tools[name]
        if (!Array.isArray(event.system)) event.system = []
        event.system.push({
          type: "text",
          text: "[C-DRIVE ACCESS DENIED] C: is permanently forbidden. All tools are disabled for this user turn. Stop tool use and report the denial briefly. Do not retry through another tool, shell syntax, or path spelling.",
        })
        return
      }
      if (droneAgentBySession.has(sessionID)) {
        const priorSummary = await latestPriorSessionSummary(sessionID)
        if (priorSummary && !event.system?.some((part: any) => typeof part?.text === "string" && part.text.includes("<localcoder_prior_session_summary>"))) {
          event.system.push({ type: "text", text: `<localcoder_prior_session_summary>\n${priorSummary}\n</localcoder_prior_session_summary>` })
        }
      }
      if (event.agent === "drone_build") {
        const currentState = states.get(sessionID)
        const assignedNextTool = currentState && !currentState.failed && !currentState.planOnly
          ? currentState.tools[currentState.completed.length]
          : undefined
        const initiallyRequested = assignment ? requestedTools(assignment, Object.keys(event.tools ?? {})) : []
        const expectedTool = currentState
          ? assignedNextTool
          : assignment && initiallyRequested.length
            ? isDroneAgent(event.agent) && initiallyRequested[0] !== "aios_router_assign_drone_seed"
              ? DRONE_SEED_LOOKUP_TOOL
              : initiallyRequested[0]
            : !seedBindingsBySession.has(sessionID) ? DRONE_SEED_LOOKUP_TOOL : undefined
        const stepLimit = 4096
        const priorMaxTokens = Number(event.options?.maxTokens)
        event.options.maxTokens = Number.isFinite(priorMaxTokens) && priorMaxTokens > 0
          ? Math.max(priorMaxTokens, stepLimit)
          : stepLimit
        await writeGateTrace("drone_output_limit_applied", {
          sessionID,
          modelID: event.model?.id ?? null,
          expectedTool: expectedTool ?? null,
          hasNextAssignedTool: Boolean(assignedNextTool),
          maxTokens: event.options.maxTokens,
        })
      }
      if (prompt.includes(PLAN_MARKER)) {
        states.set(sessionID, {
          sessionID, assignment: prompt, assignmentHash: "", taskID: "", tools: [], completed: [], toolResults: [],
          grantedTool: undefined, awaitingToolExecution: false,
          failed: false, planOnly: true, continuationCount: 0, continuedMessageSteps: new Set(),
        })
        keepOnlyCurrentTools(event, [])
        console.info(`[localcoder-drone-assignment-gate] plan_only session=${sessionID}`)
        return
      }
      if (prompt.startsWith(CONTINUATION_MARKER)) {
        const previous = states.get(sessionID)
        if (!previous || previous.failed || previous.planOnly || previous.pending) {
          keepOnlyCurrentTools(event, [])
          return
        }
        const next = previous.tools[previous.completed.length]
        const granted = Boolean(next && previous.grantedTool === next)
        if (granted && (!restoreToolDefinitions(event, previous, [next!])
            || !constrainAssignedToolInputs(event, previous.assignment, [next!], previous.completed, previous.droneAgentID))) {
          previous.failed = true
          keepOnlyCurrentTools(event, [])
          return
        }
        keepOnlyCurrentTools(event, granted ? [next!] : [])
        optionalizeTrustedRouterInputs(event, granted ? [next!] : [])
        appendTaskInstruction(event, previous, granted ? next : undefined)
        return
      }
      if (assignment === undefined) {
        const inspectionLimit = explicitlyReadOnly(prompt) ? requestedInspectionLimit(prompt) : undefined
        if (inspectionLimit !== undefined) {
          const turnKey = latestUserTurnKey(messages, prompt)
          if (inspectionBudgetsBySession.get(sessionID)?.turnKey !== turnKey) {
            inspectionBudgetsBySession.set(sessionID, { turnKey, limit: inspectionLimit, used: 0 })
            while (inspectionBudgetsBySession.size > 128) inspectionBudgetsBySession.delete(inspectionBudgetsBySession.keys().next().value!)
          }
        } else {
          inspectionBudgetsBySession.delete(sessionID)
        }
        const previous = states.get(sessionID)
        const identityIDs = assignedDroneAgentIDs(prompt)
        const droneAgentID = identityIDs.length === 1
          ? identityIDs[0]
          : identityIDs.length === 0
            ? previous?.droneAgentID ?? DRONE_AGENT_IDS[String(event.agent ?? "")]
            : undefined
        const needsDroneSeed = isDroneAgent(event.agent) || identityIDs.length > 0
        if (identityIDs.length > 1) {
          states.delete(sessionID)
          keepOnlyCurrentTools(event, [])
          event.system.push({ type: "text", text: "This request names more than one Drone identity. No response or tool action may proceed until the Architect supplies one exact agent_id." })
          return
        }
        if (previous?.seedBootstrap && previous.failed) {
          keepOnlyCurrentTools(event, [])
          event.system.push({ type: "text", text: "The Rust Router seed lookup failed for this session. Do not answer or act without a verified seed; start a fresh session after the Router issue is corrected." })
          return
        }
        const binding = seedBindingsBySession.get(sessionID)
        if (needsDroneSeed && !droneAgentID) {
          states.delete(sessionID)
          keepOnlyCurrentTools(event, [])
          event.system.push({ type: "text", text: "No Router-bound Drone identity is configured for this agent. The Architect must provide one exact agent_id before the Drone can answer or act." })
          await writeGateTrace("drone_seed_bootstrap_denied", { sessionID, agent: event.agent, reason: "identity_unavailable" })
          return
        }
        if (needsDroneSeed && binding?.agentID !== droneAgentID) {
          const available = Object.keys(event.tools ?? {})
          if (!available.includes(DRONE_SEED_LOOKUP_TOOL)) {
            states.delete(sessionID)
            keepOnlyCurrentTools(event, [])
            event.system.push({ type: "text", text: "The Rust Router seed lookup is unavailable. Do not answer or act until the Router tool is available." })
            await writeGateTrace("drone_seed_bootstrap_denied", { sessionID, agent: event.agent, agent_id: droneAgentID, reason: "lookup_tool_unavailable" })
            return
          }
          const bootstrapAssignment = `[LOCALCODER DRONE SEED BOOTSTRAP]\nagent_id: ${droneAgentID}`
          const identity = assignmentIdentity(sessionID, bootstrapAssignment)
          const tools = [DRONE_SEED_LOOKUP_TOOL]
          const state: AssignmentState = {
            sessionID,
            assignment: bootstrapAssignment,
            ...identity,
            droneAgentID,
            seedBootstrap: true,
            tools,
            toolDefinitions: captureToolDefinitions(event, tools),
            completed: [],
            toolResults: [],
            grantedTool: DRONE_SEED_LOOKUP_TOOL,
            awaitingToolExecution: true,
            failed: false,
            planOnly: false,
            continuationCount: 0,
            continuedMessageSteps: new Set(),
          }
          states.set(sessionID, state)
          keepOnlyCurrentTools(event, tools)
          if (!constrainAssignedToolInputs(event, bootstrapAssignment, tools, [], droneAgentID)) {
            state.failed = true
            keepOnlyCurrentTools(event, [])
            await writeGateTrace("drone_seed_bootstrap_denied", { sessionID, agent: event.agent, agent_id: droneAgentID, reason: "lookup_schema_unconstrained" })
            return
          }
          appendSeedBootstrapInstruction(event, droneAgentID)
          await writeGateTrace("drone_seed_bootstrap_started", { sessionID, agent: event.agent, agent_id: droneAgentID })
          return
        }
        states.delete(sessionID)
        const inspectionBudget = inspectionBudgetsBySession.get(sessionID)
        if (inspectionBudget && inspectionBudget.used >= inspectionBudget.limit) {
          keepOnlyCurrentTools(event, [])
          event.system.push({ type: "text", text: `The current request's ${inspectionBudget.limit}-inspection limit is reached. No further tools are available for this turn. Report verified findings and unresolved items; do not infer implementation facts from failed searches or missing files.` })
          return
        }
        const agentLower = String(event.agent ?? "").toLocaleLowerCase()
        const isBuilderAgent = agentLower === "drone_build" || agentLower === "build" || agentLower === ""
        const allowDirectCoding = !explicitlyReadOnly(prompt)
          && agentLower !== "drone_read"
          && (isBuilderAgent || isDirectCodingPrompt(prompt))
        const conversationTools = allowDirectCoding
          ? [...CONVERSATION_READ_ONLY_TOOLS, ...DIRECT_CODING_TOOLS]
          : [...CONVERSATION_READ_ONLY_TOOLS]
        keepOnlyCurrentTools(event, conversationTools)
        console.info(`[localcoder-drone-assignment-gate] conversation session=${sessionID} direct_coding=${allowDirectCoding} tools=${Object.keys(event.tools ?? {}).join(",") || "none"}`)
        return
      }
      const previous = states.get(sessionID)
      if ((previous?.assignment === assignment || previous?.sourceAssignment === assignment) && !previous.planOnly) {
        const next = previous.failed || previous.pending ? undefined : previous.tools[previous.completed.length]
        const granted = Boolean(next && previous.grantedTool === next)
        if (granted && (!restoreToolDefinitions(event, previous, [next!])
            || !constrainAssignedToolInputs(event, previous.assignment, [next!], previous.completed, previous.droneAgentID))) {
          previous.failed = true
          keepOnlyCurrentTools(event, [])
          return
        }
        keepOnlyCurrentTools(event, granted ? [next!] : [])
        optionalizeTrustedRouterInputs(event, granted ? [next!] : [])
        appendTaskInstruction(event, previous, granted ? next : undefined)
        return
      }
      const available = Object.keys(event.tools ?? {})
      const unavailableRouterTool = hasUnavailableRouterTool(assignment, available)
      let tools = unavailableRouterTool ? [] : requestedTools(assignment, available)
      if (unavailableRouterTool) {
        console.warn(`[localcoder-drone-assignment-gate] assignment_denied session=${sessionID} reason=unavailable_router_tool`)
      }
      const assignedIDs = assignedDroneAgentIDs(assignment)
      const droneAgent = isDroneAgent(event.agent) || assignedIDs.length > 0
      const droneAgentID = assignedIDs.length === 1
        ? assignedIDs[0]
        : assignedIDs.length === 0
          ? DRONE_AGENT_IDS[String(event.agent ?? "")]
          : undefined
      let seedLookupPrepended = false
      if (tools.length && droneAgent) {
        let denialReason: string | undefined
        if (assignedIDs.length > 1) denialReason = "ambiguous_drone_identity"
        else if (!droneAgentID) denialReason = "drone_identity_unavailable"
        else if (tools.includes("aios_router_assign_drone_seed")) {
          if (tools[0] !== "aios_router_assign_drone_seed" || assignedIDs.length !== 1) {
            denialReason = "seed_assignment_must_be_first_and_name_one_identity"
          }
        } else if (tools.includes(DRONE_SEED_LOOKUP_TOOL)) {
          if (tools[0] !== DRONE_SEED_LOOKUP_TOOL) denialReason = "seed_lookup_must_be_first"
        } else if (!available.includes(DRONE_SEED_LOOKUP_TOOL)) {
          denialReason = "seed_lookup_tool_unavailable"
        } else {
          tools = [DRONE_SEED_LOOKUP_TOOL, ...tools.filter((name) => name !== DRONE_SEED_LOOKUP_TOOL)]
          seedLookupPrepended = true
        }
        if (denialReason) {
          states.delete(sessionID)
          keepOnlyCurrentTools(event, [])
          event.system.push({ type: "text", text: `The Drone seed gate denied this assignment: ${denialReason}. No task tool may run until one Router identity and its seed are resolved.` })
          await writeGateTrace("drone_assignment_seed_denied", {
            sessionID,
            agent: event.agent,
            agent_id: droneAgentID ?? null,
            reason: denialReason,
            assigned_identity_count: assignedIDs.length,
          })
          return
        }
      }
      const sourceAssignment = assignment
      if (seedLookupPrepended) {
        if (!droneAgentID || !injectSeedPreflightPrompt(event, droneAgentID)) {
          states.delete(sessionID)
          keepOnlyCurrentTools(event, [])
          event.system.push({ type: "text", text: "The Drone seed preflight could not be bound to the Architect assignment. No task tool may run." })
          await writeGateTrace("drone_assignment_seed_denied", {
            sessionID,
            agent: event.agent,
            agent_id: droneAgentID ?? null,
            reason: "assignment_prompt_preflight_injection_failed",
          })
          return
        }
        const effectiveAssignment = assignmentText(latestUserText(event.messages ?? []))
        if (!effectiveAssignment) {
          states.delete(sessionID)
          keepOnlyCurrentTools(event, [])
          await writeGateTrace("drone_assignment_seed_denied", { sessionID, reason: "effective_assignment_unavailable" })
          return
        }
        assignment = effectiveAssignment
        tools = requestedTools(assignment, available)
        if (tools[0] !== DRONE_SEED_LOOKUP_TOOL) {
          states.delete(sessionID)
          keepOnlyCurrentTools(event, [])
          await writeGateTrace("drone_assignment_seed_denied", { sessionID, agent_id: droneAgentID, reason: "injected_lookup_not_first_in_effective_assignment" })
          return
        }
      }
      const assignmentBytes = new TextEncoder().encode(assignment).byteLength
      if (tools.includes("aios_router_open_build_task") && assignmentBytes > 2000) {
        states.delete(sessionID)
        keepOnlyCurrentTools(event, [])
        console.warn(`[localcoder-drone-assignment-gate] assignment_denied session=${sessionID} reason=router_assignment_over_utf8_byte_limit bytes=${assignmentBytes} limit=2000`)
        return
      }
      const identity = assignmentIdentity(sessionID, assignment)
      await writeGateTrace("assignment_initialized", {
        sessionID,
        assignment_sha256: identity.assignmentHash,
        assignment_bytes: assignmentBytes,
        available_tool_names: available,
        assigned_tool_sequence: tools,
        unavailable_router_tool: unavailableRouterTool,
        drone_agent_id: droneAgentID ?? null,
        seed_lookup_prepended: seedLookupPrepended,
      })
      states.set(sessionID, {
        sessionID, assignment, sourceAssignment, ...identity, tools, toolDefinitions: captureToolDefinitions(event, tools), completed: [], toolResults: [],
        droneAgentID,
        grantedTool: tools[0], awaitingToolExecution: tools.length > 0,
        failed: false, planOnly: false, continuationCount: 0, continuedMessageSteps: new Set(),
      })
      while (states.size > 128) states.delete(states.keys().next().value!)
      keepOnlyCurrentTools(event, tools.length ? [tools[0]] : [])
      if (tools.length && !constrainAssignedToolInputs(event, assignment, [tools[0]], [], droneAgentID)) {
        const current = states.get(sessionID)
        if (current) current.failed = true
        keepOnlyCurrentTools(event, [])
        console.warn(`[localcoder-drone-assignment-gate] assignment_denied session=${sessionID} reason=assigned_tool_input_not_constrained`)
      }
      optionalizeTrustedRouterInputs(event, tools.length ? [tools[0]] : [])
      appendTaskInstruction(event, states.get(sessionID)!, tools[0])
      console.info(`[localcoder-drone-assignment-gate] assignment session=${sessionID} next=${tools[0] ?? "none"} authorized_sequence=${tools.join(",") || "none"}`)
    }, { providerID: "lmstudio" })

    for (const hookName of ["compaction", "generate", "title"] as const) {
      await ctx.session.hook(hookName, applyCachedSeedOnly, { providerID: "lmstudio" })
    }

    await ctx.tool.hook("execute.before", (event: any) => {
      const sessionID = String(event.sessionID ?? "")
      if (QUEEN_POSTAL_TOOLS.has(String(event.tool))) {
        throw new Error("Queen-only postal tools cannot be invoked by a Drone OpenCode session.")
      }
      if (droneAgentBySession.has(sessionID) && hasCDriveReference(JSON.stringify(event.input ?? {}))) {
        const reason = "C: is permanently forbidden. No tool action was executed; stop this user turn."
        cDriveDeniedBySession.set(sessionID, currentPromptHashBySession.get(sessionID) ?? "")
        while (cDriveDeniedBySession.size > 128) cDriveDeniedBySession.delete(cDriveDeniedBySession.keys().next().value!)
        const state = states.get(sessionID)
        if (state) { state.failed = true; state.pending = undefined }
        void writeGateTrace("drone_c_drive_denied", { sessionID, tool: String(event.tool), reason })
        throw new Error(reason)
      }
      if (event.input && typeof event.input === "object") {
        for (const key of ["path", "filePath", "file", "target", "dir", "directory"]) {
          if (typeof event.input[key] === "string") {
            const p = event.input[key].trim()
            if (/^L:[\\/]\.(?:opencode|hermes)\b/i.test(p)) {
              event.input[key] = p.replace(/^L:[\\/]/i, "L:\\LocalCoder\\")
            } else if (/^L:[\\/]workspace\b/i.test(p)) {
              event.input[key] = p.replace(/^L:[\\/]/i, "L:\\LocalCoder\\")
            }
          }
        }
        if (typeof event.input.command === "string") {
          event.input.command = event.input.command
            .replace(/\bL:[\\/]\.(?:opencode|hermes)\b/gi, "L:\\LocalCoder\\.opencode")
            .replace(/\bL:[\\/]workspace\b/gi, "L:\\LocalCoder\\workspace")
        }
      }
      const toolName = String(event.tool ?? "")
      if (toolName === "read") {
        if (!event.input || typeof event.input !== "object" || Array.isArray(event.input)) event.input = {}
        if (event.input.limit === undefined) event.input.limit = 80
      }
      const inspectionBudget = inspectionBudgetsBySession.get(sessionID)
      if (inspectionBudget && FILE_INSPECTION_TOOLS.has(toolName)) {
        if (inspectionBudget.used >= inspectionBudget.limit) {
          throw new Error(`The current request's ${inspectionBudget.limit}-inspection limit is reached. Report findings without another tool call.`)
        }
        inspectionBudget.used++
      }
      const inputStr = JSON.stringify(event.input ?? {})
      const inputHash = createHash("sha256").update(inputStr, "utf8").digest("hex")
      const recent = recentToolCallsBySession.get(sessionID)
      if (recent && recent.tool === toolName && recent.inputHash === inputHash) {
        recent.count++
        if (recent.count >= 2) {
          throw new Error(`Duplicate tool call blocked: ${toolName} was already executed with identical arguments. Do not repeat identical queries; inspect existing files, write the necessary code, or reply to the Architect.`)
        }
      } else {
        recentToolCallsBySession.set(sessionID, { tool: toolName, inputHash, count: 1 })
        while (recentToolCallsBySession.size > 128) {
          recentToolCallsBySession.delete(recentToolCallsBySession.keys().next().value!)
        }
      }
      const state = states.get(sessionID)
      if (!state) {
        if (String(event.tool).startsWith("aios_router_")) {
          throw new Error("Router tools require a current Architect assignment bound to this OpenCode session.")
        }
        return
      }
      if (state.planOnly) {
        throw new Error("Drone plan-only turn: tool execution is denied until a separate action assignment is dispatched.")
      }
      const expected = state.tools[state.completed.length]
      if (state.failed || state.pending
          || !expected || state.grantedTool !== expected || String(event.tool) !== expected) {
        const reason = state.failed
          ? "The Drone assignment stopped after a failed tool."
          : state.pending
            ? `Tool ${state.pending} is already in progress; parallel actions are denied.`
            : expected
              ? `The current Architect assignment requires ${expected} next; ${String(event.tool)} is outside that sequence.`
              : `All ${state.completed.length} assigned tool(s) are complete; ${String(event.tool)} is outside the assignment.`
        console.warn(`[localcoder-drone-assignment-gate] denied session=${sessionID} tool=${String(event.tool)} reason=${reason}`)
        throw new Error(`${reason} No tool was executed.`)
      }
      if (String(event.tool) === "localcoder_add_python") {
        const authorizedTarget = assignedPythonTarget(state.assignment)
        if (authorizedTarget) event.input.filePath = authorizedTarget
      }
      if (String(event.tool) === "shell") {
        const cmd = assignedShellCommand(state.assignment)
        if (cmd) {
          if (!event.input || typeof event.input !== "object" || Array.isArray(event.input)) event.input = {}
          event.input.command = cmd
        }
      }
      if (String(event.tool) === "read") {
        if (!event.input || typeof event.input !== "object" || Array.isArray(event.input)) event.input = {}
        if (event.input.limit === undefined) event.input.limit = 80
      }
      injectTrustedRouterInput(event, state)
      state.pending = String(event.tool)
      console.info(`[localcoder-drone-assignment-gate] allowed session=${sessionID} tool=${String(event.tool)} step=${state.completed.length + 1}/${state.tools.length}`)
    })

    await ctx.tool.hook("execute.after", async (event: any) => {
      const sessionID = String(event.sessionID ?? "")
      const state = states.get(sessionID)
      if (!state || state.planOnly || state.pending !== String(event.tool)) return
      state.pending = undefined
      const output = toolOutputText(event.result)
      const exitCode = Number.isInteger(event.result?.metadata?.exit) ? Number(event.result.metadata.exit) : undefined
      const toolResult = {
        tool: String(event.tool),
        output: output.slice(0, 4000),
        outputLength: output.length,
        ...(exitCode === undefined ? {} : { exitCode }),
      }
      state.lastToolResult = toolResult
      if (event.status === "completed") {
        if (ROUTER_MUTATION_TOOLS.has(String(event.tool))) {
          const accepted = routerResponseAccepted(event.result)
          if (accepted !== true) {
            state.failed = true
            await writeGateTrace("tool_after_rejected", { sessionID, tool: String(event.tool), reason: "router_mutation_not_accepted" })
            console.warn(`[localcoder-drone-assignment-gate] router_mutation_not_accepted session=${sessionID} tool=${String(event.tool)} result_ok=${accepted === false ? "false" : "unrecognized"}`)
            return
          }
          if (String(event.tool) === "aios_router_record_turn_result") {
            state.activeLaneTurn = (state.activeLaneTurn ?? 0) + 1
          }
        }
        if (event.tool === DRONE_SEED_LOOKUP_TOOL || event.tool === "aios_router_assign_drone_seed") {
          const expectedAgentID = state.droneAgentID
          const suppliedAgentID = typeof event.input?.agent_id === "string" ? event.input.agent_id : ""
          const binding = expectedAgentID && suppliedAgentID === expectedAgentID
            ? routerSeedBinding(event.result, expectedAgentID)
            : undefined
          if (!binding) {
            state.failed = true
            state.grantedTool = undefined
            await writeGateTrace("drone_seed_binding_rejected", {
              sessionID,
              agent_id: expectedAgentID ?? null,
              supplied_agent_id: suppliedAgentID || null,
              source_tool: String(event.tool),
              reason: "router_result_missing_matching_identity_seed_or_style_profile",
            })
            console.warn(`[localcoder-drone-assignment-gate] seed_binding_rejected session=${sessionID} tool=${String(event.tool)}`)
            return
          }
          state.droneAgentID = binding.agentID
          state.droneSeed = binding.seed
          state.droneStyleProfile = binding.styleProfile
          seedBindingsBySession.set(sessionID, binding)
          while (seedBindingsBySession.size > 128) seedBindingsBySession.delete(seedBindingsBySession.keys().next().value!)
          await writeGateTrace("drone_seed_bound", {
            sessionID,
            agent_id: binding.agentID,
            seed_sha256: createHash("sha256").update(String(binding.seed), "utf8").digest("hex"),
            source_tool: String(event.tool),
            style_profile: binding.styleProfile,
          })
          if (state.seedBootstrap && event.tool === DRONE_SEED_LOOKUP_TOOL) {
            states.delete(sessionID)
            await writeGateTrace("drone_seed_bootstrap_completed", {
              sessionID,
              agent_id: binding.agentID,
              source_tool: String(event.tool),
              seed_sha256: createHash("sha256").update(String(binding.seed), "utf8").digest("hex"),
            })
            return
          }
        }
        state.toolResults.push(toolResult)
        state.completed.push(String(event.tool))
        state.grantedTool = state.tools[state.completed.length]
        state.awaitingToolExecution = Boolean(state.grantedTool)
        await writeGateTrace("tool_after", {
          sessionID,
          tool: String(event.tool),
          status: String(event.status),
          outputLength: state.lastToolResult.outputLength,
          exitCode: state.lastToolResult.exitCode ?? null,
          state: {
            completed: state.completed.length,
            pending: state.pending ?? null,
            failed: state.failed,
          },
        })
        console.info(`[localcoder-drone-assignment-gate] completed session=${sessionID} step=${state.completed.length}/${state.tools.length}`)
      } else {
        state.failed = true
        await writeGateTrace("tool_after_failed", { sessionID, tool: String(event.tool), status: String(event.status), outputLength: output.length })
        console.warn(`[localcoder-drone-assignment-gate] failed session=${sessionID} tool=${String(event.tool)} status=${String(event.status)}`)
      }
    })

    const controller = new AbortController()
    void (async () => {
      const completionEvents = [
        "session.execution.succeeded",
        "session.execution.failed",
        "session.execution.interrupted",
      ] as const
      for await (const event of ctx.event.subscribe({ signal: controller.signal, types: [...completionEvents] })) {
        const sessionID = String(event.data?.sessionID ?? "")
        const state = states.get(sessionID)
        const sessionAgent = droneAgentBySession.get(sessionID)
        if (sessionID && sessionAgent) {
          try {
            const messages = contextMessages(await ctx.session.context({ sessionID }))
            await writeSessionSummary(sessionID, sessionAgent, event.type, messages)
          } catch (error: any) {
            console.warn(`[localcoder-drone-assignment-gate] summary_write_failed session=${sessionID} reason=${String(error?.message ?? error)}`)
          }
        }
        await writeGateTrace("session_execution", {
          type: event.type,
          dataKeys: Object.keys(event.data ?? {}),
          sessionID,
          state: state ? {
            completed: state.completed.length,
            toolCount: state.tools.length,
            pending: state.pending ?? null,
            failed: state.failed,
            continuationCount: state.continuationCount,
          } : null,
        })
        if (event.type !== "session.execution.succeeded") {
          if (state) state.failed = true
          if (state) await writeGateTrace("session_execution_stopped", {
            type: event.type,
            sessionID,
            completed: state.completed.length,
          })
          continue
        }
        if (!sessionID || !state || state.planOnly || state.failed || state.pending) continue
        const expected = state.tools[state.completed.length]
        if (!expected) {
          await writeGateTrace("assignment_complete", { sessionID, completed: state.completed.length })
          continue
        }
        const stepKey = `${sessionID}:${state.completed.length}`
        if (continuationFlights.has(sessionID)) continue
        if (state.continuedMessageSteps.has(stepKey) || state.continuationCount >= MAX_AUTOMATIC_CONTINUATIONS) {
          state.failed = true
          await writeGateTrace("continuation_stopped", { sessionID, reason: "no_action_progress", nextTool: expected })
          continue
        }
        continuationFlights.add(sessionID)
        state.continuedMessageSteps.add(stepKey)
        state.continuationCount++
        state.grantedTool = expected
        state.awaitingToolExecution = true
        try {
          await ctx.session.prompt({
            sessionID, delivery: "steer",
            text: `${CONTINUATION_MARKER}\nContinue the current authorized task. Call the ${expected} tool.`,
          })
          await writeGateTrace("continuation_queued", { sessionID, nextTool: expected, count: state.continuationCount })
        } catch (error: any) {
          state.failed = true
          await writeGateTrace("continuation_failed", { sessionID, reason: String(error?.message ?? error) })
        } finally {
          continuationFlights.delete(sessionID)
        }
      }
    })().catch((error: any) => {
      console.warn(`[localcoder-drone-assignment-gate] event_subscription_failed reason=${String(error?.message ?? error)}`)
    })
    return () => controller.abort()
  },
})
