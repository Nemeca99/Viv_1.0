//! Deterministic admission gate for topology-anchored integer-RNN candidates.
//! It consumes a learning receipt and never edits the topology or candidate.

use serde_json::Value;
use std::{env, fs, process};

fn deny(reason: &str) -> ! {
    eprintln!("RNN_GATE_DENY {reason}");
    process::exit(1);
}

fn main() {
    let path = env::args().nth(1).unwrap_or_else(|| deny("receipt path required"));
    let bytes = fs::read(&path).unwrap_or_else(|_| deny("receipt unreadable"));
    let receipt: Value = serde_json::from_slice(&bytes).unwrap_or_else(|_| deny("receipt invalid JSON"));
    if receipt["schema"] != "viv-integer-rnn-learning-receipt-v1" {
        deny("schema mismatch");
    }
    if receipt["status"] != "PASS" || receipt["evaluation"]["passed"] != true {
        deny("held-out evaluation did not pass");
    }
    let margin = receipt["evaluation"]["held_out_margin"].as_i64().unwrap_or(-1);
    if margin <= 0 {
        deny("held-out margin is not positive");
    }
    for field in ["candidate_weights_sha256", "topology_sha256"] {
        let value = receipt[field].as_str().unwrap_or("");
        if value.len() != 64 || !value.chars().all(|c| c.is_ascii_hexdigit()) {
            deny("integrity hash missing or malformed");
        }
    }
    if receipt["verified_receipt_ids"].as_array().map_or(true, |ids| ids.is_empty()) {
        deny("verified receipt lineage missing");
    }
    let stability = &receipt["stability"];
    if stability["total_runs"].as_u64().unwrap_or(0) < 30
        || stability["positive_runs"].as_u64().unwrap_or(0) != stability["total_runs"].as_u64().unwrap_or(0)
        || stability["margin_min"].as_i64().unwrap_or(0) <= 0
        || stability["relative_margin_min"].as_f64().unwrap_or(0.0) < 0.0005
    {
        deny("multi-route stability or relative-margin criterion failed");
    }
    println!("RNN_GATE_ALLOW margin={margin} receipt={path}");
}
