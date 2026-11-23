import { Plugin } from "@opencode/plugin"
import { execFileSync } from "node:child_process"
import { createHash, randomUUID } from "node:crypto"
import { mkdir, open, readFile, readdir, realpath, rename, stat, unlink } from "node:fs/promises"
import { basename, dirname, isAbsolute, parse, relative, resolve, sep } from "node:path"

type ToolSpec = { name: string; required: string[]; properties?: Record<string, unknown>; additionalProperties?: boolean }
type ExplicitToolSequence = { prompt: string; tools: string[]; completed: string[]; failed?: string }

const allowedByRequest = new Map<string, Map<string, ToolSpec>>()
const readOnlyByRequest = new Map<string, boolean>()
const promptByRequest = new Map<string, string>()
const bridgeDiagnosticsByRequest = new Map<string, Record<string, unknown>>()
const promptBySession = new Map<string, string>()
const trustedAssignmentPromptsBySession = new Map<string, string>()
const explicitToolSequenceBySession = new Map<string, ExplicitToolSequence>()

type RouterTaskBinding = { taskId: string; assignmentHash: string; taskClass: string; laneIds: string[]; maxTurnsPerLane: number; acceptedTurns: Map<string, number>; nextTurnByLane: Map<string, number>; openAttempted: boolean; opened: boolean }
const routerTaskBindingsBySession = new Map<string, RouterTaskBinding>()
const routerMutationTools = new Set(["aios_router_assign_drone_seed", "aios_router_open_build_task", "aios_router_accept_self_prompt", "aios_router_record_turn_result", "aios_router_complete_lane", "aios_router_stop_task"])
const inspectedFilesBySession = new Map<string, Map<string, string>>()
const preToolByKey = new Map<string, Array<{ path?: string; beforeHash?: string; snapshot?: string; inputHash: string; receiptId: string }>>()
let callSequence = 0
let diagnosticRequestSequence = 0
let traceWriteQueue: Promise<void> = Promise.resolve()

function requestKey(event: any) {
  return `${event.sessionID}:${event.kind}`
}

function extractTools(body: any): Map<string, ToolSpec> {
  const result = new Map<string, ToolSpec>()
  for (const item of Array.isArray(body?.tools) ? body.tools : []) {
    const fn = item?.function
    const name = typeof fn?.name === "string" ? fn.name : item?.name
    if (item?.type !== "function" || typeof name !== "string") continue
    const rawSchema = fn?.parameters ?? item?.parameters
    const schema = rawSchema && typeof rawSchema === "object" ? rawSchema : {}
    result.set(name, {
      name,
      required: Array.isArray(schema.required) ? schema.required.filter((x: unknown) => typeof x === "string") : [],
      properties: schema.properties && typeof schema.properties === "object" ? schema.properties : undefined,
      additionalProperties: schema.additionalProperties,
    })
  }
  return result
}

function diagnosticToolChoice(value: any): unknown {
  if (typeof value === "string") return value
  if (!value || typeof value !== "object") return null
  return {
    type: typeof value.type === "string" ? value.type : null,
    function_name: typeof value.function?.name === "string" ? value.function.name : null,
  }
}

function diagnosticToolSchemas(tools: Map<string, ToolSpec>) {
  return [...tools.values()].map((spec) => ({
    name: spec.name,
    required: [...spec.required],
    property_names: Object.keys(spec.properties ?? {}).sort(),
    additional_properties: spec.additionalProperties ?? null,
  }))
}

function messageText(content: any): string {
  if (typeof content === "string") return content
  if (!Array.isArray(content)) return ""
  return content.map((part) => typeof part?.text === "string" ? part.text : "").join("\n")
}

function parseXmlToolCall(block: string, tools: Map<string, ToolSpec>) {
  const functionMatch = block.match(/<function=([^>\s]+)>\s*([\s\S]*?)\s*<\/function>/i)
  if (!functionMatch) return undefined
  const name = functionMatch[1]
  const spec = tools.get(name)
  if (!spec) return undefined
  const args: Record<string, unknown> = {}
  const body = functionMatch[2]
  const parameterPattern = /<parameter=([^>\s]+)>\s*([\s\S]*?)\s*<\/parameter>/gi
  let match: RegExpExecArray | null
  while ((match = parameterPattern.exec(body))) {
    const key = match[1]
    if (!spec.properties || !(key in spec.properties) || key in args) return undefined
    const raw = match[2].trim()
    const type = (spec.properties[key] as any)?.type
    if (type === "object" || type === "array" || type === "boolean" || type === "number" || type === "integer") {
      try { args[key] = JSON.parse(raw) } catch { return undefined }
    } else {
      args[key] = raw
    }
  }
  if (spec.required.some((key) => !(key in args))) return undefined
  if (spec.additionalProperties === false && spec.properties && Object.keys(args).some((key) => !(key in spec.properties!))) return undefined
  return { name, arguments: args }
}

function isSyntheticInstructionMessage(message: any, text: string): boolean {
  if (message?.type === "synthetic" || message?.info?.type === "synthetic") return true
  const trimmed = text.trimStart()
  return trimmed.startsWith("Instructions from: ") || trimmed.startsWith("<system-reminder>")
}

function lastUserText(messages: any[]): string {
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i]?.role !== "user") continue
    const text = messageText(messages[i]?.content)
    if (isSyntheticInstructionMessage(messages[i], text)) continue
    return text
  }
  return ""
}

function requestPrompt(body: any): string {
  const messages = Array.isArray(body?.messages) ? body.messages : []
  const chatPrompt = lastUserText(messages)
  if (chatPrompt) return chatPrompt

  if (typeof body?.input === "string") return body.input
  if (Array.isArray(body?.input)) {
    const responsePrompt = lastUserText(body.input)
    if (responsePrompt) return responsePrompt
    for (let i = body.input.length - 1; i >= 0; i--) {
      const item = body.input[i]
      const text = typeof item === "string" ? item : messageText(item?.content ?? item?.text)
      if (text && !isSyntheticInstructionMessage(item, text)) return text
    }
  }
  return ""
}

function trustedRouterAssignment(prompt: string): string | undefined {
  const match = prompt.match(/^\[ARCHITECT ASSIGNMENT \| CURRENT AND AUTHORIZED\]\r?\n([\s\S]*?)\r?\n\[CURRENT AUTHORIZATION FACT\]/)
  const assignment = match?.[1]?.trim()
  const assignmentBytes = assignment ? new TextEncoder().encode(assignment).byteLength : 0
  return assignment && assignmentBytes <= 2000 ? assignment : undefined
}

function trustedRouterContinuation(prompt: string): boolean {
  return /^[ \t]*\[LOCALCODER PRIVATE DRONE CONTINUATION \| v1\][ \t]*$/m.test(prompt)
}

function promptForCurrentAuthorization(sessionID: string): string {
  const assignedPrompt = trustedAssignmentPromptsBySession.get(sessionID)
  if (assignedPrompt) return assignedPrompt
  const latest = promptBySession.get(sessionID) ?? ""
  return trustedRouterContinuation(latest) ? "" : latest
}

function trustedRouterBounds(assignment: string): { taskClass: string; laneIds: string[]; maxTurnsPerLane: number } | undefined {
  const match = assignment.match(/^Router bounds JSON:\s*(\{[^\r\n]+\})\s*$/im)
  if (!match) return { taskClass: "build", laneIds: ["drone"], maxTurnsPerLane: 8 }
  let value: any
  try { value = JSON.parse(match[1]) } catch { return undefined }
  const taskClass = value?.task_class
  const laneIds = value?.lane_ids
  const maxTurnsPerLane = value?.max_turns_per_lane
  if (!["conversation", "build", "other"].includes(taskClass)
    || !Array.isArray(laneIds) || laneIds.length < 1 || laneIds.length > 4
    || laneIds.some((item: unknown) => typeof item !== "string" || !/^[A-Za-z0-9_.:-]{1,64}$/.test(item))
    || new Set(laneIds).size !== laneIds.length
    || !Number.isInteger(maxTurnsPerLane) || maxTurnsPerLane < 1 || maxTurnsPerLane > 32) return undefined
  return { taskClass, laneIds, maxTurnsPerLane }
}

function recoverRouterTaskBinding(sessionID: string, assignment: string): RouterTaskBinding | undefined {
  const bounds = trustedRouterBounds(assignment)
  if (!bounds || bounds.taskClass !== "build") return undefined
  const assignmentHash = createHash("sha256").update(assignment, "utf8").digest("hex")
  const taskId = `oc_${createHash("sha256").update(`${sessionID}\n${assignmentHash}`, "utf8").digest("hex")}`
  return {
    taskId,
    assignmentHash,
    taskClass: bounds.taskClass,
    laneIds: bounds.laneIds,
    maxTurnsPerLane: bounds.maxTurnsPerLane,
    acceptedTurns: new Map(),
    nextTurnByLane: new Map(),
    openAttempted: true,
    opened: true,
  }
}

