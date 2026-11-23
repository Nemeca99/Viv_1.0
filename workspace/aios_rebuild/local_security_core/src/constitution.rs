//! Constitution surface — primes + laws as machine-readable doctrine.

use crate::axioms::{
    self, AxiomSummary, AXIOM_SCHEMA_VERSION, CORE_TRUTH_DRIVE_ID,
    TRUSTED_EPISTEMIC_AUTHORITY_KEY_HASHES,
};
use crate::laws::{effective_dormancy_threshold, ARCHITECT, CRITICAL_S_N, LAWS, PRIMES};
use serde::Serialize;

#[derive(Debug, Serialize)]
pub struct ConstitutionSummary {
    pub architect: String,
    pub version: String,
    pub dormancy_threshold: f64,
    pub critical_s_n: f64,
    pub primes: Vec<String>,
    pub laws: Vec<String>,
    pub axiom_schema_version: String,
    pub core_truth_drive_id: String,
    pub axiom_registry_sha256: String,
    pub trusted_epistemic_authority_count: usize,
    pub proven_impossible_admission_open: bool,
    pub axioms: Vec<AxiomSummary>,
}

pub fn summary(version: &str) -> ConstitutionSummary {
    ConstitutionSummary {
        architect: ARCHITECT.to_string(),
        version: version.to_string(),
        dormancy_threshold: effective_dormancy_threshold(),
        critical_s_n: CRITICAL_S_N,
        primes: PRIMES.iter().map(|s| (*s).to_string()).collect(),
        laws: LAWS.iter().map(|s| (*s).to_string()).collect(),
        axiom_schema_version: AXIOM_SCHEMA_VERSION.to_string(),
        core_truth_drive_id: CORE_TRUTH_DRIVE_ID.to_string(),
        axiom_registry_sha256: axioms::registry_sha256(),
        trusted_epistemic_authority_count: TRUSTED_EPISTEMIC_AUTHORITY_KEY_HASHES.len(),
        proven_impossible_admission_open: !TRUSTED_EPISTEMIC_AUTHORITY_KEY_HASHES.is_empty(),
        axioms: axioms::registry(),
    }
}
