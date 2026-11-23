use rmcp::{handler::server::wrapper::Parameters, schemars::{self, JsonSchema}, tool, tool_handler, tool_router, transport::stdio, ServerHandler, ServiceExt};
use serde::Deserialize;
use std::path::PathBuf;

use aios_router_mcp_v1_candidate::Router;

#[derive(Debug, Deserialize, JsonSchema)] struct Label { #[schemars(description="User-originated label; conversation routes Queen, build routes Drone, every other label routes Queen.")] label:String }
#[derive(Debug, Deserialize, JsonSchema)] struct Open { session_id:String, task_id:String, assignment_hash:String, assignment:String, lane_ids:Vec<String>, max_turns_per_lane:u32 }
#[derive(Debug, Deserialize, JsonSchema)] struct Prompt { session_id:String, task_id:String, assignment_hash:String, lane_id:String, turn:u32, prompt:String }
#[derive(Debug, Deserialize, JsonSchema)] struct ResultArgs { session_id:String, task_id:String, assignment_hash:String, lane_id:String, turn:u32, result:String }
#[derive(Debug, Deserialize, JsonSchema)] struct Finish { session_id:String, task_id:String, assignment_hash:String, lane_id:String, receipt:String }
#[derive(Debug, Deserialize, JsonSchema)] struct Stop { session_id:String, task_id:String, assignment_hash:String, reason:String }
#[derive(Debug, Deserialize, JsonSchema)] struct Summary { task_id:String }

#[derive(Clone)] struct Mcp { router: std::sync::Arc<Router> }

#[tool_router]
impl Mcp {
    #[tool(description="Report candidate health, append-only event-chain status, and explicit missing security integrations.")]
    fn router_status(&self)->String { encode(self.router.status()) }
    #[tool(description="Classify only: conversation routes to Queen, build to Drone, all other labels to Queen. This does not dispatch work.")]
    fn classify_task(&self,Parameters(a):Parameters<Label>)->String { serde_json::to_string(&self.router.classify(&a.label)).unwrap_or_else(|e|err(e)) }
    #[tool(description="Open a bounded router task. Requires session_id, task_id and SHA-256 assignment_hash matching the supplied assignment plus a fresh OpenCode Body receipt.")]
    fn open_build_task(&self,Parameters(a):Parameters<Open>)->String { encode(self.router.open_build(&a.session_id,&a.task_id,&a.assignment_hash,&a.assignment,&a.lane_ids,a.max_turns_per_lane)) }
    #[tool(description="Accept one bounded self-prompt for the next serial lane turn; records only a digest, never invokes the model.")]
    fn accept_self_prompt(&self,Parameters(a):Parameters<Prompt>)->String { encode(self.router.accept_prompt(&a.session_id,&a.task_id,&a.assignment_hash,&a.lane_id,a.turn,&a.prompt)) }
    #[tool(description="Record the digest receipt for the matching active lane turn.")]
    fn record_turn_result(&self,Parameters(a):Parameters<ResultArgs>)->String { encode(self.router.record_result(&a.session_id,&a.task_id,&a.assignment_hash,&a.lane_id,a.turn,&a.result)) }
    #[tool(description="Mark an idle lane complete after at least one turn, with a nonempty completion receipt.")]
    fn complete_lane(&self,Parameters(a):Parameters<Finish>)->String { encode(self.router.finish_lane(&a.session_id,&a.task_id,&a.assignment_hash,&a.lane_id,&a.receipt)) }
    #[tool(description="Record a task stop request. This cannot cancel an external model generation; bridge cancellation and acknowledgement are not connected.")]
    fn stop_task(&self,Parameters(a):Parameters<Stop>)->String { encode(self.router.stop(&a.session_id,&a.task_id,&a.assignment_hash,&a.reason)) }
    #[tool(description="Return a Queen-facing summary derived strictly from recorded event receipts.")]
    fn queen_summary(&self,Parameters(a):Parameters<Summary>)->String { encode(self.router.summary(&a.task_id)) }
}

#[tool_handler(name="aios-router-mcp-v1-candidate",version="0.1.0",instructions="Digest-only router and negative-evidence event log. Every mutation requires a fresh matching OpenCode Body receipt. Positive Drone knowledge remains in its separate RAG database.")]
impl ServerHandler for Mcp {}

fn err(e:impl std::fmt::Display)->String{serde_json::json!({"ok":false,"error":e.to_string()}).to_string()}
fn encode<T:serde::Serialize>(r:Result<T,String>)->String{match r{Ok(v)=>serde_json::json!({"ok":true,"result":v}).to_string(),Err(e)=>err(e)}}

#[tokio::main]
async fn main()->Result<(),Box<dyn std::error::Error>>{
    const DB: &str = "/var/lib/aios-router/router.sqlite3";
    const RECEIPTS: &str = "/var/lib/aios-body-receipts";
    let db=std::env::var("AIOS_ROUTER_DB").unwrap_or_else(|_|DB.into());
    let receipts=std::env::var("AIOS_BODY_RECEIPTS_DIR").unwrap_or_else(|_|RECEIPTS.into());
    if db!=DB||receipts!=RECEIPTS{return Err("router database and receipt paths are fixed container mounts".into())}
    let server=Mcp{router:std::sync::Arc::new(Router::new(PathBuf::from(db),PathBuf::from(receipts)))}.serve(stdio()).await?;
    server.waiting().await?;
    Ok(())
}
