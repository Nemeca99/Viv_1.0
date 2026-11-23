"""Continuous D/F temporary buffers -> G cold archive pipeline."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from autonomy.drive_flow_policy import authorize_transfer
from autonomy.google_drive_api_uploader import GoogleDriveApiUploader

STAGING = Path(r"D:\AIOS_RawDump\L_neural_runs")
LOCAL_ARCHIVE = Path(r"F:\LocalCoder_Archive\INN_live_runs")
CLOUD_ARCHIVE = Path(r"G:\My Drive\AIOS_RawDump\L_neural_runs")
POLL_SECONDS = 60
API_RECEIPTS = Path(r"L:\LocalCoder\workspace\autonomy\learning\google_drive_api_receipts.jsonl")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def copy_verified(source: Path, destination: Path, *, repair_existing: bool = False) -> dict[str, str]:
    # The pipeline is rerunnable.  Never delete an existing archive tree just
    # to recopy it: SQLite readers may hold files open, and a partial tree is
    # evidence that must be inspected rather than destroyed.
    if not destination.exists():
        shutil.copytree(source, destination)
    elif not destination.is_dir():
        raise IOError(f"archive destination is not a directory: {destination}")
    manifest: dict[str, str] = {}
    for original in sorted(p for p in source.rglob("*") if p.is_file()):
        relative = original.relative_to(source)
        copied = destination / relative
        source_hash = sha256(original)
        if not copied.is_file() or sha256(copied) != source_hash:
            if repair_existing:
                # F: is a disposable transfer buffer.  It may contain a stale
                # copy from the pre-3-2-1 pipeline; rebuild it from D only
                # after G has already been verified in this transaction.
                shutil.rmtree(destination)
                shutil.copytree(source, destination)
                return copy_verified(source, destination, repair_existing=False)
            raise IOError(f"hash mismatch: {source} -> {destination} / {relative}")
        manifest[str(relative)] = source_hash
    # A destination with extra files is not silently accepted as verified.
    # Preserve it for inspection and force a later operator-approved cleanup.
    source_files = {p.relative_to(source) for p in source.rglob("*") if p.is_file()}
    destination_files = {
        p.relative_to(destination)
        for p in destination.rglob("*")
        if p.is_file() and p.name != ".archive_receipt.json"
    }
    if destination_files != source_files:
        raise IOError(f"archive file-set mismatch: {source} -> {destination}")
    return manifest


def process_once() -> int:
    if not STAGING.exists():
        return 0
    LOCAL_ARCHIVE.mkdir(parents=True, exist_ok=True)
    CLOUD_ARCHIVE.mkdir(parents=True, exist_ok=True)
    api_uploader = GoogleDriveApiUploader() if GoogleDriveApiUploader.configured() else None
    authorize_transfer(STAGING, LOCAL_ARCHIVE)
    authorize_transfer(STAGING, CLOUD_ARCHIVE)
    moved = 0
    for run in sorted(p for p in STAGING.glob("language-routes-*") if p.is_dir()):
        local = LOCAL_ARCHIVE / run.name
        cloud = CLOUD_ARCHIVE / run.name
        try:
            # Verify the cloud copy first.  F: is temporary and may be stale
            # from the previous pipeline; once G is verified it is safe to
            # rebuild F from the canonical D source.
            api_receipt = None
            if api_uploader is not None:
                api_receipt = api_uploader.upload_run(run)
                cloud_manifest = {item["path"]: item["sha256"] for item in api_receipt["files"]}
            else:
                cloud_manifest = copy_verified(run, cloud, repair_existing=True)
            local_manifest = copy_verified(run, local, repair_existing=True)
            if local_manifest != cloud_manifest:
                raise IOError(f"local/cloud manifest mismatch: {run.name}")
            receipt = {
                "schema": "viv_321_archive_receipt_v1",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": str(run),
                "local_archive": str(local),
                "cloud_archive": str(cloud),
                "files": local_manifest,
            }
            if api_receipt is not None:
                receipt["google_drive_api"] = api_receipt
                API_RECEIPTS.parent.mkdir(parents=True, exist_ok=True)
                with API_RECEIPTS.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(receipt, sort_keys=True) + "\n")
            if api_receipt is None:
                (cloud / ".archive_receipt.json").write_text(
                    json.dumps(receipt, indent=2), encoding="utf-8"
                )
            (local / ".archive_receipt.json").write_text(
                json.dumps(receipt, indent=2), encoding="utf-8"
            )
            # G is now independently verified.  F and D are temporary
            # buffers, so remove both only after the cloud receipt is durable.
            shutil.rmtree(local)
            shutil.rmtree(run)
            moved += 1
        except Exception as error:
            print(f"[ARCHIVE HOLD] {run.name}: {type(error).__name__}: {error}", flush=True)
            # Preserve staging on every failure.
    return moved


def main() -> int:
    while True:
        moved = process_once()
        print(json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(), "moved": moved}), flush=True)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
