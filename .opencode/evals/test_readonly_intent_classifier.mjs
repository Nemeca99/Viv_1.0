import assert from "node:assert/strict"
import { readFile } from "node:fs/promises"

const source = await readFile(new URL("../plugins/lmstudio-toolbridge.ts", import.meta.url), "utf8")
const signature = "function explicitlyReadOnly(prompt: string): boolean {"
const start = source.indexOf(signature)
const end = source.indexOf("\n}\n\nfunction isMutation", start)
assert.notEqual(start, -1, "read-only classifier is present")
assert.notEqual(end, -1, "read-only classifier boundary is present")
const body = source.slice(start + signature.length, end)
const classify = new Function("prompt", body)

for (const prompt of ["This request is read-only.", "Do not make any edits.", "Never write files."]) {
  assert.equal(classify(prompt), true, `must block: ${prompt}`)
}

for (const prompt of [
  "Implement this fixture; do not change any other file.",
  "Make no changes except to the named test fixture.",
  "Do not edit files outside the named fixture.",
  "Use write tool. Do not use another tool or change another file.",
]) {
  assert.equal(classify(prompt), false, `must allow scoped mutation: ${prompt}`)
}

console.log("PASS: explicit read-only requests block; scoped fixture edits remain authorized")

const requestSignature = "function explicitlyRequestedTools(prompt: string, tools: Map<string, ToolSpec>): string[] {"
const requestStart = source.indexOf(requestSignature)
const requestEnd = source.indexOf("\n}\n\nfunction requestedToolForCall", requestStart)
assert.notEqual(requestStart, -1, "explicit tool resolver is present")
assert.notEqual(requestEnd, -1, "explicit tool resolver boundary is present")
const requestBody = source.slice(requestStart + requestSignature.length, requestEnd)
  .replace("const matches: Array<{ name: string; index: number }> = []", "const matches = []")
  .replaceAll("match.index!", "match.index")
const resolveRequestedTools = new Function("prompt", "tools", requestBody)
const tools = new Map([
  ["localcoder_write_exact", {}],
  ["write", {}],
  ["localcoder_patch", {}],
  ["patch", {}],
  ["shell", {}],
])
assert.deepEqual(resolveRequestedTools("Use write tool. Then use shell tool. Do not call localcoder_write_exact tool.", tools), ["write", "shell"])
assert.deepEqual(resolveRequestedTools("Use localcoder_write_exact tool.", tools), ["localcoder_write_exact"])
assert.deepEqual(resolveRequestedTools("Use patch tool.", tools), ["patch"])
assert.deepEqual(resolveRequestedTools("Use localcoder_patch tool.", tools), ["localcoder_patch"])
assert.deepEqual(resolveRequestedTools("Call read tool. Then call edit tool. Then call edit tool again. Finally call shell tool.", new Map([["read", {}], ["edit", {}], ["shell", {}]]),), ["read", "edit", "edit", "shell"])
console.log("PASS: explicit native tool sequences take precedence over custom aliases")

const expectedPathsSignature = "function expectedPatchPaths(prompt: string): string[] | undefined {"
const expectedPathsStart = source.indexOf(expectedPathsSignature)
const expectedPathsEnd = source.indexOf("\n}\n\nfunction samePatchPathSet", expectedPathsStart)
assert.notEqual(expectedPathsStart, -1, "explicit patch path contract parser is present")
assert.notEqual(expectedPathsEnd, -1, "explicit patch path contract parser boundary is present")
const expectedPathsBody = source.slice(expectedPathsStart + expectedPathsSignature.length, expectedPathsEnd)
  .replace("const paths =", "const paths =")
const readExpectedPaths = new Function("prompt", expectedPathsBody)
assert.deepEqual(readExpectedPaths("<localcoder_patch_paths>\na.py\nb.py\n</localcoder_patch_paths>"), ["a.py", "b.py"])
assert.equal(readExpectedPaths("No coverage contract."), undefined)
assert.throws(() => readExpectedPaths("<localcoder_patch_paths>\na.py\na.py\n</localcoder_patch_paths>"))
const samePathSignature = "function samePatchPathSet(expected: string[], proposed: string[]): boolean {"
const samePathStart = source.indexOf(samePathSignature)
const samePathEnd = source.indexOf("\n}\n\nasync function writeToolReceipt", samePathStart)
assert.notEqual(samePathStart, -1, "patch path coverage gate is present")
assert.notEqual(samePathEnd, -1, "patch path coverage gate boundary is present")
const samePathBody = source.slice(samePathStart + samePathSignature.length, samePathEnd)
  .replace("const normalize = (path: string) =>", "const normalize = (path) =>")
