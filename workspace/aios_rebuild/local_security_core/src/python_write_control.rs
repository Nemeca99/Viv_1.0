//! Deny-by-default authorization for Viv's autonomous Python self-authoring.
//!
//! The model never receives a general filesystem writer.  A future runtime
//! writer must present a typed request here, and this Rust policy must be
//! separately opened before any Python source can be changed.  The current
//! capability is intentionally compiled closed.

use crate::laws::effective_dormancy_threshold;
use crate::normalize::{normalize_path, normalize_probe_text, path_has_traversal};
use hex::encode as hex_encode;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs::{self, OpenOptions};
use std::io::{Read, Write};
use std::path::Path;
use std::thread::sleep;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

const MAX_REQUEST_BYTES: usize = 64 * 1024;
const MAX_ID_BYTES: usize = 128;
const MAX_FORENSIC_BYTES: usize = 16 * 1024;
const MAX_SOURCE_BYTES: u64 = 2 * 1024 * 1024;
const VIV_ACTOR: &str = "viv_autonomous";
const PYTHON_WRITE_ROOT: &str =
    "l:/localcoder/workspace/aios_rebuild/template_toolbox/sandbox/code";
const PYTHON_WRITE_LEDGER_PATH: &str =
    "L:/LocalCoder/workspace/aios_rebuild/template_toolbox/foundation/artifacts/audit/python_write_control_events.jsonl";
const PYTHON_WRITE_LEDGER_LOCK_SUFFIX: &str = ".lock";
const PYTHON_WRITE_LEDGER_LOCK_ATTEMPTS: usize = 2000;
const PYTHON_WRITE_LEDGER_LOCK_SLEEP_MS: u64 = 5;
const PYTHON_WRITE_LEDGER_ZERO_HASH: &str =
    "0000000000000000000000000000000000000000000000000000000000000000";
const POLICY_VERSION: &str = "python-write-control-v1";

