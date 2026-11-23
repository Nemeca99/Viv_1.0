# Session Summary — 2026-11-20 (Hydra security build + parallel training/download)

## Verified actions (with silicon results)

### Hydra security stack (5 layers, all tested via `L:\.venv\Scripts\python.exe`)
All in `L:\LocalCoder\workspace\autonomy\`:
1. `hydra_protocol.py` — entropy password vault (secrets-based, 1-100 char ASCII+Unicode), 1 Hz heartbeat rate limiter, append-only attempt log. Demo: correct guess accepted, wrong rejected, rotation remints N+1.
2. `hydra_devkey.py` — master DevKey + "two halves" (XOR one-time-pad split). Verified: authorize fails while running, works after shutdown, halves reconstitute key, hash-match override.
3. `hydra_soft_devkey.py` — disk-backed write-once lock. REAL key minted at `L:\LocalCoder\workspace\security\devkey\master.key` (key_id `84F163ED33830D67`, digest `84F163ED...C27B9E4`). Write-once + read-only + tamper-detection all verified. Key bytes never printed.
4. `hydra_self_bound.py` — containment half (protect world from her): 1 Hz self-throttle, no first strike, reactive-only, no kill/no pursue levels, holds no key material.
5. `hydra_decoy_layer.py` — Wikipedia metadata decoys. Verified doubling 1→2→4, size+mtime match, content decoys, against REAL `F:\AI_Datasets\wikipedia_deduplicated` (80 GB, 85.9 GB confirmed, individual .txt articles).

### Corpus/training
- `train_viv_bpe.py` — byte-BPE transformer trainer (vocab 6,786), model 316M params. RUNNING in background on `viv_grammar_corpus.txt` + `viv_world_knowledge.txt` (3.19M tokens). Log: `.opencode/evals/viv-bpe-identity-world.log`. At step ~1850 loss ~1.48 (from 4.10). Identity holds ("I am a machine"); vocabulary garbling.
- **KNOWN BUG (unfixed):** `generate_neuron_corpus.py::coarse_class` maps `"plant"`→`"place"` (CLASS_MAP line 44) and uses only `syns[0]`, producing false sentences ("the elk is a writing", "a coontie is a place").

### Movie scripts (voice corpus)
- Cloned `Aveek-Saha/Movie-Script-Database` → `L:\LocalCoder\workspace\reference\Movie-Script-Database` (scraper utility, not scripts).
- Upstream `get_scripts.py` has Windows multiprocessing bug (fork-style spawn). Wrote `download_sequential.py` (sequential, re-run safe) to work around it.
- Installed deps into venv: tqdm, fuzzywuzzy, Unidecode, beautifulsoup4, IMDbPY, textract (all import OK).
- **Download RUNNING in background**: 9 sources sequential, `imsdb` first (1,297 scripts @ ~2.2/s). Log: `.opencode/evals/movie-script-download.log`.
- Next after download: `parse_files.py` → `C=>D` dialogue (strips scene headings/directions).
- Existing dialogue data already on disk: `F:\Viv_Data\source_dialogue\` (SODA 672MB, Gutenberg dialog 72MB).

## Current state
- Two background jobs: (1) byte-BPE training, (2) movie-script download. Do NOT poll; auto-notified on completion.
- Ex Machina script search (across drives) still pending/backgrounded — no result yet.

## Open items / next decisions
1. Fix `coarse_class` (plant→place, first-sense bias) if generated world-knowledge corpus stays in use; or switch world-knowledge to Wikipedia pipeline (already built: `wiki_sentence_corpus.py`, `wikipedia_rag.py`) and voice to scripts.
2. When download lands: run `parse_files.py` for `C=>D` dialogue.
3. Attempt-log "learning" adaptation deferred until model can actually learn (Architect's call).