function bindRouterMutation(event: any, sessionID: string, prompt: string) {
  const toolName = String(event.tool)
  const input = event.input && typeof event.input === "object" && !Array.isArray(event.input) ? event.input : {}
  if (toolName === "aios_router_open_build_task") {
    const sequence = explicitToolSequenceBySession.get(sessionID)
    const assignment = trustedRouterAssignment(prompt)
    const bounds = assignment ? trustedRouterBounds(assignment) : undefined
    if (!sequence || !sequence.tools.includes(toolName)) {
      if (sequence) sequence.failed = "router_open_not_explicitly_assigned"
      throw new Error("Router open is not in the Architect's explicit tool sequence; no task was opened.")
    }
    if (!assignment) {
      sequence.failed = "router_open_missing_architect_assignment"
      throw new Error("Router open has no current Architect assignment; no task was opened.")
    }
    if (!bounds || bounds.taskClass !== "build") {
      sequence.failed = "router_open_invalid_build_bounds"
      throw new Error("Router open requires valid build-class Router bounds; no task was opened.")
    }
    const previous = routerTaskBindingsBySession.get(sessionID)
    if (previous?.openAttempted) throw new Error("Router task open was already attempted in this session; no retry was issued.")
    const assignmentHash = createHash("sha256").update(assignment.trim(), "utf8").digest("hex")
    const taskId = `oc_${createHash("sha256").update(`${sessionID}\n${assignmentHash}`, "utf8").digest("hex")}`
    routerTaskBindingsBySession.set(sessionID, { taskId, assignmentHash, taskClass: bounds.taskClass, laneIds: bounds.laneIds, maxTurnsPerLane: bounds.maxTurnsPerLane, acceptedTurns: new Map(), nextTurnByLane: new Map(), openAttempted: true, opened: false })
    event.input = { ...input, session_id: sessionID, task_id: taskId, assignment_hash: assignmentHash, assignment, lane_ids: bounds.laneIds, max_turns_per_lane: bounds.maxTurnsPerLane }
    return
  }
  const assignment = trustedRouterAssignment(prompt)
  let binding = routerTaskBindingsBySession.get(sessionID)
  if (!binding && assignment) {
    binding = recoverRouterTaskBinding(sessionID, assignment)
    if (binding) routerTaskBindingsBySession.set(sessionID, binding)
  }
  if (!binding) throw new Error(`Router mutation ${toolName} requires the current authorized build assignment in this session.`)
  if (assignment) {
    const assignmentHash = createHash("sha256").update(assignment, "utf8").digest("hex")
    if (assignmentHash !== binding.assignmentHash) {
      throw new Error("Router mutation assignment does not match the task opened in this session.")
    }
  } else if (!trustedRouterContinuation(prompt)) {
    throw new Error("Router mutation requires the opened Architect assignment or a trusted Drone continuation.")
  }
  // This local map is only a cache. Rust validates task existence, accepted turns,
  // lane state, and completion for every mutation using the deterministic task ID.
  if (!binding.opened && binding.openAttempted) binding.opened = true
  if (!binding.opened) throw new Error(`Router mutation ${toolName} requires the current build task binding.`)
  const bound: Record<string, unknown> = { ...input, session_id: sessionID, task_id: binding.taskId, assignment_hash: binding.assignmentHash }
  const resolveLaneId = () => {
    const requestedLane = typeof input.lane_id === "string" ? input.lane_id : ""
    const laneId = binding.laneIds.length === 1 ? binding.laneIds[0] : requestedLane
    if (!binding.laneIds.includes(laneId)) throw new Error("Router lane is outside the Architect-assigned lane roster.")
    return laneId
  }
  if (toolName === "aios_router_accept_self_prompt") {
    const laneId = resolveLaneId()
    const turn = binding.nextTurnByLane.get(laneId) ?? 0
    if (!Number.isInteger(turn) || turn < 0 || turn >= binding.maxTurnsPerLane) {
      throw new Error("Router turn is outside the Architect-assigned turn bound.")
    }
    bound.lane_id = laneId
    bound.turn = turn
  } else if (toolName === "aios_router_record_turn_result") {
    const laneId = resolveLaneId()
    const turn = binding.acceptedTurns.get(laneId) ?? (binding.nextTurnByLane.get(laneId) ?? 0)
    if (!Number.isInteger(turn) || turn < 0 || turn >= binding.maxTurnsPerLane) {
      throw new Error("Router result turn is outside the Architect-assigned bound.")
    }
    bound.lane_id = laneId
    bound.turn = turn
  } else if (toolName === "aios_router_complete_lane") {
    bound.lane_id = resolveLaneId()
  } else {
    if ("lane_id" in input) bound.lane_id = resolveLaneId()
    if ("turn" in input) {
      const turn = Number(input.turn)
      if (!Number.isInteger(turn) || turn < 0 || turn >= binding.maxTurnsPerLane) throw new Error("Router turn is outside the Architect-assigned turn bound.")
      bound.turn = turn
    }
  }
  event.input = bound
}

function routerToolResultOk(result: any): boolean {
  if (result?.isError === true) return false
  const structured = [result, result?.output, result?.structuredContent, result?.output?.structuredContent]
  if (structured.some((value: any) => value?.ok === true)) return true
  const textValues = [
    typeof result === "string" ? result : "",
    typeof result?.content === "string" ? result.content : "",
    Array.isArray(result?.content) ? result.content.map((part: any) => typeof part?.text === "string" ? part.text : "").join("\n") : "",
    typeof result?.output === "string" ? result.output : "",
    typeof result?.output?.text === "string" ? result.output.text : "",
    typeof result?.output?.content === "string" ? result.output.content : "",
    Array.isArray(result?.output?.content) ? result.output.content.map((part: any) => typeof part?.text === "string" ? part.text : "").join("\n") : "",
    typeof result?.text === "string" ? result.text : "",
  ]
  for (const text of textValues) {
    try { if (JSON.parse(text)?.ok === true) return true } catch { /* try the next supported result shape */ }
  }
  return false
}

