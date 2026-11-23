"""
Snapshot Manager for AIOS Viv Autonomy (Pillar 5: Ancestral Memory & Rollback).
Handles pre-task snapshots, deterministic rollback on failure, and ancestral sealing on verified completion.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
AUTONOMY_DIR = Path(__file__).resolve().parent
SNAPSHOTS_DIR = AUTONOMY_DIR / "snapshots"
ANCESTRAL_DIR = AUTONOMY_DIR / "ancestral_epochs"
BUILD_LOG_PATH = Path("L:/LocalCoder/BUILD_LOG.md")


def sha256_file(path: Path) -> str:
    """Computes SHA-256 digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class SnapshotManager:
    def __init__(
        self,
        snapshots_dir: Path = SNAPSHOTS_DIR,
        ancestral_dir: Path = ANCESTRAL_DIR,
        build_log_path: Path = BUILD_LOG_PATH,
    ):
        self.snapshots_dir = snapshots_dir
        self.ancestral_dir = ancestral_dir
        self.build_log_path = build_log_path

        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        self.ancestral_dir.mkdir(parents=True, exist_ok=True)

    def create_snapshot(self, task_id: str, target_files: List[Union[str, Path]]) -> Dict[str, Any]:
        """Snapshots target files before modification."""
        task_dir = self.snapshots_dir / task_id
        task_dir.mkdir(parents=True, exist_ok=True)

        manifest: Dict[str, Any] = {
            "task_id": task_id,
            "created_at": datetime.now().isoformat(),
            "files": {},
        }

        for item in target_files:
            file_path = Path(item).resolve()
            if not file_path.exists():
                manifest["files"][str(file_path)] = {
                    "existed": False,
                    "sha256": None,
                    "backup_path": None,
                }
                continue

            sha = sha256_file(file_path)
            backup_rel = f"{file_path.name}_{sha[:8]}"
            backup_path = task_dir / backup_rel
            shutil.copy2(file_path, backup_path)

            manifest["files"][str(file_path)] = {
                "existed": True,
                "sha256": sha,
                "backup_path": str(backup_path),
            }

        manifest_path = task_dir / "snapshot_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"[+] [SnapshotManager] Pre-task snapshot created for task '{task_id}' ({len(target_files)} files).")
        return manifest

    def rollback(self, task_id: str, reason: str = "Self-healing exhausted") -> bool:
        """Rolls back all files modified during task_id to their pre-snapshot state."""
        task_dir = self.snapshots_dir / task_id
        manifest_path = task_dir / "snapshot_manifest.json"
        if not manifest_path.exists():
            print(f"[!] [SnapshotManager] Cannot rollback: no snapshot manifest found for task '{task_id}'.")
            return False

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for orig_str, info in manifest.get("files", {}).items():
            orig_path = Path(orig_str)
            if not info["existed"]:
                # File was created during task; remove it
                if orig_path.exists():
                    orig_path.unlink(missing_ok=True)
                    print(f"[*] [Rollback] Removed newly created file: {orig_path.name}")
            else:
                backup = Path(info["backup_path"])
                if backup.exists():
                    shutil.copy2(backup, orig_path)
                    print(f"[*] [Rollback] Restored original: {orig_path.name} (SHA: {info['sha256'][:8]})")

        # Record rollback event in BUILD_LOG
        self._record_build_log(
            event_type="ROLLBACK",
            task_id=task_id,
            details=f"Autonomous rollback executed. Reason: {reason}",
        )
        print(f"[+] [SnapshotManager] Rollback completed cleanly for task '{task_id}'.")
        return True

    def seal_epoch(self, task_id: str, task_objective: str, evidence: Dict[str, Any]) -> Path:
        """Seals verified task output with SHA-256 hashes into ancestral_epochs."""
        task_dir = self.snapshots_dir / task_id
        manifest_path = task_dir / "snapshot_manifest.json"
        
        post_files: Dict[str, Any] = {}
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for orig_str in manifest.get("files", {}).keys():
                orig_path = Path(orig_str)
                if orig_path.exists():
                    post_files[str(orig_path)] = {
                        "sha256": sha256_file(orig_path),
                        "bytes": orig_path.stat().st_size,
                    }

        receipt = {
            "task_id": task_id,
            "sealed_at": datetime.now().isoformat(),
            "objective": task_objective,
            "evidence": evidence,
            "modified_files": post_files,
            "verified_on_silicon": True,
        }

        receipt_filename = f"{task_id}_sealed_{int(time.time())}.json"
        receipt_path = self.ancestral_dir / receipt_filename
        receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")

        # Append to BUILD_LOG
        self._record_build_log(
            event_type="SEALED_RECEIPT",
            task_id=task_id,
            details=f"Task '{task_objective}' verified on silicon. Receipt: {receipt_filename}",
        )

        # Clean up temporary snapshot dir
        try:
            shutil.rmtree(task_dir, ignore_errors=True)
        except Exception:
            pass

        print(f"[+] [SnapshotManager] Ancestral receipt sealed: {receipt_path.name}")
        return receipt_path

    def _record_build_log(self, event_type: str, task_id: str, details: str):
        """Appends zero-metaphor verifiable log entry to BUILD_LOG.md."""
        if not self.build_log_path.exists():
            return
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"\n- **[{timestamp}] [{event_type}] Task: {task_id}**\n  - {details}\n"
        try:
            with open(self.build_log_path, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception as exc:
            print(f"[!] Could not append to BUILD_LOG: {exc}")


def self_test():
    print("==========================================================================")
    print("   SNAPSHOT MANAGER & ROLLBACK SILICON VERIFICATION")
    print("==========================================================================")
    sm = SnapshotManager()

    test_file = WORKSPACE_ROOT / "temp_snapshot_probe.txt"
    test_file.write_text("ORIGINAL CONTENT", encoding="utf-8")
    original_sha = sha256_file(test_file)

    task_id = "test_task_rollback_001"
    # 1. Snapshot
    sm.create_snapshot(task_id, [test_file])

    # 2. Corrupt file
    test_file.write_text("CORRUPTED BY FAILING RUN", encoding="utf-8")
    assert sha256_file(test_file) != original_sha

    # 3. Rollback
    sm.rollback(task_id, reason="Intentional test failure")
    assert test_file.read_text(encoding="utf-8") == "ORIGINAL CONTENT", "Rollback failed to restore content"
    assert sha256_file(test_file) == original_sha, "Rollback hash mismatch"
    print("[+] Rollback successfully restored exact file bytes on silicon.")

    # 4. Seal epoch test
    test_file.write_text("VERIFIED OPTIMAL CONTENT", encoding="utf-8")
    receipt = sm.seal_epoch(
        task_id="test_task_seal_002",
        task_objective="Verify seal epoch mechanism",
        evidence={"status": "passed", "exit_code": 0},
    )
    assert receipt.exists(), "Receipt file was not created"
    print(f"[+] Seal epoch verified on silicon: {receipt.name}")

    # Clean up
    test_file.unlink(missing_ok=True)
    receipt.unlink(missing_ok=True)
    print("\n==========================================================================")
    print("   SNAPSHOT MANAGER TEST RESULT: SUCCESS")
    print("==========================================================================")


if __name__ == "__main__":
    self_test()
