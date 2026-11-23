use rusqlite::{params, Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, path::PathBuf};

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum TaskClass { Conversation, Build, Other }

impl TaskClass {
    pub fn classify(label: &str) -> Self {
        match label.trim().to_ascii_lowercase().as_str() {
            "conversation" => Self::Conversation,
            "build" => Self::Build,
            _ => Self::Other,
        }
    }
    pub fn destination(self) -> &'static str {
        match self { Self::Build => "drone", Self::Conversation | Self::Other => "queen" }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
struct Event { seq: i64, task: String, kind: String, lane: Option<String>, turn: Option<u32>, digest: String, previous: String, hash: String }

#[derive(Default)]
struct Lane { active_turn: Option<u32>, next_turn: u32, done: bool, last_digest: String, turns: u32 }
#[derive(Default)]
struct Task { opened: bool, stopped: bool, max_turns: u32, lanes: BTreeMap<String, Lane> }

pub struct Router { db_path: PathBuf }

impl Router {
    pub fn new(db_path: PathBuf) -> Self { Self { db_path } }
    fn connect(&self) -> Result<Connection, String> {
        if let Some(parent) = self.db_path.parent() { std::fs::create_dir_all(parent).map_err(|e| format!("state directory unavailable: {e}"))?; }
        let c = Connection::open(&self.db_path).map_err(|e| format!("state database unavailable: {e}"))?;
        c.busy_timeout(std::time::Duration::from_secs(5)).map_err(|e| e.to_string())?;
        c.execute_batch("PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;
          CREATE TABLE IF NOT EXISTS router_event(seq INTEGER PRIMARY KEY AUTOINCREMENT, task TEXT NOT NULL, kind TEXT NOT NULL, lane TEXT, turn INTEGER, digest TEXT NOT NULL, previous TEXT NOT NULL, hash TEXT NOT NULL UNIQUE);
          CREATE TRIGGER IF NOT EXISTS router_event_no_update BEFORE UPDATE ON router_event BEGIN SELECT RAISE(ABORT,'append-only event log'); END;
          CREATE TRIGGER IF NOT EXISTS router_event_no_delete BEFORE DELETE ON router_event BEGIN SELECT RAISE(ABORT,'append-only event log'); END;")
            .map_err(|e| format!("event log schema unavailable: {e}"))?;
        Ok(c)
    }
    fn events(c: &Connection) -> Result<Vec<Event>, String> {
        let mut q = c.prepare("SELECT seq,task,kind,lane,turn,digest,previous,hash FROM router_event ORDER BY seq")
            .map_err(|e| e.to_string())?;
        let rows = q.query_map([], |r| Ok(Event { seq:r.get(0)?, task:r.get(1)?, kind:r.get(2)?, lane:r.get(3)?, turn:r.get(4)?, digest:r.get(5)?, previous:r.get(6)?, hash:r.get(7)? })).map_err(|e| e.to_string())?;
        let mut out = Vec::new(); let mut prev = String::new();
        for row in rows { let e = row.map_err(|e| e.to_string())?;
            let body = format!("{}\n{}\n{}\n{}\n{}\n{}", e.seq, e.task, e.kind, e.lane.as_deref().unwrap_or(""), e.turn.map(|v|v.to_string()).unwrap_or_default(), e.digest);
            let expected = hex(&Sha256::digest(format!("{prev}\n{body}").as_bytes()));
            if e.previous != prev || e.hash != expected { return Err(format!("event chain integrity failure at sequence {}",e.seq)); }
            prev = e.hash.clone(); out.push(e);
        }
        Ok(out)
    }
    fn append(c: &mut Connection, task: &str, kind: &str, lane: Option<&str>, turn: Option<u32>, digest: &str) -> Result<(),String> {
        let tx = c.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate).map_err(|e| e.to_string())?;
        let last: Option<String> = tx.query_row("SELECT hash FROM router_event ORDER BY seq DESC LIMIT 1", [], |r|r.get(0)).optional().map_err(|e|e.to_string())?;
        let previous = last.unwrap_or_default(); let seq: i64 = tx.query_row("SELECT COALESCE(MAX(seq),0)+1 FROM router_event", [], |r|r.get(0)).map_err(|e|e.to_string())?;
        let body = format!("{}\n{}\n{}\n{}\n{}\n{}", seq, task, kind, lane.unwrap_or(""), turn.map(|v|v.to_string()).unwrap_or_default(), digest);
        let hash = hex(&Sha256::digest(format!("{previous}\n{body}").as_bytes()));
        tx.execute("INSERT INTO router_event(task,kind,lane,turn,digest,previous,hash) VALUES(?1,?2,?3,?4,?5,?6,?7)",params![task,kind,lane,turn,digest,previous,hash]).map_err(|e|format!("append denied: {e}"))?;
        tx.commit().map_err(|e|e.to_string())
    }
    fn state(events: &[Event]) -> Result<BTreeMap<String,Task>,String> {
        let mut tasks = BTreeMap::<String,Task>::new();
        for e in events { let t=tasks.entry(e.task.clone()).or_default(); match e.kind.as_str() {
            "open_build" => { if t.opened || e.digest.len()!=64 {return Err("invalid duplicate task open or assignment digest".into())} t.opened=true; t.max_turns=e.turn.unwrap_or(1); for id in e.lane.as_deref().unwrap_or("").split(',') { if id.is_empty() || t.lanes.insert(id.into(),Lane::default()).is_some(){return Err("invalid lane roster".into())} } },
            "turn_started" => { let l=t.lanes.get_mut(e.lane.as_deref().unwrap_or("")).ok_or("unknown lane in event log")?; if l.done||l.active_turn.is_some()||e.turn!=Some(l.next_turn)||l.turns>=t.max_turns{return Err("invalid turn sequence in event log".into())} l.active_turn=e.turn; l.last_digest=e.digest.clone(); },
            "turn_result" => { let l=t.lanes.get_mut(e.lane.as_deref().unwrap_or("")).ok_or("unknown lane in event log")?; if l.active_turn!=e.turn{return Err("unpaired turn result in event log".into())} l.active_turn=None;l.turns+=1;l.next_turn+=1;l.last_digest=e.digest.clone(); },
            "lane_done" => {let l=t.lanes.get_mut(e.lane.as_deref().unwrap_or("")).ok_or("unknown lane in event log")?;if l.active_turn.is_some(){return Err("lane closed during active turn".into())}l.done=true;l.last_digest=e.digest.clone();},
            "stop" => t.stopped=true,
            _ => return Err(format!("unknown event kind {}",e.kind)),
        }} Ok(tasks)
    }
    pub fn status(&self) -> Result<serde_json::Value,String> { let c=self.connect()?;let es=Self::events(&c)?;Ok(serde_json::json!({"candidate":"aios_router_mcp_v1","operational":false,"database":"available","event_count":es.len(),"event_chain":"verified","writes":"bounded task-state events only","filesystem_write_authority":false,"body_attestation":"not connected","service_started":false})) }
    pub fn classify(&self,label:&str)->serde_json::Value {let class=TaskClass::classify(label);serde_json::json!({"task_class":class,"destination_role":class.destination(),"dispatch":"classification_only"})}
    pub fn open_build(&self,id:&str,assignment:&str,lanes:&[String],max_turns:u32)->Result<serde_json::Value,String>{
        if !valid_id(id)||assignment.trim().is_empty()||assignment.len()>2000||lanes.is_empty()||lanes.len()>4||max_turns==0||max_turns>32{return Err("invalid task bounds; require ID, bounded assignment, 1-4 unique lanes, and 1-32 turns".into())}
        let mut unique=std::collections::BTreeSet::new();if lanes.iter().any(|x|!valid_id(x)||!unique.insert(x)){return Err("lane IDs must be valid and unique".into())}
        let mut c=self.connect()?;let es=Self::events(&c)?;let st=Self::state(&es)?;if st.contains_key(id){return Err("task ID already exists".into())}
        let d=hex(&Sha256::digest(assignment.trim().as_bytes()));Self::append(&mut c,id,"open_build",Some(&lanes.join(",")),Some(max_turns),&d)?;
        Ok(serde_json::json!({"task_id":id,"task_class":"build","destination_role":"drone","assignment_sha256":d,"lanes":lanes,"max_turns_per_lane":max_turns,"state":"open"}))
    }
    pub fn accept_prompt(&self,id:&str,lane:&str,turn:u32,prompt:&str)->Result<serde_json::Value,String>{self.with_task_lane(id,lane,|t,l|{if t.stopped||l.done||l.active_turn.is_some()||turn!=l.next_turn||l.turns>=t.max_turns{return Err("self-prompt rejected: lane must be idle, active task, next serial turn, and within turn bound".into())}Ok(())})?;let digest=hex(&Sha256::digest(prompt.trim().as_bytes()));let mut c=self.connect()?;Self::append(&mut c,id,"turn_started",Some(lane),Some(turn),&digest)?;Ok(serde_json::json!({"accepted":true,"task_id":id,"lane_id":lane,"turn":turn,"prompt_sha256":digest,"note":"acceptance records a bounded prompt receipt; it does not invoke a model"}))}
    pub fn record_result(&self,id:&str,lane:&str,turn:u32,result:&str)->Result<serde_json::Value,String>{self.with_task_lane(id,lane,|_t,l|if l.active_turn==Some(turn){Ok(())}else{Err("result rejected: no matching active turn".into())})?;let d=hex(&Sha256::digest(result.trim().as_bytes()));let mut c=self.connect()?;Self::append(&mut c,id,"turn_result",Some(lane),Some(turn),&d)?;Ok(serde_json::json!({"recorded":true,"result_sha256":d,"turn":turn}))}
    pub fn finish_lane(&self,id:&str,lane:&str,receipt:&str)->Result<serde_json::Value,String>{if receipt.trim().is_empty(){return Err("completion receipt required".into())}self.with_task_lane(id,lane,|t,l|if !t.stopped&&!l.done&&l.active_turn.is_none()&&l.turns>0{Ok(())}else{Err("lane cannot complete: no completed turn, active turn, already done, or task stopped".into())})?;let d=hex(&Sha256::digest(receipt.trim().as_bytes()));let mut c=self.connect()?;Self::append(&mut c,id,"lane_done",Some(lane),None,&d)?;Ok(serde_json::json!({"lane_completed":true,"receipt_sha256":d}))}
    pub fn stop(&self,id:&str,reason:&str)->Result<serde_json::Value,String>{if reason.trim().is_empty(){return Err("stop reason required".into())}let mut c=self.connect()?;let es=Self::events(&c)?;let st=Self::state(&es)?;if st.get(id).is_none_or(|t|!t.opened||t.stopped){return Err("unknown, unopened, or already stopped task".into())}let d=hex(&Sha256::digest(reason.trim().as_bytes()));Self::append(&mut c,id,"stop",None,None,&d)?;Ok(serde_json::json!({"stop_recorded":true,"task_id":id,"reason_sha256":d,"active_turns_must_be_resolved_by_external_cancellation":true}))}
    pub fn summary(&self,id:&str)->Result<serde_json::Value,String>{let c=self.connect()?;let es=Self::events(&c)?;let st=Self::state(&es)?;let t=st.get(id).ok_or("unknown task")?;let receipts:Vec<_>=es.iter().filter(|e|e.task==id).map(|e|serde_json::json!({"event":e.kind,"lane":e.lane,"turn":e.turn,"sha256":e.digest})).collect();Ok(serde_json::json!({"task_id":id,"task_class":"build","state":if t.stopped{"stopped"}else if t.lanes.values().all(|l|l.done){"completed"}else{"in_progress"},"lanes":t.lanes.iter().map(|(id,l)|serde_json::json!({"lane_id":id,"completed":l.done,"completed_turns":l.turns,"active_turn":l.active_turn})).collect::<Vec<_>>(),"event_receipts":receipts,"queen_summary":"Derived from append-only event receipts; no model-generated outcome claims."}))}
    fn with_task_lane<F>(&self,id:&str,lane:&str,f:F)->Result<(),String> where F:FnOnce(&Task,&Lane)->Result<(),String>{let c=self.connect()?;let es=Self::events(&c)?;let st=Self::state(&es)?;let t=st.get(id).ok_or("unknown task")?;let l=t.lanes.get(lane).ok_or("unknown lane")?;f(t,l)}
}
fn valid_id(s:&str)->bool{!s.is_empty()&&s.len()<=80&&s.bytes().all(|b|b.is_ascii_alphanumeric()||b"_-.:".contains(&b))}
fn hex(b:&[u8])->String{b.iter().map(|x|format!("{x:02x}")).collect()}

