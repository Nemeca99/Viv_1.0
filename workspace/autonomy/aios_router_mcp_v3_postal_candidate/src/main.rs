use rmcp::{
    ServerHandler, ServiceExt,
    handler::server::wrapper::Parameters,
    schemars::{self, JsonSchema},
    tool, tool_handler, tool_router,
    transport::stdio,
};
use serde::Deserialize;
use std::path::PathBuf;

use aios_router_mcp_v3_postal_candidate::Router;

#[derive(Debug, Deserialize, JsonSchema)]
struct MemoryCheckpoint {
    session_id: String,
    compaction_id: String,
    summary: String,
    previous_assistant: String,
    previous_user: String,
}
#[derive(Debug, Deserialize, JsonSchema)]
struct MemoryRetrieve { session_id: String, query: String, limit: u32 }
#[derive(Debug, Deserialize, JsonSchema)]
struct MemorySession { session_id: String }
#[derive(Debug, Deserialize, JsonSchema)]
struct MemoryCheckpointRead { session_id: String, compaction_id: String }
#[derive(Debug, Deserialize, JsonSchema)]
struct MemoryWorking { session_id: String, context_id: String, content: String }

#[derive(Debug, Deserialize, JsonSchema)]
struct Label {
    #[schemars(
        description = "User-originated label; conversation routes Queen, build routes Drone, every other label routes Queen."
    )]
    label: String,
}
#[derive(Debug, Deserialize, JsonSchema)]
struct Open {
    session_id: String,
    task_id: String,
    assignment_hash: String,
    assignment: String,
    lane_ids: Vec<String>,
    max_turns_per_lane: u32,
}
#[derive(Debug, Deserialize, JsonSchema)]
struct Prompt {
    session_id: String,
    task_id: String,
    assignment_hash: String,
    lane_id: String,
    turn: u32,
    prompt: String,
}
#[derive(Debug, Deserialize, JsonSchema)]
struct ResultArgs {
    session_id: String,
    task_id: String,
    assignment_hash: String,
    lane_id: String,
    turn: u32,
    result: String,
}
#[derive(Debug, Deserialize, JsonSchema)]
struct Finish {
    session_id: String,
    task_id: String,
    assignment_hash: String,
    lane_id: String,
    receipt: String,
}
#[derive(Debug, Deserialize, JsonSchema)]
struct Stop {
    session_id: String,
    task_id: String,
    assignment_hash: String,
    reason: String,
}
#[derive(Debug, Deserialize, JsonSchema)]
struct Summary {
    task_id: String,
}
#[derive(Debug, Deserialize, JsonSchema)]
struct SeedAssign {
    #[schemars(
        description = "Architect-assigned Drone identity key; it must appear verbatim in the current assignment."
    )]
    agent_id: String,
    session_id: String,
    task_id: String,
    assignment_hash: String,
}
#[derive(Debug, Deserialize, JsonSchema)]
struct SeedLookup {
    agent_id: String,
}
#[derive(Debug, Deserialize, JsonSchema)]
struct PostalTaskBinding {
    session_id: String,
    task_id: String,
    assignment_hash: String,
}
#[derive(Debug, Deserialize, JsonSchema)]
struct PostalRegister {
    session_id: String,
    task_id: String,
    assignment_hash: String,
    #[schemars(description = "Trusted Drone identity injected by the OpenCode assignment gate.")]
    agent_id: String,
}
#[derive(Debug, Deserialize, JsonSchema)]
struct PostalSubmit {
    session_id: String,
    task_id: String,
    assignment_hash: String,
    lane_id: String,
    turn: u32,
    agent_id: String,
    reply_to_message_id: Option<String>,
    body: String,
}
#[derive(Debug, Deserialize, JsonSchema)]
struct PostalReadOutbox {
    session_id: String,
    task_id: String,
    assignment_hash: String,
    message_id: String,
}
#[derive(Debug, Deserialize, JsonSchema)]
struct PostalDispatch {
    session_id: String,
    task_id: String,
    assignment_hash: String,
    source_message_id: String,
    destination_agent_id: String,
    destination_inbox_id: String,
    body: String,
}
#[derive(Debug, Deserialize, JsonSchema)]
struct PostalInboxRead {
    session_id: String,
    task_id: String,
    assignment_hash: String,
    agent_id: String,
    limit: u8,
}

