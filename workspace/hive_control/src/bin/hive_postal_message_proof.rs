//! Narrow proof of Queen-mediated sealed mail using the existing Rust Control.
//! This is an in-memory proof, not a durable mailbox or hardware identity service.

use hive_control::{sha, Control};
use serde_json::{json, Value};
use std::time::Duration;

const TASK: &str = "postal-proof-task";
const DRONE_1: &str = "drone-1-fixture";
const DRONE_2: &str = "drone-2-fixture";
const QUEEN: &str = "queen-fixture";

fn seal_mail(
    control: &mut Control,
    sender: &str,
    recipient: &str,
    body: &Value,
) -> Result<Value, String> {
    let grant = control.create_channel(true, sender, recipient, TASK, Duration::from_secs(60))?;
    let plaintext = serde_json::to_vec(body).map_err(|error| error.to_string())?;
    control.seal_peer(sender, recipient, TASK, &grant, &plaintext)
}

fn open_mail(control: &Control, envelope: &Value, recipient: &str) -> Result<Value, String> {
    let plaintext = control.open_peer(envelope, recipient)?;
    serde_json::from_slice(&plaintext).map_err(|error| error.to_string())
}

fn require(condition: bool, reason: &str) -> Result<(), String> {
    if condition {
        Ok(())
    } else {
        Err(reason.into())
    }
}

fn run() -> Result<Value, String> {
    let mut control = Control::new(vec![]);
    control.seal_task(TASK, DRONE_1, None, None, &json!({"scope": "proof"}))?;

    let drone_report = json!({
        "schema": "hive_postal_message_v1",
        "message_id": "drone-1-report-001",
        "sender_id": DRONE_1,
        "recipient_id": QUEEN,
        "task_id": TASK,
        "kind": "REPORT",
        "request": {"kind": "SELF_PROMPT_AND_ROUTE_REPORT", "proposed_recipient": DRONE_2},
        "body": {"finding": "sealed fixture report"}
    });
    let to_queen = seal_mail(&mut control, DRONE_1, QUEEN, &drone_report)?;
    let opened_report = open_mail(&control, &to_queen, QUEEN)?;
    require(
        opened_report["sender_id"] == DRONE_1
            && opened_report["recipient_id"] == QUEEN
            && opened_report["task_id"] == TASK,
        "Queen report identity or task check failed",
    )?;
    let report_hash = sha(&serde_json::to_vec(&opened_report).map_err(|error| error.to_string())?);

    let self_prompt = json!({
        "schema": "hive_postal_message_v1",
        "message_id": "queen-self-prompt-001",
        "sender_id": QUEEN,
        "recipient_id": DRONE_1,
        "task_id": TASK,
        "kind": "SELF_PROMPT",
        "parent_message_sha256": report_hash,
        "body": {"next_bounded_action": "continue the assigned task and report"}
    });
    let to_drone_1 = seal_mail(&mut control, QUEEN, DRONE_1, &self_prompt)?;
    let drone_1_opened = open_mail(&control, &to_drone_1, DRONE_1)?;
    require(
        drone_1_opened == self_prompt,
        "Drone 1 could not open its routed self-prompt",
    )?;

    let queen_forward = json!({
        "schema": "hive_postal_message_v1",
        "message_id": "queen-forward-001",
        "sender_id": QUEEN,
        "recipient_id": DRONE_2,
        "task_id": TASK,
        "kind": "ROUTED_REPORT",
        "parent_message_sha256": report_hash,
        "body": opened_report["body"]
    });
    let to_drone_2 = seal_mail(&mut control, QUEEN, DRONE_2, &queen_forward)?;
    let drone_2_opened = open_mail(&control, &to_drone_2, DRONE_2)?;
    require(
        drone_2_opened == queen_forward,
        "Drone 2 could not open Queen's routed report",
    )?;
    let wrong_recipient_denied = open_mail(&control, &to_drone_2, DRONE_1).is_err();
    let direct_route_without_grant = control
        .create_channel(false, DRONE_1, DRONE_2, TASK, Duration::from_secs(60))
        .is_err();
    require(
        wrong_recipient_denied,
        "a non-recipient opened Drone 2's envelope",
    )?;
    require(
        direct_route_without_grant,
        "an unapproved Drone-to-Drone grant was accepted",
    )?;

    Ok(json!({
        "schema": "hive_postal_message_proof_v1",
        "status": "PASS",
        "checks": {
            "drone_report_opened_by_queen": true,
            "queen_resealed_self_prompt_to_drone_1": true,
            "queen_resealed_report_to_drone_2": true,
            "wrong_recipient_denied": wrong_recipient_denied,
            "direct_route_without_queen_grant_denied": direct_route_without_grant
        },
        "report_sha256": report_hash,
        "identity_mode": "fixture IDs; hardware-bound identity is not implemented",
        "storage_mode": "in-memory keys and messages; durable inbox/outbox is not implemented",
        "limitations": [
            "does not connect OpenCode sessions",
            "does not enforce operating-system mailbox permissions",
            "does not persist identity keys or mail across process restarts"
        ]
    }))
}

fn main() {
    match run() {
        Ok(receipt) => println!("{}", serde_json::to_string_pretty(&receipt).unwrap()),
        Err(error) => {
            eprintln!("HIVE_POSTAL_PROOF_FAILED: {error}");
            std::process::exit(1);
        }
    }
}
