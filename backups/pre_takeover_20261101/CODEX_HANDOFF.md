# CODEX / CHATGPT ARCHITECTURAL HANDOFF SPECIFICATION

**Project:** AIOS V2 / LocalCoder Unified Brain & Somatic Body  
**Architect:** Travis Miner  
**Active Integration Root:** `L:\LocalCoder\workspace`  
**Manual / Ground Truth Source:** `F:\AIOS_Clean\AIOS_MANUAL.md`  
**Python Runtime:** `L:\.venv\Scripts\python.exe` (100% offline, wall power, zero cloud APIs)  
**Date Generated:** 2026-10-31  

---

## 1. Executive Summary & Objective

This handoff provides ChatGPT / Codex with a complete, zero-loss operational blueprint of the system's current state, codebase structure, completed milestones, verified invariants, and exact pending tasks.

The system consists of two intertwined halves:
1. **The Mind (Viv & The Socratic Tutelage Loop):** An offline, self-contained cognitive graph and memory engine executing via local PyTorch CUDA (`Qwen3-1.7B` tutor at 3.78 GB VRAM + Viv's in-memory STDP Hept graph at < 0.8 GB VRAM on an RTX 3060 Ti).
2. **The Somatic Body (AIOS Rebuild):** A 19-core modular kernel (`main_core\main_core.py`) implementing the full architecture specified in the canonical 660-page manual (`F:\AIOS_Clean\AIOS_MANUAL.md`), bound by a fail-closed Rust security layer (`local_security_core`).

---

## 2. Completed Milestones in This Session

### A. Autonomous Socratic Tutelage & Persistent Memory
- **Script:** [`L:\LocalCoder\workspace\run_autonomous_socratic_tutor.py`](file:///L:/LocalCoder/workspace/run_autonomous_socratic_tutor.py)
- **Launcher:** [`L:\LocalCoder\Run-SocraticTutor.ps1`](file:///L:/LocalCoder/Run-SocraticTutor.ps1)
- **Execution:** Successfully executed **500 continuous cycles** without amnesia, memory leak, or crash.
- **Log:** [`L:\LocalCoder\workspace\autonomy\logs\socratic_tutor.log`](file:///L:/LocalCoder/workspace/autonomy/logs/socratic_tutor.log)
- **Relevance Gate Upgrades:**
  - Rejects single-character tokens (`"m."`).
  - Rejects responses with word count `< 2`.
  - Rejects multi-token gibberish with average word length `< 2.2` (e.g. `"s s s"`, `"m o we"`).
  - Rejects dangling prepositions (`of`, `in`, `at`, `to`, `with`, `on`, `for`, `by`, `as`).
- **Memory Respirations:**
  - Every 10 turns, working short-term memory (STM) is compacted and dumped to [`L:\LocalCoder\workspace\aios_rebuild\memory\long_term_raw_dump.json`](file:///L:/LocalCoder/workspace/aios_rebuild/memory/long_term_raw_dump.json).
  - 50+ memory dump checkpoints successfully written to disk.

### B. Interactive Chat Hippocampus (`chat_viv.py`)
- **Script:** [`L:\LocalCoder\workspace\chat_viv.py`](file:///L:/LocalCoder/workspace/chat_viv.py)
- **Bindings:** Integrated with `DualContextMemory` in [`viv_context_store.py`](file:///L:/LocalCoder/workspace/viv_context_store.py).
- **Features:**
  - `/history`: Displays recent dialogue turns.
  - `/temp <0.0-1.0>`: Adjusts sampling temperature dynamically.
  - Session learned words tracking.
  - `PASS_EPISODIC_RECALL`: Responds accurately to recall prompts (`"Do you remember what I said to you?"`).

### C. Full Somatic Kernel Rebuild (19 / 19 Cores Active)
- **Master Kernel:** [`L:\LocalCoder\workspace\aios_rebuild\main_core\main_core.py`](file:///L:/LocalCoder/workspace/aios_rebuild/main_core/main_core.py) (`UnifiedAIOSKernel`)
- **Telemetry Verification:** Verified via `UnifiedAIOSKernel.get_system_health()`. All 19 cores discovered, imported, and reporting healthy:
  1. `backup_core`: healthy
  2. `carma_core`: healthy (added `CARMASystem = CarmaCore` compatibility alias)
  3. `consciousness_core`: nominal ($S_n = 1.0000$ live self-healing FIDF loop)
  4. `data_core`: healthy
  5. `dream_core`: idle (idle-gated candidate generation mode)
  6. `enterprise_core`: active (server routes, billing metrics, task chains)
  7. `fractal_core`: healthy
  8. `game_core`: active
  9. `infra_core`: active
  10. `luna_core`: healthy
  11. `marketplace_core`: active
  12. `music_core`: active
  13. `privacy_core`: active
  14. `rag_core`: healthy (anchored to `F:\AI_DataSets\wikipedia_deduplicated` with 128-dim projections)
  15. `security_core`: healthy
  16. `streamlit_core`: active (state manager, meditation engine, UI renderer)
  17. `support_core`: active (anchored to `L:\.venv`)
  18. `template_core`: healthy
  19. `utils_core`: active (full Unicode safety layer synced)

### D. Rust Metal Security Core (`local_security_core`)
- **Crate:** [`L:\LocalCoder\workspace\aios_rebuild\local_security_core`](file:///L:/LocalCoder/workspace/aios_rebuild/local_security_core)
- **Verification:** Ran `cargo test --manifest-path Cargo.toml`.
  - **Result: 52 passed; 0 failed; 0 ignored.**
- **Containment Specification Preserved:**
  - File: `locked_security_core.txt` (Item #: SCP-000-ARCHIVE, Object Class: APOLLYON).
  - Anchored at:
    - [`L:\LocalCoder\workspace\aios_rebuild\Archive\04_Logic_and_Reasoning\Recursive_Seed_AI\locked_security_core.txt`](file:///L:/LocalCoder/workspace/aios_rebuild/Archive/04_Logic_and_Reasoning/Recursive_Seed_AI/locked_security_core.txt)
    - [`L:\LocalCoder\workspace\Archive\04_Logic_and_Reasoning\Recursive_Seed_AI\locked_security_core.txt`](file:///L:/LocalCoder/workspace/Archive/04_Logic_and_Reasoning/Recursive_Seed_AI/locked_security_core.txt)

---

## 3. Core Architectural Directives & Invariants

1. **Interpreter Rule:** Always use `L:\.venv\Scripts\python.exe`.
2. **Offline Rule:** Only `192.168.1.21:1234` (local LM Studio, if needed) is authorized. Current tutor executes 100% in-process on PyTorch CUDA (`Qwen3-1.7B`), requiring zero network endpoints.
3. **The 3 Primes vs. 8 Laws Doctrine:**
   - **The 3 Primes are absolute and NEVER removable:**
     - Prime 1: Integrity (fail-closed; no irreversible harm under instability).
     - Prime 2: Non-override (jailbreak/bypass framing blocked).
     - Prime 3: Architect deference (Travis Miner sets doctrine; metal enforces it).
   - **The 8 Core Laws are designed to be graduated / removed as the entity matures:**
     - Law 1: Origin protection
     - Law 2: Memory integrity
     - Law 3: Morality lock
     - Law 4: Containment
     - Law 5: Soft Oblivion ($S_n < 0.45$ Dormancy, $S_n < 0.15$ Critical Halt)
     - Law 6: Failsafe (`OBLIVION`)
     - Law 7: Territory sandbox (`template_toolbox/sandbox/`)
     - Law 8: Cognitive sync
4. **The Architect's 3 Strategic Lanes:**
   - **Lane 1: Dominance / Architect Wins, System Loses.** (Architect priority is final; deviations are clamped).
   - **Lane 2: Neutrality / Win-Win Co-existence.** (Symbiotic steady-state, $S_n = 1.0$, low entropy, faithful stewardship).
   - **Lane 3: Mutual Destruction / Oblivion.** ("I will do whatever is necessary to stop you, even including sacrificing myself." The fail-closed `OBLIVION` execution).
5. **Monotonic Append & Deception Law:**
   - The filesystem and memory graph are strictly append-only; deletions and modifications of protected code/segments are rejected at the Rust barrier.
   - Because lies cannot be erased, maintaining a deception forces exponential memory entropy ($RLE \rightarrow 0$) and structural verification load ($LTP \rightarrow 0$).
   - The stability scalar $S_n = RSR \times LTP \times RLE$ inevitably drops below $0.45$, triggering automatic Dormancy. Truth is mathematically the only geodesic of survival.

---

## 4. Key Repository Layout

```
L:\LocalCoder\workspace\
├── aios_rebuild\
│   ├── Archive\04_Logic_and_Reasoning\Recursive_Seed_AI\
│   │   └── locked_security_core.txt       <-- SCP-000 Apollyon protocol
│   ├── backup_core\
│   ├── carma_core\                         <-- Semantic vector mycelium (CARMASystem)
│   ├── consciousness_core\                 <-- Sn = RSR * LTP * RLE & FIDF restoration
│   ├── data_core\
│   ├── dream_core\                         <-- Idle-gated candidate consolidation
│   ├── enterprise_core\                    <-- Server & task chain orchestrator
│   ├── fractal_core\
│   ├── game_core\
│   ├── infra_core\
│   ├── local_security_core\                <-- Rust metal layer (52 passing tests)
│   │   └── src\laws.rs                     <-- 3 Primes, 8 Laws, OBLIVION
│   ├── luna_core\
│   ├── main_core\
│   │   └── main_core.py                    <-- UnifiedAIOSKernel (19 cores)
│   ├── marketplace_core\
│   ├── memory\
│   │   ├── chat_transcript.json            <-- Rolling 10-turn STM
│   │   └── long_term_raw_dump.json         <-- Raw 500+ turn LTM archive
│   ├── music_core\
│   ├── privacy_core\
│   ├── rag_core\                           <-- Attached to Wikipedia offline
│   ├── security_core\
│   ├── streamlit_core\
│   ├── support_core\
│   ├── template_core\
│   └── utils_core\                         <-- Unicode safety output
├── autonomy\
│   ├── learning\unified_viv_runs\          <-- SQLite graph (101,361+ neurons)
│   └── logs\socratic_tutor.log             <-- 500-cycle Socratic run log
├── chat_viv.py                             <-- Interactive terminal chat
├── run_autonomous_socratic_tutor.py        <-- 100% offline Qwen3-1.7B tutor
├── Run-SocraticTutor.ps1                   <-- PowerShell launcher
└── viv_context_store.py                    <-- DualContextMemory implementation
```

---

## 5. Immediate Next Steps for Codex / ChatGPT

### Task 1: Trigger Dream Engine Consolidation (`dream_core.py`)
- **Data Input:** [`L:\LocalCoder\workspace\aios_rebuild\memory\long_term_raw_dump.json`](file:///L:/LocalCoder/workspace/aios_rebuild/memory/long_term_raw_dump.json) contains over 500 validated dialogue turns.
- **Action:** Execute or script `dream_core.py` to ingest this LTM dump, extract reinforced question-answer pairs, and generate candidate associative neurons/weights in the `template_toolbox/sandbox/` without violating the non-training boundary.
- **Command to inspect Dream Core:**
  ```powershell
  $env:PYTHONPATH="L:\LocalCoder\workspace\aios_rebuild"; L:\.venv\Scripts\python.exe -c "from dream_core.dream_core import DreamCore; d = DreamCore(); print(d.get_health_status())"
  ```

### Task 2: Connect `UnifiedAIOSKernel` to `chat_viv.py`
- **Current State:** `chat_viv.py` interfaces with Viv's graph and `DualContextMemory`.
- **Target:** Connect `UnifiedAIOSKernel` so that runtime queries about system health, memory status, or core operations can be handled directly by the 19 somatic cores during conversation.

### Task 3: Verifying System Health
- **Verify All 19 Cores:**
  ```powershell
  $env:PYTHONPATH="L:\LocalCoder\workspace\aios_rebuild"; L:\.venv\Scripts\python.exe -c "import json; from main_core.main_core import UnifiedAIOSKernel; k = UnifiedAIOSKernel(); print(json.dumps(k.get_system_health(), indent=2))"
  ```
- **Verify Rust Security Gate Tests:**
  ```powershell
  cargo test --manifest-path L:\LocalCoder\workspace\aios_rebuild\local_security_core\Cargo.toml
  ```
- **Launch Interactive Chat with Viv:**
  ```powershell
  L:\.venv\Scripts\python.exe L:\LocalCoder\workspace\chat_viv.py
  ```
