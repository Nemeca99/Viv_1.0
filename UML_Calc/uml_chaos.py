import threading
import time
import os
import math
import tempfile
import uml_telemetry  # <-- Import the gauges for the test

# ==========================================
# SECTION 1: VARIABLES (Tuning Knobs)
# ==========================================
DEFAULT_THREADS = 4
DEFAULT_INTENSITY = 0.9  # 0.0 to 1.0 (how hard it burns)

# ==========================================
# SECTION 2: MAIN FUNCTIONS (The Stress Engine)
# ==========================================
class Saboteur:
    def __init__(self, threads=DEFAULT_THREADS, intensity=DEFAULT_INTENSITY):
        self.threads = threads
        self.intensity = intensity
        self.stop_event = threading.Event()
        self.workers = []
        self.active = False

    def _burn_cpu(self):
        """Duty-cycled CPU stress."""
        x = 0.12345
        while not self.stop_event.is_set():
            burn_time = 0.05 * self.intensity
            end_time = time.time() + burn_time
            while time.time() < end_time:
                x = math.sin(x * 1.00001 + 1e-6) * math.cos(x + 0.1)
            time.sleep(max(0.0, 0.05 - burn_time))

    def _churn_memory(self):
        """Allocates and touches memory in a loop."""
        while not self.stop_event.is_set():
            try:
                data = bytearray(10 * 1024 * 1024) # 10MB chunk
                for i in range(0, len(data), 4096):
                    data[i] = (i // 4096) % 256
                del data
            except MemoryError:
                pass
            time.sleep(0.01)

    def _thrash_io(self):
        """Writes and deletes temp files rapidly."""
        while not self.stop_event.is_set():
            try:
                with tempfile.NamedTemporaryFile(delete=True) as f:
                    f.write(os.urandom(1024 * 64))
                    f.flush()
                    os.fsync(f.fileno())
            except Exception:
                pass
            time.sleep(0.05)

    def start(self):
        if self.active:
            return
        self.active = True
        self.stop_event.clear()
        
        # Spawn CPU threads
        for _ in range(self.threads):
            t = threading.Thread(target=self._burn_cpu, daemon=True)
            t.start()
            self.workers.append(t)
            
        # Spawn 1 memory thread and 1 IO thread
        self.workers.append(threading.Thread(target=self._churn_memory, daemon=True))
        self.workers.append(threading.Thread(target=self._thrash_io, daemon=True))
        
        for w in self.workers[-2:]:
            w.start()

    def stop(self):
        if not self.active:
            return
        self.stop_event.set()
        for t in self.workers:
            t.join(timeout=1.0)
        self.workers = []
        self.active = False

# ==========================================
# SECTION 3: STANDALONE TEST BLOCK (With Live Telemetry)
# ==========================================
if __name__ == "__main__":
    print("=" * 50)
    print("  DYNAMOMETER + LIVE TELEMETRY TEST")
    print("=" * 50)
    print("Starting Dynamometer...")
    print("Watch the temperature climb and clock ratio throttle.")
    print("Press Ctrl+C to stop.\n")
    
    sab = Saboteur(threads=4, intensity=0.9)
    sab.start()
    
    start_time = time.time()
    
    try:
        while True:
            m = uml_telemetry.get_all_metrics()
            
            temp = f"{m['cpu_temp']:.1f}C"
            ram = f"{m['ram_pct']:.1f}%"
            clk = f"{m['clock_ratio']:.2f}x"
            elapsed = int(time.time() - start_time)
            
            print(f"[{elapsed:02d}s] CPU: {temp} | RAM: {ram} | Clock: {clk}")
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\nStopping chaos engine...")
        sab.stop()
        print("Stopped.")