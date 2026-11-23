//! Bottom-up horizontal proof: concurrent LoRA specialist workers, encrypted task packets, and static assertion gates.
use hive_control::graph::{AgentKind, TaskGraph, TaskSpec};
use hive_control::{sha, Control};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::env;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::{SystemTime, UNIX_EPOCH};

fn now_ns() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock before Unix epoch")
        .as_nanos()
}

fn switchboard(python: &Path, script: &Path, request: &Value) -> Result<Value, String> {
    let mut child = Command::new(python)
        .arg(script)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("start switchboard: {e}"))?;
    let mut input = child.stdin.take().ok_or("switchboard stdin unavailable")?;
    serde_json::to_writer(&mut input, request).map_err(|e| e.to_string())?;
    input.write_all(b"\n").map_err(|e| e.to_string())?;
    drop(input);
    let output = child.wait_with_output().map_err(|e| e.to_string())?;
    let response: Value = serde_json::from_slice(&output.stdout).map_err(|e| {
        format!(
            "invalid switchboard JSON: {e}; stderr={}",
            String::from_utf8_lossy(&output.stderr)
        )
    })?;
    if !output.status.success() || response["ok"] != true {
        return Err(format!(
            "switchboard held: {} {}",
            response["error"], response["detail"]
        ));
    }
    Ok(response["result"].clone())
}

fn task(id: &str, lang: &str, depends_on: &[&str], prompt: &str) -> TaskSpec {
    TaskSpec {
        id: id.into(),
        agent_id: format!("viv-{lang}-specialist"),
        agent_kind: AgentKind::Model,
        capability: format!("execute-{lang}-task"),
        objective: prompt.into(),
        depends_on: depends_on.iter().map(|v| (*v).into()).collect(),
    }
}

