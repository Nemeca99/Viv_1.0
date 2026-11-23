//! Append exact Architect-quoted memory through the deterministic Hive authority gate.
use hive_control::{sha, Control};
use serde::Deserialize;
use serde_json::json;
use std::fs::{self, OpenOptions};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

#[derive(Deserialize)]
struct Request {
    architect_approved: bool,
    privacy_authorized: bool,
    target: String,
    quote: String,
    source_user_text: String,
    session_id: String,
    receipt_id: String,
}

struct Lock(PathBuf);
impl Drop for Lock {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
    }
}

fn direct_memory_intent(text: &str) -> bool {
    let lower = text.to_lowercase();
    let intent = [
        "remember",
        "save",
        "store",
        "add",
        "write",
        "update",
        "make sure",
    ]
    .iter()
    .any(|word| lower.contains(word));
    let target = ["memory", "user.md", "user profile", "this model knows"]
        .iter()
        .any(|word| lower.contains(word));
    let negated = [
        "don't remember",
        "do not remember",
        "don't save",
        "do not save",
        "never store",
        "don't store",
        "do not store",
    ]
    .iter()
    .any(|phrase| lower.contains(phrase));
    intent && target && !negated
}

fn acquire_lock(path: &Path) -> Result<Lock, String> {
    for attempt in 0..3 {
        match OpenOptions::new().write(true).create_new(true).open(path) {
            Ok(mut file) => {
                let lock = Lock(path.to_path_buf());
                if let Err(error) =
                    writeln!(file, "{}", std::process::id()).and_then(|_| file.sync_all())
                {
                    drop(lock);
                    return Err(error.to_string());
                }
                return Ok(lock);
            }
            Err(e) if e.kind() == io::ErrorKind::AlreadyExists && attempt < 2 => {
                thread::sleep(Duration::from_millis(25 * (attempt + 1)));
            }
            Err(e) if e.kind() == io::ErrorKind::AlreadyExists => {
                return Err("memory lock is busy; no write performed".into())
            }
            Err(e) => return Err(e.to_string()),
        }
    }
    Err("memory lock acquisition failed".into())
}

fn run() -> Result<serde_json::Value, String> {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("aios_rebuild/memory/hermes_agent");
    let memory_dir = root
        .join("memories")
        .canonicalize()
        .map_err(|e| e.to_string())?;
    let state_dir = root.canonicalize().map_err(|e| e.to_string())?;
    let mut raw = String::new();
    io::stdin()
        .take(16385)
        .read_to_string(&mut raw)
        .map_err(|e| e.to_string())?;
    if raw.len() > 16384 {
        return Err("request exceeds 16 KiB".into());
    }
    let req: Request = serde_json::from_str(&raw).map_err(|e| e.to_string())?;
    if !req.architect_approved || !req.privacy_authorized {
        return Err("Architect intent or PrivacyCore authorization missing".into());
    }
    if !matches!(req.target.as_str(), "MEMORY.md" | "USER.md") {
        return Err("target must be MEMORY.md or USER.md".into());
    }
    if req.quote.trim().is_empty() || req.quote.len() > 2000 || req.quote.contains('\0') {
        return Err("quoted entry is empty or exceeds 2000 bytes".into());
    }
    if !req.source_user_text.contains(&req.quote) || !direct_memory_intent(&req.source_user_text) {
        return Err("quote is not exact user-authored text with direct memory intent".into());
    }
    if req.session_id.is_empty() || req.session_id.len() > 160 {
        return Err("invalid OpenCode session identity".into());
    }
    if req.receipt_id.len() != 32 || !req.receipt_id.chars().all(|c| c.is_ascii_hexdigit()) {
        return Err("invalid receipt identity".into());
    }
    let target = memory_dir
        .join(&req.target)
        .canonicalize()
        .map_err(|e| e.to_string())?;
    if target.parent() != Some(memory_dir.as_path())
        || target.file_name().and_then(|n| n.to_str()) != Some(&req.target)
        || !target.is_file()
    {
        return Err("memory target escaped its approved directory".into());
    }
    let control = Control::new(vec![("append_memory".into(), "hermes_agent".into())]);
    control.approve_tool(req.architect_approved, "append_memory", "hermes_agent")?;

    let _lock = acquire_lock(&target.with_file_name(format!("{}.lock", req.target)))?;
    let old = fs::read(&target).map_err(|e| e.to_string())?;
    let old_hash = sha(&old);
    let marker = format!("Architect-stated instruction: {}", req.quote.trim());
    if String::from_utf8_lossy(&old).contains(&marker) {
        return Ok(json!({"ok":true,"already_present":true,"target":target,"sha256":old_hash}));
    }
    let snapshot_dir = state_dir.join("snapshots");
    fs::create_dir_all(&snapshot_dir).map_err(|e| e.to_string())?;
    let snapshot = snapshot_dir.join(format!("{old_hash}.snapshot"));
    if snapshot.exists() {
        if sha(&fs::read(&snapshot).map_err(|e| e.to_string())?) != old_hash {
            return Err("existing snapshot hash mismatch".into());
        }
    } else {
        let mut snapshot_file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&snapshot)
            .map_err(|e| e.to_string())?;
        snapshot_file.write_all(&old).map_err(|e| e.to_string())?;
        snapshot_file.sync_all().map_err(|e| e.to_string())?;
    }
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|e| e.to_string())?
        .as_secs();
    let receipt_dir = state_dir.join("receipts");
    fs::create_dir_all(&receipt_dir).map_err(|e| e.to_string())?;
    let receipt_path = receipt_dir.join(format!("memory-{}.jsonl", req.receipt_id));
    let mut out = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&receipt_path)
        .map_err(|e| e.to_string())?;
    let prepared = json!({"kind":"memory_append","status":"prepared","target":req.target,
        "source_session":req.session_id,"source_quote_sha256":sha(req.quote.as_bytes()),
        "previous_sha256":old_hash,"snapshot":snapshot,"privacy_authorized":true,
        "rust_tool":"append_memory/hermes_agent","captured_at_unix":now});
    serde_json::to_writer(&mut out, &prepared).map_err(|e| e.to_string())?;
    out.write_all(b"\n").map_err(|e| e.to_string())?;
    out.sync_all().map_err(|e| e.to_string())?;
    let entry = format!(
        "\n§\nArchitect-stated instruction: {}\nSource: OpenCode session {}; captured_at_unix={}\n",
        req.quote.trim(),
        req.session_id,
        now
    );
    let mut file = OpenOptions::new()
        .append(true)
        .open(&target)
        .map_err(|e| e.to_string())?;
    file.write_all(entry.as_bytes())
        .map_err(|e| e.to_string())?;
    file.sync_all().map_err(|e| e.to_string())?;
    drop(file);
    let new_hash = sha(&fs::read(&target).map_err(|e| e.to_string())?);

    let committed = json!({"kind":"memory_append","status":"committed","new_sha256":new_hash});
    let mut out = OpenOptions::new()
        .append(true)
        .open(&receipt_path)
        .map_err(|e| e.to_string())?;
    serde_json::to_writer(&mut out, &committed).map_err(|e| e.to_string())?;
    out.write_all(b"\n").map_err(|e| e.to_string())?;
    out.sync_all().map_err(|e| e.to_string())?;
    Ok(
        json!({"ok":true,"target":target,"previous_sha256":old_hash,"new_sha256":new_hash,"snapshot":snapshot,"receipt":receipt_path}),
    )
}

fn main() {
    match run() {
        Ok(value) => println!("{value}"),
        Err(error) => {
            eprintln!("localcoder_memory_gate: {error}");
            std::process::exit(1);
        }
    }
}
