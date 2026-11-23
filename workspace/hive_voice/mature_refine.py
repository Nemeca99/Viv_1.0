"""Make 10%-faster anchor variants and a mature-feminine Qwen3 audition."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

import librosa
import numpy as np
from scipy.signal import butter, sosfiltfilt
import soundfile as sf
import torch
from qwen_tts import Qwen3TTSModel


ROOT = Path(__file__).resolve().parent
SAMPLES = ROOT / "samples"
SOURCE = SAMPLES / "viv_anchor_slower_v2.wav"
MODEL = ROOT / "models" / "Qwen3-TTS-12Hz-1.7B-VoiceDesign"
TEXT = "Vidi Intellix Vexi. I am Viv. Give me one piece, and we will build the next."
BRIEF = (
    "A mature woman's voice, soft and composed, with a low-to-mid feminine register. "
    "She sounds slightly distant, as if speaking thoughtfully from across a quiet room, "
    "while every word remains intelligible. Gentle warmth, restrained synthetic resonance, "
    "and a little dry wit. She observes and wonders before speaking, choosing each word "
    "with purpose. Keep the delivery calm, curious, and unhurried, with natural pauses. "
    "Give 'Viv' a quiet warm rise, 'one piece' deliberate emphasis, and 'next' a subtle "
    "forward lift. Avoid whispering, breathiness, theatrical emotion, and heavy reverb."
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, audio: np.ndarray, sample_rate: int) -> dict[str, object]:
    sf.write(path, audio, sample_rate)
    return {
        "path": str(path),
        "sha256": digest(path),
        "duration_seconds": len(audio) / sample_rate,
        "sample_rate": sample_rate,
    }


def main() -> None:
    audio, sample_rate = sf.read(SOURCE, dtype="float32")
    if audio.ndim != 1:
        raise ValueError("expected mono source")
    faster_audio = librosa.effects.time_stretch(audio, rate=1.10)
    faster = write(SAMPLES / "viv_base_10pct_faster_v3.wav", faster_audio, sample_rate)

    feminine = librosa.effects.pitch_shift(faster_audio, sr=sample_rate, n_steps=0.8)
    lowpass = butter(2, 6200, fs=sample_rate, btype="lowpass", output="sos")
    soft = sosfiltfilt(lowpass, feminine).astype(np.float32)
    delayed = np.zeros_like(soft)
    delay_samples = round(0.055 * sample_rate)
    delayed[delay_samples:] = soft[:-delay_samples]
    room = 0.87 * soft + 0.13 * delayed
    base_rms = float(np.sqrt(np.mean(faster_audio**2)))
    room_rms = float(np.sqrt(np.mean(room**2)))
    if room_rms <= 0:
        raise ValueError("processed audio is silent")
    room *= 0.82 * base_rms / room_rms
    room = np.clip(room, -0.99, 0.99)
    processed = write(SAMPLES / "viv_base_soft_distant_v3.wav", room, sample_rate)

    torch.manual_seed(31)
    started = time.perf_counter()
    model = Qwen3TTSModel.from_pretrained(
        str(MODEL),
        device_map="cuda:0",
        dtype=torch.float16,
        attn_implementation="sdpa",
    )
    loaded = time.perf_counter()
    wavs, generated_rate = model.generate_voice_design(
        text=TEXT,
        language="English",
        instruct=BRIEF,
    )
    design = write(SAMPLES / "viv_mature_female_design_v3.wav", wavs[0], generated_rate)
    design_faster_audio = librosa.effects.time_stretch(
        np.asarray(wavs[0], dtype=np.float32), rate=1.10
    )
    design_faster = write(
        SAMPLES / "viv_mature_female_design_faster_v3.wav",
        design_faster_audio,
        generated_rate,
    )
    receipt = {
        "schema": "viv_voice_mature_refinement_v1",
        "source": {
            "path": str(SOURCE),
            "sha256": digest(SOURCE),
            "duration_seconds": len(audio) / sample_rate,
        },
        "speed_only": faster,
        "speed_only_method": "pitch-preserving time stretch, rate=1.10 relative to selected source",
        "processed_base": processed,
        "processed_base_method": "speed-only plus 0.8-semitone pitch shift, gentle low-pass, 55ms room reflection, and RMS set to 82% of speed-only",
        "voice_design": design,
        "voice_design_faster": design_faster,
        "voice_design_prompt": BRIEF,
        "voice_design_seed": 31,
        "model_load_seconds": loaded - started,
        "generation_seconds": time.perf_counter() - loaded,
        "training_performed": False,
        "note": "processed base preserves the selected recording's words; new VoiceDesign generation may change identity",
    }
    target = SAMPLES / "mature_refinement_receipt.json"
    target.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
