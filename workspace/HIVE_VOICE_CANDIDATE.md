# Viv speech output candidate

Architect selection: `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice` for Viv's optional
text-to-speech output. Source: https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice

Inspected 2026-09-28. The official model card describes ten supported major
languages, streaming output, instruction-controlled style, and nine preset
speakers. `CustomVoice` controls style over those preset timbres. The separate
`VoiceDesign` variant is the one intended for a voice described in natural
language. No voice choice or speaker-switching rule is fixed yet.

The Hub repository currently reports about 4.60 GB of files including a
separate speech tokenizer model, at revision
`0c0e3051f131929182e2c023b9537f8b1c68adfe`. This is a planning figure,
not measured runtime memory. The active Qwen3 8B Mind occupied about 5.6 GB
and reported 100% GPU residency in the local integration proof. On the 8 GB
GPU, treat TTS as an on-demand stage with a resource admission check; do not
assume both models can remain on the GPU at once. CPU TTS latency is unmeasured.

Speech receives only Viv's final approved text. It has no task, tool, key,
snapshot, or index authority. This model has not been downloaded or benchmarked
in LocalCoder; the current architecture proof remains text-only.
