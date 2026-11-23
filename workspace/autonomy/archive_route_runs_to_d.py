"""Hash-verified L: -> D:+F: staging.

L: is deleted only after the same snapshot is independently verified on both
temporary buffer drives.  The D: worker later verifies G: and removes D: and
F:, leaving the cloud copy as the cold archive.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from autonomy.drive_flow_policy import authorize_transfer

RUNS = Path(r"L:\LocalCoder\workspace\autonomy\learning\neural_runs")
STAGING = Path(r"D:\AIOS_RawDump\L_neural_runs")
LOCAL_BUFFER = Path(r"F:\LocalCoder_Archive\INN_live_runs")
KEEP_NEWEST = 60


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def copy_verified(source: Path, destination: Path) -> dict[str, str]:
    if not destination.exists():
        shutil.copytree(source, destination)
    elif not destination.is_dir():
        raise IOError(f"destination is not a directory: {destination}")
    manifest = {}
    source_files = {p.relative_to(source) for p in source.rglob("*") if p.is_file()}
    destination_files = {p.relative_to(destination) for p in destination.rglob("*") if p.is_file()}
    if destination_files and destination_files != source_files:
        raise IOError(f"file-set mismatch: {source} -> {destination}")
    for relative in sorted(source_files):
        source_hash = sha256(source / relative)
        copied = destination / relative
        if not copied.is_file() or sha256(copied) != source_hash:
            raise IOError(f"hash mismatch: {source} -> {destination} / {relative}")
        manifest[str(relative)] = source_hash
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Hash-verified L: route snapshot archive")
    parser.add_argument("--keep-newest", type=int, default=KEEP_NEWEST)
    args = parser.parse_args()
    keep_newest = max(1, args.keep_newest)
    authorize_transfer(RUNS, STAGING)
    authorize_transfer(RUNS, LOCAL_BUFFER)
    STAGING.mkdir(parents=True, exist_ok=True)
    LOCAL_BUFFER.mkdir(parents=True, exist_ok=True)
    routes = sorted(p for p in RUNS.glob("language-routes-*") if p.is_dir())
    candidates = routes[:-keep_newest] if len(routes) > keep_newest else []
    manifest = {"created_utc": datetime.now(timezone.utc).isoformat(), "runs": {}}
    for run in candidates:
        staging_dest = STAGING / run.name
        local_dest = LOCAL_BUFFER / run.name
        if staging_dest.exists() and local_dest.exists():
            continue
        staging_manifest = copy_verified(run, staging_dest)
        local_manifest = copy_verified(run, local_dest)
        if staging_manifest != local_manifest:
            raise IOError(f"D/F manifest mismatch: {run.name}")
        size = sum(p.stat().st_size for p in run.rglob("*") if p.is_file())
        manifest["runs"][run.name] = {"files": staging_manifest, "bytes": size}
        shutil.rmtree(run)
        (STAGING / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    (STAGING / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(json.dumps({"archived_runs": len(manifest["runs"]), "kept_local": min(keep_newest, len(routes))}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
