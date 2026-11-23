# Stage 1 → Stage 2 admission checklist (architecture lock v1.1)

Purpose: decide whether LocalCoder/Viv is ready to freeze and run the first
80-task synthetic correctness comparison. This is an admission gate, not a
result from the visible development suite. Passing it does not establish
transfer to AIOS history; that requires a later, separate frozen evaluation.

## Stage 1: prepare clean tasks and inputs

- [ ] The target source root is the LocalCoder Viv/AIOS build tree.
- [ ] For every task, the system records the exact task scope and hashes the
      source snapshot before preparation.
- [ ] Task-relevant files pass the project's configured indentation/format and
      lint checks with zero findings, compile where applicable, and contain no
      known dead code or unused imports in the scoped files.
- [ ] The Python environment declares and pins NumPy as the numerical backend.
      Python uses arrays by default for homogeneous numerical learning, memory,
      embedding, and indexing data; lists remain for heterogeneous records or
      serialization boundaries. The task suite covers array/list choice, shape,
      indexing/slicing, broadcasting, vectorization, reshaping, dtype and
      `astype()`, views/copies, aggregation and axes, elementwise/matrix
      multiplication, and linear algebra.
- [ ] The GPU environment declares and pins CuPy separately. NumPy arrays stay
      in CPU/system RAM; CuPy arrays stay in GPU/VRAM. Python makes host/device
      transfers explicit and records placement, transfer timing, and numeric
      agreement. Rust admits the GPU work and independently checks returned
      values. This numerical path does not imply that Viv's pretrained model
      uses CuPy for token inference.
- [ ] NumPy random work uses explicit `Generator` instances and fresh OS
      entropy from `SeedSequence` per run. Receipts preserve the seed,
      BitGenerator, NumPy version, and RNG state. Sampling, shuffling,
      synthetic-data generation, experiments, and algorithm initialization are
      represented in competency coverage.
- [ ] Rust owns authority, policy, task state, resource gates, and system
      operations on the CPU/Swarm side. Viv's model runs on the GPU/Mind side.
      Python is only the bidirectional switchboard to NumPy, CuPy, and Rust;
      it cannot grant capabilities or make policy decisions. The architecture
      leaves the Rust↔Python IPC/transport mechanism open until candidate
      implementations are measured; the Rust control core, Python switchboard,
      NumPy/CuPy division of labor itself is locked.
- [ ] Each task snapshot is encrypted and authenticated with task/agent-scoped
      access. OS CSPRNG entropy creates task salts/keys/nonces; NumPy RNG is
      prohibited for cryptographic material. The task checksum binds canonical
      task metadata, parent checksum, entropy salt, and ciphertext/AEAD nonce.
      Mind alone owns master-key custody and approves/signs index changes;
      Rust verifies signatures and scope. Swarm prompts, outputs, and receipts
      contain no master or per-task key bytes.
- [ ] Negative crypto-boundary checks show that a worker cannot read another
      task snapshot, communicate directly with a peer, mint grants, or update
      the Mind index; the same worker can read/write only its own authorized
      task record. Explicit inter-agent communication requires a Mind-approved,
      scoped, expiring channel grant. Preserve tamper, wrong-key, replay, and
      unauthorized-index-update receipts.
- [ ] The scored Stage 1 artifact is the exact prepared input packet at the
      dispatch boundary, after system preparation and before the agent sees it.
      Preserve its original, prepared hash, and diff. Do not clean or format the
      worker's raw generation for Stage 1; correctness of the merged result is
      Stage 2.
- [ ] Any cleanup is made in a staged task view; original files remain
      recoverable. The system retains the source hash, prepared hash, and diff.
      Semantic code is never silently deleted as “cleanup.”
- [ ] Before dispatch, each packet contains the objective, complete required
      inputs, evidence/source IDs, task dependencies, allowed capability,
      output contract, and resource limits. Missing essentials block dispatch
      and go to the user before a Swarm task starts.
