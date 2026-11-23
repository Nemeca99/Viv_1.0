//! viv-broker: the only path from Viv's container to disk.
//!
//! The container has no mounts and no network; it cannot write anywhere on the host.
//! This host-side program PULLS an explicitly requested file out of the container
//! (`docker exec ... cat`), validates it against a fixed policy, and only then
//! writes it under the output root. Every decision (allow or deny) is receipted
//! with a SHA-256. No external crates.
//!
//! usage: viv-broker export <container-path> [--container NAME] [--out DIR]
//! exit:  0 allowed and written, 3 denied by policy, 2 usage/runtime error

use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{SystemTime, UNIX_EPOCH};

const DEFAULT_CONTAINER: &str = "viv-vm";
const DEFAULT_OUT: &str = r"E:\Viv_Sandbox\out";
const CONTAINER_ROOT: &str = "/work/";
const MAX_BYTES: usize = 2 * 1024 * 1024;
// Extensions that may leave the container. `.rs` is added to the .py/.md/.json/.pdf
// whitelist so Viv's Rust work can be kept; remove it here to restore the strict list.
const ALLOWED_EXT: [&str; 5] = ["py", "md", "json", "pdf", "rs"];

#[derive(Debug, PartialEq)]
enum Deny {
    NotUnderWork,
    TraversalOrNul,
    ExtensionNotAllowed,
    NotRegularFile,
    SymlinkEscape,
    TooLarge,
    EmptyName,
    ContainerError,
}

/// Static validation of a container path string, before touching the container.
fn validate_path(p: &str) -> Result<String, Deny> {
    if p.contains('\0') || p.contains('\\') {
        return Err(Deny::TraversalOrNul);
    }
    if !p.starts_with(CONTAINER_ROOT) {
        return Err(Deny::NotUnderWork);
    }
    let rel = &p[CONTAINER_ROOT.len()..];
    if rel.is_empty() || rel.ends_with('/') {
        return Err(Deny::EmptyName);
    }
    for part in rel.split('/') {
        if part.is_empty() || part == "." || part == ".." {
            return Err(Deny::TraversalOrNul);
        }
    }
    let ext = Path::new(rel)
        .extension()
        .and_then(|e| e.to_str())
        .map(|e| e.to_ascii_lowercase())
        .unwrap_or_default();
    if !ALLOWED_EXT.contains(&ext.as_str()) {
        return Err(Deny::ExtensionNotAllowed);
    }
    Ok(rel.to_string())
}

/// Destination-safe relative path: only [A-Za-z0-9._-] per component.
fn sanitize_rel(rel: &str) -> PathBuf {
    let mut out = PathBuf::new();
    for part in rel.split('/') {
        let clean: String = part
            .chars()
            .map(|c| if c.is_ascii_alphanumeric() || c == '.' || c == '_' || c == '-' { c } else { '_' })
            .collect();
        out.push(clean);
    }
    out
}

fn docker_exec(container: &str, args: &[&str]) -> Result<Vec<u8>, Deny> {
    let mut cmd = Command::new("docker");
    cmd.arg("exec").arg(container).args(args);
    cmd.stdin(Stdio::null());
    match cmd.output() {
        Ok(o) if o.status.success() => Ok(o.stdout),
        _ => Err(Deny::ContainerError),
    }
}

/// Container-side checks: regular file, no symlink escape out of /work, size cap.
fn inspect_in_container(container: &str, path: &str) -> Result<(), Deny> {
    let kind = docker_exec(container, &["stat", "-c", "%F", "--", path])?;
    if String::from_utf8_lossy(&kind).trim() != "regular file" {
        return Err(Deny::NotRegularFile);
    }
    let real = docker_exec(container, &["readlink", "-f", "--", path])?;
    if !String::from_utf8_lossy(&real).trim().starts_with(CONTAINER_ROOT) {
        return Err(Deny::SymlinkEscape);
    }
    let size = docker_exec(container, &["stat", "-c", "%s", "--", path])?;
    let n: usize = String::from_utf8_lossy(&size).trim().parse().map_err(|_| Deny::ContainerError)?;
    if n > MAX_BYTES {
        return Err(Deny::TooLarge);
    }
    Ok(())
}

