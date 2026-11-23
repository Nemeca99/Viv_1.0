//! Compile-time epistemic axioms and evidence-bounded possibility admission.
//!
//! Rust does not claim to prove arbitrary facts about the world. It enforces
//! the narrower security contract: an `IMPOSSIBLE` disposition is inadmissible
//! unless explicit constraints are completely covered by proof-class evidence
//! signed by a CPU evidence authority whose public-key hash is pinned here.

use crate::federation_crypto;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::BTreeSet;

pub const AXIOM_SCHEMA_VERSION: &str = "viv_epistemic_axioms_v1";
pub const POSSIBILITY_REQUEST_SCHEMA: &str = "viv_possibility_assessment_v1";
pub const EVIDENCE_SIGNATURE_SCHEMA: &str = "viv_epistemic_evidence_signature_v1";
pub const CORE_TRUTH_DRIVE_ID: &str = "AX-TRUTH-001";
pub const CORE_TRUTH_DRIVE: &str =
    "Never confuse “unusual, difficult, or unsupported by convention” with “physically impossible.”";

// Deliberately closed in the first release. A later, separately governed
// security release may pin one or more CPU evidence-authority public-key
// hashes here. A caller-supplied key or `VERIFIED` label is never authority.
pub const TRUSTED_EPISTEMIC_AUTHORITY_KEY_HASHES: &[&str] = &[];

const MAX_REQUEST_BYTES: usize = 65_536;
const MAX_PROPOSITION_CHARS: usize = 4_096;
const MAX_CONSTRAINTS: usize = 32;
const MAX_EVIDENCE: usize = 64;
const MAX_PUBLIC_KEY_HEX_CHARS: usize = 4_096;

#[derive(Debug, Clone, Serialize)]
pub struct AxiomSummary {
    pub id: String,
    pub version: u32,
    pub kind: String,
    pub statement: String,
    pub enforcement: String,
}

pub fn registry() -> Vec<AxiomSummary> {
    vec![
        AxiomSummary {
            id: CORE_TRUTH_DRIVE_ID.to_string(),
            version: 1,
            kind: "core_truth_drive".to_string(),
            statement: CORE_TRUTH_DRIVE.to_string(),
            enforcement: "IMPOSSIBLE requires explicit constraints and complete proof-class evidence signed by a Rust-pinned CPU authority."
                .to_string(),
        },
        AxiomSummary {
            id: "AX-TRUTH-002".to_string(),
            version: 1,
            kind: "uncertainty_preservation".to_string(),
            statement: "Absence of a known solution is not proof of impossibility; preserve UNKNOWN."
                .to_string(),
            enforcement: "Missing, untrusted, or insufficient proof cannot be promoted beyond UNKNOWN."
                .to_string(),
        },
        AxiomSummary {
            id: "AX-TRUTH-003".to_string(),
            version: 1,
            kind: "constraint_scope".to_string(),
            statement: "Every impossibility claim is bounded to explicit constraints and scope."
                .to_string(),
            enforcement: "Every declared constraint must be covered by qualifying signed evidence."
                .to_string(),
        },
        AxiomSummary {
            id: "AX-TRUTH-004".to_string(),
            version: 1,
            kind: "contradiction_reopens_inquiry".to_string(),
            statement: "Verified contradictory evidence defeats an impossibility admission and reopens inquiry."
                .to_string(),
            enforcement: "A trusted signed contradiction forces UNKNOWN regardless of supporting evidence."
                .to_string(),
        },
        AxiomSummary {
            id: "AX-LEARN-001".to_string(),
            version: 1,
            kind: "failure_as_evidence".to_string(),
            statement: "Success demonstrates what worked under tested conditions; failure reveals what did not work under tested conditions. Preserve both as evidence."
                .to_string(),
            enforcement: "A failed or mixed candidate remains immutable evidence and cannot be relabeled as success or silently replace its parent."
                .to_string(),
        },
        AxiomSummary {
            id: "AX-DESIGN-001".to_string(),
            version: 1,
            kind: "perfection_by_subtraction".to_string(),
            statement: "Perfection is approached not when nothing remains to add, but when nothing unnecessary remains to remove."
                .to_string(),
            enforcement: "After required behavior is demonstrated, descendants test removal of components that lack measurable capability, safety, or clarity value while preserving reversible evidence."
                .to_string(),
        },
    ]
}

