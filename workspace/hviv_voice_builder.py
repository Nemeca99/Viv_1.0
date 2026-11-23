import os
import sys
import time
import json
import subprocess
import threading
import queue
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

class SynchronousAudioStream:
    def __init__(self):
        self.speech_queue = queue.Queue()
        self.worker_thread = threading.Thread(target=self._speech_worker, daemon=True)
        self.worker_thread.start()

    def _speech_worker(self):
        """
        Single-threaded worker ensuring ONLY ONE voice speaks at a time (Sequential Queue).
        """
        while True:
            message = self.speech_queue.get()
            if message is None:
                break
            
            clean_msg = message.replace("'", "").replace('"', '')
            powershell_cmd = f"Add-Type -AssemblyName System.Speech; $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer; $synth.Rate = 1; $synth.Speak('{clean_msg}')"
            try:
                # Synchronous run - waits for speech to FINISH before pulling next message
                subprocess.run(["powershell", "-Command", powershell_cmd], capture_output=True, timeout=10)
            except Exception:
                pass
            
            self.speech_queue.task_done()

    def announce_passively(self, message: str, domain: str = "L:"):
        """
        Queues audio message sequentially. Zero overlap, zero 1000-voice overlap.
        """
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"\n[SEQUENTIAL VOICE STREAM] 🔊 [{domain} | {ts}] \"{message}\"")
        self.speech_queue.put(message)

if __name__ == "__main__":
    print("=== Testing Synchronous Single-Voice Sequential Stream ===")
    audio = SynchronousAudioStream()
    
    audio.announce_passively("Testing voice queue entry one.")
    audio.announce_passively("Testing voice queue entry two.")
    audio.announce_passively("Testing voice queue entry three.")
    
    audio.speech_queue.join()
    print("\n[SUCCESS] Sequential single-voice test complete. Zero overlapping voices.")
