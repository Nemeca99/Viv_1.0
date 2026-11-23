//! Signed negative decisions are evidence, never an admission capability.
use super::{
    contract::{digest, Candidate, Encoder},
    policy::{hold, IssuerPin, Rejection},
    receipt::ReceiptIdentity,
};
use crate::federation_crypto;
use serde::{Deserialize, Serialize};

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Disposition {
    pub request_id: String,
    pub packet_hash: String,
    pub candidate_hash: String,
    pub policy_hash: String,
    pub state: String,
    pub reason: String,
    pub decided_at: u64,
    pub host_key_hash: String,
    pub signature: String,
}
impl Disposition {
    fn bytes(&self) -> Vec<u8> {
        let mut out = Encoder::domain("VIV/FIXTURE/NEGATIVE-DISPOSITION/1");
        for s in [
            &self.request_id,
            &self.packet_hash,
            &self.candidate_hash,
            &self.policy_hash,
            &self.state,
            &self.reason,
        ] {
            out.text(s);
        }
        out.number(self.decided_at);
        out.text(&self.host_key_hash);
        out.finish()
    }
    pub fn make(
        p: &Candidate,
        policy_hash: String,
        error: &Rejection,
        now: u64,
        key: &ReceiptIdentity,
    ) -> Result<Self, Rejection> {
        let mut out = Self {
            request_id: p.request_id.clone(),
            packet_hash: p.hash(),
            candidate_hash: p.candidate_sha256.clone(),
            policy_hash,
            state: error.state.into(),
            reason: error.reason.into(),
            decided_at: now,
            host_key_hash: key.pin.public_key_sha256.clone(),
            signature: String::new(),
        };
        if !matches!(out.state.as_str(), "FAIL" | "HOLD") {
            return Err(hold("DISPOSITION_STATE"));
        }
        out.signature = federation_crypto::sign_protected(
            &key.pin.id,
            &key.protected_private_key_hex,
            &out.bytes(),
        )
        .map_err(|_| hold("DISPOSITION_SIGNING_FAILED"))?;
        out.verify(&key.pin)?;
        Ok(out)
    }
    pub fn verify(&self, pin: &IssuerPin) -> Result<(), Rejection> {
        let key = hex::decode(&pin.public_key_hex).map_err(|_| hold("DISPOSITION_PIN"))?;
        if digest(&key) != pin.public_key_sha256
            || self.host_key_hash != pin.public_key_sha256
            || !matches!(self.state.as_str(), "FAIL" | "HOLD")
            || self.reason.is_empty()
        {
            return Err(hold("DISPOSITION_BINDING"));
        }
        match federation_crypto::verify(&pin.public_key_hex, &self.bytes(), &self.signature) {
            Ok(true) => Ok(()),
            _ => Err(hold("DISPOSITION_SIGNATURE")),
        }
    }
}