- [ ] No model task is dispatched before all dependency outputs and prepared
      inputs are ready. The Mind waits for required agent and user replies
      before resuming dependent work.
- [ ] Each model agent receives one prepared task and one generation. It is not
      asked to lint, clean, test, review, or repair its output. Agents send
      messages to Viv; Viv alone mediates questions and answers with the Queen.
      The Mind waits for required
      replies before continuing the parent task. A model clarification after
      dispatch becomes a new prepared task with a new task ID and the user's
      reply included.
- [ ] Dependent tasks use the prior task's returned artifact as input only
      after the system prepares and hashes that next task's view. Independent
      tasks may run concurrently within measured resource limits.
- [ ] A composed task chain records each parent artifact hash and includes a
      controlled subtle-parent-fault case: the defect passes its local check,
      then the dependent composition catches it and records HOLD without a
      second generation. Passing isolated task checks alone is insufficient.
- [ ] The quality rubric, scoring method, and pass threshold are frozen on
      visible or separate development work before opening the correctness set.

## Stage 2 readiness: freeze the correctness comparison

- [ ] Every Stage 1 item passes on the declared LocalCoder implementation and
      task scope. Any exception is recorded and blocks admission.
- [ ] The one-turn task path, nested dependencies, waiting/resume behavior, and
      user-to-agent message routing are implemented, not only described.
- [ ] At least one Rust source file completes a forward and feedback/update
      round trip through Python to NumPy and back to Rust. The macro system path
      and an explicitly scoped NumPy numerical-component path are demonstrated;
      when that component uses forward/error/gradient updates, its math is
      explicitly specified and checked. This does not mean NumPy trains Viv or
      performs the pretrained LLM's token inference.
- [ ] Deterministic post-task checks run outside the worker. A failure is
      surfaced and recorded; it never triggers a second model generation for
      that same task.
- [ ] The 80 held-out tasks, expected outcomes, correctness rubric, and scoring
      code are frozen and hashed before any candidate sees them. Keep 20 tasks
      each for Python, Rust, AIOS, and mixed work. This first set is newly
      authored synthetic work. Freeze a separate AIOS-history set only when
      planning the later transfer evaluation; do not tune on either set.
- [ ] A non-held-out pilot may inform the plausible paired-discordance range
      and planning table, but its estimate is treated as noisy and does not set
      sample size. Preregister n = 80 and the exact decision procedure with an
      explicit inconclusive outcome; pilot tasks are excluded from both frozen
      evaluations.
- [ ] Freeze prompts, model/checkpoint and quantization hashes, runtime,
      sampling settings, tool capabilities, resource limits, and the analysis
      plan. Keep the role-prompt arm as the declared primary baseline.
- [ ] The corrected power note's exact two-sided McNemar method, assumptions,
      and decision rule are accepted or revised before freezing. The preregistered
      procedure names any confidence interval separately; it is not presumed
      equivalent to the exact test. Current illustrative scenarios estimate
      only 24–44% power at n=80 for a true 10-point gain.
- [ ] Full route, source, task, output, tool, and scoring receipts can be
      inspected after each run without exposing unredacted secrets.

## Current state

This gate has not passed. LocalCoder now has a project Python quality
configuration, pinned Ruff/Black/Vulture tools, and a staged one-file
preparation proof that retains hashes and a diff. `hive_control/` has a Cargo
manifest; `cargo fmt`, Clippy with warnings denied, and seven Rust unit tests
pass. The isolated `hive_numpy_bridge/` proof has pinned NumPy and CuPy
environments and observed CPU/GPU transfer receipts, including a deliberate
Rust `HOLD` on a changed result. These slices are not yet bound to a complete
task packet or the full Mind/Swarm runtime. The existing development harness
still includes worker repair and feedback calls, so it does not meet the
one-generation task contract. Its cases are visible development probes, not
held-out evaluation tasks. The next implementation work is to bind prepared
files and GPU resource admission into Rust dispatch, then refactor the task
path to the one-turn, nested-agent design before freezing any benchmark set.
