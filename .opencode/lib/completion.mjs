import {execFileSync} from 'node:child_process'
import {existsSync,readFileSync} from 'node:fs'

export async function registerCompletion(ctx,execute=execFileSync){
  const activation='L:/LocalCoder/.opencode/completion.json'
  if(execute===execFileSync&&(!existsSync(activation)||JSON.parse(readFileSync(activation,'utf8')).enabled!==true))return
  await ctx.tool.hook('execute.before',event=>{
    if(!['aios_router_verify_task','aios_router_complete_lane'].includes(String(event.tool)))return
    const input=event.input??{}
    const binding={session_id:String(event.sessionID),task_id:input.task_id,assignment_hash:input.assignment_hash}
    if(typeof binding.task_id!=='string'||typeof binding.assignment_hash!=='string')throw new Error('Completion requires a trusted current task binding')
    let raw
    try{raw=execute('L:/.venv/Scripts/python.exe',['-B','L:/LocalCoder/workspace/autonomy/aios_router_mcp_v3_postal_candidate/completion_authority.py'],{
      cwd:'L:/LocalCoder',input:JSON.stringify({tool:String(event.tool),binding}),encoding:'utf8',timeout:180000,maxBuffer:2*1024*1024,windowsHide:true,
    })}catch(error){throw new Error('Rust verification execution failed: '+String(error.stdout??error.message))}
    if(!JSON.parse(raw).receipt_id)throw new Error('Rust verification produced no authority receipt')
  })
}
