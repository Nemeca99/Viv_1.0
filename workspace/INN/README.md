# Local INN

Your supplied Apps Script and workbook are the source of this rebuild. Python
owns F1/F2 scoring, B1 validity learning, exploration, planning, and TD updates.
Rust owns the farm, virtual clock, actions, FIFO commitments, resources, and
rewards. The native DLL runs inside Python. Ticks have no Sheets calls or sleeps.

## Run

Double-click **Start INN.cmd** for continuous execution, or:

```powershell
cd L:\LocalCoder\INN
.\Run.ps1 -Steps 10000
```

The interpreter is `L:\.venv\Scripts\python.exe`. The default `learned` engine
executes a conservative version of the original FarmScript learner. It uses the
same farm, features, gates, and update rule with a TD step of 0.01. The exact
original learner, with its 0.15 step, remains available as `source` for parity.
The first launch imports the workbook
checkpoint at tick 4,872, including weights, validity, pending transition,
farm state, and commitments. Subsequent launches continue `latest-source.json`.
Ctrl+C finishes the current tick and saves a final checkpoint.

```powershell
# Restart from the original workbook checkpoint:
.\Run.ps1 -FromSheet -Steps 10000
# Exact original learner for parity:
.\Run.ps1 -Engine source -FromSheet -Steps 10000
# Ten sequential cycles; cycle 1 starts from the workbook and later cycles
# continue from the previous learned checkpoint:
.\Run.ps1 -FromSheet -Steps 100000 -Loops 10
# Lower disk use while retaining one action row per step, telemetry, and checkpoints:
.\Run.ps1 -FromSheet -Steps 100000 -Loops 10 -CompactLog

The training interpreter, code, and Rust DLL stay on L:. Run logs and
checkpoints default to `F:\LocalCoder_Archive\INN_live_runs` so storage does
not fill L:. Override with `-RunRoot PATH` when needed.
# New farm and learner:
.\Run.ps1 -Fresh -Steps 10000
# Continue a selected checkpoint:
& 'L:\.venv\Scripts\python.exe' run.py --resume 'runs\YOUR_RUN\checkpoint-final' --steps 10000
```

An already-running process keeps its loaded implementation. Stop it with Ctrl+C
and launch again to use this repair. Existing experimental Transformer runs
retain their checkpoints and require their original engine to resume.

## Logs and saved state

Each invocation writes a new run directory:

- `training_log.jsonl`: every action, transition, and world event, with the
  original 31 columns. `training_log_schema.json` names those columns.
- `telemetry.jsonl`: periodic rewards, harvests, decays, invalid outcomes,
  update counts, bank, and plot counts.
- `checkpoint-*`: state and SHA-256 manifest every 1,000 steps and at shutdown.
  Includes RNG, weights, validity, pending reward, frontier, commitments, and
  the last 2,048 history rows for reset/replay continuity across restarts.
- `receipt.json`: actual steps, elapsed time, and final runtime.

Action logs flush every 100 steps and sync at periodic checkpoints. Abrupt power
loss can lose the uncheckpointed tail. Completed checkpoints are immutable;
manifest hashes are checked before resume.

## Original controls

Stop the source run before changing saved state. Controls create a new checkpoint
branch and update the continuation pointer.

```powershell
& 'L:\.venv\Scripts\python.exe' control.py reset
& 'L:\.venv\Scripts\python.exe' control.py bank --value 10000
```

Reset closes the pending terminal transition, preserves frontier and history,
creates a fresh farm, and replays the last 128 compatible transitions from the
last 2,048 rows. Bank sets the amount. Use `--checkpoint PATH` to branch from a
selected source checkpoint.

## Workbook architecture in Python

```powershell
& 'L:\.venv\Scripts\python.exe' architecture.py --output architecture-results.json
```

`inn/sheet_engine.py` executes the formula graph in Pesonal, Attention,
Training_Pipeline, Cognitive_Engine, Simulation_Logs, Scaling_Stress_Test,
and Pattern_Generation_Lab. Supply `--inputs inputs.json` with overrides such
as `{"Pesonal!B1": 0}` to recalculate dependent cells.

All 780 saved formula results match the supplied workbook. Two SPARKLINE cells
return empty text; chart rendering is not implemented. Numerical formulas are
evaluated; cached values are used only for comparison. The tabs retain their
original connections. The farm's live learner is the five-feature linear Q
learner specified by FarmScript.

## Experimental neural implementation

The earlier added Transformer changes the original learner. It is preserved
as an explicit experiment requiring both flags:

```powershell
& 'L:\.venv\Scripts\python.exe' run.py --engine transformer --experimental-transformer --steps 10000
```

Its residual attention model, target network, minibatch replay, and AdamW are
not part of the source-faithful default. Better behavior has not been established.

## Repair evidence

- A 100,000-step continuation matched original JavaScript runtime, plots,
  weights, validity, loss, and update counts within floating-point tolerance.
- All 4,577 log rows across a separate 2,000-step comparison matched all 31
  columns; next-candidate JSON was compared structurally.
- Original 128-transition replay and hard reset matched.
- Save/reload plus 1,000 steps matched uninterrupted continuation.
- Ctrl+C completed its tick and saved a consistent checkpoint.
- All 780 formula results matched the saved source workbook.
- A fully logged 10,000-step run measured about 2,975 steps/second on this
  machine. Rate varies with farm size and storage.

Behavior was tested separately. The original 0.15 step caused policy collapse.
The learned-v9 candidate uses a 0.01 TD step and passed the first behavior
gate: after 20,000 training steps, its frozen policy averaged 1,111 harvests
per 10,000 evaluation steps across all eight held-out seeds, with zero decays.
The receipt is in `verification/artifacts/learned-v9-evaluation.json`. The
earlier failed run remains in `learning-evaluation.json` and documents why the
rate was changed.

The held-out winner is promoted in `latest-learned-policy.json`. New learned
runs load that policy and replace it only when a fresh-farm probe improves.

The 100,000-step log exposed a cash starvation failure: the policy spent the
bank down, lost a plot, then repeated IDLE. A trial guard that forced any
non-IDLE action made this worse by repeatedly tilling barren plots; that trial
is retained as negative evidence in `survival-guard.json` and is not active.
The next repair must distinguish a genuinely productive action from a merely
legal one.

Rebuild the Rust DLL with `.\Build.ps1`. Original workbook and FarmScript remain
unchanged. Prior implementation files are preserved in `repair_backups/`.
