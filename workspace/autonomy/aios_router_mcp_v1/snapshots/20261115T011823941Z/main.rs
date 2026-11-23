use rmcp::{handler::server::wrapper::Parameters, schemars::{self, JsonSchema}, tool, tool_handler, tool_router, transport::stdio, ServerHandler, ServiceExt};
use serde::Deserialize;
use std::{path::PathBuf, process::Command};

use aios_router_mcp_v1_candidate::Router;

#[derive(Debug, Deserialize, JsonSchema)] struct Label { #[schemars(description="User-originated label; conversation routes Queen, build routes Drone, every other label routes Queen.")] label:String }
#[derive(Debug, Deserialize, JsonSchema)] struct Open { task_id:String, assignment:String, lane_ids:Vec<String>, max_turns_per_lane:u32 }
#[derive(Debug, Deserialize, JsonSchema)] struct Prompt { task_id:String, lane_id:String, turn:u32, prompt:String }
#[derive(Debug, Deserialize, JsonSchema)] struct ResultArgs { task_id:String, lane_id:String, turn:u32, result:String }
#[derive(Debug, Deserialize, JsonSchema)] struct Finish { task_id:String, lane_id:String, receipt:String }
#[derive(Debug, Deserialize, JsonSchema)] struct Stop { task_id:String, reason:String }
#[derive(Debug, Deserialize, JsonSchema)] struct Summary { task_id:String }

#[derive(Clone)] struct Mcp { router: std::sync::Arc<Router> }

#[tool_router]
impl Mcp {
    #[tool(description="Report candidate health, append-only event-chain status, and explicit missing security integrations.")]
    fn router_status(&self)->String { encode(self.router.status()) }
    #[tool(description="Classify only: conversation routes to Queen, build to Drone, all other labels to Queen. This does not dispatch work.")]
    fn classify_task(&self,Parameters(a):Parameters<Label>)->String { serde_json::to_string(&self.router.classify(&a.label)).unwrap_or_else(|e|err(e)) }
    #[tool(description="Open a bounded build task in candidate state. Requires the trusted OpenCode bridge to bind this request to a current Architect assignment; this standalone candidate cannot authenticate that binding.")]
    fn open_build_task(&self,Parameters(a):Parameters<Open>)->String { encode(authorize_mutation().and_then(|_| self.router.open_build(&a.task_id,&a.assignment,&a.lane_ids,a.max_turns_per_lane))) }
    #[tool(description="Accept one bounded self-prompt for the next serial lane turn; records only a digest, never invokes the model.")]
    fn accept_self_prompt(&self,Parameters(a):Parameters<Prompt>)->String { encode(authorize_mutation().and_then(|_| self.router.accept_prompt(&a.task_id,&a.lane_id,a.turn,&a.prompt))) }
    #[tool(description="Record the digest receipt for the matching active lane turn.")]
    fn record_turn_result(&self,Parameters(a):Parameters<ResultArgs>)->String { encode(authorize_mutation().and_then(|_| self.router.record_result(&a.task_id,&a.lane_id,a.turn,&a.result))) }
    #[tool(description="Mark an idle lane complete after at least one turn, with a nonempty completion receipt.")]
    fn complete_lane(&self,Parameters(a):Parameters<Finish>)->String { encode(authorize_mutation().and_then(|_| self.router.finish_lane(&a.task_id,&a.lane_id,&a.receipt))) }
    #[tool(description="Record a task stop request. This cannot cancel an external model generation; bridge cancellation and acknowledgement are not connected.")]
    fn stop_task(&self,Parameters(a):Parameters<Stop>)->String { encode(authorize_mutation().and_then(|_| self.router.stop(&a.task_id,&a.reason))) }
    #[tool(description="Return a Queen-facing summary derived strictly from recorded event receipts.")]
    fn queen_summary(&self,Parameters(a):Parameters<Summary>)->String { encode(self.router.summary(&a.task_id)) }
}

#[tool_handler(name="aios-router-mcp-v1-candidate",version="0.1.0",instructions="Candidate router state machine only. No model invocation, task dispatch, filesystem mutation authority, actor authentication, or Body attestation.")]
impl ServerHandler for Mcp {}

fn err(e:impl std::fmt::Display)->String{serde_json::json!({"ok":false,"error":e.to_string()}).to_string()}
fn encode<T:serde::Serialize>(r:Result<T,String>)->String{match r{Ok(v)=>serde_json::json!({"ok":true,"result":v}).to_string(),Err(e)=>err(e)}}

/// Ask the existing Rust Body gate immediately before every MCP state mutation.
/// The executable and working directory are fixed; no request data reaches the process.
fn authorize_mutation() -> Result<(), String> {
    const PYTHON: &str = r"L:\.venv\Scripts\python.exe";
    const WORKSPACE: &str = r"L:\LocalCoder\workspace";
    let output = Command::new(PYTHON)
        .args(["-m", "aios_rebuild.main_core.mind_runtime_gate"])
        .current_dir(WORKSPACE)
        .output()
        .map_err(|e| format!("Body gate could not be started: {e}"))?;
    if !output.status.success() {
        return Err(format!("Body gate exited unsuccessfully ({})", output.status));
    }
    let verdict: serde_json::Value = serde_json::from_slice(&output.stdout)
        .map_err(|e| format!("Body gate returned invalid JSON: {e}"))?;
    let valid_allow = verdict.get("schema").and_then(|v| v.as_str()) == Some("aios_mind_runtime_gate_v1")
        && verdict.get("gate").and_then(|v| v.as_str()) == Some("rust")
        && verdict.get("execution_boundary").and_then(|v| v.as_str()) == Some("wsl_docker")
        && verdict.get("allowed").and_then(|v| v.as_bool()) == Some(true)
        && verdict.get("disposition").and_then(|v| v.as_str()) == Some("ALLOW_MIND_RUNTIME")
        && verdict.get("authority").and_then(|v| v.as_str()) == Some("deterministic_aios_body_rust");
    if !valid_allow {
        return Err("Body gate did not return a valid ALLOW_MIND_RUNTIME verdict from deterministic_aios_body_rust".into());
    }
    Ok(())
}

#[tokio::main]
async fn main()->Result<(),Box<dyn std::error::Error>>{
    let base=PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let db=std::env::var_os("AIOS_ROUTER_DB").map(PathBuf::from).unwrap_or_else(||base.join("state/router.sqlite3"));
    let server=Mcp{router:std::sync::Arc::new(Router::new(db))}.serve(stdio()).await?;
    server.waiting().await?;
    Ok(())
}