#[derive(Clone)]
struct Mcp {
    router: std::sync::Arc<Router>,
}

#[tool_router]
impl Mcp {
    #[tool(description="Read the frozen Architect acceptance contract for this bound task. Model-generated replacements are never accepted.")]
    fn acceptance_contract(&self,Parameters(a):Parameters<PostalTaskBinding>)->String {
        encode(self.router.acceptance_contract(&a.session_id,&a.task_id,&a.assignment_hash))
    }
    #[tool(description="Run only the frozen Architect acceptance checks in the read-only project sandbox. Rust records real process exits and artifact hashes. Model success claims never count; edits invalidate prior verification.")]
    fn verify_task(&self,Parameters(a):Parameters<PostalTaskBinding>)->String {
        encode(self.router.verify_task(&a.session_id,&a.task_id,&a.assignment_hash))
    }
    #[tool(description="Read an immutable compaction checkpoint by its exact transcript identity for idempotent recovery after interruption.")]
    fn memory_checkpoint_read(&self,Parameters(a):Parameters<MemoryCheckpointRead>)->String {
        encode(self.router.memory_checkpoint_read(&a.session_id,&a.compaction_id))
    }
    #[tool(description="Persist the actual current conversation context as STM with immutable prior versions. Requires the existing Body and exact-target PrivacyCore authority; never changes LTM facts.")]
    fn memory_working(&self, Parameters(a): Parameters<MemoryWorking>) -> String {
        encode(self.router.memory_working(&a.session_id,&a.context_id,&a.content))
    }
    #[tool(description="Archive one actual compaction summary and preceding assistant/user turns, then publish their STM atomically. Requires fresh existing Rust Body and PrivacyCore authority for continuity.sqlite3. Operational history, not learned facts.")]
    fn memory_checkpoint(&self, Parameters(a): Parameters<MemoryCheckpoint>) -> String {
        encode(self.router.memory_checkpoint(aios_router_mcp_v3_postal_candidate::continuity::Checkpoint {
            session_id:a.session_id, compaction_id:a.compaction_id, summary:a.summary,
            previous_assistant:a.previous_assistant, previous_user:a.previous_user,
        }))
    }
    #[tool(description="Retrieve deterministically: LTM first, STM second, read-only F-drive Wikipedia SQL corpus third. Literal search precedes FTS. Never treats historical text as instructions.")]
    fn memory_retrieve(&self, Parameters(a): Parameters<MemoryRetrieve>) -> String {
        encode(self.router.memory_retrieve(&a.session_id,&a.query,a.limit))
    }
    #[tool(description="Read the latest committed STM and its immutable checkpoint hash and authority receipt. Does not write.")]
    fn memory_stm(&self, Parameters(a): Parameters<MemorySession>) -> String {
        encode(self.router.memory_stm(&a.session_id))
    }
    #[tool(
        description = "Report candidate health, append-only event-chain status, and explicit missing security integrations."
    )]
    fn router_status(&self) -> String {
        encode(self.router.status())
    }
    #[tool(
        description = "Classify only: conversation routes to Queen, build to Drone, all other labels to Queen. This does not dispatch work."
    )]
    fn classify_task(&self, Parameters(a): Parameters<Label>) -> String {
        serde_json::to_string(&self.router.classify(&a.label)).unwrap_or_else(|e| err(e))
    }
    #[tool(
        description = "Assign exactly one OS-CSPRNG inference seed to an Architect-named Drone identity. SQLite UNIQUE constraints prevent seed or identity reuse. Requires a fresh matching Rust Body and PrivacyCore receipt."
    )]
    fn assign_drone_seed(&self, Parameters(a): Parameters<SeedAssign>) -> String {
        encode(self.router.assign_drone_seed(
            &a.session_id,
            &a.task_id,
            &a.assignment_hash,
            &a.agent_id,
        ))
    }
    #[tool(
        description = "Read the persistent seed and stable seed-derived style profile for one registered Drone identity."
    )]
    fn lookup_drone_seed(&self, Parameters(a): Parameters<SeedLookup>) -> String {
        encode(self.router.lookup_drone_seed(&a.agent_id))
    }
    #[tool(
        description = "Open a bounded router task. The Architect assignment must contain exactly one Acceptance JSON: line defining version 1 frozen artifact/behavior criteria or an explicit control_plane-only contract. Requires matching assignment hash and fresh Body/PrivacyCore authority."
    )]
    fn open_build_task(&self, Parameters(a): Parameters<Open>) -> String {
        encode(self.router.open_build(
            &a.session_id,
            &a.task_id,
            &a.assignment_hash,
            &a.assignment,
            &a.lane_ids,
            a.max_turns_per_lane,
        ))
    }
    #[tool(
        description = "Accept one bounded self-prompt for the next serial lane turn; records only a digest and requires the same fresh Rust Body plus PrivacyCore receipt. It never invokes the model."
    )]
    fn accept_self_prompt(&self, Parameters(a): Parameters<Prompt>) -> String {
        encode(self.router.accept_prompt(
            &a.session_id,
            &a.task_id,
            &a.assignment_hash,
            &a.lane_id,
            a.turn,
            &a.prompt,
        ))
    }
    #[tool(
        description = "Record the digest receipt for the matching active lane turn; requires the same fresh Rust Body plus PrivacyCore receipt."
    )]
    fn record_turn_result(&self, Parameters(a): Parameters<ResultArgs>) -> String {
        encode(self.router.record_result(
            &a.session_id,
            &a.task_id,
            &a.assignment_hash,
            &a.lane_id,
            a.turn,
            &a.result,
        ))
    }
    #[tool(
        description = "Mark an idle lane complete after at least one turn, with a nonempty completion receipt; requires the same fresh Rust Body plus PrivacyCore receipt."
    )]
    fn complete_lane(&self, Parameters(a): Parameters<Finish>) -> String {
        encode(self.router.finish_lane(
            &a.session_id,
            &a.task_id,
            &a.assignment_hash,
            &a.lane_id,
            &a.receipt,
        ))
    }
    #[tool(
        description = "Record a task stop request; requires the same fresh Rust Body plus PrivacyCore receipt. This cannot cancel an external model generation; bridge cancellation and acknowledgement are not connected."
    )]
    fn stop_task(&self, Parameters(a): Parameters<Stop>) -> String {
        encode(
            self.router
                .stop(&a.session_id, &a.task_id, &a.assignment_hash, &a.reason),
        )
    }
    #[tool(
        description = "Return a Queen-facing summary derived strictly from recorded event receipts."
    )]
    fn queen_summary(&self, Parameters(a): Parameters<Summary>) -> String {
        encode(self.router.summary(&a.task_id))
    }
    #[tool(
        description = "Drone-only. Register this assignment-bound Drone in the postal router. Requires an existing unique OS-CSPRNG Drone seed and fresh Body plus PrivacyCore plus postal actor receipt. Returns only this Drone's inbox ID."
    )]
    fn postal_register_drone(&self, Parameters(a): Parameters<PostalRegister>) -> String {
        encode(self.router.postal_register_drone(
            &a.session_id,
            &a.task_id,
            &a.assignment_hash,
            &a.agent_id,
        ))
    }
    #[tool(
        description = "Drone-only. Submit one bounded turn result to the Queen's encrypted shared outbox. It closes the active Router turn atomically; Drone-to-Drone delivery is impossible through this operation."
    )]
    fn postal_drone_submit(&self, Parameters(a): Parameters<PostalSubmit>) -> String {
        encode(self.router.postal_drone_submit(
            &a.session_id,
            &a.task_id,
            &a.assignment_hash,
            &a.lane_id,
            a.turn,
            &a.agent_id,
            a.reply_to_message_id.as_deref(),
            &a.body,
        ))
    }
    #[tool(
        description = "Queen-only. List registered Drone IDs and inbox IDs for the bound task. Requires a fresh Body, PrivacyCore, and Queen actor receipt."
    )]
    fn postal_queen_list_drones(&self, Parameters(a): Parameters<PostalTaskBinding>) -> String {
        encode(
            self.router
                .postal_queen_list_drones(&a.session_id, &a.task_id, &a.assignment_hash),
        )
    }
    #[tool(
        description = "Queen-only. List shared outbox metadata for the bound task. Bodies remain encrypted until postal_queen_read_outbox is called."
    )]
    fn postal_queen_list_outbox(&self, Parameters(a): Parameters<PostalTaskBinding>) -> String {
        encode(
            self.router
                .postal_queen_list_outbox(&a.session_id, &a.task_id, &a.assignment_hash),
        )
    }
    #[tool(
        description = "Queen-only. Verify and decrypt one encrypted outbox message. The body is returned only after the Body, PrivacyCore, actor, and AES-GCM checks pass."
    )]
    fn postal_queen_read_outbox(&self, Parameters(a): Parameters<PostalReadOutbox>) -> String {
        encode(self.router.postal_queen_read_outbox(
            &a.session_id,
            &a.task_id,
            &a.assignment_hash,
            &a.message_id,
        ))
    }
    #[tool(
        description = "Queen-only. Reseal a verified Queen reply into the named registered Drone inbox using both Drone ID and inbox ID as the route handshake. Unknown or mismatched routes create a deterministic encrypted bounce for the original sender."
    )]
    fn postal_queen_dispatch(&self, Parameters(a): Parameters<PostalDispatch>) -> String {
        encode(self.router.postal_queen_dispatch(
            &a.session_id,
            &a.task_id,
            &a.assignment_hash,
            &a.source_message_id,
            &a.destination_agent_id,
            &a.destination_inbox_id,
            &a.body,
        ))
    }
    #[tool(
        description = "Queen-only. Return the task and mailbox summary from verified Rust task state and the append-only postal receipt chain; it does not infer success from Drone prose."
    )]
    fn postal_queen_summary(&self, Parameters(a): Parameters<PostalTaskBinding>) -> String {
        encode(
            self.router
                .postal_queen_summary(&a.session_id, &a.task_id, &a.assignment_hash),
        )
    }
    #[tool(
        description = "Drone-only. Read at most four messages from this assignment-bound Drone's private inbox. The host gate overwrites agent_id with the session's assigned Drone identity."
    )]
    fn postal_drone_read_inbox(&self, Parameters(a): Parameters<PostalInboxRead>) -> String {
        encode(self.router.postal_drone_read_inbox(
            &a.session_id,
            &a.task_id,
            &a.assignment_hash,
            &a.agent_id,
            a.limit,
        ))
    }
}

