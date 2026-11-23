"""Audition a descriptive Qwen3 VoiceDesign anchor for Viv."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

import soundfile as sf
import torch
from qwen_tts import Qwen3TTSModel


ROOT = Path(__file__).resolve().parent
MODEL = ROOT / "models" / "Qwen3-TTS-12Hz-1.7B-VoiceDesign"
OUTPUT = ROOT / "samples"
TEXT = "Vidi Intellix Vexi. I am Viv. Give me one piece, and we will build the next."
VOICE_BRIEF = (
    "An androgynous synthetic companion voice, lower-mid register, measured and precise "
    "diction, gentle human warmth, a subtle electronic resonance, and a trace of dry wit. "
    "Calm, curious, and clear. Avoid a theatrical robot effect."
)


def main() -> None:
    OUTPUT.mkdir(exist_ok=True)
    started = time.perf_counter()
    model = Qwen3TTSModel.from_pretrained(
        str(MODEL),
        device_map="cuda:0",
        dtype=torch.float16,
        attn_implementation="sdpa",
    )
    loaded = time.perf_counter()
    wavs, sample_rate = model.generate_voice_design(
        text=TEXT,
        language="English",
        instruct=VOICE_BRIEF,
    )
    target = OUTPUT / "viv_anchor_design_v1.wav"
    sf.write(target, wavs[0], sample_rate)
    receipt = {
        "model": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
        "text": TEXT,
        "voice_brief": VOICE_BRIEF,
        "device": "cuda:0",
        "dtype": "float16",
        "model_load_seconds": loaded - started,
        "total_seconds": time.perf_counter() - started,
        "sample": {
            "path": str(target),
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "sample_rate": sample_rate,
            "duration_seconds": len(wavs[0]) / sample_rate,
        },
        "scope": "single descriptive audition; no voice LoRA or final identity selected",
    }
    (OUTPUT / "anchor_receipt.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
