# LocalCoder Workspace Map

Read `L:\LocalCoder\AGENTS.md` first.

## Existing systems to reuse

- `viv_autonomy.py` and `autonomy\state.sqlite3`: persistent autonomous task loop, events, capabilities, training, evaluation, and promotion gates.
- `viv_chat_cli.py`: existing user-facing Viv entry point.
- `hive_control`: Rust task graph, capability, snapshot, channel, and receipt contracts.
- `swarm_adapters`: local Qwen worker models, LoRA stacks, held-out evaluation, and candidate activation.
- `hive_voice`: one-mouth voice routing.
- `HIVE_NETWORK_ARCHITECTURE_DRAFT.md` and `HIVE_LOCK_MANIFEST.json`: locked Hive topology and evidence boundaries.
- `INN`: learned architect engine and deterministic Rust farm.

## Current coupling direction

Current farm training: Architect -> GPU model Queen -> CPU own neural INN drone proposal -> Queen selection -> Rust execution and verification. The legacy farm policy remains a reversible fallback.

The Architect intends the INN to become Queen after broader learning and language gates. Do not claim that role switch has already occurred. These current farm roles follow the Architect's explicit direction; preserve the separate locked general Hive contracts.

Own neural training uses `autonomy/train_neural_inn.py`, the admitted checkpoint in `autonomy/learning/neural_admitted.json`, verified live Rust facts, and parent-relative farm/language gates. The Hive launches a bounded CPU attempt every 250 completed lessons by default. Live receipts must distinguish neural proposals, legacy weight updates, and failed candidates. Queen prose is not automatically a verified training target.

The game supplies the common training corpus: `autonomy/farm_corpus.py` publishes immutable hash-addressed snapshots with `inn_train.json` and `model_train.jsonl`. INN training reads its internal view; `autonomy/farm_adapter.py` reuses the existing Hive QLoRA trainer for the model view. Exclude reserved plots 21 and 41, reject conflicting targets, and distinguish legality facts from measured 12-tick strategy improvements. The current Ollama Qwen3-8B Queen cannot use a LoRA trained on the existing local Qwen3-1.7B worker base. Adapter preflight and training receipts must not claim live Queen weights changed before matching-base training, held-out evaluation, conversion, and live verification.

Do not infer that Continue/Viv state is LocalCoder Hive state. Resolve and inspect each runtime separately with the updated `viv-live-foreman` skill.

Custom tokenizer lane: `INN/inn/uml_character_tokenizer.py` is a hash-identical copy of the Architect's universal Unicode tokenizer from Continue/Viv. `INN/inn/tokenizer.py` supplies a frozen compact neural view, retaining universal IDs separately. `LanguageEngine` accepts this tokenizer and a configurable token context; checkpoints bind both. Legacy byte checkpoints retain their original contract. `Rebuild-INNTokenizer.ps1` runs a bounded language-only migration/training/evaluation candidate, writes `autonomy/learning/inn_tokenizer_status.json`, and does not replace the admitted farm INN. `Speak-INNTokenizer.ps1` inspects that candidate. Character integration does not establish Wikipedia knowledge or word/BPE curriculum completion.

Wikipedia sentence scaling: `autonomy/wiki_sentence_corpus.py` creates a bounded lead-sentence pilot from F:/AI_Datasets/wikipedia_deduplicated, excluding redirects/markup and recording aligned original/reduced views with conjunction offsets. Reduction is mechanical deletion, not a guaranteed semantic rewrite. `Train-INNSentences.ps1` trains the character INN on the reduced view with prior-skill replay, deterministic article/sentence order, 512-token context and a 600-second update-loop ceiling. Whole articles are split before training; cross-split identical targets are excluded. Results are development evaluations, not evidence of general factual generation. The structure pass remains closed until a separate generation-quality evaluation passes. Never promote a candidate just because NLL fell.

Full Wikipedia continuation uses `Train-INNWikipedia.ps1` and `autonomy/train_inn_wikipedia.py`, with `autonomy/wiki_stream.py` reading prose from all article sections. The experimental campaign head at `autonomy/learning/wikipedia_campaign/head.json` binds checkpoint hash, Adam optimizer continuity, dataset cursor, pending corpus hash and chunk offset in one atomic commit. Each command resumes this head; it does not restart the pilot parent. An expanded compact character vocabulary remaps existing weights and Adam moments by character identity. Commands stop after their update budget, the pending segment's first training traversal, or a 600-second update-loop ceiling; `-Segments` requests a bounded sequence of commands. Reading a file, preparing an article or presenting its chunks is not evidence of mastery. Completed eligible articles include reserved evaluation articles. Exact-target split ownership is stored on L: in SQLite; initial pilot overlap and repeated evaluations remain development evidence. Retention failures preserve the rejected run and leave the campaign head unchanged. Training stays on L:, source reads stay on F:, and the farm admission stays untouched. Stop with less than 2 GiB free on L:; retain receipts and failed candidates.

The matching training base is now `swarm_adapters/models/Qwen3-8B`, pinned to official revision `b968826d9c46dd6066d109eabc6255188de91218`. `model_source.json` records upstream hash checks and matching live Queen architecture (36 layers, width 4096). `Train-FarmAdapter.ps1 -Train` performs bounded GPU training and evaluation using existing Hive pause controls and inference locking. It unloads Ollama and leaves farm execution paused after completion or failure. Only explicit `-ResumeFarm` restarts continuous farm execution after the entire successful command. Original base weights remain frozen. `evaluate_farm_adapter.py` compares reserved Rust descriptions before any live activation. A trained adapter or passing language score alone is not a passing Rust farm behavior gate.
