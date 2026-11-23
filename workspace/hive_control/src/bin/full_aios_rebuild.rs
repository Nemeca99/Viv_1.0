//! Full manifest-driven AIOS candidate assembly through Rust task admission.
//! Model output is limited to an exact DAG/tool-approval proposal. CPU Swarm
//! jobs stamp hash-pinned source files; they do not generate or repair code.

use hive_control::graph::{AgentKind, TaskGraph, TaskSpec};
use hive_control::{sha, Control};
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};
use std::env;
use std::fs;
use std::path::{Component, Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

fn arg(args: &[String], name: &str) -> Result<String, String> {
    let index = args
        .iter()
        .position(|value| value == name)
        .ok_or_else(|| format!("missing argument {name}"))?;
    args.get(index + 1)
        .cloned()
        .ok_or_else(|| format!("missing value for {name}"))
}

fn sha_file(path: &Path) -> Result<String, String> {
    fs::read(path)
        .map(|bytes| sha(&bytes))
        .map_err(|error| format!("read {}: {error}", path.display()))
}

fn safe_relative(text: &str) -> Result<PathBuf, String> {
    let path = Path::new(text);
    if path.as_os_str().is_empty()
        || path.is_absolute()
        || path
            .components()
            .any(|part| !matches!(part, Component::Normal(_)))
    {
        return Err(format!("unsafe manifest path: {text}"));
    }
    Ok(path.to_path_buf())
}

fn field_text<'a>(value: &'a Value, key: &str) -> Result<&'a str, String> {
    value
        .get(key)
        .and_then(Value::as_str)
        .ok_or_else(|| format!("missing string field {key}"))
}

fn core_path(path: &str, names: &[String]) -> Option<String> {
    names
        .iter()
        .find(|name| path.starts_with(&format!("{name}/")))
        .cloned()
}

fn expected_task_rows(manifest: &Value, run_id: &str) -> Result<Vec<TaskSpec>, String> {
    let core_rows = manifest["cores"]
        .as_array()
        .ok_or("manifest cores missing")?;
    let names: Vec<String> = core_rows
        .iter()
        .map(|row| row["name"].as_str().unwrap_or("").to_owned())
        .collect();
    let dependencies = manifest["static_rebuild_graph"]["dependencies"]
        .as_object()
        .ok_or("manifest dependency graph missing")?;
    let mut rows = vec![TaskSpec {
        id: "source_preflight".into(),
        agent_id: "swarm-source-auditor".into(),
        agent_kind: AgentKind::Deterministic,
        capability: "verify-source-baseline".into(),
        objective: "Verify pinned manifest, original source, and staged source hashes".into(),
        depends_on: vec!["mind_plan".into()],
    }];
    for name in &names {
        let mut depends = vec!["source_preflight".to_owned()];
        if let Some(providers) = dependencies.get(name).and_then(Value::as_array) {
            for provider in providers.iter().filter_map(Value::as_str) {
                depends.push(format!("core_{provider}"));
            }
        }
        depends.sort();
        depends.dedup();
        rows.push(TaskSpec {
            id: format!("core_{name}"),
            agent_id: format!("swarm-{name}"),
            agent_kind: AgentKind::Deterministic,
            capability: "stamp-core-files".into(),
            objective: format!("Stamp manifest-listed {name} files into the isolated candidate"),
            depends_on: depends,
        });
    }
    rows.push(TaskSpec {
        id: "workspace_support".into(),
        agent_id: "swarm-workspace-support".into(),
        agent_kind: AgentKind::Deterministic,
        capability: "stamp-support-files".into(),
        objective: "Stamp manifest-listed API/config/docs/scripts/tests and root files".into(),
        depends_on: vec!["source_preflight".into()],
    });
    rows.push(TaskSpec {
        id: "numpy_cupy_bridge".into(),
        agent_id: "swarm-numerical-bridge".into(),
        agent_kind: AgentKind::Deterministic,
        capability: "run-numpy-cupy-proof".into(),
        objective: "Run Rust-Python-NumPy-CuPy-Rust numerical round trip".into(),
        depends_on: vec!["source_preflight".into()],
    });
    let mut final_deps: Vec<String> = names.iter().map(|name| format!("core_{name}")).collect();
    final_deps.extend(["workspace_support".into(), "numpy_cupy_bridge".into()]);
    final_deps.sort();
    rows.push(TaskSpec {
        id: "verify_candidate".into(),
        agent_id: "swarm-integrity-verifier".into(),
        agent_kind: AgentKind::Deterministic,
        capability: "verify-complete-candidate".into(),
        objective: "Verify exact manifest file set, hashes, and Python syntax".into(),
        depends_on: final_deps,
    });
    let _ = run_id;
    Ok(rows)
}

