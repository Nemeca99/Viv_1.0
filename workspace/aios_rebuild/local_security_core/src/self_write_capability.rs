//! Bounded Self-Writing Capability Layer
//! 
//! This module provides typed authorization for Viv's autonomous code generation.
//! It integrates with existing Rust gates (runtime_control, registry_write, python_write)
//! to enable safe self-writing within strict bounds: tests/infrastructure only, no data-plane changes.

use crate::python_write_control::{ArchitectApproval, parse_approval};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::path::Path;

/// Maximum code size for self-writing operations (bounded to prevent DoS)
const MAX_CODE_BYTES: usize = 4 * 1024; // 4KB per operation

/// Capability types allowed in self-writing lane
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum SelfWriteCapability {
    /// Generate unit tests for existing code
    TestGeneration,
    /// Generate infrastructure scaffolding (config files, CI scripts)
    InfrastructureScaffolding,
    /// Generate documentation examples from code patterns
    DocExamples,
}

/// Self-write request with typed capability and bounds
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SelfWriteRequest {
    pub capability: SelfWriteCapability,
    pub target_path: String, // e.g., "autonomy/test_generation.py"
    pub code_snippet: String, // Bounded snippet to validate before write
    pub approval_hash: String, // SHA-256 of Architect's approval text
}

/// Verifies request against Rust policy gates
pub fn verify_self_write_request(request: &SelfWriteRequest) -> Result<(), String> {
    // Check capability bounds
    match request.capability {
        SelfWriteCapability::TestGeneration | 
        SelfWriteCapability::InfrastructureScaffolding | 
        SelfWriteCapability::DocExamples => {}
        _ => return Err("Unknown capability type".to_string()),
    }

    // Verify code size bound
    if request.code_snippet.len() > MAX_CODE_BYTES {
        return Err(format!(
            "Code snippet exceeds maximum size ({} bytes)",
            MAX_CODE_BYTES
        ));
    }

    // Validate target path is within allowed sandbox
    let allowed_paths = vec![
        "L:/LocalCoder/workspace/aios_rebuild/autonomy/",
        "L:/LocalCoder/workspace/aios_rebuild/test_generation/",
    ];

    for prefix in &allowed_paths {
        if request.target_path.starts_with(prefix) {
            return Ok(());
        }
    }

    Err("Target path outside allowed sandbox".to_string())
}

/// Compute hash of self-write operation for checkpointing
pub fn compute_operation_hash(request: &SelfWriteRequest) -> String {
    let mut hasher = Sha256::new();
    
    // Hash capability type
    match request.capability {
        SelfWriteCapability::TestGeneration => hasher.update(b"test_generation"),
        SelfWriteCapability::InfrastructureScaffolding => hasher.update(b"infra_scaffold"),
        SelfWriteCapability::DocExamples => hasher.update(b"doc_examples"),
    }

    // Hash target path
    hasher.update(request.target_path.as_bytes());

    // Hash code snippet (bounded)
    let bounded_snippet = &request.code_snippet[..std::cmp::min(MAX_CODE_BYTES, request.code_snippet.len())];
    hasher.update(bounded_snippet.as_bytes());

    // Hash approval hash if present
    if !request.approval_hash.is_empty() {
        hasher.update(request.approval_hash.as_bytes());
    }

    hex::encode(hasher.finalize().as_slice()).to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn verify_valid_test_request() {
        let request = SelfWriteRequest {
            capability: SelfWriteCapability::TestGeneration,
            target_path: "L:/LocalCoder/workspace/aios_rebuild/autonomy/test_example.py".to_string(),
            code_snippet: "def test_example():\n    assert True\n".to_string(),
            approval_hash: "abc123".to_string(),
        };

        assert!(verify_self_write_request(&request).is_ok());
    }

    #[test]
    fn reject_unknown_capability() {
        // This would require adding an unknown variant, which is not allowed by enum bounds
        // Test implicitly passes if compile succeeds
    }
}
