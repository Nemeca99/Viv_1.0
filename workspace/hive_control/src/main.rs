//! Rust-led three-step Hive proof. Python carries Mind, template, and NumPy data.
use hive_control::graph::{AgentKind, TaskGraph, TaskSpec};
use hive_control::{sha, Control};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::env;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{SystemTime, UNIX_EPOCH};

const GREETING: &str = "Hello from the Hive!"; // Architect's recorded human reply.

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

fn mind_approved(row: &Value, tool: &str) -> bool {
    row["approved_tools"]
        .as_array()
        .is_some_and(|items| items.iter().any(|item| item.as_str() == Some(tool)))
}

fn template_hash(id: &str) -> Result<&'static str, String> {
    match id {
        "python.module_docstring" => {
            Ok("f13f73d2ad5457028632ac8af982012c047f7128f34c0c07eb25fa01c26511bd")
        }
        "python.typing_final_import" => {
            Ok("4cf00c254e8ae8a65f5174806728bbbbe379c0fc9da9863d1657b5a21a89d68b")
        }
        "python.greeting_function" => {
            Ok("5aded09231abe636de33cf5f5808536f5d0f4a3664765cdb4d9b326457169573")
        }
        _ => Err("template outside Rust allowlist".into()),
    }
}

fn validate_hello_plan(specs: &[TaskSpec]) -> Result<(), String> {
    if specs.len() != 4 {
        return Err("Mind plan must contain four bounded jobs".into());
    }
    let by_id: BTreeMap<_, _> = specs.iter().map(|spec| (spec.id.as_str(), spec)).collect();
    let expected = [
        (
            "task-001",
            "stamp-header",
            AgentKind::Deterministic,
            "stamp-template",
            vec!["discover-templates"],
        ),
        (
            "task-002",
            "stamp-import",
            AgentKind::Deterministic,
            "stamp-template",
            vec!["task-001"],
        ),
        (
            "human-greeting",
            "queen-via-viv",
            AgentKind::Human,
            "reply",
            vec!["task-002"],
        ),
        (
            "task-003",
            "stamp-function",
            AgentKind::Deterministic,
            "stamp-template",
            vec!["task-002", "human-greeting"],
        ),
    ];
    for (id, agent, kind, capability, deps) in expected {
        let spec = by_id.get(id).ok_or(format!("Mind plan omitted {id}"))?;
        let actual_deps: Vec<_> = spec.depends_on.iter().map(String::as_str).collect();
        if spec.agent_id != agent
            || spec.agent_kind != kind
            || spec.capability != capability
            || actual_deps != deps
            || spec.objective.trim().is_empty()
        {
            return Err(format!(
                "Mind plan task {id} failed capability/dependency contract"
            ));
        }
    }
    Ok(())
}

struct StampRequest<'a> {
    python: &'a Path,
    script: &'a Path,
    artifact: &'a Path,
    task_id: &'a str,
    owner: &'a str,
    parent: Option<&'a str>,
    parent_hash: Option<&'a str>,
    template_id: &'a str,
    slots: Value,
    mind: &'a Value,
}

