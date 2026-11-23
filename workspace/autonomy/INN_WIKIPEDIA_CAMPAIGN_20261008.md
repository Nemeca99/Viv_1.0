# Resumable Wikipedia campaign

Run from `L:\LocalCoder`:

```powershell
.\Train-INNWikipedia.ps1 -Articles 64 -Updates 1000 -Segments 10
```

This executes at most ten bounded commands. Each continues the experimental campaign's saved weights, Adam moments, RNG, corpus and chunk position. It does not restart the original sentence pilot. A command stops at its update budget, completion of its prepared segment, or the 600-second training-loop ceiling. Preparation and verification add time outside that ceiling. If a segment has more chunks than the command can present, the next command continues the same segment. Once complete, it reads later files. `Articles` controls newly prepared segment size, not a total dataset limit.

Source: `F:\AI_Datasets\wikipedia_deduplicated`. Code, Python environment, optimizer, checkpoints and bounded corpus caches remain on L:. The reader traverses batch folders and article files, extracts text across sections, splits long prose at word boundaries, and preserves original/reduced pairs with deletion offsets. Redirects, invalid UTF-8, files above 8 MB and files without usable prose are recorded exclusions. This is not lossless ingestion of every byte. Vocabulary grows from training text only, using the Architect's universal character IDs with compact embedding rows; existing weights and Adam moments are remapped by character identity. No word/BPE phase has been claimed.

## Atomic continuation

`learning/wikipedia_campaign/head.json` commits checkpoint SHA, pending corpus SHA, chunk offset, dataset file cursor and cumulative exposure together. An interrupted command before commit leaves the previous head intact. Rejected candidates are retained and never become parents. Full checkpoints preserve the optimizer state. SQLite tracks exact original/reduced target ownership across splits. Initial pilot exposure and reused development evaluations mean these scores are not a fresh generalization acceptance test.

Prior supervised farm-description examples have dedicated alternating replay updates. A deterministic reservoir of 256 previously presented Wikipedia chunks supplements new-text batches. The continuation gate requires at least 95% of the 80 reserved prior descriptions, finite training, unchanged parent/admission hashes and identical checkpoint reload. This gate permits isolated continuation, not live farm promotion or a claim of fluent knowledge. The structure restoration pass remains pending a separate generation-quality evaluation.

## Actual runs

| Run suffix | Optimizer steps | New chunks presented | Prior exact descriptions | Result |
|---|---:|---:|---:|---|
| 225157349620Z | 2000 → 3000 | 4000 | 80/80 | Committed |
| 225324687121Z | 3000 → 4203 | 4810 | 67/80 | Rejected; head unchanged |
| 225452429624Z | 3000 → 4203 | 4810 | 79/80 | Corrected replay; committed |
| 225555996120Z | 4203 → 5203 | 4000 | 76/80 | Next article segment; committed |

The rejected replay schedule mixed prior facts and Wikipedia reservoir into one index stride. The correction kept prior examples in their own alternating updates, indexed by replay-update count, and added reservoir examples to new-text batches. It resumed the last accepted parent rather than the failed checkpoint.

Current committed exposure: 12,810 training chunks; one completed 64-article segment and 4,000 chunks of the next 64-article segment. Completed article counts include held-out articles, which are evaluated rather than trained. The original dataset has not been fully processed. Articles presented are not articles mastered.

First segment development test NLL: 3.153 baseline → 2.721 after its first command → 2.659 after completion. Next segment test NLL: 2.686 → 2.595 after its first command. Different segments use different held-out text; do not treat those scores as one directly comparable curve. Generations remain fragmented and repetitive. Retention in the latest command is at the 95% threshold; later continuation may fail and must preserve its previous head.

`autonomy/verify_inn_wikipedia.py` independently reconstructed the latest committed model and matched checkpoint/parent/corpus hashes, optimizer counters, chunk offsets, retention, NLL, generations and finite weights. 39 relevant unit tests passed, including exact next-update resume and Adam row migration. These checks establish implementation continuity, not general factual generation.

## Storage and presentation

Streamlit Learning history shows command progress, committed exposure, pending chunk position, vocabulary size, optimizer steps, actual continuations and receipts. The farm remains paused and its admission unchanged. Commands refuse to begin below 2 GiB free on L:. Checkpoints and receipts are preserved; this guard is not a guarantee that an entire multi-million-article pass fits the remaining drive space. No automatic deletion or full dataset copy occurs.

Parser v2 removes inline exported section-heading markup before parsing. Existing immutable v1 pending corpora remain unchanged for exact continuation; future prepared segments use v2. Preprocessing is mechanical and still needs corpus-quality auditing before stronger knowledge claims.