fn run_proof(python: &Path, script: &Path, inject_fault: bool) -> Result<PathBuf, String> {
    let out = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("runs")
        .join(format!("horizontal-specialists-{}", now_ns()));
    fs::create_dir_all(&out).map_err(|e| e.to_string())?;

    let py_prompt = "Python task: Implement exactly `def increment(value: int) -> int` to return value plus one. Return only that function as the result string. No imports.";
    let rust_prompt = "Rust task: Implement exactly `fn increment(value: i32) -> i32` to return value plus one. Return only that function as the result string. No crates.";

    let mut graph = TaskGraph::new();
    let mut control = Control::new(vec![
        ("stage-input-source".into(), "isolated-swarm".into()),
        ("execute-python-task".into(), "isolated-swarm".into()),
        ("execute-rust-task".into(), "isolated-swarm".into()),
        ("verify-cohort".into(), "isolated-swarm".into()),
    ]);

    // Cohort 1: Independent tasks (Stage 1 preparation + Python specialist + Rust specialist)
    // Cohort 2: Dependent verification and composition task
    graph.add_batch(vec![
        TaskSpec {
            id: "stage-prep".into(),
            agent_id: "rust-file-stager".into(),
            agent_kind: AgentKind::Deterministic,
            capability: "stage-input-source".into(),
            objective: "Stage and verify template_rebuild/reference/fixture_echo.py".into(),
            depends_on: vec![],
        },
        task("py-task", "python", &[], py_prompt),
        task("rust-task", "rust", &[], rust_prompt),
        TaskSpec {
            id: "verify-cohort".into(),
            agent_id: "rust-verifier".into(),
            agent_kind: AgentKind::Deterministic,
            capability: "verify-cohort".into(),
            objective: "Verify both specialist outputs pass bounded static assertions and staged input passed quality".into(),
            depends_on: vec!["stage-prep".into(), "py-task".into(), "rust-task".into()],
        },
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

            // Parent artifact integrity check before dispatch
            let changed_parent = parents.iter().find_map(|(parent, expected)| {
                match fs::read(out.join(format!("{parent}.json"))) {
                    Ok(bytes) if sha(&bytes) == *expected => None,
                    _ => Some(parent.clone()),
                }
            });

            if let Some(parent) = changed_parent {
                graph.claim(id)?;
                graph.fail(id)?;
                let reason = format!("parent artifact changed before dispatch: {parent}");
                events.push(json!({
                    "task_id": id,
                    "status": "HOLD",
                    "objective": record.spec.objective,
                    "parent_sha256": parents,
                    "failure": reason,
                    "generation_count": 0
                }));
                failure = Some(reason);
                continue;
            }

            let body = json!({"task": record.spec, "parents": parents});
            let checksum = control.seal_task(id, &record.spec.agent_id, None, None, &body)?;
            let opened = control.open_task(id, &record.spec.agent_id, None)?;
            packets.insert(
                id.clone(),
                json!({
                    "task_id": id,
                    "capability": record.spec.capability,
                    "checksum": checksum,
                    "payload_sha256": sha(body.to_string().as_bytes()),
                    "body": opened
                }),
            );
        }

        if failure.is_some() {
            break;
        }

        let output_events = Arc::new(Mutex::new(Vec::new()));
        let shared = Arc::clone(&output_events);

        let results = graph.run_ready_parallel(|spec| {
            let start = now_ns();
            let packet = packets.get(&spec.id).ok_or("missing prepared packet")?;
            if spec.id == "verify-cohort" {
                // Read and verify Cohort 1 artifacts
                let py_json: Value = serde_json::from_str(
                    &fs::read_to_string(out.join("py-task.json")).map_err(|e| e.to_string())?,
                )
                .map_err(|e| e.to_string())?;
                let rust_json: Value = serde_json::from_str(
                    &fs::read_to_string(out.join("rust-task.json")).map_err(|e| e.to_string())?,
                )
                .map_err(|e| e.to_string())?;

                let py_code = py_json["result"]
                    .as_str()
                    .ok_or("missing python result code")?;
                let rust_code = rust_json["result"]
                    .as_str()
                    .ok_or("missing rust result code")?;

                let py_check = switchboard(
                    python,
                    script,
                    &json!({
                        "op": "specialist_verify",
                        "language": "python",
                        "code": py_code,
                        "check": {"cases": [
                            {"input": -100, "expected": -99},
                            {"input": -1, "expected": 0},
                            {"input": 0, "expected": 1},
                            {"input": 1, "expected": 2},
                            {"input": 2, "expected": 3},
                            {"input": 100, "expected": 101}
                        ]}
                    }),
                )?;
                if py_check["passed"] != true {
                    return Err(format!(
                        "Python static verification failed: {:?}",
                        py_check["error"]
                    ));
                }

                let rust_check = switchboard(
                    python,
                    script,
                    &json!({
                        "op": "specialist_verify",
                        "language": "rust",
                        "code": rust_code,
                        "check": {"cases": [
                            {"input": -100, "expected": -99},
                            {"input": -1, "expected": 0},
                            {"input": 0, "expected": 1},
                            {"input": 1, "expected": 2},
                            {"input": 2, "expected": 3},
                            {"input": 100, "expected": 101}
                        ]}
                    }),
                )?;
                if rust_check["passed"] != true {
                    return Err(format!(
                        "Rust static verification failed: {:?}",
                        rust_check["error"]
                    ));
                }

                let ver_report = json!({
                    "status": "PASS",
                    "python_verified": true,
                    "rust_verified": true,
                    "verified_at_ns": now_ns()
                });
                let artifact_file = out.join("verify-cohort.json");
                let report_bytes =
                    serde_json::to_vec_pretty(&ver_report).map_err(|e| e.to_string())?;
                fs::write(&artifact_file, &report_bytes).map_err(|e| e.to_string())?;

                shared.lock().unwrap().push(json!({
                    "task_id": spec.id,
                    "status": "PASS",
                    "start_ns": start,
                    "finish_ns": now_ns(),
                    "artifact_sha256": sha(&report_bytes),
                    "generation_count": 0
                }));
                Ok(0)
            } else if spec.id == "stage-prep" {
                // Stage 1 quality preparation of task source
                let prep_res = switchboard(
                    python,
                    script,
                    &json!({
                        "op": "stage_prepare",
                        "source": "template_rebuild/reference/fixture_echo.py"
                    }),
                )?;
                if prep_res["status"] != "PASS" {
                    return Err(format!("Stage 1 file preparation held: {:?}", prep_res));
                }
                let artifact_file = out.join("stage-prep.json");
                let prep_bytes = serde_json::to_vec_pretty(&prep_res).map_err(|e| e.to_string())?;
                fs::write(&artifact_file, &prep_bytes).map_err(|e| e.to_string())?;

                shared.lock().unwrap().push(json!({
                    "task_id": spec.id,
                    "status": "PASS",
                    "packet": packet,
                    "start_ns": start,
                    "finish_ns": now_ns(),
                    "output_sha256": sha(&prep_bytes),
                    "generation_count": 0
                }));
                Ok(0)
            } else {
                // Model worker inference
                let lang = if spec.id == "py-task" {
                    "python"
                } else {
                    "rust"
                };
                let infer_res = switchboard(
                    python,
                    script,
                    &json!({
                        "op": "specialist_infer",
                        "language": lang,
                        "prompt": spec.objective
                    }),
                )?;
                let parsed = &infer_res["parsed"];
                if parsed.is_null() || parsed["status"] != "PASS" {
                    return Err(format!("{lang} worker returned invalid contract"));
                }
                let artifact_file = out.join(format!("{}.json", spec.id));
                let parsed_bytes = serde_json::to_vec_pretty(parsed).map_err(|e| e.to_string())?;
                fs::write(&artifact_file, &parsed_bytes).map_err(|e| e.to_string())?;

                shared.lock().unwrap().push(json!({
                    "task_id": spec.id,
                    "status": "PASS",
                    "packet": packet,
                    "start_ns": start,
                    "finish_ns": now_ns(),
                    "output_sha256": sha(&parsed_bytes),
                    "generation_count": 1
                }));
                Ok(1)
            }
        })?;
        drop(shared);

        let mut cohort_events = Arc::try_unwrap(output_events)
            .map_err(|_| "event log still shared")?
            .into_inner()
            .map_err(|e| e.to_string())?;
        events.append(&mut cohort_events);

        for (id, result) in results {
            match result {
                Ok(_gen_count) => {
                    let bytes =
                        fs::read(out.join(format!("{id}.json"))).map_err(|e| e.to_string())?;
                    let artifact_hash = sha(&bytes);
                    let agent_id = if id == "verify-cohort" {
                        "rust-verifier"
                    } else if id == "stage-prep" {
                        "rust-file-stager"
                    } else if id == "py-task" {
                        "viv-python-specialist"
                    } else {
                        "viv-rust-specialist"
                    };
                    control.complete_task(&id, agent_id, &artifact_hash)?;
                    accepted_hashes.insert(id, artifact_hash);
                }
                Err(error) => failure = Some(error),
            }
        }

        if failure.is_some() {
            break;
        }

        // Inject fault after Cohort 1 if requested
        if inject_fault && cohorts.len() == 1 {
            // Tamper with py-task artifact after local acceptance to test parent drift detection
            fs::write(out.join("py-task.json"), b"{\"tampered\": true}\n")
                .map_err(|e| e.to_string())?;
        }
    }

    let receipt = json!({
        "schema": "hive_horizontal_specialist_proof_v1",
        "status": if failure.is_none() { "PASS" } else { "HOLD" },
        "fault_injected": inject_fault,
        "cohorts": cohorts,
        "events": events,
        "accepted_hashes": accepted_hashes,
        "failure_reason": failure
    });
    let receipt_file = out.join("run_receipt.json");
    fs::write(&receipt_file, serde_json::to_vec_pretty(&receipt).unwrap())
        .map_err(|e| e.to_string())?;
    Ok(receipt_file)
}

fn main() -> Result<(), String> {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let python = root
        .parent()
        .unwrap()
        .join("hive_voice/.venv/Scripts/python.exe");
    let script = root.join("switchboard.py");
    let args: Vec<String> = env::args().collect();
    let fault = args.iter().any(|arg| arg == "--inject-parent-fault");
    let receipt_path = run_proof(&python, &script, fault)?;
    println!("{}", receipt_path.display());
    Ok(())
}
