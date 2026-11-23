import assert from 'node:assert/strict'
import {architectAssignment,currentTaskSource} from '../lib/task-binding.mjs'
const header='[ARCHITECT ASSIGNMENT | CURRENT AND AUTHORIZED]\n'
const task='Task access: write\nAcceptance JSON: {"version":1,"kind":"control_plane"}\nUse aios_router_open_build_task.'
assert.equal(architectAssignment(header+task),task)
assert.equal(architectAssignment(header+task+'\n[CURRENT AUTHORIZATION FACT]\nRuntime note'),task)
assert.equal(architectAssignment('Transcript quotes '+header+task),undefined)
assert.equal(architectAssignment('[LOCALCODER PRIVATE DRONE CONTINUATION | v1]\n'+task),undefined)
assert.equal(architectAssignment(header+'x'.repeat(16385)),undefined)
assert.equal(currentTaskSource([{role:'user',content:header+task},{role:'user',content:'[LOCALCODER PRIVATE DRONE CONTINUATION | v1]\nCall the next tool.'}]).assignment,task)
assert.equal(currentTaskSource([{role:'user',content:header+task},{role:'user',content:'Stop that task.'}]).assignment,undefined)
assert.equal(currentTaskSource([{role:'assistant',content:header+task}]).seen,false)
console.log('PASS: actual Architect header, optional runtime marker, no quoted/continuation authority, bounded source')
