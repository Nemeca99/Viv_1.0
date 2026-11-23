import assert from 'node:assert/strict'
import {registerCompletion} from '../lib/completion.mjs'
let hook,request,calls=0
await registerCompletion({tool:{hook:async(name,fn)=>{assert.equal(name,'execute.before');hook=fn}}},(exe,args,options)=>{
  calls++;request=JSON.parse(options.input);return JSON.stringify({receipt_id:'unit-test-only-receipt'})
})
await hook({tool:'read',sessionID:'actual',input:{}})
assert.equal(calls,0)
await hook({tool:'aios_router_verify_task',sessionID:'actual',input:{session_id:'forged',task_id:'bound-task',assignment_hash:'bound-hash',verification:{verified:true}}})
assert.equal(request.binding.session_id,'actual')
assert.equal(request.binding.task_id,'bound-task')
assert.equal(request.verification,undefined)
assert.equal(request.binding.verification,undefined)
assert.throws(()=>hook({tool:'aios_router_complete_lane',sessionID:'actual',input:{}}),/trusted current task/)
console.log('PASS: exact completion tools, actual session binding, no model-supplied verdict, no unbound execution')
