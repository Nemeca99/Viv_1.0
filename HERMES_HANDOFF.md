# Viv development handoff — 2026-11-13

Current setup correction: Hermes opens the whole `L:\LocalCoder` project with local terminal/file tools. The agent and automated work are stopped. This handoff supplies historical context only, not permission to run its experiments. Await the Architect's explicit assignment.

The Architect wants Hermes through OpenRouter to take over local coding, debugging, file editing, command execution, and ongoing Viv development. Read L:\LocalCoder\AGENTS.md and applicable nested instructions before changing project files. Active integration root: L:\LocalCoder\workspace. Python environment: L:\.venv\Scripts\python.exe.

Hermes is installed natively on Windows. Ori holds the authenticated OpenRouter credential; launch through Ori to inject it. Model: nvidia/nemotron-3-ultra-550b-a55b:free. Start-Hermes.cmd opens the visible CLI at L:\LocalCoder when the Architect launches it. Hermes config is C:\Users\nemec\AppData\Local\hermes\config.yaml. Terminal backend is local, with cwd L:/LocalCoder. INN at workspace\INN is a Windows junction targeting L:\LocalCoder\INN. No project was copied to C:.

## Work state

Read BUILD_LOG.md for completed evidence. Last completed frozen evaluation: epoch10038, Python 46/50 final, Rust 37/50 final. This is a plateau; it is not proof of an architectural ceiling.

Epoch10039 transfer proposal run recorded six ALLOW Rust functions and two DENY functions. Epoch10040 training completed on 65 rows with loss 0.3155. Candidate adapter hash: 0b354934b58a5e6e460d6cc247e663ed8d3af827cef50ad67d6d8330ee4022800. Receipts are in workspace\autonomy\learning\neural_runs: candidate_rust_transfer_learning_10039.json, candidate_rust_transfer_training_10040.json, candidate_rust_transfer_training_run_10040.json. Verify these artifacts directly before relying on them.

Epoch10040 full evaluation was interrupted: Docker went unavailable during early Rust tasks, was restarted, then the Architect paused the goal and the evaluation was stopped. No complete epoch10040 score was established. Check serving state before future work; the interrupted evaluation's final adapter restoration has not been independently verified. Do not promote a candidate or modify the live Viv topology/memory as part of this unfinished experiment.

## Next authorized experimental direction

Establish a clean epoch10040 baseline, then investigate helper resolution with the SAME candidate. Do not launch repeated training runs merely because prior ones plateaued. candidate_coding_runtime_helpers_v1.py already retrieves and resolves Python helpers and standard-library imports. Its Rust branch delegates to the self-contained runtime and does not compose Rust helpers.

Inspect the verified function store for actual language/type-compatible helpers for each failing task. Python helpers do not automatically count as callable Rust helpers. The previous agent incorrectly described Python collapse_adjacent/count_nonempty_blocks/unique_first_occurrences as admitted Rust helpers in commentary; inspect actual language columns.

Scoped probe: the 13 prior Rust misses plus relevant Python cases (run-length encoding, matrix trace, median). Preserve raw proposals, unresolved references, selected helper versions/hashes, composed code and deterministic gate receipts. Distinguish exact-reference resolution after generation from retrieval-aware prompting. Record ALREADY_PASSED, RESOLVED_BY_HELPER, STILL_FAILED_WITH_HELPER_AVAILABLE, or STILL_FAILED_NO_HELPER_AVAILABLE; add mechanism/error details. A failure with an available helper alone does not prove a synthesis ceiling. Do not force an unassisted improvement into a helper-resolution label.

The Architect prioritizes Python and English, efficiency, repeatable evidence, and actual capability. No scripted answers to manufacture learning. Keep logs and negative evidence. Show terminal work or provide a reliable launcher. The previous learning goal remains paused pending the Architect's direction in the new agent.
