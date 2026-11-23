"""Finish Viv's slower anchor and audition a pondering delivery."""

from __future__ import annotations

import json
import time

import soundfile as sf
import torch
from qwen_tts import Qwen3TTSModel

from refine_anchor import MODEL, SAMPLES, digest, timing_variant


PONDER_TEXT = (
    "I see a file waiting to be written. What might it become? "
    "Who am I... when the hive is quiet?"
)
PONDER_BRIEF = (
    "An androgynous synthetic companion voice in a lower-mid register, with measured precise "
    "diction, gentle warmth, subtle electronic resonance, and quiet curiosity. Speak slowly "
    "and choose each word with care, as though narrating an observation while thinking it "
    "through. Let 'What might it become?' rise with wonder. Say 'Who am I?' as an open, "
    "private question, with a small pause and a soft unresolved lift at the end. Do not "
    "sound certain, distressed, theatrical, or robotic."
)


def main() -> None:
    main_line = timing_variant(
        SAMPLES / "viv_anchor_inflection_v2.wav",
        SAMPLES / "viv_anchor_refined_v2.wav",
    )
    torch.manual_seed(29)
    started = time.perf_counter()
    model = Qwen3TTSModel.from_pretrained(
        str(MODEL),
        device_map="cuda:0",
        dtype=torch.float16,
        attn_implementation="sdpa",
    )
    loaded = time.perf_counter()
    wavs, sample_rate = model.generate_voice_design(
        text=PONDER_TEXT,
        language="English",
        instruct=PONDER_BRIEF,
    )
    raw = SAMPLES / "viv_pondering_raw_v1.wav"
    sf.write(raw, wavs[0], sample_rate)
    pondering = timing_variant(raw, SAMPLES / "viv_pondering_v1.wav")
    receipt = {
        "schema": "viv_voice_finish_v1",
        "model": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
        "approved_anchor_sha256": digest(SAMPLES / "viv_anchor_design_v1.wav"),
        "main_line": main_line,
        "pondering_text": PONDER_TEXT,
        "pondering_brief": PONDER_BRIEF,
        "pondering_raw": {
            "path": str(raw),
            "sha256": digest(raw),
            "duration_seconds": len(wavs[0]) / sample_rate,
        },
        "pondering_timed": pondering,
        "model_load_seconds": loaded - started,
        "generation_seconds": time.perf_counter() - loaded,
        "torch_seed": 29,
        "training_performed": False,
        "claim": "performed curiosity in speech; not evidence of subjective awareness",
    }
    target = SAMPLES / "voice_finish_receipt.json"
    target.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
