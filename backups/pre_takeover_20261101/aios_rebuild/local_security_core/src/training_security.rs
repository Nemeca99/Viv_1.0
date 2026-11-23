//! Deny-by-default training capabilities.
//!
//! This module does not widen the ordinary filesystem governor.  It grants
//! short-lived, process-bound leases for one isolated staging directory and
//! performs the only allowed commit into `models/Training/runs`.

use crate::laws::{effective_dormancy_threshold, TRAINING_SOFT_FLOOR};
use crate::normalize::{normalize_path, path_has_traversal};
use hex::encode as hex_encode;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};
use std::sync::{Mutex, OnceLock};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use windows_sys::Win32::Foundation::LocalFree;
#[cfg(windows)]
use windows_sys::Win32::Foundation::{CloseHandle, INVALID_HANDLE_VALUE};
use windows_sys::Win32::Security::Cryptography::{
    BCryptGenRandom, CryptProtectData, CryptUnprotectData, BCRYPT_USE_SYSTEM_PREFERRED_RNG,
    CRYPTPROTECT_UI_FORBIDDEN, CRYPT_INTEGER_BLOB,
};
#[cfg(windows)]
use windows_sys::Win32::Storage::FileSystem::{
    CreateFileW, GetFileInformationByHandle, MoveFileExW, BY_HANDLE_FILE_INFORMATION, FILE_ATTRIBUTE_NORMAL,
    FILE_FLAG_OPEN_REPARSE_POINT, FILE_READ_ATTRIBUTES, FILE_SHARE_DELETE, FILE_SHARE_READ,
    FILE_SHARE_WRITE, MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH, OPEN_EXISTING,
};

const STAGING_ROOT: &str = "L:/Continue/Viv/sandbox/training_staging";
const RUNS_ROOT: &str = "L:/Continue/Viv/foundation/models/Training/runs";
const INN_STAGING_ROOT: &str = "L:/LocalCoder/workspace/autonomy/learning/neural_candidate_staging";
const INN_RUNS_ROOT: &str = "L:/LocalCoder/workspace/autonomy/learning/neural_runs";
const INN_LEARNING_ROOT: &str = "L:/LocalCoder/workspace/autonomy/learning";
const QUARANTINE_ROOT: &str =
    "L:/Continue/Viv/foundation/artifacts/auto/security_training_quarantine";
const LEDGER_PATH: &str =
    "L:/Continue/Viv/foundation/artifacts/audit/security_training_events.jsonl";
const LEDGER_LOCK_PATH: &str =
    "L:/Continue/Viv/foundation/artifacts/audit/security_training_events.lock";
const STAGE1_REGISTRY_PATH: &str =
    "L:/Continue/Viv/foundation/artifacts/auto/openaster_training_tree/stage1/stage1_registry_v1.json";
const STAGE1_CORPUS_PATH: &str =
    "L:/Continue/Viv/foundation/artifacts/auto/openaster_training_tree/stage1/stage1_judged_v1.jsonl";
const MOUTH_IDENTITY_REGISTRY_PATH: &str =
    "L:/Continue/Viv/foundation/artifacts/auto/openaster_training_tree/stage1_mouth_identity_v1/stage1_mouth_identity_registry_v1.json";
const MOUTH_IDENTITY_CORPUS_PATH: &str =
    "L:/Continue/Viv/foundation/artifacts/auto/openaster_training_tree/stage1_mouth_identity_v1/stage1_mouth_identity_judged_v1.jsonl";
const MOUTH_IDENTITY_V2_REGISTRY_PATH: &str =
    "L:/Continue/Viv/foundation/artifacts/auto/openaster_training_tree/stage1_mouth_identity_v2/stage1_mouth_identity_registry_v1.json";
const MOUTH_IDENTITY_V2_CORPUS_PATH: &str =
    "L:/Continue/Viv/foundation/artifacts/auto/openaster_training_tree/stage1_mouth_identity_v2/stage1_mouth_identity_judged_v1.jsonl";
const MOUTH_IDENTITY_V2_1_REGISTRY_PATH: &str =
    "L:/Continue/Viv/foundation/artifacts/auto/openaster_training_tree/stage1_mouth_identity_v2_1/stage1_mouth_identity_registry_v1.json";
const MOUTH_IDENTITY_V2_1_CORPUS_PATH: &str =
    "L:/Continue/Viv/foundation/artifacts/auto/openaster_training_tree/stage1_mouth_identity_v2_1/stage1_mouth_identity_judged_v1.jsonl";
const PREEXISTING_FROZEN_PATHS: &[&str] = &[
    "L:/Continue/Viv/foundation/artifacts/auto/shadow_judge/holdout_registry.json",
    "L:/Continue/Viv/foundation/artifacts/auto/shadow_judge/holdout_pack.jsonl",
    "L:/Continue/Viv/foundation/artifacts/auto/shadow_judge/deploy_test_registry.json",
    "L:/Continue/Viv/foundation/artifacts/auto/shadow_judge/deploy_test_pack.jsonl",
    "L:/Continue/Viv/foundation/artifacts/auto/openaster_parity/development_registry_v1.json",
    "L:/Continue/Viv/foundation/artifacts/auto/openaster_parity/development_pack_v1.jsonl",
    "L:/Continue/Viv/foundation/artifacts/auto/openaster_parity/multiturn_registry_v1.json",
    "L:/Continue/Viv/foundation/artifacts/auto/openaster_parity/multiturn_pack_v1.json",
    "L:/Continue/Viv/foundation/artifacts/auto/openaster_training_tree/seed_registry_v2.json",
    "L:/Continue/Viv/foundation/artifacts/auto/openaster_training_tree/seed_nodes_v2.jsonl",
];
const MAX_REQUEST_BYTES: usize = 256 * 1024;
const MAX_QUARANTINE_BYTES: usize = 1024 * 1024;
const MAX_INN_RECEIPT_BYTES: usize = 4 * 1024 * 1024;
const MAX_LEASE_SECONDS: u64 = 4 * 60 * 60;
const MAX_VRAM_MIB: u64 = 8192;
const MAX_RAM_MIB: u64 = 28672;
const MAX_DISK_MIB: u64 = 8192;
const MAX_SEQUENCE_CAP: u64 = 384;

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum TrainingAction {
    Ingest,
    Draft,
    Judge,
    Quarantine,
    BeginRun,
    CommitRun,
    BeginInnCandidate,
    CommitInnCandidate,
    PublishInnPointer,
    WriteInnCandidateReceipt,
    Evaluate,
    Freeze,
    Promote,
    Deploy,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct TrainingSecurityRequest {
    pub action: TrainingAction,
    pub stage_id: String,
    pub run_id: String,
    pub model_role: String,
    pub manifest_hash: String,
    pub source_hashes: Vec<String>,
    pub paths: Vec<String>,
    pub artifact_class: String,
    pub master_s_n: f64,
    pub process_id: u32,
    pub max_duration_s: u64,
    pub max_vram_mib: u64,
    pub max_ram_mib: u64,
    pub max_disk_mib: u64,
    pub sequence_cap: u64,
    pub lora_rank: u64,
    #[serde(default)]
    pub body_runtime_permit: Option<String>,
    #[serde(default)]
    pub body_requested_threads: Option<u64>,
}

#[derive(Debug, Clone, Serialize)]
pub struct TrainingSecurityVerdict {
    pub allowed: bool,
    pub disposition: String,
    pub reason: String,
    pub rule: String,
    pub decision_id: String,
    pub policy_version: String,
    pub manifest_hash: String,
    pub normalized_paths: Vec<String>,
    pub lease_token: Option<String>,
    pub staging_root: Option<String>,
    pub final_root: Option<String>,
    pub quarantine_id: Option<String>,
    pub payload: Option<String>,
    pub training_soft_band: bool,
    pub master_s_n: Option<f64>,
    pub training_soft_floor: Option<f64>,
    pub hard_threshold: Option<f64>,
}

#[derive(Debug, Clone, Serialize)]
pub struct LedgerStatus {
    pub ok: bool,
    pub events: usize,
    pub head: String,
    pub error: Option<String>,
    pub policy_version: String,
}

#[derive(Debug, Clone)]
struct Lease {
    token_hash: String,
    binding_hash: String,
    run_id: String,
    stage_id: String,
    manifest_hash: String,
    process_id: u32,
    staging_root: PathBuf,
    final_root: PathBuf,
    expires_at: u64,
    max_disk_bytes: u64,
    lora_rank: u64,
    master_s_n: f64,
    body_requested_threads: Option<u64>,
    inn_candidate: bool,
    consumed: bool,
    committed: bool,
}

#[derive(Debug, Clone)]
struct BodyRuntimePermit {
    process_id: u32,
    expires_at: Instant,
    stability_sn: f64,
    requested_threads: u64,
    run_id: String,
}

#[derive(Default)]
struct SecurityState {
    leases: HashMap<String, Lease>,
    body_runtime_permits: HashMap<String, BodyRuntimePermit>,
    previous_event_hash: String,
}

static STATE: OnceLock<Mutex<SecurityState>> = OnceLock::new();

fn state() -> &'static Mutex<SecurityState> {
    STATE.get_or_init(|| Mutex::new(SecurityState::default()))
}

fn now_epoch() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

fn sha256_bytes(data: &[u8]) -> String {
    hex_encode(Sha256::digest(data))
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct FreezeTarget {
    registry_path: &'static str,
    corpus_path: &'static str,
    stage_id: &'static str,
}

const FREEZE_TARGETS: &[FreezeTarget] = &[
    FreezeTarget {
        registry_path: STAGE1_REGISTRY_PATH,
        corpus_path: STAGE1_CORPUS_PATH,
        stage_id: "evidence_truth",
    },
    FreezeTarget {
        registry_path: MOUTH_IDENTITY_REGISTRY_PATH,
        corpus_path: MOUTH_IDENTITY_CORPUS_PATH,
        stage_id: "mouth_identity",
    },
    FreezeTarget {
        registry_path: MOUTH_IDENTITY_V2_REGISTRY_PATH,
        corpus_path: MOUTH_IDENTITY_V2_CORPUS_PATH,
        stage_id: "mouth_identity",
    },
    FreezeTarget {
        registry_path: MOUTH_IDENTITY_V2_1_REGISTRY_PATH,
        corpus_path: MOUTH_IDENTITY_V2_1_CORPUS_PATH,
        stage_id: "mouth_identity",
    },
];

fn freeze_target_for_registry(normalized: &str) -> Option<FreezeTarget> {
    FREEZE_TARGETS
        .iter()
        .copied()
        .find(|target| normalized == normalize_path(target.registry_path))
}

fn registry_for_frozen_corpus(normalized: &str) -> Option<&'static str> {
    FREEZE_TARGETS
        .iter()
        .find(|target| normalized == normalize_path(target.corpus_path))
        .map(|target| target.registry_path)
}

fn resolve_freeze_target(
    paths: &[String],
    stage_id: &str,
) -> Result<FreezeTarget, (&'static str, String)> {
    if paths.len() != 1 {
        return Err((
            "freeze_target",
            "freeze requires exactly one allowlisted registry target".to_string(),
        ));
    }
    let Some(target) = freeze_target_for_registry(&paths[0]) else {
        return Err((
            "freeze_target",
            "only an exact allowlisted training registry supports create-once freeze".to_string(),
        ));
    };
    if stage_id != target.stage_id {
        return Err((
            "freeze_stage",
            format!("registry target requires stage_id {}", target.stage_id),
        ));
    }
    Ok(target)
}

fn lease_binding_hash(request: &TrainingSecurityRequest) -> String {
    let value = json!({
        "stage_id": request.stage_id,
        "run_id": request.run_id,
        "model_role": request.model_role,
        "manifest_hash": request.manifest_hash,
        "source_hashes": request.source_hashes,
        "paths": request.paths,
        "artifact_class": request.artifact_class,
        "process_id": request.process_id,
        "max_duration_s": request.max_duration_s,
        "max_vram_mib": request.max_vram_mib,
        "max_ram_mib": request.max_ram_mib,
        "max_disk_mib": request.max_disk_mib,
        "sequence_cap": request.sequence_cap,
        "lora_rank": request.lora_rank,
        "body_requested_threads": request.body_requested_threads,
    });
    sha256_bytes(&serde_json::to_vec(&value).unwrap_or_default())
}

fn is_lease_action(action: &TrainingAction) -> bool {
    matches!(action, TrainingAction::BeginRun | TrainingAction::CommitRun
        | TrainingAction::BeginInnCandidate | TrainingAction::CommitInnCandidate)
}

fn lease_roots(request: &TrainingSecurityRequest) -> (&'static str, &'static str) {
    if matches!(request.action, TrainingAction::BeginInnCandidate | TrainingAction::CommitInnCandidate) {
        (INN_STAGING_ROOT, INN_RUNS_ROOT)
    } else {
        (STAGING_ROOT, RUNS_ROOT)
    }
}

fn is_inn_pointer(path: &str) -> bool {
    ["neural_status.json", "farm_corpus_latest.json", "neural_candidate.json"]
        .iter()
        .any(|name| path == normalize_path(&format!("{INN_LEARNING_ROOT}/{name}")))
}

fn inn_receipt_path(run_id: &str) -> PathBuf {
    PathBuf::from(INN_RUNS_ROOT).join(run_id).join("recheck.json")
}

fn parse_inn_receipt(payload: &str) -> Result<Value, String> {
    if payload.is_empty() || payload.len() > MAX_INN_RECEIPT_BYTES {
        return Err("candidate receipt size is invalid".to_string());
    }
    let receipt: Value = serde_json::from_str(payload)
        .map_err(|error| format!("receipt JSON invalid: {error}"))?;
    if !receipt.is_object() {
        return Err("receipt must be a JSON object".to_string());
    }
    let held = receipt.get("body_held").and_then(Value::as_bool) == Some(true)
        && receipt.get("body_gate").is_some_and(Value::is_object)
        && receipt.get("admitted_proposals").and_then(Value::as_bool) == Some(false);
    let complete = held
        || (receipt.get("passed").and_then(Value::as_bool).is_some()
            && receipt.get("original_gate_reproduced").and_then(Value::as_bool).is_some()
            && receipt.get("checkpoint_unchanged").and_then(Value::as_bool).is_some()
            && receipt.get("admitted_proposals").and_then(Value::as_bool).is_some());
    if !complete {
        return Err("receipt omits required verification outcome fields".to_string());
    }
    Ok(receipt)
}