fn now() -> u64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0)
}

fn json_escape(s: &str) -> String {
    let mut o = String::new();
    for c in s.chars() {
        match c {
            '"' => o.push_str("\\\""),
            '\\' => o.push_str("\\\\"),
            '\n' => o.push_str("\\n"),
            c if (c as u32) < 0x20 => o.push_str(&format!("\\u{:04x}", c as u32)),
            c => o.push(c),
        }
    }
    o
}

fn receipt(out: &Path, verdict: &str, reason: &str, src: &str, dest: &str, sha: &str, size: usize) {
    let _ = fs::create_dir_all(out);
    let line = format!(
        "{{\"ts\":{},\"verdict\":\"{}\",\"reason\":\"{}\",\"src\":\"{}\",\"dest\":\"{}\",\"sha256\":\"{}\",\"bytes\":{}}}\n",
        now(), verdict, reason, json_escape(src), json_escape(dest), sha, size
    );
    if let Ok(mut f) = OpenOptions::new().create(true).append(true).open(out.join("receipts.jsonl")) {
        let _ = f.write_all(line.as_bytes());
    }
}

fn export(container: &str, out: &Path, cpath: &str) -> i32 {
    let rel = match validate_path(cpath) {
        Ok(r) => r,
        Err(d) => return deny(out, cpath, d),
    };
    if let Err(d) = inspect_in_container(container, cpath) {
        return deny(out, cpath, d);
    }
    let bytes = match docker_exec(container, &["cat", "--", cpath]) {
        Ok(b) => b,
        Err(d) => return deny(out, cpath, d),
    };
    if bytes.len() > MAX_BYTES {
        return deny(out, cpath, Deny::TooLarge);
    }
    let sha = sha256_hex(&bytes);
    let mut dest = out.join("files").join(sanitize_rel(&rel));
    if dest.exists() {
        // Monotonic: never overwrite. Keep the older file, store the new one beside it.
        let stem = dest.file_stem().map(|s| s.to_string_lossy().to_string()).unwrap_or_default();
        let ext = dest.extension().map(|s| format!(".{}", s.to_string_lossy())).unwrap_or_default();
        dest.set_file_name(format!("{}.{}{}", stem, &sha[..12], ext));
    }
    if let Some(parent) = dest.parent() {
        if fs::create_dir_all(parent).is_err() {
            return deny(out, cpath, Deny::ContainerError);
        }
    }
    if fs::write(&dest, &bytes).is_err() {
        return deny(out, cpath, Deny::ContainerError);
    }
    receipt(out, "ALLOW", "ok", cpath, &dest.to_string_lossy(), &sha, bytes.len());
    println!("ALLOW {} {} {}", dest.display(), sha, bytes.len());
    0
}

fn deny(out: &Path, cpath: &str, d: Deny) -> i32 {
    let reason = format!("{:?}", d);
    receipt(out, "DENY", &reason, cpath, "", "", 0);
    println!("DENY {}", reason);
    3
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 3 || args[1] != "export" {
        eprintln!("usage: viv-broker export <container-path> [--container NAME] [--out DIR]");
        std::process::exit(2);
    }
    let mut container = DEFAULT_CONTAINER.to_string();
    let mut out = PathBuf::from(DEFAULT_OUT);
    let mut i = 3;
    while i + 1 < args.len() {
        match args[i].as_str() {
            "--container" => container = args[i + 1].clone(),
            "--out" => out = PathBuf::from(&args[i + 1]),
            _ => {}
        }
        i += 2;
    }
    std::process::exit(export(&container, &out, &args[2]));
}

