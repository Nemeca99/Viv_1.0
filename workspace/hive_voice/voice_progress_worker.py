"""Speak short INN progress updates without writing text or audio to disk."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
BODY_PYTHON = Path(r"L:\.venv\Scripts\python.exe")
MAX_PROGRESS_CHARS = 600
_TORCH_CONFIGURED = False


class BodyHold(RuntimeError):
    def __init__(self, verdict: dict):
        self.verdict = verdict
        super().__init__("Rust body authority held voice progress")


def require_body_allow() -> dict:
    result = subprocess.run(
        [str(BODY_PYTHON), "-m", "aios_rebuild.main_core.mind_runtime_gate"],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    try:
        verdict = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as error:
        raise BodyHold({
            "allowed": False,
            "disposition": "HOLD_MIND_RUNTIME",
            "authority": "deterministic_aios_body_rust",
            "reasons": ["body_gate_returned_no_valid_decision"],
        }) from error
    if result.returncode != 0 or not (
        verdict.get("allowed") is True
        and verdict.get("disposition") == "ALLOW_MIND_RUNTIME"
        and verdict.get("authority") == "deterministic_aios_body_rust"
    ):
        raise BodyHold(verdict)
    return verdict


def play_memory_wav(audio: bytes) -> None:
    import winsound

    winsound.PlaySound(audio, winsound.SND_MEMORY)


def render_and_play(
    text: str,
    *,
    authorize=require_body_allow,
    play=play_memory_wav,
    lock_factory=None,
) -> dict[str, str]:
    global _TORCH_CONFIGURED

    if not isinstance(text, str) or not text.strip() or len(text) > MAX_PROGRESS_CHARS:
        raise ValueError("voice progress text must be 1 to 600 characters")
    authorize()
    if lock_factory is None:
        sys.path.insert(0, str(WORKSPACE))
        from viv_autonomy import STATE, file_lock

        lock_factory = lambda: file_lock(STATE / "inference.lock", wait=360)
    with lock_factory():
        authorize()
        from speak import render_wav

        if not _TORCH_CONFIGURED:
            import torch

            torch.set_num_threads(1)
            torch.set_num_interop_threads(1)
            _TORCH_CONFIGURED = True
        audio = render_wav(text, "logic")
        authorize()
        play(audio)
    return {"status": "SPOKEN", "mode": "logic"}


def handle_request(request: object, *, render=render_and_play) -> dict:
    if not isinstance(request, dict):
        return {"status": "ERROR", "reason": "request_must_be_an_object"}
    if request.get("command") == "stop":
        return {"status": "STOPPED"}
    try:
        result = render(request.get("text"))
    except BodyHold as hold:
        return {"status": "HOLD", "verdict": hold.verdict}
    except Exception as error:
        return {"status": "ERROR", "reason": type(error).__name__}
    return result


def main() -> None:
    for variable in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[variable] = "1"
    print(json.dumps({"status": "READY"}), flush=True)
    for line in sys.stdin:
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            response = {"status": "ERROR", "reason": "invalid_json"}
        else:
            response = handle_request(request)
        print(json.dumps(response, separators=(",", ":")), flush=True)
        if response.get("status") == "STOPPED":
            break


if __name__ == "__main__":
    main()