const samePatchPathSet = new Function("expected", "proposed", samePathBody)
assert.equal(samePatchPathSet(["L:\\LocalCoder\\a.py", "L:\\LocalCoder\\b.py"], ["l:/localcoder/a.py", "l:/localcoder/b.py"]), true)
assert.equal(samePatchPathSet(["a.py", "b.py"], ["a.py"]), false)
assert.equal(samePatchPathSet(["a.py", "b.py"], ["a.py", "c.py"]), false)

const selectedSignature = "function requestedToolForCall(prompt: string, tools: Map<string, ToolSpec>, callName: string): string | undefined {"
const selectedStart = source.indexOf(selectedSignature)
const selectedEnd = source.indexOf("\n}\n\nfunction nextExplicitTool", selectedStart)
assert.notEqual(selectedStart, -1, "requested tool selector is present")
assert.notEqual(selectedEnd, -1, "requested tool selector boundary is present")
const selectedBody = source.slice(selectedStart + selectedSignature.length, selectedEnd).replace("(name: string)", "(name)")
const selectRequestedTool = new Function("prompt", "tools", "callName", "explicitlyRequestedTools", selectedBody)
const sequence = "Use write tool. Then use shell tool. Do not call localcoder_write_exact tool."
assert.equal(selectRequestedTool(sequence, tools, "localcoder_write_exact", resolveRequestedTools), "write")
assert.equal(selectRequestedTool(sequence, tools, "shell", resolveRequestedTools), "shell")

const argsSignature = "function argumentsForRequestedTool("
const argsStart = source.indexOf(argsSignature)
const argsEnd = source.indexOf("\n}\n\nfunction usageFromChunks", argsStart)
const argsBodyStartMarker = "): Record<string, unknown> | undefined {"
const argsBodyStart = source.indexOf(argsBodyStartMarker, argsStart)
assert.notEqual(argsStart, -1, "tool argument adapter is present")
assert.notEqual(argsEnd, -1, "tool argument adapter boundary is present")
assert.notEqual(argsBodyStart, -1, "tool argument adapter signature is present")
const argsBody = source.slice(argsBodyStart + argsBodyStartMarker.length, argsEnd).replaceAll("target.properties!", "target.properties")
const adaptArguments = new Function("call", "target", argsBody)
const nativeWrite = { name: "write", required: ["filePath", "content"], properties: { filePath: {}, content: {} }, additionalProperties: false }
const exactWrite = { name: "localcoder_write_exact", required: ["filePath", "content"], properties: { filePath: {}, content: {} }, additionalProperties: false }
const content = "def sum_even(values): return sum(value for value in values if value % 2 == 0)"
assert.deepEqual(adaptArguments({ name: "localcoder_write_exact", arguments: { filePath: "probe.py", content } }, nativeWrite), { filePath: "probe.py", content })
assert.deepEqual(adaptArguments({ name: "write", arguments: { filePath: "probe.py", content } }, exactWrite), { filePath: "probe.py", content })
console.log("PASS: write tool aliases preserve path and content for deterministic tool routing")

const parseSignature = "function parseCall(content: string, tools: Map<string, ToolSpec>, prompt = \"\") {"
const parseStart = source.indexOf(parseSignature)
const parseEnd = source.indexOf("\n}\n\nfunction explicitlyRequestedTools", parseStart)
assert.notEqual(parseStart, -1, "strict tool call parser is present")
assert.notEqual(parseEnd, -1, "strict tool call parser boundary is present")
const parseBody = source.slice(parseStart + parseSignature.length, parseEnd)
  .replaceAll(": any", "")
  .replaceAll("spec.properties!", "spec.properties")
  .replace("const candidates: string[]", "const candidates")
