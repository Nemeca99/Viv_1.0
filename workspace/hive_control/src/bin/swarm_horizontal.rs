//! Bottom-layer horizontal proof: parallel Rust workers, hashed packets, composed outputs.
use hive_control::graph::{AgentKind, TaskGraph, TaskSpec};
use hive_control::{sha, Control};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

fn now_ns() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock before Unix epoch")
        .as_nanos()
}

fn task(id: &str, depends_on: &[&str]) -> TaskSpec {
    TaskSpec {
        id: id.into(),
        agent_id: format!("rust-worker-{id}"),
        agent_kind: AgentKind::Deterministic,
        capability: "write-own-file".into(),
        objective: format!("Write the bounded {id} artifact"),
        depends_on: depends_on.iter().map(|value| (*value).into()).collect(),
    }
}

fn execute(task: TaskSpec, packet: &Value, out: &Path) -> Result<Value, String> {
    if packet["task_id"] != task.id || packet["capability"] != task.capability {
        return Err("prepared packet task/capability mismatch".into());
    }
    let expected_checksum = packet["checksum"]
        .as_str()
        .ok_or("missing packet checksum")?;
    let body = &packet["body"];
    if sha(body.to_string().as_bytes()) != packet["payload_sha256"] {
        return Err("prepared payload hash mismatch".into());
    }
    let mut parent_hashes = BTreeMap::new();
    for parent in &task.depends_on {
        let expected = body["parents"][parent]
            .as_str()
            .ok_or("missing parent checksum")?;
        let current = sha(&fs::read(out.join(format!("{parent}.txt"))).map_err(|e| e.to_string())?);
        if current != expected {
            return Err(format!(
                "parent artifact changed before task action: {parent}"
            ));
        }
        parent_hashes.insert(parent.clone(), expected.to_string());
    }
    let started = now_ns();
    let text = match task.id.as_str() {
        "A" | "B" | "C" => {
            thread::sleep(Duration::from_millis(100));
            format!("{}\n", task.id)
        }
        "D" => format!(
            "{}{}",
            fs::read_to_string(out.join("A.txt")).map_err(|e| e.to_string())?,
            fs::read_to_string(out.join("B.txt")).map_err(|e| e.to_string())?
        ),
        "E" => fs::read_to_string(out.join("C.txt")).map_err(|e| e.to_string())?,
        "F" => format!(
            "{}{}",
            fs::read_to_string(out.join("D.txt")).map_err(|e| e.to_string())?,
            fs::read_to_string(out.join("E.txt")).map_err(|e| e.to_string())?
        ),
        _ => return Err("unadmitted task".into()),
    };
    if !text
        .lines()
        .all(|line| line.len() == 1 && line.bytes().all(|b| b.is_ascii_uppercase()))
    {
        return Err("local output shape failed".into());
    }
    let file = out.join(format!("{}.txt", task.id));
    fs::write(&file, &text).map_err(|e| e.to_string())?;
    let output_hash = sha(text.as_bytes());
    Ok(
        json!({"task_id": task.id, "status": "PASS", "packet": packet,
        "packet_checksum": expected_checksum, "output_text": text,
        "parent_sha256": parent_hashes, "start_ns": started, "finish_ns": now_ns(),
        "output_sha256": output_hash, "generation_count": 0}),
    )
}

