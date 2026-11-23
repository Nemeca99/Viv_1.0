use super::contract::{digest, Candidate, Encoder};
use super::policy::{hold, IssuerPin, Rejection};
use crate::federation_crypto;
use serde::{Deserialize, Serialize};

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReceiptIdentity {
    pub pin: IssuerPin,
    pub protected_private_key_hex: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Receipt {
    pub schema: String,
    pub admission_id: String,
    pub packet_sha256: String,
    pub candidate_sha256: String,
    pub policy_sha256: String,
    pub previous_head: String,
    pub generation: u64,
    pub adjudicated_at: u64,
    pub state: String,
    pub host_key_sha256: String,
    pub signature_hex: String,
}
impl Receipt {
    pub fn signing_bytes(&self) -> Vec<u8> {
        let mut out = Encoder::domain("VIV/FIXTURE/RECEIPT/1");
        for v in [
            &self.schema,
            &self.admission_id,
            &self.packet_sha256,
            &self.candidate_sha256,
            &self.policy_sha256,
            &self.previous_head,
        ] {
            out.text(v);
        }
        out.number(self.generation);
        out.number(self.adjudicated_at);
        out.text(&self.state);
        out.text(&self.host_key_sha256);
        out.finish()
    }
    pub fn hash(&self) -> String {
        let mut out = Encoder::domain("VIV/FIXTURE/LEDGER-HEAD/1");
        out.bytes(&self.signing_bytes());
        out.text(&self.signature_hex);
        digest(&out.finish())
    }
}
pub fn admission_id(packet: &Candidate) -> String {
    let mut out = Encoder::domain("VIV/FIXTURE/ADMISSION-ID/1");
    out.text(&packet.universe);
    out.text(&packet.request_id);
    out.text(&packet.hash());
    digest(&out.finish())
}
pub fn make(
    packet: &Candidate,
    policy: &str,
    previous: &str,
    generation: u64,
    now: u64,
    identity: &ReceiptIdentity,
) -> Result<Receipt, Rejection> {
    let mut receipt = Receipt {
        schema: "viv_fixture_receipt_v1".into(),
        admission_id: admission_id(packet),
        packet_sha256: packet.hash(),
        candidate_sha256: packet.candidate_sha256.clone(),
        policy_sha256: policy.into(),
        previous_head: previous.into(),
        generation,
        adjudicated_at: now,
        state: "PASS".into(),
        host_key_sha256: identity.pin.public_key_sha256.clone(),
        signature_hex: String::new(),
    };
    receipt.signature_hex = federation_crypto::sign_protected(
        &identity.pin.id,
        &identity.protected_private_key_hex,
        &receipt.signing_bytes(),
    )
    .map_err(|_| hold("REQUIRED_RECEIPT_SIGNING_FAILED"))?;
    verify(&receipt, &identity.pin)?;
    Ok(receipt)
}
pub fn verify(receipt: &Receipt, pin: &IssuerPin) -> Result<(), Rejection> {
    let public = hex::decode(&pin.public_key_hex).map_err(|_| hold("RECEIPT_PIN_INVALID"))?;
    if digest(&public) != pin.public_key_sha256
        || receipt.host_key_sha256 != pin.public_key_sha256
        || receipt.schema != "viv_fixture_receipt_v1"
        || receipt.state != "PASS"
    {
        return Err(hold("RECEIPT_BINDING_INVALID"));
    }
    match federation_crypto::verify(
        &pin.public_key_hex,
        &receipt.signing_bytes(),
        &receipt.signature_hex,
    ) {
        Ok(true) => Ok(()),
        _ => Err(hold("RECEIPT_SIGNATURE_INVALID")),
    }
}
