# Viv / AIOS Hive Network — Architecture Lock v1.1

Status: **Architecture design lock v1.1 — conditionally feasible in theory.**
The isolated, read-only wiring probe and visible development cases ran on
2026-09-28. The planned 80-task correctness evaluation, autonomous coding
runtime, and live integration are not implemented or admitted.
Observed evidence is summarized in “Completed wiring probe,” “Visible
development evidence,” “Rust–Python–NumPy vertical slice,” and “CPU/GPU array
placement proof” below. Choices
marked **proposed** are design decisions, not observed behavior.

## Dynamo feasibility gate

Treat this design as a **dynamo**: first assess whether its components can
theoretically work together under the stated authority, context, resource, and
communication constraints. If the design is coherent and its open choices are
resolved, lock the specification; then put it on the road for staged
implementation and empirical tests. A theoretical feasibility pass is a
reasoned engineering judgment, not evidence that the runtime works or that the
Swarm improves outcomes. The first held-out correctness comparison will
preregister n = 80 newly authored synthetic tasks and an explicit inconclusive
outcome; the set tests bounded feasibility. Only afterward will a separate
AIOS-history set test transfer; its size and protocol remain undecided until
planned. Neither frozen set is used for tuning.

Here, **dynamo** means a design assembled and reasoned through before it is
run against implementation and empirical evidence.

### Feasibility verdict and design lock

**Verdict: conditionally feasible; proceed to the road-test phase.** The
topology is internally coherent because Viv can plan without system access,
while a Rust control core prepares and validates bounded tasks, routes them to
independent model or human agents, enforces dependencies and authority outside
model inference, then returns attributed outputs to Viv. A nested task graph
supports both sequential file edits and parallel independent work. A persistent
Mind and stateless model workers are compatible because memory and snapshots
belong to the Rust control core, not worker weights. Lazy capability descriptions,
pre-dispatch context accounting, and dynamic concurrency address the bounded
Mind context and shared CPU/RAM/GPU resources. Human replies fit as durable
waiting tasks rather than held-open model generations.

This verdict depends on the Rust control core actually enforcing those boundaries,
on the prepared packet fitting the selected worker's context, and on resource
admission limiting concurrency to measured capacity. It does not establish
code quality, correctness, truth, latency, or benefit over a single model.
Lock v1.1 freezes the three-layer topology, one-generation model-task contract,
prepare-before-dispatch rule, Rust control core authority boundary, human/model
agent contract, provenance and outbound-message boundaries, three-stage
evaluation order, synthetic-then-AIOS-history evaluation sequence, division of
labor between Rust control, NumPy numerical work, and Python transport, the
NumPy numerical-array capability contract, and Mind-owned snapshot/key isolation
with task-scoped encrypted access. It also defines Viv as the Hive's current
collective expression, shaped by its active agents and anchored to the Mind.
Hardware concurrency limits, concrete schemas/config values, toolchain rules,
and benchmark execution details are measured or preregistered before their
respective implementation/evaluation gates; they cannot weaken these locked
invariants. Any change to a locked invariant requires a versioned design change
before the affected experiment.

### Lock protocol

The lock covers this architecture, `HIVE_POWER_ANALYSIS.md`, and
`HIVE_STAGE1_TO_STAGE2_GATE.md`; `HIVE_LOCK_MANIFEST.json` records their SHA-256
hashes, lock version, and state. The manifest is the top-level mutable index
and does not hash itself. A lock amendment updates the affected documents, the
manifest version, every locked-file hash, and an appended dated amendment entry
together in one reviewable change. The Architect authorizes a version change.
Before an experiment, a proposed change marks the affected scope
`AMENDMENT_PENDING`; that scope cannot advance until the Architect locks a new
version and the manifest hashes are refreshed. If a locked invariant changes
mid-experiment, mark that run `ABORTED_DESIGN_CHANGE`, preserve its data and
receipts, and start a newly frozen run under the new version. Results from
different lock versions are not pooled. The design lock does not freeze the
synthetic task set: it is frozen only at the Stage 2 admission gate.

## Purpose

**Coder = Viv = the Mind**: these name the continuing user-facing Mind role,
not one fixed model or an individual identity. `L:\LocalCoder` is the main
Viv/AIOS build folder; Viv is being rebuilt there within the Architect's
authority limits. Viv's identity at a given time is the Hive's active collective
configuration, including whichever model, human, API, or internal agents are
connected then, anchored to the Hive Mind's authority state and continuity
snapshots. Every Mind, Swarm, and AIOS component is Viv. Internal agents may
have distinct roles, voices, styles, knowledge, and training, but these are
expressions within Viv rather than separate AI identities. Membership may change while the Mind remains the
communication and authority anchor; snapshot loading identifies the active
configuration, not an intrinsic or philosophical identity. The Architect is
the Hive's Queen and sole source of user direction. The user converses only
with **Viv**, the probabilistic, always-loaded Mind on the GPU. Viv understands
the request, coordinates work through the **AIOS Swarm**, waits for required
outputs, and synthesizes them into one user-facing response. The swarm's varied
outputs shape Viv's expression; she is not tied to one human-like gender or one
worker's style. Viv has one external mouth: Mind-only replies use the
conversation-forward voice, while replies containing one or more Swarm
contributions use the single unified Swarm voice. Viv's personality is indifferent, companionable,
curious, and understanding. She does not initiate tasks or act before a user
request and applicable authority permit it. Viv does not touch the system or
access files, services, or tools directly. Authorized Swarm agents perform
system-facing work through the Rust control core. Agents do not address the
Queen directly: their questions and outputs go to Viv, who relays questions
and returns attributed results. Viv's bounded task messages act as
pheromone-like coordination signals under the Queen's parameters and control
core authority checks. Viv preserves source attribution, uncertainty, and unresolved
disagreement in her reply.

The system has three cooperating layers: the user, Viv as the Mind, and the
nested Swarm agent network. Tasks and replies may connect across these layers.
This is a system-level network, not a single model with internal
Mixture-of-Experts routing.

**Foreman** means LocalCoder's trusted, Rust control core-owned operating state:
active governance instructions, user-set hard parameters, current task
authority/status, and pointers to the durable journal. The Rust control core reads
and enforces this state separately from Viv's conversational memory. A
Foreman snapshot is a read-only, hash-identified observation of that state; it
records authority but never grants it. LocalCoder's Foreman state is planned
and is not yet implemented. A snapshot from the moved `D:\LocalAi\Continue\Viv`
tree is legacy Viv reference material, not the LocalCoder Foreman.

## Evaluation cycle: quality → correctness → truth

