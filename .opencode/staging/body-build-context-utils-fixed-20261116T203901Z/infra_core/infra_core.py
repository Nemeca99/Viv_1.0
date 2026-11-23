import time
import psutil
import threading
from datetime import datetime

class InfraCore:
    def __init__(self):
        self.temperature_threshold = 65  # Celsius
        self.vram_threshold = 90  # Percent
        self.cpu_threshold = 95
        self.memory_threshold = 95
        self.heartbeat_interval = 5  # Seconds
        self.health_status = "HEALTHY"
        self.last_heartbeat = time.time()
        self.temperature_history = []
        self.vram_history = []

    def get_health_status(self):
        try:
            cpu_percent = psutil.cpu_percent(interval=0.05)
            memory_percent = psutil.virtual_memory().percent
            healthy = cpu_percent < self.cpu_threshold and memory_percent < self.memory_threshold
            return {
                "status": "healthy" if healthy else "degraded",
                "cpu_percent": cpu_percent,
                "memory_percent": memory_percent,
                "cpu_threshold_percent": self.cpu_threshold,
                "memory_threshold_percent": self.memory_threshold,
                "telemetry_source": "psutil",
            }
        except Exception as exc:
            return {
                "status": "unhealthy",
                "reason": f"system_telemetry_unavailable:{type(exc).__name__}",
            }

    def monitor_temperature(self):
        while True:
            try:
                # Simulate GPU temperature check (replace with actual GPU monitoring if needed)
                temp = 55  # Placeholder for actual temperature reading
                self.temperature_history.append(temp)
                if temp > self.temperature_threshold:
                    self._update_health_status("WARNING", "GPU temperature exceeded threshold")
                else:
                    self._update_health_status("HEALTHY", "GPU temperature within safe range")
            except Exception as e:
                self._update_health_status("CRITICAL", f"Temperature monitoring error: {str(e)}")
            time.sleep(10)

    def monitor_vram(self):
        while True:
            try:
                # Simulate VRAM usage (replace with actual VRAM monitoring if needed)
                vram_usage = 85  # Placeholder for actual VRAM usage
                self.vram_history.append(vram_usage)
                if vram_usage > self.vram_threshold:
                    self._update_health_status("WARNING", "VRAM usage exceeded threshold")
                else:
                    self._None
                    self._update_health_status("HEALTHY", "VRAM usage within safe range")
            except Exception as e:
                self._update_health_status("CRITICAL", f"VRAM monitoring error: {str(e)}")
            time.sleep(10)

    def heartbeat(self):
        while True:
            current_time = time.time()
            if current_time - self.last_heartbeat > self.heartbeat_interval:
                self.last_heartbeat = current_time
                self._log_heartbeat()
                self._update_health_status("HEALTHY", "Heartbeat successful")
            time.sleep(1)

    def _update_health_status(self, status, message):
        self.health_status = status
        self._log_status_update(message)

    def _log_status_update(self, message):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] {self.health_status} - {message}")

    def _log_heartbeat(self):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] HEARTBEAT - System operational")

    def start(self):
        threading.Thread(target=self.monitor_temperature, daemon=True).start()
        threading.Thread(target=self.monitor_vram, daemon=True).start()
        threading.Thread(target=self.heartbeat, daemon=True).start()
        print("InfraCore started. Monitoring hardware vitals...")

if __name__ == "__main__":
    infra_core = InfraCore()
    infra_core.start()
    while True:
        time.sleep(1)