// ---- SHA-256 (FIPS 180-4), std only ----
const K: [u32; 64] = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
];

fn sha256_hex(data: &[u8]) -> String {
    let mut h: [u32; 8] = [
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
    ];
    let mut msg = data.to_vec();
    msg.push(0x80);
    while msg.len() % 64 != 56 {
        msg.push(0);
    }
    msg.extend_from_slice(&((data.len() as u64) * 8).to_be_bytes());
    for chunk in msg.chunks(64) {
        let mut w = [0u32; 64];
        for i in 0..16 {
            w[i] = u32::from_be_bytes([chunk[4 * i], chunk[4 * i + 1], chunk[4 * i + 2], chunk[4 * i + 3]]);
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16].wrapping_add(s0).wrapping_add(w[i - 7]).wrapping_add(s1);
        }
        let mut v = h;
        for i in 0..64 {
            let s1 = v[4].rotate_right(6) ^ v[4].rotate_right(11) ^ v[4].rotate_right(25);
            let ch = (v[4] & v[5]) ^ (!v[4] & v[6]);
            let t1 = v[7].wrapping_add(s1).wrapping_add(ch).wrapping_add(K[i]).wrapping_add(w[i]);
            let s0 = v[0].rotate_right(2) ^ v[0].rotate_right(13) ^ v[0].rotate_right(22);
            let maj = (v[0] & v[1]) ^ (v[0] & v[2]) ^ (v[1] & v[2]);
            let t2 = s0.wrapping_add(maj);
            v[7] = v[6];
            v[6] = v[5];
            v[5] = v[4];
            v[4] = v[3].wrapping_add(t1);
            v[3] = v[2];
            v[2] = v[1];
            v[1] = v[0];
            v[0] = t1.wrapping_add(t2);
        }
        for i in 0..8 {
            h[i] = h[i].wrapping_add(v[i]);
        }
    }
    h.iter().map(|x| format!("{:08x}", x)).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sha256_known_vectors() {
        assert_eq!(sha256_hex(b"abc"), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
        assert_eq!(sha256_hex(b""), "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
    }

    #[test]
    fn accepts_plain_work_files() {
        assert_eq!(validate_path("/work/a.py"), Ok("a.py".to_string()));
        assert_eq!(validate_path("/work/sub/dir/m.rs"), Ok("sub/dir/m.rs".to_string()));
        assert_eq!(validate_path("/work/NOTES.MD"), Ok("NOTES.MD".to_string()));
    }

    #[test]
    fn rejects_escapes_and_bad_names() {
        assert_eq!(validate_path("/etc/passwd"), Err(Deny::NotUnderWork));
        assert_eq!(validate_path("/work/../etc/a.py"), Err(Deny::TraversalOrNul));
        assert_eq!(validate_path("/work//a.py"), Err(Deny::TraversalOrNul));
        assert_eq!(validate_path("/work/./a.py"), Err(Deny::TraversalOrNul));
        assert_eq!(validate_path("/work/a\\b.py"), Err(Deny::TraversalOrNul));
        assert_eq!(validate_path("/work/a\0.py"), Err(Deny::TraversalOrNul));
        assert_eq!(validate_path("/work/"), Err(Deny::EmptyName));
        assert_eq!(validate_path("/workshop/a.py"), Err(Deny::NotUnderWork));
    }

    #[test]
    fn rejects_non_whitelisted_extensions() {
        for p in ["/work/a.exe", "/work/a.sh", "/work/a.bat", "/work/a.dll", "/work/noext", "/work/a.py.exe"] {
            assert_eq!(validate_path(p), Err(Deny::ExtensionNotAllowed), "{p}");
        }
    }

    #[test]
    fn sanitizes_destination() {
        assert_eq!(sanitize_rel("a b/c$d.py"), PathBuf::from("a_b").join("c_d.py"));
    }
}
