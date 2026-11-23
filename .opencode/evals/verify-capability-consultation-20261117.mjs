import assert from 'node:assert/strict'
import { readFile, mkdir, writeFile } from 'node:fs/promises'
import { stripTypeScriptTypes } from 'node:module'
import { pathToFileURL } from 'node:url'
import { join } from 'node:path'

// Isolated hook fixtures: no model calls, Body requests, or live receipt writes.
const root = 'L:/LocalCoder'
const evidence = join(root, '.opencode/snapshots/capability-consultation-20261117T060616557Z')
const fixtureRoot = join(evidence, 'hook-fixture')
await mkdir(join(fixtureRoot, 'plugins'), { recursive: true })
await mkdir(join(fixtureRoot, 'receipts'), { recursive: true })
let source = await readFile(join(root, '.opencode/plugins/localcoder-drone-assignment-gate.ts'), 'utf8')
source = source.replace('import { Plugin } from "@opencode/plugin"', 'const Plugin = { define: (definition) => definition }')
source += '\nexport const fixtureSeedBindings = seedBindingsBySession\n'
const modulePath = join(fixtureRoot, 'plugins/assignment-gate.mjs')
await writeFile(modulePath, stripTypeScriptTypes(source, { mode: 'transform', sourceUrl: modulePath }))
const plugin = await import(pathToFileURL(modulePath).href)
const sessionHooks = new Map()
const toolHooks = new Map()
const record = (registry, name, fn) => {
  const hooks = registry.get(name) ?? []
  hooks.push(fn)
  registry.set(name, hooks)
}
const dispose = await plugin.default.setup({
  session: { hook: async (name, fn) => record(sessionHooks, name, fn) },
  tool: {
    hook: async (name, fn) => record(toolHooks, name, fn),
    transform: async (fn) => fn({ add: () => {} }),
  },
  event: { subscribe: async function* () {} },
})
const sid = 'fixture_capability_budget'
plugin.fixtureSeedBindings.set(sid, {
  agentID: 'localcoder-viv-drone-01', seed: 123,
  styleProfile: { detail_percent: 50, directness_percent: 50, playfulness_percent: 50, warmth_percent: 50 },
})
const names = ['read', 'glob', 'grep', 'shell', 'write', 'edit']
const context = async (id, text) => {
  const event = {
    sessionID: sid, agent: 'build', model: { providerID: 'lmstudio', id: 'fixture' },
    messages: [{ id, type: 'user', text }], system: [], options: {},
    tools: Object.fromEntries(names.map((name) => [name, { input: { type: 'object', properties: {} } }])),
  }
  for (const fn of sessionHooks.get('context') ?? []) await fn(event)
  return event
}
const before = async (tool, input) => {
  const event = { sessionID: sid, tool, input }
  for (const fn of toolHooks.get('execute.before') ?? []) await fn(event)
  return event
}
const prompt = 'Read-only diagnosis, at most three file inspections.'
assert.ok((await context('user1', prompt)).tools.read)
assert.equal((await before('read', { path: 'L:/LocalCoder/BUILD_LOG.md' })).input.limit, 80)
await before('glob', { pattern: '**/*composition*.py' })
assert.equal((await before('read', { path: 'L:/LocalCoder/AGENTS.md', limit: 12 })).input.limit, 12)
await assert.rejects(before('read', { path: 'L:/LocalCoder/AGENT.md' }), /3-inspection limit/)
assert.deepEqual(Object.keys((await context('user1', prompt)).tools), [])
assert.ok((await context('user2', prompt)).tools.read, 'A new user turn resets the budget even when text is identical')
assert.equal((await before('read', { path: 'L:/LocalCoder/AGENT.md' })).input.limit, 80)
await context('user2-again', prompt)
assert.equal((await before('read', { path: 'L:/LocalCoder/AGENT.md' })).input.limit, 80,
  'The same read in a newly assigned turn must not inherit the prior duplicate-call block')
const coding = await context('user3', 'Create a small TypeScript helper in the sandbox.')
assert.ok(coding.tools.edit && coding.tools.write && coding.tools.shell, 'Unbudgeted build access remains available')
await before('read', { path: 'L:/LocalCoder/README.md' })
await assert.rejects(before('read', { path: 'L:/LocalCoder/README.md' }), /Duplicate tool call blocked/)
await assert.rejects(before('read', { path: 'C:/forbidden.txt' }), /C: is permanently forbidden/)
dispose()
const result = {
  schema: 'localcoder_capability_hook_fixture_v1',
  result: 'passed',
  checked: ['default read limit 80', 'explicit limit preserved', 'fourth inspection denied',
    'tools removed after budget', 'new user message resets budget', 'new user message resets duplicate-read state',
    'build tools remain available', 'same-turn duplicate remains blocked', 'literal C drive denied'],
  scope: 'Synthetic isolated hook checks only; no model, Rust, learning, or OS-isolation proof',
}
await writeFile(join(evidence, 'hook-checks.json'), JSON.stringify(result, null, 2))
console.log(JSON.stringify(result))
