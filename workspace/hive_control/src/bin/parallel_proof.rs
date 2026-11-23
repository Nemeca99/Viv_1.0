//! Independent file jobs followed by dependency-gated composition.
use hive_control::graph::{AgentKind, TaskGraph, TaskSpec};
use hive_control::sha;
use serde_json::json;
use std::fs;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

fn now_ns() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos()
}

fn spec(id: &str, deps: &[&str]) -> TaskSpec {
    TaskSpec {
        id: id.into(),
        agent_id: format!("stamp-{id}"),
        agent_kind: AgentKind::Deterministic,
        capability: "write-own-file".into(),
        objective: format!("Write the bounded {id} artifact"),
        depends_on: deps.iter().map(|x| (*x).into()).collect(),
    }
}

fn main() -> Result<(), String> {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let out = root.join("runs").join(format!("parallel-{}", now_ns()));
    fs::create_dir_all(&out).map_err(|e| e.to_string())?;
    let mut graph = TaskGraph::new();
    graph.add_batch(vec![
        spec("F", &["D", "E"]),
        spec("E", &["C"]),
        spec("D", &["A", "B"]),
        spec("A", &[]),
        spec("B", &[]),
        spec("C", &[]),
    ])?;
    let events = Arc::new(Mutex::new(Vec::new()));
    let mut cohorts = Vec::new();
    while !graph.ready().is_empty() {
        cohorts.push(graph.ready());
        let results = graph.run_ready_parallel(|task| {
            let start = now_ns();
            let text = match task.id.as_str() {
                "A" | "B" | "C" => {
                    thread::sleep(Duration::from_millis(100));
                    format!("{}\n", task.id)
                }
                "D" => {
                    let a = fs::read_to_string(out.join("A.txt")).map_err(|e| e.to_string())?;
                    let b = fs::read_to_string(out.join("B.txt")).map_err(|e| e.to_string())?;
                    format!("{a}{b}")
                }
                "E" => fs::read_to_string(out.join("C.txt")).map_err(|e| e.to_string())?,
                "F" => {
                    let d = fs::read_to_string(out.join("D.txt")).map_err(|e| e.to_string())?;
                    let e = fs::read_to_string(out.join("E.txt")).map_err(|e| e.to_string())?;
                    format!("{d}{e}")
                }
                _ => return Err("unadmitted file task".into()),
            };
            fs::write(out.join(format!("{}.txt", task.id)), text).map_err(|e| e.to_string())?;
            events.lock().map_err(|e| e.to_string())?.push(json!({
                "task_id": task.id, "start_ns": start, "finish_ns": now_ns(),
            }));
            Ok(0)
        })?;
        if let Some((id, Err(error))) = results.into_iter().find(|(_, result)| result.is_err()) {
            return Err(format!("task {id} failed: {error}"));
        }
    }
    let final_text = fs::read_to_string(out.join("F.txt")).map_err(|e| e.to_string())?;
    if final_text != "A\nB\nC\n" {
        return Err("final composition mismatch".into());
    }
    let events = Arc::try_unwrap(events)
        .map_err(|_| "event log still shared")?
        .into_inner()
        .map_err(|e| e.to_string())?;
    let first: Vec<_> = events
        .iter()
        .filter(|event| ["A", "B", "C"].contains(&event["task_id"].as_str().unwrap_or("")))
        .collect();
    let max_start = first
        .iter()
        .map(|event| event["start_ns"].as_u64().unwrap())
        .max()
        .unwrap();
    let min_end = first
        .iter()
        .map(|event| event["finish_ns"].as_u64().unwrap())
        .min()
        .unwrap();
    let overlap = max_start < min_end;
    if !overlap {
        return Err("independent file tasks did not overlap".into());
    }
    let mut files = serde_json::Map::new();
    for id in ["A", "B", "C", "D", "E", "F"] {
        files.insert(
            format!("{id}.txt"),
            json!(sha(
                &fs::read(out.join(format!("{id}.txt"))).map_err(|e| e.to_string())?
            )),
        );
    }
    let receipt = json!({"schema": "hive_parallel_file_proof_v1", "status": "PASS",
        "scope": "scheduler and file-composition proof; no Mind model or encrypted task snapshots",
        "cohorts": cohorts, "first_cohort_overlapped": overlap,
        "events": events, "final_text": final_text, "file_sha256": files,
        "task_graph": graph.records()});
    let receipt_path = out.join("run_receipt.json");
    fs::write(
        &receipt_path,
        serde_json::to_vec_pretty(&receipt).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())?;
    println!(
        "{}",
        json!({"status": "PASS", "receipt": receipt_path,
                           "cohorts": receipt["cohorts"], "first_cohort_overlapped": overlap})
    );
    Ok(())
}
