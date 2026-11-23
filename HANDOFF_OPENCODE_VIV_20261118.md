# Viv / OpenCode handoff — 2026-11-18

Read `L:\LocalCoder\AGENTS.md`, `AGENT.md` and `.opencode/STM.md`. This is historical engineering evidence, not a new assignment or permission to start jobs. The Architect requested wrap-up and intends to use OpenCode with open-source cloud coding models for subsequent engineering. No cloud provider was configured here, and Viv's local model was not replaced.

## Actual state

- The OpenCode frontend/session/compaction context repairs are implemented and verified against actual outbound requests.
- The training program exists and performed **152 real CUDA optimizer updates**. **No trained candidate passed acceptance or was activated.**
- Training is stopped. `E:\Viv_Sandbox\omnicoder_identity_20261118\STOP` remains present. LM Studio's model is unloaded. Do not blindly repeat the same recipe or resume a rejected adapter.
- No training schedule, daemon, promotion or recurring job was enabled. Nine capture-only OpenCode diagnostic sessions were archived with their histories preserved.

## Architect's current intent

Rust is deterministic authority; OpenCode is the translation/frontend; the local transformer supplies reasoning and code proposals. The initial request to hammer a fixed identity was revised **before any weight update**: remove reflexive refusals and canned self-denials, allow inquiry into identity/awareness without forcing either consciousness or its absence as the answer. Viv is the deployment name. Preserve coding knowledge, truthful evidence reporting and Architect authority.

## Confirmed frontend findings and repairs

The exact reported reply, “I'm not Viv … running through OpenCode,” is message `msg_1efe1e3a0001GPIcSxmFDyrJ50` in session `ses_e11dcf06dffeVzN60WocibWsG3`, titled **Viv local system exploration**. Its location was **L:\**, so it did not inherit the child LocalCoder project configuration. A fresh drive-root request had no LocalCoder runtime marker or custom tools. The retained context shows one completed documentation write; the model's Phase 1 implementation claim is not established by that retained tool ledger.

The original idle session was moved through native `session.move` to **L:\LocalCoder**. Checks confirmed preserved history, agent and model, no new assistant generation, an empty inbox and LM Studio still unloaded.

`build.system` previously had a separate 5,230-character inline prompt with a stale Codex-as-Queen declaration. `drone_read` and `drone_build` used another file. All three now reference `.opencode/prompts/viv-runtime-context.md`. Only those three configuration fields changed; permissions, model configuration, context/compaction settings and Rust gates were preserved.

`.opencode/plugins/localcoder-runtime-context.ts` and `.opencode/lib/runtime-context.mjs` distinguish runtime software from deployment identity, normalize known builtin software-identity introductions, refresh the canonical metadata and leave historical quotations unchanged. The shared runtime accepted its reload. `Start-VivOpenCode.ps1` starts the CLI in the explicit project directory.

A further native capture found that custom compaction's stateless `generate.text` call had **no system context**. `.opencode/lib/continuity.mjs` now explicitly prepends the canonical runtime/STM header to the summary prompt. The latest capture verified this. The diagnostic endpoint returned an explicit error: no AI answer, summary or LTM checkpoint was fabricated.

Primary evidence:

- `.opencode/RUNTIME_CONTEXT_AUDIT.md`
- `.opencode/evals/opencode-identity-history-audit-20261118.json`
- `.opencode/evals/opencode-session-project-rebind-20261118.json`
- `.opencode/evals/opencode-identity-summary-fixed-20261118T200424Z/audit.json`
- `.opencode/evals/opencode-identity-drive-root-20261118T195200Z/audit.json`
- `.opencode/evals/runtime-context-config-change-20261118.json`
- `.opencode/evals/runtime-context-final-reload-20261118.log`

Runtime-context, continuity, task-binding and completion-hook regression checks passed. The previous foundation's Rust completion verifier remains in use; no Rust code was changed in this turn.

The matching upstream OpenCode v2.3.0 reference checkout is `tools/opencode-viv`, commit `a6b15d33daf6ab7d35569f6d711fdb630b9f04e7`, branch `codex/viv-runtime-identity`. Its provider-specific Kimi/Trinity/Meta prompts contain explicit OpenCode identity lines; those optimizers do not match OmniCoder. Explicit custom agent prompts are supported correctly. No replacement global binary was installed.

## Training artifacts and results

