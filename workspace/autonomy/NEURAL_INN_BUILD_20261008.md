# Own neural INN: first grounded language and action checkpoint

## What is built

- `L:\LocalCoder\INN\inn\language.py`: own UTF-8 byte tokenizer, token/position embeddings, causal next-token head. Farm action/legality heads and language share the existing INN attention blocks. No pretrained language weights or inference template fallback.
- `L:\LocalCoder\workspace\autonomy\train_neural_inn.py`: bounded deterministic CPU training, Rust-grounded examples, 12-tick action targets, parent retention, candidate selection, reserved language prompts, final frozen probes, checkpoint/optimizer continuity and hashes.
- `L:\LocalCoder\workspace\autonomy\verify_neural_inn.py`: reconstruct language targets from Rust and reproduce final farm results before admitting a candidate.
- `inn_hive.py`: actual neural proposal and generated text reach the model Queen after admission and live factual checks. Rust retains execution. Legacy policy remains available if admission, legality or description checks fail.
- Neural attempts use two CPU threads, 500 updates and 1200 collection steps. The existing Hive launches one attempt initially and then every 250 completed lessons. Overlapping trainers are excluded by the existing OS file-lock contract.
- After a measured farm regression against the same admitted neural parent, the next attempt doubles the action-value retention coefficient (capped at 10). This changes one training variable and records the failed run and coefficient in its protocol; it does not relax acceptance gates.
- `neural_live_examples.json`: deduplicated verified replay facts. Queen prose remains in original receipts, with teacher-response hashes, and is not automatically trusted as factual language supervision.
- Streamlit distinguishes neural generation, legacy updates, candidate training and evaluation.

## Selected checkpoint

Run: `L:\LocalCoder\workspace\autonomy\learning\neural_runs\20261008T194732254495Z`

Checkpoint SHA256: `8939f3abae351b57b9215b24c6a05e63f76dff26a50fe04defb4d0ee00106ce4`

The selected checkpoint has 500 optimizer steps. Later 1500/2000-update candidates regressed; selection retained the earlier checkpoint instead of the last weights. Their validation failures are preserved. The final gate and `recheck.json` reproduce:

| Probe | Neural harvests | Parent harvests | Neural decays / invalids | Parent decays / invalids | Neural bank | Parent bank |
|---|---:|---:|---|---|---:|---:|
| 5000 ticks, default durations | 604 | 598 | 0 / 0 | 0 / 0 | 82 | 103 |
| 5000 ticks, till decay 4, seed/water decay 3 | 604 | 598 | 0 / 0 | 0 / 0 | 82 | 103 |

Reserved language prompts: 20/20 exactly correct, regenerated from Rust on active plot 41. The training corpus did not contain these prompts. The known global IDLE prompt is excluded from claims about previously-unseen prompts. Inference also learns that IDLE description, and live receipts record its correctness independently.

These are narrow outcomes. Harvest count improved while ending bank decreased. This does not establish improved economic management or general language understanding. Both final duration settings yielded identical outcomes; they do not establish two independent kinds of decision improvement.

## First real automatic continuation

The Hive launched a bounded CPU attempt at lesson 900, run `20261008T200508198408Z`. It resumed the selected 500-step optimizer, consumed 21 verified live facts, and advanced to 1000 optimizer steps. Language remained 20/20. Farm results regressed (555 harvests / 58 decays on default durations; 596 / 12 on changed durations), so the new checkpoint was rejected. The admitted SHA above remained unchanged. This verifies the training/rejection loop, not continual improvement. The next attempt increases retention rather than repeating the same settings.

## Failures that guided the changes

1. First small corpus: near-zero training loss but 0% exact language validation after plot identity/prefix length changed; farm regression. Expanded real plot identities and Rust-verified tool coverage.
2. Revised corpus: correct reserved descriptions and retained farm results, but no strict farm gain. Kept gate failed.
3. Longer legacy-simulator trial: queued HARVEST actions reached BARREN after decay. Training looked ahead with one-action commits while evaluation used four-action plans. Corrected both to the deployed Hive contract. A split assertion also caught the duplicated global IDLE prompt; final unseen scope now explicitly separates that known prompt.
4. Settings getter signature prevented the automatic trainer from launching. Extended the existing Store getter with an optional default, preserving prior behavior; checked the real worker after reloading.

## Commands and reversibility

`L:\LocalCoder\Train-INN.ps1` performs a bounded attempt using `L:\.venv\Scripts\python.exe`. It resumes the admitted neural checkpoint if one exists, includes verified live replay, and compares against that neural parent. Failed candidates cannot become parents.

The existing Viv CLI accepts `!auto inn legacy` to disable neural proposals and future neural training, or `!auto inn neural` to re-enable the admitted proposal path. `!auto inn` reports settings. The model Queen stays on GPU; INN learning/inference stays on CPU. No packages or external models were installed.

## Remaining language work

This checkpoint generates short farm legality descriptions from structured prompts. It does not provide open-ended conversation, a trained sequence-memory mechanism, learned natural-language instructions, verified Queen explanation distillation, or general coding ability. Queen weights are not updated by farm verdict counters. Legacy online TD updates and neural optimizer updates are separate and labeled separately.

Next language curriculum must add ordered observations and verified consequences, followed by instructions and independently checked teacher examples. Keep the current narrow language/farm retention suite when expanding it.
