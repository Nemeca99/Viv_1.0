//! Explicit Architect approval and Rust authorization for runtime-pointer adoption.
//!
//! This is intentionally separate from the existing human-approved source and
//! registry routes.  A generated version may exist without being Viv's active
//! version.  Only this route can authorize the exact runtime pointer target,
//! and it authorizes an atomic Python-side replacement; Rust never performs the
//! filesystem write itself.

use crate::laws::effective_dormancy_threshold;
use crate::normalize::{normalize_path, normalize_probe_text, path_has_traversal};
use hex::encode as hex_encode;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};

const MAX_REQUEST_BYTES: usize = 64 * 1024;
const MAX_ID_BYTES: usize = 128;
const MAX_FORENSIC_BYTES: usize = 16 * 1024;
const MAX_POINTER_BYTES: u64 = 64 * 1024;
const VIV_ACTOR: &str = "viv_autonomous";
const POINTER_TARGET: &str = "l:/continue/viv/sandbox/code/template_current.json";
const LEDGER_PATH: &str =
    "L:/Continue/Viv/foundation/artifacts/audit/pointer_adoption_control_events.jsonl";
const POLICY_VERSION: &str = "pointer-adoption-control-v1";
const APPROVAL_SCHEMA: &str = "viv_cpu_human_approved_pointer_adoption_approval_v1";

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum PointerAdoptionAction {
    ActivateTemplatePointer,
    RollbackTemplatePointer,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PointerAdoptionRequest {
    pub action: PointerAdoptionAction,
    pub actor: String,
    pub operation_id: String,
    pub request_id: String,
    pub target_path: String,
    pub parent_sha256: String,
    pub content_sha256: String,
    pub content_bytes: u64,
    pub provenance_sha256: String,
    pub candidate_generation_id: String,
    pub incumbent_generation_id: String,
    pub process_id: u32,
    pub master_s_n: f64,
    pub forensic_buffer: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PointerAdoptionApproval {
    pub schema_version: String,
    pub approver_actor: String,
    pub approval_id: String,
    pub proposal_sha256: String,
    pub approved_operations: Vec<String>,
    pub pointer_adoption_approved: bool,
    pub approval_sha256: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct PointerAdoptionVerdict {
    pub allowed: bool,
    pub disposition: String,
    pub reason: String,
    pub rule: String,
    pub decision_id: String,
    pub policy_version: String,
    pub action: Option<PointerAdoptionAction>,
    pub actor: String,
    pub operation_id: String,
    pub request_id: String,
    pub normalized_target_path: String,
    pub parent_sha256: String,
    pub content_sha256: String,
    pub content_bytes: u64,
    pub provenance_sha256: String,
    pub candidate_generation_id: String,
    pub incumbent_generation_id: String,
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

fn generation_id(value: &str) -> bool {
    value.len() == 20
        && value.starts_with("gen_")
        && value[4..].bytes().all(|byte| byte.is_ascii_hexdigit())
}

fn empty_verdict(
    request: Option<&PointerAdoptionRequest>,
    reason: &str,
    rule: &str,
) -> PointerAdoptionVerdict {
    PointerAdoptionVerdict {
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
        candidate_generation_id: request
            .map(|item| item.candidate_generation_id.clone())
            .unwrap_or_default(),
        incumbent_generation_id: request
            .map(|item| item.incumbent_generation_id.clone())
            .unwrap_or_default(),
        autonomous_access: false,
        ledger_recorded: false,
    }
}

fn parse_request(raw: &str) -> Result<PointerAdoptionRequest, String> {
    if raw.is_empty() || raw.len() > MAX_REQUEST_BYTES {
        return Err("request_size_invalid".to_string());
    }
    let mut deserializer = serde_json::Deserializer::from_str(raw);
    let request = PointerAdoptionRequest::deserialize(&mut deserializer)
        .map_err(|error| format!("request_schema:{error}"))?;
    deserializer
        .end()
        .map_err(|error| format!("request_trailing_data:{error}"))?;
    Ok(request)
}

fn parse_approval(raw: &str) -> Result<PointerAdoptionApproval, String> {
    if raw.is_empty() || raw.len() > MAX_REQUEST_BYTES {
        return Err("approval_size_invalid".to_string());
    }
    let mut deserializer = serde_json::Deserializer::from_str(raw);
    let approval = PointerAdoptionApproval::deserialize(&mut deserializer)
        .map_err(|error| format!("approval_schema:{error}"))?;
    deserializer
        .end()
        .map_err(|error| format!("approval_trailing_data:{error}"))?;
    Ok(approval)
}

fn approval_core(approval: &PointerAdoptionApproval) -> BTreeMap<String, Value> {
    BTreeMap::from([
        (
            "approved_operations".to_string(),
            json!(approval.approved_operations),
        ),
        ("approver_actor".to_string(), json!(approval.approver_actor)),
        ("approval_id".to_string(), json!(approval.approval_id)),
        (
            "pointer_adoption_approved".to_string(),
            json!(approval.pointer_adoption_approved),
        ),
        (
            "proposal_sha256".to_string(),
            json!(approval.proposal_sha256),
        ),
        ("schema_version".to_string(), json!(approval.schema_version)),
    ])
}

fn approval_digest(approval: &PointerAdoptionApproval) -> String {
    let canonical = serde_json::to_string(&approval_core(approval)).unwrap_or_default();
    sha256_bytes(format!("{canonical}\n").as_bytes())
}

fn normalized_pointer_target(raw: &str) -> Result<String, (&'static str, String)> {
    if raw.is_empty() || raw.len() > 768 || path_has_traversal(raw) {
        return Err((
            "path_contract",
            "pointer target is empty, oversized, or traverses".to_string(),
        ));
    }
    let normalized = normalize_path(raw);
    if normalized != POINTER_TARGET {
        return Err((
            "pointer_target_allowlist",
            "only the canonical runtime pointer is allowlisted".to_string(),
        ));
    }
    let path = Path::new(raw);
    if path
        .ancestors()
        .filter_map(|item| fs::symlink_metadata(item).ok())
        .any(|metadata| metadata.file_type().is_symlink())
    {
        return Err((
            "reparse_path",
            "symlink or reparse-point pointer path is denied".to_string(),
        ));
    }
    Ok(normalized)
}

fn validate_request(request: &PointerAdoptionRequest) -> Result<String, (&'static str, String)> {
    if request.process_id != std::process::id() {
        return Err((
            "process_binding",
            "request process_id does not match caller".to_string(),
        ));
    }
    if request.actor != VIV_ACTOR {
        return Err((
            "actor_not_allowlisted",
            "only viv_autonomous may use the bounded pointer route".to_string(),
        ));
    }
    if !safe_id(&request.operation_id) || !safe_id(&request.request_id) {
        return Err((
            "identifier",
            "operation_id or request_id is unsafe".to_string(),
        ));
    }
    let target = normalized_pointer_target(&request.target_path)?;
    if !valid_hash(&request.parent_sha256)
        || !valid_hash(&request.content_sha256)
        || !valid_hash(&request.provenance_sha256)
    {
        return Err((
            "hash_contract",
            "parent, content, and provenance hashes must be SHA-256".to_string(),
        ));
    }
    if request.content_bytes == 0 || request.content_bytes > MAX_POINTER_BYTES {
        return Err((
            "resource_ceiling",
            "pointer JSON exceeds the bounded resource ceiling".to_string(),
        ));
    }
    if !generation_id(&request.candidate_generation_id)
        || !generation_id(&request.incumbent_generation_id)
    {
        return Err((
            "generation_id",
            "candidate and incumbent generation identifiers are invalid".to_string(),
        ));
    }
    if request.candidate_generation_id == request.incumbent_generation_id {
        return Err((
            "generation_distinct",
            "candidate and incumbent generations must differ".to_string(),
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

fn validate_approval(
    request: &PointerAdoptionRequest,
    approval: &PointerAdoptionApproval,
) -> Result<(), (&'static str, String)> {
    if approval.schema_version != APPROVAL_SCHEMA {
        return Err((
            "approval_schema",
            "pointer-adoption approval schema is not recognized".to_string(),
        ));
    }
    if approval.approver_actor != "ARCHITECT" {
        return Err((
            "approval_actor",
            "only ARCHITECT may approve pointer adoption".to_string(),
        ));
    }
    if !safe_id(&approval.approval_id) {
        return Err(("approval_identifier", "approval_id is unsafe".to_string()));
    }
    if !approval.pointer_adoption_approved {
        return Err((
            "pointer_second_approval",
            "pointer adoption requires explicit approval".to_string(),
        ));
    }
    if !valid_hash(&approval.proposal_sha256)
        || !approval
            .proposal_sha256
            .eq_ignore_ascii_case(&request.provenance_sha256)
    {
        return Err((
            "approval_proposal_binding",
            "approval proposal hash does not bind to the pointer request".to_string(),
        ));
    }
    let required: &[&str] = match request.action {
        PointerAdoptionAction::ActivateTemplatePointer => {
            &["pointer_adoption", "live_canary", "rollback"]
        }
        PointerAdoptionAction::RollbackTemplatePointer => &["pointer_adoption", "rollback"],
    };
    if required.iter().any(|item| {
        !approval
            .approved_operations
            .iter()
            .any(|value| value == item)
    }) {
        return Err((
            "approval_operations",
            "approval does not include every required pointer operation".to_string(),
        ));
    }
    if !valid_hash(&approval.approval_sha256)
        || !approval
            .approval_sha256
            .eq_ignore_ascii_case(&approval_digest(approval))
    {
        return Err((
            "approval_self_hash",
            "pointer approval receipt self-hash is invalid".to_string(),
        ));
    }
    Ok(())
}

fn append_ledger(
    verdict: &PointerAdoptionVerdict,
    approval: Option<&PointerAdoptionApproval>,
) -> bool {
    let path = Path::new(LEDGER_PATH);
    let Some(parent) = path.parent() else {
        return false;
    };
    if fs::create_dir_all(parent).is_err() {
        return false;
    }
    let mut logged = verdict.clone();
    logged.ledger_recorded = true;
    let mut payload = json!({
        "schema_version": "viv_pointer_adoption_control_event_v1",
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

/// Authorize one exact runtime-pointer replacement.  Rust validates the
/// approval and request; the caller must still perform the atomic write and
/// re-verify the pointer and generation after the write.
pub fn authorize_human_approved(raw_request: &str, raw_approval: &str) -> PointerAdoptionVerdict {
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
    if let Err((rule, reason)) = validate_approval(&parsed, &approval) {
        let verdict = empty_verdict(Some(&parsed), &reason, rule);
        let mut recorded = verdict.clone();
        recorded.normalized_target_path = target;
        recorded.ledger_recorded = append_ledger(&recorded, Some(&approval));
        return recorded;
    }
    let decision_id = sha256_bytes(
        format!(
            "pointer-approved:{}:{}:{}:{}:{}",
            parsed.request_id,
            parsed.process_id,
            target,
            approval.approval_id,
            now_nanos()
        )
        .as_bytes(),
    )[..32]
        .to_string();
    let mut verdict = PointerAdoptionVerdict {
        allowed: true,
        disposition: "ALLOW".to_string(),
        reason: "Architect pointer approval verified".to_string(),
        rule: "human_approved_pointer_adoption".to_string(),
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
        candidate_generation_id: parsed.candidate_generation_id.clone(),
        incumbent_generation_id: parsed.incumbent_generation_id.clone(),
        autonomous_access: false,
        ledger_recorded: false,
    };
    verdict.ledger_recorded = append_ledger(&verdict, Some(&approval));
    if !verdict.ledger_recorded {
        verdict.allowed = false;
        verdict.disposition = "DENY".to_string();
        verdict.reason = "pointer-adoption control ledger could not be recorded".to_string();
        verdict.rule = "pointer_adoption_control_ledger".to_string();
    }
    verdict
}

#[cfg(test)]
mod tests {
    use super::*;

    fn request(action: PointerAdoptionAction) -> PointerAdoptionRequest {
        PointerAdoptionRequest {
            action,
            actor: VIV_ACTOR.to_string(),
            operation_id: "pointer-adoption-test".to_string(),
            request_id: "pointer-request-test".to_string(),
            target_path: POINTER_TARGET.to_string(),
            parent_sha256: "0".repeat(64),
            content_sha256: "a".repeat(64),
            content_bytes: 256,
            provenance_sha256: "b".repeat(64),
            candidate_generation_id: "gen_1111111111111111".to_string(),
            incumbent_generation_id: "gen_2222222222222222".to_string(),
            process_id: std::process::id(),
            master_s_n: 0.8,
            forensic_buffer: "Do I? Architect reviewed live adoption and rollback.".to_string(),
        }
    }

    fn approval(proposal_sha256: &str, operations: Vec<&str>) -> PointerAdoptionApproval {
        let mut value = PointerAdoptionApproval {
            schema_version: APPROVAL_SCHEMA.to_string(),
            approver_actor: "ARCHITECT".to_string(),
            approval_id: "architect-pointer-test".to_string(),
            proposal_sha256: proposal_sha256.to_string(),
            approved_operations: operations.into_iter().map(str::to_string).collect(),
            pointer_adoption_approved: true,
            approval_sha256: String::new(),
        };
        value.approval_sha256 = approval_digest(&value);
        value
    }

    #[test]
    fn explicit_pointer_approval_allows_bound_request() {
        let value = request(PointerAdoptionAction::ActivateTemplatePointer);
        let approval = approval(
            &value.provenance_sha256,
            vec!["pointer_adoption", "live_canary", "rollback"],
        );
        let verdict = authorize_human_approved(
            &serde_json::to_string(&value).expect("request json"),
            &serde_json::to_string(&approval).expect("approval json"),
        );
        assert!(verdict.allowed, "{verdict:?}");
        assert!(verdict.ledger_recorded, "{verdict:?}");
        assert!(!verdict.autonomous_access);
    }

    #[test]
    fn pointer_approval_requires_live_canary_and_rollback_scope() {
        let value = request(PointerAdoptionAction::ActivateTemplatePointer);
        let approval = approval(&value.provenance_sha256, vec!["pointer_adoption"]);
        let verdict = authorize_human_approved(
            &serde_json::to_string(&value).expect("request json"),
            &serde_json::to_string(&approval).expect("approval json"),
        );
        assert!(!verdict.allowed);
        assert_eq!(verdict.rule, "approval_operations");
    }

    #[test]
    fn pointer_target_is_exactly_allowlisted() {
        let mut value = request(PointerAdoptionAction::ActivateTemplatePointer);
        value.target_path = "L:/Continue/Viv/sandbox/code/other.json".to_string();
        let approval = approval(
            &value.provenance_sha256,
            vec!["pointer_adoption", "live_canary", "rollback"],
        );
        let verdict = authorize_human_approved(
            &serde_json::to_string(&value).expect("request json"),
            &serde_json::to_string(&approval).expect("approval json"),
        );
        assert!(!verdict.allowed);
        assert_eq!(verdict.rule, "pointer_target_allowlist");
    }
}
