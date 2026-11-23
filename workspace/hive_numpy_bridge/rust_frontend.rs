use std::env;
use std::fs;
use std::io::{BufRead, BufReader, Write};
use std::path::Path;
use std::process::{Command, Stdio};
use std::time::{SystemTime, UNIX_EPOCH};

const SAMPLES: usize = 96;
const FIRST_STEPS: usize = 120;
const SECOND_STEPS: usize = 240;
const LEARNING_RATE: f64 = 0.04;

struct Forward {
    seed: String,
    rows: usize,
    columns: usize,
    dtype: String,
    initial_loss: f64,
    first_loss: f64,
    first_gradient_norm: f64,
    numpy_version: String,
    bit_generator: String,
    rng_state_b64: String,
}

struct Backprop {
    seed: String,
    first_loss: f64,
    final_loss: f64,
    final_gradient_norm: f64,
    x_rows: usize,
    x_columns: usize,
    y_rows: usize,
    y_columns: usize,
    dtype: String,
}

fn next_line(reader: &mut BufReader<std::process::ChildStdout>) -> Result<String, String> {
    let mut line = String::new();
    let count = reader
        .read_line(&mut line)
        .map_err(|error| format!("read from Python switchboard: {error}"))?;
    if count == 0 {
        return Err("Python switchboard closed stdout before completing protocol".into());
    }
    Ok(line.trim_end_matches(['\r', '\n']).to_string())
}

fn parse_forward(line: &str) -> Result<Forward, String> {
    let fields: Vec<&str> = line.split('\t').collect();
    if fields.len() != 11 || fields[0] != "FORWARD" {
        return Err(format!("invalid FORWARD response: {line}"));
    }
    Ok(Forward {
        seed: fields[1].to_string(),
        rows: fields[2].parse().map_err(|_| "bad row count")?,
        columns: fields[3].parse().map_err(|_| "bad column count")?,
        dtype: fields[4].to_string(),
        initial_loss: fields[5].parse().map_err(|_| "bad initial loss")?,
        first_loss: fields[6].parse().map_err(|_| "bad forward loss")?,
        first_gradient_norm: fields[7].parse().map_err(|_| "bad forward gradient")?,
        numpy_version: fields[8].to_string(),
        bit_generator: fields[9].to_string(),
        rng_state_b64: fields[10].to_string(),
    })
}

fn parse_backprop(line: &str) -> Result<Backprop, String> {
    let fields: Vec<&str> = line.split('\t').collect();
    if fields.len() != 10 || fields[0] != "BACKPROP" {
        return Err(format!("invalid BACKPROP response: {line}"));
    }
    Ok(Backprop {
        seed: fields[1].to_string(),
        first_loss: fields[2].parse().map_err(|_| "bad staged loss")?,
        final_loss: fields[3].parse().map_err(|_| "bad final loss")?,
        final_gradient_norm: fields[4].parse().map_err(|_| "bad final gradient")?,
        x_rows: fields[5].parse().map_err(|_| "bad X row count")?,
        x_columns: fields[6].parse().map_err(|_| "bad X column count")?,
        y_rows: fields[7].parse().map_err(|_| "bad y row count")?,
        y_columns: fields[8].parse().map_err(|_| "bad y column count")?,
        dtype: fields[9].to_string(),
    })
}

fn finite_nonnegative(value: f64) -> bool {
    value.is_finite() && value >= 0.0
}

fn json_escape(value: &str) -> String {
    value
        .replace('\\', "\\\\")
        .replace('"', "\\\"")
        .replace('\n', "\\n")
        .replace('\r', "\\r")
        .replace('\t', "\\t")
}

fn write_receipt(path: &Path, forward: &Forward, final_result: &Backprop) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|error| format!("create receipt directory: {error}"))?;
    }
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| format!("system clock before Unix epoch: {error}"))?
        .as_millis();
    let body = format!(
        concat!(
            "{{\n",
            "  \"proof\": \"rust-python-numpy-roundtrip-v1\",\n",
            "  \"accepted_by_rust\": true,\n",
            "  \"timestamp_unix_ms\": {timestamp},\n",
            "  \"numpy_version\": \"{numpy_version}\",\n",
            "  \"bit_generator\": \"{bit_generator}\",\n",
            "  \"seed_source\": \"numpy.random.SeedSequence.entropy\",\n",
            "  \"seed\": \"{seed}\",\n",
            "  \"rng_state_base64\": \"{rng_state}\",\n",
            "  \"samples\": {samples},\n",
            "  \"features\": {features},\n",
            "  \"dtype\": \"{dtype}\",\n",
            "  \"initial_loss\": {initial_loss:.17e},\n",
            "  \"after_forward_loss\": {forward_loss:.17e},\n",
            "  \"after_feedback_backprop_loss\": {final_loss:.17e},\n",
            "  \"forward_gradient_norm\": {forward_gradient:.17e},\n",
            "  \"final_gradient_norm\": {final_gradient:.17e},\n",
            "  \"rust_feedback_learning_rate\": {learning_rate:.17e},\n",
            "  \"rust_feedback_second_steps\": {second_steps},\n",
            "  \"return_shapes\": {{\"X\": [{x_rows}, {x_columns}], \"y\": [{y_rows}, {y_columns}]}}\n",
            "}}\n"
        ),
        timestamp = timestamp,
        numpy_version = json_escape(&forward.numpy_version),
        bit_generator = json_escape(&forward.bit_generator),
        seed = json_escape(&forward.seed),
        rng_state = forward.rng_state_b64,
        samples = final_result.x_rows,
        features = final_result.x_columns,
        dtype = json_escape(&final_result.dtype),
        initial_loss = forward.initial_loss,
        forward_loss = forward.first_loss,
        final_loss = final_result.final_loss,
        forward_gradient = forward.first_gradient_norm,
        final_gradient = final_result.final_gradient_norm,
        learning_rate = LEARNING_RATE,
        second_steps = SECOND_STEPS,
        x_rows = final_result.x_rows,
        x_columns = final_result.x_columns,
        y_rows = final_result.y_rows,
        y_columns = final_result.y_columns,
    );
    fs::write(path, body).map_err(|error| format!("write receipt: {error}"))
}