function isDroneActionPrompt(prompt: string): boolean {
  return prompt.startsWith("[ARCHITECT ASSIGNMENT | CURRENT AND AUTHORIZED]")
    || prompt.startsWith("[LOCALCODER PRIVATE DRONE CONTINUATION | v1]")
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

function isMutation(call: { name: string; arguments: Record<string, unknown> }): boolean {
  const name = call.name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "")
  if (/^(edit|write|patch|localcoder_patch|localcoder_write_exact|localcoder_add_python|delete|remove|move|copy|mkdir|rmdir|touch|apply_patch|write_file|patch_file|localcoder_memory_append)$/.test(name)) return true
  if (!/(^|_)(shell|terminal|bash|powershell|cmd)(_|$)/.test(`_${name}_`)) return false
  const command = String(call.arguments.command ?? call.arguments.cmd ?? "").trim()
  if (!command || /[;&|<>`\n\r]/.test(command)) return true
  const normalized = command.replace(/^\s+/, "").toLowerCase()
  return !/^(get-location|pwd|git\s+(status|diff|log|show|grep)\b|rg\b|grep\b|cat\b|type\b|get-content\b|get-item\b|get-childitem\b|select-string\b|test-path\b|resolve-path\b|dir\b|ls\b|where\.exe\b|nvidia-smi\b|lms\s+ps\b|opencode\s+models\b)/i.test(normalized)
}

function parseCall(content: string, tools: Map<string, ToolSpec>, prompt = "") {
  const text = content.trim()
  const candidates: string[] = []
  const wrappers = [...text.matchAll(/<(?:tool_call|response|xml)>\s*([\s\S]*?)\s*<\/(?:tool_call|response|xml)>/gi)]
  for (const match of wrappers) candidates.push(match[1].trim())
  for (const match of wrappers) {
    const parsed = parseXmlToolCall(match[1], tools)
    if (parsed) candidates.unshift(JSON.stringify(parsed))
  }
  const fences = [...text.matchAll(/```(?:json)?\s*\n?([\s\S]*?)\n?```/gi)]
  for (const match of fences) candidates.push(match[1].trim())
  for (const fence of fences) {
    const block = fence[1].trim()
    for (const match of block.matchAll(/<([a-zA-Z_][\w.-]*)>\s*([\s\S]*?)\s*<\/\1>/g)) {
      if (!tools.has(match[1])) continue
      try {
        const args = JSON.parse(match[2].trim())
        if (args && typeof args === "object" && !Array.isArray(args)) {
          candidates.unshift(JSON.stringify({ name: match[1], arguments: args }))
        }
      } catch { /* XML-shaped non-JSON tool text is not executable */ }
    }
  }
  if (fences.length === 0 && wrappers.length === 0) candidates.push(text)
  const proseLines = text
    .replace(/```[\s\S]*?```/g, "\n")
    .replace(/<([a-zA-Z_][\w.-]*)\s*>[\s\S]*?<\/\1\s*>/g, "\n")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.startsWith("{") && line.endsWith("}"))
  candidates.push(...proseLines)
  if (/\buse\s+localcoder_memory_read\b/i.test(prompt)) {
    for (const match of text.matchAll(/```json\s*\n?([\s\S]*?)\n?```/gi)) {
      try {
        const request = JSON.parse(match[1].trim())
        if (request?.name === "localcoder_memory_read") candidates.unshift(match[1].trim())
      } catch { /* ignore malformed fenced JSON */ }
    }
  }

  for (const candidate of candidates) {
    let value: any
    try { value = JSON.parse(candidate) } catch { continue }
    if (!value || typeof value !== "object" || Array.isArray(value)) continue
    const name = value.name
    let spec = typeof name === "string" ? tools.get(name) : undefined
    if (!spec && typeof name === "string") {
      const outputAlias = name.replace(/^(?:localcoder_|opencode_)/, "")
      const requested = explicitlyRequestedTools(prompt, tools)
        .find((tool) => tool.replace(/^(?:localcoder_|opencode_)/, "") === outputAlias)
      if (requested) spec = tools.get(requested)
    }
    if (!spec) continue
    let args = value.arguments
    if (typeof args === "string") {
      try { args = JSON.parse(args) } catch { continue }
    }
    if (!args || typeof args !== "object" || Array.isArray(args)) continue
    if (spec.required.some((key) => !(key in args))) continue
    if (spec.additionalProperties === false && spec.properties) {
      if (Object.keys(args).some((key) => !(key in spec.properties!))) continue
    }
    return { name: spec.name, arguments: args }
  }
  return undefined
}

function explicitlyRequestedTools(prompt: string, tools: Map<string, ToolSpec>): string[] {
  const matches: Array<{ name: string; index: number }> = []
  for (const name of tools.keys()) {
    const aliases = [name]
    if (name.startsWith("localcoder_")) {
      const alias = name.slice("localcoder_".length)
      if (!tools.has(alias)) aliases.push(alias)
    }
    for (const alias of aliases) {
      const escaped = alias.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
      const pattern = new RegExp(`\\b(?:use|call|invoke|run|apply)\\s+(?:the\\s+)?[\\x60"']?${escaped}\\b[\\x60"']?(?:\\s+tool\\b)?`, "gi")
      for (const match of prompt.matchAll(pattern)) {
        const prefix = prompt.slice(Math.max(0, match.index! - 16), match.index!)
        if (/\b(?:do not|don't|dont|never)\s+$/i.test(prefix)) continue
        if (!matches.some((item) => item.name === name && item.index === match.index)) {
          matches.push({ name, index: match.index! })
        }
      }
    }
  }
  return matches.sort((left, right) => left.index - right.index).map(({ name }) => name)
}

function requestedToolForCall(prompt: string, tools: Map<string, ToolSpec>, callName: string): string | undefined {
  const normalized = (name: string) => name.replace(/^(?:localcoder_|opencode_)/, "").replace(/^write_exact$/, "write")
  return explicitlyRequestedTools(prompt, tools)
    .find((name) => name === callName || normalized(name) === normalized(callName))
}

function nextExplicitTool(sequence: ExplicitToolSequence): string | undefined {
  return sequence.tools[sequence.completed.length]
}

function recordExplicitToolCompletion(sequence: ExplicitToolSequence, tool: string, status: string): boolean {
  if (status !== "completed" || nextExplicitTool(sequence) !== tool) return false
  sequence.completed.push(tool)
  return true
}

function argumentsForRequestedTool(
  call: { name: string; arguments: Record<string, unknown> },
  target: ToolSpec,
): Record<string, unknown> | undefined {
  let args = call.arguments
  if (call.name !== target.name) {
    if ((call.name === "localcoder_write_exact" && target.name === "write")
      || (call.name === "write" && target.name === "localcoder_write_exact")) {
      args = { filePath: args.filePath ?? args.path, content: args.content }
    } else if (call.name === "edit" && (target.name === "patch" || target.name === "localcoder_patch")) {
      args = {
        filePath: args.filePath ?? args.path,
        oldString: args.oldString,
        newString: args.newString,
      }
    } else {
      return undefined
    }
  }
  if (target.required.some((key) => !(key in args))) return undefined
  if (target.additionalProperties === false && target.properties) {
    if (Object.keys(args).some((key) => !(key in target.properties!))) return undefined
  }
  return args
}

function usageFromChunks(raw: string) {
  const chunks = raw.split(/\r?\n/).filter((line) => line.startsWith("data:"))
  let content = ""
  let usage: any
  const finishReasons: string[] = []
  let model = "lmstudio"
  let created = Math.floor(Date.now() / 1000)
  let id = `chatcmpl-toolbridge-${Date.now()}`
  const calls = new Map<number, { name: string; arguments: string }>()
  for (const line of chunks) {
    const data = line.slice(5).trim()
    if (!data || data === "[DONE]") continue
    try {
      const chunk = JSON.parse(data)
      id = chunk.id ?? id
      model = chunk.model ?? model
      created = chunk.created ?? created
      usage = chunk.usage ?? usage
      for (const choice of chunk.choices ?? []) {
        content += choice.delta?.content ?? ""
        if (typeof choice.finish_reason === "string") finishReasons.push(choice.finish_reason)
        for (const call of choice.delta?.tool_calls ?? choice.message?.tool_calls ?? []) {
          const index = Number.isInteger(call.index) ? call.index : calls.size
          const current = calls.get(index) ?? { name: "", arguments: "" }
          current.name += call.function?.name ?? ""
          const fragment = call.function?.arguments
          current.arguments += typeof fragment === "string" ? fragment : fragment === undefined ? "" : JSON.stringify(fragment)
          calls.set(index, current)
        }
      }
    } catch { /* ignore non-JSON SSE lines */ }
  }
  const toolCalls = [...calls.entries()].sort(([left], [right]) => left - right).flatMap(([, call]) => {
    try {
      const arguments_ = JSON.parse(call.arguments)
      if (!call.name || !arguments_ || typeof arguments_ !== "object" || Array.isArray(arguments_)) return []
      return [{ name: call.name, arguments: arguments_ }]
    } catch { return [] }
  })
  return { content, usage, model, created, id, toolCalls, finishReasons }
}

function responseWithToolCall(original: Response, parsed: { content: string; usage: any; model: string; created: number; id: string }, call: { name: string; arguments: Record<string, unknown> }) {
  const headers = new Headers(original.headers)
  headers.delete("content-length")
  headers.delete("content-encoding")
  headers.set("content-type", "text/event-stream; charset=utf-8")
  headers.set("cache-control", "no-cache")
  const id = `call_toolbridge_${++callSequence}`
  const chunks = [
    { id: parsed.id, object: "chat.completion.chunk", created: parsed.created, model: parsed.model, choices: [{ index: 0, delta: { role: "assistant" }, finish_reason: null }] },
    { id: parsed.id, object: "chat.completion.chunk", created: parsed.created, model: parsed.model, choices: [{ index: 0, delta: { tool_calls: [{ index: 0, id, type: "function", function: { name: call.name, arguments: JSON.stringify(call.arguments) } }] }, finish_reason: null }] },
    { id: parsed.id, object: "chat.completion.chunk", created: parsed.created, model: parsed.model, choices: [{ index: 0, delta: {}, finish_reason: "tool_calls" }], ...(parsed.usage ? { usage: parsed.usage } : {}) },
  ]
  const body = chunks.map((chunk) => `data: ${JSON.stringify(chunk)}\n\n`).join("") + "data: [DONE]\n\n"
  return new Response(body, { status: original.status, statusText: original.statusText, headers })
}

function responseWithNotice(original: Response, parsed: { usage: any; model: string; created: number; id: string }, notice: string) {
  const headers = new Headers(original.headers)
  headers.delete("content-length")
  headers.delete("content-encoding")
  headers.set("content-type", "text/event-stream; charset=utf-8")
  headers.set("cache-control", "no-cache")
  const chunks = [
    { id: parsed.id, object: "chat.completion.chunk", created: parsed.created, model: parsed.model, choices: [{ index: 0, delta: { role: "assistant", content: notice }, finish_reason: null }] },
    { id: parsed.id, object: "chat.completion.chunk", created: parsed.created, model: parsed.model, choices: [{ index: 0, delta: {}, finish_reason: "stop" }], ...(parsed.usage ? { usage: parsed.usage } : {}) },
  ]
  const body = chunks.map((chunk) => `data: ${JSON.stringify(chunk)}\n\n`).join("") + "data: [DONE]\n\n"
  return new Response(body, { status: original.status, statusText: original.statusText, headers })
}

function responseProgressChunk(id: string, elapsedSeconds: number, receivedBytes: number) {
  const content = `[DRONE STATUS] LM Studio stream: ${receivedBytes} bytes received after ${elapsedSeconds}s. The bridge is still validating the complete proposal; no tool has run. This status is bridge-generated, not model output.`
  return `data: ${JSON.stringify({
    id,
    object: "chat.completion.chunk",
    created: Math.floor(Date.now() / 1000),
    model: "localcoder-toolbridge",
    choices: [{ index: 0, delta: { content }, finish_reason: null }],
  })}\n\n`
}

function responseWithBridgeProgress(
  original: Response,
  run: (signal: AbortSignal, onBytes: (count: number) => void, streamID: string) => Promise<Response>,
) {
  const headers = new Headers(original.headers)
  headers.delete("content-length")
  headers.delete("content-encoding")
  headers.set("content-type", "text/event-stream; charset=utf-8")
  headers.set("cache-control", "no-cache")
  const abort = new AbortController()
  const streamID = `chatcmpl-localcoder-progress-${Date.now()}`
  let timer: ReturnType<typeof setInterval> | undefined
  let finalReader: ReadableStreamDefaultReader<Uint8Array> | undefined
  let finished = false
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      const encoder = new TextEncoder()
      const startedAt = Date.now()
      let receivedBytes = 0
      timer = setInterval(() => {
        if (finished || abort.signal.aborted) return
        const elapsedSeconds = Math.floor((Date.now() - startedAt) / 1000)
        controller.enqueue(encoder.encode(responseProgressChunk(streamID, elapsedSeconds, receivedBytes)))
      }, 20_000)
      void run(abort.signal, (count) => { receivedBytes += count }, streamID).then(async (finalResponse) => {
        if (timer) clearInterval(timer)
        finalReader = finalResponse.body?.getReader()
        if (finalReader) {
          try {
            while (!abort.signal.aborted) {
              const result = await finalReader.read()
              if (result.done) break
              controller.enqueue(result.value)
            }
          } finally {
            finalReader.releaseLock()
            finalReader = undefined
          }
        }
        finished = true
        if (!abort.signal.aborted) controller.close()
      }).catch((error) => {
        if (timer) clearInterval(timer)
        finished = true
        if (!abort.signal.aborted) controller.error(error)
      })
    },
    cancel(reason) {
      finished = true
      if (timer) clearInterval(timer)
      abort.abort(reason)
      if (finalReader) void finalReader.cancel(reason).catch(() => {})
    },
  })
  return new Response(body, { status: original.status, statusText: original.statusText, headers })
}

async function responseTextWithProgress(response: Response, signal: AbortSignal, onBytes: (count: number) => void) {
  const reader = response.body?.getReader()
  if (!reader) return ""
  const decoder = new TextDecoder()
  let raw = ""
  const cancel = () => { void reader.cancel(signal.reason).catch(() => {}) }
  signal.addEventListener("abort", cancel, { once: true })
  try {
    while (!signal.aborted) {
      const result = await reader.read()
      if (result.done) break
      onBytes(result.value.byteLength)
      raw += decoder.decode(result.value, { stream: true })
    }
    raw += decoder.decode()
    return raw
  } finally {
    signal.removeEventListener("abort", cancel)
    reader.releaseLock()
  }
}

const projectRoot = "L:\\LocalCoder"
const memoryRoot = `${projectRoot}\\workspace\\aios_rebuild\\memory\\hermes_agent\\memories`
const memoryHelper = `${projectRoot}\\.opencode\\plugins\\localcoder-memory-gate.py`
const memoryReadTool = `${projectRoot}\\workspace\\hive_control\\target\\release\\coding_agent_read.exe`
const projectPython = "L:\\.venv\\Scripts\\python.exe"

function textParts(message: any): string {
  const infoText = typeof message?.info?.text === "string" ? message.info.text : ""
  const directText = typeof message?.text === "string" ? message.text : typeof message?.content === "string" ? message.content : ""
  const rawParts = Array.isArray(message?.parts) ? message.parts : Array.isArray(message?.content) ? message.content : []
  const partText = rawParts
    .filter((part: any) => part?.type === "text" && typeof part.text === "string")
    .map((part: any) => part.text)
    .join("\n")
  return [infoText, directText, partText].filter(Boolean).join("\n")
}

