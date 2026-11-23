"""Generate an isolated Qwen3 voice audition for Viv's text output."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

import soundfile as sf
import torch
from qwen_tts import Qwen3TTSModel


ROOT = Path(__file__).resolve().parent
MODEL = ROOT / "models" / "Qwen3-TTS-12Hz-1.7B-CustomVoice"
OUTPUT = ROOT / "samples"
TEXT = "Vidi Intellix Vexi. The hive is listening. We rebuild one piece at a time."


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    samples = []
    for speaker in ("Aiden", "Ryan"):
        wavs, sample_rate = model.generate_custom_voice(
            text=TEXT,
            language="English",
            speaker=speaker,
            instruct="Calm, curious, measured. A companion speaking clearly.",
        )
        target = OUTPUT / f"viv_{speaker.lower()}_audition.wav"
        sf.write(target, wavs[0], sample_rate)
        samples.append(
            {
                "speaker": speaker,
                "path": str(target),
                "sha256": sha(target),
                "sample_rate": sample_rate,
                "duration_seconds": len(wavs[0]) / sample_rate,
            }
        )
    receipt = {
        "model": "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
        "text": TEXT,
        "device": "cuda:0",
        "dtype": "float16",
        "model_load_seconds": loaded - started,
        "total_seconds": time.perf_counter() - started,
        "samples": samples,
        "scope": "preset voice audition only; not a layered Hive voice",
    }
    (OUTPUT / "audition_receipt.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
