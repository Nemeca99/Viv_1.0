import assert from 'node:assert/strict'
import { runtimeHeader, runtimeSystem } from '../lib/runtime-context.mjs'

const header = '<viv_runtime_context>Deployment label: Example. Runtime: OpenCode.</viv_runtime_context>'
const source = { type: 'text', text: 'You are OpenCode, an interactive CLI tool.\nKeep permission checks intact.', metadata: { source: 'builtin' } }
const result = runtimeSystem([source], header)
assert.equal(result[0].text, 'OpenCode is the host runtime and tool transport.\nKeep permission checks intact.')
assert.deepEqual(result[0].metadata, source.metadata)
assert.equal(result.filter(part => part.text.includes('<viv_runtime_context>')).length, 1)
assert.deepEqual(runtimeSystem(result, header), result)
const generic = runtimeSystem([{ type: 'text', text: 'You are an AI agent running in OpenCode, a coding agent harness.\nUse the current tools.' }], header)
assert.equal(generic[0].text, 'OpenCode is the host runtime and tool transport.\nUse the current tools.')
const history = { type: 'text', text: 'Instructions from: notes.md\nHistorical quote: You are OpenCode.' }
assert.equal(runtimeSystem([history], header)[0], history)
const quoted = { type: 'text', text: 'Historical note: ' + header }
assert.equal(runtimeSystem([quoted], header).length, 2)
const updated = '<viv_runtime_context>Updated runtime facts.</viv_runtime_context>'
assert.equal(runtimeSystem([{ type: 'text', text: header + '\nKeep permission checks.' }], updated)[0].text,
  updated + '\nKeep permission checks.')
const custom = { type: 'text', text: 'You are the project operator. Consult the manifests for model provenance.' }
assert.equal(runtimeSystem([custom], header)[0], custom)
assert.equal(runtimeHeader(header + '\n\nWork instructions.'), header)
assert.throws(() => runtimeHeader('no header'), /missing/)
console.log('PASS: runtime/name separation, preserved permissions and provenance, historical text unchanged, idempotent header')
