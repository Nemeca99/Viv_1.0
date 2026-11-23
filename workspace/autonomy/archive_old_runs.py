"""Safely archive older INN neural run checkpoints to F:\LocalCoder_Archive\INN_live_runs.

Preserves the latest 10 runs on L: so latest_run(), verification, and replays
continue uninterrupted, while reclaiming ~19+ GB on L:.
"""

from __future__ import annotations

import shutil
from pathlib import Path
import sys

RUNS_DIR = Path(r"L:\LocalCoder\workspace\autonomy\learning\neural_runs")
ARCHIVE_DIR = Path(r"F:\LocalCoder_Archive\INN_live_runs")
KEEP_COUNT = 10


def archive_runs():
    if not RUNS_DIR.exists():
        print(f"Runs directory not found: {RUNS_DIR}")
        return

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    
    runs = sorted(RUNS_DIR.glob("language-routes-*"))
    total_runs = len(runs)
    if total_runs <= KEEP_COUNT:
        print(f"Only {total_runs} runs exist (<= {KEEP_COUNT}); no archiving needed.")
        return

    to_archive = runs[:-KEEP_COUNT]
    to_keep = runs[-KEEP_COUNT:]

    free_before = shutil.disk_usage(RUNS_DIR).free / (1024 ** 3)
    print(f"Total runs found: {total_runs}")
    print(f"Preserving {len(to_keep)} latest runs on L: (from {to_keep[0].name} to {to_keep[-1].name})")
    print(f"Archiving {len(to_archive)} older runs to {ARCHIVE_DIR}...")
    print(f"L: free space before archiving: {free_before:.2f} GB")

    moved = 0
    errors = 0
    for run_dir in to_archive:
        dest_dir = ARCHIVE_DIR / run_dir.name
        try:
            if dest_dir.exists():
                shutil.rmtree(dest_dir)
            shutil.move(str(run_dir), str(dest_dir))
            moved += 1
        except Exception as exc:
            print(f"Error moving {run_dir.name}: {exc}")
            errors += 1

    free_after = shutil.disk_usage(RUNS_DIR).free / (1024 ** 3)
    freed = free_after - free_before
    print("-" * 60)
    print(f"Archiving complete: {moved} runs moved successfully, {errors} errors.")
    print(f"L: free space after archiving: {free_after:.2f} GB (+{freed:.2f} GB reclaimed)")


if __name__ == "__main__":
    archive_runs()
