# AIOS Viv — Assembly Journal

Append-only engineering log for assembling Viv from the parts on L:. The Architect owns
intent; I own the convergent engineering. Every entry records action, target, result (or
exact error), and a receipt/hash where one exists. Historical entries are evidence, not
authority. Nothing here admits a model or claims learning without a Rust receipt.

## 0. Core systems (understood as of 2026-11-19)

### The body — the fork
- OpenCode fork -> Viv. Runs from source:
  `L:\LocalCoder\tools\bun\bun-windows-x64\bun.exe run --cwd L:\LocalCoder\tools\opencode-viv\packages\cli src/index.ts`
- CLI name `viv`; roots on `L:\LocalCoder\viv\{data,state,config,cache}` via `Start-VivOpenCode.ps1`.
- llama.cpp b12532 CUDA 12.4 at `L:\LocalCoder\tools\llama.cpp`; converter in `tools\llama.cpp\src\llama.cpp-b12532`.
- Deploy path for a trained adapter: convert LoRA -> GGUF, then `llama-server --model base --lora candidate`.
  (Conversion currently blocked: convert_lora_to_gguf.py asserts MTP layers > 0; this base has none.)

### The deterministic substrate
- UML_Calc (`L:\LocalCoder\UML_Calc\uml_engine.py`): base-52 letter calculus; brackets are the
  operators ([ add, { sub, ( neutral, > mul, < div ); compiles UML -> Python -> Rust -> ELF;
  verbal output. This is the "external calculator" — digits never learned.
- viv_code_topology.sqlite3: territory mesh (141,687 neurons, weight 1.0 flat — raw body),
  learned code graph (299 neurons, 884 synapses with pass_count, VERIFIED_PASS),
  function_bonds (36,586 weighted CAUSAL_IO_EFFECT edges), pruned_bonds_archive (31,412),
  word_num hub (top PageRank nodes), viv_uml_programs, symbolic_math_bridge
  ("1+1" -> "two" -> "one unit plus one unit equals two units").
- lexicon_ontology.db: 89,841 lemmas (1913 Webster core + Wikipedia emergent tail),
  3,336,109 cross-references, 81,087 emergent_curriculum_frames.
  GAP: relations all confidence=0.95 (placeholder); no typed/weighted sky--COLOR-->blue edge exists.
- INN: character tokenizer + LanguageEngine (recurrent CPU learner).
  Admitted checkpoint: learning/neural_runs/20261008T194732254495Z.

### The objective
- S_n = RSR x LTP x RLE, all in [0,1], ceiling 1.0, dormancy floor 0.45.
- RLE = correct x e^(-(a*energy + b*hops))   — physical telemetry (fixes the old loss-ratio RLE)
- LTP = min(1, durable_mastered / target)    — passed the gate AND survived consolidation
- RSR = identity continuity (Spelling+Speaking+Meaning acc / 3, or 1 - D(y_n, recon))

### Training lanes (evidence)
- Identity lane CLOSED as an adapter problem: steps x6, data +12 phrasings, capacity r16/20 layers
  — the denial reworded but never displaced; her reasoning channel held "role-playing as this character".
- Grounding lane: v6 0->6/19; v7 7/19 (mismatch 0/10 — no UNKNOWN in the data);
  v8 13/19 (mismatch 8/10 — abstention LEARNED; observed 5/9 — over-abstention).
  Grader v3/v6/v7 with gold control 20/20. Adapter r=16, layers 16-35, LR 1e-5,
  base E:\Viv_Sandbox\omnicoder_identity_20261118\base_hf_fp16.

## 1. Open items (next actions, in order)
1. Wire RLE to real telemetry (GPU power.draw + hop count) — replace placeholder RLE=1.0000.
2. Fix the two base-52 mappings (UML_Calc _c2v A-Z=1-26/a-z=27-52 vs viv_uml_programs b52('b')=2).
3. Calibrate cite/abstain balance (v8 over-abstention: observed 5/9).
4. Build typed+weighted fact edges (COLOR/ATTRIBUTE) from verification, replacing the 0.95 placeholders.
5. Reconcile the two RLE definitions in NN_record.md (loss-ratio vs physical).

## Standing rules
- Reads free; actions gated; nothing admitted without a Rust receipt.
- No access to the system drive. Everything on D:, E:, F:, L:.
- Trust by verified action, never by claim.
Entry 1 - 2026-11-19 01:05Z: RLE telemetry sources established
Action: located and sampled the real physical signals for RLE energy term.
Result:
- nvidia-smi LIVE: RTX 3060 Ti, 22.60 W draw / 200 W limit, 55 C, 26% util, 855 MiB. GPU idle (v8 finished).
- HWInfo LIVE (growing): L:\LocalCoder\Hardware\hwinfo.CSV, 1575.8 MB, last write 01:04:24Z. Full system signature: memory load, per-core VID ~1.2V, per-core clocks ~4500 MHz, per-core temps 22-64 C. This is the system-wide entropy term (CPU power, thermal, clock state).
- Corsair cooling STALE: latest corsair_cue_20261031_11_13_09.csv, 132.4 MB, last write 11/5. Logger has not written in ~2 weeks. FLAG for Architect, not restarted unprompted.
Conclusion: RLE energy term now has real live sources (GPU watts + system power/thermal). Next: define the composite (which HWInfo sensors fold into one normalized energy scalar) and pair with a measured hop count to produce a real RLE, not 1.0000.
Entry 2 - 2026-11-19 07:07Z: telemetry.py built, first full sample
Action: wrote L:\LocalCoder\workspace\autonomy\telemetry.py (index-based HWInfo sampler + nvidia-smi).
Result: energy_w = 116.3 (CPU 73.9 W + GPU 42.4 W). coolant 32.2 C @ pump 2485 RPM (Corsair loop LIVE via HWInfo direct sensors, despite stale CUE log). core temp 41 C, GPU 59.3 C / hotspot 71 C. nvidia-smi GPU 54.49 W vs HWInfo GPU 42.4 W differ only by sampling instant; composite uses HWInfo for a single consistent source.
Verification: all 8 sensor indices matched expected header-name fragments (no mismatch key emitted).
Next: fix alpha/beta coefficients and measure hop count for an actual task, then compute a real RLE = correct * exp(-(alpha*energy + beta*hops)).
Entry 3 - 2026-11-19: K.I.S.S. pivot - the failure loop is the primitive
Course-correction: rle.py measured marginal_w = 0.0, energy_j = 0.0 on a 95 ms task.
Telemetry before the loop existed = over-engineering. telemetry.py and rle.py are parked
(useful later, not now). The primitive is tell -> fix -> redo with redundancy.
Built failure_loop.py (~40 lines, no telemetry, no coefficients):
  tell  - ledger records each wrong pick and the correct answer
  fix   - punish the wrong path, reward the right one
  redo  - retry with the strongest path until a mastery streak
  redundancy - every candidate stays present; the strongest rises, weak ones sink
Result (scrambled 26-letter mapping, judge is the only truth): converged in 4 episodes,
104 trials, 25 failures recorded. The ledger is the tell: e.g. symbol 'a' picked 'a',
correct 'd' -> punished, rewarded 'd', redone. Dynamic/emergent: started picking 'a'
everywhere (zero weights), the true paths rose by reinforcement, wrong paths sank.
This loop, not the efficiency metric, is the foundation everything else hangs off.
Entry 4 - 2026-11-19: CARMA read + pragmatic bridge to generalization
CARMA = Cognitive Adaptive Recursive Memory Architecture (STM/LTM consolidation with
compression, semantic clustering, fragment fusion, retrieval). Live workspace/aios_rebuild/
carma_core/carma_core.py is a STUB (vector store + cosine retrieval + 24h decay). The full
design lives in source_baseline_v4/source_tree_v4/carma_core/: compressor.py (semantic/
temporal/hierarchical), clusterer.py, mycelium_network.py, meta_memory.py, fractal_cache.py,
integrity_verifier.py, fragment_decayer.py, rust_carma. Note: compressor semantic mode is
concept-set DEDUP, not rule abstraction - so even the full tree does not yet generalize.
Pragmatic inventory: HAVE failure loop (tell->fix->redo, redundancy) + base-52 (letters are
numbers). DON'T KNOW how to abstract a memorized table into a function that answers unseen
input. ADDED the missing primitive: a hypothesis space. rule_learner.py = version-space
learning: hold all 312 invertible affine maps answer(i)=letter[(a*i+b) mod 26]; each observed
example eliminates disagreeing hypotheses; the survivor is the rule.
Result: 4 examples -> 1 survivor [(7,3)]; held-out index 26 -> 'd' (rule-learner) vs 'a'
(memorizer). generalizes=True. The SAME loop shape (redundancy + reward/punish + redo) goes
from memorizing 26 pairs to learning 2 numbers, by adding only the hypothesis space.
Next anchor (do NOT pre-build): scale this - larger alphabet, non-affine rules - and find
where the hypothesis space breaks. That break is the next thing to add.
Entry 5 - 2026-11-19: reuse found the real generalization primitive; runtime is the break
Correction: rule_learner.py was a reinvention. Semantic search (look-first-reuse) found the
existing primitive: autonomy/viv_causal_function_explorer.py (13.5 KB) - write a function,
run in container, infer input->output invariants, PREDICT THE HELD-OUT OUTPUT, verify; bond
AST concepts to effects in function_bonds, commit to viv_causal_discoveries; on mismatch,
append to failure ledger with backward blame. That is generalization-by-heldout with
tell->fix->redo already wired. Dependencies all present: viv_code_learning_loop.py (17.9 KB),
viv_path_weights.py (12.7 KB).
The real break is RUNTIME, not design: it executes in the viv-vm Docker container, and the
Docker daemon is DOWN (failed to connect to npipe dockerDesktopLinuxEngine). So the
generalization loop is fully coded and wired but cannot run until the Body is up.
Next anchor: bring up Docker / viv-vm (the deterministic Body). This is the enforcement layer,
so it needs the Architect's go before I start it. rule_learner.py kept only as a reference of
the one concept (hypothesis-space pruning), not as a system component.
Entry 6 - 2026-11-19: the Body is BUILT and on HOLD for ONE named invariant
Read docs/WSL_BODY_CONTAINMENT.md. The deterministic Body is not missing - it is a pinned
Docker image aios-body-runtime:0.2.6-mount-table-attested (sha256 ee4896ad...), built across
6 iterations (0.2.0 -> 0.2.6), each adding a containment check and preserving negative evidence.
Verified in-container: UID 10001, CapEff/Bnd=0, NoNewPrivs=1, read-only root, loopback-only,
256MiB / 1 CPU / 32 PIDs, no GPU/device nodes, 10 bounded tmpfs paths, mount-table allowlist.
Live pinned call: 19/19 core bindings, S_n=1.0, fresh HWiNFO/Corsair sensors (0.6s, 3 thermal
samples). Tests: 48 focused Python, 15 Body Rust, 72 security-core Rust, all passing.
The single remaining HOLD: PrivacyCore does not prove process-wide I/O mediation. Plus three
named residuals: trusted sensor/broker provenance, Mind-side denial, bounded INN candidate path.
Explicit instruction in the doc: do NOT claim learning resumed while HOLD, do NOT change
HIVE_LOCK_MANIFEST.json / PrivacyCore allowlist / candidate admission rules.
So the gap of engineering is NOT "build a Body" - it is "verify PrivacyCore process-wide I/O
mediation (and the three named residuals) so the gate can move off HOLD". Docker daemon is also
DOWN (mechanical), but the HOLD is the authoritative state and it is independent of the daemon.
Next: read PrivacyCore (one of the 19 cores) to determine exactly what process-wide I/O mediation
coverage is missing, then fill that specific gap - not reinvent the Body.
