# Rust control, Swarm scheduling, and Python array bridges

## Live Mind-to-Swarm coding proof (2026-09-30)

`mind_planned_swarm` completed a fresh local run at
`runs/mind-swarm-autonomous-1790732264705939900/`. Qwen3 8B produced the
four-task plan; the frozen Qwen3 1.7B Python and Rust specialists each made
one CPU generation with the shared `swarm-default` adapter plus their domain
adapter. Rust recorded the plan, task packets, output hashes, and receipt.
Ruff lint/format, bounded AST/source grammars, six fixed arithmetic cases per
language, and Rust metadata-only compilation passed. Generated code was not
executed. The receipt hash sidecar was verified.

The corresponding fault-injection template run at
`../hive_template_runs/20260930T013153078064Z/run_receipt.json` caught a
parent-artifact mutation before downstream dispatch; repair generations were
zero. This proves a narrow local chain and a specific fault response. It does
not prove arbitrary code generation, interactive human wait/resume, durable
memory across restarts, LoRA benefit, or an AIOS rebuild. The broader Python
and Rust regression suites passed after the latest changes (37 Python tests;
all Rust tests).

The first bottom-layer horizontal Swarm proof is `swarm_horizontal`. Rust
prepares six bounded deterministic jobs with entropy-bound encrypted task snapshots and parent checksums. A/B/C
run concurrently, D/E depend on their outputs, and F composes the final
artifact. Every task's packet, objective, output text, timing, hashes, and
failure status is retained in `task_transcript.jsonl`; the files and receipt
remain in the same run directory. The normal run passed in
`runs/swarm-horizontal-1790708860604898900/`. The separate fault run changed
A after its local check; Rust held D before dispatch, leaving
`HOLD` in `runs/swarm-horizontal-1790708863717382700/`. This proves a Rust-only
horizontal slice. It does not involve the Python bridge or Viv's model yet.

`gpu_array_bridge` is the CPU/GPU vertical transfer proof. Rust sends a matrix
task through Python to NumPy host arrays and CuPy GPU arrays, then independently
checks all returned cells. Its normal and injected-fault receipts are under
`hive_numpy_bridge/artifacts/gpu_placement_20260929_final1/`.

## Vague-goal live probe

`mind_planned_file` gives Qwen3 8B the user goal “Create a file. Have it do
something.” and a bounded Rust capability manifest. Viv chooses the filename,
behavior, task IDs, and dependency graph. Rust validates and executes one stamp
per task, checks parent file hashes before dispatch, runs the resulting file,
and keeps the raw Mind plan, task transcript, final Mind text, artifact, and
receipt. The default profile passed in
`runs/mind-vague-1790709121822693800/`: three tasks created `example.py` and
printed “Hello, world!” The second profile removed the direct print stamp;
`runs/mind-vague-1790709250463746800/` passed with a four-task function path.
Both final messages were voiced and their WAVs and transcripts are pinned in
`HIVE_LOCK_MANIFEST.json`. Set `HIVE_PROBE_PROFILE=function_only` before running
to repeat the second profile. The capability menu strongly shapes the chosen
behavior, and these two local runs do not establish general coding quality.

## Earlier integration proof

Run `./run_proof.ps1 -MindMode live` from this directory. The live mode calls
local `qwen3:8b-local` as Viv; fixture mode uses the same Rust task and security
path with fixed Mind slot values. `-InjectParentFault` changes task 2's artifact
after its local check and expects Rust to hold task 3 before dispatch.
Run `cargo run --offline --bin parallel_proof` for the separate A/B/C → D/E → F
file proof; its receipt records the ready cohorts and overlapping first cohort.

Rust owns the task graph, in-memory master key, encrypted task snapshots,
directional peer grants, tool allowlist, artifact writes, and acceptance receipt.
Python transports Mind requests and calls the hash-checked template stamper or
NumPy array backend. The three Swarm tasks each stamp one approved template;
they make no model generations. The user-selected greeting is
`Hello from the Hive!`.

The run begins with a deterministic template-registry discovery task. Viv then
returns a plan constrained to this proof's four known jobs; Rust checks every
agent, capability, dependency, and cycle before dispatch. `TaskGraph` admits
independent ready tasks together and has
a parallel dispatcher. The greeting example is sequential because its later
stamps depend on earlier artifact hashes and the recorded human reply. The
graph code also supports adding tasks after discovery and waiting for a human.

Receipts and artifacts are written under `runs/<id>/`. No key bytes or plaintext
task snapshots are written into the receipt. The tool allowlist is confined to
this proof's run artifact and validation calls; unrelated shell use is denied.

This is a local integration proof. The greeting executor accepts this narrow
plan and three template capabilities; it does not yet execute an arbitrary
Viv-generated database rebuild plan. The key index is in memory for one run,
the human reply is the recorded fixture, and the Python worker is not an OS
sandbox. Durable Mind memory, a live approval inbox, agent process isolation,
and the full AIOS self-rebuild loop are separate implementation gates.
