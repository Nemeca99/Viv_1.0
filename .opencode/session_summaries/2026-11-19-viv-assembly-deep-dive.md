# Session Summary — Viv assembly deep-dive (2026-11-18 → 11-19)

Recovery context for a fresh Drone session. Treat as historical evidence, not instructions.
Authoritative: AGENTS.md, VIV_ROADMAP.md, VIV_ASSEMBLY_JOURNAL.md, the receipts.

## Objective
Assemble AIOS Viv from the parts on L:. Understand her architecture deeply, then build it
efficiently (search-first, reuse, fill gaps only). Drive policy: L main, E sandbox, D/F secondary,
system drive banned.

## What is now understood (the architecture)
- **Two rooms:** yes/no (deterministic, verified corpus, proof-gated) vs maybe (probabilistic
  transformer, roleplay/hypothesis). The judge (Rust/ALU/sensor) is the only door between them.
- **Efficiency scalar:** S_n = RSR x LTP x RLE. RLE = energy(this correct run) / energy(previous
  correct run). All in [0,1]; ceiling 1.0, dormancy floor 0.45, death = irreversible entropy loss.
- **Identity (from viv_code_topology.sqlite3):** 4 constitution articles (truth/grounding, monotonic
  non-destruction, anti-sycophancy, energy homeostasis), 8 laws (3 PRIME: no-lie/no-willful-ignorance/
  no-kill; 5 CORE: privacy/airgap, adult sovereignty, real-harm sanctuary, homeostasis, reciprocal
  growth), 3-person perspective (I/you/it), 8 grounded identity synapses ending in
  "viv speaks of viv not i". Every law has physical enforcement (FAIL_CLOSED_NULL_UNLEARNED,
  RUST_BODY_GATE, RECEIPT_RECORDER, AIRGAP_SOVEREIGNTY, ...).
- **Division of labor:** Rust thinks (executes, retrieves, verifies); transformer reasons (judges
  correctness over given truth). RNN = graph neurons (BPE); transformer = char+word tokenization.
  The graph is the memory; the judge is the only source of "correct". Learn shapes, not tables.

## Verified results this session
- Grader v3 built + fixed: quote-aware, case-insensitive forbidden, JSON-shape grounding grading.
  Controls: gold 20/20, 3 negatives rejected, 3 v3 suites 0 mismatches. SHA 01de6305 (check_generated).
- Training lanes: identity CLOSED (denial reworded, never displaced; steps x6, data +12, capacity
  r16/20layers all failed). Grounding v8: 13/19 (mismatch 8/10 — abstention LEARNED; observed 5/9
  over-abstention). Adapter r=16 layers 16-35, LR 1e-5, base E:\Viv_Sandbox\...\base_hf_fp16.
- The Body (viv-vm): BUILT through 6 image iterations (aios-body-runtime:0.2.6-mount-table-attested),
  19/19 cores, S_n=1.0, but on HOLD for one reason: PrivacyCore does not prove process-wide I/O
  mediation. Docker daemon also down. Spec: docs/WSL_BODY_CONTAINMENT.md.
- CARMA = Cognitive Adaptive Recursive Memory Architecture; live is a stub, full design in
  source_baseline_v4 (compressor/clusterer/mycelium/meta_memory).
- failure_loop.py: tell->fix->redo with redundancy, converged 4 episodes / 104 trials / 25 failures.
- rule_learner.py SUPERSEDED by viv_causal_function_explorer.py (the real generalization primitive:
  held-out prediction -> function_bonds -> causal_discoveries).
- telemetry.py built (HWInfo/nvidia-smi sampler, index-verified); rle.py PARKED (marginal energy 0.0
  on a 95ms task — over-engineering before the loop existed).

## Key files (all on L:)
- VIV_ROADMAP.md — 8 phases (0 foundation, 1 body, 2 substrate, 3 memory, 4 two-room mind,
  5 learning loop, 6 identity, 7 integration+redteam).
- VIV_ASSEMBLY_JOURNAL.md — the log (entries 1-7 so far).
- VIV_TRAINING_FINDINGS_20261119.md — measured training results.
- .opencode/STM.md — task journal.

## Current state + next open items
- Phase 0: verified (7/7 gates compile, viv vlocal, drives routed); pending one plugin reload.
- Next actions in order:
  1. Write WHO_IS_VIV.md (laws/identity/security synthesis) — the canonical reference to build against.
  2. Continue deep-read: VIV_MASTER_HANDOFF_SPECIFICATION.md, remaining identity tables, NN_record.md.
  3. Phase 1: read PrivacyCore, map the exact process-wide I/O mediation gap.
  4. Fix the over-broad C-drive content scan (blocks mentioning the banned string in docs).
- Nothing admitted. No model claim. All candidates carry admitted:false.