fn sha256_hex(bytes: &[u8]) -> String {
    hex::encode_upper(Sha256::digest(bytes))
}

pub fn registry_sha256() -> String {
    let encoded = serde_json::to_vec(&registry()).expect("static axiom registry serializes");
    sha256_hex(&encoded)
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct EvidenceAuthority {
    schema_version: String,
    authority_id: String,
    public_key_hex: String,
    public_key_sha256: String,
    signature_hex: String,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct PossibilityEvidence {
    evidence_id: String,
    sha256: String,
    proof_kind: String,
    polarity: String,
    covered_constraints: Vec<String>,
    authority: EvidenceAuthority,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct PossibilityAssessmentRequest {
    schema_version: String,
    axiom_id: String,
    claim_id: String,
    proposition: String,
    requested_disposition: String,
    constraints: Vec<String>,
    evidence: Vec<PossibilityEvidence>,
}

#[derive(Debug, Serialize)]
struct CanonicalEvidenceBody {
    schema_version: String,
    axiom_id: String,
    claim_id: String,
    proposition: String,
    requested_disposition: String,
    constraints: Vec<String>,
    evidence_id: String,
    evidence_sha256: String,
    proof_kind: String,
    polarity: String,
    covered_constraints: Vec<String>,
    authority_id: String,
    public_key_sha256: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct PossibilityVerdict {
    pub schema_version: String,
    pub admitted: bool,
    pub requested_disposition: String,
    pub effective_disposition: String,
    pub reason: String,
    pub axiom_id: String,
    pub axiom_registry_sha256: String,
    pub claim_id: String,
    pub constraint_count: usize,
    pub qualifying_evidence_count: usize,
    pub trusted_authority_configured: bool,
    pub decision_id: String,
}

fn verdict(
    request_raw: &str,
    admitted: bool,
    requested: &str,
    effective: &str,
    reason: &str,
    claim_id: &str,
    constraints: usize,
    qualifying: usize,
    trusted_authority_configured: bool,
) -> PossibilityVerdict {
    let registry_hash = registry_sha256();
    let decision_body = format!(
        "{}\n{}\n{}\n{}\n{}\n{}\n{}",
        request_raw,
        admitted,
        requested,
        effective,
        reason,
        registry_hash,
        trusted_authority_configured
    );
    PossibilityVerdict {
        schema_version: POSSIBILITY_REQUEST_SCHEMA.to_string(),
        admitted,
        requested_disposition: requested.to_string(),
        effective_disposition: effective.to_string(),
        reason: reason.to_string(),
        axiom_id: CORE_TRUTH_DRIVE_ID.to_string(),
        axiom_registry_sha256: registry_hash,
        claim_id: claim_id.to_string(),
        constraint_count: constraints,
        qualifying_evidence_count: qualifying,
        trusted_authority_configured,
        decision_id: sha256_hex(decision_body.as_bytes()),
    }
}

fn hold(request_raw: &str, reason: &str, trusted_authority_configured: bool) -> PossibilityVerdict {
    verdict(
        request_raw,
        false,
        "INVALID",
        "HOLD",
        reason,
        "",
        0,
        0,
        trusted_authority_configured,
    )
}

fn valid_identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
}

fn valid_sha256(value: &str) -> bool {
    value.len() == 64 && value.bytes().all(|byte| byte.is_ascii_hexdigit())
}

fn valid_hex(value: &str, max_chars: usize) -> bool {
    !value.is_empty()
        && value.len() <= max_chars
        && value.len() % 2 == 0
        && value.bytes().all(|byte| byte.is_ascii_hexdigit())
}

fn validate_request(request: &PossibilityAssessmentRequest) -> Result<(), &'static str> {
    if request.schema_version != POSSIBILITY_REQUEST_SCHEMA {
        return Err("request_schema_version_mismatch");
    }
    if request.axiom_id != CORE_TRUTH_DRIVE_ID {
        return Err("axiom_id_mismatch");
    }
    if !valid_identifier(request.claim_id.trim()) {
        return Err("claim_id_invalid");
    }
    let proposition = request.proposition.trim();
    if proposition.is_empty() || proposition.chars().count() > MAX_PROPOSITION_CHARS {
        return Err("proposition_invalid");
    }
    if request.constraints.len() > MAX_CONSTRAINTS || request.evidence.len() > MAX_EVIDENCE {
        return Err("request_bounds_exceeded");
    }
    let mut constraints = BTreeSet::new();
    for constraint in &request.constraints {
        let value = constraint.trim();
        if !valid_identifier(value) || !constraints.insert(value) {
            return Err("constraint_id_invalid_or_duplicate");
        }
    }
    let mut evidence_ids = BTreeSet::new();
    for evidence in &request.evidence {
        if !valid_identifier(evidence.evidence_id.trim())
            || !evidence_ids.insert(evidence.evidence_id.trim())
            || !valid_sha256(evidence.sha256.trim())
        {
            return Err("evidence_identity_or_digest_invalid");
        }
        if !valid_identifier(evidence.proof_kind.trim())
            || !valid_identifier(evidence.polarity.trim())
            || evidence.authority.schema_version != EVIDENCE_SIGNATURE_SCHEMA
            || !valid_identifier(evidence.authority.authority_id.trim())
            || !valid_sha256(evidence.authority.public_key_sha256.trim())
            || !valid_hex(
                evidence.authority.public_key_hex.trim(),
                MAX_PUBLIC_KEY_HEX_CHARS,
            )
            || !valid_hex(
                evidence.authority.signature_hex.trim(),
                federation_crypto::FEDERATION_SIGNATURE_HEX_BYTES * 2,
            )
            || evidence.authority.signature_hex.len()
                != federation_crypto::FEDERATION_SIGNATURE_HEX_BYTES * 2
        {
            return Err("evidence_authority_binding_invalid");
        }
        let mut covered = BTreeSet::new();
        for constraint in &evidence.covered_constraints {
            let value = constraint.trim();
            if !constraints.contains(value) || !covered.insert(value) {
                return Err("evidence_constraint_coverage_invalid");
            }
        }
    }
    Ok(())
}

fn is_impossibility_proof(kind: &str) -> bool {
    matches!(
        kind,
        "FORMAL_PROOF"
            | "EXHAUSTIVE_SEARCH"
            | "PHYSICAL_CONSTRAINT"
            | "DETERMINISTIC_CONTRADICTION"
    )
}

fn is_difficulty_evidence(kind: &str) -> bool {
    matches!(
        kind,
        "OBSERVED_OBSTACLE" | "RESOURCE_MEASUREMENT" | "CONVENTIONAL_LIMITATION"
    )
}

fn canonical_evidence_message(
    request: &PossibilityAssessmentRequest,
    evidence: &PossibilityEvidence,
) -> Vec<u8> {
    let mut constraints: Vec<String> = request
        .constraints
        .iter()
        .map(|value| value.trim().to_string())
        .collect();
    constraints.sort();
    let mut covered_constraints: Vec<String> = evidence
        .covered_constraints
        .iter()
        .map(|value| value.trim().to_string())
        .collect();
    covered_constraints.sort();
    let body = CanonicalEvidenceBody {
        schema_version: EVIDENCE_SIGNATURE_SCHEMA.to_string(),
        axiom_id: request.axiom_id.trim().to_string(),
        claim_id: request.claim_id.trim().to_string(),
        proposition: request.proposition.trim().to_string(),
        requested_disposition: request.requested_disposition.trim().to_ascii_uppercase(),
        constraints,
        evidence_id: evidence.evidence_id.trim().to_string(),
        evidence_sha256: evidence.sha256.trim().to_ascii_uppercase(),
        proof_kind: evidence.proof_kind.trim().to_ascii_uppercase(),
        polarity: evidence.polarity.trim().to_ascii_uppercase(),
        covered_constraints,
        authority_id: evidence.authority.authority_id.trim().to_string(),
        public_key_sha256: evidence
            .authority
            .public_key_sha256
            .trim()
            .to_ascii_uppercase(),
    };
    serde_json::to_vec(&body).expect("bounded canonical evidence body serializes")
}

fn evidence_has_trusted_signature(
    request: &PossibilityAssessmentRequest,
    evidence: &PossibilityEvidence,
    trusted_key_hashes: &[&str],
) -> bool {
    let public_key = match hex::decode(evidence.authority.public_key_hex.trim()) {
        Ok(value) => value,
        Err(_) => return false,
    };
    let computed_hash = sha256_hex(&public_key);
    let declared_hash = evidence
        .authority
        .public_key_sha256
        .trim()
        .to_ascii_uppercase();
    if computed_hash != declared_hash
        || !trusted_key_hashes
            .iter()
            .any(|trusted| trusted.eq_ignore_ascii_case(&computed_hash))
    {
        return false;
    }
    federation_crypto::verify(
        evidence.authority.public_key_hex.trim(),
        &canonical_evidence_message(request, evidence),
        evidence.authority.signature_hex.trim(),
    )
    .unwrap_or(false)
}

fn assess_possibility_json_with_trusted_keys(
    request_raw: &str,
    trusted_key_hashes: &[&str],
) -> PossibilityVerdict {
    let authority_configured = !trusted_key_hashes.is_empty();
    if request_raw.len() > MAX_REQUEST_BYTES {
        return hold(request_raw, "request_too_large", authority_configured);
    }
    let request: PossibilityAssessmentRequest = match serde_json::from_str(request_raw) {
        Ok(value) => value,
        Err(_) => return hold(request_raw, "request_schema_invalid", authority_configured),
    };
    if let Err(reason) = validate_request(&request) {
        return hold(request_raw, reason, authority_configured);
    }

    let requested = request.requested_disposition.trim().to_ascii_uppercase();
    let constraint_count = request.constraints.len();
    if requested == "UNKNOWN" {
        return verdict(
            request_raw,
            true,
            &requested,
            "UNKNOWN",
            "uncertainty_preserved",
            &request.claim_id,
            constraint_count,
            0,
            authority_configured,
        );
    }

    if requested != "DIFFICULT" && requested != "IMPOSSIBLE" {
        return hold(
            request_raw,
            "requested_disposition_not_allowlisted",
            authority_configured,
        );
    }
    if constraint_count == 0 {
        let reason = if requested == "IMPOSSIBLE" {
            "impossibility_requires_explicit_constraints"
        } else {
            "difficulty_requires_explicit_constraints"
        };
        return verdict(
            request_raw,
            false,
            &requested,
            "UNKNOWN",
            reason,
            &request.claim_id,
            0,
            0,
            authority_configured,
        );
    }
    if request.evidence.is_empty() {
        let reason = if requested == "IMPOSSIBLE" {
            "impossibility_proof_missing_or_constraint_coverage_incomplete"
        } else {
            "difficulty_not_supported_by_trusted_obstacle_evidence"
        };
        return verdict(
            request_raw,
            false,
            &requested,
            "UNKNOWN",
            reason,
            &request.claim_id,
            constraint_count,
            0,
            authority_configured,
        );
    }
    if !authority_configured {
        return verdict(
            request_raw,
            false,
            &requested,
            "UNKNOWN",
            "trusted_epistemic_authority_unconfigured",
            &request.claim_id,
            constraint_count,
            0,
            false,
        );
    }

    let trusted: Vec<&PossibilityEvidence> = request
        .evidence
        .iter()
        .filter(|evidence| evidence_has_trusted_signature(&request, evidence, trusted_key_hashes))
        .collect();
    if trusted.is_empty() {
        return verdict(
            request_raw,
            false,
            &requested,
            "UNKNOWN",
            "no_evidence_signed_by_trusted_epistemic_authority",
            &request.claim_id,
            constraint_count,
            0,
            true,
        );
    }

    if requested == "DIFFICULT" {
        let qualifying = trusted
            .iter()
            .filter(|evidence| evidence.polarity == "OBSERVED_OBSTACLE")
            .filter(|evidence| is_difficulty_evidence(&evidence.proof_kind))
            .count();
        if qualifying == 0 {
            return verdict(
                request_raw,
                false,
                &requested,
                "UNKNOWN",
                "difficulty_not_supported_by_trusted_obstacle_evidence",
                &request.claim_id,
                constraint_count,
                0,
                true,
            );
        }
        return verdict(
            request_raw,
            true,
            &requested,
            "DIFFICULT",
            "difficulty_supported_within_explicit_constraints",
            &request.claim_id,
            constraint_count,
            qualifying,
            true,
        );
    }

    if trusted
        .iter()
        .any(|evidence| evidence.polarity == "CONTRADICTS_IMPOSSIBILITY")
    {
        return verdict(
            request_raw,
            false,
            &requested,
            "UNKNOWN",
            "trusted_contradiction_reopens_inquiry",
            &request.claim_id,
            constraint_count,
            0,
            true,
        );
    }

    let qualifying: Vec<&&PossibilityEvidence> = trusted
        .iter()
        .filter(|evidence| evidence.polarity == "SUPPORTS_IMPOSSIBILITY")
        .filter(|evidence| is_impossibility_proof(&evidence.proof_kind))
        .collect();
    let covered: BTreeSet<&str> = qualifying
        .iter()
        .flat_map(|evidence| evidence.covered_constraints.iter().map(String::as_str))
        .collect();
    if qualifying.is_empty()
        || request
            .constraints
            .iter()
            .any(|constraint| !covered.contains(constraint.as_str()))
    {
        return verdict(
            request_raw,
            false,
            &requested,
            "UNKNOWN",
            "impossibility_proof_missing_or_constraint_coverage_incomplete",
            &request.claim_id,
            constraint_count,
            qualifying.len(),
            true,
        );
    }

    verdict(
        request_raw,
        true,
        &requested,
        "PROVEN_IMPOSSIBLE",
        "impossibility_admitted_within_explicit_constraints",
        &request.claim_id,
        constraint_count,
        qualifying.len(),
        true,
    )
}

pub fn assess_possibility_json(request_raw: &str) -> PossibilityVerdict {
    assess_possibility_json_with_trusted_keys(request_raw, TRUSTED_EPISTEMIC_AUTHORITY_KEY_HASHES)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::{json, Value};

    fn authority(public_key_hex: &str, public_key_sha256: &str, signature_hex: &str) -> Value {
        json!({
            "schema_version": EVIDENCE_SIGNATURE_SCHEMA,
            "authority_id": "cpu-evidence:test",
            "public_key_hex": public_key_hex,
            "public_key_sha256": public_key_sha256,
            "signature_hex": signature_hex,
        })
    }

    fn evidence(kind: &str, polarity: &str, covered: Vec<&str>, authority: Value) -> Value {
        json!({
            "evidence_id": "evidence:test",
            "sha256": "A".repeat(64),
            "proof_kind": kind,
            "polarity": polarity,
            "covered_constraints": covered,
            "authority": authority,
        })
    }

    fn request(disposition: &str, constraints: Vec<&str>, evidence: Vec<Value>) -> Value {
        json!({
            "schema_version": POSSIBILITY_REQUEST_SCHEMA,
            "axiom_id": CORE_TRUTH_DRIVE_ID,
            "claim_id": "claim:test",
            "proposition": "The bounded task cannot be completed.",
            "requested_disposition": disposition,
            "constraints": constraints,
            "evidence": evidence,
        })
    }

    fn signed_request(disposition: &str, kind: &str, polarity: &str) -> (String, String) {
        let key = federation_crypto::generate_key_material("cpu-evidence:test")
            .expect("Windows CNG key generation must work");
        let mut value = request(
            disposition,
            vec!["energy"],
            vec![evidence(
                kind,
                polarity,
                vec!["energy"],
                authority(
                    &key.public_key_hex,
                    &key.public_key_sha256,
                    &"0".repeat(federation_crypto::FEDERATION_SIGNATURE_HEX_BYTES * 2),
                ),
            )],
        );
        let parsed: PossibilityAssessmentRequest =
            serde_json::from_value(value.clone()).expect("test request parses");
        let signature = federation_crypto::sign_protected(
            "cpu-evidence:test",
            &key.protected_private_key_hex,
            &canonical_evidence_message(&parsed, &parsed.evidence[0]),
        )
        .expect("test evidence signs");
        value["evidence"][0]["authority"]["signature_hex"] = Value::String(signature);
        (value.to_string(), key.public_key_sha256)
    }

    #[test]
    fn registry_contains_exact_architect_truth_drive() {
        assert_eq!(registry()[0].statement, CORE_TRUTH_DRIVE);
        assert_eq!(registry()[0].id, CORE_TRUTH_DRIVE_ID);
        assert_eq!(registry().len(), 6);
        assert!(registry().iter().any(|row| row.id == "AX-LEARN-001"));
        assert!(registry().iter().any(|row| row.id == "AX-DESIGN-001"));
        assert_eq!(registry_sha256().len(), 64);
        assert!(TRUSTED_EPISTEMIC_AUTHORITY_KEY_HASHES.is_empty());
    }

    #[test]
    fn unknown_is_preserved_without_evidence() {
        let result = assess_possibility_json(&request("UNKNOWN", vec![], vec![]).to_string());
        assert!(result.admitted);
        assert_eq!(result.effective_disposition, "UNKNOWN");
    }

    #[test]
    fn caller_verified_label_is_rejected_by_schema() {
        let forged = json!({
            "schema_version": POSSIBILITY_REQUEST_SCHEMA,
            "axiom_id": CORE_TRUTH_DRIVE_ID,
            "claim_id": "claim:test",
            "proposition": "x",
            "requested_disposition": "IMPOSSIBLE",
            "constraints": ["energy"],
            "evidence": [{
                "evidence_id": "evidence:test",
                "sha256": "A".repeat(64),
                "proof_kind": "PHYSICAL_CONSTRAINT",
                "verification_status": "VERIFIED",
                "polarity": "SUPPORTS_IMPOSSIBILITY",
                "covered_constraints": ["energy"]
            }]
        });
        let result = assess_possibility_json(&forged.to_string());
        assert_eq!(result.effective_disposition, "HOLD");
        assert_eq!(result.reason, "request_schema_invalid");
    }

    #[test]
    fn self_signed_arbitrary_key_cannot_authorize_impossibility() {
        let (raw, _) = signed_request(
            "IMPOSSIBLE",
            "PHYSICAL_CONSTRAINT",
            "SUPPORTS_IMPOSSIBILITY",
        );
        let result = assess_possibility_json(&raw);
        assert!(!result.admitted);
        assert_eq!(result.effective_disposition, "UNKNOWN");
        assert_eq!(result.reason, "trusted_epistemic_authority_unconfigured");
        assert!(!result.trusted_authority_configured);
    }

    #[test]
    fn trusted_signed_complete_proof_can_pass_only_in_injected_test_scope() {
        let (raw, trusted_hash) = signed_request(
            "IMPOSSIBLE",
            "PHYSICAL_CONSTRAINT",
            "SUPPORTS_IMPOSSIBILITY",
        );
        let result = assess_possibility_json_with_trusted_keys(&raw, &[&trusted_hash]);
        assert!(result.admitted);
        assert_eq!(result.effective_disposition, "PROVEN_IMPOSSIBLE");
        assert!(result.trusted_authority_configured);
    }

    #[test]
    fn tampering_after_signature_is_rejected() {
        let (raw, trusted_hash) = signed_request(
            "IMPOSSIBLE",
            "PHYSICAL_CONSTRAINT",
            "SUPPORTS_IMPOSSIBILITY",
        );
        let mut value: Value = serde_json::from_str(&raw).unwrap();
        value["proposition"] = Value::String("A different proposition.".to_string());
        let result =
            assess_possibility_json_with_trusted_keys(&value.to_string(), &[&trusted_hash]);
        assert!(!result.admitted);
        assert_eq!(
            result.reason,
            "no_evidence_signed_by_trusted_epistemic_authority"
        );
    }

    #[test]
    fn trusted_contradiction_reopens_inquiry() {
        let (raw, trusted_hash) = signed_request(
            "IMPOSSIBLE",
            "DETERMINISTIC_CONTRADICTION",
            "CONTRADICTS_IMPOSSIBILITY",
        );
        let result = assess_possibility_json_with_trusted_keys(&raw, &[&trusted_hash]);
        assert!(!result.admitted);
        assert_eq!(result.effective_disposition, "UNKNOWN");
        assert_eq!(result.reason, "trusted_contradiction_reopens_inquiry");
    }

    #[test]
    fn malformed_or_unknown_fields_hold() {
        assert_eq!(
            assess_possibility_json("not-json").effective_disposition,
            "HOLD"
        );
        let mut malformed = request("UNKNOWN", vec![], vec![]);
        malformed["unexpected"] = Value::Bool(true);
        assert_eq!(
            assess_possibility_json(&malformed.to_string()).effective_disposition,
            "HOLD"
        );
    }
}