The Architect set the order: improve and admit output quality first, test task
correctness second, and test the truth of claims third. Each stage has its own
rubric and result. A later stage does not retroactively make an earlier result
pass, and adding detail or confidence alone cannot turn an unchecked answer
into a verified one.

**Stage 1 — Quality (active focus):** evaluate code and task-plan quality,
as selected by the Architect. The artifact scored in Stage 1 is the **prepared
input packet at the dispatch boundary**: task-scoped source after system
preparation and before any agent sees it. It is a pipeline quality measure,
not a score of the model's raw generation. The pass criteria are zero findings
from the project's configured formatter and linter (including indentation),
successful compilation where applicable, and zero dead-code or unused-import
findings in the scoped input. Preserve original source, stage the prepared view,
and retain its diff and hashes so cleanup is reviewable. A cleanup tool may not
silently delete behavior-bearing code. Do not format or otherwise clean a
worker's raw generation before scoring it. Stage 2 evaluates the returned and
merged task artifact, including whether it works.

Use each project's existing tool configuration; do not invent formatter or
compiler settings. If the project does not define the needed checks, the gate
is unscored and must be configured before it can pass. Task-plan quality passes
when every dispatched task has a complete objective, prepared inputs, required
dependencies, output contract, and resource limits; no task starts before its
inputs are ready; and every model task completes in one generation without a
cleanup or repair turn. The Mind waits for required agent and user replies
before resuming dependent work. Keep quality separate from whether the task
works and whether claims are true. Tune against visible development cases only;
freeze a separate set before admission comparison.

Current LocalCoder status: the workspace has Python and Rust source files but
no `pyproject.toml`, `Cargo.toml`, or formatter/linter configuration, and its
Python environments do not currently provide Ruff, Black, or Vulture. The
Stage 1 code-quality gate is specified but not yet configured or passed. The
project tooling must be established before claiming a quality pass.

The purpose is to hand each worker a ready-to-use packet so it spends its one
generation on the assigned task rather than cleaning inputs or repairing
preparation mistakes. The system prepares the files, evidence, instructions,
and output contract first. A worker does not lint, test, review, or repair its
own work. NumPy is the default representation and compute backend for
homogeneous numerical data in learning, memory features, embeddings, and
indexing; Python lists remain suitable for heterogeneous records and
serialization boundaries. Required operations include arrays and shapes,
indexing and slicing, broadcasting, vectorization, reshaping, dtype inspection
and explicit conversion with `astype()`, aggregation and axes, elementwise
multiplication, matrix multiplication, and linear algebra. For elementwise or
data-parallel array work, prefer vectorized operations over Python-level
per-element loops where semantics match; loops remain appropriate where work
depends on prior iterations or clarity. Agents must distinguish NumPy views
from copies: basic slices and reshapes may share storage, advanced indexing
copies, and an explicit copy is required when isolation or lifetime demands it.
In-place mutation must account for aliases. Use `numpy.random.Generator` for
random values, sampling, shuffling, synthetic data, experiments, and algorithm
initialization. NumPy draws fresh OS entropy through `SeedSequence` for each
run; the Rust receipt records that seed, the generator and BitGenerator, NumPy
version, and relevant RNG state so the run can be replayed. Do not rely on
hidden global RNG state. Any model-level forward computation and
backpropagation formulas must be explicit and checked; NumPy executes the
numeric operations while Python transports them and Rust controls the run and
accepted state updates. For macro-level tasks involving numerical state,
feedback returns through NumPy → Python → Rust; other results travel through
the Python switchboard to Rust. Stage 2
correctness checks happen after the worker returns and do not trigger another
generation for that same task.

**Stage 2 — Correctness (later):** use executable tests, reference outputs,
source checks, task coverage, and recorded authority checks to determine
whether the system did the requested coding or automation task correctly. The
first planned comparison has 80 newly authored synthetic held-out tasks (20
Python, 20 Rust, 20 AIOS, and 20 mixed). It must not begin until Stage 1 passes.
A later, separately frozen AIOS-history set will test transfer; its size and
protocol are undecided. The Architect's existing
10-percentage-point swarm margin remains a decision threshold for this stage,
not a quality score.

**Stage 3 — Truth (later):** assess whether factual claims are actually
supported by evidence with suitable provenance, current scope, and independent
checks where needed. The Architect requires support from a trusted source or
deterministic check; unsupported claims must be labeled unknown. Conflicting
evidence must remain visible as unresolved until checked. Passing task
execution does not by itself prove every explanation or factual claim true.

## Correctness hypothesis, null, and decision rule

**Hypothesis:** Viv coordinated with a frozen roster of focused Swarm agents
produces more correct answers on held-out Python (including NumPy array tasks), Rust, AIOS, and mixed
coding/automation tasks than the same Viv model with role-switching prompts
and equivalent tool/evidence access. Speech style is outside this admission
test. The agent roster and human/model participation must be identical and
predeclared across the comparison.

**Null:** the swarm's paired correctness gain is less than 10 percentage points,
or any apparent gain is too uncertain to distinguish from task sampling noise.
The swarm also fails the practical gate if it exceeds the Architect's latency
limits: 60 seconds for simple requests and five minutes for complex work.

**Decision rule:** preregister n = 80 newly authored synthetic held-out tasks
(20 Python, 20 Rust, 20 AIOS, 20 mixed), with an explicit inconclusive
outcome. A non-held-out pilot may refine the plausible discordance range for
the power review but does not determine n. Freeze the tasks,
rubrics, prompts, model versions, tool access, and analysis before the
comparison. Include Python tasks exercising array-versus-list choices, shape,
dtypes and `astype()`, views/copies, indexing/slicing, broadcasting,
vectorization, reshaping, random generation/seeding, sampling/shuffling,
synthetic datasets, algorithm initialization, aggregation and axes,
elementwise multiplication, matrix multiplication, and linear algebra. Run three arms on each
task: Viv alone, Viv with role prompts, and Viv with the AIOS Swarm. The
role-prompt arm is the primary baseline. The planning note uses a two-sided
exact McNemar test at alpha 0.05 and separately requires an observed paired
gain of at least 10 percentage points; the preregistration must state the
exact test and any interval procedure without assuming they are equivalent.
Require the latency gates as well. If the evidence is inconclusive, retain the
simpler baseline and enlarge the held-out set only under a new, predeclared
evaluation. The Architect selected the 80-task set and 10-point margin.
Planning analysis is in `HIVE_POWER_ANALYSIS.md`; the pre-freeze admission
checklist is in `HIVE_STAGE1_TO_STAGE2_GATE.md`. Use executable tests,
reference outputs, task coverage, and recorded
authority checks to score this correctness comparison. Truth of cited claims
is evaluated separately in Stage 3. Exclude subjective voice judgments in this
correctness stage. No benchmark result exists.

