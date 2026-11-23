"""
voice_queue_player.py — Non-blocking Voice Audio Queueing & Overlap Player.
Manages an asynchronous audio playback queue.
Supports sequential playback, queued overlapping audio chunks, and background audio thread.
"""
from __future__ import annotations

import pathlib
import queue
import threading
import time
import winsound

AUDIO_QUEUE: queue.Queue[pathlib.Path] = queue.Queue()
_WORKER_THREAD: threading.Thread | None = None
_RUNNING = True

def _audio_queue_worker():
    """Background worker thread that consumes audio queue without blocking caller."""
    while _RUNNING:
        try:
            audio_path = AUDIO_QUEUE.get(timeout=1.0)
            if audio_path and audio_path.exists():
                # winsound.SND_FILENAME plays synchronously inside worker thread,
                # ensuring queued audio plays cleanly in sequence without cutting off.
                winsound.PlaySound(str(audio_path), winsound.SND_FILENAME)
            AUDIO_QUEUE.task_done()
        except queue.Empty:
            continue
        except Exception as e:
            print(f"[Voice Queue Player Error]: {e}")

def start_voice_queue_worker():
    global _WORKER_THREAD, _RUNNING
    if _WORKER_THREAD is None or not _WORKER_THREAD.is_alive():
        _RUNNING = True
        _WORKER_THREAD = threading.Thread(target=_audio_queue_worker, daemon=True)
        _WORKER_THREAD.start()

def enqueue_audio_playback(path: pathlib.Path):
    """Enqueues WAV file for audio playback."""
    start_voice_queue_worker()
    AUDIO_QUEUE.put(path)

def wait_for_speech_completion():
    """Blocks until current audio in queue completes playing before proceeding to training."""
    AUDIO_QUEUE.join()

if __name__ == "__main__":
    print("Testing Voice Audio Queue Player...")
    start_voice_queue_worker()
