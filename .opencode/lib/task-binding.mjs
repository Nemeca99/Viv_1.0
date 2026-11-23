const MARKER='[ARCHITECT ASSIGNMENT | CURRENT AND AUTHORIZED]'
const FACT='[CURRENT AUTHORIZATION FACT]'
export function architectAssignment(prompt){
  if(typeof prompt!=='string'||!prompt.startsWith(MARKER+'\n')&&!prompt.startsWith(MARKER+'\r\n'))return undefined
  const body=prompt.slice(MARKER.length).trimStart()
  const end=body.indexOf(FACT)
  const assignment=(end<0?body:body.slice(0,end)).trim()
  return assignment&&Buffer.byteLength(assignment,'utf8')<=16384?assignment:undefined
}
export function currentTaskSource(messages){
  let latest
  for(const message of messages){
    const role=message?.info?.role??message?.info?.type??message?.role??message?.type
    if(role!=='user')continue
    const parts=message?.parts??message?.content??[]
    const text=message?.info?.text??message?.text??(typeof message?.content==='string'?message.content:Array.isArray(parts)?parts.filter(p=>p.type==='text').map(p=>p.text??'').join('\n'):'')
    if(text.trimStart().startsWith('[LOCALCODER PRIVATE DRONE CONTINUATION | v1]'))continue
    latest=text
  }
  return latest===undefined?{seen:false}:{seen:true,prompt:latest,assignment:architectAssignment(latest)}
}