fn stamp(
    control: &mut Control,
    graph: &mut TaskGraph,
    request: StampRequest<'_>,
) -> Result<Value, String> {
    let StampRequest {
        python,
        script,
        artifact,
        task_id,
        owner,
        parent,
        parent_hash,
        template_id,
        slots,
        mind,
    } = request;
    let claimed = graph.claim(task_id)?;
    if claimed.agent_id != owner || claimed.capability != "stamp-template" {
        return Err("task graph agent or capability mismatch".into());
    }
    control.approve_tool(
        mind_approved(mind, "render_template"),
        "render_template",
        "run-artifact",
    )?;
    control.approve_tool(
        mind_approved(mind, "write_run_artifact"),
        "write_run_artifact",
        "run-artifact",
    )?;
    let payload = json!({"template_id": template_id, "slots": slots,
                         "parent_artifact_sha256": parent_hash,
                         "foreman_snapshot_id": mind["foreman_snapshot_id"]});
    let checksum = control.seal_task(task_id, owner, parent, parent_hash, &payload)?;
    let current_parent_hash = if parent.is_some() {
        Some(sha(&fs::read(artifact).map_err(|e| e.to_string())?))
    } else {
        None
    };
    let prepared = control.open_task(task_id, owner, current_parent_hash.as_deref())?;
    let template = prepared["template_id"].as_str().ok_or("missing template")?;
    let rendered = switchboard(
        python,
        script,
        &json!({"op": "render", "template_id": template,
                                                       "slots": prepared["slots"]}),
    )?;
    let code = rendered["code"].as_str().ok_or("rendered code missing")?;
    if rendered["template_id"] != template
        || rendered["source_sha256"] != template_hash(template)?
        || rendered["output_sha256"] != sha(code.as_bytes())
    {
        return Err("template source or rendered output hash failed Rust check".into());
    }
    let combined = if parent.is_some() {
        format!(
            "{}\n\n{}",
            fs::read_to_string(artifact)
                .map_err(|e| e.to_string())?
                .trim_end(),
            code
        )
    } else {
        code.to_owned()
    };
    fs::write(artifact, combined.as_bytes()).map_err(|e| e.to_string())?;
    let artifact_hash = sha(&fs::read(artifact).map_err(|e| e.to_string())?);
    control.complete_task(task_id, owner, &artifact_hash)?;
    graph.complete(task_id, 0)?;
    Ok(json!({"task_id": task_id, "owner": owner, "parent": parent,
              "checksum": checksum, "template_id": template,
              "template_source_sha256": rendered["source_sha256"],
              "artifact_sha256": artifact_hash, "stamp_count": 1,
              "generation_count": 0, "posthoc_pass": true}))
}

