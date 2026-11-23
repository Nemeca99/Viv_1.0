import assert from 'node:assert/strict'
import {registerContinuity,previousTurns,observableMessages} from '../lib/continuity.mjs'
const hooks=new Map(),calls=[],checkpoints=new Map()
let generations=0
const memory=(op,args)=>{
  calls.push({op,args})
  if(op==='checkpoint_read')return {checkpoint:checkpoints.get(args.compaction_id)??null}
  if(op==='checkpoint'){
    const stm=args.summary+'\n'+args.previous_assistant+'\n'+args.previous_user
    const cp={summary:args.summary,stm,sha256:'verified-hash',receipt_id:'verified-receipt'}
    checkpoints.set(args.compaction_id,cp);return cp
  }
  if(op==='stm')return {checkpoint:null}
  if(op==='working')return {sha256:'working-hash'}
  if(op==='retrieve')return {order:['ltm'],result:{source:'ltm',matches:[]}}
  throw new Error('unexpected '+op)
}
const ctx={session:{hook:async(name,callback)=>hooks.set(name,callback)},tool:{hook:async()=>{}},experimental:{generate:{text:async()=>{generations++;return {text:'Actual summary from stubbed generator'}}}}}
await registerContinuity(ctx,memory)
const messages=[{type:'user',text:'Continue this exact task'},{type:'assistant',text:'Already fixed error ABC; test passed'}]
assert(previousTurns(messages).previous_assistant.includes(messages[1].text))
assert(previousTurns([{type:'assistant',content:[{type:'tool-call',name:'read',input:{path:'verified.rs'}}]}]).previous_assistant.includes('verified.rs'))
const cleaned=observableMessages([{type:'assistant',reasoning:'PRIVATE_SENTINEL',parts:[{type:'reasoning',text:'PRIVATE_SENTINEL'},{type:'text',text:'Observable tool outcome'}]}])
assert(!JSON.stringify(cleaned).includes('PRIVATE_SENTINEL'))
assert(JSON.stringify(cleaned).includes('Observable tool outcome'))
const event={sessionID:'hook-test',model:{providerID:'lmstudio',id:'local'},messages,system:[]}
await hooks.get('compaction')(event)
assert(event.result.summary.includes(messages[0].text))
assert(event.result.summary.includes(messages[1].text))
assert.equal(event.result.metadata.continuity_receipt,'verified-receipt')
const retry={...event,result:undefined}
await hooks.get('compaction')(retry)
assert.equal(generations,1)
assert.equal(retry.result.summary,event.result.summary)
await hooks.get('context')(event)
assert(calls.some(c=>c.op==='working'&&c.args.content.includes('Already fixed error ABC')))
assert(calls.some(c=>c.op==='retrieve'&&c.args.query==='Continue this exact task'))
assert(event.system[0].text.includes('unverified operational history'))
const rejectedHooks=new Map()
await registerContinuity({...ctx,session:{hook:async(name,callback)=>rejectedHooks.set(name,callback)}},(op)=>{
  if(op==='checkpoint_read')return {checkpoint:null}
  if(op==='checkpoint')throw new Error('Body denied test checkpoint')
  throw new Error('unexpected operation')
})
const rejected={sessionID:'denied-test',model:event.model,messages:structuredClone(messages),system:[]}
await assert.rejects(rejectedHooks.get('compaction')(rejected),/Body denied/)
assert.equal(rejected.result,undefined)
assert.deepEqual(rejected.messages,messages)
console.log('PASS: hook wiring, exact previous turns, committed compaction, idempotent retry, current STM, ordered retrieval')