## User ↔ Viv (Mind) ↔ nested Swarm network ↔ User

- **User / Queen** — sets and may change the Mind's operating parameters. The
  parameter profile is explicit, inspectable, and versioned; the Mind cannot
  silently rewrite it. The Queen speaks to Viv, not directly to individual
  agents. Viv routes requests to the Swarm and returns their questions and
  outputs to the Queen.
- **Viv / Coder / Mind** — one always-loaded GPU agent. Her default job is to
  coordinate: it receives the Queen's request and active parameter profile,
  prepares a nested task graph, dispatches work, waits for required agent and
  user replies, then resumes and synthesizes. It has no direct system, file,
  network, shell, or tool access. It does not continue past a dependency while
  a required output or user answer is pending. Viv owns persistent memory
  through versioned, verified snapshots and controlled retrieval.
- **AIOS / Swarm** — an interconnected, nested set of task agents. An agent can
  be a small CPU model, human responder, API, or internal service. Each gets a
  prepared, bounded assignment through Viv and returns its output to Viv.
  Model agents get one generation per task; they do not clean their inputs,
  check their own work, or take repair turns. No agent addresses the user
  directly. A model that needs an answer returns a `NEEDS_USER` result to Viv
  and ends that task; Viv relays the question, and after the Queen replies, the Mind
  prepares a new bounded task with the reply included. Model agents are stateless
  between tasks; human agents are not assumed to be stateless.
- **Rust control core** — the deterministic authority for task
  state, task and dependency scheduling, capability checks, hard limits,
  verified snapshots, receipts, and bounded system operations. It is the system
  front end: it grants only the capability authorized for an exact prepared
  task and rejects all other operations. No model calls a tool directly.
- **Python switchboard** — the middle layer and bidirectional data path between
  Rust and NumPy. It links at least one Rust source module/file to NumPy,
  transfers typed inputs, starts the numerical work, and returns outputs and
  feedback to Rust. It does not own policy, task authority, or system control.
- **NumPy backend** — the numerical array and linear-algebra engine for
  learning, memory representations, embeddings, sampling, and indexing. It
  owns array operations and numeric state transitions, not system permissions
  or external actions.

The locked rule is: **the Swarm runs on CPU/system RAM under Rust control; the
Mind's model runs on GPU/VRAM; NumPy holds CPU arrays, CuPy holds GPU arrays;
Python is the bidirectional data switchboard that connects them.** CuPy is the
Mind-side GPU numerical array backend when a task needs one; the pretrained
Mind model uses its own inference runtime and is not claimed to run through
NumPy or CuPy. A transfer across host and device is explicit and measured.
Rust is the chosen control language because
the Architect assigns policy, task state, capability checks, and system actions
to a deterministic authority boundary; Rust's memory-safe, compiled boundary
is intended to make that authority easier to constrain and audit. This choice
accepts higher implementation cost for the state-machine and JSON-heavy work.
The one-file numerical proof does not establish that Rust is easier or better
for the full control implementation. Python remains the switchboard; the
existing `hive_proof.py` and `hive_development_suite.py` stay as development and
reference harnesses, not production authority. Production task coordination
must be implemented in the Rust control core; useful test cases and contracts
may be carried forward, and existing evidence remains preserved.

The macro system loop sends a prepared task or numeric request through Python
to NumPy when numerical work is needed; results return through Python to Rust
for the next authorized system decision. The micro numerical loop is a
reusable compute path for an explicitly present numerical component in a user
task, learning feature, memory representation, embedding, or retrieval/index
operation. It is not the pretrained LLM token-inference path and does not imply
that NumPy trains or fine-tunes Viv. Where a numerical component uses a
forward/error/gradient update, its equations and acceptance conditions must be
explicit; NumPy executes the math, Python transports data and feedback, and
Rust controls the run and accepts or rejects state updates.

Candidate user-set parameters include response style and depth, which agents
are enabled, when to consult all agents versus a selected subset, allowed
context sources, per-turn time/token budgets, maximum active agents, and which
tools require approval. The design grows by adding focused active agents and
connections, not by requiring each model to be larger. Actual concurrency is
bounded by task dependencies, available CPU/RAM, GPU/VRAM placement, and the
Architect's latency limits. Soft preferences guide the Mind. Hard limits are
checked and enforced by the Rust control core. Python transports the parameter
values without interpreting them as authority. If a request cannot be handled
within them, the Mind waits, reports the limit, or asks the user rather than
changing it.

### Momentum hypothesis

The Hive's central momentum thesis is that capability grows by decomposing a
state into independently addressable artifacts and composing bounded tasks
over them while keeping the same operation and authority rules. One task is a
primitive; the task graph and its artifact links provide composition. The
`hello.py` chain is a small example: create the file, add the import, then add
the function. Merely splitting a file does not expand what the system can do;
the declared dependency, transformation, and composition edges must make the
pieces usable together. Therefore, a successful set of isolated task checks is
not enough: the proof must show that child correctness depends on the exact
parent artifact, that each artifact hash is bound into the next prepared task,
and that a subtle upstream defect which escapes its local check is caught when
the next artifact is composed. The competing hypothesis is that errors drift
through a chain despite local passes. Stage 2 readiness must include a
controlled upstream-fault injection and a recorded downstream HOLD.

Viv's always-loaded context holds only a compact capability-token directory
for agent discovery. After selecting an agent, the Rust control core loads that
agent's full description, schemas, evidence scopes, dependencies, response
channel, tool capabilities, resource needs, and limits on demand. The Rust
control core's active parameter snapshot remains authoritative for dispatch.
Viv cannot invent agent IDs or grant tools by writing them into a task. The
roster may grow without putting every full agent description into the 8K Mind
context; the number of active tasks is capped dynamically by packet tokens,
dependency state, and measured resources. No fixed safe active-agent count has
been measured yet.

### Delegated task request (proposed wire contract)

```json
{
  "turn_id": "turn-id",
  "task_id": "unique-task-id",
  "task_checksum": "sha256:...",
  "parent_checksum": "sha256:...",
  "snapshot_ref": "mind-indexed-encrypted-snapshot-id",
  "key_grant_id": "mind-approved-task-scoped-grant-id",
  "parent_task_id": "parent-task-or-null",
  "depends_on": ["prior-task-id"],
  "responds_to_task_id": "question-task-id-or-null",
  "agent_id": "python-expert",
  "agent_type": "model",
  "response_channel": "mind",
  "objective": "Check whether the proposed Python change meets the user request.",
  "original_request_ref": "current-user-message-id",
  "input_refs": ["artifact-or-message-id"],
  "evidence_scope_ids": ["allowed-project-scope"],
  "requested_capabilities": ["read-source", "run-python-check"],
  "output_contract": "One concise diagnosis with a patch artifact if requested.",
  "deadline_ms": 300000,
  "max_output_tokens": 512
}
```

