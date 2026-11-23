import assert from 'node:assert/strict'
import { readFile, writeFile } from 'node:fs/promises'
import { stripTypeScriptTypes } from 'node:module'
import { pathToFileURL } from 'node:url'

const path = 'L:/LocalCoder/.opencode/evals/failure_lookup_20261117/localcoder-failure-lookup.candidate.ts'
let source = await readFile(path, 'utf8')
source = source.replace(/import\s*\{\s*Plugin\s*\}\s*from\s*["']@opencode\/plugin["'];?/, 'const Plugin = { define: value => value }')
const transport = /import\s*\{\s*execFileSync\s*\}\s*from\s*["']node:child_process["'];?/
assert.ok(transport.test(source), 'Use the contracted execFileSync import')
source = source.replace(transport, 'const execFileSync = (...args) => globalThis.__failureLookupExec(...args)')
const file = path.replace('.candidate.ts', '.fixture.mjs')
await writeFile(file, stripTypeScriptTypes(source, { mode: 'transform', sourceUrl: path }))
const plugin = (await import(pathToFileURL(file).href)).default
assert.equal(plugin.id, 'localcoder.failure-lookup')
const tools = []
await plugin.setup({ tool: { transform: async fn => fn({ add: tool => tools.push(tool) }) } })
assert.equal(tools.length, 1)
const tool = tools[0]
assert.equal(tool.name, 'localcoder_failure_lookup')
assert.equal(tool.options.codemode, false)
assert.equal(tool.input.additionalProperties, false)
let calls = []
const payload = { schema: 'localcoder_failure_lookup_v1', failures: [], current_results: [] }
globalThis.__failureLookupExec = (...args) => { calls.push(args); return JSON.stringify(payload) }
const result = await tool.execute({ case: 'valid', limit: 3 }, {})
assert.deepEqual(JSON.parse(result.content), payload)
assert.equal(calls.length, 1)
assert.equal(calls[0][0], 'L:/.venv/Scripts/python.exe')
assert.deepEqual(calls[0][1], ['-B', 'L:/LocalCoder/workspace/autonomy/receipt_failure_lookup_candidate.py', '--limit', '3', '--case', 'valid'])
assert.equal(calls[0][2].shell, undefined)
assert.equal(calls[0][2].windowsHide, true)
assert.equal(calls[0][2].timeout, 15000)
assert.equal(calls[0][2].maxBuffer, 131072)
assert.equal(calls[0][2].encoding, 'utf8')
assert.equal(calls[0][2].cwd, 'L:/LocalCoder')
calls = []
await tool.execute({}, {})
assert.equal(calls[0][1].at(-1), '8')
calls = []
const literal = "valid'; Write-Output literal_only"
await tool.execute({ case: literal }, {})
assert.equal(calls[0][1].at(-1), literal)
assert.equal(calls[0][2].shell, undefined)
const count = calls.length
for (const input of [{limit: true}, {limit: 0}, {limit: 21}, {limit: 1.5},
                     {case: ''}, {case: 'x'.repeat(121)}, {case: 3}, {root: 'elsewhere'}]) {
  await assert.rejects(async () => tool.execute(input, {}))
}
assert.equal(calls.length, count, 'Invalid input must be rejected before subprocess execution')
for (const text of ['not JSON', '{}']) {
  globalThis.__failureLookupExec = () => text
  await assert.rejects(async () => tool.execute({}, {}))
}
globalThis.__failureLookupExec = () => { throw new Error('subprocess failed') }
await assert.rejects(async () => tool.execute({}, {}))
delete globalThis.__failureLookupExec
console.log('PASS: tool registration, argv isolation, input limits, and error propagation')
