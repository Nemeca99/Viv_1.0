//! End-to-end autonomous proof:
//! 1. Viv-Mind (GPU, Qwen3-8B via Ollama) autonomously decomposes high-level Architect goal into TaskGraph.
//! 2. Rust Control Core validates and admits plan structure, sealing tasks with AEAD encryption.
//! 3. Resource-capped CPU Swarm execution (stage preparation + Python and Rust specialists).
//! 4. Static quality, semantic, and compile checks; model-produced source is never executed.
//! 5. Viv-Mind synthesizes verified receipt for final voice utterance ("One Mouth").

use hive_control::graph::{AgentKind, TaskGraph, TaskSpec};
use hive_control::{sha, Control};
use serde::Deserialize;
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::env;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::{SystemTime, UNIX_EPOCH};

#[allow(dead_code)]
#[derive(Clone, Deserialize, Debug)]
struct PlannedTask {
    id: String,
    capability: String,
    objective: String,
    depends_on: Vec<String>,
    #[serde(default)]
    target_file: Option<String>,
}

#[allow(dead_code)]
#[derive(Deserialize, Debug)]
struct SwarmPlan {
    intent: String,
    tasks: Vec<PlannedTask>,
}

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

fn mind_bridge(python: &Path, script: &Path, request: &Value) -> Result<Value, String> {
    let mut child = Command::new(python)
        .arg(script)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("start mind bridge: {e}"))?;
    let mut input = child.stdin.take().ok_or("mind bridge stdin unavailable")?;
    serde_json::to_writer(&mut input, request).map_err(|e| e.to_string())?;
    input.write_all(b"\n").map_err(|e| e.to_string())?;
    drop(input);
    let output = child.wait_with_output().map_err(|e| e.to_string())?;
    if !output.status.success() {
        return Err(format!(
            "mind bridge failed: {}",
            String::from_utf8_lossy(&output.stderr)
        ));
    }
    serde_json::from_slice(&output.stdout).map_err(|e| format!("mind JSON decode error: {e}"))
}

fn has_ancestor(start: &str, target: &str, tasks: &BTreeMap<String, PlannedTask>) -> bool {
    let mut queue = vec![start.to_string()];
    let mut seen = std::collections::BTreeSet::new();
    while let Some(curr) = queue.pop() {
        if !seen.insert(curr.clone()) {
            continue;
        }
        if let Some(t) = tasks.get(&curr) {
            for dep in &t.depends_on {
                if dep == target {
                    return true;
                }
                queue.push(dep.clone());
            }
        }
    }
    false
}

fn validate_and_build_graph(plan: &SwarmPlan) -> Result<TaskGraph, String> {
    if plan.tasks.len() != 4 {
        return Err(format!(
            "expected exactly four coding-proof tasks, got {}",
            plan.tasks.len()
        ));
    }
    let allowed_caps = [
        "stage-input-source",
        "execute-python-task",
        "execute-rust-task",
        "verify-cohort",
    ];
    let mut ids = BTreeMap::new();
    for t in &plan.tasks {
        if !allowed_caps.contains(&t.capability.as_str()) {
            return Err(format!("unadmitted capability: {}", t.capability));
        }
        if ids.insert(t.id.clone(), t.clone()).is_some() {
            return Err(format!("duplicate task id: {}", t.id));
        }
    }
    let required = [
        ("stage-prep", "stage-input-source"),
        ("py-task", "execute-python-task"),
        ("rust-task", "execute-rust-task"),
        ("verify-cohort", "verify-cohort"),
    ];
    for (id, capability) in required {
        if ids.get(id).map(|task| task.capability.as_str()) != Some(capability) {
            return Err(format!("missing or mismatched required task: {id}"));
        }
    }

    // Verify Cohort 2 dependency rule: verify-cohort must depend (directly or transitively) on all other tasks
    let ver_task = ids
        .get("verify-cohort")
        .ok_or("missing mandatory verify-cohort task")?;
    for (id, _) in &ids {
        if id != "verify-cohort"
            && !ver_task.depends_on.contains(id)
            && !has_ancestor("verify-cohort", id, &ids)
        {
            return Err(format!("verify-cohort must depend on {id}"));
        }
    }

    let mut graph = TaskGraph::new();
    let specs: Vec<TaskSpec> = plan
        .tasks
        .iter()
        .map(|t| {
            let is_model = t.id == "py-task" || t.id == "rust-task";
            TaskSpec {
                id: t.id.clone(),
                agent_id: if is_model {
                    let lang = if t.id == "py-task" { "python" } else { "rust" };
                    format!("viv-{lang}-specialist")
                } else {
                    format!("rust-{}", t.id)
                },
                agent_kind: if is_model {
                    AgentKind::Model
                } else {
                    AgentKind::Deterministic
                },
                capability: t.capability.clone(),
                objective: t.objective.clone(),
                depends_on: t.depends_on.clone(),
            }
        })
        .collect();
    graph.add_batch(specs)?;
    Ok(graph)
}