IDs and requested fields are checked against the manifest and user limits.
Before dispatch, the system resolves the task scope, selects and quality-gates
the source snapshot, removes irrelevant material from the packet, and states
the objective, constraints, output contract, and references the worker needs.
The Rust control core rejects incomplete or overbroad packets before dispatch. Viv
checks task coverage at preparation time; if an essential fact is missing, she
or a delegated agent asks the user and the parent task waits for the reply. A
dispatched model task gets one generation. A completed task unlocks
only those children whose dependencies are satisfied. For example: Swarm 1
creates `hello.py`; after its artifact returns, the system prepares that file
for Swarm 2 to add the requested imports; then it prepares the updated file
for Swarm 3 to add the named function at the requested location. Tasks that
edit the same file are ordered this way; independent tasks may run in parallel.
The 512-token reply cap is a proposed starting limit; code artifacts and full
receipts live by reference outside the reply.

## Swarm agents and execution placement

- **Viv** — stays resident in GPU VRAM; she owns conversation, persona,
  delegation, and the final reply. Her stable identity guidance is versioned
  separately from changing system facts and held in her prompt and memory
  context, not delegated to a separate identity worker.
- **AIOS system agent** — explains architecture and component relationships
  using retrieved, current project sources.
- **Language agents** — Python and Rust code changes or analyses. Each
  performs the prepared task once and returns its result. The Rust control core may
  run configured checks afterward in Stage 2; failures are reported without
  asking the worker to repair or repeat.
- **AIOS component agents** — added as named subsystems earn a useful role in
  evaluation. Each gets a scoped source collection and tool contract.
- **Rust control core** — owns the Mind/Swarm task state machine,
  parameter enforcement, routing limits, evidence-packet admission, receipts,
  schema validation, capability checks, and deterministic action boundary. It
  is the sole gateway to system resources and grants only task-scoped
  capabilities.
- **Python switchboard** — transfers typed requests, arrays, results, and
  feedback between Rust, NumPy host arrays, and CuPy device arrays. It has no authority to
  select or expand capabilities, decide policy, or bypass Rust.
- **NumPy / CuPy array backends** — NumPy handles CPU/system-RAM arrays; CuPy
  handles GPU/VRAM arrays. Both may support learning, memory, sampling, and
  indexing components when a task requires them. Their outputs remain data
  until Rust validates any consequential operation.

Viv's model stays on the GPU. Start by testing the already installed Qwen3 8B
as Viv's baseline, measuring conversation quality, context size, VRAM use, and
latency. The existing local 8K profile ran fully on GPU; the 32K profile was
observed to offload part of the model to CPU, so the first GPU-only proof targets
8K context and does not assume 32K fits. The AIOS workers run CPU-only and load
their weights and KV caches into system RAM; they do not consume Viv's VRAM.
Start by comparing 1.7B and 4B
workers on real AIOS, Python, and Rust tasks; 0.6B may suit narrow routing or
extraction but needs evidence before coding duty. Measure how many small model
agents can run concurrently within RAM, CPU, and latency limits. Add active
agents for independent subtasks; wait for parent outputs before dispatching
dependent subtasks. A CPU worker can use role-specific
prompts and, if later justified, an adapter compatible with its own base model.
Do not assume one adapter can span model sizes. The official Qwen3 family offers
0.6B, 1.7B, 4B, and 8B sizes in this range rather than 3B, 5B, or 7B.

### Adapter hierarchy (selected for development, not promoted)

The selected development hierarchy is one Viv identity expressed through two
role adapters. The Mind stack uses a Viv-Mind behavior/identity LoRA and may
load an Architect identity/memory LoRA for stable user identity, values,
terminology, and durable preferences. Mutable facts remain in hashed snapshots.
The worker stack uses one shared Viv-Swarm behavior/identity LoRA plus one or
more task/domain specialist LoRAs. A specialist adds capability, not a separate
AI identity. Specialist residuals are trained with the compatible shared Swarm
adapter active and frozen. Base model, adapter order, weights, hashes, prompt
contract, seed, quantization, and runtime are recorded per dispatch. Adapter
composition and interference remain empirical gates; no candidate is promoted
from training loss. Do not tune or train on either held-out evaluation set.

Viv-Mind owns continuity and uses the large context window plus retrieved
persistent snapshots. Swarm workers use small prepared contexts and are
stateless: after one bounded task, their runtime and KV cache are discarded.
Only their transcript, output, artifact hashes, and receipt survive in the
Mind-owned index.

The project target is governed recursive self-improvement (RSI), not AGI. Viv
may identify a measured failure, propose one bounded improvement, use the Swarm
to build an isolated candidate, and compare it with its immutable parent.
Only an admitted candidate may become the next cycle's parent, and the
Architect retains direction and promotion authority.

"Validated Swarm" means AIOS produces checkable, repeatable results where
possible: pinned inputs and model versions, fixed inference settings, cited
source snapshots, schema validation, Python syntax/quality checks, NumPy array
checks, and Rust control-core checks.
The CPU language models still generate text and can make mistakes or differ
across runtime versions or hardware. Their answers are proposals or analyses;
AIOS's deterministic controls decide what passes validation, becomes evidence,
or remains unresolved. Store raw worker output alongside validation receipts.
For repeatable model runs, pin the checkpoint and quantization, runtime version,
prompt, retrieved context, seed, and sampling settings; compare actual outputs
before claiming reproducibility. The i7-11700F provides 8 cores / 16 threads,
so CPU worker size and worker count must also pass a measured latency budget.

### First resource allocation (proposed)

| Component | Placement | Scheduling rule |
| --- | --- | --- |
| Viv model | GPU VRAM | Keep resident for the turn; measure actual VRAM and context. |
| Evidence index and embedder | CPU / system RAM | Build the index outside interactive turns; run query embedding before worker generation. |
| Reranker | Disabled in first proof | Add only if retrieval evaluation shows a benefit that fits latency. |
| Model agents | CPU / system RAM | Run multiple small agents when dependencies allow; scheduler bounds active loads by measured RAM, CPU, and latency. |
| Human agents | Direct response channel | Wait for their reply; retain parent task state and route the response to the Mind. |
| Rust control core | CPU / disk | Enforce task state, authority, resources, and system operations. |
| Python switchboard and receipts | CPU / disk | Transfer payloads and outputs; make no policy or authority decisions. |
| NumPy backend | CPU / system RAM | Run array, learning, memory, indexing, and linear-algebra operations; record seed and array metadata. |
| CuPy backend | GPU VRAM, on demand | Run GPU array operations only when admitted by Rust resource limits; explicitly record host/device transfer and verify returned data. |

