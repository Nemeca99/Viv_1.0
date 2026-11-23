//! Isolated AIOS fixture.echo template rebuild through the Hive task boundary.
use hive_control::graph::{AgentKind, TaskGraph, TaskSpec};
use hive_control::{sha, Control};
use serde_json::{json, Value};
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{SystemTime, UNIX_EPOCH};

const REFERENCE_SHA256: &str = "8f84915a7c291691f6e5a5028b75e7e43573a68af7f46cd91ce46cf1774fa82c";

fn bridge(python: &Path, script: &Path, request: Value) -> Result<Value, String> {
    let mut child = Command::new(python)
        .arg(script)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| e.to_string())?;
    let mut input = child.stdin.take().ok_or("bridge stdin unavailable")?;
    serde_json::to_writer(&mut input, &request).map_err(|e| e.to_string())?;
    input.write_all(b"\n").map_err(|e| e.to_string())?;
    drop(input);
    let output = child.wait_with_output().map_err(|e| e.to_string())?;
    let value: Value = serde_json::from_slice(&output.stdout).map_err(|e| {
        format!(
            "bridge returned invalid JSON: {e}: {}",
            String::from_utf8_lossy(&output.stderr)
        )
    })?;
    if !output.status.success() || value["ok"] != true {
        return Err(format!(
            "bridge held: {} {}",
            value["error"], value["detail"]
        ));
    }
    Ok(value["result"].clone())
}

fn safe_slot(value: &Value) -> Result<&str, String> {
    let slot = value.as_str().ok_or("Mind slot must be a string")?;
    if slot.is_empty() || slot.len() > 80 || slot.chars().any(char::is_control) {
        return Err("Mind slot outside bounded literal contract".into());
    }
    Ok(slot)
}

fn spans(source: &str, message: &str, suffix: &str) -> Result<[String; 3], String> {
    let start = source
        .find("# TEMPLATE VARIABLES BEGIN\n")
        .ok_or("variable marker absent")?;
    let end_marker = "# TEMPLATE VARIABLES END\n";
    let end = source
        .find(end_marker)
        .ok_or("variable end marker absent")?
        + end_marker.len();
    if !source[end..].contains("def main(") || source.matches("def main(").count() != 1 {
        return Err("reference function shape invalid".into());
    }
    let import = source[..start].to_owned();
    let original_variables = &source[start..end];
    if !original_variables.contains("\"message\": \"template-fixture\"")
        || !original_variables.contains("\"suffix\": \"ok\"")
    {
        return Err("reference variable declaration changed".into());
    }
    let message_literal = serde_json::to_string(message).map_err(|e| e.to_string())?;
    let suffix_literal = serde_json::to_string(suffix).map_err(|e| e.to_string())?;
    let variables = format!(
        "# TEMPLATE VARIABLES BEGIN\nVARIABLES = {{\n    \"message\": {message_literal},\n    \"suffix\": {suffix_literal},\n}}\n# TEMPLATE VARIABLES END\n"
    );
    Ok([import, variables, source[end..].to_owned()])
}