struct FailureReceiptGuard {
    run_dir: PathBuf,
    committed: bool,
}

impl FailureReceiptGuard {
    fn new(run_dir: PathBuf) -> Self {
        Self {
            run_dir,
            committed: false,
        }
    }

    fn commit(&mut self) {
        self.committed = true;
    }
}

impl Drop for FailureReceiptGuard {
    fn drop(&mut self) {
        if self.committed {
            return;
        }
        let artifacts: BTreeMap<String, String> = fs::read_dir(&self.run_dir)
            .into_iter()
            .flatten()
            .filter_map(Result::ok)
            .filter_map(|entry| {
                let path = entry.path();
                if !path.is_file()
                    || matches!(
                        path.file_name()?.to_str()?,
                        "run_receipt.json" | "run_receipt.sha256"
                    )
                {
                    return None;
                }
                let name = path.file_name()?.to_string_lossy().into_owned();
                let bytes = fs::read(path).ok()?;
                Some((name, sha(&bytes)))
            })
            .collect();
        let failure = json!({
            "schema": "mind_swarm_autonomous_proof_v1",
            "status": "HOLD",
            "run_dir": self.run_dir.display().to_string(),
            "failure": "execution exited before PASS receipt was committed",
            "preserved_artifact_sha256": artifacts,
            "finished_at_unix_ns": now_ns()
        });
        if let Ok(bytes) = serde_json::to_vec_pretty(&failure) {
            let receipt_path = self.run_dir.join("run_receipt.json");
            if fs::write(&receipt_path, &bytes).is_ok() {
                let _ = fs::write(
                    self.run_dir.join("run_receipt.sha256"),
                    format!("{}  run_receipt.json\n", sha(&bytes)),
                );
            }
        }
    }
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .ok_or("cannot find workspace root")?
        .to_path_buf();

    let out = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("runs")
        .join(format!("mind-swarm-autonomous-{}", now_ns()));
    fs::create_dir_all(&out)?;
    let mut receipt_guard = FailureReceiptGuard::new(out.clone());

    let python_tools = root.join(".hive_proof_env/Scripts/python.exe");
    let python_cuda = root.join("hive_voice/.venv/Scripts/python.exe");
    let mind_bridge_script = root.join("hive_control/mind_swarm_bridge.py");
    let switchboard_script = root.join("hive_control/switchboard.py");

    let goal = "Implement and prove increment in Python and Rust";
    println!("=== Viv-Mind Swarm Autonomous Proof ===");
    println!("1. Mind Planning Phase (GPU, Qwen3-8B via Ollama)...");

    let mind_plan_res = mind_bridge(
        &python_tools,
        &mind_bridge_script,
        &json!({
            "phase": "plan",
            "goal": goal
        }),
    )?;

    fs::write(
        out.join("mind_plan_transcript.json"),
        serde_json::to_vec_pretty(&mind_plan_res)?,
    )?;