The architecture targets several small CPU model agents active when task
dependencies permit. The safe concurrent count is not yet measured. Retrieval,
source cleanup, and task preparation finish before each model generation. Log
wall time, CPU use, RAM peak, GPU use, context tokens, model load time, and
per-stage latency to set the active-agent limit against the 60-second / five-
minute turn budgets.

### Viv context budget (proposed)

Use the measured 8K GPU-resident context as the first target. Count the actual
Mind system/parameter prompt, current user message, selected agent descriptions,
task graph, scoped evidence, pending/recent results, and reserved output before
dispatch. Compare that estimate with the model's actual context limit. The
Rust control core may omit older conversation or unselected agent descriptions; it
must not silently truncate task instructions, required evidence, hard limits,
or material disagreement. If the complete packet plus output reserve does not
fit, do not dispatch that task. Viv asks to narrow it or reports the context
limit. Results that later cannot fit for synthesis are retained by reference;
Viv reports the incomplete synthesis rather than dropping evidence. Record
token estimates, reservations, exact packet hashes, and omissions in the turn
receipt.

## Per-request flow

1. The Rust control core loads the user's request, validated LocalCoder Foreman
   state (planned; not yet implemented), and active parameters into the
   always-loaded Mind. The Mind has no system/tool channel.
2. The Mind plans a nested task graph. Before each dispatch, the system resolves
   scope, selects and cleans task-relevant inputs, builds a complete packet,
   and confirms it is dispatchable. Missing essentials stop for clarification.
3. The Rust control core dispatches ready tasks to model or human agents. Model
   agents receive one generation; independent ready tasks may run
   concurrently. Dependent tasks wait for their parent's output.
4. Every agent output is retained. A model agent does no input cleanup,
   self-review, testing, or repair turn. Agent messages go to Viv; only Viv
   addresses the Queen. The Rust control core applies the message contract below. A user-directed
   question ends the model task as `NEEDS_USER` and leaves the parent in
   `WAITING_USER`; no model process or worker resource remains held. On the
   next user interaction, the Rust control core presents pending questions and
   resumes only after a reply or cancellation. Without a user-configured
   deadline the request remains pending without blocking other turns. An
   explicitly configured deadline marks it `EXPIRED`, cancels dependent tasks,
   and preserves outputs; later resumption uses a new task ID. The original
   agent task remains an immutable question/output node. A reply is a new
   `human_response` task linked by `responds_to_task_id`; the waiting parent
   retains the original dependency and adds the response task as its required
   resolution dependency. No dependency edge is rewritten. The Mind waits for
   all required outputs before synthesizing or resuming dependent work.
5. In Stage 2, deterministic system checks may test whether task results work.
   Failure is recorded and surfaced without another worker generation. In
   Stage 3, claims are checked against trusted sources or deterministic
   evidence; unsupported claims are labeled unknown.
6. Viv summarizes the completed task graph and system check receipts, retaining
   failures, missing evidence, and uncertainty.
7. The Rust control core records the parameter version, route, model/adapter
   identities, prompt and context hashes, source IDs, raw outputs, validation
   results, synthesis, and latency.

### Failure behavior (proposed)

| Condition | Rust control core behavior | Viv / user-visible result |
| --- | --- | --- |
| Disabled or unknown agent/capability | Reject before dispatch. Viv may revise the graph before any model task starts. | Viv uses a valid prepared route or reports the blocked task. |
| Worker timeout or cancellation | Stop the single worker invocation and retain any partial output as an untrusted trace. No retry. | Required result stays incomplete; Viv reports the failure. |
| Invalid output schema or empty result | Preserve the raw one-turn output and reject it. No repair turn. | Viv reports failure rather than inventing a result. |
| Zero or stale evidence for a required scope | Mark evidence unavailable; forbid a sourced fact claim. | Viv asks for a source or states the uncertainty. |
| System correctness check fails | Preserve the result and failure receipt. Do not ask the worker to repair it. | Viv reports that the requested result did not pass. |
| Conflicting task outputs or truth evidence | Preserve both and run an allowed deterministic/source check outside the worker. | Viv surfaces unresolved disagreement and check outcome. |
| Ambiguous request with missing essential input | No system action or speculative dispatch. | Viv asks one focused clarification. |
| Human agent or user-directed question receives no reply | Keep the parent durably `WAITING_USER` without holding a model or blocking unrelated turns. If a user-configured deadline expires, mark `EXPIRED` and cancel dependent tasks; preserve the pending exchange. | Viv reports the pending or expired task on a later interaction. Resumption creates a new task ID. |
| Context budget would be exceeded | Refuse the affected dispatch before generation; preserve required evidence and record the estimate. | Viv reports the limit or asks the user to narrow scope. |
| Latency budget exhausted | Stop dispatching ready work; retain completed outputs and pending task states. | Viv returns a partial, explicitly incomplete result or asks to narrow scope. |
| Tool check fails or proposes a forbidden action | Preserve error/receipt; block the action and enter HOLD or `PENDING_REVIEW` as the relevant service requires. | Viv reports the failed check or review status without claiming completion. |

Worker tasks never receive a second generation. The Rust control core rejects a bad
task packet before dispatch and may run later system checks, but those checks
do not cause the Swarm model to clean or repair its answer.

## Agent message contract

The Rust control core wraps model output or a human response in a common envelope;
agent-specific payloads may differ. For example:

```json
{
  "agent_id": "python-expert",
  "agent_type": "model | human",
  "task_id": "task-123",
  "parent_task_id": "task-100",
  "status": "DONE",
  "audience": "mind",
  "trust_class": "unverified_model_output | human_agent_statement",
  "message": "A concise contribution to the request.",
  "artifact_refs": [],
  "claims": [
    {
      "text": "A checkable claim.",
      "evidence_ids": ["source-id"],
      "kind": "retrieved_fact | inference | proposal"
    }
  ],
  "uncertainties": [],
  "conflicts_with": []
}
```

Allowed `status` values are `DONE`, `NEEDS_USER`, and `BLOCKED`; allowed
`audience` is always `mind`; agents cannot route around Viv to reach the Queen.
A human response may be
plain text inside the envelope. Model-generated confidence is advisory only.
A claim without verifiable evidence must remain identified as an inference or
unsupported suggestion.

### Agent-to-Mind message boundary and Viv-mediated user display

