# Local INN

Python owns the Transformer, F1/F2 scoring, learned B1 gate, exploration,
planning, and training. The Rust farm owns the world, virtual clock, legal
actions, committed FIFO queues, execution, resources, and outcome rewards.
The native DLL stays in the Python process. There are no cell writes or sleeps
in the simulation loop. `tickMs` remains simulation metadata; one tick still
has the original game meaning regardless of wall-clock speed.

## Run

Use the Architect's selected base interpreter: **`L:\.venv\Scripts\python.exe`**.
No additional environment or package installation is required on this machine.

```powershell
cd L:\LocalCoder\INN
.\Build.ps1
.\Run.ps1 -Steps 10000
```

Double-click **Start INN.cmd** for continuous Transformer training, or run:

```powershell
& 'L:\.venv\Scripts\python.exe' run.py --steps 0
```

Ctrl+C requests a stop at the next completed tick and writes the final
checkpoint. Each run gets a separate directory under `runs/`. Every 1,000
steps, the runner writes sampled telemetry and a checkpoint generation.
Checkpoints contain the farm, pending reward transition, commitments, RNG,
model/target weights, optimizer, and replay buffer, with SHA-256 manifests.

By default a new local run imports the original sheet checkpoint at tick
4,872. Its saved action values and validity logits are frozen initial baselines
for the Transformer; its attention layers start with new weights. Training
adds neural action values and learned validity residuals. Use `--fresh` to
start with a new farm and zero baselines.

To continue a **local** checkpoint, pass its generation directory explicitly:

```powershell
& 'L:\.venv\Scripts\python.exe' run.py --resume 'runs\YOUR_RUN\checkpoint-final' --steps 10000
```

The original V8 learner is available for reference and fast farm experiments:

```powershell
.\Run.ps1 -Engine linear -Steps 10000
```

Use `--engine linear` when resuming a linear checkpoint. CPU is the default
for this small sequential model. `-Device cuda` enables GPU execution.
`--train-every 32` controls how often a minibatch optimizer update occurs;
every tick still makes a model decision and records its transition in replay.

## Implementation

- `farm_rust/src/lib.rs`: all original world rules, five observation features,
  candidate enumeration, immutable FIFO consumption, preview mechanics, and
  native C ABI. Rust rechecks legality before any world action.
- `inn/engine.py`: shared controller loop and original V8 linear TD learner.
- `inn/transformer.py`: two attention blocks, width 32, four heads, residual
  connections, LayerNorm, ReLU feed-forward layers, action-value head, and
  validity head. It uses the sheet's square divisor and normalized softmax
  power: `norm(softmax(QK / (sqrt(d_head)^surface))^volume)V`. The default
  surface is 2; volume follows the original exploration schedule from 1 to 3.
  There is no causal mask because the tokens are simultaneous action candidates.
- Training uses outcome rewards, TD targets, an AdamW optimizer, a target
  network, replay, and gradient clipping. Validity learns from Rust's legality
  outcomes. The learner does not award itself extra success rewards.
- `inn/import_sheet.py`: standard-library XLSX checkpoint and log import.
- `source_archive/`: original checkpoint and historical training rows with hashes.
- `verification/`: original-JavaScript parity and Transformer/resume checks.

The Apps Script farm rules are retained, including bank-based expansion,
growing delay of two ticks, merge and upgrade costs, automation funding,
late-deadline decay, inactive committed queue consumption, and negative
outcomes. Spreadsheet display descriptions that differ from those executable
rules did not override the script. The attention/training/cognitive lab tabs
remain available in the original workbook as architecture references; this
local runner connects the Transformer directly to farm observations and rewards.

## Build evidence (2026-10-08)

- Six original-JavaScript comparisons passed across 8,000 steps: fresh runs,
  the imported checkpoint, expansion, automation, and inactive commitments.
  Runtime traces and final plot state, weights, validity, loss, and update
  counts agree within floating-point tolerance.
- The square/cube attention formula passed an independent tensor calculation.
- Actual optimization changed Transformer attention weights.
- An uninterrupted 128-step Transformer run matched a 64 + save/reload + 64
  run, including exact CPU model weights.
- A 1,000-step imported Transformer run completed 31 optimizer updates at
  approximately 348 steps/second on CPU. A short CUDA run measured about
  92 steps/second. The original linear learner measured about 3,500–4,300
  steps/second in the normal small-farm parity runs. Larger candidate sets
  can run more slowly; these are bounded local measurements.

The implementation and restart path are verified. Better farming behavior,
long-run training stability, and generalization have not been established.
Raw receipts are in `verification/artifacts/` and `runs/*/receipt.json`.

The LocalCoder launcher and its scoped OpenCode shell environment override
also select `L:\.venv`. Existing long-running Viv workers were not altered by
this INN build.