fn run() -> Result<(), String> {
    let args: Vec<String> = env::args().collect();
    if args.len() != 4 {
        return Err(format!(
            "usage: {} <python.exe> <python_switchboard.py> <receipt.json>",
            args.first().map(String::as_str).unwrap_or("rust_frontend")
        ));
    }
    let python = &args[1];
    let switchboard = &args[2];
    let receipt_path = Path::new(&args[3]);

    let mut child = Command::new(python)
        .arg(switchboard)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()
        .map_err(|error| format!("launch Python switchboard: {error}"))?;
    let mut input = child.stdin.take().ok_or("missing Python stdin")?;
    let mut output = BufReader::new(child.stdout.take().ok_or("missing Python stdout")?);

    writeln!(input, "START\t{SAMPLES}\t{FIRST_STEPS}\t{LEARNING_RATE}")
        .map_err(|error| format!("send START: {error}"))?;
    let forward = parse_forward(&next_line(&mut output)?)?;
    if forward.rows != SAMPLES || forward.columns != 2 || forward.dtype != "float64" {
        writeln!(input, "HOLD").map_err(|error| format!("send HOLD: {error}"))?;
        return Err("Rust rejected unexpected NumPy shape or dtype".into());
    }
    if !finite_nonnegative(forward.initial_loss)
        || !finite_nonnegative(forward.first_loss)
        || !forward.first_gradient_norm.is_finite()
        || forward.first_gradient_norm < 0.0
        || forward.first_loss >= forward.initial_loss
    {
        writeln!(input, "HOLD").map_err(|error| format!("send HOLD: {error}"))?;
        return Err("Rust rejected invalid or non-improving forward result".into());
    }

    // Rust owns this feedback decision. Python only transports it to NumPy.
    let feedback_rate = LEARNING_RATE;
    writeln!(input, "FEEDBACK\t{SECOND_STEPS}\t{feedback_rate}")
        .map_err(|error| format!("send FEEDBACK: {error}"))?;
    let backprop = parse_backprop(&next_line(&mut output)?)?;
    let valid_return = backprop.seed == forward.seed
        && backprop.x_rows == SAMPLES
        && backprop.x_columns == 2
        && backprop.y_rows == SAMPLES
        && backprop.y_columns == 1
        && backprop.dtype == "float64"
        && (backprop.first_loss - forward.first_loss).abs() <= 1e-12
        && finite_nonnegative(backprop.final_loss)
        && backprop.final_loss < backprop.first_loss
        && backprop.final_gradient_norm.is_finite()
        && backprop.final_gradient_norm >= 0.0;

    if !valid_return {
        writeln!(input, "HOLD").map_err(|error| format!("send HOLD: {error}"))?;
        let _ = next_line(&mut output);
        return Err("Rust rejected NumPy feedback/update result".into());
    }

    writeln!(input, "ACCEPT").map_err(|error| format!("send ACCEPT: {error}"))?;
    let closed = next_line(&mut output)?;
    if closed != "CLOSED\tACCEPT" {
        return Err(format!("unexpected switchboard close: {closed}"));
    }
    drop(input);
    drop(output);
    let status = child
        .wait()
        .map_err(|error| format!("wait for switchboard: {error}"))?;
    if !status.success() {
        return Err(format!("Python switchboard exited with {status}"));
    }

    write_receipt(receipt_path, &forward, &backprop)?;
    println!(
        "RUST_ACCEPT seed={} samples={}x{} dtype={} loss={:.8e}->{:.8e}->{:.8e} grad={:.8e}->{:.8e}",
        forward.seed,
        SAMPLES,
        forward.columns,
        backprop.dtype,
        forward.initial_loss,
        forward.first_loss,
        backprop.final_loss,
        forward.first_gradient_norm,
        backprop.final_gradient_norm
    );
    println!("RUST_RECEIPT {}", receipt_path.display());
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("RUST_HOLD {error}");
        std::process::exit(1);
    }
}