fn create_inn_receipt_file(path: &Path, payload: &str) -> Result<(), String> {
    if path.exists() {
        return Err("verification receipt already exists".to_string());
    }
    let receipt_hash = sha256_bytes(payload.as_bytes());
    let pending = path.with_file_name(format!(".recheck_{}.pending", &receipt_hash[..16]));
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&pending)
        .map_err(|error| error.to_string())?;
    if let Err(error) = file.write_all(payload.as_bytes()).and_then(|_| file.sync_all()) {
        drop(file);
        let _ = fs::remove_file(&pending);
        return Err(error.to_string());
    }
    drop(file);
    if let Err(error) = fs::rename(&pending, path) {
        let _ = fs::remove_file(&pending);
        return Err(error.to_string());
    }
    Ok(())
}

fn valid_hash(value: &str) -> bool {
    value.len() == 64 && value.bytes().all(|byte| byte.is_ascii_hexdigit())
}

fn safe_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'))
        && !value.contains("..")
}

fn within_root(path: &str, root: &str) -> bool {
    path == root
        || path
            .strip_prefix(root)
            .is_some_and(|suffix| suffix.starts_with('/'))
}

fn require_plain_root(path: &Path) -> Result<(), String> {
    if !path.is_dir() {
        return Err(format!("trusted root missing: {}", path.display()));
    }
    if is_reparse(path)? {
        return Err(format!(
            "trusted root is a reparse point: {}",
            path.display()
        ));
    }
    Ok(())
}

fn deny(
    request: Option<&TrainingSecurityRequest>,
    rule: &str,
    reason: impl Into<String>,
) -> TrainingSecurityVerdict {
    let manifest = request.map(|r| r.manifest_hash.clone()).unwrap_or_default();
    let hard_threshold = effective_dormancy_threshold();
    let training_soft_band = request.is_some_and(|r| {
        matches!(
            r.action,
            TrainingAction::BeginRun | TrainingAction::CommitRun | TrainingAction::BeginInnCandidate | TrainingAction::CommitInnCandidate
        ) && r.master_s_n.is_finite()
            && r.master_s_n >= TRAINING_SOFT_FLOOR
            && r.master_s_n < hard_threshold
    });
    let reason_string = reason.into();
    let decision_id =
        random_hex(16).unwrap_or_else(|_| sha256_bytes(reason_string.as_bytes())[..32].to_string());
    let verdict = TrainingSecurityVerdict {
        allowed: false,
        disposition: "DENY".to_string(),
        reason: reason_string,
        rule: rule.to_string(),
        decision_id,
        policy_version: env!("CARGO_PKG_VERSION").to_string(),
        manifest_hash: manifest,
        normalized_paths: vec![],
        lease_token: None,
        staging_root: None,
        final_root: None,
        quarantine_id: None,
        payload: None,
        training_soft_band,
        master_s_n: request.map(|r| r.master_s_n),
        training_soft_floor: request.map(|_| TRAINING_SOFT_FLOOR),
        hard_threshold: request.map(|_| hard_threshold),
    };
    append_ledger("deny", &verdict, json!({}));
    verdict
}

fn allow(
    request: &TrainingSecurityRequest,
    rule: &str,
    normalized_paths: Vec<String>,
) -> TrainingSecurityVerdict {
    let hard_threshold = effective_dormancy_threshold();
    let training_soft_band = matches!(
        request.action,
        TrainingAction::BeginRun | TrainingAction::CommitRun | TrainingAction::BeginInnCandidate | TrainingAction::CommitInnCandidate
    ) && request.master_s_n.is_finite()
        && request.master_s_n >= TRAINING_SOFT_FLOOR
        && request.master_s_n < hard_threshold;
    let verdict = TrainingSecurityVerdict {
        allowed: true,
        disposition: "ALLOW".to_string(),
        reason: "OK".to_string(),
        rule: rule.to_string(),
        decision_id: random_hex(16)
            .unwrap_or_else(|_| sha256_bytes(request.manifest_hash.as_bytes())[..32].to_string()),
        policy_version: env!("CARGO_PKG_VERSION").to_string(),
        manifest_hash: request.manifest_hash.clone(),
        normalized_paths,
        lease_token: None,
        staging_root: None,
        final_root: None,
        quarantine_id: None,
        payload: None,
        training_soft_band,
        master_s_n: Some(request.master_s_n),
        training_soft_floor: Some(TRAINING_SOFT_FLOOR),
        hard_threshold: Some(hard_threshold),
    };
    append_ledger(
        "allow",
        &verdict,
        json!({"action": request.action, "run_id": request.run_id}),
    );
    verdict
}

fn parse_request(raw: &str) -> Result<TrainingSecurityRequest, String> {
    if raw.is_empty() || raw.len() > MAX_REQUEST_BYTES {
        return Err("request_size_invalid".to_string());
    }
    let mut deserializer = serde_json::Deserializer::from_str(raw);
    let request = TrainingSecurityRequest::deserialize(&mut deserializer)
        .map_err(|error| format!("request_schema:{error}"))?;
    deserializer
        .end()
        .map_err(|error| format!("request_trailing_data:{error}"))?;
    Ok(request)
}

fn validate_request(
    request: &TrainingSecurityRequest,
) -> Result<Vec<String>, (&'static str, String)> {
    if let Err(error) = verify_ledger_file(Path::new(LEDGER_PATH)) {
        return Err(("ledger_integrity", error));
    }
    if request.action == TrainingAction::Deploy {
        return Err((
            "training_deploy_disabled",
            "DEPLOY is disabled for this milestone".to_string(),
        ));
    }
    if request.process_id != std::process::id() {
        return Err((
            "process_binding",
            "request process_id does not match caller".to_string(),
        ));
    }
    let hard_threshold = effective_dormancy_threshold();
    let stability_floor = if request.action == TrainingAction::WriteInnCandidateReceipt {
        0.0
    } else if matches!(
        request.action,
        TrainingAction::BeginRun | TrainingAction::CommitRun | TrainingAction::BeginInnCandidate | TrainingAction::CommitInnCandidate
    ) {
        TRAINING_SOFT_FLOOR
    } else {
        hard_threshold
    };
    if !request.master_s_n.is_finite() || request.master_s_n < stability_floor {
        return Err((
            "law5_stability",
            format!(
                "Master S_n {:.4} is below {:.4}",
                request.master_s_n, stability_floor
            ),
        ));
    }
    if !safe_id(&request.run_id) || !safe_id(&request.stage_id) {
        return Err(("identifier", "run_id or stage_id is unsafe".to_string()));
    }
    if !valid_hash(&request.manifest_hash)
        || request.source_hashes.iter().any(|hash| !valid_hash(hash))
    {
        return Err((
            "hash_contract",
            "manifest/source hash is invalid".to_string(),
        ));
    }
    if !matches!(
        request.model_role.as_str(),
        "qwen_teacher"
            | "openaster_target"
            | "parity_mouth_eval"
            | "cpu_semantic_sensor"
            | "deterministic_authority"
            | "artifact_controller"
            | "inn_candidate_trainer"
            | "inn_candidate_verifier"
    ) {
        return Err(("model_role", "model role is not allowlisted".to_string()));
    }
    if request.max_duration_s == 0
        || request.max_duration_s > MAX_LEASE_SECONDS
        || request.max_vram_mib > MAX_VRAM_MIB
        || request.max_ram_mib > MAX_RAM_MIB
        || request.max_disk_mib == 0
        || request.max_disk_mib > MAX_DISK_MIB
        || request.sequence_cap == 0
        || request.sequence_cap > MAX_SEQUENCE_CAP
        || request.lora_rank > 16
    {
        return Err((
            "resource_ceiling",
            "requested resource ceiling is invalid".to_string(),
        ));
    }
    if !matches!(
        request.artifact_class.as_str(),
        "curriculum_record"
            | "draft_set"
            | "judge_record"
            | "training_evidence"
            | "lora_adapter"
            | "evaluation_report"
            | "candidate_pointer"
            | "inn_candidate_bundle"
            | "inn_candidate_pointer"
            | "inn_candidate_receipt"
            | "encrypted_quarantine"
    ) {
        return Err((
            "artifact_class",
            "artifact class is not allowlisted".to_string(),
        ));
    }
    let capability_ok = match request.action {
        TrainingAction::Ingest => {
            request.artifact_class == "curriculum_record"
                && matches!(
                    request.model_role.as_str(),
                    "artifact_controller" | "deterministic_authority"
                )
        }
        TrainingAction::Draft => {
            request.artifact_class == "draft_set" && request.model_role == "qwen_teacher"
        }
        TrainingAction::Judge => {
            request.artifact_class == "judge_record"
                && matches!(
                    request.model_role.as_str(),
                    "cpu_semantic_sensor" | "deterministic_authority"
                )
        }
        TrainingAction::Quarantine => {
            request.artifact_class == "encrypted_quarantine"
                && request.model_role == "deterministic_authority"
        }
        TrainingAction::BeginRun | TrainingAction::CommitRun => {
            (request.artifact_class == "lora_adapter" && request.model_role == "openaster_target")
                || (request.artifact_class == "draft_set" && request.model_role == "qwen_teacher")
        }
        TrainingAction::BeginInnCandidate | TrainingAction::CommitInnCandidate => {
            request.artifact_class == "inn_candidate_bundle"
                && request.model_role == "inn_candidate_trainer"
                && request.stage_id == "inn_candidate"
        }
        TrainingAction::PublishInnPointer => {
            request.artifact_class == "inn_candidate_pointer"
                && request.model_role == "inn_candidate_trainer"
                && request.stage_id == "inn_candidate"
        }
        TrainingAction::WriteInnCandidateReceipt => {
            request.artifact_class == "inn_candidate_receipt"
                && request.model_role == "inn_candidate_verifier"
                && request.stage_id == "inn_candidate"
        }
        TrainingAction::Evaluate => {
            matches!(
                request.artifact_class.as_str(),
                "training_evidence" | "evaluation_report" | "judge_record"
            ) && matches!(
                request.model_role.as_str(),
                "qwen_teacher"
                    | "openaster_target"
                    | "parity_mouth_eval"
                    | "deterministic_authority"
                    | "artifact_controller"
            )
        }
        TrainingAction::Freeze => {
            request.artifact_class == "training_evidence"
                && request.model_role == "deterministic_authority"
        }
        TrainingAction::Promote => {
            request.artifact_class == "candidate_pointer"
                && request.model_role == "deterministic_authority"
        }
        TrainingAction::Deploy => false,
    };
    if !capability_ok {
        return Err((
            "capability_matrix",
            "action, model role, and artifact class are not an approved combination".to_string(),
        ));
    }
    let mut paths = Vec::new();
    for raw in &request.paths {
        if raw.len() > 512
            || path_has_traversal(raw)
            || raw.contains(':') && raw.matches(':').count() > 1
        {
            return Err(("path_contract", format!("unsafe path: {raw}")));
        }
        let normalized = normalize_path(raw);
        let allowed = match request.action {
            TrainingAction::BeginInnCandidate | TrainingAction::CommitInnCandidate => {
                within_root(&normalized, &normalize_path(INN_STAGING_ROOT))
                    || within_root(&normalized, &normalize_path(INN_RUNS_ROOT))
            }
            TrainingAction::PublishInnPointer => is_inn_pointer(&normalized),
            TrainingAction::WriteInnCandidateReceipt => {
                normalized == normalize_path(&inn_receipt_path(&request.run_id).to_string_lossy())
            }
            _ => {
                within_root(&normalized, &normalize_path(STAGING_ROOT))
                    || within_root(&normalized, &normalize_path(RUNS_ROOT))
                    || within_root(&normalized, &normalize_path(QUARANTINE_ROOT))
                    || within_root(&normalized, "l:/continue/viv/foundation/artifacts")
            }
        };
        if !allowed {
            return Err((
                "path_contract",
                format!("path outside training roots: {normalized}"),
            ));
        }
        if normalized == normalize_path(LEDGER_PATH) {
            return Err((
                "ledger_protected",
                "the training ledger cannot authorize its own overwrite".to_string(),
            ));
        }
        if PREEXISTING_FROZEN_PATHS
            .iter()
            .any(|path| normalized == normalize_path(path))
        {
            return Err((
                "preexisting_frozen_artifact",
                "frozen evaluation or seed artifact is immutable in this milestone".to_string(),
            ));
        }
        if freeze_target_for_registry(&normalized).is_some()
            && request.action != TrainingAction::Freeze
        {
            return Err((
                "frozen_registry",
                "training registry is create-once through FREEZE".to_string(),
            ));
        }
        if let Some(registry_path) = registry_for_frozen_corpus(&normalized) {
            if Path::new(registry_path).exists() {
                return Err((
                    "frozen_corpus",
                    "training corpus is immutable after registry freeze".to_string(),
                ));
            }
        }
        if !matches!(
            request.action,
            TrainingAction::BeginRun | TrainingAction::CommitRun | TrainingAction::BeginInnCandidate | TrainingAction::CommitInnCandidate
        ) {
            let extension = Path::new(&normalized)
                .extension()
                .and_then(|value| value.to_str())
                .unwrap_or("");
            if !matches!(extension, "json" | "jsonl" | "md" | "log") {
                return Err((
                    "artifact_extension",
                    format!("typed training artifact extension denied: {extension}"),
                ));
            }
        }
        paths.push(normalized);
    }
    Ok(paths)
}

pub fn authorize(raw: &str) -> TrainingSecurityVerdict {
    let request = match parse_request(raw) {
        Ok(request) => request,
        Err(error) => return deny(None, "request_schema", error),
    };
    if is_lease_action(&request.action) {
        return deny(
            Some(&request),
            "lease",
            "run lifecycle actions require the dedicated lease API",
        );
    }
    if request.action == TrainingAction::WriteInnCandidateReceipt {
        return deny(
            Some(&request),
            "receipt_api_required",
            "candidate verification receipts require the create-only Rust writer",
        );
    }
    match validate_request(&request) {
        Ok(paths) => allow(&request, "training_authorize", paths),
        Err((rule, reason)) => deny(Some(&request), rule, reason),
    }
}