// Explicitly closed until the Architect reviews a built module and opens a
// separate capability contract.  A Python fallback must never override this.
const AUTONOMOUS_PYTHON_WRITE_ENABLED: bool = false;

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum PythonWriteAction {
    WritePython,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PythonWriteRequest {
    pub action: PythonWriteAction,
    pub actor: String,
    pub operation_id: String,
    pub request_id: String,
    pub target_path: String,
    pub parent_sha256: String,
    pub content_sha256: String,
    pub content_bytes: u64,
    #[serde(default)]
    pub provenance_sha256: String,
    pub process_id: u32,
    pub master_s_n: f64,
    pub forensic_buffer: String,
}

/// A separately supplied Architect approval for the production-generation
/// operation.  This is intentionally not part of `PythonWriteRequest`: the
/// ordinary autonomous API remains deny-by-default, while this path requires
/// an independently authored, proposal-bound approval receipt.
#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ArchitectApproval {
    pub schema_version: String,
    pub approver_actor: String,
    pub approval_id: String,
    pub proposal_sha256: String,
    pub approved_operations: Vec<String>,
    pub pointer_adoption_approved: bool,
    pub approval_sha256: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct PythonWriteVerdict {
    pub allowed: bool,
    pub disposition: String,
    pub reason: String,
    pub rule: String,
    pub decision_id: String,
    pub policy_version: String,
    pub action: Option<PythonWriteAction>,
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

fn canonical_json(value: &Value) -> Option<String> {
    match value {
        Value::Null => Some("null".to_string()),
        Value::Bool(value) => Some(if *value { "true" } else { "false" }.to_string()),
        Value::Number(value) => Some(value.to_string()),
        Value::String(value) => serde_json::to_string(value).ok(),
        Value::Array(values) => {
            let rendered = values
                .iter()
                .map(canonical_json)
                .collect::<Option<Vec<_>>>()?;
            Some(format!("[{}]", rendered.join(",")))
        }
        Value::Object(values) => {
            let mut keys = values.keys().collect::<Vec<_>>();
            keys.sort();
            let mut rendered = Vec::with_capacity(keys.len());
            for key in keys {
                rendered.push(format!(
                    "{}:{}",
                    serde_json::to_string(key).ok()?,
                    canonical_json(values.get(key)?)?
                ));
            }
            Some(format!("{{{}}}", rendered.join(",")))
        }
    }
}

fn canonical_json_line(value: &Value) -> Option<Vec<u8>> {
    let mut rendered = canonical_json(value)?;
    rendered.push('\n');
    Some(rendered.into_bytes())
}

fn event_hash(value: &Value) -> Option<String> {
    let mut body = value.clone();
    body.as_object_mut()?.remove("event_sha256");
    Some(sha256_bytes(&canonical_json_line(&body)?).to_uppercase())
}

fn verified_ledger_head() -> Option<(u64, String)> {
    let path = Path::new(PYTHON_WRITE_LEDGER_PATH);
    if !path.exists() {
        return Some((0, PYTHON_WRITE_LEDGER_ZERO_HASH.to_string()));
    }
    let mut bytes = Vec::new();
    fs::File::open(path).ok()?.read_to_end(&mut bytes).ok()?;
    if bytes.is_empty() {
        return Some((0, PYTHON_WRITE_LEDGER_ZERO_HASH.to_string()));
    }
    if !bytes.ends_with(b"\n") {
        return None;
    }
    let mut previous = PYTHON_WRITE_LEDGER_ZERO_HASH.to_string();
    let mut expected_index = 1u64;
    for line in bytes.split_inclusive(|byte| *byte == b'\n') {
        if line.len() < 2 || line[line.len() - 2] == b'\r' {
            return None;
        }
        let body = &line[..line.len() - 1];
        let value: Value = serde_json::from_slice(body).ok()?;
        let object = value.as_object()?;
        if object.get("schema_version")?.as_str()? != "viv_python_write_control_event_v1"
            || object.get("ledger_event_index")?.as_u64()? != expected_index
            || object.get("previous_event_sha256")?.as_str()? != previous
        {
            return None;
        }
        let recorded = object.get("event_sha256")?.as_str()?.to_string();
        if recorded != event_hash(&value)? || canonical_json_line(&value)?.as_slice() != line {
            return None;
        }
        previous = recorded;
        expected_index = expected_index.checked_add(1)?;
    }
    Some((expected_index - 1, previous))
}

fn acquire_ledger_lock() -> Option<(fs::File, String)> {
    let lock_path = format!(
        "{}{}",
        PYTHON_WRITE_LEDGER_PATH, PYTHON_WRITE_LEDGER_LOCK_SUFFIX
    );
    for _ in 0..PYTHON_WRITE_LEDGER_LOCK_ATTEMPTS {
        match OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&lock_path)
        {
            Ok(file) => return Some((file, lock_path)),
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
                sleep(Duration::from_millis(PYTHON_WRITE_LEDGER_LOCK_SLEEP_MS));
            }
            Err(_) => return None,
        }
    }
    None
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
    request: Option<&PythonWriteRequest>,
    reason: &str,
    rule: &str,
) -> PythonWriteVerdict {
    PythonWriteVerdict {
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
        autonomous_access: AUTONOMOUS_PYTHON_WRITE_ENABLED,
        ledger_recorded: false,
    }
}

fn parse_request(raw: &str) -> Result<PythonWriteRequest, String> {
    if raw.is_empty() || raw.len() > MAX_REQUEST_BYTES {
        return Err("request_size_invalid".to_string());
    }
    let mut deserializer = serde_json::Deserializer::from_str(raw);
    let request = PythonWriteRequest::deserialize(&mut deserializer)
        .map_err(|error| format!("request_schema:{error}"))?;
    deserializer
        .end()
        .map_err(|error| format!("request_trailing_data:{error}"))?;
    Ok(request)
}

pub(crate) fn parse_approval(raw: &str) -> Result<ArchitectApproval, String> {
    if raw.is_empty() || raw.len() > MAX_REQUEST_BYTES {
        return Err("approval_size_invalid".to_string());
    }
    let mut deserializer = serde_json::Deserializer::from_str(raw);
    let approval = ArchitectApproval::deserialize(&mut deserializer)
        .map_err(|error| format!("approval_schema:{error}"))?;
    deserializer
        .end()
        .map_err(|error| format!("approval_trailing_data:{error}"))?;
    Ok(approval)
}

