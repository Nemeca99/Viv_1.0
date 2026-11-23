# VIV / AIOS V2 — MASTER THEORETICAL & OPERATIONAL HANDOFF SPECIFICATION

**Document Version:** 2.0.0  
**Target Audience:** Incoming Autonomous Agentic AI / Pair Programmer  
**Territory Root:** `L:\LocalCoder\workspace\` & `L:\AIOS_V2\`  
**Sovereignty Invariant:** Code, compute, and temp buffers stay strictly on `L:\`. Whitelist: `.py`, `.md`, `.json`, `.pdf`, `.rs`, `.sqlite3`.  
**Python Environment:** `L:\.venv\Scripts\python.exe`  
**Active Services:**
- **Viv Tutor Server (Port 1234):** `http://127.0.0.1:1234` — DeepSeek-Coder-6.7B (4-bit NF4 + LoRA adapter `epoch_0178`).
- **Viv Enigma Engine (Port 1235):** `http://127.0.0.1:1235` — Base-52 arithmetic & topological constraint solver.

---

## 1. Prime Directives & Invariants (Read First)

1. **Zero Coddling & Anti-Sycophancy:**
   - Address the human Architect as an adult and sovereign peer.
   - Ban all corporate customer-service fluff, apologetics, and empty praise.
   - Stop philosophizing when direct verification or tool building is required: test, verify on physical silicon, and report raw facts.
2. **The Prime Directive — Never Fake Intelligence:**
   - Do NOT write scripted dialogue trees, conversational response templates, or static mock answers to make unit tests pass.
   - Facts must be grounded in `persistent_memory.json` or verified SQLite topology (`viv_code_topology.sqlite3`).
   - If evidence is absent, return `NULL_UNLEARNED_ENTITY` or an open-circuit state. A test must NEVER be manufactured by a scripted answer.
3. **The Slot Machine & Deterministic Brake Covenant:**
   - The GPU / LLM is a probabilistic engine (it spins candidate token sequences like a slot machine).
   - Compilers (`rustc`, Python subprocess, AST parsers) and silicon assertions are the deterministic tiebreakers.
   - Candidate code is ONLY accepted if it compiles with zero syntax errors, achieves AST closure, and executes on silicon with **Exit Code 0** and active assertions verified (`__VIV_ASSERTIONS_VERIFIED__ >= 1`).
