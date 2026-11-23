//! Bounded Rust -> Python -> NumPy CPU -> CuPy GPU -> Rust verification.
use hive_control::sha;
use serde_json::{json, Value};
use std::env;
use std::fs;
use std::io::{BufRead, BufReader, Write};
use std::path::Path;
use std::process::{Command, Stdio};

fn request(inject_fault: bool) -> Value {
    json!({
        "n": 4,
        "matrix_a": [[1.0, 2.0, 3.0, 4.0], [5.0, 6.0, 7.0, 8.0],
                     [9.0, 10.0, 11.0, 12.0], [13.0, 14.0, 15.0, 16.0]],
        "matrix_b": [[2.0, 0.0, 1.0, 3.0], [1.0, 2.0, 0.0, 4.0],
                     [3.0, 1.0, 2.0, 0.0], [0.0, 4.0, 3.0, 1.0]],
        "bias": [0.5, 1.5, -0.5, 2.0],
        "inject_fault": inject_fault
    })
}

fn expected(input: &Value, row: usize, column: usize) -> Result<f64, String> {
    let mut total = input["bias"][column].as_f64().ok_or("invalid Rust bias")?;
    for inner in 0..4 {
        let a = input["matrix_a"][row][inner]
            .as_f64()
            .ok_or("invalid Rust matrix A")?;
        let b = input["matrix_b"][inner][column]
            .as_f64()
            .ok_or("invalid Rust matrix B")?;
        total += a * b;
    }
    Ok(total)
}

fn run(
    python: &str,
    script: &str,
    receipt_path: &Path,
    inject_fault: bool,
) -> Result<bool, String> {
    let input = request(inject_fault);
    let mut child = Command::new(python)
        .arg(script)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()
        .map_err(|error| format!("start Python switchboard: {error}"))?;
    let mut stdin = child.stdin.take().ok_or("missing Python stdin")?;
    writeln!(stdin, "{input}").map_err(|error| error.to_string())?;
    drop(stdin);
    let mut line = String::new();
    BufReader::new(child.stdout.take().ok_or("missing Python stdout")?)
        .read_line(&mut line)
        .map_err(|error| error.to_string())?;
    let status = child.wait().map_err(|error| error.to_string())?;
    let response: Value = serde_json::from_str(&line).map_err(|error| error.to_string())?;
    if !status.success() || response["status"] != "RESULT" {
        return Err(format!("Python bridge failed: {response}"));
    }
    let data = &response["data"];
    let mut violations = Vec::new();
    if data["n"] != 4
        || data["dtype"] != "float32"
        || data["device_id"] != 0
        || data["host_type"] != "numpy.ndarray"
        || data["device_type"] != "cupy.ndarray"
    {
        violations.push("shape, dtype, or host/device placement mismatch".to_string());
    }
    let error = data["max_cpu_gpu_error"]
        .as_f64()
        .ok_or("missing CPU/GPU error")?;
    if !error.is_finite() || error > 1e-5 {
        violations.push("CPU/GPU disagreement".to_string());
    }
    for row in 0..4 {
        for column in 0..4 {
            let actual = data["output"][row][column]
                .as_f64()
                .ok_or("missing output cell")?;
            if !actual.is_finite() || (actual - expected(&input, row, column)?).abs() > 1e-5 {
                violations.push(format!("Rust reference mismatch at ({row}, {column})"));
            }
        }
    }
    let accepted = violations.is_empty();
    let receipt = json!({
        "proof": "rust-python-numpy-cupy-placement-v1",
        "status": if accepted { "PASS" } else { "HOLD" },
        "rust_accepted": accepted,
        "fault_injected": inject_fault,
        "input_sha256": sha(input.to_string().as_bytes()),
        "output_sha256": sha(data["output"].to_string().as_bytes()),
        "violations": violations,
        "gpu": {"name": data["device_name"], "id": data["device_id"]},
        "host_type": data["host_type"],
        "device_type": data["device_type"],
        "host_dtype": data["dtype"],
        "numpy_version": data["numpy_version"],
        "cupy_version": data["cupy_version"],
        "max_cpu_gpu_error": error,
        "timing_ms": {
            "upload": data["upload_ms"], "compute": data["compute_ms"],
            "download": data["download_ms"]
        }
    });
    if let Some(parent) = receipt_path.parent() {
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    fs::write(
        receipt_path,
        serde_json::to_vec_pretty(&receipt).map_err(|error| error.to_string())?,
    )
    .map_err(|error| error.to_string())?;
    Ok(accepted)
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 4 || args.len() > 5 {
        eprintln!(
            "usage: gpu_array_bridge <python.exe> <switchboard.py> <receipt.json> [--inject-fault]"
        );
        std::process::exit(2);
    }
    let fault = args.get(4).is_some_and(|value| value == "--inject-fault");
    match run(&args[1], &args[2], Path::new(&args[3]), fault) {
        Ok(true) => println!("GPU_BRIDGE_PASS {}", args[3]),
        Ok(false) => {
            eprintln!("GPU_BRIDGE_HOLD {}", args[3]);
            std::process::exit(1);
        }
        Err(error) => {
            eprintln!("GPU_BRIDGE_ERROR {error}");
            std::process::exit(2);
        }
    }
}
