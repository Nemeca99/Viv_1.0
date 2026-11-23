//! Mind-selected, hash-pinned template composition across all 19 AIOS cores.
//! Rust owns admission, task snapshots, tool grants, and CPU dispatch. Workers
//! copy catalogued source spans exactly; candidate code is parsed, never run.

use hive_control::graph::{AgentKind, TaskGraph, TaskSpec};
use hive_control::{sha, Control};
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};
use std::env;
use std::fs::{self, OpenOptions};
use std::io::{BufRead, BufReader, Seek, SeekFrom, Write};
use std::path::{Component, Path, PathBuf};
use std::process::Command;

fn arg(args: &[String], name: &str) -> Result<String, String> {
    let index = args
        .iter()
        .position(|value| value == name)
        .ok_or_else(|| format!("missing argument {name}"))?;
    args.get(index + 1)
        .cloned()
        .ok_or_else(|| format!("missing value for {name}"))
}

fn read(path: &Path) -> Result<Vec<u8>, String> {
    fs::read(path).map_err(|error| format!("read {}: {error}", path.display()))
}

fn sha_file(path: &Path) -> Result<String, String> {
    Ok(sha(&read(path)?))
}

fn safe_relative(text: &str) -> Result<PathBuf, String> {
    let path = Path::new(text);
    if path.as_os_str().is_empty()
        || path.is_absolute()
        || path
            .components()
            .any(|part| !matches!(part, Component::Normal(_)))
    {
        return Err(format!("unsafe catalog path: {text}"));
    }
    Ok(path.to_path_buf())
}

fn text<'a>(value: &'a Value, key: &str) -> Result<&'a str, String> {
    value
        .get(key)
        .and_then(Value::as_str)
        .ok_or_else(|| format!("missing string field {key}"))
}

