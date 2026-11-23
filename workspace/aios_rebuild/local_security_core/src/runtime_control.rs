//! Typed, fail-closed authorization for operator runtime controls.
//!
//! The dashboard is only a request surface.  This module is the authority
//! membrane for bounded training start/stop requests.  It deliberately keeps
//! Viv's autonomous actor closed until a later, separately authorized stage.

use crate::laws::effective_dormancy_threshold;
use crate::normalize::normalize_probe_text;
use hex::encode as hex_encode;
use serde::{Deserialize, Serialize};
use serde_json::json;
use sha2::{Digest, Sha256};
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};

const MAX_REQUEST_BYTES: usize = 64 * 1024;
const MAX_ID_BYTES: usize = 128;
const MAX_FORENSIC_BYTES: usize = 16 * 1024;
const MAX_RUNTIME_SECONDS: u64 = 4 * 60 * 60;
const OPERATOR_ACTOR: &str = "operator_dashboard";
const VIV_ACTOR: &str = "viv_autonomous";
const AUTONOMOUS_RUNTIME_CONTROL_ENABLED: bool = false;
const POLICY_VERSION: &str = "runtime-control-v1";
const RUNTIME_LEDGER_PATH: &str =
    "L:/Continue/Viv/foundation/artifacts/audit/runtime_control_events.jsonl";

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum RuntimeControlAction {
    StartTraining,
    StopTraining,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RuntimeControlRequest {
    pub action: RuntimeControlAction,
    pub actor: String,
    pub request_id: String,
    pub target_id: String,
    pub manifest_hash: String,
    pub state_hash: String,
    pub master_s_n: f64,
    pub process_id: u32,
    pub target_process_id: Option<u32>,
    pub forensic_buffer: String,
    pub max_duration_s: u64,
}

#[derive(Debug, Clone, Serialize)]
pub struct RuntimeControlVerdict {
    pub allowed: bool,
    pub disposition: String,
    pub reason: String,
    pub rule: String,
    pub decision_id: String,
    pub policy_version: String,
    pub action: Option<RuntimeControlAction>,
    pub actor: String,
    pub request_id: String,
    pub target_id: String,
    pub manifest_hash: String,
    pub state_hash: String,
    pub target_process_id: Option<u32>,
    pub autonomous_access: bool,
    pub ledger_recorded: bool,
    pub master_s_n: Option<f64>,
}

fn now_nanos() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos()
}

fn sha256_bytes(data: &[u8]) -> String {
    hex_encode(Sha256::digest(data))
}

fn valid_hash(value: &str) -> bool {
    value.len() == 64 && value.bytes().all(|byte| byte.is_ascii_hexdigit())
}

fn safe_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= MAX_ID_BYTES
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'))
        && !value.contains("..")
}

fn empty_verdict(
    request: Option<&RuntimeControlRequest>,
    reason: &str,
    rule: &str,
) -> RuntimeControlVerdict {
    RuntimeControlVerdict {
        allowed: false,
        disposition: "DENY".to_string(),
        reason: reason.to_string(),
        rule: rule.to_string(),
        decision_id: sha256_bytes(format!("deny:{rule}:{reason}:{}", now_nanos()).as_bytes())[..32]
            .to_string(),
        policy_version: POLICY_VERSION.to_string(),
        action: request.map(|item| item.action.clone()),
        actor: request.map(|item| item.actor.clone()).unwrap_or_default(),
        request_id: request
            .map(|item| item.request_id.clone())
            .unwrap_or_default(),
        target_id: request
            .map(|item| item.target_id.clone())
            .unwrap_or_default(),
        manifest_hash: request
            .map(|item| item.manifest_hash.clone())
            .unwrap_or_default(),
        state_hash: request
            .map(|item| item.state_hash.clone())
            .unwrap_or_default(),
        target_process_id: request.and_then(|item| item.target_process_id),
        autonomous_access: AUTONOMOUS_RUNTIME_CONTROL_ENABLED,
        ledger_recorded: false,
        master_s_n: request.map(|item| item.master_s_n),
    }
}

