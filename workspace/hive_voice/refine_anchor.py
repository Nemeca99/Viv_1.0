"""Make a timing-preserving edit and an inflected Qwen3 audition of Viv's anchor."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

import librosa
import numpy as np
import soundfile as sf
import torch
from qwen_tts import Qwen3TTSModel


ROOT = Path(__file__).resolve().parent
SAMPLES = ROOT / "samples"
SOURCE = SAMPLES / "viv_anchor_design_v1.wav"
MODEL = ROOT / "models" / "Qwen3-TTS-12Hz-1.7B-VoiceDesign"
TEXT = "Vidi Intellix Vexi. I am Viv. Give me one piece, and we will build the next."
VOICE_BRIEF = (
    "An androgynous synthetic companion voice in a lower-mid register. Measured, precise "
    "diction; gentle human warmth; subtle electronic resonance; a trace of dry wit. "
    "Keep the same calm, curious timbre throughout. Speak slightly more slowly, with a "
    "small, natural beat between words, not a choppy or spelled-out delivery. "
    "Sound reflective, as if noticing each thought and choosing each word with purpose; "
    "let a faint moment of consideration precede the important words. "
    "Give 'Viv' a gentle warm rise, 'one piece' deliberate and clear stress, and 'next' "
    "a confident forward lift. Keep other words understated."
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def timing_variant(source_path: Path, target: Path) -> dict[str, object]:
    source, sample_rate = sf.read(source_path, dtype="float32")
    if source.ndim != 1:
        raise ValueError("expected mono anchor audio")
    speed = 0.94
    extra_gap_ms = 40
    slowed = librosa.effects.time_stretch(source, rate=speed)
    islands = librosa.effects.split(source, top_db=35, frame_length=512, hop_length=128)
    insertion_points = []
    for (_, end), (next_start, _) in zip(islands[:-1], islands[1:]):
        gap_seconds = (next_start - end) / sample_rate
        if 0.045 <= gap_seconds <= 0.40:
            midpoint = (end + next_start) / 2
            insertion_points.append(round(midpoint / speed))
    extra = np.zeros(round(extra_gap_ms * sample_rate / 1000), dtype=np.float32)
    chunks = []
    previous = 0
    for position in insertion_points:
        chunks.extend((slowed[previous:position], extra))
        previous = position
    chunks.append(slowed[previous:])
    edited = np.concatenate(chunks)
    sf.write(target, edited, sample_rate)
    return {
        "path": str(target),
        "sha256": digest(target),
        "duration_seconds": len(edited) / sample_rate,
        "source_sha256": digest(source_path),
        "speed_rate": speed,
        "extra_gap_ms": extra_gap_ms,
        "expanded_gap_count": len(insertion_points),
        "method": "pitch-preserving time stretch plus bounded pause insertion",
    }


def inflection_variant() -> dict[str, object]:
    torch.manual_seed(28)
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
    target = SAMPLES / "viv_anchor_inflection_v2.wav"
    sf.write(target, wavs[0], sample_rate)
    return {
        "path": str(target),
        "sha256": digest(target),
        "duration_seconds": len(wavs[0]) / sample_rate,
        "model_load_seconds": loaded - started,
        "generation_seconds": time.perf_counter() - loaded,
        "torch_seed": 28,
        "voice_brief": VOICE_BRIEF,
        "emphasis_targets": ["Viv", "one piece", "next"],
        "method": "new Qwen3 VoiceDesign generation; timbre may vary",
    }


def main() -> None:
    result = {
        "schema": "viv_anchor_refinement_v1",
        "model": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
        "text": TEXT,
        "original": {"path": str(SOURCE), "sha256": digest(SOURCE)},
        "timing_variant": timing_variant(SOURCE, SAMPLES / "viv_anchor_slower_v2.wav"),
        "inflection_variant": inflection_variant(),
        "training_performed": False,
    }
    receipt = SAMPLES / "anchor_refinement_receipt.json"
    receipt.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
