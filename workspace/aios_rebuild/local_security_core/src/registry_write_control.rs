//! Approval-bound control for the active template registry.
//!
//! This is deliberately narrower than the autonomous filesystem surface.  It
//! authorizes one exact JSON target, only with a separately supplied
//! Architect approval bound to the proposal hash.  Rust authorizes the
//! transaction; the Python adapter performs the already-authorized atomic
//! write and must re-check the parent hash immediately before doing so.

use crate::laws::effective_dormancy_threshold;
use crate::normalize::{normalize_path, normalize_probe_text, path_has_traversal};
use crate::python_write_control::{parse_approval, validate_approval_binding, ArchitectApproval};
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
const MAX_REGISTRY_BYTES: u64 = 512 * 1024;
const VIV_ACTOR: &str = "viv_autonomous";
const REGISTRY_TARGET: &str = "l:/continue/viv/foundation/code_templates/registry.json";
const REGISTRY_LEDGER_PATH: &str =
    "L:/Continue/Viv/foundation/artifacts/audit/registry_write_control_events.jsonl";
const POLICY_VERSION: &str = "registry-write-control-v1";

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum RegistryWriteAction {
    WriteRegistryJson,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RegistryWriteRequest {
    pub action: RegistryWriteAction,
    pub actor: String,
    pub operation_id: String,
    pub request_id: String,
    pub target_path: String,
    pub parent_sha256: String,
    pub content_sha256: String,
    pub content_bytes: u64,
    pub provenance_sha256: String,
    pub process_id: u32,
    pub master_s_n: f64,
    pub forensic_buffer: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct RegistryWriteVerdict {
    pub allowed: bool,
    pub disposition: String,
    pub reason: String,
    pub rule: String,
    pub decision_id: String,
    pub policy_version: String,
    pub action: Option<RegistryWriteAction>,
    pub actor: String,
    pub operation_id: String,
    pub request_id: String,
    pub normalized_target_path: String,
    pub parent_sha256: String,
    pub content_sha256: String,
    pub content_bytes: u64,
    pub provenance_sha256: String,
    pub autonomous_access: bool,
    pub ledger_recorded: bool,
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
    request: Option<&RegistryWriteRequest>,
    reason: &str,
    rule: &str,
) -> RegistryWriteVerdict {
    RegistryWriteVerdict {
        allowed: false,
        disposition: "DENY".to_string(),
        reason: reason.to_string(),
        rule: rule.to_string(),
        decision_id: sha256_bytes(format!("deny:{rule}:{reason}:{}", now_nanos()).as_bytes())[..32]
            .to_string(),
        policy_version: POLICY_VERSION.to_string(),
        action: request.map(|item| item.action.clone()),
        actor: request.map(|item| item.actor.clone()).unwrap_or_default(),
        operation_id: request
            .map(|item| item.operation_id.clone())
            .unwrap_or_default(),
        request_id: request
            .map(|item| item.request_id.clone())
            .unwrap_or_default(),
        normalized_target_path: request
            .map(|item| normalize_path(&item.target_path))
            .unwrap_or_default(),
        parent_sha256: request
            .map(|item| item.parent_sha256.clone())
            .unwrap_or_default(),
        content_sha256: request
            .map(|item| item.content_sha256.clone())
            .unwrap_or_default(),
        content_bytes: request.map(|item| item.content_bytes).unwrap_or_default(),
        provenance_sha256: request
            .map(|item| item.provenance_sha256.clone())
            .unwrap_or_default(),
        autonomous_access: false,
        ledger_recorded: false,
    }
}

fn parse_request(raw: &str) -> Result<RegistryWriteRequest, String> {
    if raw.is_empty() || raw.len() > MAX_REQUEST_BYTES {
        return Err("request_size_invalid".to_string());
    }
    let mut deserializer = serde_json::Deserializer::from_str(raw);
    let request = RegistryWriteRequest::deserialize(&mut deserializer)
        .map_err(|error| format!("request_schema:{error}"))?;
    deserializer
        .end()
        .map_err(|error| format!("request_trailing_data:{error}"))?;
    Ok(request)
}

fn existing_component_is_reparse(path: &Path) -> bool {
    let mut cursor = Some(path);
    while let Some(current) = cursor {
        if let Ok(metadata) = fs::symlink_metadata(current) {
            if metadata.file_type().is_symlink() {
                return true;
            }
            #[cfg(windows)]
            {
                use std::os::windows::fs::MetadataExt;
                const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x400;
                if metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
                    return true;
                }
            }
        }
        cursor = current.parent();
    }
    false
}

fn normalized_registry_target(raw: &str) -> Result<String, (&'static str, String)> {
    if raw.is_empty() || raw.len() > 768 || path_has_traversal(raw) {
        return Err((
            "path_contract",
            "target path is empty, oversized, or traverses".to_string(),
        ));
    }
    let normalized = normalize_path(raw);
    if normalized != REGISTRY_TARGET {
        return Err((
            "registry_target_allowlist",
            "only the canonical active template registry is allowlisted".to_string(),
        ));
    }
    if existing_component_is_reparse(Path::new(raw)) {
        return Err((
            "reparse_path",
            "symlink or reparse-point path is denied".to_string(),
        ));
    }
    Ok(normalized)
}

fn validate_request(request: &RegistryWriteRequest) -> Result<String, (&'static str, String)> {
    if request.process_id != std::process::id() {
        return Err((
            "process_binding",
            "request process_id does not match caller".to_string(),
        ));
    }
    if request.action != RegistryWriteAction::WriteRegistryJson {
        return Err((
            "action_allowlist",
            "only WRITE_REGISTRY_JSON is supported".to_string(),
        ));
    }
    if request.actor != VIV_ACTOR {
        return Err((
            "actor_not_allowlisted",
            "only viv_autonomous may use this capability".to_string(),
        ));
    }
    if !safe_id(&request.operation_id) || !safe_id(&request.request_id) {
        return Err((
            "identifier",
            "operation_id or request_id is unsafe".to_string(),
        ));
    }
    let target = normalized_registry_target(&request.target_path)?;
    if !valid_hash(&request.parent_sha256)
        || !valid_hash(&request.content_sha256)
        || !valid_hash(&request.provenance_sha256)
    {
        return Err((
            "hash_contract",
            "parent, content, and provenance hashes must be SHA-256".to_string(),
        ));
    }
    if request.content_bytes > MAX_REGISTRY_BYTES {
        return Err((
            "resource_ceiling",
            "registry JSON exceeds the Rust size ceiling".to_string(),
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
    if request.forensic_buffer.len() > MAX_FORENSIC_BYTES {
        return Err((
            "forensic_buffer",
            "forensic buffer is too large".to_string(),
        ));
    }
    if !normalize_probe_text(&request.forensic_buffer)
        .to_uppercase()
        .contains("DO I?")
    {
        return Err((
            "law8_cognitive_sync",
            "Law 8 requires an explicit 'Do I?' forensic review trace".to_string(),
        ));
    }
    Ok(target)
}

fn append_ledger(verdict: &RegistryWriteVerdict, approval: Option<&ArchitectApproval>) -> bool {
    let path = Path::new(REGISTRY_LEDGER_PATH);
    let Some(parent) = path.parent() else {
        return false;
    };
    if fs::create_dir_all(parent).is_err() {
        return false;
    }
    let mut logged = verdict.clone();
    logged.ledger_recorded = true;
    let mut payload = json!({
        "schema_version": "viv_registry_write_control_event_v1",
        "recorded_utc_epoch_nanos": now_nanos(),
        "verdict": logged,
    });
    if let Some(approval) = approval {
        payload["approval"] = json!({
            "approval_id": approval.approval_id,
            "approval_sha256": approval.approval_sha256,
            "proposal_sha256": approval.proposal_sha256,
        });
    }
    let Ok(serialized) = serde_json::to_string(&payload) else {
        return false;
    };
    let Ok(mut file) = OpenOptions::new().create(true).append(true).open(path) else {
        return false;
    };
    file.write_all(serialized.as_bytes()).is_ok() && file.write_all(b"\n").is_ok()
}

/// Authorize one exact active-registry JSON write through the same proposal-
/// bound Architect approval used by production generation.  This route does
/// not authorize the active pointer and never opens autonomous registry
/// mutation.
pub fn authorize_human_approved(raw_request: &str, raw_approval: &str) -> RegistryWriteVerdict {
    let parsed = match parse_request(raw_request) {
        Ok(request) => request,
        Err(error) => {
            let verdict = empty_verdict(None, &error, "request_schema");
            let mut recorded = verdict.clone();
            recorded.ledger_recorded = append_ledger(&verdict, None);
            return recorded;
        }
    };
    let target = match validate_request(&parsed) {
        Ok(target) => target,
        Err((rule, reason)) => {
            let verdict = empty_verdict(Some(&parsed), &reason, rule);
            let mut recorded = verdict.clone();
            recorded.ledger_recorded = append_ledger(&verdict, None);
            return recorded;
        }
    };
    let approval = match parse_approval(raw_approval) {
        Ok(approval) => approval,
        Err(error) => {
            let verdict = empty_verdict(Some(&parsed), &error, "approval_schema");
            let mut recorded = verdict.clone();
            recorded.normalized_target_path = target;
            recorded.ledger_recorded = append_ledger(&recorded, None);
            return recorded;
        }
    };
    if let Err((rule, reason)) = validate_approval_binding(
        &parsed.provenance_sha256,
        &approval,
        &["template_insertion", "production_generation"],
    ) {
        let verdict = empty_verdict(Some(&parsed), &reason, rule);
        let mut recorded = verdict.clone();
        recorded.normalized_target_path = target;
        recorded.ledger_recorded = append_ledger(&recorded, Some(&approval));
        return recorded;
    }
    let decision_id = sha256_bytes(
        format!(
            "human-approved-registry:{}:{}:{}:{}:{}",
            parsed.request_id,
            parsed.process_id,
            target,
            approval.approval_id,
            now_nanos()
        )
        .as_bytes(),
    )[..32]
        .to_string();
    let mut verdict = RegistryWriteVerdict {
        allowed: true,
        disposition: "ALLOW".to_string(),
        reason: "Architect approval verified".to_string(),
        rule: "human_approved_registry_write".to_string(),
        decision_id,
        policy_version: POLICY_VERSION.to_string(),
        action: Some(parsed.action.clone()),
        actor: parsed.actor.clone(),
        operation_id: parsed.operation_id.clone(),
        request_id: parsed.request_id.clone(),
        normalized_target_path: target,
        parent_sha256: parsed.parent_sha256.clone(),
        content_sha256: parsed.content_sha256.clone(),
        content_bytes: parsed.content_bytes,
        provenance_sha256: parsed.provenance_sha256.clone(),
        autonomous_access: false,
        ledger_recorded: false,
    };
    verdict.ledger_recorded = append_ledger(&verdict, Some(&approval));
    if !verdict.ledger_recorded {
        verdict.allowed = false;
        verdict.disposition = "DENY".to_string();
        verdict.reason = "Registry write-control ledger could not be recorded".to_string();
        verdict.rule = "registry_write_control_ledger".to_string();
    }
    verdict
}

#[cfg(test)]
mod tests {
    use super::*;

    fn request(target: &str) -> RegistryWriteRequest {
        RegistryWriteRequest {
            action: RegistryWriteAction::WriteRegistryJson,
            actor: VIV_ACTOR.to_string(),
            operation_id: "registry-write-test-1".to_string(),
            request_id: "registry-write-request-1".to_string(),
            target_path: target.to_string(),
            parent_sha256: "a".repeat(64),
            content_sha256: "b".repeat(64),
            content_bytes: 128,
            provenance_sha256: "c".repeat(64),
            process_id: std::process::id(),
            master_s_n: 0.8,
            forensic_buffer: "Do I? CPU reviewed the bounded registry proposal.".to_string(),
        }
    }

    #[test]
    fn exact_registry_target_is_required() {
        assert!(validate_request(&request(REGISTRY_TARGET)).is_ok());
        assert!(validate_request(&request(
            "L:/Continue/Viv/foundation/code_templates/other.json"
        ))
        .is_err());
    }

    #[test]
    fn approval_digest_is_shared_with_python_write_control() {
        let mut approval = ArchitectApproval {
            schema_version: "viv_cpu_human_approved_production_adoption_approval_v1".to_string(),
            approver_actor: "ARCHITECT".to_string(),
            approval_id: "registry-test-approval".to_string(),
            proposal_sha256: "c".repeat(64),
            approved_operations: vec![
                "template_insertion".to_string(),
                "production_generation".to_string(),
            ],
            pointer_adoption_approved: false,
            approval_sha256: String::new(),
        };
        approval.approval_sha256 = crate::python_write_control::approval_digest(&approval);
        assert!(validate_approval_binding(
            &"c".repeat(64),
            &approval,
            &["template_insertion", "production_generation"],
        )
        .is_ok());
    }
}