fn run(inject_fault: bool) -> Result<PathBuf, String> {
    let out = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("runs")
        .join(format!("swarm-horizontal-{}", now_ns()));
    fs::create_dir_all(&out).map_err(|e| e.to_string())?;
    let mut graph = TaskGraph::new();
    let mut control = Control::new(vec![]);
    graph.add_batch(vec![
        task("F", &["D", "E"]),
        task("E", &["C"]),
        task("D", &["A", "B"]),
        task("A", &[]),
        task("B", &[]),
        task("C", &[]),
    ])?;
    let mut accepted_hashes: BTreeMap<String, String> = BTreeMap::new();
    let mut cohorts = Vec::new();
    let mut events = Vec::new();
    let mut failure = None;
    while !graph.ready().is_empty() {
        let ready = graph.ready();
        cohorts.push(ready.clone());
        let mut packets = BTreeMap::new();
        for id in &ready {
            let record = graph
                .records()
                .into_iter()
                .find(|row| &row.spec.id == id)
                .ok_or("ready task missing")?;
            let parents: BTreeMap<_, _> = record
                .spec
                .depends_on
                .iter()
                .map(|parent| {
                    accepted_hashes
                        .get(parent)
                        .map(|hash| (parent.clone(), hash.clone()))
                        .ok_or("dependency missing accepted hash")
                })
                .collect::<Result<_, _>>()?;
            let changed_parent = parents.iter().find_map(|(parent, expected)| {
                match fs::read(out.join(format!("{parent}.txt"))) {
                    Ok(bytes) if sha(&bytes) == *expected => None,
                    _ => Some(parent.clone()),
                }
            });
            if let Some(parent) = changed_parent {
                graph.claim(id)?;
                graph.fail(id)?;
                let reason = format!("parent artifact changed before dispatch: {parent}");
                events.push(json!({"task_id": id, "status": "HOLD",
                    "objective": record.spec.objective, "parent_sha256": parents,
                    "failure": reason, "generation_count": 0}));
                failure = Some(reason);
                continue;
            }
            let body = json!({"task": record.spec, "parents": parents});
            let checksum = control.seal_task(id, &record.spec.agent_id, None, None, &body)?;
            let opened = control.open_task(id, &record.spec.agent_id, None)?;
            packets.insert(
                id.clone(),
                json!({"task_id": id, "capability": "write-own-file",
                    "checksum": checksum, "payload_sha256": sha(body.to_string().as_bytes()),
                    "body": opened}),
            );
        }
        let output_events = Arc::new(Mutex::new(Vec::new()));
        let shared = Arc::clone(&output_events);
        let results = graph.run_ready_parallel(|spec| {
            let packet = packets.get(&spec.id).ok_or("missing prepared packet")?;
            let result = execute(spec.clone(), packet, &out);
            let event = match &result {
                Ok(event) => event.clone(),
                Err(error) => json!({"task_id": spec.id, "status": "HOLD",
                    "objective": spec.objective, "packet": packet, "failure": error,
                    "generation_count": 0}),
            };
            shared.lock().map_err(|e| e.to_string())?.push(event);
            result.map(|_| 0)
        })?;
        drop(shared);
        let mut cohort_events = Arc::try_unwrap(output_events)
            .map_err(|_| "event log still shared")?
            .into_inner()
            .map_err(|e| e.to_string())?;
        events.append(&mut cohort_events);
        for (id, result) in results {
            match result {
                Ok(()) => {
                    let bytes =
                        fs::read(out.join(format!("{id}.txt"))).map_err(|e| e.to_string())?;
                    let artifact_hash = sha(&bytes);
                    control.complete_task(&id, &format!("rust-worker-{id}"), &artifact_hash)?;
                    accepted_hashes.insert(id, artifact_hash);
                }
                Err(error) => failure = Some(error),
            }
        }
        if failure.is_some() {
            break;
        }
        if inject_fault && cohorts.len() == 1 {
            // Still locally valid text; only the parent checksum exposes the drift.
            fs::write(out.join("A.txt"), b"Z\n").map_err(|e| e.to_string())?;
        }
    }
    let first: Vec<_> = events
        .iter()
        .filter(|event| ["A", "B", "C"].contains(&event["task_id"].as_str().unwrap_or("")))
        .collect();
    let latest_start = first.iter().filter_map(|e| e["start_ns"].as_u64()).max();
    let earliest_finish = first.iter().filter_map(|e| e["finish_ns"].as_u64()).min();
    let overlapped =
        matches!((latest_start, earliest_finish), (Some(start), Some(end)) if start < end);
    if !overlapped {
        failure = Some("independent tasks did not overlap".into());
    }
    let final_text = fs::read_to_string(out.join("F.txt")).ok();
    if !inject_fault && final_text.as_deref() != Some("A\nB\nC\n") {
        failure = Some("final composition mismatch".into());
    }
    let status = if failure.is_none() { "PASS" } else { "HOLD" };
    let mut actual_hashes = BTreeMap::new();
    for id in ["A", "B", "C", "D", "E", "F"] {
        let path = out.join(format!("{id}.txt"));
        if path.exists() {
            actual_hashes.insert(id, sha(&fs::read(path).map_err(|e| e.to_string())?));
        }
    }
    let transcript_path = out.join("task_transcript.jsonl");
    let transcript = events
        .iter()
        .map(|event| serde_json::to_string(event).map_err(|e| e.to_string()))
        .collect::<Result<Vec<_>, _>>()?
        .join("\n")
        + "\n";
    fs::write(&transcript_path, transcript).map_err(|e| e.to_string())?;
    let receipt = json!({"schema": "hive_swarm_horizontal_v1", "status": status,
        "scope": "Rust-only bottom Swarm layer with entropy-bound encrypted task snapshots; no Python bridge or Mind model",
        "fault_injected": inject_fault, "failure": failure,
        "cohorts": cohorts, "first_cohort_overlapped": overlapped,
        "events": events, "task_transcript": transcript_path,
        "accepted_artifact_sha256": accepted_hashes,
        "actual_artifact_sha256": actual_hashes,
        "final_text": final_text, "task_graph": graph.records()});
    let path = out.join("run_receipt.json");
    fs::write(
        &path,
        serde_json::to_vec_pretty(&receipt).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())?;
    Ok(path)
}

fn main() {
    let inject_fault = env::args()
        .skip(1)
        .any(|arg| arg == "--inject-parent-fault");
    match run(inject_fault) {
        Ok(path) => {
            println!("{}", path.display());
            let receipt: Value = serde_json::from_slice(&fs::read(&path).expect("receipt read"))
                .expect("receipt JSON");
            if receipt["status"] != "PASS" {
                std::process::exit(1);
            }
        }
        Err(error) => {
            eprintln!("SWARM_HORIZONTAL_ERROR {error}");
            std::process::exit(2);
        }
    }
}
