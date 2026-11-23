# Qwen3-only Hive model roster

Inspected 2026-09-28. This is a candidate roster, not an admission decision.
Local machine: 31.9 GiB system RAM, RTX 3060 Ti with 8 GiB VRAM. The live
Rust-led greeting proof ran `qwen3:8b-local` as Mind at 100% GPU residency;
`ollama ps` showed about 5.6 GB for it. The installed `qwen3:1.7b` ran on CPU
in the earlier isolated worker proof. Concurrency and long-context costs are
not yet measured.

| Role | Candidate | Reason to trial | Current state |
| --- | --- | --- | --- |
| Always-loaded Mind | [Qwen3-8B](https://huggingface.co/Qwen/Qwen3-8B) | Conversation, planning, reasoning, coding; thinking mode available | Installed as `qwen3:8b-local`, used in live Rust integration proof |
| Stronger narrow Swarm or alternate Mind | [Qwen3-4B-Instruct-2507](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507) | Updated instruction, coding, tool use, non-thinking, long native context | Not installed in this exact variant; local `qwen3:4b` is a different candidate |
| Small model Swarm | [Qwen3-1.7B](https://huggingface.co/Qwen/Qwen3-1.7B) | Bounded CPU tasks and structured output | Installed as `qwen3:1.7b`; earlier worker proof passed, not a quality admission |
| Very small specialist experiment | [Qwen3-0.6B](https://huggingface.co/Qwen/Qwen3-0.6B) | Narrow classifications or routing only if measured | Not installed as a separate Swarm role |
| Memory retrieval | [Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) | Text/code embeddings, up to 1024 dimensions | Candidate, not integrated |
| Retrieval reranking | [Qwen3-Reranker-0.6B](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B) | Reorder a small retrieved set before Mind context admission | Candidate, not integrated |
| Large coding comparator | [Qwen3-Coder-30B-A3B-Instruct](https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct) | Dedicated agentic coding comparison | Not scheduled for current always-loaded Hive; 30.5B total weights remain a memory cost despite 3.3B active parameters |
| Viv speech output | [Qwen3-TTS-12Hz-1.7B-CustomVoice](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice) | On-demand speech from Viv's final text | Selected candidate; not downloaded or benchmarked |

The first model comparison should use the existing 8B Mind and 1.7B/4B Qwen3
workers on the same bounded task packets, with quality checks before broader
correctness/truth claims. The official Qwen3-4B-Instruct-2507 card reports a
262K native context and non-thinking mode, but local usable context will be
set by measured RAM/VRAM and latency, not the card maximum. Qwen3-Coder-30B
is an optional comparator; its total parameter count means it does not become
a small worker merely because it activates 3.3B parameters per token.

Use a single embedding service and a single reranking service when admitted;
agents do not each need a private copy of either model. TTS receives final
text only and has no task or key authority. It should be loaded on demand after
checking GPU memory or trialed on CPU separately.