    let parsed_plan = mind_plan_res["parsed"].clone();
    println!("   Mind intent: {}", parsed_plan["intent"]);
    let plan: SwarmPlan = serde_json::from_value(parsed_plan.clone())
        .map_err(|e| format!("plan deserialization: {e}"))?;

    println!("2. Rust Control Core Admission & TaskGraph Construction...");
    let mut graph = validate_and_build_graph(&plan)?;
    let mut control = Control::new(vec![
        ("stage-input-source".into(), "isolated-swarm".into()),
        ("execute-python-task".into(), "isolated-swarm".into()),
        ("execute-rust-task".into(), "isolated-swarm".into()),
        ("verify-cohort".into(), "isolated-swarm".into()),
    ]);

    let mut accepted_hashes: BTreeMap<String, String> = BTreeMap::new();
    let mut events = Vec::new();
    let mut cohort_idx = 1;

    while !graph.ready().is_empty() {
        let ready = graph.ready();
        println!("3. Executing Cohort {} (Tasks: {:?})...", cohort_idx, ready);
        let mut packets = BTreeMap::new();

        for id in &ready {
            let record = graph
                .records()
                .into_iter()
                .find(|row| &row.spec.id == id)
                .ok_or("ready task missing from records")?;

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

        let output_events = Arc::new(Mutex::new(Vec::new()));
        let shared = Arc::clone(&output_events);

        let out_dir = out.clone();
        let py_cuda = python_cuda.clone();
        let sw_script = switchboard_script.clone();

        // CPU-resident 1.7B workers each need several GiB of system RAM, so
        // execute this proof's ready cohort one worker at a time.
        let results = graph.run_ready_sequential(|spec| {
            let start = now_ns();
            let packet = packets.get(&spec.id).ok_or("missing prepared packet")?;

            if spec.id == "verify-cohort" {
                // Statically verify bounded Cohort 1 outputs; never execute model code.
                let py_json: Value = serde_json::from_str(&fs::read_to_string(out_dir.join("py-task.json")).map_err(|e| e.to_string())?).map_err(|e| e.to_string())?;
                let rust_json: Value = serde_json::from_str(&fs::read_to_string(out_dir.join("rust-task.json")).map_err(|e| e.to_string())?).map_err(|e| e.to_string())?;

                let py_code = py_json["result"].as_str().ok_or("missing python code")?;
                let rust_code = rust_json["result"].as_str().ok_or("missing rust code")?;

                let py_check = switchboard(
                    &py_cuda,
                    &sw_script,
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
                    return Err(format!("Python static verification failed: {:?}", py_check["error"]));
                }

                let rust_check = switchboard(
                    &py_cuda,
                    &sw_script,
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
                    return Err(format!("Rust static verification failed: {:?}", rust_check["error"]));
                }

                let ver_report = json!({
                    "status": "PASS",
                    "python_verified_cases": py_check["case_count"],
                    "python_quality_checks": py_check["quality_checks"],
                    "python_execution": py_check["execution"],
                    "rust_verified_cases": rust_check["case_count"],
                    "rust_quality_checks": rust_check["quality_checks"],
                    "rust_execution": rust_check["execution"],
                    "verified_at_ns": now_ns()
                });
                let artifact_file = out_dir.join("verify-cohort.json");
                let report_bytes = serde_json::to_vec_pretty(&ver_report).map_err(|e| e.to_string())?;
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
                let prep_res = switchboard(
                    &py_cuda,
                    &sw_script,
                    &json!({
                        "op": "stage_prepare",
                        "source": "template_rebuild/reference/fixture_echo.py"
                    }),
                )?;
                if prep_res["status"] != "PASS" {
                    return Err(format!("stage_prepare failed: {:?}", prep_res));
                }
                let artifact_file = out_dir.join("stage-prep.json");
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
                let lang = if spec.id == "py-task" { "python" } else { "rust" };
                let prompt = if lang == "python" {
                    "Python: Implement exactly increment(value) to return value plus one. Return only that function as result string. No extra code.".to_string()
                } else {
                    "Rust: Implement exactly increment(value) to return value plus one. Return only that function as result string. No extra code.".to_string()
                };
                let infer_res = switchboard(
                    &py_cuda,
                    &sw_script,
                    &json!({
                        "op": "specialist_infer",
                        "language": lang,
                        "prompt": prompt
                    }),
                )?;
                let worker_device = infer_res["worker_device"]
                    .as_str()
                    .ok_or("specialist inference omitted its device receipt")?;
                if worker_device != "cpu" {
                    return Err(format!("Swarm task escaped CPU placement: {worker_device}"));
                }
                let parsed = &infer_res["parsed"];
                if parsed.is_null() || parsed["status"] != "PASS" {
                    return Err(format!("{lang} specialist output did not pass contract"));
                }
                let artifact_file = out_dir.join(format!("{}.json", spec.id));
                let parsed_bytes = serde_json::to_vec_pretty(parsed).map_err(|e| e.to_string())?;
                fs::write(&artifact_file, &parsed_bytes).map_err(|e| e.to_string())?;

                shared.lock().unwrap().push(json!({
                    "task_id": spec.id,
                    "status": "PASS",
                    "packet": packet,
                    "worker_device": worker_device,
                    "specialist_run": infer_res["specialist_run"],
                    "active_adapters": infer_res["active_adapters"],
                    "trainable_parameter_count": infer_res["trainable_parameter_count"],
                    "normalization_steps": infer_res["normalization_steps"],
                    "start_ns": start,
                    "finish_ns": now_ns(),
                    "output_sha256": sha(&parsed_bytes),
                    "generation_count": 1
                }));
                Ok(1)
            }
        });

        let committed = results.map_err(|e| format!("cohort execution error: {e}"))?;
        for (id, res) in committed {
            res.map_err(|e| format!("task {id} commit failed: {e}"))?;
        }
        drop(shared);
        let completed = Arc::try_unwrap(output_events)
            .map_err(|_| "event log still shared")?
            .into_inner()
            .map_err(|e| e.to_string())?;

        for ev in completed {
            let task_id = ev["task_id"].as_str().unwrap().to_string();
            let hash = ev
                .get("artifact_sha256")
                .or_else(|| ev.get("output_sha256"))
                .unwrap()
                .as_str()
                .unwrap()
                .to_string();
            accepted_hashes.insert(task_id, hash);
            events.push(ev);
        }
        cohort_idx += 1;
    }

    println!("4. Viv-Mind One Mouth Speech Synthesis...");
    let final_synthesis = mind_bridge(
        &python_tools,
        &mind_bridge_script,
        &json!({
            "phase": "final",
            "verified_result": {
                "status": "PASS",
                "python_verified_cases": 6,
                "python_quality_checks": ["bounded AST contract", "Ruff lint", "Ruff format"],
                "rust_verified_cases": 6,
                "rust_quality_checks": ["bounded source grammar", "rustfmt", "rustc metadata compile"],
                "model_code_executed": false,
                "cohort_count": cohort_idx - 1
            }
        }),
    )?;

    let spoken_text = final_synthesis["raw"]
        .as_str()
        .unwrap_or("All tasks verified.");
    println!("   Synthesized Utterance: \"{}\"", spoken_text);

    let receipt = json!({
        "schema": "mind_swarm_autonomous_proof_v1",
        "status": "PASS",
        "goal": goal,
        "run_dir": out,
        "foreman_snapshot_id": mind_plan_res["foreman_snapshot_id"],
        "plan": parsed_plan,
        "events": events,
        "final_speech": {
            "spoken_text": spoken_text,
            "raw_response": final_synthesis
        }
    });

    let receipt_path = out.join("run_receipt.json");
    let receipt_bytes = serde_json::to_vec_pretty(&receipt)?;
    fs::write(&receipt_path, &receipt_bytes)?;
    fs::write(
        out.join("run_receipt.sha256"),
        format!("{}  run_receipt.json\n", sha(&receipt_bytes)),
    )?;
    receipt_guard.commit();
    println!("=== Proof Complete ===");
    println!("Receipt saved to: {}", receipt_path.display());
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn coding_plan() -> SwarmPlan {
        SwarmPlan {
            intent: "Implement increment in Python and Rust".into(),
            tasks: vec![
                PlannedTask {
                    id: "stage-prep".into(),
                    capability: "stage-input-source".into(),
                    objective: "Prepare the bounded proof input".into(),
                    depends_on: vec![],
                    target_file: None,
                },
                PlannedTask {
                    id: "py-task".into(),
                    capability: "execute-python-task".into(),
                    objective: "Implement Python increment".into(),
                    depends_on: vec!["stage-prep".into()],
                    target_file: None,
                },
                PlannedTask {
                    id: "rust-task".into(),
                    capability: "execute-rust-task".into(),
                    objective: "Implement Rust increment".into(),
                    depends_on: vec!["stage-prep".into()],
                    target_file: None,
                },
                PlannedTask {
                    id: "verify-cohort".into(),
                    capability: "verify-cohort".into(),
                    objective: "Check both implementations".into(),
                    depends_on: vec!["stage-prep".into(), "py-task".into(), "rust-task".into()],
                    target_file: None,
                },
            ],
        }
    }

    #[test]
    fn coding_plan_admits_only_the_four_scoped_tasks() {
        let graph = validate_and_build_graph(&coding_plan()).unwrap();
        assert_eq!(graph.ready(), ["stage-prep"]);
    }

    #[test]
    fn coding_plan_rejects_an_unrequested_aios_task() {
        let mut plan = coding_plan();
        plan.tasks.push(PlannedTask {
            id: "aios-task".into(),
            capability: "execute-aios-task".into(),
            objective: "Unrequested policy task".into(),
            depends_on: vec!["stage-prep".into()],
            target_file: None,
        });
        assert!(validate_and_build_graph(&plan).is_err());
    }

    #[test]
    fn coding_plan_rejects_a_capability_mismatch() {
        let mut plan = coding_plan();
        plan.tasks[1].capability = "execute-rust-task".into();
        assert!(validate_and_build_graph(&plan).is_err());
    }

    #[test]
    fn incomplete_run_writes_hold_receipt_and_hashes_partial_evidence() {
        let run_dir = std::env::temp_dir().join(format!("hive-run-guard-{}", now_ns()));
        fs::create_dir_all(&run_dir).unwrap();
        let evidence = run_dir.join("mind_plan_transcript.json");
        fs::write(&evidence, b"{\"plan\":\"partial\"}").unwrap();
        let evidence_hash = sha(&fs::read(&evidence).unwrap());

        {
            let _guard = FailureReceiptGuard::new(run_dir.clone());
        }

        let receipt_path = run_dir.join("run_receipt.json");
        let receipt: Value = serde_json::from_slice(&fs::read(&receipt_path).unwrap()).unwrap();
        assert_eq!(receipt["status"], "HOLD");
        assert_eq!(
            receipt["preserved_artifact_sha256"]["mind_plan_transcript.json"],
            evidence_hash
        );
        let sidecar = fs::read_to_string(run_dir.join("run_receipt.sha256")).unwrap();
        assert!(sidecar.starts_with(&sha(&fs::read(receipt_path).unwrap())));
        let temp_root = std::env::temp_dir().canonicalize().unwrap();
        let resolved_run = run_dir.canonicalize().unwrap();
        assert!(resolved_run.starts_with(&temp_root));
        assert!(resolved_run
            .file_name()
            .is_some_and(|name| name.to_string_lossy().starts_with("hive-run-guard-")));
        fs::remove_dir_all(resolved_run).unwrap();
    }
}
