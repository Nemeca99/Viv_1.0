import assert from 'node:assert/strict'
import { readFile, mkdir, writeFile } from 'node:fs/promises'
import { stripTypeScriptTypes } from 'node:module'
import { pathToFileURL } from 'node:url'
import { join } from 'node:path'
import { createHash } from 'node:crypto'

const root = 'L:/LocalCoder'
const evidence = join(root, '.opencode/snapshots/normal-conversation-20261117')
const fixture = join(evidence, 'fixture')
await mkdir(join(fixture, 'plugins'), { recursive: true })
await mkdir(join(fixture, 'receipts'), { recursive: true })
const compileFixture = async (name, extra = '') => {
  let source = await readFile(join(root, '.opencode/plugins', name + '.ts'), 'utf8')
  source = source.replace('import { Plugin } from "@opencode/plugin"', 'const Plugin = { define: (value) => value }')
  source = source.replaceAll('L:\\\\LocalCoder', fixture.replaceAll('\\', '/'))
  const path = join(fixture, 'plugins', name + '.mjs')
  await writeFile(path, stripTypeScriptTypes(source + extra, { mode: 'transform', sourceUrl: path }))
  return import(pathToFileURL(path).href)
}
const plugin = await compileFixture('localcoder-drone-assignment-gate', '\nexport const testState = { states, seedBindingsBySession }\n')
const hooks = new Map()
const beforeHooks = []
const afterHooks = []
const toolsAdded = []
const prompts = []
const backlog = []
let wake
const emit = (event) => new Promise((done) => { backlog.push({ event, done }); wake?.(); wake = undefined })
const ctx = {
  session: {
    hook: async (name, fn) => { const list = hooks.get(name) ?? []; list.push(fn); hooks.set(name, list) },
    context: async () => [{ id: 'assistant-final', type: 'assistant', content: [{ type: 'text', text: 'Done.' }] }],
    prompt: async (input) => { prompts.push(input) },
  },
  tool: {
    hook: async (name, fn) => (name === 'execute.before' ? beforeHooks : afterHooks).push(fn),
    transform: async (fn) => fn({ add: (tool) => toolsAdded.push(tool.name) }),
  },
  event: { subscribe: async function* ({ signal }) {
    while (!signal.aborted) {
      if (!backlog.length) await new Promise((resolve) => { wake = resolve })
      const job = backlog.shift()
      if (!job) return
      yield job.event
      job.done()
    }
  } },
}
const dispose = await plugin.default.setup(ctx)
assert.ok(!toolsAdded.includes('localcoder_drone_self_prompt'))
const definition = (properties = {}) => ({ input: { type: 'object', properties } })
const text = '[ARCHITECT ASSIGNMENT | CURRENT AND AUTHORIZED]\n'
  + 'Use aios_router_lookup_drone_seed tool.\nUse read on `L:/LocalCoder/AGENT.md`.\n'
  + 'Use shell with exactly `Write-Output NORMAL_LOOP_OK`.\n[CURRENT AUTHORIZATION FACT]\nFixture only.'
const context = async (sid, prompt = text) => {
  const event = { sessionID: sid, agent: 'build', kind: 'primary', options: {},
    model: { providerID: 'lmstudio', id: 'fixture' },
    messages: [{ id: sid + '-' + createHash('sha256').update(prompt).digest('hex'), type: 'user', text: prompt }], system: [],
    tools: { aios_router_lookup_drone_seed: definition({ agent_id: { type: 'string' } }),
      read: definition({ path: { type: 'string' }, limit: { type: 'integer' } }),
      shell: definition({ command: { type: 'string' } }) } }
  for (const fn of hooks.get('context') ?? []) await fn(event)
  assert.ok(!/\[DRONE SELF-PROMPT\]|Agenda:|Verified facts:|Next bounded action:/.test(JSON.stringify(event.system)))
  return event
}
const action = async (sid, tool, input, result) => {
  const event = { sessionID: sid, tool, input }
  for (const fn of beforeHooks) await fn(event)
  for (const fn of afterHooks) await fn({ ...event, status: 'completed', result })
}
const binding = { ok: true, result: { agent_id: 'localcoder-viv-drone-01', seed: 123,
  style_profile: { warmth_percent: 50, directness_percent: 50, playfulness_percent: 50, detail_percent: 50 } } }