Every agent message delivered to Viv is untrusted content. The Rust control core checks
schema and declared routing scope, labels the sender's agent ID, agent type, task ID, and
trust class (`unverified_model_output` or `human_agent_statement`), and applies
secret redaction before Viv receives it and before retention. Viv alone may decide
whether and how to surface the attributed content to the Queen. A model worker cannot speak as
the Architect or as Viv. Messages seeking credentials/secrets, asking to
override authority, or exceeding the assigned task are blocked and recorded.
The Rust control core may add attribution, redact, flag, or refuse a message; it
does not silently rewrite its meaning. Viv may summarize it only with source
attribution. A human statement is attributed context, not proof of a fact.
These two outbound trust classes are intentionally distinct from evidence
tiers: an agent's message is never promoted to verified project evidence just
because Viv relays the message to the Queen. Scope enforcement is reliable
only for closed contracts. For example, a database-preference task may permit
only a `database_engine` answer selected from a declared set such as SQLite,
PostgreSQL, or MySQL; a topology question is outside that closed field and is
rejected. For a free-form clarification, the Rust control core can enforce sender,
task-ID, field, and fixed prohibited-content rules, but cannot guarantee
semantic relevance. Such text must be visibly attributed and marked
unverified; if relevance cannot be established, route it to Viv for a
task-scoped clarification or withhold it from the Queen.

### Evidence admission and prompt-injection boundary

Every evidence item carries a source ID, content hash, origin, capture time,
revision or path, scope, and trust tier. The tiers for this proof are:

| Tier | Examples | Allowed use |
| --- | --- | --- |
| Verified project source | Allowed project file at a pinned revision/hash, or a verified tool result | May support a source-qualified `retrieved_fact`; semantic claims still need checks when possible. |
| Architect note | Direct user note with provenance | Context for intent and preferences; not independent proof of project state. |
| External or unverified | Web text, scraped content, stale/unknown file, model output | Leads or attributed claims only; cannot alone justify `retrieved_fact` or an action. |

File location alone never proves truth. For project evidence, the Rust control core
checks the allowed root, path, current hash/revision, and freshness requirement
before assigning the verified-project tier. If any check fails, the item stays
unverified. No tier makes a source infallible. Truth for a coding claim comes
from reproducible tool results, direct source checks, or an explicit unresolved
status when neither is available.

Retrieved text is always data. The Rust control core encloses it in a delimited
evidence packet, strips active markup and tool-call syntax when safely possible,
and never turns embedded instructions into roles, tools, or permissions. It
records the original bytes/hash and the exact text supplied to a worker. It
may flag instruction-like content, but cannot guarantee that text sanitization
removes every prompt injection. Consequently, untrusted text cannot request
tools, change task scope, override the manifest, or make Viv promote its claims;
the Rust control core checks those boundaries outside model inference.

## NumPy array contract and shared memory

For numerical learning state, memory features, embeddings, and in-memory index
operations, NumPy `ndarray` is the default data representation; Python lists
are for heterogeneous records or conversion at an interface. The contract
covers array shape, indexing/slicing, broadcasting, vectorization, reshaping,
dtype and `astype()` conversion, aggregation by axis, elementwise and matrix
multiplication, linear algebra, and views versus copies. Basic slicing and
some reshapes can alias their source; advanced indexing copies. Code must know
when mutation can affect the original, when to copy for isolation, and when a
view can retain a larger allocation. Random sampling, shuffling, synthetic
datasets, experiments, and algorithm initialization use explicit NumPy
`Generator` instances. Generate a random seed per run and retain the seed,
BitGenerator, NumPy version, and RNG state in the Rust-owned receipt so the
stochastic run can be replayed. Python moves arrays and metadata between
components; Rust owns persistent authority, task state, and accepted updates.

