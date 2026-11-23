//! Fixture-only wire contract. No policy decision or persistence lives here.
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

pub const SCHEMA: &str = "viv_durable_candidate_v1";
pub const ACTION: &str = "ADMIT_FIXTURE_FACT_V1";
pub const MAX_PACKET: usize = 65_536;
pub const MAX_EVIDENCE: usize = 8;
pub const ZERO_HASH: &str = "0000000000000000000000000000000000000000000000000000000000000000";

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Fact {
    pub object: String,
    pub predicate: String,
    pub value: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Provenance {
    pub origin: String,
    pub producer: String,
    pub input_sha256: String,
    pub source_ref: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Evidence {
    pub schema: String,
    pub issuer_id: String,
    pub role: String,
    pub universe: String,
    pub fact: Fact,
    pub sequence: u64,
    pub issued_at: u64,
    pub expires_at: u64,
    pub signature_hex: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Grant {
    pub schema: String,
    pub issuer_id: String,
    pub role: String,
    pub grant_id: String,
    pub request_id: String,
    pub nonce: String,
    pub action: String,
    pub universe: String,
    pub namespace: String,
    pub candidate_id: String,
    pub candidate_sha256: String,
    pub provenance_sha256: String,
    pub evidence_sha256: String,
    pub expected_generation: u64,
    pub expected_head_sha256: String,
    pub policy_sha256: String,
    pub sequence: u64,
    pub issued_at: u64,
    pub expires_at: u64,
    pub signature_hex: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Candidate {
    pub schema: String,
    pub action: String,
    pub request_id: String,
    pub nonce: String,
    pub universe: String,
    pub namespace: String,
    pub candidate_id: String,
    pub payload: Fact,
    pub candidate_sha256: String,
    pub expected_generation: u64,
    pub expected_head_sha256: String,
    pub provenance: Provenance,
    pub provenance_sha256: String,
    pub evidence: Vec<Evidence>,
    pub authorization: Grant,
}

/// Typed, explicit field ordering. Domain and every string are byte-length
/// prefixed; integers are unsigned big endian. No delimiter ambiguity or floats.
#[derive(Default)]
pub struct Encoder(Vec<u8>);
impl Encoder {
    pub fn domain(domain: &str) -> Self {
        let mut out = Self::default();
        out.text(domain);
        out
    }
    pub fn text(&mut self, value: &str) {
        self.number(value.len() as u64);
        self.0.extend_from_slice(value.as_bytes());
    }
    pub fn number(&mut self, value: u64) {
        self.0.extend_from_slice(&value.to_be_bytes());
    }
    pub fn bytes(&mut self, value: &[u8]) {
        self.number(value.len() as u64);
        self.0.extend_from_slice(value);
    }
    pub fn finish(self) -> Vec<u8> {
        self.0
    }
}

pub fn digest(bytes: &[u8]) -> String {
    hex::encode_upper(Sha256::digest(bytes))
}
pub fn valid_hash(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'A'..=b'F').contains(&b))
}
pub fn valid_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"-_:/.".contains(&b))
}
fn fact_into(out: &mut Encoder, fact: &Fact) {
    out.text(&fact.object);
    out.text(&fact.predicate);
    out.text(&fact.value);
}
impl Fact {
    pub fn canonical(&self) -> Vec<u8> {
        let mut out = Encoder::domain("VIV/FIXTURE/FACT/1");
        fact_into(&mut out, self);
        out.finish()
    }
    pub fn hash(&self) -> String {
        digest(&self.canonical())
    }
}
impl Provenance {
    pub fn canonical(&self) -> Vec<u8> {
        let mut out = Encoder::domain("VIV/FIXTURE/PROVENANCE/1");
        out.text(&self.origin);
        out.text(&self.producer);
        out.text(&self.input_sha256);
        out.text(&self.source_ref);
        out.finish()
    }
    pub fn hash(&self) -> String {
        digest(&self.canonical())
    }
}
impl Evidence {
    pub fn signing_bytes(&self) -> Vec<u8> {
        let mut out = Encoder::domain("VIV/FIXTURE/EVIDENCE/1");
        out.text(&self.schema);
        out.text(&self.issuer_id);
        out.text(&self.role);
        out.text(&self.universe);
        fact_into(&mut out, &self.fact);
        out.number(self.sequence);
        out.number(self.issued_at);
        out.number(self.expires_at);
        out.finish()
    }
}
pub fn evidence_hash(evidence: &[Evidence]) -> String {
    let mut out = Encoder::domain("VIV/FIXTURE/EVIDENCE-SET/1");
    out.number(evidence.len() as u64);
    for item in evidence {
        out.bytes(&item.signing_bytes());
        out.text(&item.signature_hex);
    }
    digest(&out.finish())
}
impl Grant {
    pub fn signing_bytes(&self) -> Vec<u8> {
        let mut out = Encoder::domain("VIV/FIXTURE/GRANT/1");
        for value in [
            &self.schema,
            &self.issuer_id,
            &self.role,
            &self.grant_id,
            &self.request_id,
            &self.nonce,
            &self.action,
            &self.universe,
            &self.namespace,
            &self.candidate_id,
            &self.candidate_sha256,
            &self.provenance_sha256,
            &self.evidence_sha256,
        ] {
            out.text(value);
        }
        out.number(self.expected_generation);
        out.text(&self.expected_head_sha256);
        out.text(&self.policy_sha256);
        out.number(self.sequence);
        out.number(self.issued_at);
        out.number(self.expires_at);
        out.finish()
    }
}
impl Candidate {
    pub fn canonical(&self) -> Vec<u8> {
        let mut out = Encoder::domain("VIV/FIXTURE/CANDIDATE/1");
        for value in [
            &self.schema,
            &self.action,
            &self.request_id,
            &self.nonce,
            &self.universe,
            &self.namespace,
            &self.candidate_id,
        ] {
            out.text(value);
        }
        out.bytes(&self.payload.canonical());
        out.text(&self.candidate_sha256);
        out.number(self.expected_generation);
        out.text(&self.expected_head_sha256);
        out.bytes(&self.provenance.canonical());
        out.text(&self.provenance_sha256);
        out.text(&evidence_hash(&self.evidence));
        out.bytes(&self.authorization.signing_bytes());
        out.text(&self.authorization.signature_hex);
        out.finish()
    }
    pub fn hash(&self) -> String {
        digest(&self.canonical())
    }
}

