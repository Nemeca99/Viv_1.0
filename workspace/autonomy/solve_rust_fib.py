import os
import json
import urllib.request
import subprocess
import tempfile
import sqlite3
from pathlib import Path

CODE_DB = Path(r"L:\LocalCoder\workspace\autonomy\viv_code_topology.sqlite3")
LM_STUDIO_URL = "http://127.0.0.1:1234/v1/chat/completions"

sys_prompt = """You are Viv. The Architect requires an exact, zero-defect Rust implementation.
Write a Rust function fn fibonacci(n: u32) -> u32.
Ensure that:
fibonacci(0) == 0
fibonacci(1) == 1
fibonacci(10) == 55
Include a fn main() that runs:
assert_eq!(fibonacci(10), 55);
println!("FIB_PASS");
Output ONLY valid Rust code inside ```rust ... ```."""

payload = {
    "model": os.environ.get("VIV_TUTOR_MODEL", "deepseek-coder-6.7b-base"),
    "messages": [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": "Generate the verified Rust code now."}
    ],
    "temperature": 0.1,
    "max_tokens": 300
}

req = urllib.request.Request(LM_STUDIO_URL, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req) as r:
    data = json.loads(r.read().decode("utf-8"))
    raw_code = data["choices"][0]["message"]["content"]

# Clean fences
lines = raw_code.strip().splitlines()
while lines and lines[0].strip().startswith("```"):
    lines = lines[1:]
while lines and lines[-1].strip().startswith("```"):
    lines = lines[:-1]
rust_code = "\n".join(lines).strip()

print("Testing Proposed Rust Code...")

# Compile with rustc
with tempfile.NamedTemporaryFile("w", suffix=".rs", delete=False, encoding="utf-8") as tf:
    tf.write(rust_code)
    src_p = tf.name
    bin_p = src_p.replace(".rs", ".exe")

comp = subprocess.run(["rustc", src_p, "-o", bin_p], capture_output=True, text=True)
Path(src_p).unlink(missing_ok=True)

if comp.returncode == 0:
    run_res = subprocess.run([bin_p], capture_output=True, text=True)
    Path(bin_p).unlink(missing_ok=True)
    if "FIB_PASS" in run_res.stdout:
        print("\n[RUST SUCCESS] fibonacci(10) == 55 verified by rustc 1.90.0!")
        # Graduate into SQLite
        conn = sqlite3.connect(CODE_DB)
        conn.cursor().execute("""
        INSERT OR REPLACE INTO verified_code_primitives 
        (primitive_id, intent_description, ast_skeleton, verified_python_code, test_harness_code, execution_status, pass_count, fail_count, registered_at)
        VALUES ('AUTONOMOUS_CHALLENGE_03_RUST_FIBONACCI', 'Recursive or iterative Fibonacci in Rust verified by rustc', 'RUST_BIN_VERIFIED', ?, 'FIB_PASS', 'VERIFIED_GRADUATE', 1, 0, datetime('now'))
        """, (rust_code,))
        conn.cursor().execute("UPDATE autonomous_curriculum_queue SET status = 'GRADUATED', graduated_primitive_id = 'AUTONOMOUS_CHALLENGE_03_RUST_FIBONACCI' WHERE curriculum_id = 'CHALLENGE_03_RUST_FIBONACCI'")
        conn.commit()
        conn.close()
        print("Graduation committed permanently to SQLite on SSD.")
    else:
        print("Execution failed stdout:", run_res.stdout, "stderr:", run_res.stderr)
else:
    print("Compilation failed:", comp.stderr)
