# Session Summary — Viv Stage 2: Identity + Dialogue (sleep started)

## Training = sleep, learning = daydreaming (Architect's frame)
The corpus pass is sleep (passive consolidation, loss = sleep depth); the periodic
samples are dreams (generation = where learning shows). We read the dreams, not
just the loss.

## CURRENT RUN (live, background)
- `train_viv_bpe.py --corpus viv_identity_dialogue.txt` — fresh model.
- init: stamp `20261121T032253Z`, 319,154,176 params, vocab 8192, corpus 756,220 tokens.
- Log: `.opencode/evals/viv-dialogue-identity.log`. Checkpoint dir: `L:/LocalCoder/models/viv_bpe/<stamp>/`.
- Sequence per Architect: identity + dialogue now; facts (world knowledge) LATER once she can speak.

## Security stack (all verified via L:\.venv\Scripts\python.exe)
In `L:\LocalCoder\workspace\autonomy\`:
1. `hydra_protocol.py` — entropy password vault, 1 Hz heartbeat, append-only attempt log.
2. `hydra_devkey.py` — master DevKey + two-halves XOR split.
3. `hydra_soft_devkey.py` — disk lock, write-once, tamper-detected. REAL key at
   `L:/LocalCoder/workspace/security/devkey/master.key` (key_id `84F163ED33830D67`).
4. `hydra_self_bound.py` — containment (protect world from her): 1 Hz self-throttle,
   no first strike, no kill/pursue levels, no key material.
5. `hydra_decoy_layer.py` — Wikipedia metadata decoys (doubling haystack), verified
   against real 80 GB `F:\AI_Datasets\wikipedia_deduplicated` (85.9 GB, .txt articles).

## Corpus / training artifacts (L:/LocalCoder/models/)
- `viv_bpe_tokenizer.json` — RE-TRAINED for dialogue (vocab 8192; "?"/"!" now tokens,
  contractions 2-token). Old tokenizer backed up as `viv_bpe_tokenizer_grammar_world.json`.
- `viv_identity_dialogue.txt` — 44,649 lines (42,522 spoken dialogue + identity every 20).
- `viv_world_knowledge.txt` — regenerated with plant fix (40,246 sentences).
- `viv_world_knowledge.txt.pre_plant_fix` — pre-fix backup (negative evidence).

## Classifier bug fix (generate_neuron_corpus.py + generate_world_knowledge.py)
- FIXED: `plant.n.02` (flora) no longer -> "place". Added real `plant` class
  (was missing; docstring even said "the tree is a plant"). Now: coontie/tree/flower -> plant.
- FIXED: own-name check in `coarse_class` — person/animal/machine/vehicle/time/text
  classify as themselves (were "object").
- KNOWN remaining: `car -> object` ("a car is a thing", true-but-vague, left alone).

## Movie scripts (voice corpus) — L:/LocalCoder/workspace/reference/Movie-Script-Database/
- Cloned Aveek-Saha/Movie-Script-Database. Download: 1,843 scripts, 336 MB
  (imsdb 1213, scriptpdf 278, awesomefilm 134, screenplays 117, dailyscript 101).
  5 sources failed (scraper rot: site changes / expired SSL / 404).
- Wrote `download_sequential.py` (upstream get_scripts.py had Windows multiprocessing bug).
- Wrote `parse_batch.py` (bulk parser + cp1252->UTF-8 normalization).
- Fixed 4 bugs in `parse_files.py`: get_offset min() empty, get_char_dial empty char_ind,
  abridged_ind IndexError, UTF-8 write encoding.
- Output: `scripts/viv_dialogue_corpus.txt` = 42,547 C=>D lines (1,843/1,843 parsed).

## Ex Machina script (seed, not yet read)
Found on E: (search completed):
- `E:\Backup\Dev_AIOS_Backup\AIOS_Clean\backup_core\active_backup\data_core\analysis\ex_machina_dialogue.json`
- `...\ex_machina_full_script.txt`

## Hardware telemetry incident
Rust Body gate fail-closed ALL tools with `body_thermal_telemetry_missing_or_stale`.
Cause: HWInfo/Corsair live logging stalled. Architect restarted logging at
`L:\LocalCoder\Hardware` (hwinfo.CSV + corsair_cue_*.csv). Gate cleared.

## Next open items
1. Monitor dialogue run: identity should hold; dialogue (contractions, "?", natural
   turn-of-speech) should emerge. Report loss + samples at completion.
2. Once she can speak: add facts (world knowledge) as next stage.
3. Read ex_machina_dialogue.json as thematic seed (when relevant).
4. (Optional) re-train tokenizer once more when adding facts; (Optional) car->object fix.

## Sleep/dream loop (built after this summary)
Architect's frame: mind sleeps (training = relearning what she already knows, forming
new links/patterns to make it solid) while the body stays awake (Rust = deterministic).
Daydream = explore probability; learning = from experience; awake = apply it.

- `train_viv_bpe.py` now injects SCENES every 100 steps (SCENE_EVERY=100): 7 scene
  prompts (identity questions + situation setups). She "acts out" the scene; logged
  as `{"event":"scene", "scene":..., "text":...}`. Takes effect NEXT run (current run
  predates this edit).
- `filter_dreams.py` = the awake body: deterministically verifies dreams (samples +
  scenes), keeps accepted -> `L:/LocalCoder/models/viv_dreams.txt`, rejects drift/garbled
  -> `viv_dreams_rejected.txt` (negative evidence). Tested live: 15 dreams, 14 accepted,
  1 rejected ("You are" -> "You areiest hurt" identity drift). Accepted dreams fold back
  into next sleep's corpus (dream replay).