fn same_set(a: &[String], b: &[String]) -> bool {
    a.iter().collect::<BTreeSet<_>>() == b.iter().collect::<BTreeSet<_>>() && a.len() == b.len()
}

fn check_plan(
    plan_transcript: &Value,
    rows: &[TaskSpec],
    manifest_sha256: &str,
    foreman_snapshot_id: &str,
    file_count: usize,
    core_count: usize,
) -> Result<Value, String> {
    if field_text(plan_transcript, "foreman_snapshot_id")? != foreman_snapshot_id {
        return Err("Mind plan Foreman snapshot does not match this run".into());
    }
    let request = plan_transcript
        .get("request")
        .ok_or("Mind plan request envelope missing")?;
    if field_text(request, "model")? != "qwen3:8b-local" {
        return Err("Mind plan model identity mismatch".into());
    }
    let user_text = request["messages"][1]["content"]
        .as_str()
        .ok_or("Mind plan request user payload missing")?;
    let user: Value = serde_json::from_str(user_text)
        .map_err(|error| format!("Mind plan request user payload invalid: {error}"))?;
    if field_text(&user, "source_manifest_sha256")? != manifest_sha256
        || user["catalogued_file_count"].as_u64() != Some(file_count as u64)
        || user["core_count"].as_u64() != Some(core_count as u64)
    {
        return Err("Mind plan request is not bound to the full run manifest".into());
    }
    let requested_contracts = user["task_contracts"]
        .as_array()
        .ok_or("Mind request task contracts missing")?;
    if requested_contracts.len() != rows.len() {
        return Err("Mind request task contracts do not match Rust manifest plan".into());
    }
    let requested_by_id: BTreeMap<&str, &Value> = requested_contracts
        .iter()
        .map(|row| {
            let id = field_text(row, "id")?;
            Ok((id, row))
        })
        .collect::<Result<_, String>>()?;
    if requested_by_id.len() != requested_contracts.len() {
        return Err("Mind request has duplicate task contracts".into());
    }
    for row in rows {
        let requested = requested_by_id
            .get(row.id.as_str())
            .ok_or_else(|| format!("Mind request omitted task {}", row.id))?;
        let required: Vec<String> = requested["required_depends_on"]
            .as_array()
            .ok_or("Mind request required dependencies missing")?
            .iter()
            .map(|value| {
                value
                    .as_str()
                    .map(str::to_owned)
                    .ok_or("Mind request dependency must be a string")
            })
            .collect::<Result<_, _>>()?;
        if !same_set(&required, &row.depends_on) {
            return Err(format!(
                "Mind request required dependencies mismatch for {}",
                row.id
            ));
        }
    }
    let parsed = plan_transcript
        .get("parsed")
        .ok_or("Mind plan has no parsed JSON")?;
    let got = parsed["tasks"]
        .as_array()
        .ok_or("Mind plan tasks missing")?;
    if got.len() < rows.len() || got.len() > rows.len() * 2 {
        return Err(format!(
            "Mind task count {}, expected {} (allowing exact duplicate rows)",
            got.len(),
            rows.len()
        ));
    }
    let expected: BTreeMap<&str, &TaskSpec> =
        rows.iter().map(|row| (row.id.as_str(), row)).collect();
    let valid_dependencies: BTreeSet<&str> = rows
        .iter()
        .map(|row| row.id.as_str())
        .chain(std::iter::once("mind_plan"))
        .collect();
    let mut seen = BTreeMap::<&str, &Value>::new();
    let mut normalized_tasks = Vec::with_capacity(rows.len());
    for item in got {
        let id = item["id"].as_str().ok_or("Mind task id missing")?;
        if !expected.contains_key(id) {
            return Err(format!("Mind added unknown task {id}"));
        }
        if let Some(previous) = seen.get(id) {
            if *previous == item {
                continue;
            }
            return Err(format!("conflicting duplicate Mind task {id}"));
        }
        seen.insert(id, item);
        normalized_tasks.push(item.clone());
        let additions: Vec<String> = item["additional_depends_on"]
            .as_array()
            .ok_or("Mind additional dependencies missing")?
            .iter()
            .map(|v| v.as_str().unwrap_or("").to_owned())
            .collect();
        let addition_set: BTreeSet<&str> = additions.iter().map(String::as_str).collect();
        if addition_set.len() != additions.len()
            || addition_set.contains(id)
            || !addition_set
                .iter()
                .all(|dep| valid_dependencies.contains(dep))
        {
            return Err(format!("Mind added an invalid dependency for {id}"));
        }
        let reason = item["sequencing_reason"]
            .as_str()
            .ok_or("Mind sequencing reason missing")?
            .trim();
        if !(20..=160).contains(&reason.len()) {
            return Err(format!("Mind sequencing reason out of bounds for {id}"));
        }
    }
    if seen.len() != rows.len() {
        return Err(format!(
            "Mind task set {}, expected {}",
            seen.len(),
            rows.len()
        ));
    }
    let approved: Vec<String> = parsed["approved_tools"]
        .as_array()
        .ok_or("Mind tool approvals missing")?
        .iter()
        .map(|v| v.as_str().unwrap_or("").to_owned())
        .collect();
    let required = vec![
        "assemble_candidate".to_owned(),
        "run_numpy_cupy_bridge".to_owned(),
        "verify_candidate".to_owned(),
    ];
    if !same_set(&approved, &required) {
        return Err("Mind tool approvals differ from the bounded allowlist".into());
    }
    let mut normalized = parsed.clone();
    normalized["tasks"] = Value::Array(normalized_tasks);
    Ok(normalized)
}

