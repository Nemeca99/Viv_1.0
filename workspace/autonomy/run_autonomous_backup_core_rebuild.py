"""
Autonomous Rebuild of BackupCore (AIOS Viv Core #12).
Executes through the DAG Orchestrator:
Decomposes Goal -> Pre-Coding Topological Retrieval -> Authors Tests -> Authors Implementation ->
Runs Verification with Closed-Loop Self-Healing (N<=3) -> Automatic Snapshot Rollback if failed ->
Seals SHA-256 Ancestral Receipt & Registers Primitives in viv_code_topology.sqlite3.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

AUTONOMY_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = AUTONOMY_DIR.parent
REBUILD_DIR = WORKSPACE_ROOT / "aios_rebuild" / "backup_core"

sys.path.insert(0, str(AUTONOMY_DIR))
from dag_orchestrator import DAGOrchestrator
from topological_context_injector import TopologicalContextInjector


def main():
    print("==========================================================================")
    print("   AIOS VIV AUTONOMOUS CORE REBUILD: BACKUP_CORE")
    print("   Architect: Human Architect (Absolute Authority)")
    print("   Substrate: 100% Offline Local Model (omnicoder-2-9b)")
    print("   Retry Budget: 3 Bounded Attempts")
    print("==========================================================================")

    # 1. Register existing BackupCore baseline into topology so pre-coding RAG has ground truth
    injector = TopologicalContextInjector()
    baseline_desc = (
        "BackupCore state preservation engine with snapshot quota management, "
        "file hash calculation, integrity verification, and get_health_status() reporting."
    )
    baseline_code = """
import hashlib
import os
import shutil

class BackupCore:
    def __init__(self, config: dict):
        self.config = config
        self.snapshot_dir = config.get('snapshot_dir', '.snapshots')
        os.makedirs(self.snapshot_dir, exist_ok=True)
        self.max_snapshots = config.get('max_snapshots', 5)
        self.quota_limit = config.get('quota_limit', 1000000000)
        self.snapshot_hashes = {}
    def backup_file(self, file_path: str): pass
    def get_health_status(self) -> dict: pass
    def _calculate_hash(self, file_path: str) -> str: pass
    def _manage_snapshot_quota(self): pass
    def _verify_hashes(self) -> bool: pass
"""
    injector.register_verified_primitive(
        primitive_id="PRIM_BACKUP_CORE_SPEC",
        intent_description=baseline_desc,
        verified_code=baseline_code.strip(),
        language="python",
    )

    # 2. Initialize DAG Orchestrator
    orchestrator = DAGOrchestrator(injector=injector)
    goal_id = f"GOAL_REBUILD_BACKUP_CORE_{int(time.time())}"

    # 3. Create the 3-step DAG with explicit contracts
    core_desc = (
        "State preservation checkpoint engine with `BackupCore(config)` class.\n"
        "Config dict keys: `snapshot_dir` (default '.snapshots'), `max_snapshots` (default 5), and `quota_limit` (default 1000000000).\n"
        "Required instance attributes:\n"
        "- `self.config`: the config dict passed into __init__\n"
        "- `self.snapshot_dir`: snapshot directory path (must call os.makedirs(self.snapshot_dir, exist_ok=True) in __init__)\n"
        "- `self.max_snapshots`: maximum allowed snapshot files\n"
        "- `self.quota_limit`: byte quota limit\n"
        "Required methods:\n"
        "- `backup_file(self, file_path: str)`: saves snapshot copy of file_path to snapshot_dir and records sha256 hash\n"
        "- `get_health_status(self) -> dict`: returns dict with exact keys 'status' ('healthy' or 'over_quota'), 'snapshot_count' (int), and 'quota_used' (total bytes of snapshot files computed via os.path.getsize(os.path.join(self.snapshot_dir, f)))\n"
        "- `_calculate_hash(self, file_path: str) -> str`: returns sha256 hex digest of file_path\n"
        "- `_manage_snapshot_quota(self)`: prunes oldest snapshot files when count > max_snapshots\n"
        "- `_verify_hashes(self) -> bool`: checks snapshot file hashes against recorded digests, returning True if all valid, False on mismatch, missing file, or if no snapshots have been recorded yet (do not raise exceptions)\n"
        "Zero external cloud dependencies."
    )

    tasks = orchestrator.create_goal_dag(
        goal_id=goal_id,
        core_name="backup_core",
        core_description=core_desc,
        target_dir=REBUILD_DIR,
        language="python",
    )
    print(f"[*] Created {len(tasks)} tasks in DAG for goal: {goal_id}")

    # 4. Execute Autonomous Goal
    t0 = time.time()
    success = orchestrator.run_autonomous_goal(goal_id=goal_id, language="python")
    elapsed = time.time() - t0

    print("\n==========================================================================")
    print(f"   BACKUP_CORE REBUILD RESULT: {'SUCCESS' if success else 'FAILED'}")
    print(f"   Total Elapsed Time: {elapsed:.2f} seconds")
    print("==========================================================================")

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
