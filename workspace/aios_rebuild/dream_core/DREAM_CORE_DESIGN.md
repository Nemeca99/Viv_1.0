# AIOS Viv Dream Core

Dream has two distinct jobs: consolidate/replay recent episodic memory and
prepare candidate examples for later learning. This implementation performs
deterministic memory grouping and emits hash-linked observed turn pairs. It
does not assert that a clustered answer is correct, true, or aligned.

This follows the older AIOS manual's background consolidation idea, while
using the current AIFL contract's provenance and admission boundary. The older
manual describes intended behavior, not proof that its historical code worked.
The 2026 paper *Language Models Need Sleep* also distinguishes memory
consolidation from synthetic-data dreaming and evaluates continual-learning
effects; that is useful precedent, not evidence this small local implementation
will improve Viv.

## Current behavior

- `main_core.py` calls `DreamCore.tick()` from its 1 Hz heartbeat.
- Five quiet minutes are required by default; a cycle cooldown prevents repeated
  work. Each cycle processes at most 32 records.
- The only default inputs are `memory/chat_transcript.json` and
  `memory/long_term_raw_dump.json`. Sources remain unchanged.
- Similar turns are grouped by role. Without a provider, the recorded mode is
  `token_jaccard_fallback`; callers may inject an embedding provider to use
  finite, equal-sized float32 vectors with cosine similarity. No embedding model
  is loaded by default, and the receipt records which mode actually ran.
- Adjacent user/assistant pairs are written to `state/candidate_turns.jsonl`.
  IDs include source turn IDs and source SHA-256 values, so unchanged sources
  are idempotent across cycles. A pair is eligible only when both timestamps
  are valid timezone-aware values older than the 24-hour freshness window;
  missing or malformed timestamps are excluded, and filtered turns are never
  compressed together to create a false adjacency.
- `state/consolidations.jsonl` is append-only. `state/status.json` is an atomic
  latest-state view.
- Every candidate is `PENDING_QUALITY_CORRECTNESS_TRUTH_REVIEW`; the heuristic
  adapter target is only a suggestion. Candidate output is not an admitted
  training dataset.
- `train_3lora_stack.py --train-dream-candidates <jsonl>` is a separate,
  explicit training path. It accepts only rows marked `ADMITTED_BY_ARCHITECT`
  with quality, correctness, and truth each `PASS`, evidence references, and an
  explicit adapter target. It stages hashed dataset files and writes newly
  trained adapters to a run-specific candidate directory. It does not promote
  them to the active stack. The default 3-LoRA training path is unchanged.
- The heartbeat never calls a model, loads a LoRA, or trains. No synthetic
  self-play generator or judge is wired yet: current Dream candidates are
  observed transcript pairs. Therefore this proves memory replay, candidate
  provenance, admission gating, and isolated trainer routing, not autonomous
  synthetic curriculum learning or continual improvement.

## Heartbeat integration boundary

`UnifiedAIOSKernel.notify_activity()` resets Dream's quiet timer. The existing
short-term-context and task-archive entrypoints call it; a future request
ingress must call it before work that does not pass through those methods. At
process startup, the kernel waits for Dream's own five-minute idle window before
a first cycle.

## Research distinction

Biological replay literature treats replay/consolidation as an active research
question with multiple proposed functions. Modern LLM sleep work separates
memory consolidation from model self-improvement and evaluates forgetting as
well as gains. Therefore this Dream Core only establishes a reproducible data
path; it does not claim biological equivalence or recursive self-improvement.

References:

- Behrouz et al., *Language Models Need Sleep: Learning to Self-Modify and
  Consolidate Memories* (2026), https://arxiv.org/abs/2606.03979
- *The evolving view of replay and its functions in wake and sleep* (review),
  https://pmc.ncbi.nlm.nih.gov/articles/PMC7898724/
