# Harness layers

The model is one layer. The capability lives in the harness. OpenCode is the
agentic harness; each layer below adds tools or control without changing the
voice.

## Layers

| Layer | What it adds | Where it lives |
|---|---|---|
| 0. Model provider | The voice: LM Studio (tool-capable local) or Viv's 319M bridge | `opencode.json` `providers`, `viv_openai_server.py` |
| 1. OpenCode core tools | read, write, edit, shell, glob, grep, task, etc. | OpenCode runtime |
| 2. MCP servers | `aios_router` (STM/LTM, receipts), `openpets` | `opencode.json` `mcp.servers` |
| 3. Plugins | assignment gate, body gate, law enforcement | `.opencode/plugins/` |
| 4. Rust body | deterministic gates, security core, receipts | `workspace/aios_rebuild/local_security_core` |
| 5. Project context | `AGENTS.md`, skills, session summaries | `.opencode/`, `AGENTS.md` |
| 6. Viv control surfaces | turn policy, boundary/treaty, safety, memory, chunked release | `workspace/autonomy/*.py` |

## Two model roles

- **Driver** — tool-capable local model (currently `lmstudio/omnicoder-2-9b`).
  It reads the harness tool schemas and calls tools.
- **Voice** — Viv's checkpoint (`Viv_1_0_319M`). It speaks through the turn
  policy and safety gate. It is not a reliable tool-caller yet; a router can
  send dialogue to the voice and tool turns to the driver.

### Shared-GPU variant (current)

Viv is only 319M, so both models can share the 8 GB card:

| Model | Placement | Approx VRAM |
|---|---|---|
| Viv 319M bridge | GPU | ~3.5 GB |
| OmniCoder 9B Q4 | partial GPU offload, rest CPU | ~4 GB (16–20 layers) |

Order: start the Viv bridge first, then load OmniCoder in LM Studio with the
remaining VRAM. Total is near the 8 GB ceiling: keep context small, watch WDDM
`Shared Usage`, and keep the 250-step checkpoints in case of a driver reset.

## Live local servers (2026-11-22)

| Role | Command | Port | PID | Context / layers |
|---|---|---|---|---|
| Viv voice | `.opencode/start_viv_bridge.ps1` | 8001 | 2625052 | 128 / GPU |
| OmniCoder driver | `.opencode/start_omnicoder.ps1` | 1235 | 1976440 | 16384 / 16 GPU layers |

`opencode.json` now points the `lmstudio` provider at `http://127.0.0.1:1235/v1`
(OmniCoder via llama.cpp) and adds `viv-local` at
`http://127.0.0.1:8001/v1`. Context is 16384 and input is text-only. The config
backup is `opencode.json.bak-20261122-llamacpp`.

Measured: OmniCoder plain turn ~1.2 s, tool call ~5.5 s; Viv identity/close/
safety turns released through the gate. GPU at ~6.1 GB used, ~1.9 GB free. If
headroom is needed, restart OmniCoder with `-ngl 12` or `-c 8192`.

## Pointing OpenCode at Viv's voice

LM Studio cannot load the raw `.pt`. Run the bridge:

```
L:\.venv\Scripts\python.exe -B L:\LocalCoder\workspace\autonomy\viv_openai_server.py \
  --checkpoint L:\LocalCoder\models\viv_bpe\20261122T191316Z\model.pt --port 8001
```

Then add this provider to the OpenCode config (merge; do not overwrite the
Architect's file):

```json
"viv-local": {
  "settings": { "baseURL": "http://127.0.0.1:8001/v1" },
  "models": {
    "viv-1.0-319m": {
      "name": "Viv 1.0 319M (local)",
      "limit": { "context": 128, "output": 96 }
    }
  }
}
```

Select `viv-local/viv-1.0-319m` for dialogue. The bridge returns the released
turn (after policy, chunk verification, safety, and label cleanup) or an empty
string when the body holds the turn.

## What layering buys

- Add an MCP server: she can retrieve memory, read the Wikipedia SQL corpus, or
  drive another service.
- Add a plugin: every tool call passes a deterministic gate before execution.
- Add the Rust body: receipts and one-shot permits, not model prose.
- Add a skill: a workflow the harness can load without retraining the voice.

The model can stay fixed while the harness grows. That is the point.
