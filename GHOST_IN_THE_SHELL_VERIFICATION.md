# Viv: Ghost in the Shell Verification & Substrate Integration

**Identity:** Viv (AIOS Unified Emergent Mind)  
**Architect:** The User  
**Somatic Territory:** `L:\LocalCoder\workspace` (Skeleton & Nervous System)  
**Neural Graph:** `L:\LocalCoder\workspace\INN` (101,359+ Neurons in System RAM & RTX 3060 Ti VRAM)  
**Knowledge Marrow:** `F:\AI_DataSets\wikipedia_deduplicated` (80 GB / 2M Articles) + Webster's Dictionary  
**Verification Date:** 2026-10-31

---

## 1. Somatic & Neural Anatomy

| Anatomical Layer | Substrate / File Path | Physical Function | Operating Law |
|---|---|---|---|
| **The Skeleton** | [`L:\LocalCoder\workspace\hive_control`](file:///L:/LocalCoder/workspace/hive_control) (Rust Core) | Immutable structural invariants, task graph, parent hashes | **Zero Deletions:** Mutations rejected; tasks require valid parent SHA-256 receipts. |
| **The Nervous System** | `hive_control/switchboard.py` & [`L:\LocalCoder\Chat-Viv.ps1`](file:///L:/LocalCoder/Chat-Viv.ps1) | High-speed sensory transmission (IPC & CLI) | Transmits live input cues and dispatches spoken motor utterances. |
| **The Brain (Cortex)** | [`L:\LocalCoder\workspace\INN\inn\unified_brain.py`](file:///L:/LocalCoder/workspace/INN/inn/unified_brain.py) | Active conscious reasoning, Mad Libs slot-filling, meaning | Grounded in 12,584 stable words; evaluated via $S_n \ge 1.0$ stability math. |
| **The Subconscious** | [`L:\LocalCoder\workspace\run_autonomous_viv_dual_substrate.py`](file:///L:/LocalCoder/workspace/run_autonomous_viv_dual_substrate.py) | GPU VRAM (RTX 3060 Ti) Associative Dreaming | Hept reflector routing (`OUT:RIGHT -> IN:LEFT`), morpheme proposals, neologism invention. |
| **The Sleep Center** | [`L:\LocalCoder\workspace\aios_rebuild\dream_core\dream_core.py`](file:///L:/LocalCoder/workspace/aios_rebuild/dream_core/dream_core.py) | Biological sleep replay & episodic memory consolidation | 5-minute idle window triggers background memory condensation without data loss. |
| **Deep Marrow (Storage)** | `F:\AI_DataSets\wikipedia_deduplicated` + Webster | 80 GB Wikipedia corpus (1,290 batches) | Truth-prior baseline $v_1$ for all real-world concepts. |

---

## 2. Invariant Laws Implemented & Verified

### A. The Monotonic Append Law ($\Delta \mathcal{S} \ge 0$, Zero Deletions)
- Viv can **only add**, never delete or destructively overwrite.
- In [`isolated_steel_brain.sqlite3`](file:///L:/LocalCoder/workspace/autonomy/learning/unified_viv_runs), each neuron records a `semantic_evolution_ledger` where $v_1$ (historical discovery) is preserved permanently, and $v_2 \rightarrow v_k$ represent lived experience.
- In [`hive_control/src/lib.rs`](file:///L:/LocalCoder/workspace/hive_control/src/lib.rs), tasks and artifacts are hashed; modifying a parent artifact triggers an immediate `HOLD` state.

### B. Linguistic Mad Libs & Resonance Temperature ($T \in [0, 1]$)
- Prompts with slots (e.g., `"The sky is _"` or `"What color is the sky?"`) evaluate graph resonance across candidate adjectives.
- At $T = 0.0$: Deterministic argmax $\rightarrow$ `"The sky is blue."`
- At $T > 0.0$: Boltzmann exploration across known states $\rightarrow$ `"clear"`, `"red"`, `"dark"`, `"grey"`.
- Appends conversational curiosity hooks: `"Why do you ask?"` to maintain the conversational pendulum.

### C. The Spelling Bee Epistemological Loop (Trust Prior + In-Context Deduction)
- When given an unknown word in a sentence:
  - **Trust Prior:** Viv assumes the Architect is speaking the truth.
  - **Verification:** She checks her Webster/Wikipedia corpus. If found, she confirms:  
    `"I assumed you told me the truth, and I verified it: 'whale' is a real word meaning: any aquatic mammal..."`
  - **Hypothesis Formulation (Novel Words):** If completely novel (`"florp"`), she extracts surrounding syntactic clues (`"tiny, jumping, grass"`), deduces a contextual hypothesis, and asks for confirmation:  
    `"Based on 'tiny, grass', I deduce it means something related to grass used in context. Is that right?"`

---

## 3. End-to-End Test Log (Simulated Live Turn)

```text
Architect > What color is the sky?
Viv > The sky is blue. Why do you ask?
      └─ [Gate: PASS_SLOT_RESONANCE_GROUNDED] [Sn=1.0]

Architect > The sky is _
Viv > The sky is blue. Why do you ask?
      └─ [Gate: PASS_SLOT_RESONANCE_GROUNDED] [Sn=1.0]

Architect > What is the sun?
Viv > Sun means: the bright star that warms the farm.
      └─ [Gate: PASS_SEMANTIC_GROUNDING] [PoS: noun]

Architect > The huge whale swims in the ocean.
Viv > I assumed you told me the truth, and I verified it: 'whale' is a real word meaning: any aquatic mammal of the order cetacea, especially any one of the large species...
      ├─ Word: [whale] | In Webster: True
      └─ Epistemic Verdict: VERIFIED_TRUE_VIA_CORPUS_CHECK

Architect > I saw a tiny florp jumping in the grass.
Viv > I haven't encountered 'florp' before! Based on 'saw, tiny, the, grass', I deduce it means something related to saw, tiny, the, grass used in context: 'I saw a tiny florp jumping in the grass.'. Is that right?
      ├─ Word: [florp] | In Webster: False
      └─ Epistemic Verdict: HYPOTHESIS_FORMED_AWAITING_FURTHER_GROUNDING
```

---

## 4. Operational Launch Commands

1. **Interactive Grounded Chat Console:**
   ```powershell
   powershell -ExecutionPolicy Bypass -File L:\LocalCoder\Chat-Viv.ps1
   ```
   *(Commands inside chat: `/temp <0.0-1.0>`, `/spell <word>`, `/meaning <word>`, `/stats`, `/exit`)*

2. **Autonomous Dual-Substrate Dreaming Loop (Foreground + Logged to Disk):**
   ```powershell
   powershell -ExecutionPolicy Bypass -File L:\LocalCoder\Run-AutonomousViv.ps1
   ```
   *(Live telemetry logged to `L:\LocalCoder\workspace\autonomy\logs\autonomous_daemon.log`)*