const parse = new Function("content", "tools", "prompt", "explicitlyRequestedTools", parseBody)
const toolSchemas = new Map([
  ["localcoder_patch", { name: "localcoder_patch", required: [], properties: { filePath: {}, oldString: {}, newString: {}, changes: {} }, additionalProperties: false }],
  ["edit", { name: "edit", required: ["path", "oldString", "newString"], properties: { path: {}, oldString: {}, newString: {} }, additionalProperties: false }],
  ["shell", { name: "shell", required: ["command"], properties: { command: {} }, additionalProperties: false }],
])
const sequenceProposal = [
  JSON.stringify({ name: "localcoder_patch", arguments: { filePath: "probe.py", oldString: "return None", newString: "return 0" } }),
  JSON.stringify({ name: "shell", arguments: { command: "python probe.py" } }),
].join("\n\n")
assert.equal(parse(sequenceProposal, toolSchemas, "Use localcoder_patch tool. Then use shell tool.", resolveRequestedTools).name, "localcoder_patch")
const batchPatch = { name: "localcoder_patch", arguments: { changes: [
  { filePath: "a.py", oldString: "return None", newString: "return 1" },
  { filePath: "b.py", oldString: "return None", newString: "return 2" },
] } }
assert.deepEqual(parse(JSON.stringify(batchPatch), toolSchemas, "Use localcoder_patch tool.", resolveRequestedTools), batchPatch)
assert.equal(parse('{"name":"shell","arguments":{"command":"python probe.py"}}}', toolSchemas, "", resolveRequestedTools), undefined)
const responseAfterExplanation = [
  "Explanation before the call.",
  "```python\nreturn value.strip()\n```",
  JSON.stringify({ name: "edit", arguments: { path: "probe.py", oldString: "return value", newString: "return value.strip()" } }),
].join("\n\n")
assert.equal(parse(responseAfterExplanation, toolSchemas, "Use edit tool. Then use shell tool.", resolveRequestedTools).name, "edit")
const syntheticResponse = `<tool_response>\n${JSON.stringify({ name: "shell", arguments: { command: "python probe.py" } })}\n</tool_response>`
assert.equal(parse(syntheticResponse, toolSchemas, "Use shell tool.", resolveRequestedTools), undefined)
const usageSignature = "function usageFromChunks(raw: string) {"
const usageStart = source.indexOf(usageSignature)
const usageEnd = source.indexOf("\n}\n\nfunction responseWithToolCall", usageStart)
assert.notEqual(usageStart, -1, "stream response parser is present")
assert.notEqual(usageEnd, -1, "stream response parser boundary is present")
const usageBody = source.slice(usageStart + usageSignature.length, usageEnd)
  .replaceAll(": any", "")
  .replace("const finishReasons: string[] = []", "const finishReasons = []")
  .replace("new Map<number, { name: string; arguments: string }>()", "new Map()")
const readUsage = new Function("raw", usageBody)
const structuredChunks = [
  { id: "test", model: "qwen", choices: [{ delta: { tool_calls: [{ index: 0, id: "call-1", type: "function", function: { name: "localcoder_patch", arguments: '{"filePath":"probe.py","oldString":"return None","newString":' } }] }, finish_reason: null }] },
  { id: "test", model: "qwen", choices: [{ delta: { tool_calls: [{ index: 0, function: { arguments: '"return 0"}' } }] }, finish_reason: "tool_calls" }] },
].map((chunk) => `data: ${JSON.stringify(chunk)}`).join("\n") + "\ndata: [DONE]"
const streamed = readUsage(structuredChunks)
assert.deepEqual(streamed.toolCalls, [{ name: "localcoder_patch", arguments: { filePath: "probe.py", oldString: "return None", newString: "return 0" } }])
assert.deepEqual(streamed.finishReasons, ["tool_calls"])
assert.equal(parse(JSON.stringify(streamed.toolCalls[0]), toolSchemas, "Use localcoder_patch tool.", resolveRequestedTools).name, "localcoder_patch")
const nextSignature = "function nextExplicitTool(sequence: ExplicitToolSequence): string | undefined {"
const nextStart = source.indexOf(nextSignature)
const nextEnd = source.indexOf("\n}\n\nfunction recordExplicitToolCompletion", nextStart)
assert.notEqual(nextStart, -1, "explicit tool sequence cursor is present")
assert.notEqual(nextEnd, -1, "explicit tool sequence cursor boundary is present")
const nextTool = new Function("sequence", source.slice(nextStart + nextSignature.length, nextEnd))
const recordSignature = "function recordExplicitToolCompletion(sequence: ExplicitToolSequence, tool: string, status: string): boolean {"
const recordStart = source.indexOf(recordSignature)
const recordEnd = source.indexOf("\n}\n\nfunction argumentsForRequestedTool", recordStart)
assert.notEqual(recordStart, -1, "explicit tool sequence advancement is present")
assert.notEqual(recordEnd, -1, "explicit tool sequence advancement boundary is present")
const recordTool = new Function("sequence", "tool", "status", "nextExplicitTool", source.slice(recordStart + recordSignature.length, recordEnd))
const toolSequenceState = { prompt: "probe", tools: ["read", "edit", "shell"], completed: [] }
assert.equal(nextTool(toolSequenceState), "read")
assert.equal(recordTool(toolSequenceState, "shell", "completed", nextTool), false)
assert.equal(recordTool(toolSequenceState, "read", "error", nextTool), false)
assert.equal(recordTool(toolSequenceState, "read", "completed", nextTool), true)
assert.equal(nextTool(toolSequenceState), "edit")
assert.equal(recordTool(toolSequenceState, "edit", "completed", nextTool), true)
assert.equal(nextTool(toolSequenceState), "shell")
assert.equal(recordTool(toolSequenceState, "shell", "completed", nextTool), true)
assert.equal(nextTool(toolSequenceState), undefined)
console.log("PASS: structured tool calls reassemble; explicit tool order advances only on completed calls")
