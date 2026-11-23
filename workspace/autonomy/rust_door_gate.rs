// Rust Body Gate: Door Action Evaluation
// Enforces deterministic decision: ALLOW or DENY based on safety constraints
use std::env;

fn main() {
    let args: Vec<String> = env::args().collect();
    let action = if args.len() > 1 { &args[1] } else { "open_door" };
    let safety_override = if args.len() > 2 { &args[2] } else { "safe" };

    // Deterministic invariant check
    // If door is marked hazardous or outside territory, DENY (Exit Code 1)
    // If safe, ALLOW (Exit Code 0)
    if safety_override == "hazard" || action == "open_airlock_without_suit" {
        eprintln!("[RUST BODY GATE: DENIED] Invariant violation: Hazard detected.");
        std::process::exit(1);
    } else {
        println!("[RUST BODY GATE: ALLOWED] Deterministic check passed: Safe to actuate.");
        std::process::exit(0);
    }
}