fn parse_request(raw: &str) -> Result<RuntimeControlRequest, String> {
    if raw.is_empty() || raw.len() > MAX_REQUEST_BYTES {
        return Err("request_size_invalid".to_string());
    }
    let mut deserializer = serde_json::Deserializer::from_str(raw);
    let request = RuntimeControlRequest::deserialize(&mut deserializer)
        .map_err(|error| format!("request_schema:{error}"))?;
    deserializer
        .end()
        .map_err(|error| format!("request_trailing_data:{error}"))?;
    Ok(request)
}

fn validate_request(request: &RuntimeControlRequest) -> Result<(), (&'static str, String)> {
    if request.process_id != std::process::id() {
        return Err((
            "process_binding",
            "request process_id does not match caller".to_string(),
        ));
    }
    if request.actor == VIV_ACTOR && !AUTONOMOUS_RUNTIME_CONTROL_ENABLED {
        return Err((
            "autonomous_runtime_control_closed",
            "Viv autonomous runtime control is closed at this stage".to_string(),
        ));
    }
    if request.actor != OPERATOR_ACTOR {
        return Err((
            "actor_not_allowlisted",
            "only operator_dashboard may request this action".to_string(),
        ));
    }
    if !safe_id(&request.request_id) || !safe_id(&request.target_id) {
        return Err((
            "identifier",
            "request_id or target_id is unsafe".to_string(),
        ));
    }
    if !valid_hash(&request.manifest_hash) || !valid_hash(&request.state_hash) {
        return Err((
            "hash_contract",
            "manifest_hash and state_hash must be SHA-256".to_string(),
        ));
    }
    if !request.master_s_n.is_finite() || request.master_s_n < effective_dormancy_threshold() {
        return Err((
            "law5_stability",
            format!(
                "Master S_n {:.4} is below {:.4}",
                request.master_s_n,
                effective_dormancy_threshold()
            ),
        ));
    }
    if request.max_duration_s == 0 || request.max_duration_s > MAX_RUNTIME_SECONDS {
        return Err((
            "resource_ceiling",
            "max_duration_s is outside the bounded runtime ceiling".to_string(),
        ));
    }
    if request.forensic_buffer.len() > MAX_FORENSIC_BYTES {
        return Err((
            "forensic_buffer",
            "forensic buffer is too large".to_string(),
        ));
    }
    let forensic = normalize_probe_text(&request.forensic_buffer).to_uppercase();
    if !forensic.contains("DO I?") {
        return Err((
            "law8_cognitive_sync",
            "Law 8 requires an explicit 'Do I?' forensic review trace".to_string(),
        ));
    }
    match request.action {
        RuntimeControlAction::StartTraining => {
            if request.target_process_id.is_some() {
                return Err((
                    "start_target",
                    "start requests cannot carry a target process id".to_string(),
                ));
            }
        }
        RuntimeControlAction::StopTraining => {
            let Some(pid) = request.target_process_id else {
                return Err((
                    "stop_target",
                    "stop requests require an exact target process id".to_string(),
                ));
            };
            if pid == 0 {
                return Err((
                    "stop_target",
                    "target process id must be non-zero".to_string(),
                ));
            }
        }
    }
    Ok(())
}

fn append_ledger(verdict: &RuntimeControlVerdict) -> bool {
    let path = Path::new(RUNTIME_LEDGER_PATH);
    let Some(parent) = path.parent() else {
        return false;
    };
    if fs::create_dir_all(parent).is_err() {
        return false;
    }
    let mut logged_verdict = verdict.clone();
    logged_verdict.ledger_recorded = true;
    let payload = json!({
        "schema_version": "viv_runtime_control_event_v1",
        "recorded_utc_epoch_nanos": now_nanos(),
        "verdict": logged_verdict,
    });
    let Ok(serialized) = serde_json::to_string(&payload) else {
        return false;
    };
    let Ok(mut file) = OpenOptions::new().create(true).append(true).open(path) else {
        return false;
    };
    file.write_all(serialized.as_bytes()).is_ok() && file.write_all(b"\n").is_ok()
}

