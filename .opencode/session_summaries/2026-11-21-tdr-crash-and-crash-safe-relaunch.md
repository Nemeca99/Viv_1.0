# 2026-11-21 — TDR killed the SODA run; trainer made crash-safe; relaunch

## What happened
- Run r1 (stamp `20261121T175508Z`, resumed from `20261121T135228Z` at step 15,201)
  stopped at **14:54:13**, step **18,950**, elapsed 10,189 s.
- No traceback, no `done` event, no `model.pt`. The log ends mid-sample.
- `nvlddmkm` Event **153** (Error) at **14:55:01** — display driver reset (TDR).
- Same Event 153 at **11:41:14**, matching stamp `20261121T154238Z` dying at 11:40.
- Recurring 153s 11/19–11/21. `TdrDelay`/`TdrLevel` unset (2 s default).
  Driver 32.0.16.1742 dated 2026-09-29. GPU at 7,951 / 8,192 MiB before reset.
- **3,749 steps lost** because the trainer saved only after the loop exits.

## What was changed
`workspace/autonomy/train_viv_bpe.py` — the Architect had already added a
2,000-step save at 14:56:46. Extended it, not replaced it:
- `--save-every N`, default **250** (`0` disables periodic saves).
- `save_checkpoint()` writes `model.pt.tmp` then `os.replace` — a kill during
  the write leaves the previous checkpoint intact instead of a truncated file.
- `--device` (`cuda`/`cpu`, default auto) so the trainer is testable on CPU.
- Final save uses the same atomic helper.

## Verification (`verify_periodic_save.py`, CPU tiny model, ALL PASS)
- 4-step run: saves at step 2 and 4; checkpoint loads with `steps=4`; no `.tmp`.
- Hard kill at step 48: last periodic checkpoint is loadable.
- Resume from it: reports `steps=48`, advances to 49.
- Grader controls (`verify_grader_cycle.py`) still ALL PASS after the temp-dir fix.
- Both test scripts now use `L:\LocalCoder\.opencode\evals\tmp`, not `C:`.

## Relaunch
- Discovered the Architect's 14:58 stopgap (batch 6, 7,976 MiB) and my own
  duplicate 15:09 launch. My duplicate was stopped; the stopgap was stopped
  because it had no checkpoint yet and the explicit choice was the patched run.
- Empty stamps preserved as evidence: `20261121T210942Z` (my duplicate),
  `20261121T205819Z` (stopgap, samples only).
- **Run r3**: `--resume 135228Z --batch 4 --save-every 250 --device cuda`,
  8 h bound, log `.opencode/evals/viv-soda-training-r3.log`,
  PIDs 2034144 / 2412208. Expected VRAM ~6.9 GB.
- First periodic save at step 15,250 (~2 min after training starts), then every
  250 steps (~11 min). Watcher armed for 9 h.

## Open
- `TdrDelay` is still the 2 s default. Raising it to 60 s is a system change and
  needs a reboot — Architect's call.
- Batch 4 VRAM has not yet been observed under load; confirm it stays below the
  ceiling once training starts.
- If r3 dies, resume from the newest stamp containing `model.pt`; the periodic
  save is the recovery point.

## Ownership decision — 2026-11-21T21:35Z
- Discovered a second OpenCode session (parent `opencode-pty` PID 976000)
  launching competing runs at 15:17:09 and 15:27:39; it killed r3 at 15:26:59
  (no traceback, no TDR).
- Architect assigned GPU ownership to that session. This session stands down:
  no launching, no monitoring, to avoid duplicate reports and lost progress.
- r3 checkpoint preserved: `models/viv_bpe/20261121T211330Z/model.pt`
  (step 15,250, 3.86 GB) — proves the atomic save on the full 319M model.
- The other session truncated the shared `viv-soda-training.log`; r1 per-step
  evidence survives in `models/viv_bpe/20261121T175508Z/train.jsonl`.
- The live batch-6 run started after the patch, so it uses save-every 250 and
  atomic saves by default.