fn apply_planned_dependencies(plan: &Value, rows: &[TaskSpec]) -> Result<Vec<TaskSpec>, String> {
    let additions: BTreeMap<&str, Vec<String>> = plan["tasks"]
        .as_array()
        .ok_or("Mind task plan missing")?
        .iter()
        .map(|item| {
            let id = item["id"].as_str().ok_or("Mind task id missing")?;
            let deps = item["additional_depends_on"]
                .as_array()
                .ok_or("Mind additional dependencies missing")?
                .iter()
                .map(|value| {
                    value
                        .as_str()
                        .map(str::to_owned)
                        .ok_or("Mind dependency must be a string")
                })
                .collect::<Result<Vec<_>, _>>()?;
            Ok((id, deps))
        })
        .collect::<Result<_, String>>()?;
    rows.iter()
        .map(|row| {
            let mut planned_row = row.clone();
            let additional = additions
                .get(row.id.as_str())
                .ok_or_else(|| format!("Mind omitted task {}", row.id))?
                .clone();
            for dependency in additional {
                if !planned_row.depends_on.contains(&dependency) {
                    planned_row.depends_on.push(dependency);
                }
            }
            planned_row.depends_on.sort();
            planned_row.depends_on.dedup();
            Ok(planned_row)
        })
        .collect()
}

fn run_gpu_bridge(
    exe: &Path,
    python: &Path,
    switchboard: &Path,
    receipt: &Path,
) -> Result<String, String> {
    // CuPy needs a clean VRAM window after the Mind has completed its plan.
    let _ = Command::new("ollama")
        .args(["stop", "qwen3:8b-local"])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
    let result = Command::new(exe)
        .arg(python)
        .arg(switchboard)
        .arg(receipt)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .output()
        .map_err(|e| format!("start GPU bridge: {e}"))?;
    if !result.status.success() {
        return Err(format!(
            "GPU bridge failed: {} {}",
            String::from_utf8_lossy(&result.stdout),
            String::from_utf8_lossy(&result.stderr)
        ));
    }
    let value: Value = serde_json::from_slice(&fs::read(receipt).map_err(|e| e.to_string())?)
        .map_err(|e| e.to_string())?;
    if !valid_gpu_receipt(&value) {
        return Err("GPU bridge receipt did not pass Rust verification".into());
    }
    sha_file(receipt)
}

