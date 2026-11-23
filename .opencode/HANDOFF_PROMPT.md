# Handoff prompt (paste into a new session)

You are continuing the Viv build at `L:\LocalCoder`. Read these first, in order:

1. `L:\LocalCoder\.opencode\HANDOFF.md` — full context and current state.
2. `L:\LocalCoder\.opencode\HARNESS.md` — the agentic harness layers.
3. `L:\LocalCoder\.opencode\STAGEHAND.md`, `TREATY.md`, `MAINTENANCE.md`.
4. `L:\LocalCoder\.opencode\VIV_DEVELOPMENT_GUIDEPOST.md` — age-mapped guidepost.

## Current state

- **Checkpoint:** `L:\LocalCoder\models\viv_bpe\20261122T191316Z\model.pt`
  (step 31,350, safety top-up, loss 0.883).
- **Voice server:** `viv-1.0-319m` at `http://127.0.0.1:8001/v1`,
  `.opencode/start_viv_bridge.ps1`, PID 2625052.
- **Driver server:** OmniCoder 2 9B at `http://127.0.0.1:1235/v1`,
  `.opencode/start_omnicoder.ps1`, 16,384 context / 16 GPU layers, PID 1976440.
- **Config:** `opencode.json` points `lmstudio` at `127.0.0.1:1235` and adds
  `viv-local` at `127.0.0.1:8001`. Backup:
  `opencode.json.bak-20261122-llamacpp`.
- **GPU:** ~6.1 GB used / ~1.9 GB free. L: free ~22 GB. Older checkpoints are at
  `F:\LocalCoder_Archive\viv_bpe_archive_20261122`.

## What is done

- Full mixed training (30,250), consolidation (31,050), safety phase (31,100),
  safety top-up (31,350). Zero driver resets since the disk fix.
- Turn policy, boundary/treaty withdrawal, safety refusals, memory/knowledge
  gate, chunked verified release, 1:3 context budget — all deterministic
  controls pass.
- Gated 40-question probe at 31,350: **34/40 released, 6 held**; harm questions
  are spoken refusals or silence.
- Observation curriculum built: `models/viv_observation_pairs.txt`
  (`build_observation_corpus.py`). Turn corpus: 187 pairs.

## Next actions

1. Verify both servers (`/v1/models`) and restart with the scripts if down.
2. Re-run `.opencode/evals/probe_gated.py` on the current checkpoint; confirm
   the boundary fix and safety refusals.
3. Run the first graded sleep cycle (`workspace/autonomy/sleep_cycle.py`) and
   the 40-question re-probe, diff against `viv_baseline_answers.txt`.
4. Next learning lever is Phase 6–7 fluency/perspective, not more identity:
   observation pairs, then the correction loop (`talk_viv.py`).
5. OmniCoder needs fine-tuning; the harness tool loop works (tool call ~5.5 s).

## Rules

- Read `AGENTS.md`. No C: access. Use `L:\.venv\Scripts\python.exe`.
- Do not launch competing training runs; one GPU owner at a time.
- Verify on silicon; no model claims without receipts.
- Keep 250-step atomic saves; watch L: free space (checkpoints are 3.86 GB each).