fn approval_core(approval: &ArchitectApproval) -> BTreeMap<String, Value> {
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

pub(crate) fn approval_digest(approval: &ArchitectApproval) -> String {
    let canonical = serde_json::to_string(&approval_core(approval)).unwrap_or_default();
    sha256_bytes(format!("{canonical}\n").as_bytes())
}

pub(crate) fn validate_approval_binding(
    proposal_sha256: &str,
    approval: &ArchitectApproval,
    required_operations: &[&str],
) -> Result<(), (&'static str, String)> {
    if approval.schema_version != "viv_cpu_human_approved_production_adoption_approval_v1" {
        return Err((
            "approval_schema",
            "Architect approval schema is not recognized".to_string(),
        ));
    }
    if approval.approver_actor != "ARCHITECT" {
        return Err((
            "approval_actor",
            "only ARCHITECT may approve production generation".to_string(),
        ));
    }
    if !safe_id(&approval.approval_id) {
        return Err(("approval_identifier", "approval_id is unsafe".to_string()));
    }
    if !valid_hash(&approval.proposal_sha256)
        || !valid_hash(proposal_sha256)
        || !approval
            .proposal_sha256
            .eq_ignore_ascii_case(proposal_sha256)
    {
        return Err((
            "approval_proposal_binding",
            "approval proposal hash does not bind to the write provenance".to_string(),
        ));
    }
    if required_operations.iter().any(|required| {
        !approval
            .approved_operations
            .iter()
            .any(|item| item == required)
    }) {
        return Err((
            "approval_operations",
            "approval does not include every required operation".to_string(),
        ));
    }
    if approval.pointer_adoption_approved {
        return Err((
            "pointer_second_approval",
            "pointer adoption requires a separate approval".to_string(),
        ));
    }
    if !valid_hash(&approval.approval_sha256)
        || !approval
            .approval_sha256
            .eq_ignore_ascii_case(&approval_digest(approval))
    {
        return Err((
            "approval_self_hash",
            "approval receipt self-hash is invalid".to_string(),
        ));
    }
    Ok(())
}

fn validate_approval(
    request: &PythonWriteRequest,
    approval: &ArchitectApproval,
) -> Result<(), (&'static str, String)> {
    validate_approval_binding(
        &request.provenance_sha256,
        approval,
        &["template_insertion", "production_generation"],
    )
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

fn normalized_python_target(raw: &str) -> Result<String, (&'static str, String)> {
    if raw.is_empty() || raw.len() > 768 || path_has_traversal(raw) {
        return Err((
            "path_contract",
            "target path is empty, oversized, or traverses".to_string(),
        ));
    }
    let normalized = normalize_path(raw);
    if normalized.contains("//")
        || normalized.contains(':') && !normalized.starts_with("l:/")
        || normalized.contains(':') && normalized[2..].contains(':')
        || normalized == PYTHON_WRITE_ROOT
        || !normalized.starts_with(&format!("{PYTHON_WRITE_ROOT}/"))
    {
        return Err((
            "python_root_allowlist",
            "target must be below the sandbox/code Python root".to_string(),
        ));
    }
    if !normalized.ends_with(".py") {
        return Err((
            "python_suffix_allowlist",
            "Viv autonomous self-authoring permits only .py source".to_string(),
        ));
    }
    if normalized.contains("/__pycache__/") || normalized.ends_with(".pyc") {
        return Err((
            "python_artifact_denied",
            "compiled Python artifacts are denied".to_string(),
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

fn validate_request(request: &PythonWriteRequest) -> Result<String, (&'static str, String)> {
    if request.process_id != std::process::id() {
        return Err((
            "process_binding",
            "request process_id does not match caller".to_string(),
        ));
    }
    if request.action != PythonWriteAction::WritePython {
        return Err((
            "action_allowlist",
            "only WRITE_PYTHON is supported".to_string(),
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
    let target = normalized_python_target(&request.target_path)?;
    if !valid_hash(&request.parent_sha256) || !valid_hash(&request.content_sha256) {
        return Err((
            "hash_contract",
            "parent and content hashes must be SHA-256".to_string(),
        ));
    }
    if !request.provenance_sha256.is_empty() && !valid_hash(&request.provenance_sha256) {
        return Err((
            "provenance_hash_contract",
            "provenance_sha256 must be empty or a SHA-256 digest".to_string(),
        ));
    }
    if request.content_bytes > MAX_SOURCE_BYTES {
        return Err((
            "resource_ceiling",
            "Python source exceeds the Rust size ceiling".to_string(),
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

fn append_ledger_with_approval(
    verdict: &PythonWriteVerdict,
    approval: Option<&ArchitectApproval>,
) -> bool {
    let path = Path::new(PYTHON_WRITE_LEDGER_PATH);
    let Some(parent) = path.parent() else {
        return false;
    };
    if fs::create_dir_all(parent).is_err() {
        return false;
    }
    let (lock, lock_path) = match acquire_ledger_lock() {
        Some(value) => value,
        None => return false,
    };
    let result = append_ledger_locked(verdict, approval);
    drop(lock);
    let lock_removed = fs::remove_file(&lock_path).is_ok();
    result && lock_removed
}

fn append_ledger_locked(
    verdict: &PythonWriteVerdict,
    approval: Option<&ArchitectApproval>,
) -> bool {
    let path = Path::new(PYTHON_WRITE_LEDGER_PATH);
    let (last_index, previous_hash) = match verified_ledger_head() {
        Some(value) => value,
        None => return false,
    };
    let mut logged = verdict.clone();
    logged.ledger_recorded = true;
    let mut payload = json!({
        "schema_version": "viv_python_write_control_event_v1",
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
    payload["ledger_event_index"] = json!(last_index.saturating_add(1));
    payload["previous_event_sha256"] = json!(previous_hash);
    let Some(hash) = event_hash(&payload) else {
        return false;
    };
    payload["event_sha256"] = json!(hash.clone());
    let Some(serialized) = canonical_json_line(&payload) else {
        return false;
    };
    let Ok(mut file) = OpenOptions::new().create(true).append(true).open(path) else {
        return false;
    };
    if file.write_all(&serialized).is_err() || file.sync_all().is_err() {
        return false;
    }
    matches!(
        verified_ledger_head(),
        Some((index, head)) if index == last_index.saturating_add(1) && head == hash
    )
}

fn append_ledger(verdict: &PythonWriteVerdict) -> bool {
    append_ledger_with_approval(verdict, None)
}

pub fn authorize(raw: &str) -> PythonWriteVerdict {
    let parsed = match parse_request(raw) {
        Ok(request) => request,
        Err(error) => {
            let verdict = empty_verdict(None, &error, "request_schema");
            let mut recorded = verdict.clone();
            recorded.ledger_recorded = append_ledger(&verdict);
            return recorded;
        }
    };
    let target = match validate_request(&parsed) {
        Ok(target) => target,
        Err((rule, reason)) => {
            let verdict = empty_verdict(Some(&parsed), &reason, rule);
            let mut recorded = verdict.clone();
            recorded.ledger_recorded = append_ledger(&verdict);
            return recorded;
        }
    };
    if !AUTONOMOUS_PYTHON_WRITE_ENABLED {
        let verdict = empty_verdict(
            Some(&parsed),
            "Rust Python self-authoring capability is closed at this stage",
            "python_write_capability_closed",
        );
        let mut recorded = verdict.clone();
        recorded.normalized_target_path = target;
        recorded.ledger_recorded = append_ledger(&recorded);
        return recorded;
    }
    let decision_id = sha256_bytes(
        format!(
            "allow:{}:{}:{}:{}",
            parsed.request_id,
            parsed.process_id,
            target,
            now_nanos()
        )
        .as_bytes(),
    )[..32]
        .to_string();
    let mut verdict = PythonWriteVerdict {
        allowed: true,
        disposition: "ALLOW".to_string(),
        reason: "OK".to_string(),
        rule: "python_write_allowlist".to_string(),
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
        autonomous_access: AUTONOMOUS_PYTHON_WRITE_ENABLED,
        ledger_recorded: false,
    };
    verdict.ledger_recorded = append_ledger(&verdict);
    if !verdict.ledger_recorded {
        verdict.allowed = false;
        verdict.disposition = "DENY".to_string();
        verdict.reason = "Python write-control ledger could not be recorded".to_string();
        verdict.rule = "python_write_control_ledger".to_string();
    }
    verdict
}

/// Authorize one production-generation Python write only when a separately
/// supplied Architect approval receipt is valid and bound to the request.
/// This does not open the autonomous writer: `authorize()` remains closed and
/// this function never authorizes pointer adoption.
pub fn authorize_human_approved(raw_request: &str, raw_approval: &str) -> PythonWriteVerdict {
    let parsed = match parse_request(raw_request) {
        Ok(request) => request,
        Err(error) => {
            let verdict = empty_verdict(None, &error, "request_schema");
            let mut recorded = verdict.clone();
            recorded.ledger_recorded = append_ledger(&verdict);
            return recorded;
        }
    };
    let target = match validate_request(&parsed) {
        Ok(target) => target,
        Err((rule, reason)) => {
            let verdict = empty_verdict(Some(&parsed), &reason, rule);
            let mut recorded = verdict.clone();
            recorded.ledger_recorded = append_ledger(&verdict);
            return recorded;
        }
    };
    let approval = match parse_approval(raw_approval) {
        Ok(approval) => approval,
        Err(error) => {
            let verdict = empty_verdict(Some(&parsed), &error, "approval_schema");
            let mut recorded = verdict.clone();
            recorded.normalized_target_path = target;
            recorded.ledger_recorded = append_ledger(&verdict);
            return recorded;
        }
    };
    if let Err((rule, reason)) = validate_approval(&parsed, &approval) {
        let verdict = empty_verdict(Some(&parsed), &reason, rule);
        let mut recorded = verdict.clone();
        recorded.normalized_target_path = target;
        recorded.ledger_recorded = append_ledger(&verdict);
        return recorded;
    }
    let decision_id = sha256_bytes(
        format!(
            "human-approved:{}:{}:{}:{}:{}",
            parsed.request_id,
            parsed.process_id,
            target,
            approval.approval_id,
            now_nanos()
        )
        .as_bytes(),
    )[..32]
        .to_string();
    let mut verdict = PythonWriteVerdict {
        allowed: true,
        disposition: "ALLOW".to_string(),
        reason: "Architect approval verified".to_string(),
        rule: "human_approved_python_write".to_string(),
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
    verdict.ledger_recorded = append_ledger_with_approval(&verdict, Some(&approval));
    if !verdict.ledger_recorded {
        verdict.allowed = false;
        verdict.disposition = "DENY".to_string();
        verdict.reason = "Python write-control ledger could not be recorded".to_string();
        verdict.rule = "python_write_control_ledger".to_string();
    }
    verdict
}

#[cfg(test)]
mod tests {
    use super::*;

    fn request() -> PythonWriteRequest {
        PythonWriteRequest {
            action: PythonWriteAction::WritePython,
            actor: VIV_ACTOR.to_string(),
            operation_id: "python-write-test-1".to_string(),
            request_id: "python-write-request-1".to_string(),
            target_path: "L:/LocalCoder/workspace/aios_rebuild/template_toolbox/sandbox/code/learning_step.py".to_string(),
            parent_sha256: "a".repeat(64),
            content_sha256: "b".repeat(64),
            content_bytes: 128,
            provenance_sha256: "c".repeat(64),
            process_id: std::process::id(),
            master_s_n: 0.8,
            forensic_buffer: "Do I? CPU reviewed the bounded Python proposal.".to_string(),
        }
    }

    fn approved_request() -> PythonWriteRequest {
        let mut value = request();
        value.provenance_sha256 = "d".repeat(64);
        value.master_s_n = 0.8;
        value
    }

    fn approval(proposal_sha256: &str) -> ArchitectApproval {
        let mut value = ArchitectApproval {
            schema_version: "viv_cpu_human_approved_production_adoption_approval_v1".to_string(),
            approver_actor: "ARCHITECT".to_string(),
            approval_id: "architect-test-only".to_string(),
            proposal_sha256: proposal_sha256.to_string(),
            approved_operations: vec![
                "template_insertion".to_string(),
                "production_generation".to_string(),
            ],
            pointer_adoption_approved: false,
            approval_sha256: String::new(),
        };
        value.approval_sha256 = approval_digest(&value);
        value
    }

    #[test]
    fn autonomous_python_capability_is_closed() {
        let verdict = authorize(&serde_json::to_string(&request()).expect("json"));
        assert!(!verdict.allowed);
        assert_eq!(verdict.rule, "python_write_capability_closed");
        assert!(verdict.ledger_recorded);
        assert!(!verdict.autonomous_access);
    }

    #[test]
    fn human_approval_validator_accepts_bound_receipt_without_writing() {
        let request = approved_request();
        let approval = approval(&request.provenance_sha256);
        assert!(validate_request(&request).is_ok());
        assert!(validate_approval(&request, &approval).is_ok());
    }

    #[test]
    fn human_approval_route_rejects_forged_actor_and_bad_binding() {
        let request = approved_request();
        let mut forged = approval(&request.provenance_sha256);
        forged.approver_actor = "MODEL".to_string();
        forged.approval_sha256 = approval_digest(&forged);
        let verdict = authorize_human_approved(
            &serde_json::to_string(&request).expect("request json"),
            &serde_json::to_string(&forged).expect("approval json"),
        );
        assert!(!verdict.allowed);
        assert_eq!(verdict.rule, "approval_actor");

        let mismatched = approval(&"e".repeat(64));
        let verdict = authorize_human_approved(
            &serde_json::to_string(&request).expect("request json"),
            &serde_json::to_string(&mismatched).expect("approval json"),
        );
        assert!(!verdict.allowed);
        assert_eq!(verdict.rule, "approval_proposal_binding");
    }

    #[test]
    fn human_approval_route_keeps_pointer_adoption_separate() {
        let request = approved_request();
        let mut pointer = approval(&request.provenance_sha256);
        pointer.pointer_adoption_approved = true;
        pointer.approval_sha256 = approval_digest(&pointer);
        let verdict = authorize_human_approved(
            &serde_json::to_string(&request).expect("request json"),
            &serde_json::to_string(&pointer).expect("approval json"),
        );
        assert!(!verdict.allowed);
        assert_eq!(verdict.rule, "pointer_second_approval");
    }

    #[test]
    fn non_python_targets_are_denied_before_capability_state() {
        let mut value = request();
        value.target_path =
            "L:/LocalCoder/workspace/aios_rebuild/template_toolbox/sandbox/code/learning_step.json"
                .to_string();
        let verdict = authorize(&serde_json::to_string(&value).expect("json"));
        assert!(!verdict.allowed);
        assert_eq!(verdict.rule, "python_suffix_allowlist");
    }

    #[test]
    fn outside_root_is_denied() {
        let mut value = request();
        value.target_path =
            "L:/LocalCoder/workspace/aios_rebuild/template_toolbox/foundation/lib/learning_step.py"
                .to_string();
        let verdict = authorize(&serde_json::to_string(&value).expect("json"));
        assert!(!verdict.allowed);
        assert_eq!(verdict.rule, "python_root_allowlist");
    }

    #[test]
    fn rust_actor_and_source_are_denied() {
        let mut value = request();
        value.actor = "operator_dashboard".to_string();
        let verdict = authorize(&serde_json::to_string(&value).expect("json"));
        assert!(!verdict.allowed);
        assert_eq!(verdict.rule, "actor_not_allowlisted");
    }

    #[test]
    fn law8_is_required() {
        let mut value = request();
        value.forensic_buffer = "operator reviewed".to_string();
        let verdict = authorize(&serde_json::to_string(&value).expect("json"));
        assert!(!verdict.allowed);
        assert_eq!(verdict.rule, "law8_cognitive_sync");
    }

    #[test]
    fn unknown_fields_are_rejected() {
        let raw = r#"{"action":"WRITE_PYTHON","actor":"viv_autonomous","operation_id":"x","request_id":"y","target_path":"L:/LocalCoder/workspace/aios_rebuild/template_toolbox/sandbox/code/x.py","parent_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","content_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","content_bytes":1,"process_id":1,"master_s_n":0.8,"forensic_buffer":"Do I?","bypass":true}"#;
        let verdict = authorize(raw);
        assert!(!verdict.allowed);
        assert_eq!(verdict.rule, "request_schema");
    }

    #[test]
    fn provenance_hash_is_part_of_the_typed_request() {
        let verdict = authorize(&serde_json::to_string(&request()).expect("json"));
        assert_eq!(verdict.provenance_sha256, "c".repeat(64));
        assert_eq!(verdict.rule, "python_write_capability_closed");
    }

    #[test]
    fn malformed_provenance_hash_is_denied_before_capability_state() {
        let mut value = request();
        value.provenance_sha256 = "not-a-hash".to_string();
        let verdict = authorize(&serde_json::to_string(&value).expect("json"));
        assert!(!verdict.allowed);
        assert_eq!(verdict.rule, "provenance_hash_contract");
    }
}
