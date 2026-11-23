//! Immutable synthetic semantics and independently pinned issuer checks.
//! Trust is host/bootstrap-owned, never parsed from the candidate API.
use super::contract::{digest, evidence_hash, Candidate, Encoder, Fact, ACTION};
use crate::federation_crypto;
use serde::{Deserialize, Serialize};

pub const UNIVERSE: &str = "viv-fixture-universe-v1";
pub const NAMESPACE: &str = "synthetic-facts";
pub const MAX_TTL: u64 = 300;

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct IssuerPin {
    pub id: String,
    pub public_key_hex: String,
    pub public_key_sha256: String,
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Trust {
    pub capability: IssuerPin,
    pub evidence: IssuerPin,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Rejection {
    pub state: &'static str,
    pub reason: &'static str,
}
pub fn fail(reason: &'static str) -> Rejection {
    Rejection {
        state: "FAIL",
        reason,
    }
}
pub fn hold(reason: &'static str) -> Rejection {
    Rejection {
        state: "HOLD",
        reason,
    }
}

pub fn policy_hash(trust: &Trust) -> String {
    let mut bytes = Encoder::domain("VIV/FIXTURE/POLICY/1");
    for text in [
        UNIVERSE,
        NAMESPACE,
        ACTION,
        "fixture:block-1",
        "color",
        "blue",
        &trust.capability.id,
        &trust.capability.public_key_sha256,
        &trust.evidence.id,
        &trust.evidence.public_key_sha256,
    ] {
        bytes.text(text);
    }
    bytes.number(MAX_TTL);
    digest(&bytes.finish())
}

fn verify_pin(pin: &IssuerPin) -> Result<(), Rejection> {
    let bytes = hex::decode(&pin.public_key_hex).map_err(|_| hold("TRUST_PIN_INVALID"))?;
    if digest(&bytes) != pin.public_key_sha256 || pin.id.is_empty() {
        return Err(hold("TRUST_PIN_INVALID"));
    }
    Ok(())
}
fn verify_signature(pin: &IssuerPin, bytes: &[u8], signature: &str) -> Result<(), Rejection> {
    match federation_crypto::verify(&pin.public_key_hex, bytes, signature) {
        Ok(true) => Ok(()),
        Ok(false) => Err(fail("SIGNATURE_INVALID")),
        Err(_) => Err(hold("SIGNATURE_VERIFIER_ERROR")),
    }
}
fn fresh(issued: u64, expires: u64, now: u64) -> Result<(), Rejection> {
    if !matches!(expires.checked_sub(issued), Some(1..=MAX_TTL)) || now < issued || now >= expires {
        return Err(hold("ENVELOPE_TIME"));
    }
    Ok(())
}

/// Host clock is passed by the Rust orchestrator, not obtained from packet.
/// This is pre-adjudication; store must re-run it under transaction lock.
/// Returning Ok is INTERNAL ONLY, never a transferable public PASS.
pub fn adjudicate(packet: &Candidate, trust: &Trust, now: u64) -> Result<(), Rejection> {
    verify_pin(&trust.capability)?;
    verify_pin(&trust.evidence)?;
    if trust.capability.id == trust.evidence.id
        || trust.capability.public_key_sha256 == trust.evidence.public_key_sha256
    {
        return Err(hold("ISSUER_ROLES_NOT_SEPARATE"));
    }
    if packet.universe != UNIVERSE || packet.namespace != NAMESPACE || packet.action != ACTION {
        return Err(fail("FIXTURE_SCOPE"));
    }
    if packet.candidate_sha256 != packet.payload.hash()
        || packet.provenance_sha256 != packet.provenance.hash()
    {
        return Err(fail("CONTENT_HASH_MISMATCH"));
    }
    if packet.provenance.origin != "probabilistic_candidate" {
        return Err(fail("PROVENANCE_ORIGIN"));
    }
    let grant = &packet.authorization;
    if grant.issuer_id != trust.capability.id {
        return Err(hold("UNKNOWN_CAPABILITY_ISSUER"));
    }
    if grant.schema != "viv_fixture_grant_v1" || grant.role != "fixture_capability" {
        return Err(fail("GRANT_SCHEMA_ROLE"));
    }
    if grant.request_id != packet.request_id
        || grant.nonce != packet.nonce
        || grant.action != packet.action
        || grant.universe != packet.universe
        || grant.namespace != packet.namespace
        || grant.candidate_id != packet.candidate_id
        || grant.candidate_sha256 != packet.candidate_sha256
        || grant.provenance_sha256 != packet.provenance_sha256
        || grant.evidence_sha256 != evidence_hash(&packet.evidence)
        || grant.expected_generation != packet.expected_generation
        || grant.expected_head_sha256 != packet.expected_head_sha256
    {
        return Err(fail("GRANT_BINDING"));
    }
    if grant.policy_sha256 != policy_hash(trust) {
        return Err(hold("POLICY_MISMATCH"));
    }
    if grant.sequence == 0 || grant.sequence > i64::MAX as u64 {
        return Err(fail("GRANT_SEQUENCE"));
    }
    fresh(grant.issued_at, grant.expires_at, now)?;
    verify_signature(
        &trust.capability,
        &grant.signing_bytes(),
        &grant.signature_hex,
    )?;
    if packet.evidence.is_empty() {
        return Err(hold("MISSING_EVIDENCE"));
    }
    let supported = Fact {
        object: "fixture:block-1".into(),
        predicate: "color".into(),
        value: "blue".into(),
    };
    for evidence in &packet.evidence {
        if evidence.issuer_id != trust.evidence.id {
            return Err(hold("UNKNOWN_EVIDENCE_ISSUER"));
        }
        if evidence.schema != "viv_fixture_evidence_v1"
            || evidence.role != "fixture_oracle"
            || evidence.universe != UNIVERSE
        {
            return Err(fail("EVIDENCE_SCOPE"));
        }
        if evidence.sequence == 0 || evidence.sequence > i64::MAX as u64 {
            return Err(fail("EVIDENCE_SEQUENCE"));
        }
        fresh(evidence.issued_at, evidence.expires_at, now)?;
        verify_signature(
            &trust.evidence,
            &evidence.signing_bytes(),
            &evidence.signature_hex,
        )?;
        if evidence.fact != supported || evidence.fact != packet.payload {
            return Err(fail("FALSE_OR_UNSUPPORTED_FIXTURE_FACT"));
        }
    }
    Ok(())
}
