// Execute the original Apps Script computation functions without Sheets services.
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'FarmScript.txt'), 'utf8');
const core = source.slice(source.indexOf('const FARM8'), source.indexOf('/* Spreadsheet integration:'));
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const context = vm.createContext({input});
vm.runInContext(core, context);
if(input.mode==='reset') {
  for(const [start,end] of [['function replay8(', 'function beginBatch8('],
    ['function beginBatch8(', 'function writeProjection8('],
    ['function commit8(', 'function load8('],['function hardResetFarm(', 'function repairStateFrontier(']])
    vm.runInContext(source.slice(source.indexOf(start),source.indexOf(end)),context);
  vm.runInContext(`
    var saved=input.state, history=input.rows.slice(), emitted=[], initialLast=input.state.logNext-1;
    var stopTraining=()=>{}, LockService={getDocumentLock:()=>({tryLock:()=>true,releaseLock:()=>{}})};
    var io8=()=>({farm:{getRange:()=>({clearContent:()=>{}})},logs:{
      getLastRow:()=>initialLast+emitted.length,
      getRange:(first,col,count)=>({getValues:()=>history.slice(-count)})}});
    var prepareLogs8=()=>{},readCheckpoint8=()=>saved,writeProjection8=()=>{};
    var checkpoint8=(io,c)=>{saved=c;history.push(...c.batch);emitted.push(...c.batch);};
    var config8=()=>input.state.config,newId8=()=>'reset-proof';Date.now=()=>input.seed;
    hardResetFarm();
  `,context);
  process.stdout.write(vm.runInContext('JSON.stringify({state:saved,rows:emitted})',context));
  process.exit(0);
}
if(input.mode==='replay') {
  vm.runInContext(source.slice(source.indexOf('function replay8('),source.indexOf('function beginBatch8(')),context);
  const result=vm.runInContext(`(() => {
    const c=fresh8(input.config,'replay',input.seed);
    const io={logs:{getLastRow:()=>100+input.rows.length,
      getRange:(first,col,count)=>({getValues:()=>input.rows.slice(first-101,first-101+count)})}};
    replay8(io,c);
    return JSON.stringify({w:c.w,validity:c.validity,loss:c.loss,updates:c.updates,replayed:c.replayed});
  })()`,context);
  process.stdout.write(result);
  process.exit(0);
}
const result = vm.runInContext(`(() => {
  const c=input.state || fresh8(input.config,'parity',input.seed);
  const trace=[],logs=[];
  for(let i=0;i<input.steps;i++) {
    const rows=step8(c);
    if(input.capture)logs.push(...rows);
    if(i%25===0)trace.push({r:clone8(c.r),events:rows.filter(r=>!['ACTION','TRANSITION'].includes(r[22]))});
  }
  return JSON.stringify({r:c.r,p:c.p,w:c.w,validity:c.validity,loss:c.loss,updates:c.updates,trace,logs});
})()`, context);
process.stdout.write(result);