fn run(python: &Path, mode: &str, fault: bool) -> Result<(Value, PathBuf), String> {
    if mode != "fixture" && mode != "live" {
        return Err("mode must be fixture or live".into());
    }
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..");
    let reference_path = root.join("template_rebuild/reference/fixture_echo.py");
    let reference_bytes = fs::read(&reference_path).map_err(|e| e.to_string())?;
    if sha(&reference_bytes) != REFERENCE_SHA256 {
        return Err("legacy source snapshot hash changed".into());
    }
    let reference = String::from_utf8(reference_bytes).map_err(|e| e.to_string())?;
    let switchboard = root.join("hive_control/switchboard.py");
    let run_id = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|e| e.to_string())?
        .as_nanos();
    let out = root.join("template_rebuild/runs").join(format!("{run_id}"));
    fs::create_dir_all(&out).map_err(|e| e.to_string())?;
    let artifact = out.join("fixture_echo.py");
    let receipt_path = out.join("receipt.json");
    let mut receipt = json!({"schema": "hive_template_rebuild_run_v1", "mode": mode,
        "scope": "isolated fixture.echo source and registry; no legacy write or promotion",
        "reference_sha256": REFERENCE_SHA256, "fault_injected": fault,
        "tasks": [], "mind_generation_count": if mode == "live" { 2 } else { 0 },
        "swarm_generation_count": 0,
        "source_sha256": {"runner": sha(&fs::read(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("src/bin/template_rebuild.rs")).map_err(|e| e.to_string())?),
                           "switchboard": sha(&fs::read(&switchboard).map_err(|e| e.to_string())?)}});
    let result = (|| -> Result<(), String> {
        let plan = bridge(
            python,
            &switchboard,
            json!({"op": "template_rebuild_mind", "phase": "plan", "mode": mode, "reference_sha256": REFERENCE_SHA256}),
        )?;
        let slots = bridge(
            python,
            &switchboard,
            json!({"op": "template_rebuild_mind", "phase": "slots", "mode": mode, "reference_sha256": REFERENCE_SHA256}),
        )?;
        if plan["foreman_snapshot_id"] != slots["foreman_snapshot_id"] {
            return Err("Mind phases used different Foreman snapshots".into());
        }
        let expected = [
            ("import", vec![]),
            ("variables", vec!["import"]),
            ("function", vec!["variables"]),
            ("registry", vec!["function"]),
        ];
        let rows = plan["value"]["tasks"]
            .as_array()
            .ok_or("Mind plan missing tasks")?;
        if rows.len() != expected.len() {
            return Err("Mind plan task count changed".into());
        }
        let mut graph = TaskGraph::new();
        let mut specs = Vec::new();
        for (row, (id, deps)) in rows.iter().zip(expected.iter()) {
            let actual_deps = row["depends_on"]
                .as_array()
                .ok_or("Mind dependency list missing")?;
            if row["id"] != *id || actual_deps != &deps.iter().map(|d| json!(d)).collect::<Vec<_>>()
            {
                return Err(format!("Mind plan deviated at {id}"));
            }
            specs.push(TaskSpec {
                id: (*id).into(),
                agent_id: format!("stamp-{id}"),
                agent_kind: AgentKind::Deterministic,
                capability: "stamp-approved-span".into(),
                objective: format!("Stamp approved {id} span"),
                depends_on: deps.iter().map(|d| (*d).into()).collect(),
            });
        }
        graph.add_batch(specs.clone())?;
        receipt["mind_plan"] = json!(specs);
        receipt["foreman_snapshot_id"] = plan["foreman_snapshot_id"].clone();
        receipt["mind_metrics"] =
            json!({"plan": plan["model_metrics"], "slots": slots["model_metrics"]});
        let message = safe_slot(&slots["value"]["message"])?;
        let suffix = safe_slot(&slots["value"]["suffix"])?;
        let parts = spans(&reference, message, suffix)?;
        receipt["mind_slots"] = json!({"message": message, "suffix": suffix});
        let mut control = Control::new(vec![(
            "write_run_artifact".into(),
            "template-rebuild-run".into(),
        )]);
        let mut current = String::new();
        let mut parent_id: Option<&str> = None;
        let mut parent_hash: Option<String> = None;
        for (index, (id, _)) in expected.iter().enumerate() {
            let claimed = graph.claim(id)?;
            if claimed.agent_id != format!("stamp-{id}") {
                return Err("wrong Swarm agent".into());
            }
            control.approve_tool(true, "write_run_artifact", "template-rebuild-run")?;
            let payload = json!({"span_sha256": if index < 3 {sha(parts[index].as_bytes())} else {"registry".into()},
                                 "foreman_snapshot_id": plan["foreman_snapshot_id"]});
            let checksum = control.seal_task(
                id,
                &claimed.agent_id,
                parent_id,
                parent_hash.as_deref(),
                &payload,
            )?;
            let actual_parent = if parent_id.is_some() {
                if index == 3 {
                    Some(sha(current.as_bytes()))
                } else {
                    Some(sha(&fs::read(&artifact).map_err(|e| e.to_string())?))
                }
            } else {
                None
            };
            let opened = control.open_task(id, &claimed.agent_id, actual_parent.as_deref())?;
            if index < 3 && opened["span_sha256"] != sha(parts[index].as_bytes()) {
                return Err("task span hash mismatch".into());
            }
            if index < 3 {
                current.push_str(&parts[index]);
                fs::write(&artifact, current.as_bytes()).map_err(|e| e.to_string())?;
                if fault && index == 1 {
                    fs::write(&artifact, format!("{current}\n# injected parent fault\n"))
                        .map_err(|e| e.to_string())?;
                }
            } else {
                let registry = json!({"schema_version": "hive_rebuilt_template_registry_v1",
                    "templates": [{"template_id": "fixture.echo", "source": "fixture_echo.py",
                                   "source_sha256": sha(current.as_bytes()), "declared_variables": ["message", "suffix"]}]});
                fs::write(
                    out.join("registry.json"),
                    serde_json::to_vec_pretty(&registry).map_err(|e| e.to_string())?,
                )
                .map_err(|e| e.to_string())?;
            }
            let hash = if index == 3 {
                sha(&fs::read(out.join("registry.json")).map_err(|e| e.to_string())?)
            } else {
                sha(current.as_bytes())
            };
            control.complete_task(id, &claimed.agent_id, &hash)?;
            graph.complete(id, 0)?;
            receipt["tasks"]
                .as_array_mut()
                .ok_or("receipt tasks missing")?
                .push(json!({"task_id": id,
                "owner": claimed.agent_id, "checksum": checksum, "artifact_sha256": hash,
                "one_task": true, "generation_count": 0}));
            parent_id = Some(id);
            parent_hash = Some(hash);
        }
        if !graph.ready().is_empty() {
            return Err("task graph still has ready nodes".into());
        }
        let verified = Command::new(python)
            .arg(root.join("template_rebuild/verify_run.py"))
            .arg(&out)
            .arg(&reference_path)
            .output()
            .map_err(|e| e.to_string())?;
        if !verified.status.success() {
            return Err(format!(
                "posthoc verification failed: {}",
                String::from_utf8_lossy(&verified.stderr)
            ));
        }
        receipt["verification"] =
            serde_json::from_slice(&verified.stdout).map_err(|e| e.to_string())?;
        receipt["artifact_sha256"] = json!(sha(&fs::read(&artifact).map_err(|e| e.to_string())?));
        receipt["registry_sha256"] = json!(sha(
            &fs::read(out.join("registry.json")).map_err(|e| e.to_string())?
        ));
        Ok(())
    })();
    receipt["status"] = if result.is_ok() {
        json!("PASS")
    } else {
        json!("HOLD")
    };
    if let Err(error) = &result {
        receipt["reason"] = json!(error);
    }
    fs::write(
        &receipt_path,
        serde_json::to_vec_pretty(&receipt).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())?;
    Ok((receipt, receipt_path))
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let python = args
        .get(1)
        .map(PathBuf::from)
        .expect("usage: template_rebuild PYTHON fixture|live [--inject-parent-fault]");
    let mode = args.get(2).expect("mode required");
    let fault = args.iter().any(|arg| arg == "--inject-parent-fault");
    match run(&python, mode, fault) {
        Ok((receipt, path)) => {
            println!(
                "{}",
                json!({"status": receipt["status"], "receipt": path, "reason": receipt["reason"]})
            );
            if receipt["status"] != "PASS" && !fault {
                std::process::exit(1);
            }
            if fault && receipt["status"] != "HOLD" {
                std::process::exit(1);
            }
        }
        Err(error) => {
            eprintln!("{error}");
            std::process::exit(1);
        }
    }
}
