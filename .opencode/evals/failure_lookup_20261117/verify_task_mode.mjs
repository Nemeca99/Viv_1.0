import assert from 'node:assert/strict'
import { readFile, writeFile } from 'node:fs/promises'
import { stripTypeScriptTypes } from 'node:module'
import { pathToFileURL } from 'node:url'

const root = 'L:/LocalCoder'
const marker = '[ARCHITECT ASSIGNMENT | CURRENT AND AUTHORIZED]\n'
const history = 'The old patch made no changes. The checker is read-only.\nUse localcoder_patch tool.'
const cases = [
  [marker + 'Task access: write\n' + history, false],
  [marker + 'Task access: read\nUse localcoder_patch tool.', true],
  [marker + '[LOCALCODER REQUIRED SEED PREFLIGHT]\nUse the aios_router_lookup_drone_seed tool.\nTask access: write\n' + history, false],
  ['Read-only diagnosis; no changes.', true],
  [marker + 'Read-only diagnosis.', true],
  ['Repair the candidate function.', false],
  ['Explain this text: Task access: write. Read-only diagnosis.', true],
]
for (const name of ['localcoder-drone-assignment-gate', 'lmstudio-toolbridge']) {
  let source = await readFile(`${root}/.opencode/plugins/${name}.ts`, 'utf8')
  source = source.replace('import { Plugin } from "@opencode/plugin"', 'const Plugin = { define: value => value }')
  source += '\nexport { explicitlyReadOnly }\n'
  const path = `${root}/.opencode/evals/failure_lookup_20261117/${name}.mode-fixture.mjs`
  await writeFile(path, stripTypeScriptTypes(source, { mode: 'transform', sourceUrl: path }))
  const module = await import(pathToFileURL(path).href)
  for (const [prompt, expected] of cases) assert.equal(module.explicitlyReadOnly(prompt), expected, `${name}: ${prompt}`)
}
console.log('PASS: 14 task-mode cases; ordinary read-only instructions remain enforced')