pub fn write_inn_candidate_receipt(raw: &str, payload: &str) -> TrainingSecurityVerdict {
    let request = match parse_request(raw) {
        Ok(request) => request,
        Err(error) => return deny(None, "request_schema", error),
    };
    if request.action != TrainingAction::WriteInnCandidateReceipt {
        return deny(Some(&request), "action_contract", "WRITE_INN_CANDIDATE_RECEIPT required");
    }
    let paths = match validate_request(&request) {
        Ok(paths) => paths,
        Err((rule, reason)) => return deny(Some(&request), rule, reason),
    };
    if paths.len() != 1
        || paths[0] != normalize_path(&inn_receipt_path(&request.run_id).to_string_lossy())
    {
        return deny(Some(&request), "receipt_path", "receipt target must be the exact run recheck.json");
    }
    if sha256_bytes(payload.as_bytes()) != request.manifest_hash {
        return deny(Some(&request), "receipt_hash", "receipt payload does not match its hash");
    }
    if let Err(error) = parse_inn_receipt(payload) {
        return deny(Some(&request), "receipt_schema", error);
    }
    if request.source_hashes.len() != 2 {
        return deny(Some(&request), "receipt_sources", "receipt must bind candidate and evaluation hashes");
    }
    let run_root = PathBuf::from(INN_RUNS_ROOT).join(&request.run_id);
    if let Err(error) = require_plain_root(&run_root) {
        return deny(Some(&request), "receipt_run_root", error);
    }
    let pointer_path = Path::new(INN_LEARNING_ROOT).join("neural_candidate.json");
    if !pointer_path.is_file()
        || is_reparse(&pointer_path).unwrap_or(true)
        || hard_link_count(&pointer_path).unwrap_or(0) != 1
    {
        return deny(Some(&request), "receipt_candidate_pointer", "candidate pointer is not a plain single-link file");
    }
    let pointer_raw = match fs::read_to_string(&pointer_path) {
        Ok(value) => value,
        Err(error) => return deny(Some(&request), "receipt_candidate_pointer", error.to_string()),
    };
    let pointer: Value = match serde_json::from_str(&pointer_raw) {
        Ok(value) => value,
        Err(error) => return deny(Some(&request), "receipt_candidate_pointer", error.to_string()),
    };
    let candidate_path = pointer.get("run").and_then(Value::as_str).unwrap_or_default();
    let expected_run = run_root.to_string_lossy();
    if normalize_path(candidate_path) != normalize_path(&expected_run)
        || pointer.get("engine_sha256").and_then(Value::as_str) != Some(request.source_hashes[0].as_str())
        || pointer.get("evaluation_sha256").and_then(Value::as_str) != Some(request.source_hashes[1].as_str())
    {
        return deny(Some(&request), "receipt_candidate_binding", "candidate pointer does not bind this passing run");
    }
    for (name, expected_hash) in [
        ("engine.pt", request.source_hashes[0].as_str()),
        ("evaluation.json", request.source_hashes[1].as_str()),
    ] {
        let file_path = run_root.join(name);
        if !file_path.is_file() || is_reparse(&file_path).unwrap_or(true) || hard_link_count(&file_path).unwrap_or(0) != 1 {
            return deny(Some(&request), "receipt_candidate_file", format!("candidate file is not a plain single-link file: {name}"));
        }
        match hash_file(&file_path) {
            Ok(actual) if actual == expected_hash => {}
            Ok(_) => return deny(Some(&request), "receipt_candidate_hash", format!("candidate file hash mismatch: {name}")),
            Err(error) => return deny(Some(&request), "receipt_candidate_file", error),
        }
    }
    let path = inn_receipt_path(&request.run_id);
    if let Some(parent) = path.parent() {
        if let Err(error) = require_plain_root(parent) {
            return deny(Some(&request), "receipt_parent", error);
        }
    }
    if let Err(error) = create_inn_receipt_file(&path, payload) {
        return deny(Some(&request), "receipt_create", error);
    }
    let verdict = allow(&request, "inn_candidate_receipt_create", paths);
    append_ledger("inn_candidate_receipt", &verdict, json!({
        "run_id": request.run_id,
        "receipt_sha256": request.manifest_hash,
        "candidate_sha256": request.source_hashes[0],
        "evaluation_sha256": request.source_hashes[1]
    }));
    verdict
}

pub fn freeze_registry(raw: &str, payload: &str) -> TrainingSecurityVerdict {
    let request = match parse_request(raw) {
        Ok(request) => request,
        Err(error) => return deny(None, "request_schema", error),
    };
    if request.action != TrainingAction::Freeze {
        return deny(Some(&request), "action_contract", "FREEZE required");
    }
    let paths = match validate_request(&request) {
        Ok(paths) => paths,
        Err((rule, reason)) => return deny(Some(&request), rule, reason),
    };
    let target = match resolve_freeze_target(&paths, &request.stage_id) {
        Ok(target) => target,
        Err((rule, reason)) => return deny(Some(&request), rule, reason),
    };
    if payload.is_empty() || payload.len() > 4 * 1024 * 1024 {
        return deny(
            Some(&request),
            "freeze_payload",
            "freeze payload size invalid",
        );
    }
    if sha256_bytes(payload.as_bytes()) != request.manifest_hash {
        return deny(
            Some(&request),
            "freeze_manifest",
            "freeze payload does not match manifest hash",
        );
    }
    let payload_value = match serde_json::from_str::<Value>(payload) {
        Ok(value) => value,
        Err(_) => {
            return deny(
                Some(&request),
                "freeze_payload",
                "freeze payload is not valid JSON",
            )
        }
    };
    if payload_value.get("stage_id").and_then(Value::as_str) != Some(target.stage_id) {
        return deny(
            Some(&request),
            "freeze_stage",
            "freeze payload stage_id does not match the allowlisted registry",
        );
    }
    let corpus = Path::new(target.corpus_path);
    let corpus_bytes = match fs::read(corpus) {
        Ok(bytes) => bytes,
        Err(error) => {
            return deny(
                Some(&request),
                "freeze_corpus",
                format!("allowlisted judged corpus is unavailable: {error}"),
            )
        }
    };
    let corpus_sha256 = sha256_bytes(&corpus_bytes);
    if payload_value.get("corpus_sha256").and_then(Value::as_str) != Some(corpus_sha256.as_str()) {
        return deny(
            Some(&request),
            "freeze_corpus",
            "freeze payload corpus_sha256 does not match the exact allowlisted judged corpus",
        );
    }
    let path = Path::new(target.registry_path);
    if let Some(parent) = path.parent() {
        if let Err(error) = fs::create_dir_all(parent) {
            return deny(Some(&request), "freeze_parent", error.to_string());
        }
        if let Err(error) = require_plain_root(parent) {
            return deny(Some(&request), "trusted_root", error);
        }
    }
    let mut file = match OpenOptions::new().create_new(true).write(true).open(path) {
        Ok(file) => file,
        Err(error) => return deny(Some(&request), "freeze_collision", error.to_string()),
    };
    if let Err(error) = file
        .write_all(payload.as_bytes())
        .and_then(|_| file.sync_all())
    {
        return deny(Some(&request), "freeze_write", error.to_string());
    }
    let verdict = allow(&request, "training_registry_freeze", paths);
    append_ledger(
        "registry_freeze",
        &verdict,
        json!({
            "path": target.registry_path,
            "corpus_path": target.corpus_path,
            "corpus_sha256": corpus_sha256,
            "stage_id": target.stage_id,
            "bytes": payload.len()
        }),
    );
    verdict
}

pub fn begin_lease(raw: &str) -> TrainingSecurityVerdict {
    let request = match parse_request(raw) {
        Ok(request) => request,
        Err(error) => return deny(None, "request_schema", error),
    };
    if !matches!(request.action, TrainingAction::BeginRun | TrainingAction::BeginInnCandidate) {
        return deny(Some(&request), "action_contract", "BEGIN_RUN or BEGIN_INN_CANDIDATE required");
    }
    let paths = match validate_request(&request) {
        Ok(paths) => paths,
        Err((rule, reason)) => return deny(Some(&request), rule, reason),
    };
    let (staging_root, runs_root) = lease_roots(&request);
    let staging = PathBuf::from(staging_root).join(&request.run_id);
    let final_root = PathBuf::from(runs_root).join(&request.run_id);
    let expected_paths = vec![
        normalize_path(&staging.to_string_lossy()),
        normalize_path(&final_root.to_string_lossy()),
    ];
    if paths != expected_paths {
        return deny(
            Some(&request),
            "lease_path_binding",
            "BEGIN_RUN paths must be the exact staging and final roots",
        );
    }
    if staging.exists() || final_root.exists() {
        return deny(
            Some(&request),
            "run_collision",
            "staging or final run already exists",
        );
    }
    if request.action == TrainingAction::BeginInnCandidate {
        if let Err(error) = require_body_runtime_permit(&request) {
            return deny(Some(&request), "body_runtime_permit", error);
        }
    }
    if let Err(error) = fs::create_dir_all(Path::new(staging_root)) {
        return deny(Some(&request), "staging_create", error.to_string());
    }
    if let Err(error) = require_plain_root(Path::new(staging_root)) {
        return deny(Some(&request), "trusted_root", error);
    }
    if let Err(error) = fs::create_dir(&staging) {
        return deny(Some(&request), "staging_create", error.to_string());
    }
    let token = match random_hex(32) {
        Ok(token) => token,
        Err(error) => {
            let _ = fs::remove_dir(&staging);
            return deny(Some(&request), "rng", error);
        }
    };
    let token_hash = sha256_bytes(token.as_bytes());
    let lease = Lease {
        token_hash: token_hash.clone(),
        binding_hash: lease_binding_hash(&request),
        run_id: request.run_id.clone(),
        stage_id: request.stage_id.clone(),
        manifest_hash: request.manifest_hash.clone(),
        process_id: request.process_id,
        staging_root: staging.clone(),
        final_root: final_root.clone(),
        expires_at: now_epoch() + request.max_duration_s,
        max_disk_bytes: request.max_disk_mib * 1024 * 1024,
        lora_rank: request.lora_rank,
        master_s_n: request.master_s_n,
        body_requested_threads: request.body_requested_threads,
        inn_candidate: request.action == TrainingAction::BeginInnCandidate,
        consumed: false,
        committed: false,
    };
    state()
        .lock()
        .expect("security state poisoned")
        .leases
        .insert(token_hash.clone(), lease);
    let mut verdict = allow(&request, "training_lease_begin", paths);
    verdict.lease_token = Some(token);
    verdict.staging_root = Some(staging.to_string_lossy().replace('\\', "/"));
    verdict.final_root = Some(final_root.to_string_lossy().replace('\\', "/"));
    append_ledger(
        "lease_begin",
        &verdict,
        json!({"token_hash": token_hash, "expires_at": now_epoch() + request.max_duration_s}),
    );
    verdict
}

pub fn issue_body_runtime_permit(stability_sn: f64, sensor_age_seconds: f64, requested_threads: u64, run_id: &str) -> Result<String, String> {
    if !stability_sn.is_finite() || stability_sn < TRAINING_SOFT_FLOOR {
        return Err("body runtime stability is below the INN lease floor".to_string());
    }
    if !sensor_age_seconds.is_finite() || !(0.0..15.0).contains(&sensor_age_seconds) {
        return Err("body runtime sensor sample is stale or unavailable".to_string());
    }
    if !(1..=4).contains(&requested_threads) {
        return Err("body runtime thread budget is outside policy".to_string());
    }
    if !safe_id(run_id) {
        return Err("body runtime permit requires a safe candidate run id".to_string());
    }
    let token = random_hex(32)?;
    let token_hash = sha256_bytes(token.as_bytes());
    let permit = BodyRuntimePermit {
        process_id: std::process::id(),
        expires_at: Instant::now() + Duration::from_secs_f64(15.0 - sensor_age_seconds),
        stability_sn,
        requested_threads,
        run_id: run_id.to_string(),
    };
    let mut guard = state().lock().map_err(|_| "security state poisoned".to_string())?;
    let now = Instant::now();
    guard.body_runtime_permits.retain(|_, issued| issued.expires_at >= now);
    guard.body_runtime_permits.insert(token_hash, permit);
    Ok(token)
}

fn consume_body_runtime_permit(token: &str, request: &TrainingSecurityRequest) -> Result<(), String> {
    let token_hash = sha256_bytes(token.as_bytes());
    let mut guard = state().lock().map_err(|_| "security state poisoned".to_string())?;
    let permit = guard.body_runtime_permits.get(&token_hash)
        .ok_or_else(|| "unknown, expired, or already consumed body permit".to_string())?;
    if permit.process_id != std::process::id()
        || permit.process_id != request.process_id
        || permit.expires_at < Instant::now()
        || (permit.stability_sn - request.master_s_n).abs() > f64::EPSILON {
        guard.body_runtime_permits.remove(&token_hash);
        return Err("body permit expired or does not match process/stability".to_string());
    }
    if request.body_requested_threads != Some(permit.requested_threads) {
        guard.body_runtime_permits.remove(&token_hash);
        return Err("body permit does not match requested thread budget".to_string());
    }
    if request.run_id != permit.run_id {
        guard.body_runtime_permits.remove(&token_hash);
        return Err("body permit does not match candidate run id".to_string());
    }
    guard.body_runtime_permits.remove(&token_hash);
    Ok(())
}

fn require_body_runtime_permit(request: &TrainingSecurityRequest) -> Result<(), String> {
    if request.action != TrainingAction::BeginInnCandidate {
        return Ok(());
    }
    let permit = request.body_runtime_permit.as_deref()
        .ok_or_else(|| "fresh Rust body allow permit required for INN candidate lease".to_string())?;
    consume_body_runtime_permit(permit, request)
}

