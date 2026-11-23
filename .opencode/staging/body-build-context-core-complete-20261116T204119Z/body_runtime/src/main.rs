#[path = "../../local_security_core/src/body_authority.rs"]
mod body_authority;
mod architect_runtime_permission;
mod container_policy;

use serde_json::Value;
use std::io::{self, Read};

const MAX_REQUEST_BYTES: usize = 1_048_576;
const CORE_MANIFEST: &str = include_str!("../core_manifest.json");
const ARCHITECT_PERMISSION: &str = include_str!("../architect_runtime_permission.json");

#[derive(serde::Deserialize)]
struct BodyCoreManifest {
    schema: String,
    expected_cores: Vec<String>,
}

fn main() {
    if let Err(error) = run() {
        eprintln!("body_request_rejected:{error}");
        std::process::exit(2);
    }
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let mut input = Vec::new();
    io::stdin()
        .take((MAX_REQUEST_BYTES + 1) as u64)
        .read_to_end(&mut input)?;
    if input.len() > MAX_REQUEST_BYTES {
        return Err("request_exceeds_1_mibibyte_limit".into());
    }

    let request: Value = serde_json::from_slice(&input)?;
    let request = apply_core_manifest(request)?;
    let container_violations = container_policy::violations();
    let mut verdict = body_authority::authorize_mind_runtime_with_container_io(
        &request,
        container_violations.is_empty(),
    );
    for violation in container_violations {
        verdict.allowed = false;
        verdict.disposition = "HOLD_MIND_RUNTIME".to_string();
        verdict.reasons.push(violation.to_string());
    }
    let permission: architect_runtime_permission::ArchitectRuntimePermission =
        serde_json::from_str(ARCHITECT_PERMISSION)?;
    let audit = architect_runtime_permission::apply(
        &mut verdict,
        &permission,
        &request,
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)?
            .as_secs(),
    );
    let mut response = serde_json::to_value(&verdict)?;
    response["architect_permission"] = serde_json::to_value(audit)?;
    serde_json::to_writer(io::stdout().lock(), &response)?;
    println!();
    Ok(())
}

fn apply_core_manifest(mut request: Value) -> Result<Value, Box<dyn std::error::Error>> {
    let manifest: BodyCoreManifest = serde_json::from_str(CORE_MANIFEST)?;
    if manifest.schema != "aios_body_core_manifest_v1"
        || manifest.expected_cores.is_empty()
        || manifest.expected_cores.iter().any(String::is_empty)
    {
        return Err("body_core_manifest_invalid".into());
    }
    let mut sorted = manifest.expected_cores.clone();
    sorted.sort();
    sorted.dedup();
    if sorted.len() != manifest.expected_cores.len() {
        return Err("body_core_manifest_contains_duplicates".into());
    }
    let cores = serde_json::to_value(manifest.expected_cores)?;
    request["expected_cores"] = cores;
    Ok(request)
}

#[cfg(test)]
mod tests {
    use super::apply_core_manifest;
    use serde_json::json;

    #[test]
    fn caller_cannot_replace_body_core_inventory() {
        let request = json!({"expected_cores":["caller_core"]});
        let bound = apply_core_manifest(request).expect("valid embedded manifest");
        assert_eq!(bound["expected_cores"].as_array().unwrap().len(), 19);
        assert!(!bound["expected_cores"]
            .as_array()
            .unwrap()
            .contains(&json!("caller_core")));
    }
}