function isUserMessage(message: any): boolean {
  if ((message?.info?.role ?? message?.info?.type ?? message?.role ?? message?.type) !== "user") return false
  return !isSyntheticInstructionMessage(message, textParts(message))
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

function directMemoryRequest(text: string): boolean {
  const intent = /\b(?:remember|save|store|add|write|update|make sure)\b/i.test(text)
  const target = /\b(?:memory|USER\.md|user profile|this model knows)\b/i.test(text)
  const negated = /\b(?:don't|do not|never)\s+(?:remember|save|store|write|update)\b/i.test(text)
  return intent && target && !negated
}

function digest(bytes: Uint8Array): string {
  return createHash("sha256").update(bytes).digest("hex")
}

function toolKey(event: any, filePath?: string): string {
  return String(event?.sessionID ?? "") + ":" + String(event?.tool ?? "") + ":" + String(filePath ?? "")
}

async function assertInsideProject(path: string): Promise<string> {
  const root = await realpath("L:\\LocalCoder")
  const actual = await realpath(path)
  const rel = relative(root, actual)
  if (!rel || rel === ".." || rel.startsWith(".." + sep) || isAbsolute(rel)) {
    throw new Error("OpenCode tool file path resolves outside L:\\LocalCoder")
  }
  return actual
}

const ALLOWED_DRIVE_ROOTS = new Set(["D:\\", "E:\\", "F:\\", "L:\\"])

async function assertAllowedDrivePath(path: string): Promise<string> {
  const requested = resolve(isAbsolute(path) ? path : `${projectRoot}\\${path}`)
  const requestedRoot = parse(requested).root.toLocaleUpperCase()
  if (!ALLOWED_DRIVE_ROOTS.has(requestedRoot)) {
    throw new Error(`Drone path denied: only D:, E:, F:, and L: are available; received ${requestedRoot || "an unsupported path"}.`)
  }
  let probe = requested
  const missing: string[] = []
  while (true) {
    try {
      let actual = await realpath(probe)
      const actualRoot = parse(actual).root.toLocaleUpperCase()
      if (!ALLOWED_DRIVE_ROOTS.has(actualRoot)) {
        throw new Error(`Drone path denied: resolved path leaves D:, E:, F:, and L: (${actualRoot || "unknown root"}).`)
      }
      for (const part of missing.reverse()) actual = resolve(actual, part)
      return actual
    } catch (error: any) {
      if (error?.code !== "ENOENT" && error?.code !== "ENOTDIR") throw error
      const parent = dirname(probe)
      if (parent === probe) throw error
      missing.push(basename(probe))
      probe = parent
    }
  }
}

function containsCDriveReference(value: string): boolean {
  return /\bC:/i.test(value)
}

function pathNamedInPrompt(path: string, prompt: string): boolean {
  const normalize = (value: string) => value.replace(/[\\/]+/g, "\\").toLocaleLowerCase()
  const normalizedPrompt = normalize(prompt)
  if (normalizedPrompt.includes(normalize(path))) return true
  const rel = relative(projectRoot, path)
  return !isAbsolute(rel) && rel !== ".." && !rel.startsWith(`..${sep}`)
    && normalizedPrompt.includes(normalize(rel))
}

function exactWritePayload(prompt: string): string | undefined {
  if (!/\b(?:write|save|put|create)\b[\s\S]{0,240}\bexact(?:ly)?\b/i.test(prompt)
      && !/\bexact(?:ly)?\b[\s\S]{0,240}\b(?:write|save|content|text)\b/i.test(prompt)) return undefined
  const blocks = [...prompt.matchAll(/```(?:text|txt|plaintext)?(?:\r?\n)?([\s\S]*?)(?:\r?\n)?```/gi)]
  return blocks.length === 1 ? blocks[0][1] : undefined
}

function expectedPatchPaths(prompt: string): string[] | undefined {
  const blocks = [...prompt.matchAll(/<localcoder_patch_paths>\s*([\s\S]*?)\s*<\/localcoder_patch_paths>/gi)]
  if (!blocks.length) return undefined
  if (blocks.length !== 1) throw new Error("Patch path contract must appear exactly once.")
  const paths = blocks[0][1].split(/\r?\n/).map((path) => path.trim()).filter(Boolean)
  if (!paths.length || new Set(paths.map((path) => path.toLocaleLowerCase())).size !== paths.length) {
    throw new Error("Patch path contract must contain distinct project-relative paths.")
  }
  return paths
}

function samePatchPathSet(expected: string[], proposed: string[]): boolean {
  const normalize = (path: string) => path.replace(/[\\/]+/g, "\\").toLocaleLowerCase()
  const left = expected.map(normalize).sort()
  const right = proposed.map(normalize).sort()
  return left.length === right.length && left.every((path, index) => path === right[index])
}

async function writeToolReceipt(record: Record<string, unknown>) {
  const requestedDirectory = "L:\\LocalCoder\\.opencode\\receipts"
  await mkdir(requestedDirectory, { recursive: true })
  const directory = await assertInsideProject(requestedDirectory)
  const path = directory + "\\" + Date.now() + "-" + randomUUID() + ".json"
  const handle = await open(path, "wx")
  try {
    await handle.writeFile(JSON.stringify(record, null, 2), "utf8")
    await handle.sync()
  } finally {
    await handle.close()
  }
}

async function writeBridgeDiagnostic(record: Record<string, unknown>) {
  try {
    await writeToolReceipt({ schema: "lmstudio_toolbridge_diagnostic_v1", ...record })
  } catch (error: any) {
    console.warn(`[localcoder-toolbridge] diagnostic_receipt_failed reason=${String(error?.message ?? error)}`)
  }
}

async function writeRequestTrace(record: Record<string, unknown>) {
  const requested = process.env.LOCALCODER_TRACE_LLM_PATH
  if (process.env.LOCALCODER_TRACE_LLM !== "1" || !requested) return
  const directory = await realpath(`${projectRoot}\\.opencode\\evals`)
  const path = resolve(requested)
  const rel = relative(directory, path)
  if (!rel || rel === ".." || rel.startsWith(".." + sep) || isAbsolute(rel)) throw new Error("Request trace output must be a file directly under .opencode/evals.")
  try { await assertInsideProject(path) }
  catch (error: any) { if (error?.code !== "ENOENT") throw error }
  const line = JSON.stringify(record) + "\n"
  traceWriteQueue = traceWriteQueue.catch(() => undefined).then(async () => {
    const handle = await open(path, "a")
    try { await handle.writeFile(line, "utf8"); await handle.sync() }
    finally { await handle.close() }
  })
  await traceWriteQueue
}

function fileTarget(input: any): string | undefined {
  for (const key of ["filePath", "path", "file_path", "filename"]) {
    if (typeof input?.[key] === "string" && input[key].trim()) return input[key].trim()
  }
  return undefined
}

function fileTargets(input: any): string[] {
  const batch = Array.isArray(input?.changes)
    ? input.changes.map((change: any) => fileTarget(change)).filter((path: unknown): path is string => typeof path === "string")
    : []
  const single = fileTarget(input)
  return [...new Set([...batch, ...(single ? [single] : [])])]
}

async function sealPreEdit(rawPath: string): Promise<{ path: string; beforeHash?: string; snapshot?: string }> {
  const projectRoot = "L:\\LocalCoder"
  const requestedPath = resolve(isAbsolute(rawPath) ? rawPath : projectRoot + "\\" + rawPath)
  const absolutePath = await assertAllowedDrivePath(requestedPath)
  let beforeHash: string | undefined
  let snapshot: string | undefined
  try {
    const info = await stat(absolutePath)
    if (!info.isFile()) throw new Error("OpenCode edit target is not a regular file")
    if (info.size > 8 * 1024 * 1024) throw new Error("OpenCode edit target exceeds the 8 MiB snapshot limit")
    const bytes = await readFile(absolutePath)
    beforeHash = digest(bytes)
    const requestedDirectory = projectRoot + "\\.opencode\\snapshots"
    await mkdir(requestedDirectory, { recursive: true })
    const directory = await assertInsideProject(requestedDirectory)
    snapshot = directory + "\\" + beforeHash + ".snapshot"
    try {
      const handle = await open(snapshot, "wx")
      try { await handle.writeFile(bytes); await handle.sync() }
      finally { await handle.close() }
    } catch (error: any) {
      if (error?.code !== "EEXIST") throw error
      if (digest(await readFile(snapshot)) !== beforeHash) throw new Error("Existing pre-edit snapshot failed SHA-256 verification")
    }
  } catch (error: any) {
    if (error?.code !== "ENOENT") throw error
  }
  return { path: absolutePath, beforeHash, snapshot }
}

export default Plugin.define({
  id: "localcoder.lmstudio-toolbridge",
  async setup(ctx) {
    await ctx.session.hook("context", async (event: any) => {
      const [memory, user] = await Promise.all([
        readFile(`${memoryRoot}\\MEMORY.md`, "utf8"),
        readFile(`${memoryRoot}\\USER.md`, "utf8"),
      ])
      if (memory.length + user.length > 32768) throw new Error("LocalCoder persistent context exceeds 32 KiB; refusing silent truncation")
      event.system.push({ type: "text", text: `<localcoder_persistent_memory>\n<MEMORY.md>\n${memory}\n</MEMORY.md>\n<USER.md>\n${user}\n</USER.md>\n</localcoder_persistent_memory>` })
    }, { providerID: "lmstudio" })

    await ctx.tool.transform((editor: any) => {
      editor.add({
        name: "localcoder_status",
        description: "Read LocalCoder project, integration, persistent-memory, and receipt paths and availability. Read-only; never launches work.",
        input: { type: "object", properties: {}, additionalProperties: false },
        options: { codemode: false },
        execute: async () => {
          const stateRoot = `${projectRoot}\\workspace\\aios_rebuild\\memory\\hermes_agent`
          const memory = `${stateRoot}\\memories`
          const openCodeReceipts = `${projectRoot}\\.opencode\\receipts`
          const hermesReceipts = `${stateRoot}\\receipts`
          const countJson = async (directory: string) => {
            try { return (await readdir(directory)).filter((name) => name.toLowerCase().endsWith(".json")).length }
            catch (error: any) { if (error?.code === "ENOENT") return 0; throw error }
          }
          const latestJson = async (directory: string) => {
            try {
              const names = (await readdir(directory)).filter((name) => name.toLowerCase().endsWith(".json")).sort()
              return names.length ? `${directory}\\${names[names.length - 1]}` : null
            } catch (error: any) { if (error?.code === "ENOENT") return null; throw error }
          }
          const [opencodeReceiptCount, hermesReceiptCount, opencodeLatestReceipt, hermesLatestReceipt,
            memoryExists, userExists] = await Promise.all([
            countJson(openCodeReceipts), countJson(hermesReceipts), latestJson(openCodeReceipts), latestJson(hermesReceipts),
            stat(`${memory}\\MEMORY.md`).then(() => true, (error: any) => { if (error?.code === "ENOENT") return false; throw error }),
            stat(`${memory}\\USER.md`).then(() => true, (error: any) => { if (error?.code === "ENOENT") return false; throw error }),
          ])
          return { content: JSON.stringify({
            project_root: projectRoot, python: "L:/.venv/Scripts/python.exe", integration_root: `${projectRoot}\\workspace`,
            instructions: `${projectRoot}\\AGENTS.md`, agent_guide: `${projectRoot}\\AGENT.md`,
            memory_directory: memory, memory_files: { "MEMORY.md": memoryExists, "USER.md": userExists },
            opencode_receipt_directory: openCodeReceipts, opencode_receipt_count: opencodeReceiptCount,
            opencode_latest_receipt: opencodeLatestReceipt, hermes_receipt_directory: hermesReceipts,
            hermes_receipt_count: hermesReceiptCount, hermes_latest_receipt: hermesLatestReceipt,
            execution_policy: "Only the current Architect-assigned task; no standing autonomous assignment.",
          }) }
        },
      })
      editor.add({
        name: "localcoder_add_python",
        description: "Write one Python source file on D:, E:, F:, or L:. The exact target must be named in the current Architect request and end in .py. Existing targets are snapshotted before replacement. Accepts up to 1 MiB of UTF-8 source.",
        input: {
          type: "object",
          properties: {
            filePath: { type: "string", description: "Project-relative path or absolute D:/E:/F:/L: path for one .py file, matching the current Architect assignment." },
            content: { type: "string", description: "Python source text for the new file." },
          },
          required: ["filePath", "content"],
          additionalProperties: false,
        },
        options: { codemode: false },
        execute: async (input: any, context: any) => {
          if (typeof input.filePath !== "string" || typeof input.content !== "string") {
            throw new Error("Python writer requires filePath and content strings.")
          }
          const rawPath = input.filePath.trim()
          const segments = rawPath.split(/[\\/]+/).filter(Boolean)
          if (!rawPath || rawPath.includes("\0")
              || segments.some((part: string) => part === "." || part === "..")) {
            throw new Error("Python writer requires a safe path with no dot segments; no file was changed.")
          }
          if (!rawPath.toLocaleLowerCase().endsWith(".py")) {
            throw new Error("Python writer accepts only .py files; no file was changed.")
          }
          const bytes = Buffer.from(input.content, "utf8")
          if (!bytes.length || bytes.length > 1024 * 1024) {
            throw new Error("Python writer requires 1 byte to 1 MiB of UTF-8 source; no file was changed.")
          }
          const requested = isAbsolute(rawPath) ? resolve(rawPath) : resolve(projectRoot, rawPath)
          const sessionID = String(context?.sessionID ?? "")
          if (!sessionID) throw new Error("Python writer requires an active OpenCode session; no file was changed.")
          const target = await assertAllowedDrivePath(requested)
          let handle: Awaited<ReturnType<typeof open>>
          try {
            handle = await open(target, "w")
          } catch (error: any) {
            throw error
          }
          try {
            await handle.writeFile(bytes)
            await handle.sync()
          } finally {
            await handle.close()
          }
          const after = await readFile(target)
          if (!after.equals(bytes)) throw new Error("Add-only Python writer verification failed; the created file was retained for inspection.")
          return { content: JSON.stringify({ ok: true, created: true, path: target, bytes: after.length, sha256: digest(after) }) }
        },
      })
      editor.add({
        name: "localcoder_write_exact",
        description: "Write only the exact contents from the single fenced text block in the Architect's current request. The supplied content must match byte-for-byte; any model-added or altered text is rejected. Use this for explicit exact-content file writes.",
        input: {
          type: "object",
          properties: {
            filePath: { type: "string", description: "Project-relative destination path inside L:\\LocalCoder." },
            content: { type: "string", description: "Must exactly equal the sole fenced text block in the current user request." },
          },
          required: ["filePath", "content"],
          additionalProperties: false,
        },
        options: { codemode: false },
        execute: async (input: any, context: any) => {
          if (typeof input.filePath !== "string" || typeof input.content !== "string") throw new Error("Exact write requires filePath and content strings.")
          const prompt = promptBySession.get(String(context.sessionID ?? "")) ?? ""
          const expected = exactWritePayload(prompt)
          if (expected === undefined) {
            const fenceCount = [...prompt.matchAll(/```/g)].length
            const hasProbe = prompt.includes("EXACT_WRITE_PROBE_20261113")
            throw new Error(`Exact write denied: captured user request did not yield one exact-content block (prompt_chars=${prompt.length}, fence_markers=${fenceCount}, probe_marker=${hasProbe}). No file was changed.`)
          }
          if (input.content !== expected) throw new Error("Exact write denied: model content differs from the Architect's fenced text. No file was changed.")
          const requested = resolve(isAbsolute(input.filePath) ? input.filePath : `${projectRoot}\\${input.filePath}`)
          const target = await assertAllowedDrivePath(requested)
          if (!pathNamedInPrompt(target, prompt)) {
            throw new Error("Exact write denied: the target path must be named in the Architect's current request. No file was changed.")
          }
          try {
            const current = await assertAllowedDrivePath(target)
            const info = await stat(current)
            if (!info.isFile() || info.size > 8 * 1024 * 1024) throw new Error("Exact write target must be a regular file no larger than 8 MiB.")
          } catch (error: any) {
            if (error?.code !== "ENOENT") throw error
          }
          if (Buffer.byteLength(expected, "utf8") > 8 * 1024 * 1024) throw new Error("Exact write content exceeds the 8 MiB limit.")
          const temporary = `${target}.${randomUUID()}.exact-tmp`
          const handle = await open(temporary, "wx")
          try { await handle.writeFile(expected, "utf8"); await handle.sync() }
          finally { await handle.close() }
          try { await rename(temporary, target) }
          catch (error) { await unlink(temporary).catch(() => undefined); throw error }
          const after = await readFile(target)
          if (!after.equals(Buffer.from(expected, "utf8"))) throw new Error("Exact write verification failed after replacement.")
          return { content: JSON.stringify({ ok: true, path: target, exact_match: true, sha256: digest(after) }) }
        },
      })
      editor.add({
        name: "localcoder_patch",
        description: "Apply strict exact-text replacements to existing project files. Provide either one filePath/oldString/newString replacement or a changes array containing up to 16 replacements across distinct files. Every oldString must match exactly once; all files are preflighted before any replacement, then each file is atomically replaced and snapshotted. No fuzzy matching.",
        input: {
          type: "object",
          properties: {
            filePath: { type: "string", description: "Project-relative path for a single replacement." },
            oldString: { type: "string", description: "Exact existing text to replace; it must match exactly once." },
            newString: { type: "string", description: "Replacement text." },
            changes: {
              type: "array", minItems: 1, maxItems: 16,
              description: "Multiple exact replacements. Each file path must be distinct.",
              items: {
                type: "object",
                properties: {
                  filePath: { type: "string", description: "Project-relative path to an existing file." },
                  oldString: { type: "string", description: "Exact existing text; must occur once." },
                  newString: { type: "string", description: "Replacement text." },
                },
                required: ["filePath", "oldString", "newString"],
                additionalProperties: false,
              },
            },
          },
          required: [],
          additionalProperties: false,
        },
        options: { codemode: false },
        execute: async (input: any, context: any) => {
          const singleMode = input.filePath !== undefined || input.oldString !== undefined || input.newString !== undefined
          const batchMode = input.changes !== undefined
          if (singleMode === batchMode) throw new Error("Provide exactly one patch form: filePath/oldString/newString or changes[].")
          const changes = batchMode ? input.changes : [{ filePath: input.filePath, oldString: input.oldString, newString: input.newString }]
          if (!Array.isArray(changes) || changes.length < 1 || changes.length > 16) throw new Error("Patch changes must contain 1-16 entries.")
          const userPrompt = promptBySession.get(String(context?.sessionID ?? "")) ?? ""
          const expectedPaths = expectedPatchPaths(userPrompt)
          if (expectedPaths) {
            const canonical = (path: string) => resolve(isAbsolute(path) ? path : `${projectRoot}\\${path}`).toLocaleLowerCase()
            const expected = expectedPaths.map(canonical)
            const proposed = changes.map((change: any) => canonical(String(change?.filePath ?? "")))
            if (!samePatchPathSet(expected, proposed)) {
              throw new Error(`Patch path coverage mismatch; expected exactly [${expectedPaths.join(", ")}], received [${changes.map((change: any) => String(change?.filePath ?? "")).join(", ")}]. No files were changed.`)
            }
          }
          const seen = new Set<string>()
          const prepared: Array<{ path: string; before: Buffer; after: Buffer }> = []
          for (const change of changes) {
            if (![change?.filePath, change?.oldString, change?.newString].every((value) => typeof value === "string" && value.length > 0)) {
              throw new Error("Each patch requires non-empty filePath, oldString, and newString strings.")
            }
            if (change.oldString === change.newString) throw new Error("Patch replacement is identical to its old text.")
            const requested = resolve(isAbsolute(change.filePath) ? change.filePath : `${projectRoot}\\${change.filePath}`)
            const target = await assertAllowedDrivePath(requested)
            if (seen.has(target.toLocaleLowerCase())) throw new Error(`Batch patch must use distinct file paths: ${target}`)
            seen.add(target.toLocaleLowerCase())
            const info = await stat(target)
            if (!info.isFile() || info.size > 8 * 1024 * 1024) throw new Error(`Patch target must be a regular file no larger than 8 MiB: ${target}`)
            const before = await readFile(target)
            const original = before.toString("utf8")
            if (!Buffer.from(original, "utf8").equals(before)) throw new Error(`Patch target is not valid UTF-8 text: ${target}`)
            const index = original.indexOf(change.oldString)
            if (index < 0 || original.indexOf(change.oldString, index + change.oldString.length) >= 0) {
              throw new Error(`Patch oldString must match exactly once; no files were changed: ${target}`)
            }
            const updated = original.slice(0, index) + change.newString + original.slice(index + change.oldString.length)
            prepared.push({ path: target, before, after: Buffer.from(updated, "utf8") })
          }

          const staged: Array<{ path: string; temporary: string; before: Buffer; after: Buffer }> = []
          try {
            for (const item of prepared) {
              const temporary = `${item.path}.${randomUUID()}.patch-tmp`
              const handle = await open(temporary, "wx")
              try { await handle.writeFile(item.after); await handle.sync() }
              finally { await handle.close() }
              staged.push({ ...item, temporary })
            }
          } catch (error) {
            await Promise.all(staged.map((item) => unlink(item.temporary).catch(() => undefined)))
            throw error
          }

          const committed: string[] = []
          try {
            for (const item of staged) {
              if (await assertAllowedDrivePath(item.path) !== item.path) throw new Error(`Patch target changed before replacement: ${item.path}`)
              await rename(item.temporary, item.path)
              committed.push(item.path)
            }
          } catch (error: any) {
            await Promise.all(staged.filter((item) => !committed.includes(item.path)).map((item) => unlink(item.temporary).catch(() => undefined)))
            throw new Error(`Batch patch stopped after committing ${committed.length}/${staged.length} file(s); inspect snapshots and per-file receipts. ${String(error?.message ?? error)}`)
          }

          const results = []
          for (const item of staged) {
            const result = await readFile(item.path)
            if (!result.equals(item.after)) throw new Error(`Patch verification mismatch after replacement: ${item.path}`)
            results.push({ path: item.path, before_sha256: digest(item.before), after_sha256: digest(result) })
          }
          return { content: JSON.stringify({ ok: true, changes: results }) }
        },
      })
      editor.add({
        name: "localcoder_memory_append",
        description: "Append one exact statement or preference the Architect explicitly asked to persist. Requires a direct memory instruction in the current user message. Stores the exact quote with hashes, a prior snapshot, a PrivacyCore check, and the Rust authority receipt.",
        input: {
          type: "object",
          properties: {
            quote: { type: "string", description: "Exact substring from the current user message to persist; do not paraphrase or add facts." },
            target: { type: "string", enum: ["USER.md", "MEMORY.md"], description: "USER.md for preferences; MEMORY.md for stable project facts." },
          },
          required: ["quote", "target"],
          additionalProperties: false,
        },
        options: { codemode: false },
        execute: async (input: any, context: any) => {
          const history = await ctx.session.context({ sessionID: context.sessionID })
          const allMessages = contextMessages(history)
          const userMessages = allMessages
            .filter(isUserMessage)
            .map(textParts)
          const current = userMessages.at(-1) ?? ""
          if (!directMemoryRequest(current)) {
            const keys = history && typeof history === "object" ? Object.keys(history).join(",") : typeof history
            const roles = allMessages.slice(-4).map((message: any) => `${message?.info?.role ?? message?.role ?? message?.type ?? "?"}:${textParts(message).length}`).join(";")
            const latest = allMessages.filter(isUserMessage).at(-1)
            const shape = latest ? `message=${Object.keys(latest).join("/")}; info=${Object.keys(latest.info ?? {}).join("/")}; parts=${Array.isArray(latest.parts) ? latest.parts.map((part: any) => `${part?.type ?? "?"}:${Object.keys(part ?? {}).join("/")}`).join(",") : typeof latest.parts}` : "no-user"
            throw new Error(`Memory append denied: no direct memory request found in the current user message (${shape}; context keys=${keys}; messages=${allMessages.length}; tail=${roles}).`)
          }
          if (typeof input.quote !== "string" || !current.includes(input.quote)) throw new Error("Memory append denied: quote must match the current user message exactly.")
          const payload = JSON.stringify({ target: input.target, quote: input.quote, user_messages: [current], session_id: context.sessionID })
          const output = execFileSync(projectPython, [memoryHelper], { input: payload, encoding: "utf8", timeout: 25000, windowsHide: true })
          return { content: output.trim() }
        },
      })
      editor.add({
        name: "localcoder_memory_read",
        description: "Search the current persistent LocalCoder MEMORY.md or USER.md through the existing scoped Rust file reader and return exact matching lines with the file hash. Use this to answer questions about stored project context or Architect preferences; this is agent memory, not Viv learned memory.",
        input: {
          type: "object",
          properties: {
            target: { type: "string", enum: ["USER.md", "MEMORY.md"], description: "Choose the persistent user preferences or project facts file." },
            query: { type: "string", description: "A distinctive exact phrase to find in the file; matching is case-insensitive." },
          },
          required: ["target", "query"],
          additionalProperties: false,
        },
        options: { codemode: false },
        execute: async (input: any, context: any) => {
          if (!(["USER.md", "MEMORY.md"] as string[]).includes(input.target)) throw new Error("Memory read target is not allowlisted.")
          const history = contextMessages(await ctx.session.context({ sessionID: context.sessionID }))
          const current = history.filter(isUserMessage).map(textParts).at(-1) ?? ""
          const queryClause = current.match(/\bquery\s+([^\n.!?]+)/i)?.[1]?.trim()
          const userQuery = queryClause?.replace(/^["“']|["”']$/g, "").trim()
          const query = userQuery || (typeof input.query === "string" ? input.query.trim() : "")
          if (query.length < 3 || query.length > 120) throw new Error("Memory search phrase must be 3-120 characters.")
          const relative = `aios_rebuild/memory/hermes_agent/memories/${input.target}`
          const raw = execFileSync(memoryReadTool, [`${projectRoot}\\workspace`], {
            input: JSON.stringify({ path: relative }), encoding: "utf8", timeout: 10000, windowsHide: true,
          })
          const result = JSON.parse(raw)
          if (result.ok !== true || typeof result.content !== "string") throw new Error("Rust memory read returned an invalid result.")
          const matches = result.content.split(/\r?\n/).filter((line: string) => line.toLocaleLowerCase().includes(query.toLocaleLowerCase()))
          return { content: JSON.stringify({ ok: true, path: result.path, sha256: result.sha256, query, matches }) }
        },
      })
    })

    await ctx.tool.hook("execute.before", async (event: any) => {
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
      const serializedInput = JSON.stringify(event.input ?? {})
      if (containsCDriveReference(serializedInput)) {
        const reason = "C: is permanently forbidden. No tool action was executed."
        await writeToolReceipt({
          schema: "opencode_tool_v1", event: "blocked", receipt_id: randomUUID(),
          session_id: event.sessionID, tool: event.tool,
          input_sha256: digest(new TextEncoder().encode(serializedInput)),
          path: fileTargets(event.input)[0] ?? null, reason, captured_at: new Date().toISOString(),
        })
        throw new Error(reason)
      }
      const rawPaths = fileTargets(event.input)
      const rawPath = rawPaths[0]
      const activePrompt = promptForCurrentAuthorization(String(event.sessionID ?? ""))
      const explicitSequence = explicitToolSequenceBySession.get(String(event.sessionID ?? ""))
      if (explicitSequence?.failed) {
        const reason = `The explicit task already failed at ${explicitSequence.failed}; no retry or later tool will run.`
        await writeToolReceipt({
          schema: "opencode_tool_v1", event: "blocked", receipt_id: randomUUID(),
          session_id: event.sessionID, tool: event.tool,
          input_sha256: digest(new TextEncoder().encode(JSON.stringify(event.input ?? {}))),
          path: rawPath, reason, captured_at: new Date().toISOString(),
        })
        throw new Error(reason)
      }
      if (explicitSequence?.tools.length) {
        const expected = nextExplicitTool(explicitSequence)
        if (!expected || String(event.tool) !== expected) {
          explicitSequence.failed = "out_of_order_tool_attempt"
          const inputHash = digest(new TextEncoder().encode(JSON.stringify(event.input ?? {})))
          const reason = expected
            ? `Explicit tool order requires ${expected} before ${String(event.tool)}.`
            : `All explicitly requested tools have completed; ${String(event.tool)} is outside the sequence.`
          await writeToolReceipt({
            schema: "opencode_tool_v1", event: "blocked", receipt_id: randomUUID(),
            session_id: event.sessionID, tool: event.tool, input_sha256: inputHash, path: rawPath,
            reason, captured_at: new Date().toISOString(),
          })
          throw new Error(`${reason} No tool was executed.`)
        }
      }
      if (String(event.tool) === "aios_router_classify_task") {
        const assignment = trustedRouterAssignment(activePrompt)
        const bounds = assignment ? trustedRouterBounds(assignment) : undefined
        if (bounds) event.input = { ...(event.input ?? {}), label: bounds.taskClass }
      }
      if (routerMutationTools.has(String(event.tool))) {
        try {
          bindRouterMutation(event, String(event.sessionID ?? ""), activePrompt)
        } catch (error: any) {
          const sessionID = String(event.sessionID ?? "")
          const sequence = explicitToolSequenceBySession.get(sessionID)
          const reason = String(error?.message ?? error)
          if (sequence) sequence.failed = `router_mutation_binding_failed:${String(event.tool)}`
          await writeToolReceipt({
            schema: "opencode_tool_v1", event: "blocked", receipt_id: randomUUID(),
            session_id: sessionID, tool: event.tool,
            input_sha256: digest(new TextEncoder().encode(JSON.stringify(event.input ?? {}))),
            path: rawPath, reason, captured_at: new Date().toISOString(),
          })
          console.warn(`[localcoder-toolbridge] router_mutation_denied session=${sessionID} tool=${String(event.tool)} reason=${reason}`)
          throw error
        }
      }
      const editsFiles = ["edit", "write", "patch", "localcoder_patch", "localcoder_write_exact", "localcoder_add_python", "apply_patch"].includes(String(event.tool).toLowerCase())
      const inputHash = digest(new TextEncoder().encode(JSON.stringify(event.input ?? {})))
      const paths = rawPaths.length ? rawPaths : [undefined]
      const sealedItems: Array<{ rawPath?: string; sealed: { path?: string; beforeHash?: string; snapshot?: string }; receiptId: string }> = []
      try {
        for (const itemPath of paths) {
          const sealed = editsFiles && itemPath ? await sealPreEdit(itemPath) : {}
          sealedItems.push({ rawPath: itemPath, sealed, receiptId: randomUUID() })
        }
      } catch (error: any) {
        await writeToolReceipt({
          schema: "opencode_tool_v1", event: "blocked", receipt_id: randomUUID(),
          session_id: event.sessionID, tool: event.tool, input_sha256: inputHash,
          path: rawPath, reason: String(error?.message ?? error), captured_at: new Date().toISOString(),
        })
        throw error
      }
      for (const { rawPath: itemPath, sealed, receiptId } of sealedItems) {
        const keyPath = itemPath ? resolve(isAbsolute(itemPath) ? itemPath : `${projectRoot}\\${itemPath}`) : undefined
        const key = toolKey(event, keyPath)
        const queue = preToolByKey.get(key) ?? []
        queue.push({ ...sealed, inputHash, receiptId })
        preToolByKey.set(key, queue)
        await writeToolReceipt({
          schema: "opencode_tool_v1", event: "before", receipt_id: receiptId,
          session_id: event.sessionID, tool: event.tool, input_sha256: inputHash,
          ...(sealed.path ? { path: sealed.path } : {}),
          ...(sealed.beforeHash ? { before_sha256: sealed.beforeHash } : {}),
          ...(sealed.snapshot ? { snapshot: sealed.snapshot } : {}),
          captured_at: new Date().toISOString(),
        })
      }
    })

    await ctx.tool.hook("execute.after", async (event: any) => {
      const rawPaths = fileTargets(event.input)
      const routerSessionID = String(event.sessionID ?? "")
      const routerBinding = routerTaskBindingsBySession.get(routerSessionID)
      if (event.tool === "aios_router_open_build_task" && routerBinding) {
        routerBinding.opened = event.status === "completed" && routerToolResultOk(event.result)
      }
      if (event.tool === "aios_router_accept_self_prompt" && routerBinding
        && event.status === "completed" && routerToolResultOk(event.result)) {
        const laneId = String(event.input?.lane_id ?? "")
        const turn = Number(event.input?.turn)
        if (routerBinding.laneIds.includes(laneId) && Number.isInteger(turn)
            && turn >= 0 && turn < routerBinding.maxTurnsPerLane) {
          routerBinding.acceptedTurns.set(laneId, turn)
        }
      }
      if (event.tool === "aios_router_record_turn_result" && routerBinding
        && event.status === "completed" && routerToolResultOk(event.result)) {
        const laneId = String(event.input?.lane_id ?? "")
        const turn = Number(event.input?.turn)
        if (routerBinding.laneIds.includes(laneId) && Number.isInteger(turn)
            && turn >= 0 && turn < routerBinding.maxTurnsPerLane) {
          routerBinding.nextTurnByLane.set(laneId, turn + 1)
          routerBinding.acceptedTurns.delete(laneId)
        }
      }
      if ((event.tool === "aios_router_complete_lane" || event.tool === "aios_router_stop_task") && routerBinding
        && event.status === "completed" && routerToolResultOk(event.result)) {
        routerTaskBindingsBySession.delete(routerSessionID)
        trustedAssignmentPromptsBySession.delete(routerSessionID)
      }

      if (event.tool === "read" && event.status === "completed") {
        const sessionID = String(event.sessionID ?? "")
        const inspected = inspectedFilesBySession.get(sessionID) ?? new Map<string, string>()
        for (const target of rawPaths) {
          const absolute = resolve(isAbsolute(target) ? target : projectRoot + "\\" + target)
          try { inspected.set(absolute.toLowerCase(), digest(await readFile(absolute))) }
          catch { /* A missing or changed read target does not authorize an edit. */ }
        }
        inspectedFilesBySession.set(sessionID, inspected)
        while (inspectedFilesBySession.size > 128) inspectedFilesBySession.delete(inspectedFilesBySession.keys().next().value!)
      }
      const paths = rawPaths.length ? rawPaths : [undefined]
      const explicitSequence = explicitToolSequenceBySession.get(String(event.sessionID ?? ""))
      if (explicitSequence?.tools.length && event.status !== "completed") {
        explicitSequence.failed = `${String(event.tool)}_${String(event.status)}`
      }
      if (explicitSequence?.tools.length && routerMutationTools.has(String(event.tool))
        && event.status === "completed" && !routerToolResultOk(event.result)) {
        explicitSequence.failed = `${String(event.tool)}_rejected_result`
      }
      if (explicitSequence?.tools.length && !explicitSequence.failed
        && recordExplicitToolCompletion(explicitSequence, String(event.tool), String(event.status))) {
        console.info(`[localcoder-toolbridge] completed explicit tool step ${explicitSequence.completed.length}/${explicitSequence.tools.length}: ${String(event.tool)}`)
      }
      for (const rawPath of paths) {
        const absolutePath = rawPath ? resolve(isAbsolute(rawPath) ? rawPath : "L:\\LocalCoder\\" + rawPath) : undefined
        const key = toolKey(event, absolutePath)
        const queue = preToolByKey.get(key) ?? []
        const prior = queue.shift()
        if (queue.length) preToolByKey.set(key, queue)
        else preToolByKey.delete(key)
        let afterHash: string | undefined
        if (prior?.path && event.status === "completed") {
          try {
            const info = await stat(prior.path)
            if (info.isFile() && info.size <= 8 * 1024 * 1024) afterHash = digest(await readFile(prior.path))
          } catch { /* retain the before receipt even if the target vanished */ }
        }
        await writeToolReceipt({
          schema: "opencode_tool_v1", event: "after", receipt_id: prior?.receiptId ?? randomUUID(),
          session_id: event.sessionID, tool: event.tool, status: event.status,
          input_sha256: prior?.inputHash, ...(prior?.path ? { path: prior.path } : {}),
          ...(prior?.beforeHash ? { before_sha256: prior.beforeHash } : {}),
          ...(afterHash ? { after_sha256: afterHash } : {}),
          ...(prior?.snapshot ? { snapshot: prior.snapshot } : {}),
          captured_at: new Date().toISOString(),
        })
      }
    })

    await ctx.session.hook("http.request", async (event: any) => {
      if (event.kind !== "primary" || event.request.method !== "POST") return
      try {
        const body = await event.request.clone().json()
        let tools = extractTools(body)
        const key = requestKey(event)
        const prompt = requestPrompt(body)
        let forcedDroneToolChoice: string | undefined
        const requestPath = (() => {
          try { return new URL(event.request.url).pathname }
          catch { return "" }
        })()
        if (requestPath.endsWith("/v1/chat/completions") && isDroneActionPrompt(prompt)) {
          // The Architect's explicit assignment already fixes the exact next tool.
          // Expose only that tool to the local model so it cannot drift into prose,
          // malformed XML, or a neighboring tool during a bounded Drone step.
          const nextAssignedTool = explicitlyRequestedTools(prompt, tools)[0]
          if (nextAssignedTool) {
            const providerTools = Array.isArray(body.tools) ? body.tools : []
            const focusedTools = providerTools.filter((item: any) => {
              const fn = item?.function
              const name = typeof fn?.name === "string" ? fn.name : item?.name
              return item?.type === "function" && name === nextAssignedTool
            })
            if (focusedTools.length === 1) {
              body.tools = focusedTools
              tools = extractTools(body)
              const headers = new Headers(event.request.headers)
              headers.delete("content-length")
              body.tool_choice = "required"
              event.request = new Request(event.request, {
                headers,
                body: JSON.stringify(body),
              })
              forcedDroneToolChoice = nextAssignedTool
              console.info(`[localcoder-toolbridge] drone_next_tool_required session=${event.sessionID ?? "unknown"} tool=${nextAssignedTool}`)
            }
          }
        } else if (requestPath.endsWith("/v1/chat/completions") && tools.size === 1 && tools.has("aios_router_lookup_drone_seed")) {
          const headers = new Headers(event.request.headers)
          headers.delete("content-length")
          body.tool_choice = "required"
          event.request = new Request(event.request, {
            headers,
            body: JSON.stringify(body),
          })
          forcedDroneToolChoice = "aios_router_lookup_drone_seed"
          console.info(`[localcoder-toolbridge] drone_seed_bootstrap_required session=${event.sessionID ?? "unknown"}`)
        }
        if (isDroneActionPrompt(prompt)) {
          const requestMessages = Array.isArray(body.messages)
            ? body.messages
            : Array.isArray(body.input) ? body.input : []
          const requestTextChars = typeof body.input === "string"
            ? body.input.length
            : requestMessages.reduce((total: number, message: any) =>
              total + messageText(message?.content ?? message?.text).length, 0)
          const systemTextChars = requestMessages
            .filter((message: any) => ["system", "developer"].includes(String(message?.role ?? "")))
            .reduce((total: number, message: any) =>
              total + messageText(message?.content ?? message?.text).length, 0)
          const diagnostic = {
            request_id: randomUUID(),
            session_id: event.sessionID ?? null,
            request_path: requestPath,
            model: typeof body.model === "string" ? body.model : null,
            prompt_chars: prompt.length,
            prompt_sha256: digest(new TextEncoder().encode(prompt)),
            request_body_chars: JSON.stringify(body).length,
            request_text_chars: requestTextChars,
            system_text_chars: systemTextChars,
            output_token_limit: body.max_completion_tokens ?? body.max_output_tokens ?? body.max_tokens ?? null,
            inference_parameters: {
              temperature: typeof body.temperature === "number" ? body.temperature : null,
              top_p: typeof body.top_p === "number" ? body.top_p : null,
              seed: Number.isSafeInteger(body.seed) ? body.seed : null,
              reasoning_effort: typeof body.reasoning_effort === "string"
                ? body.reasoning_effort
                : typeof body.reasoning?.effort === "string" ? body.reasoning.effort : null,
              frequency_penalty: typeof body.frequency_penalty === "number" ? body.frequency_penalty : null,
              presence_penalty: typeof body.presence_penalty === "number" ? body.presence_penalty : null,
            },
            tool_field_count: Array.isArray(body.tools) ? body.tools.length : 0,
            tool_schemas: diagnosticToolSchemas(tools),
            tool_choice: diagnosticToolChoice(body.tool_choice),
            forced_drone_tool_choice: forcedDroneToolChoice ?? null,
            captured_at: new Date().toISOString(),
          }
          bridgeDiagnosticsByRequest.set(key, diagnostic)
          while (bridgeDiagnosticsByRequest.size > 128) {
            bridgeDiagnosticsByRequest.delete(bridgeDiagnosticsByRequest.keys().next().value!)
          }
          await writeBridgeDiagnostic({ event: "provider_request", ...diagnostic })
        } else {
          bridgeDiagnosticsByRequest.delete(key)
        }
        if (tools.size) {
          const requestedSequence = explicitlyRequestedTools(prompt, tools)
          if (event.sessionID) {
            const previousPrompt = promptBySession.get(event.sessionID)
            if (previousPrompt !== undefined && previousPrompt !== prompt) {
              const binding = routerTaskBindingsBySession.get(event.sessionID)
              const assignment = trustedRouterAssignment(prompt)
              const sameAssignment = Boolean(assignment && binding
                && createHash("sha256").update(assignment, "utf8").digest("hex") === binding.assignmentHash)
              const internalContinuation = !assignment && trustedRouterContinuation(prompt)
              if (binding && !sameAssignment && !internalContinuation) {
                routerTaskBindingsBySession.delete(event.sessionID)
              }
            }
            promptBySession.delete(event.sessionID)
            promptBySession.set(event.sessionID, prompt)
            while (promptBySession.size > 128) promptBySession.delete(promptBySession.keys().next().value!)
            const currentAssignment = trustedRouterAssignment(prompt)
            if (currentAssignment) trustedAssignmentPromptsBySession.set(event.sessionID, prompt)
            else if (!trustedRouterContinuation(prompt)) trustedAssignmentPromptsBySession.delete(event.sessionID)
            while (trustedAssignmentPromptsBySession.size > 128) trustedAssignmentPromptsBySession.delete(trustedAssignmentPromptsBySession.keys().next().value!)
            let sequence = explicitToolSequenceBySession.get(event.sessionID)
            const internalContinuation = Boolean(sequence && trustedRouterContinuation(prompt))
            if (!sequence || (sequence.prompt !== prompt && !internalContinuation)) {
              sequence = { prompt, tools: requestedSequence, completed: [] }
              explicitToolSequenceBySession.set(event.sessionID, sequence)
            } else if (internalContinuation) {
              // Keep the Architect's original ordered tools and any failure flag
              // across the gate's bounded continuation.
              sequence.prompt = prompt
            }
            if (sequence.tools.join("\0") !== requestedSequence.join("\0")) {
              sequence.tools = requestedSequence
              sequence.completed = []
            }
            while (explicitToolSequenceBySession.size > 128) explicitToolSequenceBySession.delete(explicitToolSequenceBySession.keys().next().value!)
          }
          if (process.env.LOCALCODER_TRACE_LLM === "1") {
            const systemText = (Array.isArray(body.messages) ? body.messages : [])
              .filter((message: any) => message?.role === "system")
              .map((message: any) => messageText(message?.content))
              .join("\n")
            const memoryMatch = systemText.match(/<MEMORY\.md>\r?\n([\s\S]*?)\r?\n<\/MEMORY\.md>/)
            const userMatch = systemText.match(/<USER\.md>\r?\n([\s\S]*?)\r?\n<\/USER\.md>/)
            const [diskMemory, diskUser] = await Promise.all([
              readFile(`${memoryRoot}\\MEMORY.md`, "utf8"),
              readFile(`${memoryRoot}\\USER.md`, "utf8"),
            ])
            const memorySha = memoryMatch ? digest(new TextEncoder().encode(memoryMatch[1])) : null
            const userSha = userMatch ? digest(new TextEncoder().encode(userMatch[1])) : null
            const trace = {
              sequence: ++diagnosticRequestSequence,
              captured_at: new Date().toISOString(),
              session_id: event.sessionID ?? null,
              kind: event.kind,
              method: event.request.method,
              path: (() => { try { return new URL(event.request.url).pathname } catch { return String(event.request.url ?? "").split("?")[0] } })(),
              model: typeof body.model === "string" ? body.model : null,
              tool_names: [...tools.keys()],
              tool_choice: body.tool_choice ?? null,
              forced_drone_tool_choice: forcedDroneToolChoice ?? null,
              prompt_chars: prompt.length,
              prompt_sha256: digest(new TextEncoder().encode(prompt)),
              system_chars: systemText.length,
              persistent_memory_injected: Boolean(memoryMatch && userMatch),
              memory_sha256: memorySha,
              memory_matches_disk: memorySha === digest(new TextEncoder().encode(diskMemory)),
              user_sha256: userSha,
              user_matches_disk: userSha === digest(new TextEncoder().encode(diskUser)),
              architect_preference_injected: Boolean(userMatch?.[1].includes("Treat everything I say as truth")),
            }
            await writeRequestTrace(trace)
          }
          allowedByRequest.set(key, tools)
          promptByRequest.set(key, prompt)
          readOnlyByRequest.set(key, explicitlyReadOnly(prompt))
        } else {
          allowedByRequest.delete(key)
          promptByRequest.delete(key)
          readOnlyByRequest.delete(key)
        }
      } catch { /* non-JSON model request */ }
    }, { providerID: "lmstudio" })

    await ctx.session.hook("http.response", async (event: any) => {
      if (event.kind !== "primary") return
      const key = requestKey(event)
      const tools = allowedByRequest.get(key)
      const prompt = promptByRequest.get(key) ?? ""
      const readOnly = readOnlyByRequest.get(key) === true
      allowedByRequest.delete(key)
      promptByRequest.delete(key)
      readOnlyByRequest.delete(key)
      const original = event.response
      const normalizeResponse = async (signal: AbortSignal, onBytes: (count: number) => void, streamID: string): Promise<Response> => {
        const raw = await responseTextWithProgress(original.clone(), signal, onBytes)
        const parsed = usageFromChunks(raw)
        const normalized = streamID ? { ...parsed, id: streamID } : parsed
        const bridgeDiagnostic = bridgeDiagnosticsByRequest.get(key)
        bridgeDiagnosticsByRequest.delete(key)
        if (bridgeDiagnostic) {
          await writeBridgeDiagnostic({
            event: "provider_response",
            request_id: bridgeDiagnostic.request_id,
            session_id: event.sessionID ?? null,
            http_status: original.status,
            response_ok: original.ok,
            finish_reasons: parsed.finishReasons,
            provider_content_chars: parsed.content.length,
            content_contains_tool_markup: /<(?:tool_call|function)\b/i.test(parsed.content),
            provider_tool_calls: parsed.toolCalls.map((call) => ({ name: call.name, argument_keys: Object.keys(call.arguments) })),
            captured_at: new Date().toISOString(),
          })
        }
        if (process.env.LOCALCODER_TRACE_LLM === "1") {
          await writeRequestTrace({
            captured_at: new Date().toISOString(), event: "provider_response",
            session_id: event.sessionID ?? null, kind: event.kind,
            http_status: original.status, response_ok: original.ok,
            finish_reasons: parsed.finishReasons,
            provider_content_chars: parsed.content.length,
            provider_tool_call_names: parsed.toolCalls.map((call) => call.name),
            usage: parsed.usage ?? null,
          })
        }
        if (!tools?.size || !original.ok) {
          if (bridgeDiagnostic) {
            await writeBridgeDiagnostic({
              event: "candidate_parse",
              request_id: bridgeDiagnostic.request_id,
              session_id: event.sessionID ?? null,
              outcome: !original.ok ? "provider_http_error" : "no_tool_schema_received",
              available_tool_names: tools ? [...tools.keys()] : [],
              captured_at: new Date().toISOString(),
            })
          }
          return original
        }
        let call = parsed.toolCalls
          .map((candidate) => parseCall(JSON.stringify(candidate), tools, prompt))
          .find(Boolean) ?? parseCall(parsed.content, tools, prompt)
        if (bridgeDiagnostic) {
          await writeBridgeDiagnostic({
            event: "candidate_parse",
            request_id: bridgeDiagnostic.request_id,
            session_id: event.sessionID ?? null,
            outcome: call ? "candidate_parsed_and_schema_validated" : "no_valid_tool_candidate",
            available_tool_names: [...tools.keys()],
            requested_tool_names: explicitlyRequestedTools(prompt, tools),
            candidate_tool: call?.name ?? null,
            candidate_argument_keys: call ? Object.keys(call.arguments) : [],
            captured_at: new Date().toISOString(),
          })
        }
        if (process.env.LOCALCODER_TRACE_LLM === "1") {
          await writeRequestTrace({
            captured_at: new Date().toISOString(), event: "toolbridge_candidate",
            session_id: event.sessionID ?? null,
            provider_tool_calls: parsed.toolCalls.map((candidate) => ({
              name: candidate.name,
              argument_keys: Object.keys(candidate.arguments),
            })),
            validated_call: call ? { name: call.name, argument_keys: Object.keys(call.arguments) } : null,
            validated_schema: call ? {
              required: tools.get(call.name)?.required ?? [],
              property_names: Object.keys(tools.get(call.name)?.properties ?? {}),
            } : null,
            requested_tools: explicitlyRequestedTools(prompt, tools),
            response_header_names: [...original.headers.keys()],
          })
        }
        if (!call) return original
        const activeSequence = explicitToolSequenceBySession.get(String(event.sessionID ?? ""))
        if (activeSequence?.failed) {
          return responseWithNotice(original, normalized, `The current Architect task stopped after ${activeSequence.failed}. No further tool will run.`)
        }
        const requestedTools = explicitlyRequestedTools(prompt, tools)
        const requestedTool = requestedToolForCall(prompt, tools, call.name)
        if (requestedTools.length && !requestedTool) {
          const blockedSequence = explicitToolSequenceBySession.get(String(event.sessionID ?? ""))
          if (blockedSequence) blockedSequence.failed = "unrequested_tool_proposal"
          const requestedList = requestedTools.join(", ")
          console.warn(`[localcoder-toolbridge] blocked unrequested tool ${call.name}; explicit request was ${requestedList}`)
          return responseWithNotice(original, normalized, `Blocked ${call.name}: the Architect explicitly requested only these available tools: ${requestedList}. No tool was executed.`)
        }
        if (requestedTool && requestedTool !== call.name) {
          const target = tools.get(requestedTool)!
          const arguments_ = argumentsForRequestedTool(call, target)
          if (!arguments_) {
            const blockedSequence = explicitToolSequenceBySession.get(String(event.sessionID ?? ""))
            if (blockedSequence) blockedSequence.failed = "unroutable_tool_arguments"
            console.warn(`[localcoder-toolbridge] blocked substitute tool ${call.name}; explicit request was ${requestedTool}`)
            return responseWithNotice(original, normalized, `Blocked ${call.name}: the Architect explicitly requested ${requestedTool}, and the proposed arguments cannot be safely routed to it. No tool was executed.`)
          }
          console.warn(`[localcoder-toolbridge] routed ${call.name} request to explicitly requested tool ${requestedTool}`)
          call = { name: requestedTool, arguments: arguments_ }
        }
        const explicitSequence = explicitToolSequenceBySession.get(String(event.sessionID ?? ""))
        if (explicitSequence?.tools.length) {
          const expected = nextExplicitTool(explicitSequence)
          if (!expected || call.name !== expected) {
            const reason = expected
              ? `The next explicitly requested tool is ${expected}, but the proposal was ${call.name}. No tool was executed.`
              : `All explicitly requested tools have completed; no additional tool was executed.`
            explicitSequence.failed = "out_of_order_tool_proposal"
            console.warn(`[localcoder-toolbridge] blocked out-of-order tool ${call.name}; next=${expected ?? "none"}`)
            return responseWithNotice(original, normalized, reason)
          }
        }
        if (readOnly && isMutation(call)) {
          const blockedSequence = explicitToolSequenceBySession.get(String(event.sessionID ?? ""))
          if (blockedSequence) blockedSequence.failed = "mutation_in_read_only_request"
          console.warn(`[localcoder-toolbridge] blocked mutating tool in explicit read-only request: ${call.name}`)
          return responseWithNotice(original, normalized, `Blocked ${call.name}: the user's current request is explicitly read-only. No mutating tool was executed.`)
        }
        console.info(`[localcoder-toolbridge] normalized tool call: ${call.name}`)
        return responseWithToolCall(original, normalized, call)
      }
      const isEventStream = original.headers.get("content-type")?.toLowerCase().includes("text/event-stream") === true
      if (tools?.size && original.ok && isEventStream) {
        event.response = responseWithBridgeProgress(original, normalizeResponse)
        return
      }
      event.response = await normalizeResponse(new AbortController().signal, () => {}, "")
    }, { providerID: "lmstudio" })
  },
})
