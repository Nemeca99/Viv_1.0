# Full AIOS rebuild gap evidence — 2026-09-30

This note records the current template-composition and full-manifest assembly
experiments, including what they prove and what remains unestablished. All
outputs are isolated under `rebuild_runs/`; the inspected source and live D:
Viv tree were not modified.

## Full-manifest assembly and verification

Run `rebuild_runs/full_manifest_rebuilds/full-horizontal-20260930T043936799967Z-0abeca24`
completed with status `PASS_SOURCE_PRESERVING_FULL_MANIFEST_ASSEMBLY`. Viv
returned a complete plan that Rust admitted; the graph covered 19 cores plus
workspace support and the NumPy/CuPy bridge. The candidate contains all 3,641
files from the prepared source-derived manifest (42,026,529 bytes), with no
missing, unexpected, or mismatched paths. Python syntax validation checked
1,584 files with zero errors and six explicit exclusions. The CuPy/Rust bridge
receipt passed shape, dtype, finite/decreasing-loss, and Rust-acceptance checks.

The full pytest suite ran against a disposable copy: 458 collected, 440 passed,
18 skipped, zero failed. The assembled candidate itself remains unchanged and
matches the manifest after the test run. Its logs and receipts are linked by
`post_run_validation.json` and `post_run_validation.sha256` in that run
directory.

This is a complete hash-verified assembly route, not a semantic self-rebuild:
the source was a prepared transformed candidate, `model_generated_source` is
false, and `swarm_generation_count` is zero. Viv planned ordering; Rust
performed bounded copy and checks. No live D: Viv or F: AIOS source was
modified.

## Whole-kernel and Dream heartbeat integration

The earlier Dream vertical-slice evidence had only 11 of 13 cores bound because
that run's environment lacked `psutil` and NumPy. The current LocalCoder proof
environment has both; a fresh kernel probe binds all 13 cores. Regression tests
cover all-core binding and verify that one heartbeat tick passes recent
activity/busy state to the same Dream instance. The test and dependency files
are `test_main_core_integration.py` and `requirements-kernel.txt`; test output
will be recorded under `main_core/evidence/`.

## What now works

- A hash-pinned catalog runtime reads the 11,395 exact source templates across
  19 cores and can stamp a selected top-level source span into a new candidate
  file. It parses, hashes, and copies; it does not import or execute AIOS code.
- The Rust control binary validates the plan, fixed tool allowlist, menu/source
  hashes, per-core ownership, task snapshots, and generated candidate files.
- An all-core contract fixture dispatched one deterministic task per core and
  produced 19 syntax-valid stamped artifacts. Its receipt is
  `rebuild_runs/full_catalog_rebuilds/contract-fixture-20260930T034546205640Z-14ba9668/run_receipt.json`.
  This fixture used no Mind or worker model generations and is explicitly not
  an AIOS replacement.
- Plan admission now has regression coverage for generic rationales and
  position collapse. Five Rust admission tests and six Python catalog-runtime
  tests pass; Ruff check and format checks pass.

## Live Mind evidence

Six Qwen3 8B calls received the 19-core menu (8,194 prompt tokens per call).
Three stopped at the output limit with invalid JSON. Three returned valid JSON
but were not admitted. Raw requests and transcripts are retained in their
individual run directories:

| Run | Result |
|---|---|
| `aios-all19-20260930T0338060413Z` | Invalid JSON; `done_reason=length`, 2,400 output tokens. |
| `aios-all19-mind-20260930T0346295132Z` | Invalid JSON; `done_reason=length`, 1,400 output tokens. |
| `aios-all19-mind-20260930T0350476679Z` | Valid JSON; selected menu keys `T1` and `T2` for every core; held for duplicate declarations before dispatch. |
| `aios-all19-mind-20260930T0355389919Z` | Valid JSON; selected `T1` for every core and intent described catalog generation, not a full AIOS candidate; held. |
| `aios-all19-mind-20260930T0400056103Z` | Invalid JSON; `done_reason=length`, 900 output tokens. |
| `aios-all19-mind-20260930T0402339961Z` | Valid JSON; selected `T1` for all 19 cores, generic reasons did not name selected symbols, and intent described catalog generation; held before dispatch. |

The latest plan was replayed byte-for-byte in a fresh admission diagnostic run.
Rust held it with `Mind selection is collapsed onto the same menu position
across most cores`; the hold receipt reports zero partial candidate files,
source unchanged, and source code not executed. Replaying did not call the
model. The original request, raw response, menu, and plan remain preserved in
the originating run directory.

## What this establishes and does not establish

The coordinator can reject invalid plans safely, and deterministic workers can
stamp verified source spans across all cores. The live Qwen Mind did not produce
an admitted full-rebuild plan in these six attempts. Valid JSON alone was not
treated as planning success.

The later full-manifest assembly run admits a complete plan and executes the
assembly tasks, but it does not supersede the template-authoring gap: it copies
already prepared source. The central autonomous rebuild claim remains open.

## Deterministic template toolbox candidate proof

The legacy template builder, runtime, fixture templates, and tests were copied
from the moved `D:\LocalAi\Continue\Viv` tree into `template_toolbox/`; the
moved tree was read-only. The local Rust clone was rebuilt as a candidate
extension and its general Law 7 mutation root was narrowed to
`template_toolbox/sandbox/`. Regression checks allow JSONL audit append inside
that candidate sandbox and deny writes to the old Viv sandbox, D:, and
LocalCoder sibling paths. The Rust Python source-write capability remains
compiled closed.

`template_toolbox/verify_candidate.ps1` is the repeatable proof command. Run
`template-toolbox-20260930T051125Z` recorded 52/52 Rust unit tests, 40/40
Python toolbox tests, a valid hash-pinned Rust bridge, and ten deterministic
isolated fixture executions. The protected source, generation pointer, and
production generation state remained unchanged. The two-template Mind-shaped
selection produced a dry-run plan with stable SHA-256 identities; publication
was held by the closed Rust Python-write capability, with
`writes_performed=false`. The isolated fixture used a disposable test adapter
only after recording the Rust denial. Its manifest is
`template_toolbox/sandbox/code/audit/verification_runs/template-toolbox-20260930T051125Z/verification_manifest.json`
with SHA-256
`d7b18223b6072c4e9b4e3b102203a6a200504f876b62d9a68ea465c09e2fff0b`.

This establishes deterministic selection, exact template assembly, and the
candidate write boundary. It does not produce a useful AIOS module, add
Mind-authored variable binding or a dependency graph, admit template registry
changes, or open Python source writes. Those remain separate implementation
gaps; the closed writer is not bypassed to make the demo appear complete.

More fundamentally, the current plan contract requires exactly one selected
template per core. It cannot express a multi-file subsystem rebuild, generated
variable values, task ordering/dependencies, evidence requirements, or a
verification plan per change. The current candidate output is a collection of
isolated snippets, not working AIOS modules. The next implementation gap is a
bounded hierarchical rebuild-plan contract that can represent those tasks and
their dependency graph while keeping Mind tool approval and Rust admission
separate. Its candidate artifacts must still be built and tested independently
before calling the path an autonomous AIOS rebuild.
