"""
Hive Master Record Snapshot Diffing Engine (Layer 0)

Compares two per-drive index snapshots (_drive_index/*.jsonl) to detect:
- Added files
- Deleted files
- Modified files (size or epoch change)
- State Drift
"""

import glob
import json
import os
import sys
from typing import Any, Dict, List, Optional, Set, Tuple


def load_snapshot(index_file: str) -> Dict[str, Tuple[int, int]]:
    """Loads snapshot into dictionary mapping path -> (size, mtime)."""
    snapshot = {}
    with open(index_file, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)
            p = item.get("p")
            if p and "s" in item:
                snapshot[p.lower()] = (item.get("s", 0), item.get("m", 0))
    return snapshot


def compare_snapshots(old_file: str, new_file: str) -> Dict[str, Any]:
    """Compares old snapshot vs new snapshot and returns deltas."""
    old_snap = load_snapshot(old_file)
    new_snap = load_snapshot(new_file)

    old_paths: Set[str] = set(old_snap.keys())
    new_paths: Set[str] = set(new_snap.keys())

    added = new_paths - old_paths
    deleted = old_paths - new_paths
    common = old_paths.intersection(new_paths)

    modified = []
    for p in common:
        old_size, old_mtime = old_snap[p]
        new_size, new_mtime = new_snap[p]
        if old_size != new_size or old_mtime != new_mtime:
            modified.append({
                "path": p,
                "old_size": old_size,
                "new_size": new_size,
                "old_mtime": old_mtime,
                "new_mtime": new_mtime
            })

    return {
        "old_snapshot": old_file,
        "new_snapshot": new_file,
        "added_count": len(added),
        "deleted_count": len(deleted),
        "modified_count": len(modified),
        "added_sample": list(added)[:10],
        "deleted_sample": list(deleted)[:10],
        "modified_sample": modified[:10]
    }


def diff_latest(drive_letter: str) -> Optional[Dict[str, Any]]:
    """Finds the two most recent snapshots on target drive and computes diff."""
    snapshots = sorted(glob.glob(f"{drive_letter.upper()}:\\_drive_index\\index_*.jsonl"))
    if len(snapshots) < 2:
        print(f"[HIVE DIFF] Insufficient snapshots on Drive {drive_letter.upper()}: (found {len(snapshots)}). Need at least 2 snapshots to compute diff.")
        return None
    
    old_file = snapshots[-2]
    new_file = snapshots[-1]
    return compare_snapshots(old_file, new_file)


if __name__ == "__main__":
    drive = sys.argv[1] if len(sys.argv) > 1 else "L"
    print(f"--- Running Hive Snapshot Diff on Drive {drive.upper()}: ---")
    result = diff_latest(drive)
    if result:
        print(json.dumps(result, indent=2))
