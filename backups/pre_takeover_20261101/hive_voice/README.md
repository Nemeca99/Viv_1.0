# Viv voice

## Local text-to-WAV converter

`converter_app.py` is a loopback-only utility that renders text with the two
Architect-selected Hive reference voices and returns a standalone WAV. The
8B Queen uses the default reference `samples/viv_mature_female_design_v3.wav`;
1.7B drones use the faster reference
`samples/viv_mature_female_design_faster_v3.wav`. The local Qwen TTS model and
each voice prompt are loaded lazily and reused while the converter process is
running. Both speaker classes use that same voice renderer; only the reference
clip changes. Start it with the voice environment:

```powershell
L:\LocalCoder\workspace\hive_voice\.venv\Scripts\python.exe L:\LocalCoder\workspace\hive_voice\converter_app.py
```

Then open `http://127.0.0.1:8765/`. The app has no account, network egress,
history, transcript, or file output. New audio stays in a bounded process-RAM
ticket until a complete download or the 24-hour expiry; interrupted downloads
can resume with HTTP `Range`. The gate is checked before each TTS render, and
only the Rust body authority can permit it. The UI accepts up to 6,000
characters; an omitted voice selection defaults to the Queen voice.

This is an engineering boundary, not a claim about operating-system paging:
Windows may page process memory to disk. The app does not alter pagefile or
swap configuration. It does not implement billing, cloud hosting, OCR, audio
transcription, vision input, or multi-speaker stitching. Existing `speak.py`
remains compatible with the current Viv chat playback path and retains its
historical output/receipt behavior; the converter does not call that path.

Mocked converter tests run without loading TTS or accessing the GPU:

```powershell
L:\.venv\Scripts\python.exe -m unittest workspace.hive_voice.test_converter_app
```

The Architect selected two final reference clips. Companion replies use
`samples/viv_mature_female_design_v3.wav` (human voice); Build replies use
`samples/viv_mature_female_design_faster_v3.wav` (logic/Swarm voice). Each
completed top-level OpenCode reply gets exactly one voice. The project plugin
`.opencode/plugins/voice.js` queues a detached voice job after the text is
complete. `speak.py` serializes jobs with a file lock so they do not overlap,
unloads the allowed Ollama text model to free the 8 GB GPU, clones the selected
reference with the local Qwen3-TTS Base model, and plays the resulting WAV.
The next text turn reloads the Ollama model as needed. The voice is generated
from the actual reply; no voice LoRA has been trained.

Viv has one external mouth. A Mind-only reply uses the human/conversation voice.
When the Mind synthesizes one or more Swarm contributions, the single final
reply uses the unified logic/Swarm voice. Worker identities and outputs remain
in the audit trace and are never played as separate external speakers.

Every generated reply is retained in `outputs/` as a WAV and matching UTF-8
`.txt`. The transcript records the full text reply, the spoken text after
Markdown/code filtering, the selected mode, the reference filename, and the
OpenCode message/session IDs. `runtime/voice_events.jsonl` records playback
status and hashes. Long messages speak at most 1,800 cleaned characters and
say that the rest is on screen; the full text remains in the transcript.
Autoplay begins shortly after the text finishes and can continue after a
short-lived `opencode run` command exits. Playback is local to Windows.

## Earlier auditions

The Qwen3 CustomVoice model produced two English preset auditions from Viv's
text: `samples/archived_voices/viv_aiden_audition.wav` and `samples/archived_voices/viv_ryan_audition.wav`.
The Qwen3 VoiceDesign model produced `samples/archived_voices/viv_anchor_design_v1.wav` from
a descriptive anchor: androgynous, measured, warm, gently synthetic, curious,
and dry-witted. This approximates the Architect's Jarvis/Ava/GLaDOS blend as
qualities to assess, without claiming to reproduce those characters' voices.

All three clips are experiments. `samples/audition_receipt.json` and
`samples/anchor_receipt.json` record text, duration, CUDA device, timing, and
audio hashes. The models were loaded on demand after freeing the 8 GB GPU from
the text Mind. The clips are separate voices; a multi-voice Hive output and
voice LoRA have not been built or selected.

The Architect selected `viv_anchor_design_v1.wav` as the reference sound. The
next pass kept it intact and produced `samples/archived_voices/viv_anchor_slower_v2.wav` with
pitch-preserving 0.94-speed timing and five small pause extensions. A separate
VoiceDesign take targets inflection on “Viv,” “one piece,” and “next”; its
slowed version is `samples/archived_voices/viv_anchor_refined_v2.wav`. A second passage,
`samples/archived_voices/viv_pondering_v1.wav`, tests a reflective, open-ended “Who am I?”
delivery. These are auditions. The model may vary its timbre between
generations; `samples/voice_finish_receipt.json` records the audio hashes,
timing edits, and prompt. No voice weights were trained.

The selected `viv_anchor_slower_v2.wav` then became the source for a 10%-faster
pitch-preserving edit, `samples/archived_voices/viv_base_10pct_faster_v3.wav` (7.07 seconds).
`samples/archived_voices/viv_base_soft_distant_v3.wav` keeps that timing and applies a subtle
pitch, EQ, room reflection, and level matched to 82% of the faster base as a reversible approximation of
the requested softer, more distant mature-feminine sound. A separate Qwen3
VoiceDesign audition, `samples/viv_mature_female_design_faster_v3.wav`, uses a
voice prompt and a 10% timing increase over its own raw take. The Architect
subsequently selected that clip and its original take as the two current
references above. The earlier alternatives remain separate;
`samples/mature_refinement_receipt.json` records hashes and settings. No voice
weights were trained.
