//! Vague-goal live probe: Viv plans, Rust admits and stamps, receipts retain behavior.
use hive_control::graph::{AgentKind, TaskGraph, TaskSpec};
use hive_control::{sha, Control};
use serde::Deserialize;
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};
use std::env;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{SystemTime, UNIX_EPOCH};

#[derive(Clone, Deserialize)]
struct MindTask {
    id: String,
    capability: String,
    objective: String,
    depends_on: Vec<String>,
    value: String,
}
#[derive(Deserialize)]
struct MindPlan {
    filename: String,
    intent: String,
    tasks: Vec<MindTask>,
}

fn now_ns() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_nanos()
}

fn bridge(python: &Path, script: &Path, input: &Value) -> Result<Value, String> {
    let mut child = Command::new(python)
        .arg(script)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| e.to_string())?;
    child
        .stdin
        .take()
        .ok_or("bridge stdin")?
        .write_all(input.to_string().as_bytes())
        .map_err(|e| e.to_string())?;
    let output = child.wait_with_output().map_err(|e| e.to_string())?;
    if !output.status.success() {
        return Err(format!(
            "Mind bridge: {}",
            String::from_utf8_lossy(&output.stderr)
        ));
    }
    serde_json::from_slice(&output.stdout).map_err(|e| e.to_string())
}

fn ancestor(id: &str, parent: &str, tasks: &BTreeMap<String, MindTask>) -> bool {
    let mut todo = vec![id.to_owned()];
    let mut seen = BTreeSet::new();
    while let Some(node) = todo.pop() {
        if !seen.insert(node.clone()) {
            continue;
        }
        if let Some(task) = tasks.get(&node) {
            for dep in &task.depends_on {
                if dep == parent {
                    return true;
                }
                todo.push(dep.clone());
            }
        }
    }
    false
}

fn validate(plan: &MindPlan) -> Result<TaskGraph, String> {
    if plan.filename.len() > 40
        || !plan.filename.ends_with(".py")
        || !plan
            .filename
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '.')
        || plan.filename.starts_with('.')
    {
        return Err("filename outside isolated Python-file bound".into());
    }
    if plan.intent.trim().is_empty() || plan.intent.len() > 200 {
        return Err("missing or long intent".into());
    }
    if !(3..=5).contains(&plan.tasks.len()) {
        return Err("task count outside bound".into());
    }
    let allowed = [
        "create_file",
        "stamp_print",
        "stamp_function",
        "stamp_call",
        "run_file",
    ];
    let mut ids = BTreeMap::new();
    let mut caps = BTreeMap::new();
    for task in &plan.tasks {
        if !allowed.contains(&task.capability.as_str())
            || task.id.is_empty()
            || task.id.len() > 40
            || !task
                .id
                .chars()
                .all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-')
            || task.objective.trim().is_empty()
            || task.objective.len() > 160
            || task.value.len() > 100
            || !task.value.chars().all(|c| c.is_ascii_graphic() || c == ' ')
        {
            return Err("task outside admitted bounds".into());
        }
        if ids.insert(task.id.clone(), task.clone()).is_some()
            || caps
                .insert(task.capability.clone(), task.id.clone())
                .is_some()
        {
            return Err("duplicate task or capability".into());
        }
    }
    for cap in ["create_file", "run_file"] {
        if !caps.contains_key(cap) {
            return Err(format!("missing {cap}"));
        }
    }
    let prints = caps.contains_key("stamp_print");
    let functions = caps.contains_key("stamp_function");
    if prints == functions
        || (functions && !caps.contains_key("stamp_call"))
        || (prints && caps.contains_key("stamp_call"))
    {
        return Err("choose one executable stamp pattern".into());
    }
    let sequence: Vec<&str> = if prints {
        vec!["create_file", "stamp_print", "run_file"]
    } else {
        vec!["create_file", "stamp_function", "stamp_call", "run_file"]
    };
    if sequence.len() != plan.tasks.len() {
        return Err("extraneous task".into());
    }
    for pair in sequence.windows(2) {
        if !ancestor(&caps[pair[1]], &caps[pair[0]], &ids) {
            return Err(format!("missing dependency {} -> {}", pair[0], pair[1]));
        }
    }
    let mut graph = TaskGraph::new();
    graph.add_batch(
        plan.tasks
            .iter()
            .map(|task| TaskSpec {
                id: task.id.clone(),
                agent_id: format!("rust-{}", task.id),
                agent_kind: AgentKind::Deterministic,
                capability: task.capability.clone(),
                objective: task.objective.clone(),
                depends_on: task.depends_on.clone(),
            })
            .collect(),
    )?;
    Ok(graph)
}

