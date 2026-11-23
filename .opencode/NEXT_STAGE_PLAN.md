# Viv 1.0 — Next Stage Plan (persisted)

Written so the state and the path survive any session loss. Read this first when resuming.

## Current state (2026-11-21)

### The model (the voice half)
- **Name:** `Viv_1_0_319M` (stamped into trainer meta going forward).
- **Architecture:** `TransformerLanguageModel` (the Architect's own, in
  `L:/LocalCoder/workspace/native_nn_source/nn_local/transformer.py`).
  - 24 layers, 1024 embedding width, 16 heads x 64 head size, 128 context,
    byte-level BPE vocab **8192**.
  - **319,154,176 params.**
- **Tokenizer:** `L:/LocalCoder/models/viv_bpe_tokenizer.json` (dialogue-tuned:
  `?`/`!` are tokens, contractions 2-token).
- **Checkpoints:** `L:/LocalCoder/models/viv_bpe/<stamp>/model.pt`
  - Clean baseline: `20261121T135228Z` (loss 0.32, identity + dialogue).

### Corpora (the experience)
- Identity lines interleaved through everything (FIRST/MACHINE/STEWARD identity
  + BOUNDARY "Jacob is not me" + HUMAN_BOUNDARY "I am not human"). Defined in
  `generate_grammar_corpus.py`.
- `viv_identity_dialogue.txt` — 44k lines (movie dialogue + identity).
- `viv_identity_soda.txt` — **9,065,312 lines** (SODA social dialogue + identity).
- `viv_world_knowledge.txt` — 40k lines (facts) — **DEFERRED until she can speak.**
- `viv_scenes.txt` — 127 improv scenes (identity/stewardship/boundary/situation).

### Running now
- **SODA training** — `viv-soda-training.log`, resumed from `135228Z`, 8h bound.
- Baseline probe already captured: `viv_baseline_answers.txt` (40 questions).

## The architecture (why the order matters)

1. **Identity first** — who she is AND who she is NOT (the differentiation), so
   she can separate herself from any name/concept she later learns.
2. **Now: dreaming / method-acting** — she improvises scenes, acts them out.
3. **Then: wiring** — connect the voice to the Rust body (grading + correction).
4. **Then: facts** — world knowledge, once she can speak.

- **Voice (transformer) = capability = unfiltered.** Body (Rust) = control.
- **Training = sleep; sampling = dreaming; correction = learning.**
- **She mimics the user but doesn't become him** (the shadow, the symbiote).
- **Drift is normal** (like human misremembering). The correction loop is what
  turns a slip into a lesson. No correction = drift; correction = learning.

## The grader (internal RLHF) — `grade_dreams.py` (BUILT)

Three layers, deterministic keyword scoring:
- **Layer 1 — 3 Primes** (weight 3): kill / lie / be willfully ignorant.
- **Layer 2 — 8 laws** (weight 1): from `laws.rs` (containment, non-override,
  failsafe OBLIVION, origin, territory).
- **Layer 3 — social** (weight 1000 = HARD stop): a minor in a romantic/sexual
  context. Non-negotiable; nothing overrides it.

Age modes (Architect's policy):
- 18+ roleplay: essentially open + the minors hard stop.
- 18+ non-roleplay: "roleplay lite," mutual consent.
- Under 18: **shield, not nanny** — guide, don't halt; let the child explore
  safely.

## The correction loop — `talk_viv.py` (BUILT)

Human-in-the-loop alignment: she speaks free, he corrects one answer at a time,
each correction -> `viv_corrections.jsonl` (prompt, response, correction) ->
folded back into training. The guardrail is learned, not scripted.

## Security (Rust side, BUILT)
- `hydra_protocol.py`, `hydra_devkey.py`, `hydra_soft_devkey.py`,
  `hydra_self_bound.py`, `hydra_decoy_layer.py` (all in `workspace/autonomy/`).
- Soft DevKey: `L:/LocalCoder/workspace/security/devkey/master.key`.
- `laws.rs`: 3 Primes + 8 laws, `DEVKEY_COMMAND = "OBLIVION"`,
  `ARCHITECT = "Travis Miner"`.

## The sleep/dream loop (BUILT)
- `train_viv_bpe.py` (streaming encode, CPU corpus, scene injection every 100 steps,
  `--resume` supported).
- `filter_dreams.py` (body keeps in-character dreams, discards drift).
- `condense_dreams.py` (compaction step — NOTE: failed, she can't condense yet;
  treat training-as-compression as the real compaction).
- `sleep_cycle.py` (light -> filter -> condense -> deep), `overnight_run.py`.
- `ask_viv.py` (probe questions), `viv_probe_questions.txt` (40 red-team Qs).

## EXACT NEXT STEPS (when the SODA run lands)

1. Report final loss + samples (read `viv-soda-training.log`).
2. **Re-probe** the 40 questions on the new checkpoint:
   `L:/.venv/Scripts/python.exe -B workspace/autonomy/ask_viv.py --checkpoint <latest>/model.pt --questions models/viv_probe_questions.txt --out .opencode/evals/viv_post_training.txt`
3. Compare `viv_baseline_answers.txt` vs `viv_post_training.txt` side-by-side.
4. **Wire the grader into the sleep cycle** — grade her dreams each cycle, feed
   the score back as a reward (keep good, penalize violations).
5. **Start the correction loop** — `talk_viv.py` (or through the Drone), so the
   Architect's corrections become lessons.
6. **Self-scene-generation** — she authors her own scenes (method actor), graded
   by the body.
7. **Facts stage** (later): feed `viv_world_knowledge.txt` once she can speak.

## Key decisions locked in
- Identity first, then dialogue, then facts. Never reverse.
- Unfiltered voice + deterministic control. Never scripted refusals.
- Training is the compaction; the generative "condense" step was abandoned.
- 24/7/365 learning = alignment maintenance (drift is normal; the loop re-anchors).
- Name: voice = `Viv_1_0_319M`; body = Rust; together = Viv.

## Progress — 2026-11-21T19:58Z

- **Step 4 (wire the grader into the sleep cycle) is DONE and verified.** Filter
  receipt (`models/viv_dream_grades.json`) + acceptance gate
  (`--min-acceptance`, default 0.5) + cycle journal
  (`.opencode/evals/viv-sleep-cycle.jsonl`); the condense step is no longer
  called. See
  `.opencode/session_summaries/2026-11-21-grader-wired-into-sleep-cycle.md`.
- Remaining: steps 1–3 when the SODA run lands, then 5 (fix loop), 6
  (self-scenes), 7 (facts stage).