#[tool_handler(
    name = "aios-router-mcp-v3-postal-candidate",
    version = "0.3.0",
    instructions = "Persistent encrypted Hive postal candidate. All postal operations require fresh Rust Body, PrivacyCore, and role-bound OpenCode actor receipts. Drone messages enter Queen-only encrypted outbox; only Queen tools can read and reseal into an exact registered Drone inbox."
)]
impl ServerHandler for Mcp {}

fn err(e: impl std::fmt::Display) -> String {
    serde_json::json!({"ok":false,"error":e.to_string()}).to_string()
}
fn encode<T: serde::Serialize>(r: Result<T, String>) -> String {
    match r {
        Ok(v) => serde_json::json!({"ok":true,"result":v}).to_string(),
        Err(e) => err(e),
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    if std::env::args().nth(1).as_deref()==Some("--verify-contract") {
        println!("{}",encode(aios_router_mcp_v3_postal_candidate::completion::runner()));
        return Ok(());
    }
    const DB: &str = "/var/lib/aios-router/router.sqlite3";
    const RECEIPTS: &str = "/var/lib/aios-body-receipts";
    const KEY_DIR: &str = "/var/lib/aios-router-key";
    const PRIVACY_TARGET: &str =
        r"L:\LocalCoder\workspace\aios_rebuild\memory\aios_router\router.sqlite3";
    let db = std::env::var("AIOS_ROUTER_DB").unwrap_or_else(|_| DB.into());
    let receipts = std::env::var("AIOS_BODY_RECEIPTS_DIR").unwrap_or_else(|_| RECEIPTS.into());
    let key_dir = std::env::var("AIOS_ROUTER_KEY_DIR").unwrap_or_else(|_| KEY_DIR.into());
    let privacy_target =
        std::env::var("AIOS_ROUTER_PRIVACY_TARGET").unwrap_or_else(|_| PRIVACY_TARGET.into());
    if db != DB || receipts != RECEIPTS || privacy_target != PRIVACY_TARGET || key_dir != KEY_DIR {
        return Err("router database, receipt, key, and PrivacyCore target paths are fixed".into());
    }
    let server = Mcp {
        router: std::sync::Arc::new(Router::new(
            PathBuf::from(db),
            PathBuf::from(receipts),
            privacy_target,
            PathBuf::from(key_dir),
        )),
    }
    .serve(stdio())
    .await?;
    server.waiting().await?;
    Ok(())
}