fn selected_templates(
    plan: &Value,
    menu: &Value,
    registry: &Value,
) -> Result<BTreeMap<String, Vec<String>>, String> {
    if plan["schema"] != "viv_full_aios_catalog_plan_v1" {
        return Err("Mind plan schema mismatch".into());
    }
    let intent = text(plan, "intent")?.trim();
    if !matches!(
        plan["plan_origin"].as_str(),
        Some("viv_mind_model" | "contract_fixture")
    ) {
        return Err(
            "plan origin is not an admitted model result or explicit contract fixture".into(),
        );
    }
    let tools: BTreeSet<&str> = plan["approved_tools"]
        .as_array()
        .ok_or("Mind tool approvals missing")?
        .iter()
        .filter_map(Value::as_str)
        .collect();
    let required_tools: BTreeSet<&str> = ["stamp_catalog_templates", "verify_template_composition"]
        .into_iter()
        .collect();
    if tools != required_tools {
        return Err("Mind tool approvals differ from the fixed catalog allowlist".into());
    }
    let cores = registry["core_names"]
        .as_array()
        .ok_or("catalog core manifest missing")?;
    let cards = menu["cards"]
        .as_object()
        .ok_or("Mind candidate menu missing")?;
    let selections = plan["selections"]
        .as_array()
        .ok_or("Mind selections missing")?;
    if selections.len() != cores.len() {
        return Err("Mind must select templates for every manifest core".into());
    }
    let mut selected = BTreeMap::new();
    let mut position_patterns = BTreeMap::<String, usize>::new();
    let mut invalid_rationales = Vec::new();
    for selection in selections {
        let core = text(selection, "core")?.to_owned();
        if !cores.iter().any(|item| item.as_str() == Some(&core)) {
            return Err(format!("Mind selected unknown core {core}"));
        }
        let options = cards
            .get(&core)
            .and_then(Value::as_array)
            .ok_or_else(|| format!("candidate menu missing core {core}"))?;
        let by_key: BTreeMap<&str, (&str, &str)> = options
            .iter()
            .filter_map(|row| {
                Some((
                    row["candidate_key"].as_str()?,
                    (
                        row["template_id"].as_str()?,
                        row["qualified_name"].as_str()?,
                    ),
                ))
            })
            .collect();
        if by_key.len() != options.len() {
            return Err(format!("candidate menu key collision for {core}"));
        }
        let keys = selection["candidate_keys"]
            .as_array()
            .ok_or_else(|| format!("Mind candidate keys missing for {core}"))?;
        if keys.len() != 1 {
            return Err(format!("Mind selection size out of bounds for {core}"));
        }
        let selected_keys: Vec<String> = keys
            .iter()
            .map(|value| {
                value
                    .as_str()
                    .map(str::to_owned)
                    .ok_or_else(|| format!("non-string candidate key for {core}"))
            })
            .collect::<Result<_, _>>()?;
        let unique: BTreeSet<&str> = selected_keys.iter().map(String::as_str).collect();
        if unique.len() != selected_keys.len()
            || selected_keys
                .iter()
                .any(|key| !by_key.contains_key(key.as_str()))
        {
            return Err(format!(
                "Mind selected an unknown or duplicate candidate key for {core}"
            ));
        }
        let reason = text(selection, "reason")?.trim();
        let selected_name = by_key[selected_keys[0].as_str()].1.to_ascii_lowercase();
        if !(12..=120).contains(&reason.len())
            || !reason.to_ascii_lowercase().contains(&selected_name)
        {
            invalid_rationales.push(core.clone());
        }
        *position_patterns
            .entry(selected_keys[0].clone())
            .or_default() += 1;
        let values = selected_keys
            .iter()
            .map(|key| by_key[key.as_str()].0.to_owned())
            .collect();
        if selected.insert(core.clone(), values).is_some() {
            return Err(format!("Mind selected core more than once: {core}"));
        }
    }
    if selected.len() != cores.len() {
        return Err("Mind selection does not cover every core exactly once".into());
    }
    if cores.len() >= 10
        && position_patterns
            .values()
            .copied()
            .max()
            .unwrap_or_default()
            > cores.len() / 2
    {
        return Err(
            "Mind selection is collapsed onto the same menu position across most cores".into(),
        );
    }
    if let Some(core) = invalid_rationales.first() {
        return Err(format!(
            "Mind reason must name its selected template for {core}"
        ));
    }
    let lower_intent = intent.to_ascii_lowercase();
    if !(40..=180).contains(&intent.len())
        || !lower_intent.contains("aios")
        || !lower_intent.contains("candidate")
        || !lower_intent.contains("rebuild")
    {
        return Err("Mind intent must describe the full AIOS candidate composition".into());
    }
    Ok(selected)
}

fn source_span(
    id: &str,
    core: &str,
    index: &Value,
    data_path: &Path,
    candidate: &Path,
    core_names: &BTreeSet<String>,
) -> Result<(String, Value), String> {
    let offset = index
        .get(id)
        .and_then(Value::as_u64)
        .ok_or_else(|| format!("template ID not indexed: {id}"))?;
    let mut line = Vec::new();
    let mut reader = BufReader::new(fs::File::open(data_path).map_err(|error| error.to_string())?);
    reader
        .seek(SeekFrom::Start(offset))
        .map_err(|error| error.to_string())?;
    reader
        .read_until(b'\n', &mut line)
        .map_err(|error| error.to_string())?;
    let row: Value = serde_json::from_slice(&line).map_err(|error| error.to_string())?;
    if text(&row, "template_id")? != id || text(&row, "core")? != core {
        return Err(format!("catalog identity/core mismatch for {id}"));
    }
    let qualified_name = text(&row, "qualified_name")?;
    if qualified_name.contains('.') {
        return Err(format!(
            "nested member requires its containing class template: {id}"
        ));
    }
    let relative = safe_relative(text(&row, "source_path")?)?;
    if !core_names.contains(core)
        || relative
            .components()
            .next()
            .and_then(|part| part.as_os_str().to_str())
            != Some(core)
    {
        return Err(format!("template source is outside assigned core: {id}"));
    }
    let lexical = candidate.join(&relative);
    let source = lexical.canonicalize().map_err(|error| error.to_string())?;
    if !source.starts_with(candidate) {
        return Err(format!("template source escapes candidate: {id}"));
    }
    let source_bytes = read(&source)?;
    if sha(&source_bytes) != text(&row, "source_file_sha256")? {
        return Err(format!("template source hash changed: {id}"));
    }
    let source_text = String::from_utf8(source_bytes).map_err(|error| error.to_string())?;
    let lines: Vec<&str> = source_text.split_inclusive('\n').collect();
    let start = row["start_line"]
        .as_u64()
        .ok_or("template start line invalid")? as usize;
    let end = row["end_line"]
        .as_u64()
        .ok_or("template end line invalid")? as usize;
    if start == 0 || end < start || end > lines.len() {
        return Err(format!("template line range invalid: {id}"));
    }
    let snippet: String = lines[start - 1..end].concat();
    if snippet != text(&row, "snippet_utf8")?
        || sha(snippet.as_bytes()) != text(&row, "snippet_sha256")?
    {
        return Err(format!("template span digest mismatch: {id}"));
    }
    Ok((snippet, row))
}

