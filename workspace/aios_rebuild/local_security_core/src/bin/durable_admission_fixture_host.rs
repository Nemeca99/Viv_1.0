//! Isolated, default-off fixture endpoint. No management verbs or caller paths.
use security_core::durable_admission::{
    contract::MAX_PACKET, policy::Trust, receipt::ReceiptIdentity, store::Host,
};
use serde::Deserialize;
use std::{
    io::{self, BufRead, Write},
    path::PathBuf,
};

// Trusted build/controller provisioning, not a candidate-selected environment variable.
const ROOT: &str = match option_env!("VIV_DURABLE_FIXTURE_ROOT") {
    Some(root) => root,
    None => {
        "L:/Continue/Viv/foundation/artifacts/auto/rust_durable_admission_fixture_v0/host_fixture"
    }
};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Bootstrap {
    trust: Trust,
    receipt_identity: ReceiptIdentity,
}

#[derive(Deserialize)]
#[serde(tag = "op", deny_unknown_fields)]
enum Request {
    #[serde(rename = "submit_candidate")]
    Submit { canonical_packet_bytes: String },
    #[serde(rename = "query_request")]
    Query {
        request_id: String,
        candidate_hash: String,
    },
    #[serde(rename = "read_admitted")]
    Read { admission_id: String },
}

fn rejected(reason: &str) -> serde_json::Value {
    serde_json::json!({"state":"HOLD", "reason":reason,
        "authority_scope":"fixture_only",
        "os_isolation":"HOLD_OS_ISOLATION_NOT_PROVEN",
        "production_antirollback":"HOLD_EXTERNAL_MONOTONIC_ANCHOR_NOT_PROVEN"})
}

fn run() -> Result<(), &'static str> {
    if std::env::args_os().len() != 1 {
        return Err("NO_COMMAND_LINE_OVERRIDES");
    }
    let root = PathBuf::from(ROOT);
    let raw = std::fs::read(root.join("bootstrap.json")).map_err(|_| "BOOTSTRAP_UNAVAILABLE")?;
    if raw.len() > MAX_PACKET {
        return Err("BOOTSTRAP_SIZE");
    }
    let bootstrap: Bootstrap = serde_json::from_slice(&raw).map_err(|_| "BOOTSTRAP_INVALID")?;
    let mut host = Host::attach(
        root.join("fixture.sqlite"),
        bootstrap.trust,
        bootstrap.receipt_identity,
    )
    .map_err(|_| "HOST_ATTACH_HOLD")?;
    let input = io::stdin();
    let mut input = input.lock();
    let output = io::stdout();
    let mut output = output.lock();
    loop {
        // Bound memory before allocating an entire untrusted line. Oversize closes endpoint.
        let mut line = Vec::new();
        loop {
            let available = input.fill_buf().map_err(|_| "INPUT_IO")?;
            if available.is_empty() {
                break;
            }
            let count = available
                .iter()
                .position(|b| *b == b'\n')
                .map(|i| i + 1)
                .unwrap_or(available.len());
            if line.len() + count > MAX_PACKET * 2 + 1024 {
                return Err("IPC_SIZE");
            }
            let complete = available[count - 1] == b'\n';
            line.extend_from_slice(&available[..count]);
            input.consume(count);
            if complete {
                break;
            }
        }
        if line.is_empty() {
            return Ok(());
        }
        let response = match serde_json::from_slice::<Request>(&line) {
            Ok(Request::Submit {
                canonical_packet_bytes,
            }) => serde_json::to_value(host.submit_candidate(canonical_packet_bytes.as_bytes()))
                .map_err(|_| "OUTPUT_SERIALIZATION")?,
            Ok(Request::Query {
                request_id,
                candidate_hash,
            }) => serde_json::to_value(host.query_request(&request_id, &candidate_hash))
                .map_err(|_| "OUTPUT_SERIALIZATION")?,
            Ok(Request::Read { admission_id }) => match host.read_admitted(&admission_id) {
                Ok((packet, receipt)) => {
                    serde_json::json!({"state":"PASS", "authority_scope":"fixture_only",
                    "os_isolation":"HOLD_OS_ISOLATION_NOT_PROVEN", "production_antirollback":"HOLD_EXTERNAL_MONOTONIC_ANCHOR_NOT_PROVEN",
                    "packet":packet, "receipt":receipt})
                }
                Err(error) => rejected(error.reason),
            },
            Err(_) => rejected("IPC_SCHEMA"),
        };
        serde_json::to_writer(&mut output, &response).map_err(|_| "OUTPUT_IO")?;
        output
            .write_all(b"\n")
            .and_then(|_| output.flush())
            .map_err(|_| "OUTPUT_IO")?;
    }
}

fn main() {
    if let Err(reason) = run() {
        // No secret material, bootstrap bytes, or caller input in diagnostics.
        eprintln!("fixture host HOLD: {reason}");
        std::process::exit(2);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn only_three_exact_operations() {
        for packet in [
            r#"{"op":"submit_candidate","canonical_packet_bytes":"{}"}"#,
            r#"{"op":"query_request","request_id":"r","candidate_hash":"h"}"#,
            r#"{"op":"read_admitted","admission_id":"a"}"#,
        ] {
            assert!(serde_json::from_str::<Request>(packet).is_ok());
        }
        for packet in [
            r#"{"op":"commit","verdict":"PASS"}"#,
            r#"{"op":"submit_candidate","canonical_packet_bytes":"{}","verdict":"PASS"}"#,
            r#"{"op":"query_request","request_id":"r","candidate_hash":"h","db_path":"elsewhere"}"#,
            r#"{"op":"read_admitted","admission_id":"a","key":"attacker"}"#,
            r#"{"op":"read_admitted","admission_id":"a","clock":0}"#,
            r#"{"op":"query_request","request_id":"r","request_id":"other","candidate_hash":"h"}"#,
            r#"{"op":"read_admitted","admission_id":"a"} {}"#,
        ] {
            assert!(
                serde_json::from_str::<Request>(packet).is_err(),
                "accepted {packet}"
            );
        }
    }
}