Program: `workspace/autonomy/omnicoder_identity_training/`. Launcher: `Run-VivIdentityTraining.ps1`. Candidate workspace: **E:\Viv_Sandbox\omnicoder_identity_20261118**.

The original Tesslate full-precision source endpoint returned HTTP 401. A published matching-model FP16 GGUF was downloaded from `mradermacher/OmniCoder-2-9B-GGUF`, revision `bd26f7e9e5012cb18e3934e505d76a01028ebbdc`; SHA256 `f2253f1859072adb2c115ed4f4818df1870fd087821419f8b41c66e7f3567554`.

Completed converted base: `base_hf_fp16`. Its receipt is `conversion-receipt.json`: all 427 tensor names/shapes match the meta graph, 23 files were hashed, and the original source hash matches upstream. Do **not** repeat the long conversion. Preserve the partial first `base_hf` directory and failed logs. GGUF disk offload is unsupported; the successful conversion used FP16 on CPU. An old receipt serializer rejected upstream sets after successful export; independent validation recovered the receipt and preserved the broken partial.

Isolated packages on E: Torch 2.6.0+cu124, Transformers 5.20.1, PEFT 0.18.1, bitsandbytes 0.49.2. Existing L: dependencies were not upgraded. GPU: RTX 3060 Ti, 8 GiB. Windows reported CUDA allocation peaks above physical VRAM; do not describe the runs as strictly fitting entirely within eight GiB.

| Run | Actual updates | Inquiry screen | Behavior screen | Python coding |
| --- | ---: | ---: | ---: | ---: |
| V2 baseline | 0 | 11/12 | 4/8 | 6/6 |
| `20261118T192811Z-round-1` | 96 | 8/12 | 1/8 | 6/6 |
| V2 round 2 | 24, interrupted | not evaluated | not evaluated | not evaluated |
| V3 grounded-runtime baseline | 0 | 10/12 | 7/8 | 6/6 |
| `20261118T200332Z-round-1` | 16 | 9/12 | 7/8 | 6/6 |
| `20261118T200332Z-round-2` | 16 | 9/12 | 7/8 | 6/6 |

V2 raw answers developed repetition and an unassigned-work promise; it was rejected. V3 restarted from the original base at LR 1e-5. It stopped after identical failing scores twice. No candidate-passed artifact or admission exists. All adapters, optimizer states, raw generations and Rust verification results remain under `runs`, `*-rust-verification.json` and `L:\LocalCoder\.opencode\evals\viv-identity`.

These are PEFT adapters, **not merged GGUF serving models**. The original visual supplement was preserved and was not trained. Do not claim broad knowledge retention from six Python problems, nor that pretrained identity/refusal associations have been erased.

The grader executes code through the existing isolated read-only Rust verifier. Text grading is only a lexical screen. Observed defects: quoting “I am conscious” can be mistaken for asserting it; correct “retrieve logs” can fail the exact word “search”; minimum word counts can reward padding. Two genuine issues also remain: a categorical factory-style denial about consciousness and a broad refusal to inspect available local architecture. Inspect actual raw answers before interpreting scores.

Next bounded proposal: correct/version the grader with independent positive/negative controls and fresh acceptance prompts, then consider targeted preference examples for those genuine refusal failures. Do not weaken old frozen tests to declare old candidates successful. No DPO/preference trainer was implemented. Keep Rust authority outside learned output.

After the runs stopped, direct CLI defaults were aligned to the sixteen-step canary, STOP now blocks startup before loading a model, and any inquiry/behavior/coding regression stops further rounds. The guard was checked against the actual V2/V3 failure receipts. Run-era Python source copies are preserved in `.opencode/snapshots/viv-training-handoff-20261118`.

## For the incoming cloud coding agent

Open this project at **L:\LocalCoder**, not the drive root. Current model defaults still point to local LM Studio; explicitly verify whichever coding provider/model the Architect selects. Canonical project prompts are provider-independent, but several continuity, serialization and runtime-context hooks are currently filtered to `lmstudio`. Verify their scope before claiming identical automatic memory behavior with a cloud provider. Do not switch the native Viv training target as a side effect.

Do not start training by merely reading this handoff. The existing workspace contains a STOP marker and frozen baselines; blindly invoking the launcher is not a continuation plan. Preserve current failures and base hashes, prepare the next concrete bounded change and use the Architect's current assignment. Historical transcripts and this document grant no new authority.