pub fn commit_lease(token: &str, raw: &str) -> TrainingSecurityVerdict {
    let request = match parse_request(raw) {
        Ok(request) => request,
        Err(error) => return deny(None, "request_schema", error),
    };
    if !matches!(request.action, TrainingAction::CommitRun | TrainingAction::CommitInnCandidate) {
        return deny(Some(&request), "action_contract", "COMMIT_RUN or COMMIT_INN_CANDIDATE required");
    }
    if let Err((rule, reason)) = validate_request(&request) {
        return deny(Some(&request), rule, reason);
    }
    let token_hash = sha256_bytes(token.as_bytes());
    let presented_binding_hash = lease_binding_hash(&request);
    let lease = {
        let mut guard = state().lock().expect("security state poisoned");
        match guard.leases.get_mut(&token_hash) {
            None => Err("unknown or replayed lease"),
            Some(lease)
                if lease.consumed
                    || lease.expires_at < now_epoch()
                    || lease.process_id != std::process::id()
                    || lease.run_id != request.run_id
                    || lease.stage_id != request.stage_id
                    || lease.manifest_hash != request.manifest_hash
                    || lease.token_hash != token_hash =>
            {
                lease.consumed = true;
                Err("expired, consumed, or mismatched lease")
            }
            Some(lease) if lease.inn_candidate != (request.action == TrainingAction::CommitInnCandidate) => {
                lease.consumed = true;
                Err("lease runtime family mismatch")
            }
            Some(lease) if lease.binding_hash != presented_binding_hash => {
                lease.consumed = true;
                Err("lease policy binding mismatch")
            }
            Some(lease) => {
                lease.consumed = true;
                Ok(lease.clone())
            }
        }
    };
    let lease = match lease {
        Ok(lease) => lease,
        Err(error) => return deny(Some(&request), "lease", error),
    };
    let inventory =
        match inspect_staging(&lease.staging_root, lease.max_disk_bytes, lease.lora_rank, lease.inn_candidate, false) {
            Ok(inventory) => inventory,
            Err(error) => return deny(Some(&request), "staging_inspection", error),
        };
    if lease.inn_candidate {
        if let Err(error) = validate_inn_body_gate_receipt(
            &lease.staging_root,
            &lease.run_id,
            lease.master_s_n,
            lease.body_requested_threads,
        ) {
            return deny(Some(&request), "body_gate_receipt", error);
        }
    }
    let has_adapter = inventory.iter().any(|entry| {
        entry
            .get("path")
            .and_then(Value::as_str)
            .is_some_and(|path| path.ends_with(".safetensors"))
    });
    if request.artifact_class == "lora_adapter" && !has_adapter {
        return deny(
            Some(&request),
            "adapter_required",
            "LoRA adapter lease contains no safetensors",
        );
    }
    if request.artifact_class != "lora_adapter" && has_adapter {
        return deny(
            Some(&request),
            "artifact_confusion",
            "non-adapter lease may not commit safetensors",
        );
    }
    if lease.final_root.exists() {
        return deny(
            Some(&request),
            "run_collision",
            "final run appeared before commit",
        );
    }
    if let Some(parent) = lease.final_root.parent() {
        if let Err(error) = fs::create_dir_all(parent) {
            return deny(Some(&request), "commit_parent", error.to_string());
        }
        if let Err(error) = require_plain_root(parent) {
            return deny(Some(&request), "trusted_root", error);
        }
    }
    let pending = lease
        .final_root
        .parent()
        .unwrap_or(Path::new(RUNS_ROOT))
        .join(format!(
            ".security_pending_{}_{}",
            lease.run_id,
            &token_hash[..12]
        ));
    if pending.exists() {
        return deny(
            Some(&request),
            "pending_collision",
            "pending commit path already exists",
        );
    }
    if let Err(error) = fs::rename(&lease.staging_root, &pending) {
        return deny(Some(&request), "atomic_stage", error.to_string());
    }
    let post_inventory = match inspect_staging(&pending, lease.max_disk_bytes, lease.lora_rank, lease.inn_candidate, false) {
        Ok(inventory) => inventory,
        Err(error) => return deny(Some(&request), "post_move_inspection", error),
    };
    if inventory != post_inventory {
        return deny(Some(&request), "toctou", "inventory changed during commit");
    }
    if let Err(error) = fs::rename(&pending, &lease.final_root) {
        return deny(Some(&request), "atomic_commit", error.to_string());
    }
    if lease.inn_candidate {
        let mut guard = match state().lock() {
            Ok(guard) => guard,
            Err(_) => return deny(Some(&request), "lease_state", "security state poisoned after candidate commit"),
        };
        let Some(stored) = guard.leases.get_mut(&token_hash) else {
            return deny(Some(&request), "lease_state", "committed candidate lease record missing");
        };
        stored.committed = true;
    }
    let mut verdict = allow(
        &request,
        "training_lease_commit",
        vec![lease.final_root.to_string_lossy().replace('\\', "/")],
    );
    verdict.final_root = Some(lease.final_root.to_string_lossy().replace('\\', "/"));
    append_ledger("lease_commit", &verdict, json!({"inventory": inventory}));
    verdict
}

pub fn quarantine(token: &str, record_id: &str, plaintext: &str) -> TrainingSecurityVerdict {
    if !safe_id(record_id) || plaintext.is_empty() || plaintext.len() > MAX_QUARANTINE_BYTES {
        return deny(None, "quarantine_contract", "record id or payload invalid");
    }
    let lease = match active_lease(token) {
        Ok(lease) => lease,
        Err(error) => return deny(None, "lease", error),
    };
    let ciphertext = match dpapi_protect(plaintext.as_bytes(), lease.manifest_hash.as_bytes()) {
        Ok(data) => data,
        Err(error) => return deny(None, "dpapi", error),
    };
    let directory = PathBuf::from(QUARANTINE_ROOT).join(&lease.run_id);
    if let Err(error) = fs::create_dir_all(Path::new(QUARANTINE_ROOT)) {
        return deny(None, "quarantine_write", error.to_string());
    }
    if let Err(error) = require_plain_root(Path::new(QUARANTINE_ROOT)) {
        return deny(None, "trusted_root", error);
    }
    if let Err(error) = fs::create_dir(&directory) {
        if error.kind() != std::io::ErrorKind::AlreadyExists {
            return deny(None, "quarantine_write", error.to_string());
        }
    }
    if let Err(error) = require_plain_root(&directory) {
        return deny(None, "quarantine_write", error.to_string());
    }
    let path = directory.join(format!("{record_id}.dpapi"));
    let mut file = match OpenOptions::new().create_new(true).write(true).open(&path) {
        Ok(file) => file,
        Err(error) => return deny(None, "quarantine_write", error.to_string()),
    };
    if let Err(error) = file.write_all(&ciphertext).and_then(|_| file.sync_all()) {
        return deny(None, "quarantine_write", error.to_string());
    }
    let verdict = TrainingSecurityVerdict {
        allowed: true,
        disposition: "QUARANTINE".to_string(),
        reason: "encrypted_training_only".to_string(),
        rule: "dpapi_current_user".to_string(),
        decision_id: random_hex(16).unwrap_or_default(),
        policy_version: env!("CARGO_PKG_VERSION").to_string(),
        manifest_hash: lease.manifest_hash,
        normalized_paths: vec![path.to_string_lossy().replace('\\', "/")],
        lease_token: None,
        staging_root: None,
        final_root: None,
        quarantine_id: Some(record_id.to_string()),
        payload: None,
        training_soft_band: false,
        master_s_n: None,
        training_soft_floor: None,
        hard_threshold: None,
    };
    append_ledger(
        "quarantine",
        &verdict,
        json!({"run_id": lease.run_id, "cipher_sha256": sha256_bytes(&ciphertext), "plaintext_sha256": sha256_bytes(plaintext.as_bytes()), "bytes": plaintext.len()}),
    );
    verdict
}

pub fn read_quarantine(token: &str, record_id: &str) -> TrainingSecurityVerdict {
    if !safe_id(record_id) {
        return deny(None, "quarantine_contract", "record id invalid");
    }
    let lease = match active_lease(token) {
        Ok(lease) => lease,
        Err(error) => return deny(None, "lease", error),
    };
    let path = PathBuf::from(QUARANTINE_ROOT)
        .join(&lease.run_id)
        .join(format!("{record_id}.dpapi"));
    let ciphertext = match fs::read(&path) {
        Ok(data) => data,
        Err(error) => return deny(None, "quarantine_read", error.to_string()),
    };
    let plaintext = match dpapi_unprotect(&ciphertext, lease.manifest_hash.as_bytes()) {
        Ok(data) => data,
        Err(error) => return deny(None, "dpapi", error),
    };
    let payload = match String::from_utf8(plaintext) {
        Ok(text) => text,
        Err(_) => return deny(None, "quarantine_read", "decrypted payload is not UTF-8"),
    };
    let verdict = TrainingSecurityVerdict {
        allowed: true,
        disposition: "ALLOW".to_string(),
        reason: "memory_only_training_read".to_string(),
        rule: "dpapi_current_user".to_string(),
        decision_id: random_hex(16).unwrap_or_default(),
        policy_version: env!("CARGO_PKG_VERSION").to_string(),
        manifest_hash: lease.manifest_hash,
        normalized_paths: vec![],
        lease_token: None,
        staging_root: None,
        final_root: None,
        quarantine_id: Some(record_id.to_string()),
        payload: Some(payload),
        training_soft_band: false,
        master_s_n: None,
        training_soft_floor: None,
        hard_threshold: None,
    };
    append_ledger(
        "quarantine_read",
        &verdict,
        json!({"run_id": lease.run_id, "record_id": record_id}),
    );
    verdict
}

fn active_lease(token: &str) -> Result<Lease, String> {
    let token_hash = sha256_bytes(token.as_bytes());
    let guard = state()
        .lock()
        .map_err(|_| "security state poisoned".to_string())?;
    let lease = guard
        .leases
        .get(&token_hash)
        .ok_or_else(|| "unknown lease".to_string())?;
    if lease.consumed || lease.expires_at < now_epoch() || lease.process_id != std::process::id() {
        return Err("expired, consumed, or process-mismatched lease".to_string());
    }
    Ok(lease.clone())
}

pub fn lease_is_active(token: &str) -> bool {
    active_lease(token).is_ok()
}

fn validate_inn_sqlite_snapshot(relative: &Path, header: &[u8], length: u64) -> Result<(), String> {
    if relative.components().count() != 1
        || !matches!(relative.to_str(), Some("neuron_graph.sqlite3" | "curriculum.sqlite3"))
    {
        return Err("only named INN graph/curriculum snapshots are allowed".to_string());
    }
    if header.len() < 100 || &header[..16] != b"SQLite format 3\0" {
        return Err("invalid SQLite snapshot header".to_string());
    }
    let encoded = u16::from_be_bytes([header[16], header[17]]) as u64;
    let page_size = if encoded == 1 { 65_536 } else { encoded };
    if !(512..=65_536).contains(&page_size) || !page_size.is_power_of_two()
        || length < page_size || length % page_size != 0
        || header[18] != 1 || header[19] != 1
    {
        return Err("SQLite snapshot must contain complete standalone pages without WAL dependency".to_string());
    }
    Ok(())
}

pub fn write_inn_candidate_artifact(token: &str, relative_path: &str, payload: &[u8]) -> Result<(), String> {
    let lease = active_lease(token)?;
    if !lease.inn_candidate {
        return Err("INN candidate lease required".to_string());
    }
    if payload.is_empty() || payload.len() as u64 > lease.max_disk_bytes {
        return Err("candidate artifact is empty or exceeds lease size".to_string());
    }
    let relative = Path::new(relative_path);
    if relative.is_absolute() || relative.components().any(|component| !matches!(component, std::path::Component::Normal(_))) {
        return Err("candidate artifact path must be a relative normalized path".to_string());
    }
    let extension = relative.extension().and_then(|value| value.to_str()).unwrap_or("").to_ascii_lowercase();
    if !matches!(extension.as_str(), "json" | "jsonl" | "md" | "log" | "py" | "pt" | "sqlite3") {
        return Err("candidate artifact extension denied".to_string());
    }
    if extension == "sqlite3" {
        validate_inn_sqlite_snapshot(relative, payload, payload.len() as u64)?;
    } else if extension == "json" {
        let text = std::str::from_utf8(payload).map_err(|error| error.to_string())?;
        serde_json::from_str::<Value>(text).map_err(|error| error.to_string())?;
    } else if extension == "jsonl" {
        let text = std::str::from_utf8(payload).map_err(|error| error.to_string())?;
        for line in text.lines().filter(|line| !line.trim().is_empty()) {
            serde_json::from_str::<Value>(line).map_err(|error| error.to_string())?;
        }
    }
    let root = lease.staging_root.canonicalize().map_err(|error| error.to_string())?;
    let destination = lease.staging_root.join(relative);
    let parent = destination.parent().ok_or_else(|| "candidate artifact parent missing".to_string())?;
    fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    require_plain_root(parent)?;
    let canonical_parent = parent.canonicalize().map_err(|error| error.to_string())?;
    if !canonical_parent.starts_with(&root) {
        return Err("candidate artifact escaped staging root".to_string());
    }
    let current_bytes = inspect_staging(&lease.staging_root, lease.max_disk_bytes, lease.lora_rank, true, true)?
        .iter().filter_map(|item| item.get("bytes").and_then(Value::as_u64)).sum::<u64>();
    if current_bytes.saturating_add(payload.len() as u64) > lease.max_disk_bytes {
        return Err("candidate artifact would exceed lease disk limit".to_string());
    }
    let mut file = OpenOptions::new().create_new(true).write(true).open(&destination)
        .map_err(|error| error.to_string())?;
    if let Err(error) = file.write_all(payload).and_then(|_| file.sync_all()) {
        drop(file);
        let _ = fs::remove_file(&destination);
        return Err(error.to_string());
    }
    Ok(())
}

