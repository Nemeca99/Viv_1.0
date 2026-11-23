//! Read-only, scoped file observation for a coding agent.
use hive_control::{sha, Control};
use serde_json::{json, Value};
use std::io::{self, Read};
use std::path::{Component, Path, PathBuf};

fn main() {
    let result = run();
    match result {
        Ok(value) => println!("{}", value),
        Err(error) => { println!("{}", json!({"ok": false, "error": error})); std::process::exit(1); }
    }
}

fn run() -> Result<Value, String> {
    let root = std::env::args_os().nth(1).ok_or("missing workspace root")?;
    let root = PathBuf::from(root).canonicalize().map_err(|e| e.to_string())?;
    let mut input = String::new();
    io::stdin().take(65537).read_to_string(&mut input).map_err(|e| e.to_string())?;
    if input.len() > 65536 { return Err("request too large".into()); }
    let request: Value = serde_json::from_str(&input).map_err(|e| e.to_string())?;
    let rel = Path::new(request["path"].as_str().ok_or("missing path")?);
    if rel.components().any(|c| !matches!(c, Component::Normal(_))) { return Err("invalid path".into()); }
    let path = root.join(rel).canonicalize().map_err(|e| e.to_string())?;
    if !path.starts_with(&root) || !path.is_file() { return Err("path outside workspace or not a file".into()); }
    let control = Control::new(vec![("read_file".into(), "workspace".into())]);
    control.approve_tool(true, "read_file", "workspace")?;
    let metadata = std::fs::metadata(&path).map_err(|e| e.to_string())?;
    if metadata.len() > 262144 { return Err("file exceeds read limit".into()); }
    let bytes = std::fs::read(&path).map_err(|e| e.to_string())?;
    let content = String::from_utf8(bytes.clone()).map_err(|_| "file is not UTF-8")?;
    Ok(json!({"ok":true,"path":rel.to_string_lossy(),"sha256":sha(&bytes),"content":content}))
}