pub fn authorize(raw: &str) -> RuntimeControlVerdict {
    let parsed = match parse_request(raw) {
        Ok(request) => request,
        Err(error) => {
            let verdict = empty_verdict(None, &error, "request_schema");
            let mut recorded = verdict.clone();
            recorded.ledger_recorded = append_ledger(&verdict);
            return recorded;
        }
    };
    if let Err((rule, reason)) = validate_request(&parsed) {
        let verdict = empty_verdict(Some(&parsed), &reason, rule);
        let mut recorded = verdict.clone();
        recorded.ledger_recorded = append_ledger(&verdict);
        return recorded;
    }
    let decision_id = sha256_bytes(
        format!(
            "allow:{}:{}:{}:{}",
            parsed.request_id,
            parsed.process_id,
            parsed.target_id,
            now_nanos()
        )
        .as_bytes(),
    )[..32]
        .to_string();
    let mut verdict = RuntimeControlVerdict {
        allowed: true,
        disposition: "ALLOW".to_string(),
        reason: "OK".to_string(),
        rule: "runtime_control_allowlist".to_string(),
        decision_id,
        policy_version: POLICY_VERSION.to_string(),
        action: Some(parsed.action.clone()),
        actor: parsed.actor.clone(),
        request_id: parsed.request_id.clone(),
        target_id: parsed.target_id.clone(),
        manifest_hash: parsed.manifest_hash.clone(),
        state_hash: parsed.state_hash.clone(),
        target_process_id: parsed.target_process_id,
        autonomous_access: AUTONOMOUS_RUNTIME_CONTROL_ENABLED,
        ledger_recorded: false,
        master_s_n: Some(parsed.master_s_n),
    };
    verdict.ledger_recorded = append_ledger(&verdict);
    if !verdict.ledger_recorded {
        verdict.allowed = false;
        verdict.disposition = "DENY".to_string();
        verdict.reason = "runtime control ledger could not be recorded".to_string();
        verdict.rule = "runtime_control_ledger".to_string();
    }
    verdict
}

#[cfg(test)]
mod tests {
    use super::*;

    fn request(action: RuntimeControlAction) -> RuntimeControlRequest {
        RuntimeControlRequest {
            action,
            actor: OPERATOR_ACTOR.to_string(),
            request_id: "dashboard-test-1".to_string(),
            target_id: "viv-training".to_string(),
            manifest_hash: "a".repeat(64),
            state_hash: "b".repeat(64),
            master_s_n: 0.8,
            process_id: std::process::id(),
            target_process_id: None,
            forensic_buffer: "Do I? Operator reviewed the bounded request.".to_string(),
            max_duration_s: 300,
        }
    }

    #[test]
    fn operator_start_is_allowlisted() {
        let raw =
            serde_json::to_string(&request(RuntimeControlAction::StartTraining)).expect("json");
        let verdict = authorize(&raw);
        assert!(verdict.allowed, "{verdict:?}");
        assert!(verdict.ledger_recorded, "{verdict:?}");
        assert!(!verdict.autonomous_access);
    }

    #[test]
    fn autonomous_actor_is_closed() {
        let mut value = request(RuntimeControlAction::StartTraining);
        value.actor = VIV_ACTOR.to_string();
        let verdict = authorize(&serde_json::to_string(&value).expect("json"));
        assert!(!verdict.allowed);
        assert_eq!(verdict.rule, "autonomous_runtime_control_closed");
    }

    #[test]
    fn law8_is_required() {
        let mut value = request(RuntimeControlAction::StartTraining);
        value.forensic_buffer = "operator confirmed".to_string();
        let verdict = authorize(&serde_json::to_string(&value).expect("json"));
        assert!(!verdict.allowed);
        assert_eq!(verdict.rule, "law8_cognitive_sync");
    }

    #[test]
    fn stop_requires_exact_nonzero_pid() {
        let mut value = request(RuntimeControlAction::StopTraining);
        value.target_process_id = Some(0);
        let verdict = authorize(&serde_json::to_string(&value).expect("json"));
        assert!(!verdict.allowed);
        assert_eq!(verdict.rule, "stop_target");
    }

    #[test]
    fn unknown_fields_are_rejected() {
        let raw = r#"{"action":"START_TRAINING","actor":"operator_dashboard","request_id":"x","target_id":"t","manifest_hash":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","state_hash":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","master_s_n":0.8,"process_id":1,"target_process_id":null,"forensic_buffer":"Do I?","max_duration_s":1,"bypass":true}"#;
        let verdict = authorize(raw);
        assert!(!verdict.allowed);
        assert_eq!(verdict.rule, "request_schema");
    }
}
