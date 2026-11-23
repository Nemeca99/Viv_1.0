"""Dormant bounded-learning scheduler; construction never starts work."""
from __future__ import annotations
import json,time
from pathlib import Path

class PassiveLearningScheduler:
    def __init__(self, report_path: str|Path, *, max_cycles: int=3):
        if not 1 <= max_cycles <= 10: raise ValueError("bounded cycle limit")
        self.report_path=Path(report_path); self.max_cycles=max_cycles; self.running=False

    def gpu_available(self) -> bool:
        try:
            import cupy
            return bool(cupy.cuda.runtime.getDeviceCount() > 0)
        except Exception:
            return False

    def dry_cycle(self, gaps: list[str], *, architect_active: bool=False, gpu_available: bool|None=None) -> dict:
        available=self.gpu_available() if gpu_available is None else bool(gpu_available)
        if architect_active: status="PAUSED_ARCHITECT_ACTIVE"
        elif not available: status="WAIT_GPU_AVAILABLE"
        else: status="READY_BOUNDED_CYCLE"
        report={"schema":"viv-passive-learning-report-v1","status":status,"cycles_run":0,"gaps_seen":list(gaps)[:self.max_cycles],"promoted":[],"candidates":[],"rejected":[],"daemons_started":False,"architect_active":architect_active,"gpu_available":available,"authority":"Architect and deterministic gates"}
        self.report_path.parent.mkdir(parents=True,exist_ok=True); self.report_path.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
        return report

    def run_once(self, gaps: list[str], *, explicit_launch: bool=False, user_active: bool=False, gpu_idle: bool=False) -> dict:
        """One ownership decision; this method never loops or self-launches."""
        if not explicit_launch:
            status="NOT_LAUNCHED"
        elif user_active:
            status="PAUSED_USER_ACTIVE"
        elif not gpu_idle:
            status="WAIT_GPU_BUSY"
        elif not gaps:
            status="QUEUE_EXHAUSTED"
        else:
            status="LEARNING_BOUNDED"
        report={"schema":"viv-gpu-ownership-report-v1","status":status,"explicit_launch":explicit_launch,"user_active":user_active,"gpu_idle":gpu_idle,"gaps_seen":list(gaps)[:self.max_cycles],"cycles_allowed":self.max_cycles,"promoted":[],"auto_started":False,"authority":"Architect and deterministic gates"}
        self.report_path.parent.mkdir(parents=True,exist_ok=True); self.report_path.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
        return report