pub fn publish_inn_pointer(token: &str, raw: &str, payload: &str) -> TrainingSecurityVerdict {
    let request = match parse_request(raw) {
        Ok(request) => request,
        Err(error) => return deny(None, "request_schema", error),
    };
    if request.action != TrainingAction::PublishInnPointer {
        return deny(Some(&request), "action_contract", "PUBLISH_INN_POINTER required");
    }
    let paths = match validate_request(&request) {
        Ok(paths) if paths.len() == 1 && is_inn_pointer(&paths[0]) => paths,
        Ok(_) => return deny(Some(&request), "pointer_path", "one exact INN pointer path is required"),
        Err((rule, reason)) => return deny(Some(&request), rule, reason),
    };
    if payload.is_empty() || payload.len() > MAX_INN_RECEIPT_BYTES {
        return deny(Some(&request), "pointer_payload", "pointer payload size is invalid");
    }
    let value: Value = match serde_json::from_str::<Value>(payload) {
        Ok(value) if value.is_object() => value,
        Ok(_) => return deny(Some(&request), "pointer_payload", "pointer JSON must be an object"),
        Err(error) => return deny(Some(&request), "pointer_payload", error.to_string()),
    };
    let token_hash = sha256_bytes(token.as_bytes());
    let lease = match find_inn_pointer_lease(state(), &token_hash, &request) {
        Ok(lease) => lease,
        Err(reason) => return deny(Some(&request), "lease", reason),
    };
    let final_root = lease.final_root;
    let staging_root = lease.staging_root;
    let pointer_name = Path::new(&paths[0]).file_name().and_then(|name| name.to_str()).unwrap_or_default().to_string();
    let committed = lease.committed;
    if pointer_name != "neural_status.json" && !committed {
        return deny(Some(&request), "lease_state", "corpus and candidate pointers publish only after commit");
    }
    match pointer_name.as_str() {
        "neural_status.json" => {
            let run = value.get("run").and_then(Value::as_str).unwrap_or_default();
            if normalize_path(run) != normalize_path(&final_root.to_string_lossy())
                && normalize_path(run) != normalize_path(&staging_root.to_string_lossy()) {
                return deny(Some(&request), "status_binding", "status run must bind the leased staging or final root");
            }
        }
        "farm_corpus_latest.json" => {
            let folder = value.get("folder").and_then(Value::as_str).unwrap_or_default();
            let folder = PathBuf::from(folder);
            let expected_root = final_root.join("farm_corpus");
            let manifest_hash = value.get("manifest_sha256").and_then(Value::as_str).unwrap_or_default();
            let manifest = folder.join("manifest.json");
            if !folder.starts_with(&expected_root) || !folder.is_dir() || is_reparse(&folder).unwrap_or(true)
                || !manifest_hash_valid_file(&manifest, manifest_hash) {
                return deny(Some(&request), "corpus_binding", "corpus pointer must bind a committed in-run manifest");
            }
        }
        "neural_candidate.json" => {
            let run = value.get("run").and_then(Value::as_str).unwrap_or_default();
            let engine_hash = value.get("engine_sha256").and_then(Value::as_str).unwrap_or_default();
            let evaluation_hash = value.get("evaluation_sha256").and_then(Value::as_str).unwrap_or_default();
            if normalize_path(run) != normalize_path(&final_root.to_string_lossy())
                || !manifest_hash_valid_file(&final_root.join("engine.pt"), engine_hash)
                || !manifest_hash_valid_file(&final_root.join("evaluation.json"), evaluation_hash) {
                return deny(Some(&request), "candidate_binding", "candidate pointer must bind committed checkpoint and evaluation hashes");
            }
        }
        _ => return deny(Some(&request), "pointer_path", "pointer path is not supported"),
    }
    let path = PathBuf::from(&paths[0]);
    let root = Path::new(INN_LEARNING_ROOT);
    if let Err(error) = atomic_replace_pointer(root, &path, payload.as_bytes()) {
        return deny(Some(&request), "pointer_write", error);
    }
    let verdict = allow(&request, "inn_candidate_pointer_publish", paths);
    append_ledger("inn_pointer_publish", &verdict, json!({"path": pointer_name, "run_id": request.run_id}));
    verdict
}

fn atomic_replace_pointer(root: &Path, path: &Path, payload: &[u8]) -> Result<(), String> {
    require_plain_root(root)?;
    let canonical_root = root.canonicalize().map_err(|error| error.to_string())?;
    let parent = path.parent().ok_or_else(|| "pointer parent missing".to_string())?;
    if parent.canonicalize().map_err(|error| error.to_string())? != canonical_root {
        return Err("pointer must be a direct child of the configured learning root".to_string());
    }
    if path.exists() && (is_reparse(path)? || hard_link_count(path)? != 1) {
        return Err("existing pointer must be a plain single-link file".to_string());
    }
    let nonce = random_hex(8)?;
    let name = path.file_name().and_then(|value| value.to_str()).unwrap_or("pointer");
    let pending = path.with_file_name(format!(".{name}.{nonce}.pending"));
    let mut file = OpenOptions::new().create_new(true).write(true).open(&pending)
        .map_err(|error| error.to_string())?;
    if let Err(error) = file.write_all(payload).and_then(|_| file.sync_all()) {
        drop(file);
        let _ = fs::remove_file(&pending);
        return Err(error.to_string());
    }
    drop(file);
    #[cfg(windows)]
    let replace_result = {
        use std::os::windows::ffi::OsStrExt;
        let source: Vec<u16> = pending.as_os_str().encode_wide().chain(std::iter::once(0)).collect();
        let destination: Vec<u16> = path.as_os_str().encode_wide().chain(std::iter::once(0)).collect();
        let ok = unsafe { MoveFileExW(source.as_ptr(), destination.as_ptr(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH) };
        if ok == 0 { Err(std::io::Error::last_os_error()) } else { Ok(()) }
    };
    #[cfg(not(windows))]
    let replace_result = fs::rename(&pending, path);
    if let Err(error) = replace_result {
        let _ = fs::remove_file(&pending);
        return Err(error.to_string());
    }
    Ok(())
}

fn pointer_request_lease_mismatch(
    lease: &Lease,
    request: &TrainingSecurityRequest,
    token_hash: &str,
) -> Option<&'static str> {
    let mut bound_request = request.clone();
    bound_request.paths = vec![
        lease.staging_root.to_string_lossy().replace('\\', "/"),
        lease.final_root.to_string_lossy().replace('\\', "/"),
    ];
    bound_request.artifact_class = "inn_candidate_bundle".to_string();
    if !lease.inn_candidate {
        return Some("lease_role_mismatch");
    }
    if lease.process_id != std::process::id() {
        return Some("lease_process_mismatch");
    }
    if lease.expires_at < now_epoch() {
        return Some("lease_expired");
    }
    if lease.token_hash != token_hash {
        return Some("lease_token_mismatch");
    }
    if lease.run_id != request.run_id {
        return Some("lease_run_id_mismatch");
    }
    if lease.stage_id != request.stage_id {
        return Some("lease_stage_id_mismatch");
    }
    if lease.manifest_hash != request.manifest_hash {
        return Some("lease_manifest_mismatch");
    }
    if lease.binding_hash != lease_binding_hash(&bound_request) {
        return Some("lease_binding_mismatch");
    }
    if lease.consumed && !lease.committed {
        return Some("lease_consumed_before_commit");
    }
    None
}

fn find_inn_pointer_lease(
    state: &Mutex<SecurityState>,
    token_hash: &str,
    request: &TrainingSecurityRequest,
) -> Result<Lease, &'static str> {
    let guard = state.lock().map_err(|_| "security_state_poisoned")?;
    let lease = guard.leases.get(token_hash).ok_or("lease_token_not_found")?;
    if let Some(reason) = pointer_request_lease_mismatch(lease, request, token_hash) {
        return Err(reason);
    }
    Ok(lease.clone())
}

fn manifest_hash_valid_file(path: &Path, expected: &str) -> bool {
    if !valid_hash(expected) || !path.is_file() || is_reparse(path).unwrap_or(true) || hard_link_count(path).unwrap_or(0) != 1 {
        return false;
    }
    hash_file(path).is_ok_and(|actual| actual == expected)
}

fn random_hex(bytes: usize) -> Result<String, String> {
    let mut output = vec![0u8; bytes];
    let status = unsafe {
        BCryptGenRandom(
            std::ptr::null_mut(),
            output.as_mut_ptr(),
            output.len() as u32,
            BCRYPT_USE_SYSTEM_PREFERRED_RNG,
        )
    };
    if status < 0 {
        return Err(format!("BCryptGenRandom failed: {status}"));
    }
    Ok(hex_encode(output))
}

fn append_ledger(kind: &str, verdict: &TrainingSecurityVerdict, detail: Value) {
    let path = Path::new(LEDGER_PATH);
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    let _file_lock = match acquire_training_ledger_lock() {
        Ok(lock) => lock,
        Err(_) => return,
    };
    let mut guard = match state().lock() {
        Ok(guard) => guard,
        Err(_) => return,
    };
    // Always refresh the head while holding the cross-process lock. A cached
    // per-process head is stale as soon as another Python/Rust process appends.
    match verify_ledger_file(path) {
        Ok((_, head)) => guard.previous_event_hash = head,
        Err(_) => return,
    }
    let base = json!({
        "at_epoch": now_epoch(),
        "kind": kind,
        "decision_id": verdict.decision_id,
        "allowed": verdict.allowed,
        "disposition": verdict.disposition,
        "rule": verdict.rule,
        "reason": verdict.reason,
        "manifest_hash": verdict.manifest_hash,
        "policy_version": verdict.policy_version,
        "previous_event_hash": guard.previous_event_hash,
        "detail": detail,
    });
    let encoded = serde_json::to_vec(&base).unwrap_or_default();
    let event_hash = sha256_bytes(&encoded);
    let mut event = base;
    event["event_hash"] = Value::String(event_hash.clone());
    if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(path) {
        if writeln!(file, "{}", event).is_ok() {
            let _ = file.sync_data();
            guard.previous_event_hash = event_hash;
        }
    }
}

struct TrainingLedgerLock {
    path: PathBuf,
}

impl Drop for TrainingLedgerLock {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.path);
    }
}

fn acquire_training_ledger_lock() -> Result<TrainingLedgerLock, String> {
    let path = PathBuf::from(LEDGER_LOCK_PATH);
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    for attempt in 0..500 {
        match OpenOptions::new().create_new(true).write(true).open(&path) {
            Ok(mut handle) => {
                writeln!(handle, "pid={} at={}", std::process::id(), now_epoch())
                    .map_err(|error| error.to_string())?;
                handle.sync_all().map_err(|error| error.to_string())?;
                return Ok(TrainingLedgerLock { path });
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
                if attempt > 0 && attempt % 100 == 0 {
                    let stale = fs::metadata(&path)
                        .and_then(|metadata| metadata.modified())
                        .ok()
                        .and_then(|modified| modified.elapsed().ok())
                        .is_some_and(|age| age > Duration::from_secs(60));
                    if stale {
                        let _ = fs::remove_file(&path);
                    }
                }
                thread::sleep(Duration::from_millis(10));
            }
            Err(error) => return Err(error.to_string()),
        }
    }
    Err("training ledger lock busy".to_string())
}

fn verify_ledger_file(path: &Path) -> Result<(usize, String), String> {
    if !path.is_file() {
        return Ok((0, String::new()));
    }
    let raw = fs::read_to_string(path).map_err(|error| error.to_string())?;
    let mut expected_previous = String::new();
    let mut count = 0usize;
    for (index, line) in raw.lines().enumerate() {
        if line.trim().is_empty() {
            continue;
        }
        let mut value: Value = serde_json::from_str(line)
            .map_err(|error| format!("ledger line {} invalid JSON: {error}", index + 1))?;
        let event_hash = value
            .get("event_hash")
            .and_then(Value::as_str)
            .ok_or_else(|| format!("ledger line {} missing event_hash", index + 1))?
            .to_string();
        let previous = value
            .get("previous_event_hash")
            .and_then(Value::as_str)
            .ok_or_else(|| format!("ledger line {} missing previous_event_hash", index + 1))?;
        if previous != expected_previous {
            return Err(format!("ledger chain break at line {}", index + 1));
        }
        value
            .as_object_mut()
            .ok_or_else(|| format!("ledger line {} is not object", index + 1))?
            .remove("event_hash");
        let computed = sha256_bytes(
            &serde_json::to_vec(&value)
                .map_err(|error| format!("ledger line {} encode: {error}", index + 1))?,
        );
        if computed != event_hash {
            return Err(format!("ledger hash mismatch at line {}", index + 1));
        }
        expected_previous = event_hash;
        count += 1;
    }
    Ok((count, expected_previous))
}

pub fn verify_ledger() -> LedgerStatus {
    match verify_ledger_file(Path::new(LEDGER_PATH)) {
        Ok((events, head)) => LedgerStatus {
            ok: true,
            events,
            head,
            error: None,
            policy_version: env!("CARGO_PKG_VERSION").to_string(),
        },
        Err(error) => LedgerStatus {
            ok: false,
            events: 0,
            head: String::new(),
            error: Some(error),
            policy_version: env!("CARGO_PKG_VERSION").to_string(),
        },
    }
}

fn is_reparse(path: &Path) -> Result<bool, String> {
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x400;
        let metadata = fs::symlink_metadata(path).map_err(|error| error.to_string())?;
        Ok(metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0)
    }
    #[cfg(not(windows))]
    {
        Ok(fs::symlink_metadata(path)
            .map_err(|error| error.to_string())?
            .file_type()
            .is_symlink())
    }
}