const seed = async (sid) => {
  assert.deepEqual(Object.keys((await context(sid)).tools), ['aios_router_lookup_drone_seed'])
  await action(sid, 'aios_router_lookup_drone_seed', { agent_id: binding.result.agent_id }, JSON.stringify(binding))
}
const sid = 'fixture_normal_chain'
await context(sid, 'Read-only, at most 0 file inspections.')
await seed(sid)
assert.deepEqual(Object.keys((await context(sid)).tools), ['read'])
await action(sid, 'read', { path: 'L:/LocalCoder/AGENT.md' }, 'Actual source text')
assert.deepEqual(Object.keys((await context(sid)).tools), ['shell'])
await action(sid, 'shell', { command: 'Write-Output NORMAL_LOOP_OK' }, { metadata: { exit: 0 }, output: 'NORMAL_LOOP_OK' })
assert.deepEqual(Object.keys((await context(sid)).tools), [])
await emit({ type: 'session.execution.succeeded', data: { sessionID: sid } })
await emit({ type: 'session.execution.succeeded', data: { sessionID: sid } })
assert.equal(prompts.length, 0, 'A plain final reply never triggers report-format retries')
assert.equal(plugin.testState.states.get(sid).failed, false)
const early = 'fixture_early_finish'
await seed(early)
await emit({ type: 'session.execution.succeeded', data: { sessionID: early } })
assert.equal(prompts.length, 1, 'Incomplete assigned actions retain one bounded continuation')
assert.match(prompts[0].text, /Call the read tool/)
assert.ok(!/SELF-PROMPT|Agenda:|Verified facts:/.test(prompts[0].text))
assert.deepEqual(Object.keys((await context(early, prompts[0].text)).tools), ['read'])
await emit({ type: 'session.execution.succeeded', data: { sessionID: early } })
assert.equal(prompts.length, 1)
assert.equal(plugin.testState.states.get(early).failed, true, 'No progress does not create an endless loop')
dispose()
wake?.()

// Exercise the bridge's real request/tool hooks across consecutive exposed tools.
delete process.env.LOCALCODER_TRACE_LLM
const bridge = await compileFixture('lmstudio-toolbridge')
const bridgeHooks = new Map()
const bridgeBefore = []
const bridgeAfter = []
await bridge.default.setup({
  session: { hook: async (name, fn) => { const list = bridgeHooks.get(name) ?? []; list.push(fn); bridgeHooks.set(name, list) } },
  tool: { transform: async (fn) => fn({ add: () => {} }),
    hook: async (name, fn) => (name === 'execute.before' ? bridgeBefore : bridgeAfter).push(fn) },
})
await writeFile(join(fixture, 'input.txt'), 'fixture source\n')
for (const [name, input] of [['read', { path: join(fixture, 'input.txt') }], ['shell', { command: 'Write-Output NORMAL_LOOP_OK' }]]) {
  const event = { sessionID: 'fixture_bridge_chain', kind: 'primary',
    request: new Request('http://127.0.0.1:1234/v1/chat/completions', { method: 'POST', body: JSON.stringify({
      messages: [{ role: 'user', content: text }], tools: [{ type: 'function', function: { name, parameters: { type: 'object', properties: {} } } }],
    }) }) }
  for (const fn of bridgeHooks.get('http.request') ?? []) await fn(event)
  const toolEvent = { sessionID: event.sessionID, tool: name, input }
  for (const fn of bridgeBefore) await fn(toolEvent)
  for (const fn of bridgeAfter) await fn({ ...toolEvent, status: 'completed', result: { output: 'fixture', metadata: { exit: 0 } } })
}
const result = { result: 'passed', checks: [
  'retired tool absent', 'prior inspection budget cleared for a new assignment',
  'seed → read → shell without checkpoint tools', 'plain final response accepted without retries',
  'incomplete work receives one concise continuation', 'no-progress continuation stops', 'bridge advances exposed-tool sequence'],
  scope: 'Isolated plugin/bridge hook fixtures; no live model or Rust execution' }
await writeFile(join(evidence, 'hook-checks.json'), JSON.stringify(result, null, 2))
console.log(JSON.stringify(result))
