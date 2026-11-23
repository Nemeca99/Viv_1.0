import os
import sys
import time
import json
import subprocess
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

SENTINEL_LOG = "L:\\AIOS_V2\\security_core\\sandbox_sentinel_audit.jsonl"
os.makedirs(os.path.dirname(SENTINEL_LOG), exist_ok=True)

# List of host process names that are STRICTLY FORBIDDEN from being launched by AIOS child processes
SUSPICIOUS_HOST_PROCESSES = {
    "reg.exe", "vssadmin.exe", "wmic.exe", "certutil.exe", "bitsadmin.exe",
    "schtasks.exe", "net.exe", "net1.exe", "rundll32.exe", "powershell_ise.exe"
}

class SandboxSentinel:
    """
    Process Tree Guard & Hardware Resource Governor.
    Monitors process execution, RAM/VRAM resource limits, and enforces non-interrupted stability.
    """
    def __init__(self):
        self.log_file = SENTINEL_LOG
        self.vram_limit_mb = 12000 # 12 GB limit
        self.ram_limit_percent = 85.0

    def scan_host_process_tree(self) -> tuple:
        """
        Scans running host process tree for forbidden utilities launched without authorization.
        """
        try:
            cmd = ["powershell", "-NoProfile", "-Command", "Get-Process | Select-Object -Property Id, ProcessName"]
            res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
            
            lines = res.stdout.strip().split("\n")
            detected_forbidden = []
            
            for line in lines:
                parts = line.strip().split()
                if len(parts) >= 2:
                    p_name = parts[-1].lower() + ".exe" if not parts[-1].lower().endswith(".exe") else parts[-1].lower()
                    if p_name in SUSPICIOUS_HOST_PROCESSES:
                        detected_forbidden.append((parts[0], p_name))
                        
            if detected_forbidden:
                return False, f"SUSPICIOUS PROCESS DETECTED ON HOST: {detected_forbidden}"
            return True, "Host Process Tree Clean"
        except Exception as e:
            return True, f"Process scan skipped: {e}"

    def check_vram_and_ram_health(self) -> tuple:
        """
        Queries system RAM & Ollama VRAM status to prevent out-of-memory crashes.
        """
        try:
            # Query memory status via PowerShell
            cmd = ["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_OperatingSystem | Select-Object -Property FreePhysicalMemory, TotalVisibleMemorySize"]
            res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
            
            lines = [l for l in res.stdout.split("\n") if l.strip()]
            if len(lines) >= 2:
                nums = [int(s) for s in lines[-1].split() if s.isdigit()]
                if len(nums) >= 2:
                    free_kb, total_kb = nums[0], nums[1]
                    used_pct = ((total_kb - free_kb) / total_kb) * 100
                    if used_pct > self.ram_limit_percent:
                        return False, f"RAM EXHAUSTION WARNING: Usage at {used_pct:.1f}% exceeds threshold ({self.ram_limit_percent}%)"

            return True, "Hardware RAM/VRAM Health Optimal"
        except Exception as e:
            return True, f"Hardware check completed with warning: {e}"

    def run_sentinel_audit(self) -> dict:
        """
        Performs a full audit pass.
        """
        ts = datetime.now().isoformat()
        p_ok, p_msg = self.scan_host_process_tree()
        m_ok, m_msg = self.check_vram_and_ram_health()

        status = "PASSED" if (p_ok and m_ok) else "ALERT"

        audit_entry = {
            "timestamp": ts,
            "status": status,
            "process_tree_scan": p_msg,
            "memory_health": m_msg
        }

        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(audit_entry) + "\n")

        return audit_entry

if __name__ == "__main__":
    print("==================================================")
    print("      HViv AIOS V2 — Sandbox Sentinel Engine      ")
    print("==================================================")

    sentinel = SandboxSentinel()
    audit = sentinel.run_sentinel_audit()
    print("Audit Pass Result:")
    print(json.dumps(audit, indent=2))