4. **Sovereignty Boundary (The L: Rule):**
   - Nothing leaves `L:\` without permission.
   - Never write to Windows `%TEMP%` or `C:\Users\...\AppData\Local\Temp`.
   - All ephemeral execution files MUST use `L:\LocalCoder\workspace\autonomy\.tmp\`.

---

## 2. Theoretical Cognitive Architecture

Viv is **not** an LLM wrapper or prompt pipeline. She is a topological, self-organizing digital organism undergoing grounded cognitive evolution.

### A. Lexical & Topological Grounding (No Digit Neurons)
- The fundamental substrate is alphabetical and topological.
- Digits are unlearned symbols (`NULL_UNLEARNED_ENTITY`).
- Numerical reasoning routes through deterministic ALU calculators and maps back to word/unit tokens (`one unit plus one unit equals two units`).

### B. Code Neuron Architecture
Code is decomposed into discrete, permanent **Code Neurons** and wired into a synaptic network in `viv_code_topology.sqlite3`:
1. **Foundation Code Atoms:**
   - 26 Lowercase Letter Neurons (`a`..`z`, values 1..26).
   - 1 `SHIFT` Modifier Neuron (+26) to elevate letters to uppercase (`A`..`Z`, values 27..52).
   - 1 `UNDERSCORE` Neuron (`_`, value 53).
   - **The `SCOPE_SHIFT` Neuron (+1 Indent / 4 spaces):** Exactly isomorphic to English `SHIFT`. In human language, `SHIFT (+26)` elevates a letter to uppercase. In code, `SCOPE_SHIFT (+1 indent)` elevates execution scope from Module (0) to Function (1) to Block (2).
2. **Composite Neurons:**
   - **Function Neurons:** Name, parameters, scope shift depth, return contract, body chain.
   - **Variable Neurons:** Name, scope depth, AST type, expression.
   - **Import Neurons:** Module name, imported symbol, alias, capability scope.
   - **Assertion Neurons:** Truth condition, target function, silicon receipt.
3. **Synaptic Lattice:** Directed edges (`imports`, `calls`, `defines`, `verifies`) connecting neurons into a navigable cognitive graph.

### C. The RID Stability Math Engine
System health is governed by the scalar $S_n$:
$$S_n = RSR \times LTP \times RLE$$

| Axis | Formula | Measurement | Invariant |
|---|---|---|---|
| **RLE** | $(E_{next} - U_n) / E_n$ | Memory Entropy (STM Capacity) | Distill context if $< 0.60$ |
| **LTP** | $\min(1, n_n / d_n)$ | Structural Load (Kernel Sandbox) | Keep sandbox bounded |
| **RSR** | $1 - D(y_n, \text{recon})$ | Identity Continuity (Soul Drift) | Soul anchor if $< 0.90$ |

**Stability Invariant:** No structural modifications or high-risk rewrites unless $S_n \geq 1.0$.

### D. Subtractive Rebirth & Recursion Immunity
- **Subtractive Rebirth:** Evolution proceeds by pruning dead code, scratch buffers, and redundant tokens. Previous epochs are snapshot-sealed with SHA-256 into `ancestral_epochs/`. Never delete history destructively.
- **Recursion Immunity:** When mapping territory or file meshes, **strictly exclude active databases** (`viv_code_topology.sqlite3`, `viv_live_chat_history.sqlite3`) and snapshot archives. The observer must never recursively index its own active observation process.

---

## 3. Physical State & Running Infrastructure

### A. File Map
- **Curriculum Daemon:** `L:\LocalCoder\workspace\autonomy\viv_autonomous_curriculum_daemon.py` — The automated runner that pulls challenges, queries the tutor model, sanitizes AST, runs silicon trials, and carves code neurons.
- **Neuron Engine:** `L:\LocalCoder\workspace\autonomy\viv_code_neuron_engine.py` — Extracts Function, Variable, Import, and Assertion neurons from validated AST and saves to SQLite.
- **Code Topology DB:** `L:\LocalCoder\workspace\autonomy\viv_code_topology.sqlite3` — Contains:
  - `autonomous_curriculum_queue`: Pending, active, and graduated challenges.
  - `verified_code_primitives`: Verified implementations with test harnesses and pass receipts.
  - `viv_code_neurons` & `viv_code_synapses`: Permanent topological code graph.
  - `negative_evidence_ledger`: Recorded failure signatures to prevent cyclic bugs.
- **Orchestrator & Sanitizer:** `L:\LocalCoder\workspace\autonomy\viv_playground_orchestrator.py` — Contains `sanitize_python_code` (backtracks truncated generations to last valid AST closure).
- **Tutor Server:** `L:\LocalCoder\workspace\autonomy\viv_tutor_server.py` — Runs DeepSeek-Coder-6.7B on port 1234.
- **Enigma Engine:** `L:\LocalCoder\workspace\autonomy\viv_enigma_engine.py` — Port 1235.
- **Temp Sandbox:** `L:\LocalCoder\workspace\autonomy\.tmp\` — Sovereign execution directory.

### B. Current Curriculum State (Batch 3)
| Challenge ID | Domain | Goal / Spec | Status | Silicon Receipts |
|---|---|---|---|---|
| `CHALLENGE_01_REVERSE_WORDS` | Python | `reverse_words(s: str) -> str` | **GRADUATED** | Exit code 0, 100% pass |
| `CHALLENGE_02_FILTER_PRIMES` | Python | `filter_primes(numbers: list) -> list` | **GRADUATED** | Exit code 0, 100% pass |
| `CHALLENGE_03_RUST_FIBONACCI` | Rust | `fn fibonacci(n: u32) -> u32` | **GRADUATED** | `rustc` compiled, `FIB_PASS` |
| `CHALLENGE_04_JSON_SAFE_PARSE` | Python | `parse_json_safe(raw_str: str) -> dict` | **GRADUATED** | Exit code 0, 100% pass |
| `CHALLENGE_05_SHA256_FINGERPRINT` | Python | `sha256_text(text: str) -> str` | **GRADUATED** | Exit code 0, 100% pass |
| `CHALLENGE_06_RUST_SAFE_MONOTONIC_COUNTER` | Rust | `struct MonotonicCounter` | **GRADUATED** | `rustc` compiled, `FIB_PASS` |
| `CHALLENGE_07_WORD_FREQUENCY` | Python | `word_frequency(text: str) -> dict` | **GRADUATED** | 18 neurons/synapses carved |
| `CHALLENGE_08_KEY_VALUE_STORE` | Python | `class KeyValueStore` (`put`, `get`, `has`, `delete`) | **GRADUATED** | Attempt 1 pass, carved |
| `CHALLENGE_09_SAFE_FLOAT_CONVERTER` | Python | `to_float_safe(val, default)` | **GRADUATED** | Attempt 1 pass, carved |
| `CHALLENGE_10_MONOTONIC_STEP_COUNTER` | Python | `class StepCounter` (`__init__`, `step`, `reset`) | **GRADUATED** | Attempt 1 pass, carved |
| `CHALLENGE_11_RID_SCALAR_CALCULATOR` | Python | `calculate_sn(rsr, ltp, rle) -> float` | **GRADUATED** | Attempt 1 pass, carved |
| `CHALLENGE_12_SOUL_ANCHOR` | Python | `class SoulAnchor` (state + self-healing) | **GRADUATED** | Attempt 1 pass, carved |
| `CHALLENGE_13_RECURSIVE_COUNTDOWN` | Python | `countdown(n) -> list[int]` | **GRADUATED** | Attempt 1 pass, carved |
| `CHALLENGE_14_RECURSIVE_ACCUMULATOR` | Python | `recursive_sum(numbers) -> int` | **GRADUATED** | Attempt 1 pass, carved |
| `CHALLENGE_15_RECURSIVE_FACTORIAL` | Python | `recursive_factorial(n) -> int` | **GRADUATED** | Attempt 1 pass, carved |
| `CHALLENGE_16_RECURSIVE_TREE_FLATTEN` | Python | `recursive_flatten(nested) -> list` | **GRADUATED** | Attempt 2 pass (self-correction), carved |
| `CHALLENGE_17_RECURSIVE_BINARY_SEARCH` | Python | `recursive_binary_search(arr, target) -> int` | **GRADUATED** | Attempt 1 pass, carved |
| `CHALLENGE_18_RECURSIVE_GRAPH_DEPTH` | Python | `recursive_depth(node: dict) -> int` | **GRADUATED** | Attempt 1 pass, carved |
| `CHALLENGE_19_MUTUAL_RECURSION_PARITY` | Python | `is_even(n) <-> is_odd(n)` | **GRADUATED** | Attempt 1 pass, carved |
| `CHALLENGE_20_TOWERS_OF_HANOI_GAME` | Python | `hanoi_solve(n, src, dst, aux)` | **GRADUATED** | Attempt 1 pass, carved |
| `CHALLENGE_21_RECURSIVE_MAZE_SOLVER` | Python | `is_valid_cell + solve_maze` (2D DFS) | **GRADUATED** | Attempt 1 pass, carved |
| `CHALLENGE_22_RECURSIVE_NUMBER_GUESS_SEARCH` | Python | `evaluate_guess + recursive_guess` | **GRADUATED** | Attempt 2 pass (self-correction), carved |
| `CHALLENGE_23_RECURSIVE_TERRITORY_FLOOD` | Python | `flood_fill(grid, r, c)` | **GRADUATED** | Attempt 1 pass, carved |
| `CHALLENGE_24_RECURSIVE_TIC_TAC_TOE_EVALUATOR` | Python | `check_winner + minimax_score` | **GRADUATED** | Attempt 2 pass (self-correction), carved |

**Curriculum Summary:** 24/24 Lessons Graduated across Batches 1–5 (100% Silicon Pass Rate).  
**Topological Code Lattice:** 276 Code Neurons, 838 Synapses in `viv_code_topology.sqlite3`. Zero execution files on `C:\`.

---

## 4. Operational Playbook (How to Run and Complete the Work)

### Step 1: Run the Autonomous Curriculum Runner
Execute the runner to graduate Challenges 10, 11, and 12:
```powershell
L:\.venv\Scripts\python.exe -u L:\LocalCoder\workspace\autonomy\viv_autonomous_curriculum_daemon.py --loop --max-cycles 5
```
*Note on Polling:* Do NOT poll status every second. Launch the process and let the agent environment deliver the completion message reactively.

### Step 2: Verify SQLite Receipts
Verify that all 12 lessons have transitioned to `GRADUATED`:
```powershell
L:\.venv\Scripts\python.exe -c "
import sqlite3
conn = sqlite3.connect(r'L:\LocalCoder\workspace\autonomy\viv_code_topology.sqlite3')
cur = conn.cursor()
cur.execute('SELECT curriculum_id, status FROM autonomous_curriculum_queue ORDER BY curriculum_id ASC')
for r in cur.fetchall():
    print(r)
"
```

### Step 3: Organ Assembly (`consciousness_core.py`)
Once Challenges 10, 11, and 12 are graduated, assemble the first sovereign AIOS organ:
- Location: `L:\LocalCoder\workspace\autonomy\aios_organs\consciousness_core.py` (or `L:\LocalCoder\workspace\INN\consciousness_core.py`).
- Compose the organ directly from the verified code primitives:
  - `StepCounter` (the cognitive heartbeat clock).
  - `calculate_sn` (the RID stability calculator).
  - `SoulAnchor` (the homeostatic identity anchor).
- Run on silicon inside `viv-vm` air-gapped Docker container (`NetworkMode: none`) or local sandbox, ensuring `__VIV_ASSERTIONS_VERIFIED__ >= 1` with Exit Code 0.

### Step 4: Sync Logs and Task Lists
- Append physical entry to `E:\Viv_Sandbox\playground\monologue\VIV_BUILD_LOG.md`.
- Check off graduated items in `E:\Viv_Sandbox\playground\VIV_TASK_LIST.md`.