fn preflight_selected_spans(
    selected: &BTreeMap<String, Vec<String>>,
    index: &Value,
    data_path: &Path,
    candidate: &Path,
    core_names: &BTreeSet<String>,
) -> Result<(), String> {
    for (core, ids) in selected {
        let mut names = BTreeSet::new();
        let mut spans = BTreeMap::<String, Vec<(usize, usize)>>::new();
        for id in ids {
            let (_, row) = source_span(id, core, index, data_path, candidate, core_names)?;
            let name = text(&row, "qualified_name")?;
            if !names.insert(name.to_owned()) {
                return Err(format!("duplicate declaration selected for {core}: {name}"));
            }
            let path = text(&row, "source_path")?.to_owned();
            let span = (
                row["start_line"]
                    .as_u64()
                    .ok_or("template start line missing")? as usize,
                row["end_line"]
                    .as_u64()
                    .ok_or("template end line missing")? as usize,
            );
            if spans.get(&path).is_some_and(|existing| {
                existing
                    .iter()
                    .any(|(start, end)| span.0 <= *end && *start <= span.1)
            }) {
                return Err(format!("overlapping templates selected for {core}"));
            }
            spans.entry(path).or_default().push(span);
        }
    }
    Ok(())
}

fn run() -> Result<PathBuf, String> {
    let args: Vec<String> = env::args().collect();
    let catalog = PathBuf::from(arg(&args, "--catalog")?);
    let candidate = PathBuf::from(arg(&args, "--candidate-root")?)
        .canonicalize()
        .map_err(|error| error.to_string())?;
    let menu_path = PathBuf::from(arg(&args, "--menu")?);
    let plan_path = PathBuf::from(arg(&args, "--plan")?);
    let foreman_id = arg(&args, "--foreman-id")?;
    let python = PathBuf::from(arg(&args, "--python")?);
    let verifier = PathBuf::from(arg(&args, "--verifier")?);
    let run_root = PathBuf::from(arg(&args, "--run-root")?);
    let allowed_base =
        Path::new(r"L:\LocalCoder\workspace\aios_rebuild\rebuild_runs\full_catalog_rebuilds");
    fs::create_dir_all(allowed_base).map_err(|error| error.to_string())?;
    fs::create_dir_all(run_root.parent().ok_or("run root has no parent")?)
        .map_err(|error| error.to_string())?;
    let allowed_base = allowed_base
        .canonicalize()
        .map_err(|error| error.to_string())?;
    let run_root = run_root.canonicalize().map_err(|error| error.to_string())?;
    if !run_root.starts_with(&allowed_base) {
        return Err("output base escapes isolated LocalCoder full-catalog run root".into());
    }
    let run_id = run_root
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or("run root name invalid")?
        .to_owned();
    let output_root = run_root.join("candidate");
    if output_root.exists() || run_root.join("run_receipt.json").exists() {
        return Err("run root already contains a candidate or receipt".into());
    }
    let plan_path = plan_path
        .canonicalize()
        .map_err(|error| error.to_string())?;
    let menu_path = menu_path
        .canonicalize()
        .map_err(|error| error.to_string())?;
    if !plan_path.starts_with(&run_root) || !menu_path.starts_with(&run_root) {
        return Err("Mind plan and candidate menu must remain inside this run directory".into());
    }
    let verified_source_root = Path::new(
        r"L:\LocalCoder\workspace\aios_rebuild\rebuild_runs\full_horizontal_candidate_v5\candidate",
    )
    .canonicalize()
    .map_err(|error| error.to_string())?;
    if !candidate.starts_with(&verified_source_root) {
        return Err("source candidate is outside the verified full-source run".into());
    }
    fs::create_dir(&output_root).map_err(|error| error.to_string())?;

    let registry_path = catalog.join("registry.json");
    let data_path = catalog.join("functions.jsonl");
    let index_path = catalog.join("lookup.json");
    let registry_bytes = read(&registry_path)?;
    let registry_hash = sha(&registry_bytes);
    let registry: Value =
        serde_json::from_slice(&registry_bytes).map_err(|error| error.to_string())?;
    let menu_bytes = read(&menu_path)?;
    let menu_hash = sha(&menu_bytes);
    let menu: Value = serde_json::from_slice(&menu_bytes).map_err(|error| error.to_string())?;
    if menu["schema"] != "viv_full_aios_template_menu_v1"
        || menu["catalog_registry_sha256"].as_str() != Some(registry_hash.as_str())
        || registry["status"] != "PASS"
        || sha_file(&data_path)? != text(&registry, "functions_jsonl_sha256")?
        || sha_file(&index_path)? != text(&registry, "lookup_sha256")?
    {
        return Err("catalog or Mind menu integrity preflight failed".into());
    }
    let plan_bytes = read(&plan_path)?;
    let plan: Value = serde_json::from_slice(&plan_bytes).map_err(|error| error.to_string())?;
    if text(&plan, "foreman_snapshot_id")? != foreman_id
        || text(&plan, "catalog_registry_sha256")? != registry_hash
        || text(&plan, "candidate_menu_sha256")? != menu_hash
    {
        return Err("Mind plan is not bound to this Foreman snapshot and candidate menu".into());
    }
    let selected = selected_templates(&plan, &menu, &registry)?;
    let core_names: BTreeSet<String> = registry["core_names"]
        .as_array()
        .ok_or("catalog cores missing")?
        .iter()
        .filter_map(Value::as_str)
        .map(str::to_owned)
        .collect();
    let cards = menu["cards"].as_object().ok_or("candidate cards missing")?;
    let mut scores = BTreeMap::<String, String>::new();
    let mut task_specs = Vec::new();
    for core in &core_names {
        let id = format!("stamp_{core}");
        task_specs.push(TaskSpec {
            id: id.clone(),
            agent_id: format!("swarm_{core}"),
            agent_kind: AgentKind::Deterministic,
            capability: "stamp_catalog_templates".into(),
            objective: format!("Stamp Mind-selected verified templates for {core}"),
            depends_on: vec!["mind_plan".into()],
        });
        scores.insert(id, core.clone());
        if cards.get(core).is_none() {
            return Err(format!("candidate menu omitted {core}"));
        }
    }
    let plan_hash = sha(&plan_bytes);
    let scope = format!("full_catalog_rebuild/{run_id}");
    let mut control = Control::new(vec![
        ("stamp_catalog_templates".into(), scope.clone()),
        ("verify_template_composition".into(), scope.clone()),
    ]);
    control.approve_tool(true, "stamp_catalog_templates", &scope)?;
    control.approve_tool(true, "verify_template_composition", &scope)?;
    control.seal_task("mind_plan", "viv_mind", None, None, &plan)?;
    control.open_task("mind_plan", "viv_mind", None)?;
    control.complete_task("mind_plan", "viv_mind", &plan_hash)?;
    let mut graph = TaskGraph::new();
    let mind_generation_count = u8::from(plan["plan_origin"] == "viv_mind_model");
    graph.add_batch(vec![TaskSpec {
        id: "mind_plan".into(),
        agent_id: "viv_mind".into(),
        agent_kind: if mind_generation_count == 1 {
            AgentKind::Model
        } else {
            AgentKind::Deterministic
        },
        capability: "select_verified_aios_templates".into(),
        objective: text(&plan, "intent")?.to_owned(),
        depends_on: vec![],
    }])?;
    graph.claim("mind_plan")?;
    graph.complete("mind_plan", mind_generation_count)?;
    graph.add_batch(task_specs.clone())?;

    let index: Value =
        serde_json::from_slice(&read(&index_path)?).map_err(|error| error.to_string())?;
    preflight_selected_spans(&selected, &index, &data_path, &candidate, &core_names)?;
    let mut checksums = BTreeMap::new();
    let mut payloads = BTreeMap::new();
    for spec in &task_specs {
        let core = &scores[&spec.id];
        let ids = &selected[core];
        let parent_hash = plan_hash.clone();
        let payload = json!({"task_id":spec.id,"core":core,"template_ids":ids,"candidate_root":output_root,"catalog_registry_sha256":registry_hash,"parent_plan_sha256":parent_hash});
        let checksum = control.seal_task(
            &spec.id,
            &spec.agent_id,
            Some("mind_plan"),
            Some(&plan_hash),
            &payload,
        )?;
        if control.open_task(&spec.id, &spec.agent_id, Some(&plan_hash))? != payload {
            return Err(format!("task snapshot payload mismatch: {}", spec.id));
        }
        checksums.insert(spec.id.clone(), checksum);
        payloads.insert(spec.id.clone(), payload);
    }
    let worker_results = graph.run_ready_parallel(|spec| {
        let core = scores.get(&spec.id).ok_or("task core mapping missing")?;
        let ids = selected.get(core).ok_or("task selection missing")?;
        let target = output_root.join(core).join(format!("{core}_selected.py"));
        let mut snippets = Vec::new();
        let mut rows = Vec::new();
        let mut occupied = BTreeMap::<String, Vec<(usize, usize)>>::new();
        let mut names = BTreeSet::new();
        for id in ids {
            let (snippet, row) = source_span(id, core, &index, &data_path, &candidate, &core_names)?;
            let relative = text(&row, "source_path")?.to_owned();
            let span = (
                row["start_line"].as_u64().ok_or("line start missing")? as usize,
                row["end_line"].as_u64().ok_or("line end missing")? as usize,
            );
            if occupied.get(&relative).is_some_and(|items| items.iter().any(|(a, b)| span.0 <= *b && *a <= span.1)) {
                return Err(format!("overlapping templates selected for {core}"));
            }
            occupied.entry(relative).or_default().push(span);
            let name = text(&row, "qualified_name")?.to_owned();
            if !names.insert(name.clone()) {
                return Err(format!("duplicate declaration selected for {core}: {name}"));
            }
            snippets.push(snippet.trim_end_matches(['\r', '\n']).to_owned());
            rows.push(row);
        }
        let code = format!("{}\n", snippets.join("\n\n\n"));
        if let Some(parent) = target.parent() {
            fs::create_dir_all(parent).map_err(|error| error.to_string())?;
        }
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&target)
            .map_err(|error| error.to_string())?;
        file.write_all(code.as_bytes()).map_err(|error| error.to_string())?;
        file.sync_all().map_err(|error| error.to_string())?;
        let hash = sha(code.as_bytes());
        fs::write(
            target.with_extension("templates.json"),
            serde_json::to_vec_pretty(&json!({"core":core,"template_ids":ids,"templates":rows,"artifact_sha256":hash,"source_code_executed":false}))
                .map_err(|error| error.to_string())?,
        )
        .map_err(|error| error.to_string())?;
        Ok(0)
    })?;
    let mut task_rows = Vec::new();
    for (id, result) in worker_results {
        result?;
        let core = &scores[&id];
        let target = output_root.join(core).join(format!("{core}_selected.py"));
        let hash = sha_file(&target)?;
        let spec = task_specs
            .iter()
            .find(|row| row.id == id)
            .ok_or("task spec missing")?;
        control.complete_task(&id, &spec.agent_id, &hash)?;
        task_rows.push(json!({"task_id":id,"core":core,"owner":spec.agent_id,"generation_count":0,"snapshot_checksum":checksums[&id],"payload":payloads[&id],"artifact_path":target,"artifact_sha256":hash,"template_ids":selected[core]}));
    }
    if task_rows.len() != core_names.len() {
        return Err("not every AIOS core was stamped".into());
    }
    let verify = Command::new(&python)
        .arg(&verifier)
        .arg(&output_root)
        .arg(&menu_path)
        .arg(&catalog)
        .arg(&candidate)
        .output()
        .map_err(|error| format!("start independent syntax verifier: {error}"))?;
    if !verify.status.success() {
        return Err(format!(
            "catalog candidate verification held: {}",
            String::from_utf8_lossy(&verify.stderr)
        ));
    }
    let verification: Value =
        serde_json::from_slice(&verify.stdout).map_err(|error| error.to_string())?;
    if verification["status"] != "PASS" {
        return Err(format!(
            "catalog candidate verification failed: {verification}"
        ));
    }
    let receipt = json!({
        "schema":"viv_full_aios_catalog_rebuild_receipt_v1",
        "status":"PASS_CANDIDATE_COMPOSITION_NOT_AIOS_REPLACEMENT",
        "plan_origin":plan["plan_origin"],
        "run_id":run_id,
        "intent":plan["intent"],
        "foreman_snapshot_id":foreman_id,
        "catalog_registry_sha256":registry_hash,
        "candidate_menu_sha256":menu_hash,
        "mind_plan_sha256":plan_hash,
        "mind_plan_path":plan_path,
        "mind_transcript_path":run_root.join("mind_transcript.json"),
        "candidate_menu_path":menu_path,
        "candidate_root":output_root,
        "core_count":core_names.len(),
        "stamped_core_count":task_rows.len(),
        "template_count":task_rows.iter().map(|row|row["template_ids"].as_array().map(Vec::len).unwrap_or(0)).sum::<usize>(),
        "mind_plan_generation_count":mind_generation_count,
        "swarm_generation_count":0,
        "source_modified":false,
        "source_code_executed":false,
        "verification":verification,
        "tasks":task_rows,
        "model_rationale_retained":true
    });
    let receipt_path = run_root.join("run_receipt.json");
    fs::write(
        &receipt_path,
        serde_json::to_vec_pretty(&receipt).map_err(|error| error.to_string())?,
    )
    .map_err(|error| error.to_string())?;
    let receipt_hash = sha_file(&receipt_path)?;
    fs::write(
        run_root.join("run_receipt.sha256"),
        format!("{receipt_hash}  run_receipt.json\n"),
    )
    .map_err(|error| error.to_string())?;
    Ok(receipt_path)
}

