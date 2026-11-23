# Game-generated corpus for INN and model learning

This records the initial corpus stage. The later matching 8B weights and actual
GPU training phase are documented in `FARM_QUEEN_GPU_TRAINING_20261008.md`.

The Rust farm is the source of training facts. Its existing isolated executions
label legal and illegal choices; recorded strict 12-tick improvements supply
bounded strategy labels. Queen messages remain evidence, not automatic truth.

`farm_corpus.py` publishes hash-addressed immutable snapshots. `inn_train.json`
feeds the internal INN action/language optimizer. `model_train.jsonl` is an
assistant-only chat view for the existing `swarm_adapters/train_adapter.py`.
Plot identities 21 and 41 remain excluded from training. Conflicting targets
are rejected because the prompt must then include more state.

The first snapshot contains 581 deduplicated text facts, 840 action contexts,
and 970 model rows. All 970 rows passed the existing Hive ChatDataset interface:
at least eight supervised tokens each, zero truncated contexts. The existing
1.7B tokenizer was used only for this format check.

Future neural runs publish and consume this corpus before optimization. The
current admitted INN checkpoint predates this shared corpus packaging. This
packaging does not prove broader prediction, general language, or continual
improvement. Both later continuation attempts failed the farm gate despite
retaining 20/20 descriptions; the admitted checkpoint remains unchanged.

## Commands

From `L:\LocalCoder`:

```powershell
& L:\.venv\Scripts\python.exe workspace\autonomy\farm_corpus.py
& L:\.venv\Scripts\python.exe workspace\autonomy\verify_farm_corpus.py
.\Train-FarmAdapter.ps1
```

The adapter command defaults to preflight. The actual Queen is Ollama
Qwen3-8B Q4_K_M. The local trainable Hive worker is Qwen3-1.7B; its adapter cannot
be applied to the 8B Queen. A matching trainable Qwen3-8B source is required.
The GPU is occupied by the live Queen, so bounded QLoRA training also requires
an explicitly scheduled GPU training phase. No download, GPU handoff, LoRA
training, Queen replacement, or adapter activation was performed here.

With the matching local base and a free GPU, `Train-FarmAdapter.ps1 -Base PATH
-Steps 40 -Train` reuses the existing Hive trainer for an isolated candidate.
Its training receipt does not admit that candidate. Held-out behavior, Rust
farm comparisons, conversion compatibility, and live verification remain
required before the Queen can use a trained farm adapter.

Status and interface verification are in `learning/farm_adapter_status.json`
and `learning/farm_corpus_verification.json`. Streamlit Learning history shows
the corpus counts and actual adapter blockers.