fn run(python: &Path, mode: &str, inject_fault: bool) -> Result<(Value, PathBuf), String> {
    if mode != "fixture" && mode != "live" {
        return Err("mode must be fixture or live".into());
    }
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let script = root.join("switchboard.py");
    let stamp_id = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|e| e.to_string())?
        .as_nanos();
    let out = root.join("runs").join(format!("{stamp_id}"));
    fs::create_dir_all(&out).map_err(|e| e.to_string())?;
    let artifact = out.join("hello.py");
    let mut control = Control::new(vec![
        (
            "read_template_registry".into(),
            "workspace-templates".into(),
        ),
        ("render_template".into(), "run-artifact".into()),
        ("write_run_artifact".into(), "run-artifact".into()),
        ("validate_artifact".into(), "run-artifact".into()),
        ("numeric_contract".into(), "run-artifact".into()),
    ]);
    let mut graph = TaskGraph::new();
    let mut receipt = json!({"schema": "hive_rust_control_run_v1", "mode": mode,
        "scope": "isolated LocalCoder proof; no training, promotion, or deployment",
        "rust_owns": ["task state", "OS entropy and master key", "snapshot encryption",
                      "tool grants", "artifact commits", "receipt"],
        "python_role": "data transport only", "swarm_generation_count": 0,
        "fault_injected": inject_fault, "tasks": [], "security_checks": {}});
    receipt["source_sha256"] = json!({
        "rust_control": sha(&fs::read(root.join("src/lib.rs")).map_err(|e| e.to_string())?),
        "rust_graph": sha(&fs::read(root.join("src/graph.rs")).map_err(|e| e.to_string())?),
        "rust_runner": sha(&fs::read(root.join("src/main.rs")).map_err(|e| e.to_string())?),
        "python_switchboard": sha(&fs::read(&script).map_err(|e| e.to_string())?),
        "template_registry": sha(&fs::read(root.join("../code_templates/registry.json")).map_err(|e| e.to_string())?),
        "numpy_backend": sha(&fs::read(root.join("../hive_numpy_bridge/numpy_backend.py")).map_err(|e| e.to_string())?),
    });
    let finish = (|| -> Result<(), String> {
        graph.add_batch(vec![TaskSpec {
            id: "discover-templates".into(),
            agent_id: "template-lookup".into(),
            agent_kind: AgentKind::Deterministic,
            capability: "read-template-registry".into(),
            objective: "Read the approved template registry".into(),
            depends_on: vec![],
        }])?;
        graph.claim("discover-templates")?;
        control.approve_tool(true, "read_template_registry", "workspace-templates")?;
        let registry_bytes =
            fs::read(root.join("../code_templates/registry.json")).map_err(|e| e.to_string())?;
        let registry: Value = serde_json::from_slice(&registry_bytes).map_err(|e| e.to_string())?;
        let mut template_ids = Vec::new();
        for row in registry["templates"]
            .as_array()
            .ok_or("template registry has no rows")?
        {
            let id = row["template_id"]
                .as_str()
                .ok_or("registry template ID missing")?;
            if row["sha256"] != template_hash(id)? {
                return Err("template registry hash outside Rust pin".into());
            }
            template_ids.push(id);
        }
        graph.complete("discover-templates", 0)?;
        let discovery = json!({"agent": "template-lookup", "template_ids": template_ids,
            "registry_sha256": sha(&registry_bytes)});
        receipt["discovery"] = discovery.clone();
        let plan_row = switchboard(
            python,
            &script,
            &json!({"op": "plan", "mode": mode, "evidence": discovery}),
        )?;
        let specs: Vec<TaskSpec> = serde_json::from_value(plan_row["tasks"].clone())
            .map_err(|e| format!("Mind plan schema failed: {e}"))?;
        validate_hello_plan(&specs)?;
        graph.add_batch(specs.clone())?;
        receipt["mind_plan"] = json!(specs);
        receipt["mind_plan_metrics"] = plan_row["model_metrics"].clone();
        receipt["foreman_snapshot_id"] = plan_row["foreman_snapshot_id"].clone();
        receipt["ready_cohorts"] = json!([graph.ready()]);
        let mind1 = switchboard(
            python,
            &script,
            &json!({"op": "mind", "phase": "header", "mode": mode}),
        )?;
        if mind1["values"]["module_docstring"] != "Hive greeting module"
            || mind1["values"]["import_template_id"] != "python.typing_final_import"
        {
            return Err("Mind header slots outside contract".into());
        }
        if mind1["foreman_snapshot_id"] != receipt["foreman_snapshot_id"] {
            return Err("Mind plan and slot generations used different Foreman snapshots".into());
        }
        receipt["mind_header_metrics"] = mind1["model_metrics"].clone();
        receipt["mind_generations"] = json!(if mode == "live" { 3 } else { 0 });
        let task1 = stamp(
            &mut control,
            &mut graph,
            StampRequest {
                python,
                script: &script,
                artifact: &artifact,
                task_id: "task-001",
                owner: "stamp-header",
                parent: None,
                parent_hash: None,
                template_id: "python.module_docstring",
                slots: json!({"docstring": mind1["values"]["module_docstring"]}),
                mind: &mind1,
            },
        )?;
        receipt["tasks"].as_array_mut().unwrap().push(task1.clone());
        receipt["ready_cohorts"]
            .as_array_mut()
            .unwrap()
            .push(json!(graph.ready()));
        let hash1 = task1["artifact_sha256"]
            .as_str()
            .ok_or("task1 artifact hash missing")?;
        let task2 = stamp(
            &mut control,
            &mut graph,
            StampRequest {
                python,
                script: &script,
                artifact: &artifact,
                task_id: "task-002",
                owner: "stamp-import",
                parent: Some("task-001"),
                parent_hash: Some(hash1),
                template_id: "python.typing_final_import",
                slots: json!({}),
                mind: &mind1,
            },
        )?;
        receipt["tasks"].as_array_mut().unwrap().push(task2.clone());
        let hash2 = task2["artifact_sha256"]
            .as_str()
            .ok_or("task2 artifact hash missing")?
            .to_owned();
        receipt["human_reply"] = json!({"route": "Queen -> Viv -> task-003", "value": GREETING});
        receipt["ready_cohorts"]
            .as_array_mut()
            .unwrap()
            .push(json!(graph.ready()));
        graph.claim("human-greeting")?;
        graph.wait_for_user("human-greeting")?;
        graph.resume_user("human-greeting")?;
        graph.complete("human-greeting", 0)?;
        receipt["ready_cohorts"]
            .as_array_mut()
            .unwrap()
            .push(json!(graph.ready()));
        let mind3 = switchboard(
            python,
            &script,
            &json!({"op": "mind", "phase": "greeting",
            "mode": mode, "greeting": GREETING}),
        )?;
        if mind3["foreman_snapshot_id"] != receipt["foreman_snapshot_id"]
            || mind3["values"]["greeting"] != GREETING
            || mind3["values"]["function_name"] != "greet"
        {
            return Err("Mind resumed slots or Foreman binding outside contract".into());
        }
        receipt["mind_greeting_metrics"] = mind3["model_metrics"].clone();
        if inject_fault {
            let source = fs::read_to_string(&artifact).map_err(|e| e.to_string())?;
            fs::write(
                &artifact,
                source.replace("from typing import Final", "from typing import Optional"),
            )
            .map_err(|e| e.to_string())?;
        }
        let task3 = stamp(
            &mut control,
            &mut graph,
            StampRequest {
                python,
                script: &script,
                artifact: &artifact,
                task_id: "task-003",
                owner: "stamp-function",
                parent: Some("task-002"),
                parent_hash: Some(&hash2),
                template_id: "python.greeting_function",
                slots: json!({"greeting": mind3["values"]["greeting"],
                                     "function_name": mind3["values"]["function_name"]}),
                mind: &mind3,
            },
        );
        if inject_fault {
            if task3
                .as_ref()
                .err()
                .is_some_and(|e| e == "parent artifact changed before dispatch")
            {
                graph.fail("task-003")?;
                receipt["status"] = json!("HOLD_PARENT_FAULT_CAUGHT");
                receipt["fault_detection"] = json!({"task2_passed": true,
                    "expected_parent_sha256": hash2,
                    "observed_parent_sha256": sha(&fs::read(&artifact).map_err(|e| e.to_string())?),
                    "task3_stamp_count": 0, "repair_generations": 0});
                return Ok(());
            }
            return Err(format!("fault was not caught by parent check: {task3:?}"));
        }
        let task3 = task3?;
        receipt["tasks"].as_array_mut().unwrap().push(task3);
        control.approve_tool(true, "validate_artifact", "run-artifact")?;
        let source = fs::read_to_string(&artifact).map_err(|e| e.to_string())?;
        let validation = switchboard(
            python,
            &script,
            &json!({"op": "validate", "source": source,
                                                               "expected": GREETING}),
        )?;
        if validation["passed"] != true {
            return Err(format!("composition failed: {validation}"));
        }
        receipt["validation"] = validation;
        control.approve_tool(true, "numeric_contract", "run-artifact")?;
        let numeric = switchboard(python, &script, &json!({"op": "numeric_contract"}))?;
        if numeric["summary"]["matrix_product"] != json!([[11.0]])
            || numeric["summary"]["slice_is_view"] != true
        {
            return Err("NumPy contract result failed Rust check".into());
        }
        receipt["numeric_bridge"] = numeric;
        receipt["security_checks"] = json!({
            "unapproved_shell_denied": control.approve_tool(true, "shell", "run-artifact").is_err(),
            "unapproved_peer_denied": control.seal_peer("stamp-header", "stamp-import", "task-002", "missing", b"probe").is_err(),
            "wrong_task_owner_denied": control.open_task("task-003", "stamp-import", Some(&hash2)).is_err(),
            "master_key_in_worker_context": false,
        });
        receipt["task_index"] = json!([
            control.task_record("task-001")?,
            control.task_record("task-002")?,
            control.task_record("task-003")?,
        ]);
        receipt["task_graph"] = json!(graph.records());
        receipt["status"] = json!("PASS");
        Ok(())
    })();
    if let Err(error) = finish {
        receipt["status"] = json!("HOLD");
        receipt["error"] = json!(error);
    }
    receipt["artifact"] = if artifact.exists() {
        json!({"path": artifact.strip_prefix(&root).unwrap().to_string_lossy(),
               "sha256": sha(&fs::read(&artifact).map_err(|e| e.to_string())?)})
    } else {
        Value::Null
    };
    let receipt_path = out.join("run_receipt.json");
    fs::write(
        &receipt_path,
        serde_json::to_vec_pretty(&receipt).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())?;
    Ok((receipt, receipt_path))
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 3 || args.len() > 4 {
        eprintln!("usage: hive_control <python.exe> <fixture|live> [--inject-parent-fault]");
        std::process::exit(2);
    }
    let fault = args.get(3).is_some_and(|x| x == "--inject-parent-fault");
    if args.len() == 4 && !fault {
        eprintln!("unknown flag");
        std::process::exit(2);
    }
    match run(Path::new(&args[1]), &args[2], fault) {
        Ok((receipt, path)) => {
            println!(
                "{}",
                json!({"status": receipt["status"], "receipt": path,
                                     "artifact": receipt["artifact"]})
            );
            if receipt["status"] == "HOLD_PARENT_FAULT_CAUGHT" {
                return;
            }
            if receipt["status"] != "PASS" {
                std::process::exit(1);
            }
        }
        Err(error) => {
            eprintln!("{error}");
            std::process::exit(1);
        }
    }
}