fn existing_files(root: &Path) -> Vec<String> {
    let mut pending = vec![root.to_path_buf()];
    let mut files = Vec::new();
    while let Some(directory) = pending.pop() {
        let Ok(entries) = fs::read_dir(directory) else {
            continue;
        };
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_dir() {
                pending.push(path);
            } else if let Ok(relative) = path.strip_prefix(root) {
                files.push(relative.to_string_lossy().replace('\\', "/"));
            }
        }
    }
    files.sort();
    files
}

fn main() {
    match run() {
        Ok(path) => println!("{{\"status\":\"PASS\",\"receipt\":{:?}}}", path),
        Err(error) => {
            let args: Vec<String> = env::args().collect();
            if let Ok(root_text) = arg(&args, "--run-root") {
                let root = PathBuf::from(root_text);
                let hold_path = root.join("rust_hold_receipt.json");
                if root.is_dir() && !hold_path.exists() {
                    let partial_root = root.join("candidate");
                    let partial = existing_files(&partial_root);
                    let value = json!({
                        "schema":"viv_full_aios_catalog_rebuild_hold_v1",
                        "status":"HOLD",
                        "reason":error,
                        "source_modified":false,
                        "source_code_executed":false,
                        "partial_candidate_files":partial
                    });
                    if let Ok(bytes) = serde_json::to_vec_pretty(&value) {
                        if let Ok(mut file) = OpenOptions::new()
                            .write(true)
                            .create_new(true)
                            .open(&hold_path)
                        {
                            if file.write_all(&bytes).is_ok() && file.sync_all().is_ok() {
                                let _ = fs::write(
                                    root.join("rust_hold_receipt.sha256"),
                                    format!("{}  rust_hold_receipt.json\n", sha(&bytes)),
                                );
                            }
                        }
                    }
                }
            }
            eprintln!("FULL_AIOS_CATALOG_REBUILD_HOLD: {error}");
            std::process::exit(1);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn registry() -> Value {
        json!({"core_names":["alpha_core","beta_core"]})
    }

    fn menu() -> Value {
        json!({"cards":{
            "alpha_core":[{"candidate_key":"T1","template_id":"fn-a","qualified_name":"AlphaCore"}],
            "beta_core":[{"candidate_key":"T2","template_id":"fn-b","qualified_name":"BetaCore"}]
        }})
    }

    fn plan() -> Value {
        json!({"schema":"viv_full_aios_catalog_plan_v1",
            "plan_origin":"contract_fixture",
            "intent":"Contract test rebuilds the full AIOS candidate from verified source templates.",
            "approved_tools":["stamp_catalog_templates","verify_template_composition"],
            "selections":[
                {"core":"alpha_core","candidate_keys":["T1"],"reason":"AlphaCore represents its source subsystem."},
                {"core":"beta_core","candidate_keys":["T2"],"reason":"BetaCore represents its source subsystem."}
        ]})
    }

    #[test]
    fn complete_per_core_selection_is_admitted() {
        assert_eq!(
            selected_templates(&plan(), &menu(), &registry())
                .unwrap()
                .len(),
            2
        );
    }

    #[test]
    fn rejects_missing_core_unknown_id_duplicate_and_overbound() {
        let mut value = plan();
        value["selections"].as_array_mut().unwrap().pop();
        assert!(selected_templates(&value, &menu(), &registry()).is_err());
        let mut value = plan();
        value["selections"][0]["candidate_keys"][0] = json!("T9");
        assert!(selected_templates(&value, &menu(), &registry()).is_err());
        let mut value = plan();
        value["selections"][1]["core"] = json!("alpha_core");
        assert!(selected_templates(&value, &menu(), &registry()).is_err());
        let mut value = plan();
        value["selections"][0]["candidate_keys"] = json!(["T1", "T1"]);
        assert!(selected_templates(&value, &menu(), &registry()).is_err());
    }

    #[test]
    fn tool_approval_and_manifest_path_are_fixed() {
        let mut value = plan();
        value["approved_tools"] = json!(["execute_arbitrary_code"]);
        assert!(selected_templates(&value, &menu(), &registry()).is_err());
        assert!(safe_relative("../outside.py").is_err());
        assert!(safe_relative("core/file.py").is_ok());
        let mut value = plan();
        value["intent"] = json!("stamp_catalog_templates");
        assert!(selected_templates(&value, &menu(), &registry()).is_err());
    }

    #[test]
    fn rejects_generic_rationales_that_do_not_name_the_selected_template() {
        let mut value = plan();
        value["selections"][0]["reason"] = json!("This is the main system component.");
        assert!(selected_templates(&value, &menu(), &registry()).is_err());
    }

    #[test]
    fn rejects_model_position_collapse_across_many_cores() {
        let cores: Vec<String> = (0..10).map(|i| format!("core_{i}")).collect();
        let registry = json!({"core_names":cores});
        let mut cards = serde_json::Map::new();
        let mut selections = Vec::new();
        for core in registry["core_names"].as_array().unwrap() {
            let name = core.as_str().unwrap();
            cards.insert(
                name.to_owned(),
                json!([
                    {"candidate_key":"T1","template_id":format!("{name}-first"),"qualified_name":format!("{name}First")},
                    {"candidate_key":"T2","template_id":format!("{name}-second"),"qualified_name":format!("{name}Second")}
                ]),
            );
            selections.push(json!({
                "core":name,
                "candidate_keys":["T1"],
                "reason":format!("{name}First defines its core-specific behavior.")
            }));
        }
        let menu = json!({"cards":cards});
        let mut value = plan();
        value["selections"] = json!(selections);
        let error = selected_templates(&value, &menu, &registry).unwrap_err();
        assert!(error.contains("collapsed onto the same menu position"));
    }
}