fn append(path: &Path, bytes: &[u8]) -> Result<(), String> {
    fs::OpenOptions::new()
        .append(true)
        .open(path)
        .map_err(|e| e.to_string())?
        .write_all(bytes)
        .map_err(|e| e.to_string())
}

fn run() -> Result<PathBuf, String> {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .ok_or("workspace")?
        .to_path_buf();
    let out = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("runs")
        .join(format!("mind-vague-{}", now_ns()));
    fs::create_dir_all(&out).map_err(|e| e.to_string())?;
    let python = root.join(".hive_proof_env/Scripts/python.exe");
    let script = root.join("hive_control/mind_file_bridge.py");
    let goal = "Create a file. Have it do something.";
    let profile = env::var("HIVE_PROBE_PROFILE").unwrap_or_else(|_| "default".into());
    if profile != "default" && profile != "function_only" {
        return Err("unknown capability profile".into());
    }
    let mut receipt = json!({"schema":"mind_vague_file_v1", "status":"HOLD", "goal":goal,
        "scope":"isolated LocalCoder run only", "run_dir":out, "capability_profile":profile});
    let result = (|| -> Result<(), String> {
        let mind = bridge(
            &python,
            &script,
            &json!({"phase":"plan", "goal":goal, "capability_profile":profile}),
        )?;
        fs::write(
            out.join("mind_plan_transcript.json"),
            serde_json::to_vec_pretty(&mind).map_err(|e| e.to_string())?,
        )
        .map_err(|e| e.to_string())?;
        receipt["foreman_snapshot_id"] = mind["foreman_snapshot_id"].clone();
        receipt["mind_plan_metrics"] = mind["metrics"].clone();
        receipt["plan"] = mind["parsed"].clone();
        let plan: MindPlan =
            serde_json::from_value(mind["parsed"].clone()).map_err(|e| e.to_string())?;
        let mut graph = validate(&plan)?;
        if profile == "function_only"
            && plan
                .tasks
                .iter()
                .any(|task| task.capability == "stamp_print")
        {
            return Err("task uses capability absent from profile".into());
        }
        let file = out.join(&plan.filename);
        let by_id: BTreeMap<String, MindTask> = plan
            .tasks
            .iter()
            .map(|t| (t.id.clone(), t.clone()))
            .collect();
        let mut control = Control::new(vec![
            ("write_run_artifact".into(), "isolated_run".into()),
            ("run_file".into(), "isolated_run".into()),
        ]);
        let mut hashes: BTreeMap<String, String> = BTreeMap::new();
        let mut events = Vec::new();
        let mut stdout = String::new();
        while !graph.ready().is_empty() {
            let ready = graph.ready();
            if ready.len() != 1 {
                return Err("multiple shared-file tasks ready".into());
            }
            let id = &ready[0];
            let spec = graph.claim(id)?;
            let parent_hashes: BTreeMap<String, String> = spec
                .depends_on
                .iter()
                .map(|parent| {
                    hashes
                        .get(parent)
                        .map(|hash| (parent.clone(), hash.clone()))
                        .ok_or("parent hash missing")
                })
                .collect::<Result<_, _>>()?;
            if file.exists()
                && parent_hashes.values().any(|expected| {
                    fs::read(&file)
                        .map(|bytes| sha(&bytes) != *expected)
                        .unwrap_or(true)
                })
            {
                graph.fail(id)?;
                return Err(format!("parent artifact changed before dispatch: {id}"));
            }
            let task = by_id.get(id).ok_or("plan task missing")?;
            let body = json!({"task":spec,"parent_sha256":parent_hashes,"value":task.value,"filename":plan.filename});
            let checksum = control.seal_task(id, &spec.agent_id, None, None, &body)?;
            if control.open_task(id, &spec.agent_id, None)? != body {
                return Err("snapshot mismatch".into());
            }
            let tool = if spec.capability == "run_file" {
                "run_file"
            } else {
                "write_run_artifact"
            };
            control.approve_tool(true, tool, "isolated_run")?;
            match spec.capability.as_str() {
                "create_file" => fs::write(&file, b"").map_err(|e| e.to_string())?,
                "stamp_print" => append(&file, format!("print({:?})\n", task.value).as_bytes())?,
                "stamp_function" => append(
                    &file,
                    format!("def perform():\n    print({:?})\n\n", task.value).as_bytes(),
                )?,
                "stamp_call" => append(&file, b"\nif __name__ == \"__main__\":\n    perform()\n")?,
                "run_file" => {
                    let output = Command::new(&python)
                        .arg(&file)
                        .current_dir(&out)
                        .output()
                        .map_err(|e| e.to_string())?;
                    if !output.status.success() {
                        return Err(format!(
                            "file failed: {}",
                            String::from_utf8_lossy(&output.stderr)
                        ));
                    }
                    stdout = String::from_utf8(output.stdout).map_err(|e| e.to_string())?;
                    if stdout.trim().is_empty() {
                        return Err("file produced no output".into());
                    }
                }
                _ => return Err("unadmitted capability".into()),
            }
            let hash = sha(&fs::read(&file).map_err(|e| e.to_string())?);
            control.complete_task(id, &spec.agent_id, &hash)?;
            hashes.insert(id.clone(), hash.clone());
            graph.complete(id, 0)?;
            events.push(json!({"task_id":id,"capability":spec.capability,"status":"PASS",
                "checksum":checksum,"parent_sha256":parent_hashes,"artifact_sha256":hash,
                "generation_count":0,"stdout":if spec.capability == "run_file" {Some(stdout.as_str())} else {None}}));
        }
        fs::write(
            out.join("swarm_task_transcript.jsonl"),
            events
                .iter()
                .map(Value::to_string)
                .collect::<Vec<_>>()
                .join("\n")
                + "\n",
        )
        .map_err(|e| e.to_string())?;
        receipt["swarm_events"] = json!(events);
        receipt["task_graph"] = json!(graph.records());
        receipt["artifact"] = json!(file);
        receipt["artifact_sha256"] = json!(sha(&fs::read(&file).map_err(|e| e.to_string())?));
        receipt["stdout"] = json!(stdout);
        let final_mind = bridge(
            &python,
            &script,
            &json!({"phase":"final","verified_result":{
            "goal":goal,"status":"PASS","intent":plan.intent,"filename":plan.filename,"stdout":stdout,
            "tasks_completed":events.len()}}),
        )?;
        fs::write(
            out.join("mind_final_transcript.json"),
            serde_json::to_vec_pretty(&final_mind).map_err(|e| e.to_string())?,
        )
        .map_err(|e| e.to_string())?;
        receipt["mind_final"] = final_mind["raw"].clone();
        receipt["mind_final_metrics"] = final_mind["metrics"].clone();
        receipt["status"] = json!("PASS");
        Ok(())
    })();
    if let Err(error) = result {
        receipt["failure"] = json!(error);
    }
    let path = out.join("run_receipt.json");
    fs::write(
        &path,
        serde_json::to_vec_pretty(&receipt).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())?;
    Ok(path)
}

fn main() {
    match run() {
        Ok(path) => {
            println!("{}", path.display());
            let receipt: Value =
                serde_json::from_slice(&fs::read(&path).expect("receipt")).expect("JSON");
            if receipt["status"] != "PASS" {
                std::process::exit(1);
            }
        }
        Err(error) => {
            eprintln!("MIND_VAGUE_ERROR {error}");
            std::process::exit(2);
        }
    }
}