/// JSON is only the bounded transport envelope; canonical typed bytes above
/// are the signature/hash representation. Serde structs reject duplicate
/// known keys and unknown fields at every nested level; end rejects trailing
/// documents. No Value/map parsing can silently collapse duplicate fields.
pub fn parse_packet(raw: &[u8]) -> Result<Candidate, &'static str> {
    if raw.is_empty() || raw.len() > MAX_PACKET {
        return Err("PACKET_SIZE");
    }
    let mut parser = serde_json::Deserializer::from_slice(raw);
    let packet = Candidate::deserialize(&mut parser).map_err(|_| "PACKET_SCHEMA")?;
    parser.end().map_err(|_| "PACKET_TRAILING")?;
    if packet.schema != SCHEMA || packet.action != ACTION {
        return Err("PACKET_SCHEMA");
    }
    if packet.evidence.len() > MAX_EVIDENCE {
        return Err("EVIDENCE_SIZE");
    }
    let ids = [
        &packet.request_id,
        &packet.nonce,
        &packet.universe,
        &packet.namespace,
        &packet.candidate_id,
        &packet.payload.object,
        &packet.payload.predicate,
        &packet.payload.value,
        &packet.provenance.producer,
        &packet.provenance.source_ref,
    ];
    if ids.iter().any(|v| !valid_id(v)) {
        return Err("IDENTIFIER");
    }
    let hashes = [
        &packet.candidate_sha256,
        &packet.expected_head_sha256,
        &packet.provenance_sha256,
        &packet.provenance.input_sha256,
    ];
    if hashes.iter().any(|v| !valid_hash(v)) {
        return Err("HASH_FORMAT");
    }
    if packet.expected_generation > i64::MAX as u64 {
        return Err("INTEGER_RANGE");
    }
    let grant = &packet.authorization;
    if [
        &grant.issuer_id,
        &grant.grant_id,
        &grant.request_id,
        &grant.nonce,
    ]
    .iter()
    .any(|v| !valid_id(v))
    {
        return Err("GRANT_IDENTIFIER");
    }
    for evidence in &packet.evidence {
        if !valid_id(&evidence.issuer_id)
            || evidence.signing_bytes().len() > 4096
            || evidence.signature_hex.len() > 128
        {
            return Err("EVIDENCE_SIZE");
        }
    }
    if grant.signing_bytes().len() > 8192 || grant.signature_hex.len() > 128 {
        return Err("GRANT_SIZE");
    }
    Ok(packet)
}