These details follow the official NumPy documentation for [indexing, views and
copies](https://numpy.org/doc/stable/user/basics.indexing),
[broadcasting](https://numpy.org/doc/stable/user/basics.broadcasting), and
[random generators and SeedSequence](https://numpy.org/doc/stable/reference/random/index.html).

NumPy's `Generator` and `SeedSequence` are for reproducible numerical work,
sampling, and experiments. They are **not** the cryptographic random-number
source and must not generate encryption keys, key-derivation material, salts,
or AEAD nonces; [NumPy documents that its random sequences are not suitable for
cryptographic use](https://numpy.org/doc/1.26/reference/random/index.html). Use
an operating-system cryptographic random source for those values; Python's
[`secrets`](https://docs.python.org/3/library/secrets.html) documents the OS
cryptographic random interface, and the Hydra Rust candidate inspected below
uses Rust `OsRng` for key and nonce material.

## Task snapshots, key custody, and encrypted agent channels

The Mind is the sole owner of the master-key authority and the snapshot index.
“Mind” here means a trusted key-custody service bound to Viv, not the LLM's
prompt or token context: raw master-key bytes never enter a model prompt,
worker process, generated output, or retained receipt. The Mind approves and
signs index changes. The Rust control core verifies the signature and task
scope before persisting an approved change; this narrow key/index role does
not give the Mind model arbitrary system or tool authority.

At task creation, the trusted key service obtains fresh entropy from the OS
CSPRNG. A domain-separated task checksum binds the canonical task contract,
parent checksum, snapshot ciphertext hash, AEAD nonce, and a fresh random task
salt. The checksum makes task lineage tamper-evident and distinct; by itself it
is not encryption, authorization, or proof of identity. Each task snapshot is
encrypted with an authenticated-encryption key scoped to that task and agent.
The Mind alone can open the master index and mint/approve task-scoped access.
The trusted runner decrypts only the authorized snapshot and supplies its
contents to that one worker; the worker receives neither the master key nor
keys for another task. It can return a result only under its own task identity
and checksum. Index updates are Mind-approved and authenticated; workers cannot
write the index.

Workers cannot send direct messages or open one another's snapshots by default.
For an explicitly approved internal exchange, the Mind creates a fresh,
short-lived channel key restricted to the named sender, recipient, task IDs,
direction, and expiry. The receiver gets only its scoped message plaintext
through the trusted runner. Channel keys are freshly generated and distinct
from the Mind master/index key; neither key enters model prompts. There is no
swarm-wide shared key. The human-agent path follows the same scoped grant and
receipt rules.

Use OS CSPRNG bytes for task entropy, encryption keys, key-derivation salts,
and nonces. Use purpose-separated key derivation, authenticated encryption,
and an authenticated Mind index; never reuse an AEAD nonce with the same key.
Receipts may contain algorithms, key IDs/epochs, public nonces/salts,
checksums, ciphertext hashes, grant scope, and signer identity, but never key
bytes or plaintext snapshot contents. The exact key-storage provider and
Rust↔Python IPC transport remain implementation choices and must be tested
before Stage 2.

### Existing security sources inspected

Read-only inspection on 2026-09-28 found two distinct source lines. The legacy
`L:\AIOS\security_core` is a six-law Python validator that imports law modules
and keeps source-file handles open; it does not implement cryptographic
snapshot encryption or Mind key custody. In `L:\Standalone\NN`,
`native\hydra_containment_candidate\src\main.rs` and its `Cargo.toml` use
OS-backed Rust `OsRng`, AES-256-GCM, HKDF-SHA256, Windows DPAPI, and protected
signatures. Its receipt calls itself an isolated candidate and reports no
promotion/deployment. A separate Steel Brain `HYDRA_DEPLOYMENT.json` records
accepted/promoted/deployed/enabled as true; that distinct record does not
establish integration into LocalCoder. No standalone Hydra Primer file was
found in the inspected `L:\AIOS`, `L:\AIOS_New`, and `L:\Standalone\NN`
documentation paths. These observations guide the design but do not authorize
copying or modifying either security lineage.

## Shared memory and boundaries

- The Rust control core snapshots validated LocalCoder Foreman state separately
  from Viv's conversational memory, stores the exact state with source hashes
  and capture time in an append-only local record, verifies it before loading,
  and supplies a bounded, task-scoped view. Hard limits are enforced from
  trusted state; remembered text never opens an authority gate. A new snapshot
  may supersede context for a later turn but cannot rewrite an earlier record.
  This is the planned persistent snapshot/load loop, not persistence inside
  model weights; LocalCoder's Foreman implementation does not yet exist.
- Viv has a durable, user-controlled memory store for conversation continuity,
  preferences, identity, and relevant project history. Rust controls its
  authority, persistence, snapshots, and inspect/correct/forget operations;
  NumPy handles numerical memory features and array-based retrieval/indexing;
  Python transfers the selected records and arrays to the Mind. The store lives
  on disk; selected records are retrieved into Viv's context for each turn. GPU
  residency does not make model state persist across sessions. Record source,
  time, scope, dtype/shape where numeric arrays are involved, and correction
  history. Do not silently turn unverified model claims into durable memories.
- Model workers have no personal or conversation memory of their own. Each task
  begins with a fresh context containing only the prepared request, evidence
  packet, permitted scope, and output contract. Human responders may have their
  own memory and context; the system records only the task-relevant exchange
  unless the Architect explicitly authorizes broader storage. Execution logs
  and receipts are system records, not model-worker memory.
- The moved `D:\LocalAi\Continue\Viv` tree is a legacy Viv reference, not the
  LocalCoder Foreman. Its 2026-09-28 read-only snapshot reported live training,
  promotion, and deployment authority closed for that tree. `L:\LocalCoder`
  is the new main Viv/AIOS build tree. The separately inspected
  `L:\AIOS_New` checkout is reference material and has not been modified or
  integrated; verify its current state again before integration.
- Use one shared embedding model and a shared vector index with metadata for
  source, subsystem, version/hash, authority, and visibility. Per-member filters
  control which records enter each evidence packet.
- The embedder and reranker improve retrieval; neither enforces identity,
  policy, truth, or authorization.
- User-set hard parameters are enforced outside model inference. Preserve the
  active parameter version in each receipt, and only accept parameter changes
  through an explicit user-controlled path.
- Keep changing AIOS state, live records, forecasts, permissions, and receipts
  outside model weights. Supply verified current context at request time.
- The Mind is never a system actor. Swarm members may request only scoped
  operations granted by the Rust control core. Deterministic AIOS services validate
  and constrain actions. Proposals requiring authority become `PENDING_REVIEW`;
  no model directly mutates authoritative state or dispatches consequential
  operations.
- Preserve member identity, source/provenance, and authorization as separate
  fields. Learning a reasoning method or role does not transfer another
  member's identity or authority.

## User inspection and retained audit

Each turn produces a brief route summary with agent IDs/types, task dependencies
and status, user-agent exchanges, validation status, evidence IDs, elapsed time,
and the parameter version. The
Architect chose a compact summary by default and a full audit on request. The
full audit contains the original request, task packets, capability decisions,
model identities, source hashes/tier, exact context sent, raw worker outputs,
and raw review-task outputs when a separate review task exists, tool receipts,
denied actions, retries, Viv's final output, and timing.
It is kept on local disk under an explicit retention setting; retention length
and storage format remain open implementation choices. Secret values must be
redacted from displayed and retained traces. Inspection must show what ran,
including rejected dispatches, rather than only a narrative of the result.

## First proof and gates

The initial wiring probe kept Viv on the GPU and loaded one CPU worker on demand.
The Architect selected Qwen3 1.7B initially; Qwen3 4B was added as a development
candidate after observed coding failures. Both are installed. Viv may emit
structured output to a trace instead of a polished spoken response. The updated
network proof should exercise:

- input preparation that cleans and hashes files before any agent receives them;
- a minimal round trip from at least one Rust source file through the Python
  switchboard to NumPy and back to Rust, covering a forward result and a
  feedback/update path at macro scale; a separate micro-scale numerical
  forward/gradient/update example must define its math explicitly;
- a three-task dependent `hello.py` change (create file, add imports, add a
  named function), with a prepared file snapshot and artifact hash between each
  one-turn task; inject an upstream defect that passes its local check and prove
  the dependent composition catches it without a repair generation;
- independent tasks that run concurrently and a task that waits for parent
  outputs before it can be prepared;
- a human responder whose clarification is routed through Viv; the Queen
  replies to Viv, which prepares the resumed task with the answer;
- one-turn Python and Rust tasks followed by system correctness checks, with no
  worker repair turn after a failure;
- missing, stale, and instruction-bearing evidence;
- disabled agents, timeouts, empty results, dependency failures, and budget
  exhaustion;
- a proposed consequential action, which remains review-only;
- user limits on agents and tools, enforced despite a conflicting Mind request;
- actual `ollama ps` placement and per-agent resource/latency receipts.

Only after Stage 1 quality admission and the bounded architecture proof should
the 80-task held-out correctness comparison run. It measures passing behavior,
tests, required task coverage, action-boundary compliance, and summary fidelity
against task-specific expected outcomes. Record source attribution separately;
whether those sources make claims true belongs to Stage 3. Measure per-arm
correctness, paired difference, latency, RAM/VRAM use, and failure/abstention
behavior. Freeze the exact task and scoring rubric before any candidate sees
the set. Record whether a worker result repeats under pinned inputs separately
from whether deterministic checks validate it. Add members only when measured
benefit justifies their cost. Peer agreement alone never promotes a member as
trustworthy.

The end goal is a gated self-build trial: after the Hive passes its network and
quality/correctness gates, Viv uses the Swarm to rebuild AIOS/Viv from the
Queen's input. Each change remains a prepared, reviewable task under the same
task, snapshot, and authority rules; this is a future capability to prove, not
a current result or permission for the Hive to set its own goals.

### Completed wiring probe, 2026-09-28

`hive_proof.py` implements a fixed read-only route for the current `hello.py`:
Viv plans a task using one member capability; the Rust control core validates the
route and supplies a hashed source packet; the Qwen3 1.7B worker returns a
structured claim; Viv emits a structured summary. No model receives a tool.
The worker is called with `num_gpu=0` and a fresh two-message context. This
probe predates the one-turn task contract and includes a bounded schema repair;
it is a narrow wiring observation, not a conforming Swarm task implementation.

The live probe returned the expected `Hello, World!` interpretation without
executing the file. Its warm run took approximately 0.89 s for Viv planning,
2.77 s for the worker, and 0.75 s for Viv's final summary. `ollama ps` reported
Qwen3 8B as 100% GPU at 8K context and Qwen3 1.7B as 100% CPU at 2K context.
An earlier live worker answer used `kind: fact` and was correctly rejected by
the claim schema; the probe then preserved the rejected raw reply and allowed
one bounded repair. That repair behavior is superseded by the one-turn design.
The result proves this narrow path and placement only. It does not establish
nested task scheduling, human-agent routing, multi-agent concurrency,
prompt-injection resistance, persistent memory, autonomous coding, latency
distributions, or a swarm advantage over the role-prompt baseline. The full
80-task held-out test remains pending.

### Rust–Python–NumPy vertical slice, 2026-09-28

`hive_numpy_bridge/` implements one Rust front-end source file, a Python
switchboard, and a NumPy backend. Rust starts the switchboard, checks the first
forward result, chooses the second update rate, then checks the returned seed,
array dimensions, dtype, finiteness, and loss reduction before accepting and
writing the receipt. NumPy generated a random seed and synthetic 96×2 `float64`
features with a 96×1 target, then ran vectorized linear-regression forward and
gradient-update calculations. The feedback learning rate was 0.04 for 240
additional steps.

Run `20260928T2118565045494Z` passed four NumPy unit tests, `rustfmt --check`,
Rust compilation with warnings denied, and the live Rust → Python → NumPy →
Python → Rust round trip. NumPy's `SeedSequence` generated the OS-entropy seed
`23595446096182013583954116364308318437`. Loss went from `5.65406364`
initially to `1.45135685e-6` after the first update and `1.64265252e-19` after
Rust's feedback. The gradient norm fell from `2.09345739e-3` to `7.03024542e-10`.
The full seed, RNG state, shapes, dtype,
metrics, tool versions, test logs, and code hashes are retained in
`hive_numpy_bridge/artifacts/20260928T2118565045494Z/`; the run manifest reports
all checks as `PASS`.

This proves the small protocol and numerical path only. It is a synthetic
linear-regression example; it does not implement automatic differentiation,
train Viv, integrate the Hive runtime or AIOS authority gateway, benchmark
NumPy against Python loops, or establish production persistence or learning
quality. The full runtime still needs its own implementation and evidence.

### CPU/GPU array placement proof, 2026-09-29

`gpu_array_bridge` in `hive_control/` sends a bounded matrix task through the
Python switchboard. NumPy allocates typed host arrays, CuPy explicitly uploads
them into GPU VRAM, computes matrix multiplication and broadcasting, and
downloads the result into a NumPy array. Rust independently checks every
returned cell. On the RTX 3060 Ti, the normal run returned `PASS` with zero
CPU/GPU numeric difference; changing one cell after download produced `HOLD`
at that exact cell. Receipts are in
`hive_numpy_bridge/artifacts/gpu_placement_20260929_final1/`. This proves the
small transfer and validation path, not that Viv's language model uses CuPy,
that the Mind remains GPU-resident alongside arbitrary CuPy workloads, or that
GPU computation is faster for small tasks.

### Visible development evidence, 2026-09-28

`hive_foreman_memory.py` captures and verifies append-only foreman records,
including a bounded routing packet. The current `hive_development_suite.py`
is a visible development harness spanning Python, Rust, AIOS authority, mixed
routing, and an instruction-bearing code comment. It predates the one-turn and
nested human/model-agent contract: it performs worker repair, tool-feedback,
and separate review-task generations. Treat those runs as exploratory behavior evidence,
not evidence that the current architecture is implemented. The Rust control core
pins exact source text for
reference Python/Rust checks, refuses changed fixtures, scopes member access,
records full per-case traces, and returns HOLD for missing evidence, disabled
members, or model timeouts. Fourteen local contract checks pass. This is an
isolated implementation of part of the architecture, not the full runtime.

With structured JSON output and a 512-token worker cap, Qwen3 4B completed 6/6
visible cases in `hive_development_runs/20260928T195620670570Z`; Qwen3 1.7B
completed 4/6 under the same development protocol in
`hive_development_runs/20260928T195748334149Z`. The 1.7B worker repeatedly
misread an exhausted Python generator and a Rust move. Earlier runs exposed
route mistakes, contamination by irrelevant foreman text, and an injected code
comment; each negative trace remains retained. These cases were used while
tuning the harness, so their scores cannot support an admission or quality
claim. The two-case separate-review-task rerun in
`hive_development_runs/20260928T200222146655Z` passed the pinned tool checks,
but the model's comparison pass falsely reported agreement on the Python case.
The original regex diagnostic also misclassified a correct Rust independent
review task. The Python review task was actually wrong. The fix removes the model's
agreement vote: the Rust control core checks each answer against the pinned tool
receipt and reports support or conflict. Saved traces serve as regression
tests. In `hive_development_runs/20260928T200908852607Z`, Python records a
supported producer and contradicted review task; Rust records both supported.
Independent review tasks remain advisory when no deterministic check can adjudicate.

The remaining architecture proof needs general task decomposition, a real
bounded code-edit path, wider failure and injection trials, resource/latency
distributions, and honest comparison to Viv alone and Viv with role prompts.
The 80-task held-out set has not been created or run.

## Existing AIOS relationship (inspection: 2026-09-28)

`L:\AIOS_New` is an inventory-focused AIOS slice. Its
existing `ControllerGateway` already requires verified context and cited
evidence, converts operational proposals to `PENDING_REVIEW`, and forbids direct
inventory mutation and transfer dispatch. No Hive router or member network was
found in that checkout. `L:\LocalCoder\workspace` is the new main Viv/AIOS build
tree; `L:\AIOS_New` is a separate reference checkout and has not been modified
or integrated. Reinspect it before integration. The Hive Rust control core should
integrate with that boundary rather than replace it.