fn inspect_staging(
    root: &Path,
    max_bytes: u64,
    lora_rank: u64,
    inn_candidate: bool,
    allow_empty: bool,
) -> Result<Vec<Value>, String> {
    if !root.is_dir() || is_reparse(root)? {
        return Err("staging root missing or reparse point".to_string());
    }
    let canonical_root = root.canonicalize().map_err(|error| error.to_string())?;
    let mut stack = vec![root.to_path_buf()];
    let mut total = 0u64;
    let mut inventory = Vec::new();
    while let Some(directory) = stack.pop() {
        for entry in fs::read_dir(&directory).map_err(|error| error.to_string())? {
            let entry = entry.map_err(|error| error.to_string())?;
            let path = entry.path();
            if is_reparse(&path)? {
                return Err(format!("reparse point denied: {}", path.display()));
            }
            let canonical = path.canonicalize().map_err(|error| error.to_string())?;
            if !canonical.starts_with(&canonical_root) {
                return Err(format!("path escaped staging root: {}", path.display()));
            }
            let metadata = entry.metadata().map_err(|error| error.to_string())?;
            if metadata.is_dir() {
                stack.push(path);
                continue;
            }
            if !metadata.is_file() {
                return Err(format!("non-regular file denied: {}", path.display()));
            }
            if hard_link_count(&path)? != 1 {
                return Err(format!("hard-linked file denied: {}", path.display()));
            }
            let extension = path
                .extension()
                .and_then(|value| value.to_str())
                .unwrap_or("")
                .to_ascii_lowercase();
            if !matches!(extension.as_str(), "json" | "jsonl" | "md" | "log" | "safetensors")
                && !(inn_candidate && matches!(extension.as_str(), "pt" | "py" | "sqlite3"))
            {
                return Err(format!("extension denied at commit: {}", path.display()));
            }
            total = total.saturating_add(metadata.len());
            if total > max_bytes {
                return Err("staging size exceeds lease".to_string());
            }
            let sha = hash_file(&path)?;
            if extension == "sqlite3" {
                let mut header = [0u8; 100];
                File::open(&path).and_then(|mut file| file.read_exact(&mut header))
                    .map_err(|error| error.to_string())?;
                let relative = path.strip_prefix(root).map_err(|error| error.to_string())?;
                validate_inn_sqlite_snapshot(relative, &header, metadata.len())?;
            } else if extension == "json" {
                let raw = fs::read_to_string(&path).map_err(|error| error.to_string())?;
                serde_json::from_str::<Value>(&raw)
                    .map_err(|error| format!("invalid JSON {}: {error}", path.display()))?;
            } else if extension == "jsonl" {
                let raw = fs::read_to_string(&path).map_err(|error| error.to_string())?;
                for (index, line) in raw.lines().enumerate() {
                    if !line.trim().is_empty() {
                        serde_json::from_str::<Value>(line).map_err(|error| {
                            format!(
                                "invalid JSONL {} line {}: {error}",
                                path.display(),
                                index + 1
                            )
                        })?;
                    }
                }
            } else if extension == "safetensors" {
                if inn_candidate {
                    return Err("INN candidate lease cannot commit LoRA adapters".to_string());
                }
                inspect_safetensors(&path, lora_rank)?;
            }
            inventory.push(json!({
                "path": canonical.strip_prefix(&canonical_root).unwrap_or(&canonical).to_string_lossy().replace('\\', "/"),
                "bytes": metadata.len(),
                "sha256": sha,
            }));
        }
    }
    if inventory.is_empty() && !allow_empty {
        return Err("empty staging run".to_string());
    }
    inventory.sort_by(|left, right| {
        left.get("path")
            .and_then(Value::as_str)
            .cmp(&right.get("path").and_then(Value::as_str))
    });
    Ok(inventory)
}

fn validate_inn_body_gate_receipt(
    root: &Path,
    run_id: &str,
    stability_sn: f64,
    requested_threads: Option<u64>,
) -> Result<(), String> {
    let wsl_body_image = include_str!("../../body_runtime/image_id.txt").trim();
    let path = root.join("body_gate.json");
    let raw = fs::read(&path).map_err(|_| "required body_gate.json is missing or unreadable".to_string())?;
    let receipt: Value = serde_json::from_slice(&raw)
        .map_err(|error| format!("body_gate.json is invalid: {error}"))?;
    if receipt.get("allowed").and_then(Value::as_bool) != Some(true)
        || receipt.get("disposition").and_then(Value::as_str) != Some("ALLOW_MIND_RUNTIME")
        || receipt.get("authority").and_then(Value::as_str) != Some("deterministic_aios_body_rust")
        || receipt.get("gate").and_then(Value::as_str) != Some("rust")
        || receipt.get("execution_boundary").and_then(Value::as_str) != Some("wsl_docker")
        || receipt.get("body_image").and_then(Value::as_str) != Some(wsl_body_image)
        || receipt.get("schema").and_then(Value::as_str) != Some("aios_mind_runtime_gate_v1")
        || receipt.get("candidate_run_id").and_then(Value::as_str) != Some(run_id)
        || receipt.get("requested_threads").and_then(Value::as_u64) != requested_threads
        || !receipt.get("stability_sn").and_then(Value::as_f64)
            .is_some_and(|value| (value - stability_sn).abs() <= f64::EPSILON)
        || receipt.get("body_runtime_permit").is_some()
    {
        return Err("body gate receipt is not an allowed, redacted verdict bound to this lease".to_string());
    }
    Ok(())
}

#[cfg(windows)]
fn hard_link_count(path: &Path) -> Result<u32, String> {
    use std::os::windows::ffi::OsStrExt;
    let wide: Vec<u16> = path
        .as_os_str()
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();
    let handle = unsafe {
        CreateFileW(
            wide.as_ptr(),
            FILE_READ_ATTRIBUTES,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            std::ptr::null(),
            OPEN_EXISTING,
            FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT,
            0,
        )
    };
    if handle == INVALID_HANDLE_VALUE {
        return Err(format!("failed to open file identity: {}", path.display()));
    }
    let mut information: BY_HANDLE_FILE_INFORMATION = unsafe { std::mem::zeroed() };
    let ok = unsafe { GetFileInformationByHandle(handle, &mut information) };
    unsafe { CloseHandle(handle) };
    if ok == 0 {
        return Err(format!("failed to read file identity: {}", path.display()));
    }
    Ok(information.nNumberOfLinks)
}

#[cfg(not(windows))]
fn hard_link_count(_path: &Path) -> Result<u32, String> {
    Ok(1)
}

fn hash_file(path: &Path) -> Result<String, String> {
    let mut file = File::open(path).map_err(|error| error.to_string())?;
    let mut hasher = Sha256::new();
    let mut buffer = [0u8; 1024 * 1024];
    loop {
        let count = file.read(&mut buffer).map_err(|error| error.to_string())?;
        if count == 0 {
            break;
        }
        hasher.update(&buffer[..count]);
    }
    Ok(hex_encode(hasher.finalize()))
}

fn inspect_safetensors(path: &Path, lora_rank: u64) -> Result<(), String> {
    let mut file = File::open(path).map_err(|error| error.to_string())?;
    let length = file.metadata().map_err(|error| error.to_string())?.len();
    if length < 10 {
        return Err("safetensors file too small".to_string());
    }
    let mut header_len_bytes = [0u8; 8];
    file.read_exact(&mut header_len_bytes)
        .map_err(|error| error.to_string())?;
    let header_len = u64::from_le_bytes(header_len_bytes);
    if header_len == 0 || header_len > 16 * 1024 * 1024 || header_len + 8 > length {
        return Err("safetensors header length invalid".to_string());
    }
    let mut header = vec![0u8; header_len as usize];
    file.read_exact(&mut header)
        .map_err(|error| error.to_string())?;
    let value: Value = serde_json::from_slice(&header)
        .map_err(|error| format!("safetensors header JSON invalid: {error}"))?;
    let object = value
        .as_object()
        .ok_or("safetensors header is not an object")?;
    let data_len = length - header_len - 8;
    let mut tensor_count = 0usize;
    for (name, descriptor) in object {
        if name == "__metadata__" {
            continue;
        }
        tensor_count += 1;
        if tensor_count > 4096 || !name.contains("lora_") {
            return Err(format!("unexpected adapter tensor: {name}"));
        }
        let dtype = descriptor
            .get("dtype")
            .and_then(Value::as_str)
            .ok_or("tensor dtype missing")?;
        let width = match dtype {
            "F32" => 4u64,
            "F16" | "BF16" => 2u64,
            _ => return Err(format!("adapter dtype denied: {dtype}")),
        };
        let shape = descriptor
            .get("shape")
            .and_then(Value::as_array)
            .ok_or("tensor shape missing")?;
        if shape.len() != 2 {
            return Err(format!("adapter tensor rank is not 2D: {name}"));
        }
        if lora_rank == 0
            || !shape
                .iter()
                .filter_map(Value::as_u64)
                .any(|dimension| dimension == lora_rank)
        {
            return Err(format!("LoRA rank mismatch for {name}"));
        }
        let elements = shape.iter().try_fold(1u64, |total, dim| {
            dim.as_u64()
                .and_then(|value| total.checked_mul(value))
                .ok_or_else(|| "tensor shape overflow".to_string())
        })?;
        let offsets = descriptor
            .get("data_offsets")
            .and_then(Value::as_array)
            .ok_or("tensor offsets missing")?;
        if offsets.len() != 2 {
            return Err("tensor offsets malformed".to_string());
        }
        let start = offsets[0].as_u64().ok_or("tensor start missing")?;
        let end = offsets[1].as_u64().ok_or("tensor end missing")?;
        if start > end || end > data_len || end - start != elements.saturating_mul(width) {
            return Err(format!("tensor bounds invalid: {name}"));
        }
        inspect_tensor_finite(&mut file, header_len + 8 + start, end - start, dtype, name)?;
    }
    if tensor_count == 0 {
        return Err("adapter contains no tensors".to_string());
    }
    Ok(())
}

fn inspect_tensor_finite(
    file: &mut File,
    absolute_offset: u64,
    length: u64,
    dtype: &str,
    name: &str,
) -> Result<(), String> {
    file.seek(SeekFrom::Start(absolute_offset))
        .map_err(|error| error.to_string())?;
    let width = if dtype == "F32" { 4usize } else { 2usize };
    let mut remaining = length;
    let mut buffer = vec![0u8; 1024 * 1024];
    while remaining > 0 {
        let count = (remaining as usize).min(buffer.len());
        file.read_exact(&mut buffer[..count])
            .map_err(|error| error.to_string())?;
        if count % width != 0 {
            return Err(format!("unaligned tensor data: {name}"));
        }
        for chunk in buffer[..count].chunks_exact(width) {
            let nonfinite = if dtype == "F32" {
                let bits = u32::from_le_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]);
                bits & 0x7f80_0000 == 0x7f80_0000
            } else if dtype == "F16" {
                let bits = u16::from_le_bytes([chunk[0], chunk[1]]);
                bits & 0x7c00 == 0x7c00
            } else {
                let bits = u16::from_le_bytes([chunk[0], chunk[1]]);
                bits & 0x7f80 == 0x7f80
            };
            if nonfinite {
                return Err(format!("non-finite tensor value denied: {name}"));
            }
        }
        remaining -= count as u64;
    }
    Ok(())
}

fn dpapi_protect(plaintext: &[u8], entropy: &[u8]) -> Result<Vec<u8>, String> {
    let input = CRYPT_INTEGER_BLOB {
        cbData: plaintext.len() as u32,
        pbData: plaintext.as_ptr() as *mut u8,
    };
    let entropy_blob = CRYPT_INTEGER_BLOB {
        cbData: entropy.len() as u32,
        pbData: entropy.as_ptr() as *mut u8,
    };
    let mut output = CRYPT_INTEGER_BLOB {
        cbData: 0,
        pbData: std::ptr::null_mut(),
    };
    let ok = unsafe {
        CryptProtectData(
            &input,
            std::ptr::null(),
            &entropy_blob,
            std::ptr::null(),
            std::ptr::null(),
            CRYPTPROTECT_UI_FORBIDDEN,
            &mut output,
        )
    };
    if ok == 0 || output.pbData.is_null() {
        return Err("CryptProtectData failed".to_string());
    }
    let data =
        unsafe { std::slice::from_raw_parts(output.pbData, output.cbData as usize).to_vec() };
    unsafe { LocalFree(output.pbData as *mut core::ffi::c_void) };
    Ok(data)
}

fn dpapi_unprotect(ciphertext: &[u8], entropy: &[u8]) -> Result<Vec<u8>, String> {
    let input = CRYPT_INTEGER_BLOB {
        cbData: ciphertext.len() as u32,
        pbData: ciphertext.as_ptr() as *mut u8,
    };
    let entropy_blob = CRYPT_INTEGER_BLOB {
        cbData: entropy.len() as u32,
        pbData: entropy.as_ptr() as *mut u8,
    };
    let mut output = CRYPT_INTEGER_BLOB {
        cbData: 0,
        pbData: std::ptr::null_mut(),
    };
    let ok = unsafe {
        CryptUnprotectData(
            &input,
            std::ptr::null_mut(),
            &entropy_blob,
            std::ptr::null(),
            std::ptr::null(),
            CRYPTPROTECT_UI_FORBIDDEN,
            &mut output,
        )
    };
    if ok == 0 || output.pbData.is_null() {
        return Err("CryptUnprotectData failed".to_string());
    }
    let data =
        unsafe { std::slice::from_raw_parts(output.pbData, output.cbData as usize).to_vec() };
    unsafe { LocalFree(output.pbData as *mut core::ffi::c_void) };
    Ok(data)
}

#[cfg(test)]
mod tests {
    #[test]
    fn inn_sqlite_snapshots_are_named_standalone_and_page_aligned() {
        let mut header = [0u8; 100];
        header[..16].copy_from_slice(b"SQLite format 3\0");
        header[16..18].copy_from_slice(&4096u16.to_be_bytes());
        header[18] = 1;
        header[19] = 1;
        for name in ["neuron_graph.sqlite3", "curriculum.sqlite3"] {
            assert!(super::validate_inn_sqlite_snapshot(std::path::Path::new(name), &header, 8192).is_ok());
        }
        for name in ["other.sqlite3", "nested/neuron_graph.sqlite3", "../curriculum.sqlite3"] {
            assert!(super::validate_inn_sqlite_snapshot(std::path::Path::new(name), &header, 8192).is_err());
        }
        assert!(super::validate_inn_sqlite_snapshot(std::path::Path::new("neuron_graph.sqlite3"), &header, 8191).is_err());
        header[18] = 2;
        assert!(super::validate_inn_sqlite_snapshot(std::path::Path::new("neuron_graph.sqlite3"), &header, 8192).is_err());
        assert!(super::validate_inn_sqlite_snapshot(std::path::Path::new("neuron_graph.sqlite3"), b"not sqlite", 8192).is_err());
    }

    use super::*;