fn valid_gpu_receipt(value: &Value) -> bool {
    let initial_loss = value["initial_loss"].as_f64();
    let final_loss = value["after_feedback_backprop_loss"].as_f64();
    let samples = value["samples"].as_u64().unwrap_or(0);
    let features = value["features"].as_u64().unwrap_or(0);
    value["proof"] == "rust-python-numpy-roundtrip-v1"
        && value["accepted_by_rust"] == true
        && value["dtype"] == "float64"
        && samples > 0
        && features > 0
        && value["return_shapes"]["X"][0].as_u64() == Some(samples)
        && value["return_shapes"]["X"][1].as_u64() == Some(features)
        && value["return_shapes"]["y"][0].as_u64() == Some(samples)
        && value["return_shapes"]["y"][1].as_u64() == Some(1)
        && initial_loss.is_some_and(f64::is_finite)
        && final_loss.is_some_and(f64::is_finite)
        && final_loss < initial_loss
}

fn perform_task(
    id: &str,
    rows: &[Value],
    source: &Path,
    staged: &Path,
    candidate: &Path,
    names: &[String],
    manifest: &Value,
    gpu: (&Path, &Path, &Path, &Path),
    verifier: (&Path, &Path, &Path),
) -> Result<String, String> {
    if id == "source_preflight" {
        let entries = manifest["files"]
            .as_array()
            .ok_or("manifest files missing")?;
        for row in entries {
            let rel = safe_relative(row["path"].as_str().ok_or("manifest path missing")?)?;
            let expected = row["sha256"].as_str().ok_or("manifest digest missing")?;
            if sha_file(&source.join(&rel))? != expected
                || sha_file(&staged.join(&rel))? != expected
            {
                return Err(format!("source/staged hash mismatch: {}", rel.display()));
            }
        }
        return Ok(sha(entries
            .iter()
            .flat_map(|row| {
                row["sha256"]
                    .as_str()
                    .unwrap_or("")
                    .as_bytes()
                    .iter()
                    .copied()
            })
            .collect::<Vec<_>>()
            .as_slice()));
    }
    if id == "numpy_cupy_bridge" {
        return run_gpu_bridge(gpu.0, gpu.1, gpu.2, gpu.3);
    }
    if id == "verify_candidate" {
        let run = Command::new(verifier.0)
            .arg(verifier.1)
            .arg(verifier.2)
            .arg(source)
            .arg(candidate)
            .output()
            .map_err(|e| format!("start candidate verifier: {e}"))?;
        if !run.status.success() {
            return Err(format!(
                "candidate verifier failed: {}",
                String::from_utf8_lossy(&run.stderr)
            ));
        }
        let receipt: Value = serde_json::from_slice(&run.stdout)
            .map_err(|e| format!("verifier returned invalid JSON: {e}"))?;
        if receipt["status"] != "PASS" {
            return Err(format!("candidate verification held: {receipt}"));
        }
        return Ok(sha(
            &serde_json::to_vec(&receipt).map_err(|e| e.to_string())?
        ));
    }
    let (prefix, support) = if id == "workspace_support" {
        (None, true)
    } else if let Some(name) = id.strip_prefix("core_") {
        (Some(name), false)
    } else {
        return Err(format!("unknown task {id}"));
    };
    let mut output_hashes = Vec::new();
    for row in rows {
        let rel_text = row["path"].as_str().ok_or("manifest path missing")?;
        let belongs = match prefix {
            Some(name) => core_path(rel_text, names).as_deref() == Some(name),
            None if support => core_path(rel_text, names).is_none(),
            None => false,
        };
        if !belongs {
            continue;
        }
        let rel = safe_relative(rel_text)?;
        let expected = row["sha256"].as_str().ok_or("manifest digest missing")?;
        let from = staged.join(&rel);
        let to = candidate.join(&rel);
        if sha_file(&from)? != expected {
            return Err(format!("staged hash changed before stamp: {rel_text}"));
        }
        if to.exists() {
            return Err(format!("candidate path already exists: {rel_text}"));
        }
        if let Some(parent) = to.parent() {
            fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        fs::copy(&from, &to).map_err(|e| format!("stamp {rel_text}: {e}"))?;
        if sha_file(&to)? != expected {
            return Err(format!("candidate hash mismatch after stamp: {rel_text}"));
        }
        output_hashes.extend_from_slice(expected.as_bytes());
    }
    Ok(sha(&output_hashes))
}

fn execute() -> Result<Value, String> {
    let args: Vec<String> = env::args().collect();
    if args.len() < 2 {
        return Err("missing CLI arguments".into());
    }
    let manifest_path = PathBuf::from(arg(&args, "--manifest")?);
    let sidecar_path = PathBuf::from(arg(&args, "--sidecar")?);
    let source = PathBuf::from(arg(&args, "--source")?);
    let staged = PathBuf::from(arg(&args, "--staged")?);
    let candidate = PathBuf::from(arg(&args, "--candidate")?);
    let run_id = arg(&args, "--run-id")?;
    let plan_path = PathBuf::from(arg(&args, "--plan")?);
    let gpu_exe = PathBuf::from(arg(&args, "--gpu-exe")?);
    let python = PathBuf::from(arg(&args, "--gpu-python")?);
    let switchboard = PathBuf::from(arg(&args, "--switchboard")?);
    let verifier_python = PathBuf::from(arg(&args, "--verifier-python")?);
    let verifier = PathBuf::from(arg(&args, "--verifier")?);
    let manifest_bytes = fs::read(&manifest_path).map_err(|e| e.to_string())?;
    let manifest_hash = sha(&manifest_bytes);
    let sidecar = fs::read_to_string(sidecar_path).map_err(|e| e.to_string())?;
    if !sidecar.starts_with(&manifest_hash) {
        return Err("manifest sidecar hash mismatch".into());
    }
    let manifest: Value = serde_json::from_slice(&manifest_bytes).map_err(|e| e.to_string())?;
    if manifest["schema"] != "aios_clean_source_baseline_v1"
        || manifest["source_root"].as_str() != Some(source.to_string_lossy().as_ref())
    {
        return Err("manifest schema/source root mismatch".into());
    }
    if candidate.exists() {
        return Err("candidate directory already exists".into());
    }
    if !candidate
        .to_string_lossy()
        .starts_with("L:\\LocalCoder\\workspace\\aios_rebuild\\rebuild_runs\\")
    {
        return Err("candidate path escapes the approved LocalCoder run root".into());
    }
    let plan_transcript: Value =
        serde_json::from_slice(&fs::read(plan_path).map_err(|e| e.to_string())?)
            .map_err(|e| e.to_string())?;
    let rows = expected_task_rows(&manifest, &run_id)?;
    let parsed = check_plan(
        &plan_transcript,
        &rows,
        &manifest_hash,
        arg(&args, "--foreman-id")?.as_str(),
        manifest["files"]
            .as_array()
            .ok_or("manifest files missing")?
            .len(),
        manifest["cores"]
            .as_array()
            .ok_or("manifest cores missing")?
            .len(),
    )?;
    let rows = apply_planned_dependencies(&parsed, &rows)?;
    let tool_scope = format!("aios_rebuild_runs/{run_id}");
    let mut control = Control::new(vec![
        ("assemble_candidate".into(), tool_scope.clone()),
        ("run_numpy_cupy_bridge".into(), tool_scope.clone()),
        ("verify_candidate".into(), tool_scope.clone()),
    ]);
    for tool in [
        "assemble_candidate",
        "run_numpy_cupy_bridge",
        "verify_candidate",
    ] {
        control.approve_tool(true, tool, &tool_scope)?;
    }
    let mind_hash = sha(&serde_json::to_vec(&parsed).map_err(|e| e.to_string())?);
    control.seal_task("mind_plan", "viv-mind", None, None, &parsed)?;
    control.open_task("mind_plan", "viv-mind", None)?;
    control.complete_task("mind_plan", "viv-mind", &mind_hash)?;
    let mut graph = TaskGraph::new();
    graph.add_batch(vec![TaskSpec {
        id: "mind_plan".into(),
        agent_id: "viv-mind".into(),
        agent_kind: AgentKind::Model,
        capability: "decompose-source-rebuild".into(),
        objective: parsed["intent"]
            .as_str()
            .unwrap_or("Plan full AIOS candidate assembly")
            .into(),
        depends_on: vec![],
    }])?;
    graph.claim("mind_plan")?;
    graph.complete("mind_plan", 1)?;
    graph.add_batch(rows.clone())?;
    let mut task_checksums = BTreeMap::new();
    let mut task_artifacts = BTreeMap::new();
    let mut task_events = Vec::new();
    let entries = manifest["files"]
        .as_array()
        .ok_or("manifest files missing")?;
    let core_names: Vec<String> = manifest["cores"]
        .as_array()
        .ok_or("cores missing")?
        .iter()
        .map(|row| row["name"].as_str().unwrap_or("").into())
        .collect();
    fs::create_dir_all(&candidate).map_err(|e| e.to_string())?;
    loop {
        let ready = graph.ready();
        if ready.is_empty() {
            break;
        }
        for id in &ready {
            let spec = rows
                .iter()
                .find(|row| &row.id == id)
                .ok_or("ready task has no contract")?;
            let mut deps = BTreeMap::new();
            for dep in &spec.depends_on {
                deps.insert(
                    dep.clone(),
                    task_artifacts
                        .get(dep)
                        .cloned()
                        .unwrap_or_else(|| mind_hash.clone()),
                );
            }
            let payload = json!({"run_id":run_id,"manifest_sha256":manifest_hash,"task_id":id,"objective":spec.objective,"depends_on":deps,"source_root":source,"staged_root":staged,"candidate_root":candidate,"allowed_files":entries.iter().filter(|row| if id.starts_with("core_") { core_path(row["path"].as_str().unwrap_or(""), &core_names).as_deref() == id.strip_prefix("core_") } else if id == "workspace_support" { core_path(row["path"].as_str().unwrap_or(""), &core_names).is_none() } else { false }).map(|row|row["path"].clone()).collect::<Vec<_>>()});
            let sum = control.seal_task(
                id,
                &spec.agent_id,
                Some("mind_plan"),
                Some(&mind_hash),
                &payload,
            )?;
            let opened = control.open_task(id, &spec.agent_id, Some(&mind_hash))?;
            if opened != payload {
                return Err(format!("encrypted task payload changed for {id}"));
            }
            task_checksums.insert(id.clone(), sum);
        }
        let outputs = Mutex::new(BTreeMap::<String, (String, u128)>::new());
        let result = graph.run_ready_parallel(|spec| {
            let started = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_nanos();
            match perform_task(
                &spec.id,
                entries,
                &source,
                &staged,
                &candidate,
                &core_names,
                &manifest,
                (
                    &gpu_exe,
                    &python,
                    &switchboard,
                    &candidate.parent().unwrap().join("numpy_cupy_receipt.json"),
                ),
                (&verifier_python, &verifier, &manifest_path),
            ) {
                Ok(hash) => {
                    let elapsed = SystemTime::now()
                        .duration_since(UNIX_EPOCH)
                        .unwrap_or_default()
                        .as_nanos()
                        .saturating_sub(started);
                    outputs
                        .lock()
                        .map_err(|_| "task receipt lock poisoned".to_string())?
                        .insert(spec.id, (hash, elapsed));
                    Ok(0)
                }
                Err(error) => Err(error),
            }
        })?;
        for (id, outcome) in result {
            outcome?;
            let (hash, elapsed) = outputs
                .lock()
                .map_err(|_| "task receipt lock poisoned")?
                .remove(&id)
                .ok_or("task output receipt missing")?;
            let spec = rows
                .iter()
                .find(|row| row.id == id)
                .ok_or("task contract lost")?;
            control.complete_task(&id, &spec.agent_id, &hash)?;
            task_artifacts.insert(id.clone(), hash.clone());
            task_events.push(json!({"task_id":id,"owner":spec.agent_id,"state":"completed","generation_count":0,"snapshot_checksum":task_checksums[&id],"artifact_sha256":hash,"depends_on":spec.depends_on,"elapsed_ns":elapsed}));
        }
    }
    if graph
        .records()
        .iter()
        .any(|row| format!("{:?}", row.state) != "Completed")
    {
        return Err("task graph did not complete".into());
    }
    Ok(
        json!({"schema":"hive_full_aios_rebuild_receipt_v1","status":"PASS","run_id":run_id,"manifest_sha256":manifest_hash,"mind_intent":parsed["intent"],"mind_snapshot_id":plan_transcript["foreman_snapshot_id"],"candidate":candidate,"source_modified":false,"source_code_executed":false,"model_generated_source":false,"core_count":core_names.len(),"catalogued_file_count":entries.len(),"task_count":task_events.len()+1,"model_generation_count":1,"task_events":task_events,"mind_task":{"state":"completed","generation_count":1,"artifact_sha256":mind_hash},"graph":graph.records(),"task_artifact_hashes":task_artifacts,"gpu_bridge_receipt":candidate.parent().unwrap().join("numpy_cupy_receipt.json"),"candidate_verification_task":"verify_candidate"}),
    )
}

fn main() {
    match execute() {
        Ok(receipt) => println!(
            "{}",
            serde_json::to_string(&receipt).unwrap_or_else(|_| "{}".into())
        ),
        Err(error) => {
            eprintln!("FULL_REBUILD_HOLD: {error}");
            std::process::exit(1);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture_rows() -> Vec<TaskSpec> {
        let manifest = json!({
            "cores": [{"name": "alpha_core"}],
            "static_rebuild_graph": {"dependencies": {}}
        });
        expected_task_rows(&manifest, "test-run").unwrap()
    }

    fn valid_transcript(rows: &[TaskSpec]) -> Value {
        let user = json!({
            "source_manifest_sha256":"manifest-hash",
            "catalogued_file_count":1,
            "core_count":1,
            "task_contracts":rows.iter().map(|row| json!({
                "id":row.id,
                "required_depends_on":row.depends_on,
                "objective":row.objective,
            })).collect::<Vec<_>>(),
            "approved_tools":["assemble_candidate","run_numpy_cupy_bridge","verify_candidate"]
        });
        json!({
            "foreman_snapshot_id":"foreman-test-id",
            "request":{
                "model":"qwen3:8b-local",
                "messages":[
                    {"role":"system","content":"test"},
                    {"role":"user","content":user.to_string()}
                ]
            },
            "parsed": {
                "intent": "Assemble pinned source files",
                "tasks": rows.iter().map(|row| json!({
                    "id": row.id,
                    "additional_depends_on": [],
                    "sequencing_reason":"This task follows its required source and dependency checks.",
                })).collect::<Vec<_>>(),
                "approved_tools": ["assemble_candidate", "run_numpy_cupy_bridge", "verify_candidate"]
            }
        })
    }

    #[test]
    fn exact_plan_and_exact_tool_allowlist_are_admitted() {
        let rows = fixture_rows();
        assert!(check_plan(
            &valid_transcript(&rows),
            &rows,
            "manifest-hash",
            "foreman-test-id",
            1,
            1
        )
        .is_ok());
    }

    #[test]
    fn unknown_mind_added_dependency_is_rejected() {
        let rows = fixture_rows();
        let mut plan = valid_transcript(&rows);
        plan["parsed"]["tasks"][0]["additional_depends_on"] = json!(["missing_task"]);
        assert!(check_plan(&plan, &rows, "manifest-hash", "foreman-test-id", 1, 1).is_err());
    }

    #[test]
    fn exact_duplicate_plan_row_is_collapsed_but_conflict_is_rejected() {
        let rows = fixture_rows();
        let mut transcript = valid_transcript(&rows);
        let duplicate = transcript["parsed"]["tasks"][0].clone();
        transcript["parsed"]["tasks"]
            .as_array_mut()
            .unwrap()
            .push(duplicate);
        let normalized =
            check_plan(&transcript, &rows, "manifest-hash", "foreman-test-id", 1, 1).unwrap();
        assert_eq!(normalized["tasks"].as_array().unwrap().len(), rows.len());

        let mut conflicting = valid_transcript(&rows);
        let mut duplicate = conflicting["parsed"]["tasks"][0].clone();
        duplicate["sequencing_reason"] = json!("This conflicting duplicate must be rejected.");
        conflicting["parsed"]["tasks"]
            .as_array_mut()
            .unwrap()
            .push(duplicate);
        assert!(check_plan(
            &conflicting,
            &rows,
            "manifest-hash",
            "foreman-test-id",
            1,
            1
        )
        .is_err());
    }

    #[test]
    fn repeated_required_dependency_is_admitted_as_noop() {
        let rows = fixture_rows();
        let mut transcript = valid_transcript(&rows);
        transcript["parsed"]["tasks"][0]["additional_depends_on"] = json!(["mind_plan"]);
        let parsed =
            check_plan(&transcript, &rows, "manifest-hash", "foreman-test-id", 1, 1).unwrap();
        let planned_rows = apply_planned_dependencies(&parsed, &rows).unwrap();
        assert_eq!(planned_rows[0].depends_on, ["mind_plan"]);
    }

    #[test]
    fn gpu_receipt_requires_matching_shape_and_decreased_finite_loss() {
        let receipt = json!({
            "proof":"rust-python-numpy-roundtrip-v1",
            "accepted_by_rust":true,
            "dtype":"float64",
            "samples":96,
            "features":2,
            "initial_loss":10.0,
            "after_feedback_backprop_loss":0.01,
            "return_shapes":{"X":[96,2],"y":[96,1]}
        });
        assert!(valid_gpu_receipt(&receipt));
        let mut wrong_shape = receipt.clone();
        wrong_shape["return_shapes"]["X"][0] = json!(95);
        assert!(!valid_gpu_receipt(&wrong_shape));
        let mut worse_loss = receipt.clone();
        worse_loss["after_feedback_backprop_loss"] = json!(11.0);
        assert!(!valid_gpu_receipt(&worse_loss));
        let mut nonfinite = receipt;
        nonfinite["initial_loss"] = json!("NaN");
        assert!(!valid_gpu_receipt(&nonfinite));
    }

    #[test]
    fn extra_or_missing_tool_approval_is_rejected() {
        let rows = fixture_rows();
        let mut plan = valid_transcript(&rows);
        plan["parsed"]["approved_tools"] = json!(["assemble_candidate"]);
        assert!(check_plan(&plan, &rows, "manifest-hash", "foreman-test-id", 1, 1).is_err());
    }

    #[test]
    fn full_manifest_and_foreman_snapshot_are_bound_to_mind_request() {
        let rows = fixture_rows();
        let transcript = valid_transcript(&rows);
        assert!(check_plan(
            &transcript,
            &rows,
            "different-manifest",
            "foreman-test-id",
            1,
            1
        )
        .is_err());
        assert!(check_plan(
            &transcript,
            &rows,
            "manifest-hash",
            "different-foreman",
            1,
            1
        )
        .is_err());
    }

    #[test]
    fn mind_added_dependency_changes_the_admitted_execution_graph() {
        let rows = fixture_rows();
        let mut transcript = valid_transcript(&rows);
        let parsed_tasks = transcript["parsed"]["tasks"].as_array_mut().unwrap();
        let workspace = parsed_tasks
            .iter_mut()
            .find(|item| item["id"] == "workspace_support")
            .unwrap();
        workspace["additional_depends_on"] = json!(["core_alpha_core"]);
        workspace["sequencing_reason"] =
            json!("Finish the core files before staging the workspace support layer.");
        let parsed =
            check_plan(&transcript, &rows, "manifest-hash", "foreman-test-id", 1, 1).unwrap();
        let planned_rows = apply_planned_dependencies(&parsed, &rows).unwrap();
        let workspace = planned_rows
            .iter()
            .find(|row| row.id == "workspace_support")
            .unwrap();
        assert!(workspace.depends_on.contains(&"core_alpha_core".to_owned()));
        let mut graph = TaskGraph::new();
        graph
            .add_batch(vec![TaskSpec {
                id: "mind_plan".into(),
                agent_id: "viv-mind".into(),
                agent_kind: AgentKind::Model,
                capability: "plan".into(),
                objective: "Plan all manifest tasks".into(),
                depends_on: vec![],
            }])
            .unwrap();
        graph.claim("mind_plan").unwrap();
        graph.complete("mind_plan", 1).unwrap();
        graph.add_batch(planned_rows).unwrap();
        assert_eq!(graph.ready(), ["source_preflight"]);
        graph.claim("source_preflight").unwrap();
        graph.complete("source_preflight", 0).unwrap();
        assert!(graph.ready().contains(&"core_alpha_core".to_owned()));
        assert!(!graph.ready().contains(&"workspace_support".to_owned()));
    }

    #[test]
    fn path_traversal_and_absolute_manifest_paths_are_rejected() {
        assert!(safe_relative("../secret.txt").is_err());
        assert!(safe_relative("C:/Windows/win.ini").is_err());
        assert!(safe_relative("core/file.py").is_ok());
    }
}
