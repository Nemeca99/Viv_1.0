"""Speak one completed Viv message using her selected Qwen3 reference voice."""

from __future__ import annotations

import os
import warnings

# Suppress PyTorch/pynvml deprecation warnings & noise
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)
os.environ["PYTHONWARNINGS"] = "ignore"

import argparse
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock

ROOT = Path(__file__).resolve().parent
SAMPLES = ROOT / "samples"
RUNTIME = ROOT / "runtime"
OUTPUTS = ROOT / "outputs"
MODEL = ROOT / "models" / "Qwen3-TTS-12Hz-1.7B-Base"
REFERENCE_TEXT = (
    "Vidi Intellix Vexi. I am Viv. Give me one piece, and we will build the next."
)
REFERENCES = {
    "human": (
        SAMPLES / "viv_mature_female_design_v3.wav",
        "8251bce22b460b4c5e000f8078600545628964d75a178568916acf3644094407",
    ),
    "logic": (
        SAMPLES / "viv_mature_female_design_faster_v3.wav",
        "af85d206262db7520015ab2668ebef5f52428ec2915d41f19767dd42078eddd2",
    ),
}
ALLOWED_OLLAMA_MODELS = {"qwen3:8b-local", "qwen3:8b-local-32k"}
MAX_SPOKEN_CHARS = 1800
_CONVERTER_MODEL = None
_CONVERTER_PROMPTS: dict[str, object] = {}


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def spoken_text(raw: str) -> str:
    """Keep reply prose; never feed model code blocks, commands, or URLs as speech."""
    text = re.sub(r"```[\s\S]*?```", " ", raw)
    text = re.sub(r"!\[([^]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"(?m)^\s{0,3}(?:#{1,6}|>|[-*+]\s|\d+\.\s)", " ", text)
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > MAX_SPOKEN_CHARS:
        end = text.rfind(". ", 0, MAX_SPOKEN_CHARS)
        text = text[: end + 1 if end > 250 else MAX_SPOKEN_CHARS].strip()
        text += " The rest is on screen."
    return text


def chunks(text: str, limit: int = 330) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    result: list[str] = []
    current = ""
    for sentence in sentences:
        if not sentence:
            continue
        if len(sentence) > limit:
            if current:
                result.append(current)
                current = ""
            words = sentence.split()
            piece = ""
            for word in words:
                candidate = f"{piece} {word}".strip()
                if len(candidate) > limit and piece:
                    result.append(piece)
                    piece = word
                else:
                    piece = candidate
            if piece:
                result.append(piece)
            continue
        candidate = f"{current} {sentence}".strip()
        if len(candidate) > limit and current:
            result.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        result.append(current)
    return result


def verify_reference(mode: str) -> Path:
    reference, expected = REFERENCES[mode]
    if digest(reference.read_bytes()) != expected:
        raise ValueError("selected voice reference hash changed")
    return reference


def free_gpu(model_id: str | None) -> None:
    if model_id is None:
        return
    if model_id not in ALLOWED_OLLAMA_MODELS:
        raise ValueError("OpenCode model outside voice resource allowlist")
    result = subprocess.run(
        ["ollama", "stop", model_id],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Ollama unload failed: {result.stderr.strip()}")


def play_wav(path: Path) -> None:
    try:
        from voice_queue_player import enqueue_audio_playback
        enqueue_audio_playback(path)
    except Exception:
        import winsound
        winsound.PlaySound(str(path), winsound.SND_FILENAME)


def speak(
    request: dict[str, str], *, play: bool, save_probe: bool = False
) -> dict[str, object]:
    import librosa
    import numpy as np
    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel

    mode = request.get("mode")
    if mode not in REFERENCES:
        raise ValueError("voice mode must be human or logic")
    raw = request.get("text", "")
    if not isinstance(raw, str):
        raise TypeError("text must be a string")
    text = spoken_text(raw)
    if not text:
        return {"status": "SKIP_EMPTY", "mode": mode}
    reference = verify_reference(mode)
    free_gpu(request.get("model_id"))
    started = time.perf_counter()
    model = Qwen3TTSModel.from_pretrained(
        str(MODEL),
        device_map="cuda:0",
        dtype=torch.float16,
        attn_implementation="sdpa",
    )
    loaded = time.perf_counter()
    prompt = model.create_voice_clone_prompt(
        ref_audio=str(reference),
        ref_text=REFERENCE_TEXT,
        x_vector_only_mode=False,
    )
    outputs: list[dict[str, object]] = []
    audio_parts: list[np.ndarray] = []
    output_rate: int | None = None
    for index, piece in enumerate(chunks(text)):
        wavs, sample_rate = model.generate_voice_clone(
            text=piece,
            language="English",
            voice_clone_prompt=prompt,
        )
        if output_rate is not None and sample_rate != output_rate:
            raise ValueError("voice chunk sample rate changed")
        output_rate = sample_rate
        audio = np.asarray(wavs[0], dtype=np.float32)
        if mode == "logic":
            audio = librosa.effects.time_stretch(audio, rate=1.10)
        if index:
            audio_parts.append(np.zeros(round(sample_rate * 0.24), dtype=np.float32))
        audio_parts.append(audio)
        outputs.append(
            {
                "index": index,
                "chars": len(piece),
                "duration_seconds": len(audio) / sample_rate,
            }
        )
    OUTPUTS.mkdir(exist_ok=True)
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", request.get("message_id", "message"))[:64]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    stem = f"{stamp}_{time.time_ns()}_{safe_id}_{mode}"
    audio_file = OUTPUTS / f"{stem}.wav"
    transcript_file = OUTPUTS / f"{stem}.txt"
    sf.write(audio_file, np.concatenate(audio_parts), output_rate)
    transcript_file.write_text(
        f"Voice: {mode}\nMessage ID: {request.get('message_id', '')}\n"
        f"Session ID: {request.get('session_id', '')}\n"
        f"Reference: {reference.name}\n\nFull message:\n{raw}\n\n"
        f"Spoken text:\n{text}\n",
        encoding="utf-8",
    )
    if save_probe:
        shutil.copyfile(audio_file, RUNTIME / f"probe_{mode}.wav")
    if play:
        play_wav(audio_file)
    return {
        "status": "PLAYED" if play else "GENERATED",
        "mode": mode,
        "message_id": request.get("message_id", ""),
        "session_id": request.get("session_id", ""),
        "text_sha256": digest(text.encode("utf-8")),
        "audio_sha256": digest(audio_file.read_bytes()),
        "audio_file": str(audio_file),
        "transcript_file": str(transcript_file),
        "spoken_chars": len(text),
        "reference_sha256": digest(reference.read_bytes()),
        "model": "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
        "model_load_seconds": loaded - started,
        "total_seconds": time.perf_counter() - started,
        "parts": outputs,
    }


def render_wav(text: str, mode: str) -> bytes:
    """Render the selected Viv voice to a WAV held only in process memory."""
    global _CONVERTER_MODEL

    import librosa
    import numpy as np
    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel

    if mode not in REFERENCES:
        raise ValueError("voice mode must be human or logic")
    text = text.strip()
    if not text:
        raise ValueError("text is empty after speech cleanup")
    reference = verify_reference(mode)
    if _CONVERTER_MODEL is None:
        _CONVERTER_MODEL = Qwen3TTSModel.from_pretrained(
            str(MODEL), device_map="cuda:0", dtype=torch.float16,
            attn_implementation="sdpa",
        )
    model = _CONVERTER_MODEL
    if mode not in _CONVERTER_PROMPTS:
        _CONVERTER_PROMPTS[mode] = model.create_voice_clone_prompt(
            ref_audio=str(reference), ref_text=REFERENCE_TEXT,
            x_vector_only_mode=False,
        )
    prompt = _CONVERTER_PROMPTS[mode]
    audio_parts: list[np.ndarray] = []
    output_rate: int | None = None
    for index, piece in enumerate(chunks(text)):
        wavs, sample_rate = model.generate_voice_clone(
            text=piece, language="English", voice_clone_prompt=prompt,
        )
        if output_rate is not None and sample_rate != output_rate:
            raise ValueError("voice chunk sample rate changed")
        output_rate = sample_rate
        audio = np.asarray(wavs[0], dtype=np.float32)
        if mode == "logic":
            audio = librosa.effects.time_stretch(audio, rate=1.10)
        if index:
            audio_parts.append(np.zeros(round(sample_rate * 0.24), dtype=np.float32))
        audio_parts.append(audio)
    buffer = io.BytesIO()
    sf.write(
        buffer, np.concatenate(audio_parts), output_rate,
        format="WAV", subtype="PCM_16",
    )
    return buffer.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-play", action="store_true")
    parser.add_argument("--save-probe", action="store_true")
    parser.add_argument("--request", type=Path)
    args = parser.parse_args()
    RUNTIME.mkdir(exist_ok=True)
    if args.request:
        raw = args.request.read_text(encoding="utf-8-sig")
        args.request.unlink()
        request = json.loads(raw)
        # Double-encoded guard: if JSON decoded to a string, parse again
        if isinstance(request, str):
            request = json.loads(request)
    else:
        raw = sys.stdin.read()
        request = json.loads(raw)
        if isinstance(request, str):
            request = json.loads(request)
    try:
        with FileLock(str(RUNTIME / "voice_worker.lock"), timeout=300):
            receipt = speak(request, play=not args.no_play, save_probe=args.save_probe)
    except Exception as exc:  # noqa: BLE001 - retain a failure receipt for voice jobs
        _req = request if isinstance(request, dict) else {}
        receipt = {
            "status": "HOLD",
            "reason": f"{type(exc).__name__}: {exc}",
            "mode": _req.get("mode"),
            "message_id": _req.get("message_id", ""),
        }
    with (RUNTIME / "voice_events.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(receipt, ensure_ascii=False) + "\n")
    print(json.dumps(receipt, ensure_ascii=False))
    if receipt["status"] == "HOLD":
        raise SystemExit(1)
    
    # Wait for background queue worker thread to finish playing complete WAV audio out loud
    try:
        from voice_queue_player import wait_for_speech_completion
        wait_for_speech_completion()
    except Exception:
        pass


if __name__ == "__main__":
    main()
