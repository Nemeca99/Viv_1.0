# AIOS Viv rebuild workspace

This is the isolated LocalCoder rebuild target. The inspected source is
`F:\AIOS_Clean`; it remains read-only. Candidate transformations, tests, and
receipts are kept on `L:`. This workspace is intended to rebuild the whole
AIOS, not stop at a narrow vertical demo. The present evidence establishes a
full-source candidate and broad regression run; it does not yet establish that
Viv can autonomously redesign and rebuild the system.

## Current full-source candidate

`source_baseline_v4/source_manifest.json` covers 3,641 files (42,557,675
bytes) across all 19 cores, including the Streamlit vendor trees. The
source-derived candidate and test copy are under
`rebuild_runs/full_horizontal_candidate_v5/`. Candidate-only transformations
are recorded in `streamlit_vendor_normalization_receipt.json`; the source tree
was not changed.

The latest candidate verifier reports:

- 3,641 expected files and 3,641 candidate files, with no missing, extra, or
  hash-mismatched files.
- 1,584 Python files syntax-checked, zero syntax errors, four existing
  invalid-escape warnings, and six declared compile exclusions (five
  cookiecutter templates and one intentional syntax-error fixture).
- 1,272 declared candidate transformations, including vendor bootstrap cleanup
  and three local source-link materializations. Each is tied to source and
  candidate hashes.

The full suite ran against a disposable copy of this candidate:
458 collected, 440 passed, 18 skipped, zero failed. This is regression evidence
for the candidate suite, not proof of all AIOS behavior or correctness. The
suite's breakdown categories total 494 because categories overlap; 458 is the
actual collected test count.

## Exact-source function template catalog

`rebuild_runs/full_horizontal_candidate_v5/template_catalog_v2/` contains
11,395 exact function, async-function, and class spans indexed from 1,548
Python files across the 19 cores. The catalog records source path and hash,
line span, qualified name, parameters, direct call names, and content digest.
Independent verification matched all 11,395 entries. The builder parses source
but does not import or execute it, and it does not synthesize code. This gives
the Mind/swarm pipeline a broad template substrate. `template_catalog/runtime.py`
now verifies catalog and source hashes and stamps exact top-level spans;
`hive_control/src/bin/full_aios_catalog_rebuild.rs` admits hash-bound Mind
selections and dispatches deterministic per-core stamping tasks. An all-core
contract fixture passed across 19 cores. See
[`FULL_REBUILD_GAP_EVIDENCE_2026-09-30.md`](FULL_REBUILD_GAP_EVIDENCE_2026-09-30.md)
for the live Qwen attempts, hold receipts, and current limits.

## Dream Core candidate

The workspace Dream implementation supports an injected embedding provider
with cosine similarity and records an explicit token-Jaccard fallback when no
provider is configured. It requires valid timezone-aware timestamps at least
24 hours old, preserves adjacency across filtered turns, and leaves candidates
pending review. The focused behavior tests pass 7/7; two AIOS contract tests
cover embedding-mode declaration and freshness immunity. No default embedding
model, synthetic self-play judge, or automatic training loop is active.

The kernel integration tests now bind all 13 discovered cores when the
declared NumPy and `psutil` runtime dependencies are installed. A one-tick
heartbeat check confirms activity marks the same Dream instance busy. Install
`requirements-kernel.txt` before running the kernel integration test.

## Full-manifest assembly proof

`run_full_manifest_rebuild.py` completed an admitted Mind plan and Rust task
graph across 19 cores and 3,641 hash-pinned files. Rust assembled the prepared
candidate and verified the NumPy/CuPy bridge; an independent verifier found
no missing, unexpected, or hash-mismatched files and no Python syntax errors
among 1,584 checked files. The 458-test suite passed on a disposable copy
(440 passed, 18 skipped, zero failed). This validates the route and candidate
integrity; the assembled files were copied from the prepared source-derived
candidate. Mind generated no replacement source and the Swarm performed zero
code-generation tasks.

## Local deterministic template toolbox candidate

The legacy deterministic template builder, its two fixture templates, and its
tests are copied into `template_toolbox/` as a LocalCoder candidate. Its cloned
Rust control policy permits mutations only below
`template_toolbox/sandbox/`; the autonomous Python source-write capability
remains compiled closed. `template_toolbox/verify_candidate.ps1` rebuilds the
candidate Rust extension, runs Rust and Python tests, checks bridge integrity,
and records a structured verification manifest plus hashed logs under the
candidate sandbox.

The 2026-09-30 run passed Rust formatting, 52 Rust tests, and 40 Python tests.
The registered two-template request produces stable hashes and a dry-run plan,
but publication correctly ends in `HOLD_SECURITY`; no generation or active
pointer is written. Ten isolated fixture executions were deterministic and
left protected state unchanged. This proves candidate toolbox mechanics and
the closed write boundary. It does not prove a model-authored plan, a useful
AIOS module rebuild, or permission to open source writes. See
[`FULL_REBUILD_GAP_EVIDENCE_2026-09-30.md`](FULL_REBUILD_GAP_EVIDENCE_2026-09-30.md)
for the receipt path and remaining integration gaps.

## What remains unestablished

- **Whole-system autonomous rebuild:** the candidate is mostly source inherited
  from AIOS; the recorded full route copied/stamped prepared source. No Qwen
  Mind authored the full rebuild plan or code, and no AIOS-wide semantic rewrite
  has been shown.
- **Integrated Mind/Rust/Python/NumPy/CuPy execution:** the earlier assembly
  proof exercised a Mind-plan-shaped route, checksummed Rust task graph,
  deterministic CPU file-copy worker, Python checks, a NumPy/CuPy operation
  (reported max error 0.0 for that operation), and Qwen3-TTS. It proves those
  components could be assembled for that run, not autonomous task decomposition
  or broad semantic correctness.
- **Template-driven authoring:** the 11,395 exact templates are cataloged and
  verified, and exact-span stamping is wired through Rust. Mind has not yet
  produced an admitted all-core plan. The present contract allows one template
  per core and cannot represent multi-file changes, variable binding, or a
  useful rebuild dependency graph; outputs are isolated snippets, not working
  AIOS modules.
- **Durable snapshot encryption:** the current Rust proof used OS CSPRNG
  entropy for in-process authenticated snapshots, but the master key and index
  were memory-only. Restart-persistent, Mind-only key custody and swarm-scoped
  encryption remain unimplemented.
- **Model-backed stateless swarm and human-agent routing:** one-turn CPU model
  tasks, external/human agents, bounded wait/resume, and their audit receipts
  are not yet integrated into the full rebuild route.
- **Foreman continuity:** the current fresh snapshot has training, promotion,
  and deployment authority closed; the snapshot reports missing Rust security
  extension integrity. No live D: Viv runtime was modified.
- **LoRA training evidence:** three binary adapters load together on the RTX
  3060 Ti and generate sample outputs. The current receipt verifies runtime
  composition and adapter hashes; it does not independently prove the
  historical training process, behavioral gains, or held-out quality.
- **Dream-to-training loop:** Dream emitted 13 transcript-derived examples
  pending review. No model-generated synthetic curriculum, candidate
  admission, new Dream adapter training, or promotion has been demonstrated.

The full-system goal remains active. The evidence so far shows broad source
coverage and regression health, while the central RSI claim—Viv using the Hive
to inspect, plan, modify, verify, and iteratively improve all AIOS cores—still
needs an integrated, model-authored rebuild run with durable receipts and
independent checks.
