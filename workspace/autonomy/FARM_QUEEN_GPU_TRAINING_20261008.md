# Matching 8B farm adapter and GPU training phase

The training source is the official `Qwen/Qwen3-8B`, revision
`b968826d9c46dd6066d109eabc6255188de91218`, under
`L:\LocalCoder\workspace\swarm_adapters\models\Qwen3-8B`.
Fourteen required files total 16,397,459,696 bytes. Every required file was
checked against its upstream Git or LFS hash. `model_source.json` preserves
the checks and the live Ollama Queen architecture comparison: 36 layers,
width 4096. This does not assert numerical equality with quantized GGUF tensors.

## GPU phase

`farm_gpu_phase.py` uses the existing Hive Store, worker pause control, and
inference lock. It waits for the current farm cycle to finish, unloads the
Ollama Queen, and runs a bounded training subprocess. GPU commands now leave
the farm paused after completion or failure. Previously they restored the
prior continuous worker, so activity continued after the command returned.
Only explicit `-ResumeFarm` restarts it after both training and evaluation.
The Windows launcher tree is terminated on child timeout before cleanup.
Tests cover paused completion and failure, optional restoration, inference
refusal, and launcher-tree timeout.

The existing Hive trainer uses NF4 QLoRA, rank 8 on its existing attention/MLP
targets, gradient checkpointing, batch size 1, and accumulation 2. Frozen
embedding and output matrices remain fp16 in the low-VRAM option; CPU staging
avoids PEFT's transient fp32 GPU allocation. Original base weights are frozen.

The first actual run completed 40 optimizer updates in 73.93 training seconds,
using 975 corpus rows and 21,823,488 trainable adapter parameters. Peak PyTorch
allocation was 7,001,249,280 bytes. Its base weight hashes matched the verified
upstream source. Queen inference and farm execution were restored afterwards.

Reserved plot-21 evaluation: base 0/20 exact descriptions, adapter 15/20.
Five incorrect facts caused the 95% language gate to fail. This run remains
preserved under `learning/farm_adapter_runs/20261008T203300746907Z`.
A second attempt used the identical corpus and 160 updates, completing in
315.13 training seconds. Peak PyTorch allocation was 7,092,286,976 bytes.
It scored 18/20 on plot-21 validation and 18/20 on freshly reconstructed
plot-41 Rust facts. Both failures were early HARVEST: SEEDED and WATER1 were
incorrectly called legal. The 95% language gate failed. Its weights and
negative evidence are preserved under
`learning/farm_adapter_runs/20261008T204051482407Z`. It was not activated.

The larger budget fixed the five legal-action errors from the first attempt
but introduced two premature-harvest errors. The next refinement must address
stage-boundary discrimination; these receipts do not establish general game
mastery or a passing farm behavior gate. The matching source and GPU phase
are functional even though this learned candidate remains below its gate.

## Commands

From `L:\LocalCoder`:

```powershell
.\Train-FarmAdapter.ps1                 # preflight
.\Train-FarmAdapter.ps1 -Train -Steps 160
.\Train-FarmAdapter.ps1 -Train -Steps 160 -ResumeFarm # explicitly continue farm afterwards
```

The training command also runs reserved-language evaluation. `-SkipEvaluation`
leaves an unevaluated candidate for a later explicit evaluation command.
The default command leaves the existing Queen unloaded and the farm paused;
the dashboard and idle supervisor remain available. `-ResumeFarm` runs the
continuous worker until explicitly paused. It does not install the new
adapter into Ollama. Language evaluation is separate from Rust farm decision
behavior, conversion compatibility, and live admission. Current status and
progress appear in Streamlit's Learning history.

Runtime training receipts report Torch 2.6.0+cu124. The shared environment's
distribution metadata also contains a 2.5.1+cu121 version; preflight now records
the imported runtime version separately from distribution metadata. This work
did not install or change packages in the shared environment.
