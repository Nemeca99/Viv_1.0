use chrono::{DateTime, Utc};
use rusqlite::{params, Connection, OpenFlags, OptionalExtension};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, path::PathBuf, time::Duration};

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum TaskClass { Conversation, Build, Other }
impl TaskClass {
    pub fn classify(label: &str) -> Self { match label.trim().to_ascii_lowercase().as_str() { "conversation"=>Self::Conversation,"build"=>Self::Build,_=>Self::Other } }
    pub fn destination(self)->&'static str { match self {Self::Build=>"drone",Self::Conversation|Self::Other=>"queen"} }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
struct Event { seq:i64, task:String, kind:String, lane:Option<String>, turn:Option<u32>, digest:String, previous:String, hash:String, session_id:String, assignment_hash:String, reason_code:String, receipt_id:String }
#[derive(Default)] struct Lane { active_turn:Option<u32>, next_turn:u32, done:bool, turns:u32 }
#[derive(Default)] struct Task { opened:bool, stopped:bool, max_turns:u32, session_id:String, assignment_hash:String, lanes:BTreeMap<String,Lane> }
struct Receipt { id:String }
pub struct Router { db_path:PathBuf, receipt_dir:PathBuf }

impl Router {
    pub fn new(db_path:PathBuf, receipt_dir:PathBuf)->Self { Self{db_path,receipt_dir} }
    fn writable(&self)->Result<Connection,String> {
        if let Some(p)=self.db_path.parent(){std::fs::create_dir_all(p).map_err(|e|format!("state directory unavailable: {e}"))?;}
        let c=Connection::open(&self.db_path).map_err(|e|format!("state database unavailable: {e}"))?;
        c.busy_timeout(Duration::from_secs(5)).map_err(|e|e.to_string())?;
        c.execute_batch("PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;
          CREATE TABLE IF NOT EXISTS router_event(seq INTEGER PRIMARY KEY AUTOINCREMENT, task TEXT NOT NULL, kind TEXT NOT NULL, lane TEXT, turn INTEGER, digest TEXT NOT NULL, previous TEXT NOT NULL, hash TEXT NOT NULL UNIQUE, session_id TEXT NOT NULL, assignment_hash TEXT NOT NULL, reason_code TEXT NOT NULL, receipt_id TEXT NOT NULL UNIQUE);
          CREATE TRIGGER IF NOT EXISTS router_event_no_update BEFORE UPDATE ON router_event BEGIN SELECT RAISE(ABORT,'append-only event log'); END;
          CREATE TRIGGER IF NOT EXISTS router_event_no_delete BEFORE DELETE ON router_event BEGIN SELECT RAISE(ABORT,'append-only event log'); END;")
            .map_err(|e|format!("event log schema unavailable: {e}"))?;
        Ok(c)
    }
    fn readonly(&self)->Result<Connection,String> {
        if !self.db_path.is_file(){return Err("router database does not exist; read-only operation did not create it".into())}
        let c=Connection::open_with_flags(&self.db_path,OpenFlags::SQLITE_OPEN_READ_ONLY).map_err(|e|format!("read-only database unavailable: {e}"))?;
        c.busy_timeout(Duration::from_secs(5)).map_err(|e|e.to_string())?;
        Ok(c)
    }
    fn events(c:&Connection)->Result<Vec<Event>,String>{
        let mut q=c.prepare("SELECT seq,task,kind,lane,turn,digest,previous,hash,session_id,assignment_hash,reason_code,receipt_id FROM router_event ORDER BY seq").map_err(|e|e.to_string())?;
        let rows=q.query_map([],|r|Ok(Event{seq:r.get(0)?,task:r.get(1)?,kind:r.get(2)?,lane:r.get(3)?,turn:r.get(4)?,digest:r.get(5)?,previous:r.get(6)?,hash:r.get(7)?,session_id:r.get(8)?,assignment_hash:r.get(9)?,reason_code:r.get(10)?,receipt_id:r.get(11)?})).map_err(|e|e.to_string())?;
        let mut out=Vec::new();let mut prev=String::new();
        for row in rows {let e=row.map_err(|e|e.to_string())?;let body=event_body(&e);let expected=hex(&Sha256::digest(format!("{prev}\n{body}").as_bytes()));if e.previous!=prev||e.hash!=expected{return Err(format!("event chain integrity failure at sequence {}",e.seq))}prev=e.hash.clone();out.push(e)}Ok(out)
    }
    fn append(c:&mut Connection,task:&str,kind:&str,lane:Option<&str>,turn:Option<u32>,digest:&str,session:&str,assignment_hash:&str,reason_code:&str,receipt_id:&str)->Result<(),String>{
        let tx=c.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate).map_err(|e|e.to_string())?;
        let previous:Option<String>=tx.query_row("SELECT hash FROM router_event ORDER BY seq DESC LIMIT 1",[],|r|r.get(0)).optional().map_err(|e|e.to_string())?.unwrap_or_default();
        let seq:i64=tx.query_row("SELECT COALESCE(MAX(seq),0)+1 FROM router_event",[],|r|r.get(0)).map_err(|e|e.to_string())?;
        let mut e=Event{seq,task:task.into(),kind:kind.into(),lane:lane.map(str::to_owned),turn,digest:digest.into(),previous:previous.clone(),hash:String::new(),session_id:session.into(),assignment_hash:assignment_hash.into(),reason_code:reason_code.into(),receipt_id:receipt_id.into()};
        e.hash=hex(&Sha256::digest(format!("{previous}\n{}",event_body(&e)).as_bytes()));
        tx.execute("INSERT INTO router_event(task,kind,lane,turn,digest,previous,hash,session_id,assignment_hash,reason_code,receipt_id) VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11)",params![e.task,e.kind,e.lane,e.turn,e.digest,e.previous,e.hash,e.session_id,e.assignment_hash,e.reason_code,e.receipt_id]).map_err(|e|format!("append denied: {e}"))?;tx.commit().map_err(|e|e.to_string())
    }
    fn state(events:&[Event])->Result<BTreeMap<String,Task>,String>{
        let mut tasks=BTreeMap::<String,Task>::new();
        for e in events {
            if e.kind=="denial" { continue; }
            let t=tasks.entry(e.task.clone()).or_default();
            if e.kind=="open_build" {if t.opened||!valid_hash(&e.assignment_hash)||e.digest!=e.assignment_hash{return Err("invalid duplicate task open or assignment binding".into())}t.opened=true;t.session_id=e.session_id.clone();t.assignment_hash=e.assignment_hash.clone();t.max_turns=e.turn.unwrap_or(0);for id in e.lane.as_deref().unwrap_or("").split(','){if id.is_empty()||t.lanes.insert(id.into(),Lane::default()).is_some(){return Err("invalid lane roster".into())}}continue}
            if !t.opened||t.session_id!=e.session_id||t.assignment_hash!=e.assignment_hash{return Err("task/session/assignment binding mismatch in event log".into())}
            match e.kind.as_str(){
                "turn_started"=>{let l=t.lanes.get_mut(e.lane.as_deref().unwrap_or("")).ok_or("unknown lane in event log")?;if l.done||l.active_turn.is_some()||e.turn!=Some(l.next_turn)||l.turns>=t.max_turns{return Err("invalid turn sequence in event log".into())}l.active_turn=e.turn;},
                "turn_result"=>{let l=t.lanes.get_mut(e.lane.as_deref().unwrap_or("")).ok_or("unknown lane in event log")?;if l.active_turn!=e.turn{return Err("unpaired turn result in event log".into())}l.active_turn=None;l.turns+=1;l.next_turn+=1;},
                "lane_done"=>{let l=t.lanes.get_mut(e.lane.as_deref().unwrap_or("")).ok_or("unknown lane in event log")?;if l.active_turn.is_some(){return Err("lane closed during active turn".into())}l.done=true;},
                "stop"=>t.stopped=true,
                _=>return Err(format!("unknown event kind {}",e.kind)),
            }
        }Ok(tasks)
    }
    fn receipt(&self,source:&str,session:&str)->Result<Receipt,String>{
        if session.is_empty()||session.len()>160{return Err("invalid session_id".into())}
        let entries=std::fs::read_dir(&self.receipt_dir).map_err(|_|"Body receipt directory unavailable")?;
        let now=Utc::now();let mut best:Option<(DateTime<Utc>,String)>=None;
        for entry in entries {let entry=entry.map_err(|_|"Body receipt directory unreadable")?;let path=entry.path();if !path.file_name().and_then(|x|x.to_str()).is_some_and(|n|n.ends_with("-body-gate.json")){continue}
            let md=entry.metadata().map_err(|_|"Body receipt metadata unavailable")?;if !md.is_file()||md.len()>16*1024{continue}
            let bytes=std::fs::read(&path).map_err(|_|"Body receipt unreadable")?;let Ok(v)=serde_json::from_slice::<serde_json::Value>(&bytes) else {continue};
            if v.get("schema").and_then(|x|x.as_str())!=Some("opencode_body_gate_receipt_v1")||v.get("source").and_then(|x|x.as_str())!=Some(source)||v.get("session_id").and_then(|x|x.as_str())!=Some(session)||v.get("allowed").and_then(|x|x.as_bool())!=Some(true)||v.get("disposition").and_then(|x|x.as_str())!=Some("ALLOW_MIND_RUNTIME")||v.get("authority").and_then(|x|x.as_str())!=Some("deterministic_aios_body_rust"){continue}
            let Some(ts)=v.get("captured_at").and_then(|x|x.as_str()).and_then(|s|DateTime::parse_from_rfc3339(s).ok()).map(|d|d.with_timezone(&Utc)) else {continue};
            let age=now.signed_duration_since(ts);if age.num_milliseconds()<0||age.num_seconds()>=15{continue}
            let id=path.file_name().and_then(|x|x.to_str()).unwrap_or_default().to_owned();if best.as_ref().is_none_or(|(old,_)|ts>*old){best=Some((ts,id))}
        }
        best.map(|(_,id)|Receipt{id}).ok_or_else(||format!("no fresh Body ALLOW receipt for {source} and this session"))
    }
    fn guarded<T,F>(&self,source:&str,session:&str,task:&str,assignment_hash:&str,attempt_hash:&str,op:F)->Result<T,String> where F:FnOnce(&str)->Result<T,String>{
        let r=self.receipt(source,session)?;
        let bounded_task=if valid_id(task){task.to_owned()}else{format!("invalid:{}",hex(&Sha256::digest(task.as_bytes())))};
        let bounded_assignment=if valid_hash(assignment_hash){assignment_hash.to_ascii_lowercase()}else{format!("invalid:{}",hex(&Sha256::digest(assignment_hash.as_bytes())))};
        let mut c=self.writable()?;let es=Self::events(&c)?;
        if es.iter().any(|e|e.receipt_id==r.id){return Err("Body receipt already consumed".into())}
        match op(&r.id){Ok(v)=>Ok(v),Err(e)=>{let code=reason_code(&e);let evidence=hex(&Sha256::digest(format!("{code}\n{attempt_hash}\n{bounded_task}\n{bounded_assignment}").as_bytes()));Self::append(&mut c,&bounded_task,"denial",None,None,&evidence,session,&bounded_assignment,code,&r.id).map_err(|log|format!("{e}; denial receipt could not be persisted: {log}"))?;Err(e)}}
    }
    pub fn status(&self)->Result<serde_json::Value,String>{let c=self.readonly()?;let es=Self::events(&c)?;Ok(serde_json::json!({"candidate":"aios_router_mcp_v1","operational":false,"database":"available","event_count":es.len(),"event_chain":"verified","event_memory":"router_and_negative_evidence_only","positive_rag":"separate_drone_owned_database","filesystem_write_authority":false,"body_attestation":"fresh_opencode_receipt_required_for_mutations","service_started":false}))}
    pub fn classify(&self,label:&str)->serde_json::Value{let c=TaskClass::classify(label);serde_json::json!({"task_class":c,"destination_role":c.destination(),"dispatch":"classification_only"})}
    pub fn open_build(&self,session:&str,id:&str,assignment_hash:&str,assignment:&str,lanes:&[String],max:u32)->Result<serde_json::Value,String>{let ah=hex(&Sha256::digest(assignment.trim().as_bytes()));let attempt=hex(&Sha256::digest(serde_json::to_vec(&(session,id,assignment_hash,ah,lanes,max)).unwrap_or_default()));self.guarded("tool:aios_router_open_build_task",session,id,assignment_hash,&attempt,|rid|{if !valid_id(id)||assignment.trim().is_empty()||assignment.len()>2000||!valid_hash(assignment_hash)||assignment_hash!=ah||lanes.is_empty()||lanes.len()>4||max==0||max>32{return Err("invalid_task_binding_or_bounds".into())}let mut u=std::collections::BTreeSet::new();if lanes.iter().any(|x|!valid_id(x)||!u.insert(x)){return Err("invalid_lane_roster".into())}let es=Self::events(&self.writable()?)?;let st=Self::state(&es)?;if st.contains_key(id){return Err("duplicate_task_id".into())}let mut c=self.writable()?;Self::append(&mut c,id,"open_build",Some(&lanes.join(",")),Some(max),assignment_hash,session,assignment_hash,"",rid)?;Ok(serde_json::json!({"task_id":id,"task_class":"build","destination_role":"drone","assignment_sha256":assignment_hash,"lanes":lanes,"max_turns_per_lane":max,"state":"open"}))})}
    pub fn accept_prompt(&self,session:&str,id:&str,ah:&str,lane:&str,turn:u32,prompt:&str)->Result<serde_json::Value,String>{let d=hex(&Sha256::digest(prompt.trim().as_bytes()));self.turn_mutation("tool:aios_router_accept_self_prompt",session,id,ah,lane,turn,&d,"turn_started",|t,l|if t.stopped||l.done||l.active_turn.is_some()||turn!=l.next_turn||l.turns>=t.max_turns{Err("invalid_turn_state".into())}else{Ok(())})}
    pub fn record_result(&self,session:&str,id:&str,ah:&str,lane:&str,turn:u32,result:&str)->Result<serde_json::Value,String>{let d=hex(&Sha256::digest(result.trim().as_bytes()));self.turn_mutation("tool:aios_router_record_turn_result",session,id,ah,lane,turn,&d,"turn_result",|_t,l|if l.active_turn==Some(turn){Ok(())}else{Err("no_matching_active_turn".into())})}
    fn turn_mutation<F>(&self,source:&str,session:&str,id:&str,ah:&str,lane:&str,turn:u32,digest:&str,kind:&str,check:F)->Result<serde_json::Value,String>where F:FnOnce(&Task,&Lane)->Result<(),String>{let attempt=hex(&Sha256::digest(format!("{session}\n{id}\n{ah}\n{lane}\n{turn}\n{digest}").as_bytes()));self.guarded(source,session,id,ah,&attempt,|rid|{if !valid_id(id)||!valid_hash(ah)||!valid_id(lane){return Err("invalid_task_binding_or_lane".into())}let c=self.readonly()?;let es=Self::events(&c)?;let st=Self::state(&es)?;let t=st.get(id).ok_or("unknown_task")?;if t.session_id!=session||t.assignment_hash!=ah{return Err("task_binding_mismatch".into())}let l=t.lanes.get(lane).ok_or("unknown_lane")?;check(t,l)?;let mut c=self.writable()?;Self::append(&mut c,id,kind,Some(lane),Some(turn),digest,session,ah,"",rid)?;Ok(serde_json::json!({"recorded":true,"task_id":id,"lane_id":lane,"turn":turn,"sha256":digest}))})}
    pub fn finish_lane(&self,session:&str,id:&str,ah:&str,lane:&str,receipt:&str)->Result<serde_json::Value,String>{let d=hex(&Sha256::digest(receipt.trim().as_bytes()));let attempt=hex(&Sha256::digest(format!("{session}\n{id}\n{ah}\n{lane}\n{d}").as_bytes()));self.guarded("tool:aios_router_complete_lane",session,id,ah,&attempt,|rid|{if !valid_id(id)||!valid_id(lane)||!valid_hash(ah)||receipt.trim().is_empty(){return Err("invalid_completion_request".into())}let c=self.readonly()?;let es=Self::events(&c)?;let st=Self::state(&es)?;let t=st.get(id).ok_or("unknown_task")?;if t.session_id!=session||t.assignment_hash!=ah{return Err("task_binding_mismatch".into())}let l=t.lanes.get(lane).ok_or("unknown_lane")?;if t.stopped||l.done||l.active_turn.is_some()||l.turns==0{return Err("lane_not_completable".into())}let mut c=self.writable()?;Self::append(&mut c,id,"lane_done",Some(lane),None,&d,session,ah,"",rid)?;Ok(serde_json::json!({"lane_completed":true,"receipt_sha256":d}))})}
    pub fn stop(&self,session:&str,id:&str,ah:&str,reason:&str)->Result<serde_json::Value,String>{let d=hex(&Sha256::digest(reason.trim().as_bytes()));let attempt=hex(&Sha256::digest(format!("{session}\n{id}\n{ah}\n{d}").as_bytes()));self.guarded("tool:aios_router_stop_task",session,id,ah,&attempt,|rid|{if !valid_id(id)||!valid_hash(ah)||reason.trim().is_empty(){return Err("invalid_stop_request".into())}let c=self.readonly()?;let es=Self::events(&c)?;let st=Self::state(&es)?;let t=st.get(id).ok_or("unknown_task")?;if t.session_id!=session||t.assignment_hash!=ah{return Err("task_binding_mismatch".into())}if t.stopped{return Err("task_already_stopped".into())}let mut c=self.writable()?;Self::append(&mut c,id,"stop",None,None,&d,session,ah,"",rid)?;Ok(serde_json::json!({"stop_recorded":true,"task_id":id,"reason_sha256":d}))})}
    pub fn summary(&self,id:&str)->Result<serde_json::Value,String>{let c=self.readonly()?;let es=Self::events(&c)?;let st=Self::state(&es)?;let t=st.get(id).ok_or("unknown task")?;let receipts:Vec<_>=es.iter().filter(|e|e.task==id).map(|e|serde_json::json!({"event":e.kind,"lane":e.lane,"turn":e.turn,"sha256":e.digest,"reason_code":if e.reason_code.is_empty(){serde_json::Value::Null}else{serde_json::json!(e.reason_code)}})).collect();Ok(serde_json::json!({"task_id":id,"task_class":"build","state":if t.stopped{"stopped"}else if t.lanes.values().all(|l|l.done){"completed"}else{"in_progress"},"lanes":t.lanes.iter().map(|(id,l)|serde_json::json!({"lane_id":id,"completed":l.done,"completed_turns":l.turns,"active_turn":l.active_turn})).collect::<Vec<_>>(),"event_receipts":receipts,"queen_summary":"Derived from router events only; turn outputs are not accepted knowledge and no model-authored outcome claims are made."}))}
}

fn event_body(e:&Event)->String{format!("{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}",e.seq,e.task,e.kind,e.lane.as_deref().unwrap_or(""),e.turn.map(|x|x.to_string()).unwrap_or_default(),e.digest,e.session_id,e.assignment_hash,e.reason_code,e.receipt_id,e.previous)}
fn reason_code(e:&str)->&'static str{match e{"invalid_task_binding_or_bounds"|"invalid_lane_roster"|"invalid_task_binding_or_lane"|"invalid_completion_request"|"invalid_stop_request"=>"invalid_arguments","duplicate_task_id"=>"duplicate_task","invalid_turn_state"|"no_matching_active_turn"|"lane_not_completable"|"task_already_stopped"=>"invalid_state","task_binding_mismatch"=>"binding_mismatch","unknown_task"|"unknown_lane"=>"unknown_reference",_=>"router_rejected"}}
fn valid_id(s:&str)->bool{!s.is_empty()&&s.len()<=160&&s.bytes().all(|b|b.is_ascii_alphanumeric()||b"_-.:".contains(&b))}
fn valid_hash(s:&str)->bool{s.len()==64&&s.bytes().all(|b|b.is_ascii_hexdigit())}
fn hex(b:&[u8])->String{b.iter().map(|x|format!("{x:02x}")).collect()}