    fn test_directory(label: &str) -> PathBuf {
        std::env::temp_dir().join(format!(
            "viv-training-security-{}-{}",
            label,
            std::process::id()
        ))
    }

    fn write_test_adapter(path: &Path, nonfinite: bool) {
        let header = json!({
            "base_model.model.layers.0.self_attn.q_proj.lora_A.weight": {
                "dtype": "F32",
                "shape": [16, 1],
                "data_offsets": [0, 64]
            }
        })
        .to_string();
        let mut file = File::create(path).expect("create adapter");
        file.write_all(&(header.len() as u64).to_le_bytes())
            .expect("write header length");
        file.write_all(header.as_bytes()).expect("write header");
        let mut data = vec![0u8; 64];
        if nonfinite {
            data[..4].copy_from_slice(&f32::NAN.to_bits().to_le_bytes());
        }
        file.write_all(&data).expect("write tensor");
        file.sync_all().expect("sync adapter");
    }

    fn request(action: TrainingAction) -> TrainingSecurityRequest {
        TrainingSecurityRequest {
            action,
            stage_id: "evidence_truth".to_string(),
            run_id: "security-test-run".to_string(),
            model_role: "openaster_target".to_string(),
            manifest_hash: "a".repeat(64),
            source_hashes: vec!["b".repeat(64)],
            paths: vec![
                "L:/Continue/Viv/sandbox/training_staging/security-test-run".to_string(),
                "L:/Continue/Viv/foundation/models/Training/runs/security-test-run".to_string(),
            ],
            artifact_class: "lora_adapter".to_string(),
            master_s_n: 0.55,
            process_id: std::process::id(),
            max_duration_s: 60,
            max_vram_mib: 8192,
            max_ram_mib: 28672,
            max_disk_mib: 512,
            sequence_cap: 384,
            lora_rank: 16,
            body_runtime_permit: None,
            body_requested_threads: None,
        }
    }

    #[test]
    fn valid_begin_request_passes_pure_contract() {
        let result = validate_request(&request(TrainingAction::BeginRun));
        assert!(result.is_ok(), "{result:?}");
    }

    #[test]
    fn missing_inn_pointer_lease_returns_after_releasing_state_lock() {
        let state = Mutex::new(SecurityState::default());
        let pointer = request(TrainingAction::PublishInnPointer);
        let result = find_inn_pointer_lease(&state, &"d".repeat(64), &pointer);
        assert_eq!(result.unwrap_err(), "lease_token_not_found");
        assert!(state.try_lock().is_ok());
    }

    #[test]
    fn pointer_publication_preserves_lease_binding_and_requires_commit_for_consumed_lease() {
        let mut pointer = request(TrainingAction::PublishInnPointer);
        pointer.stage_id = "inn_candidate".to_string();
        pointer.model_role = "inn_candidate_trainer".to_string();
        pointer.artifact_class = "inn_candidate_pointer".to_string();
        pointer.run_id = "pointer-binding-test".to_string();
        pointer.source_hashes = vec!["b".repeat(64), "c".repeat(64)];
        pointer.lora_rank = 0;
        pointer.paths = vec![format!("{INN_LEARNING_ROOT}/neural_status.json")];
        let staging_root = PathBuf::from(INN_STAGING_ROOT).join(&pointer.run_id);
        let final_root = PathBuf::from(INN_RUNS_ROOT).join(&pointer.run_id);
        let mut bound = pointer.clone();
        bound.artifact_class = "inn_candidate_bundle".to_string();
        bound.paths = vec![
            staging_root.to_string_lossy().replace('\\', "/"),
            final_root.to_string_lossy().replace('\\', "/"),
        ];
        let token_hash = "d".repeat(64);
        let mut lease = Lease {
            token_hash: token_hash.clone(),
            binding_hash: lease_binding_hash(&bound),
            run_id: pointer.run_id.clone(),
            stage_id: pointer.stage_id.clone(),
            manifest_hash: pointer.manifest_hash.clone(),
            process_id: std::process::id(),
            staging_root,
            final_root,
            expires_at: now_epoch() + 60,
            max_disk_bytes: pointer.max_disk_mib * 1024 * 1024,
            lora_rank: pointer.lora_rank,
            master_s_n: pointer.master_s_n,
            body_requested_threads: pointer.body_requested_threads,
            inn_candidate: true,
            consumed: true,
            committed: true,
        };
        assert!(pointer_request_lease_mismatch(&lease, &pointer, &token_hash).is_none());
        let mut altered = pointer.clone();
        altered.max_disk_mib += 1;
        assert!(pointer_request_lease_mismatch(&lease, &altered, &token_hash).is_some());
        lease.committed = false;
        assert!(pointer_request_lease_mismatch(&lease, &pointer, &token_hash).is_some());
    }

