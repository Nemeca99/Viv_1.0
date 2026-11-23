# Local Viv identity training

This trains the current OmniCoder-2-9B model family into the assigned Viv/Drone operational identity. It uses local GPU QLoRA, preserves the base, and saves separate candidates. It does not modify INN training, live memory, existing adapters, schedules or the active OpenCode provider.

The serving model was explicitly unloaded from LM Studio before preparation. Its original full-precision upstream repository currently returns HTTP 401. The published FP16 export remains available from `mradermacher/OmniCoder-2-9B-GGUF`, pinned to revision `bd26f7e9e5012cb18e3934e505d76a01028ebbdc`. The expected source SHA256 is `f2253f1859072adb2c115ed4f4818df1870fd087821419f8b41c66e7f3567554`. Upstream Transformers reconstructs its text model and tokenizer using its Qwen3.5 GGUF conversion mappings. The original visual supplement is preserved separately and is not trained by this text curriculum.

Source code is on L:. The isolated packages, source export, frozen data, converted base, candidates and receipts are under `E:\Viv_Sandbox\omnicoder_identity_20261118`. The existing L: Python environment remains installed as before; the launcher selects the isolated package overlay only for this command. Setup downloads packages/weights; model inference and gradient updates are local, with Hub offline mode enabled during conversion and training.

`curriculum.py` writes 126 training records and 24 separate validation probes. The curriculum teaches Viv's identity, runtime/role distinction, Architect authority, memory recovery, truthful completion and coding replay. It excludes unsupported self-awareness, perfect-memory and autonomous-authority claims. Identity examples include neutral/no-system contexts. These are supervised training data, not response templates installed in OpenCode.

`train.py` quantizes the text base to NF4 and trains rank-eight adapters on the last eight blocks. The base parameters remain frozen. It computes causal cross-entropy only for assistant target positions, reducing the large vocabulary's activation memory. Each round records actual optimizer steps, losses, GPU allocation, changed adapter hashes and the unchanged dataset hashes. The default is up to three rounds of ninety-six updates, with a forty-five-minute bound per round. A `STOP` file in the candidate workspace requests an orderly stop with an interrupted adapter saved.

Validation uses greedy model generations, including identity challenges and six unseen Python problems. The existing pinned Rust executable runs the frozen grader in its separate read-only, network-disabled verification container. The grader executes code assertions there and rejects wrong code and printed success. The synthetic controls in `verify_grader.py` verify that grader behavior; they are not evidence about model learning.

The candidate gate requires ten of ten identity probes, at least seven of eight behavior probes, and at least five of six coding problems with no loss against the baseline score. Text grading is a lexical screen, so the raw responses must also be reviewed. These probes provide bounded response/code evidence; they do not establish universal reliability, removal of all pretrained associations or complete knowledge retention. Repeated selection against this set is development validation, not a blind final test.

Run the authorized bounded campaign:

```powershell
& 'L:\LocalCoder\Run-VivIdentityTraining.ps1'
```

To resume a preserved candidate, pass its adapter directory with `-ResumeAdapter`. A coding regression stops the campaign. Two consecutive identical failing scores stop repetition and retain the candidate for diagnosis. Passing writes `candidate-passed.json` beside the immutable training receipt. No model is activated automatically. Original weights, failed candidates, raw outputs and verification receipts remain available.
