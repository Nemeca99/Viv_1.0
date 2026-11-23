import assert from 'node:assert/strict';
import {readFile, writeFile, mkdir} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import {resolve} from 'node:path';

const dir = resolve('.opencode/evals/read-gate-tests', String(Date.now()));
await mkdir(dir, {recursive:true});
const source = (await readFile('.opencode/plugins/lmstudio-toolbridge.ts', 'utf8'))
  .replace('import { Plugin } from "@opencode/plugin"', 'const Plugin = { define: (x: any) => x }');
await writeFile(resolve(dir, 'plugin.ts'), source);
const plugin = (await import(pathToFileURL(resolve(dir, 'plugin.ts')).href)).default;
const hooks = new Map();
await plugin.setup({
  session: {hook: async () => {}},
  tool: {transform: async () => {}, hook: async (name, fn) => hooks.set(name, fn)},
});
const target = resolve(dir, 'fixture.py');
await writeFile(target, 'value = 1\n');
const edit = {sessionID:'read-gate-test-'+Date.now(), tool:'edit', input:{path:target,oldString:'value = 1',newString:'value = 2'}};
await assert.rejects(hooks.get('execute.before')(edit), /Read .* before editing/);
await hooks.get('execute.after')({...edit,tool:'read',status:'error'});
await assert.rejects(hooks.get('execute.before')(edit), /Read .* before editing/);
await hooks.get('execute.after')({...edit,tool:'read',status:'completed'});
await hooks.get('execute.before')(edit);
await hooks.get('execute.after')({...edit,status:'completed'});
await assert.rejects(hooks.get('execute.before')({...edit,sessionID:'other-session'}), /Read .* before editing/);
await writeFile(target, 'value = 3\n');
await assert.rejects(hooks.get('execute.before')(edit), /Read .* before editing/);
console.log('PASS: unread, failed read, other session, and changed file blocked; completed current read admitted. Evidence: '+dir);