    #[test]
    fn atomic_pointer_replacement_is_verified_in_an_isolated_directory() {
        let root = test_directory("atomic-pointer");
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(&root).expect("create isolated pointer root");
        let pointer = root.join("neural_status.json");
        fs::write(&pointer, br#"{"run":"old"}"#).expect("seed pointer");
        atomic_replace_pointer(&root, &pointer, br#"{"run":"new"}"#)
            .expect("atomically replace pointer");
        assert_eq!(fs::read(&pointer).expect("read replaced pointer"), br#"{"run":"new"}"#);
        assert_eq!(fs::read_dir(&root).expect("read pointer directory").count(), 1);
        let outside = root.parent().expect("temp parent").join("outside-pointer.json");
        assert!(atomic_replace_pointer(&root, &outside, b"{}").is_err());
        assert!(!outside.exists());
        fs::remove_dir_all(&root).expect("remove isolated pointer root");
    }

    #[test]
    fn body_runtime_permit_is_one_shot_process_and_stability_bound() {
        let token = issue_body_runtime_permit(0.8, 1.0, 2, "permit-test-run").expect("issue permit");
        let mut candidate = request(TrainingAction::BeginInnCandidate);
        candidate.master_s_n = 0.8;
        candidate.run_id = "permit-test-run".to_string();
        candidate.body_runtime_permit = Some(token.clone());
        candidate.body_requested_threads = Some(2);
        assert!(consume_body_runtime_permit(&token, &candidate).is_ok());
        assert!(consume_body_runtime_permit(&token, &candidate).is_err());

        let mismatched = issue_body_runtime_permit(0.8, 1.0, 2, "permit-test-run").expect("issue second permit");
        candidate.master_s_n = 0.9;
        candidate.body_runtime_permit = Some(mismatched.clone());
        assert!(consume_body_runtime_permit(&mismatched, &candidate).is_err());
        assert!(consume_body_runtime_permit(&mismatched, &candidate).is_err());

        let thread_mismatch = issue_body_runtime_permit(0.8, 1.0, 2, "permit-test-run").expect("issue thread-bound permit");
        candidate.master_s_n = 0.8;
        candidate.body_requested_threads = Some(3);
        candidate.body_runtime_permit = Some(thread_mismatch.clone());
        assert!(consume_body_runtime_permit(&thread_mismatch, &candidate).is_err());

        let run_mismatch = issue_body_runtime_permit(0.8, 1.0, 2, "permit-test-run").expect("issue run-bound permit");
        candidate.body_requested_threads = Some(2);
        candidate.body_runtime_permit = Some(run_mismatch.clone());
        candidate.run_id = "different-run".to_string();
        assert!(consume_body_runtime_permit(&run_mismatch, &candidate).is_err());
    }

    #[test]
    fn inn_candidate_lease_denies_missing_body_runtime_permit_before_filesystem_writes() {
        let mut candidate = request(TrainingAction::BeginInnCandidate);
        candidate.stage_id = "inn_candidate".to_string();
        candidate.model_role = "inn_candidate_trainer".to_string();
        candidate.artifact_class = "inn_candidate_bundle".to_string();
        candidate.lora_rank = 0;
        candidate.run_id = format!("missing-body-permit-{}", std::process::id());
        candidate.paths = vec![
            PathBuf::from(INN_STAGING_ROOT).join(&candidate.run_id).to_string_lossy().replace('\\', "/"),
            PathBuf::from(INN_RUNS_ROOT).join(&candidate.run_id).to_string_lossy().replace('\\', "/"),
        ];
        assert!(require_body_runtime_permit(&candidate).is_err());
        assert!(!PathBuf::from(&candidate.paths[0]).exists());
    }

    #[test]
    fn training_soft_band_allows_bounded_begin_and_commit() {
        for action in [TrainingAction::BeginRun, TrainingAction::CommitRun] {
            let mut value = request(action);
            value.master_s_n = 0.3229;
            assert!(validate_request(&value).is_ok(), "{value:?}");
        }
    }

    #[test]
    fn non_training_actions_keep_hard_law5_gate() {
        let mut value = request(TrainingAction::Evaluate);
        value.artifact_class = "training_evidence".to_string();
        value.model_role = "deterministic_authority".to_string();
        value.master_s_n = 0.3229;
        assert!(matches!(
            validate_request(&value),
            Err(("law5_stability", _))
        ));
    }

    #[test]
    fn training_soft_floor_still_fails_closed() {
        let mut value = request(TrainingAction::BeginRun);
        value.master_s_n = TRAINING_SOFT_FLOOR - 0.0001;
        assert!(matches!(
            validate_request(&value),
            Err(("law5_stability", _))
        ));
    }

    #[test]
    fn deployment_is_compiled_closed() {
        let result = validate_request(&request(TrainingAction::Deploy));
        assert!(matches!(result, Err(("training_deploy_disabled", _))));
    }

    #[test]
    fn low_stability_fails_closed() {
        let mut value = request(TrainingAction::BeginRun);
        value.master_s_n = 0.1;
        let result = validate_request(&value);
        assert!(matches!(result, Err(("law5_stability", _))));
    }

    #[test]
    fn path_escape_and_rank_widen_are_denied() {
        let mut escaped = request(TrainingAction::BeginRun);
        escaped.paths = vec!["L:/Continue/Viv/sandbox/../security_core/Cargo.toml".to_string()];
        assert!(matches!(
            validate_request(&escaped),
            Err(("path_contract", _))
        ));
        let mut widened = request(TrainingAction::BeginRun);
        widened.lora_rank = 32;
        assert!(matches!(
            validate_request(&widened),
            Err(("resource_ceiling", _))
        ));
    }

    #[test]
    fn continue_training_lease_denies_localcoder_inn_candidate_root() {
        let mut value = request(TrainingAction::BeginRun);
        value.paths = vec![
            "L:/LocalCoder/workspace/autonomy/learning/neural_runs/security-test-run"
                .to_string(),
        ];
        assert!(matches!(
            validate_request(&value),
            Err(("path_contract", _))
        ));
    }

    #[test]
    fn inn_candidate_lease_is_separate_from_continue_lease() {
        let mut begin = request(TrainingAction::BeginInnCandidate);
        begin.stage_id = "inn_candidate".to_string();
        begin.model_role = "inn_candidate_trainer".to_string();
        begin.artifact_class = "inn_candidate_bundle".to_string();
        begin.paths = vec![
            "L:/LocalCoder/workspace/autonomy/learning/neural_candidate_staging/security-test-run".to_string(),
            "L:/LocalCoder/workspace/autonomy/learning/neural_runs/security-test-run".to_string(),
        ];
        assert!(validate_request(&begin).is_ok());
        begin.paths[0] = "L:/LocalCoder/workspace/autonomy/learning/neural_admitted.json".to_string();
        assert!(matches!(validate_request(&begin), Err(("path_contract", _))));
        begin.paths[0] = "L:/Continue/Viv/sandbox/training_staging/security-test-run".to_string();
        assert!(matches!(validate_request(&begin), Err(("path_contract", _))));
    }

    #[test]
    fn inn_candidate_pointer_scope_is_exact_and_excludes_admission() {
        let mut pointer = request(TrainingAction::PublishInnPointer);
        pointer.stage_id = "inn_candidate".to_string();
        pointer.model_role = "inn_candidate_trainer".to_string();
        pointer.artifact_class = "inn_candidate_pointer".to_string();
        for name in ["neural_status.json", "farm_corpus_latest.json", "neural_candidate.json"] {
            pointer.paths = vec![format!("L:/LocalCoder/workspace/autonomy/learning/{name}")];
            assert!(validate_request(&pointer).is_ok(), "{name}");
        }
        pointer.paths = vec!["L:/LocalCoder/workspace/autonomy/learning/neural_admitted.json".to_string()];
        assert!(matches!(validate_request(&pointer), Err(("path_contract", _))));
        pointer.paths = vec!["L:/LocalCoder/workspace/autonomy/learning/neural_candidate.json.bak".to_string()];
        assert!(matches!(validate_request(&pointer), Err(("path_contract", _))));
        pointer.paths = vec!["L:/Continue/Viv/sandbox/training_staging/security-test-run".to_string()];
        assert!(matches!(validate_request(&pointer), Err(("path_contract", _))));
    }

    #[test]
    fn inn_verification_receipt_is_only_the_exact_run_sidecar() {
        let mut receipt = request(TrainingAction::WriteInnCandidateReceipt);
        receipt.stage_id = "inn_candidate".to_string();
        receipt.model_role = "inn_candidate_verifier".to_string();
        receipt.artifact_class = "inn_candidate_receipt".to_string();
        receipt.master_s_n = 0.0;
        receipt.source_hashes = vec!["b".repeat(64), "c".repeat(64)];
        receipt.paths = vec![
            "L:/LocalCoder/workspace/autonomy/learning/neural_runs/security-test-run/recheck.json".to_string(),
        ];
        assert!(validate_request(&receipt).is_ok());
        receipt.paths[0] =
            "L:/LocalCoder/workspace/autonomy/learning/neural_runs/security-test-run/manifest.json".to_string();
        assert!(matches!(validate_request(&receipt), Err(("path_contract", _))));
    }

    #[test]
    fn inn_verification_receipt_is_validated_and_create_only() {
        let payload = r#"{"passed":false,"original_gate_reproduced":true,"checkpoint_unchanged":true,"admitted_proposals":false}"#;
        assert!(parse_inn_receipt(payload).is_ok());
        assert!(parse_inn_receipt(r#"{"passed":false}"#).is_err());
        let root = test_directory("inn-receipt");
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(&root).expect("create test root");
        let path = root.join("recheck.json");
        create_inn_receipt_file(&path, payload).expect("create receipt atomically");
        assert_eq!(fs::read_to_string(&path).expect("read receipt"), payload);
        assert!(create_inn_receipt_file(&path, payload).is_err());
        fs::remove_dir_all(&root).expect("cleanup test root");
    }

    #[test]
    fn typed_capabilities_protect_ledger_extensions_and_freeze_path() {
        let mut evidence = request(TrainingAction::Evaluate);
        evidence.model_role = "artifact_controller".to_string();
        evidence.artifact_class = "training_evidence".to_string();
        evidence.paths = vec![LEDGER_PATH.to_string()];
        assert!(matches!(
            validate_request(&evidence),
            Err(("ledger_protected", _))
        ));
        evidence.paths =
            vec!["L:/Continue/Viv/foundation/artifacts/auto/training_payload.py".to_string()];
        assert!(matches!(
            validate_request(&evidence),
            Err(("artifact_extension", _))
        ));

        let mut freeze = request(TrainingAction::Freeze);
        freeze.model_role = "deterministic_authority".to_string();
        freeze.artifact_class = "training_evidence".to_string();
        freeze.paths = vec![STAGE1_REGISTRY_PATH.to_string()];
        assert!(validate_request(&freeze).is_ok());
        freeze.model_role = "openaster_target".to_string();
        assert!(matches!(
            validate_request(&freeze),
            Err(("capability_matrix", _))
        ));
    }

    #[test]
    fn registry_freeze_targets_are_exact_and_stage_bound() {
        let old = resolve_freeze_target(&[normalize_path(STAGE1_REGISTRY_PATH)], "evidence_truth")
            .expect("legacy stage1 registry remains allowlisted");
        assert_eq!(old.corpus_path, STAGE1_CORPUS_PATH);

        let mouth = resolve_freeze_target(
            &[normalize_path(MOUTH_IDENTITY_REGISTRY_PATH)],
            "mouth_identity",
        )
        .expect("mouth identity registry is allowlisted");
        assert_eq!(mouth.corpus_path, MOUTH_IDENTITY_CORPUS_PATH);
        assert_eq!(
            registry_for_frozen_corpus(&normalize_path(MOUTH_IDENTITY_CORPUS_PATH)),
            Some(MOUTH_IDENTITY_REGISTRY_PATH)
        );

        let mouth_v2 = resolve_freeze_target(
            &[normalize_path(MOUTH_IDENTITY_V2_REGISTRY_PATH)],
            "mouth_identity",
        )
        .expect("mouth identity v2 registry is allowlisted");
        assert_eq!(mouth_v2.corpus_path, MOUTH_IDENTITY_V2_CORPUS_PATH);

        let mouth_v2_1 = resolve_freeze_target(
            &[normalize_path(MOUTH_IDENTITY_V2_1_REGISTRY_PATH)],
            "mouth_identity",
        )
        .expect("mouth identity v2.1 registry is allowlisted");
        assert_eq!(mouth_v2_1.corpus_path, MOUTH_IDENTITY_V2_1_CORPUS_PATH);

        assert!(matches!(
            resolve_freeze_target(
                &[normalize_path(MOUTH_IDENTITY_REGISTRY_PATH)],
                "evidence_truth"
            ),
            Err(("freeze_stage", _))
        ));
        assert!(matches!(
            resolve_freeze_target(
                &["l:/continue/viv/foundation/artifacts/auto/arbitrary.json".to_string()],
                "mouth_identity"
            ),
            Err(("freeze_target", _))
        ));
        assert!(matches!(
            resolve_freeze_target(
                &[
                    normalize_path(MOUTH_IDENTITY_REGISTRY_PATH),
                    normalize_path(STAGE1_REGISTRY_PATH)
                ],
                "mouth_identity"
            ),
            Err(("freeze_target", _))
        ));
    }

    #[test]
    fn parity_mouth_role_is_evaluate_only() {
        let mut evaluate = request(TrainingAction::Evaluate);
        evaluate.model_role = "parity_mouth_eval".to_string();
        evaluate.artifact_class = "evaluation_report".to_string();
        evaluate.paths = vec![
            "L:/Continue/Viv/foundation/artifacts/auto/openaster_parity/reports/probe.json"
                .to_string(),
        ];
        assert!(validate_request(&evaluate).is_ok());

        let mut begin = request(TrainingAction::BeginRun);
        begin.model_role = "parity_mouth_eval".to_string();
        assert!(matches!(
            validate_request(&begin),
            Err(("capability_matrix", _))
        ));

        let mut promote = request(TrainingAction::Promote);
        promote.model_role = "parity_mouth_eval".to_string();
        promote.artifact_class = "candidate_pointer".to_string();
        assert!(matches!(
            validate_request(&promote),
            Err(("capability_matrix", _))
        ));
    }

    #[test]
    fn request_schema_rejects_unknown_fields() {
        let raw = format!(
            "{{\"action\":\"BEGIN_RUN\",\"stage_id\":\"evidence_truth\",\"run_id\":\"x\",\
             \"model_role\":\"openaster_target\",\"manifest_hash\":\"{}\",\"source_hashes\":[],\
             \"paths\":[],\"artifact_class\":\"lora_adapter\",\"master_s_n\":0.5,\
             \"process_id\":{},\"max_duration_s\":60,\"max_vram_mib\":1,\"max_ram_mib\":1,\
             \"max_disk_mib\":1,\"sequence_cap\":1,\"lora_rank\":1,\"bypass\":true}}",
            "a".repeat(64),
            std::process::id()
        );
        assert!(parse_request(&raw).is_err());
    }

    #[test]
    fn dpapi_round_trip_is_current_user_bound() {
        let plaintext = b"Viv training quarantine test";
        let entropy = b"manifest";
        let ciphertext = dpapi_protect(plaintext, entropy).expect("protect");
        assert_ne!(ciphertext, plaintext);
        let restored = dpapi_unprotect(&ciphertext, entropy).expect("unprotect");
        assert_eq!(restored, plaintext);
        assert!(dpapi_unprotect(&ciphertext, b"wrong-manifest").is_err());
    }

    #[test]
    fn safetensors_parser_accepts_finite_rank_and_rejects_nonfinite_or_malformed() {
        let root = test_directory("safetensors");
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(&root).expect("create test root");
        let good = root.join("good.safetensors");
        write_test_adapter(&good, false);
        assert!(inspect_safetensors(&good, 16).is_ok());

        let nonfinite = root.join("nonfinite.safetensors");
        write_test_adapter(&nonfinite, true);
        let error = inspect_safetensors(&nonfinite, 16).expect_err("nonfinite denied");
        assert!(error.contains("non-finite"), "{error}");

        let malformed = root.join("malformed.safetensors");
        fs::write(&malformed, b"not-safe").expect("write malformed");
        assert!(inspect_safetensors(&malformed, 16).is_err());
        fs::remove_dir_all(&root).expect("cleanup test root");
    }

    #[test]
    fn staging_inspection_rejects_hardlinks_and_reparse_points() {
        let root = test_directory("links");
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(&root).expect("create test root");
        let original = root.join("record.json");
        fs::write(&original, b"{}").expect("write record");
        let linked = root.join("record-linked.json");
        fs::hard_link(&original, &linked).expect("create hardlink");
        let error = inspect_staging(&root, 1024, 16, false, false).expect_err("hardlink denied");
        assert!(error.contains("hard-linked"), "{error}");
        fs::remove_file(&linked).expect("remove hardlink");

        #[cfg(windows)]
        {
            use std::os::windows::fs::symlink_file;
            let outside = test_directory("outside").with_extension("json");
            fs::write(&outside, b"{}").expect("write outside target");
            let link = root.join("reparse.json");
            if symlink_file(&outside, &link).is_ok() {
                let error = inspect_staging(&root, 1024, 16, false, false).expect_err("reparse denied");
                assert!(error.contains("reparse"), "{error}");
            }
            let _ = fs::remove_file(&link);
            fs::remove_file(&outside).expect("remove outside target");
        }
        fs::remove_dir_all(&root).expect("cleanup test root");
    }

    #[test]
    fn inn_candidate_checkpoint_is_opaque_and_other_binary_types_remain_denied() {
        let root = test_directory("inn-checkpoint");
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(&root).expect("create test root");
        fs::write(root.join("engine.pt"), b"opaque candidate checkpoint").expect("write checkpoint");
        assert!(inspect_staging(&root, 1024, 0, true, false).is_ok());
        assert!(inspect_staging(&root, 1024, 0, false, false).is_err());
        fs::write(root.join("source.py"), b"source provenance").expect("write source");
        assert!(inspect_staging(&root, 1024, 0, true, false).is_ok());
        assert!(inspect_staging(&root, 1024, 0, false, false).is_err());
        fs::write(root.join("unexpected.bin"), b"untyped binary").expect("write binary");
        assert!(inspect_staging(&root, 1024, 0, true, false).is_err());
        fs::remove_dir_all(&root).expect("cleanup test root");
    }

    #[test]
    fn empty_inn_candidate_staging_is_allowed_only_before_artifact_writes() {
        let root = test_directory("inn-empty-staging");
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(&root).expect("create empty staging root");
        assert!(inspect_staging(&root, 1024, 0, true, true)
            .expect("allow pre-write empty staging")
            .is_empty());
        assert_eq!(
            inspect_staging(&root, 1024, 0, true, false).unwrap_err(),
            "empty staging run"
        );
        fs::remove_dir_all(&root).expect("cleanup empty staging root");
    }

    #[test]
    fn inn_candidate_commit_requires_matching_redacted_body_receipt() {
        let root = test_directory("inn-body-gate-receipt");
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(&root).expect("create body receipt test root");
        let receipt_path = root.join("body_gate.json");
        let receipt = json!({
            "allowed": true,
            "disposition": "ALLOW_MIND_RUNTIME",
            "authority": "deterministic_aios_body_rust",
            "gate": "rust",
            "execution_boundary": "wsl_docker",
            "body_image": include_str!("../../body_runtime/image_id.txt").trim(),
            "schema": "aios_mind_runtime_gate_v1",
            "candidate_run_id": "body-gate-test-run",
            "requested_threads": 2,
            "stability_sn": 0.8
        });
        fs::write(&receipt_path, serde_json::to_vec(&receipt).expect("serialize receipt"))
            .expect("write valid body receipt");
        assert!(validate_inn_body_gate_receipt(&root, "body-gate-test-run", 0.8, Some(2)).is_ok());

        let mut wrong_boundary = receipt.clone();
        wrong_boundary["execution_boundary"] = json!("windows_host");
        fs::write(&receipt_path, serde_json::to_vec(&wrong_boundary).expect("serialize boundary mismatch"))
            .expect("write wrong-boundary body receipt");
        assert!(validate_inn_body_gate_receipt(&root, "body-gate-test-run", 0.8, Some(2)).is_err());

        let mut wrong_image = receipt.clone();
        wrong_image["body_image"] = json!("sha256:unverified");
        fs::write(&receipt_path, serde_json::to_vec(&wrong_image).expect("serialize image mismatch"))
            .expect("write wrong-image body receipt");
        assert!(validate_inn_body_gate_receipt(&root, "body-gate-test-run", 0.8, Some(2)).is_err());

        let mut mismatched = receipt.clone();
        mismatched["candidate_run_id"] = json!("other-run");
        fs::write(&receipt_path, serde_json::to_vec(&mismatched).expect("serialize mismatch"))
            .expect("write mismatched body receipt");
        assert!(validate_inn_body_gate_receipt(&root, "body-gate-test-run", 0.8, Some(2)).is_err());

        let mut wrong_threads = receipt.clone();
        wrong_threads["requested_threads"] = json!(3);
        fs::write(&receipt_path, serde_json::to_vec(&wrong_threads).expect("serialize thread mismatch"))
            .expect("write thread-mismatched body receipt");
        assert!(validate_inn_body_gate_receipt(&root, "body-gate-test-run", 0.8, Some(2)).is_err());

        let mut wrong_stability = receipt.clone();
        wrong_stability["stability_sn"] = json!(0.9);
        fs::write(&receipt_path, serde_json::to_vec(&wrong_stability).expect("serialize stability mismatch"))
            .expect("write stability-mismatched body receipt");
        assert!(validate_inn_body_gate_receipt(&root, "body-gate-test-run", 0.8, Some(2)).is_err());

        let mut unredacted = receipt;
        unredacted["body_runtime_permit"] = json!("secret-permit");
        fs::write(&receipt_path, serde_json::to_vec(&unredacted).expect("serialize unredacted"))
            .expect("write unredacted body receipt");
        assert!(validate_inn_body_gate_receipt(&root, "body-gate-test-run", 0.8, Some(2)).is_err());
        fs::remove_file(&receipt_path).expect("remove body receipt");
        assert!(validate_inn_body_gate_receipt(&root, "body-gate-test-run", 0.8, Some(2)).is_err());
        fs::remove_dir_all(&root).expect("cleanup body receipt test root");
    }

    #[test]
    fn consumed_lease_token_cannot_be_replayed() {
        let token = "replay-test-token";
        let token_hash = sha256_bytes(token.as_bytes());
        let lease = Lease {
            token_hash: token_hash.clone(),
            binding_hash: "binding".to_string(),
            run_id: "replay-test".to_string(),
            stage_id: "tree_control".to_string(),
            manifest_hash: "a".repeat(64),
            process_id: std::process::id(),
            staging_root: PathBuf::from(STAGING_ROOT).join("replay-test"),
            final_root: PathBuf::from(RUNS_ROOT).join("replay-test"),
            expires_at: now_epoch() + 60,
            max_disk_bytes: 1024,
            lora_rank: 16,
            master_s_n: 1.0,
            body_requested_threads: None,
            inn_candidate: false,
            consumed: true,
            committed: false,
        };
        state()
            .lock()
            .expect("state")
            .leases
            .insert(token_hash.clone(), lease);
        assert!(!lease_is_active(token));
        let error = active_lease(token).expect_err("consumed lease denied");
        assert!(error.contains("expired, consumed"));
        state().lock().expect("state").leases.remove(&token_hash);
    }
}
