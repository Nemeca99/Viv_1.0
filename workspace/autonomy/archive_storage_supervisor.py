"""Run the hash-verified L->D->F/G archive pipeline continuously.

The supervisor is deliberately single-owner: route retention and D draining
must not run concurrently with each other or with a second supervisor.
"""
from __future__ import annotations

import msvcrt
import hashlib
import json
import os
import shutil
import time
from pathlib import Path

from autonomy.archive_route_runs_to_d import main as stage_old_routes
from autonomy.archive_staging_pipeline import process_once
from autonomy.google_drive_api_uploader import GoogleDriveApiUploader

LOCK_PATH = Path(r"L:\LocalCoder\workspace\autonomy\learning\archive_storage_supervisor.lock")
POLL_SECONDS = 60
MIN_STAGE_FREE_BYTES = 5 * 1024**3
MIN_LOCAL_FREE_BYTES = 5 * 1024**3
RELIEF_TARGET_BYTES = 10 * 1024**3
LOCAL_ARCHIVE = Path(r"F:\LocalCoder_Archive\INN_live_runs")
CLOUD_ARCHIVE = Path(r"G:\My Drive\AIOS_RawDump\L_neural_runs")
UPLOAD_QUEUE = Path(r"D:\AIOS_RawDump\UPLOAD_TO_DRIVE")
UPLOAD_RECEIPTS = Path(r"L:\LocalCoder\workspace\autonomy\learning\google_drive_file_receipts.jsonl")
# A file upload uses a list (100 units) plus create (50 units).  Thirty files
# per minute is deliberately far below Google's 325,000 user/project units per
# minute, while still allowing a large drop tree to drain.
UPLOAD_MAX_FILES_PER_CYCLE = max(1, int(os.environ.get("VIV_DRIVE_MAX_FILES_PER_CYCLE", "30")))
UPLOAD_MIN_INTERVAL_SECONDS = max(0.5, float(os.environ.get("VIV_DRIVE_MIN_INTERVAL_SECONDS", "1")))


def _safe_str(val: Any) -> str:
    """Sanitize strings containing unicode or surrogate chars for Windows console output."""
    if isinstance(val, str):
        return val.encode("ascii", "backslashreplace").decode("ascii")
    if isinstance(val, dict):
        return {k: _safe_str(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_safe_str(x) for x in val]
    return str(val)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def relieve_local_archive() -> int:
    """Move oldest verified F: runs to G: when F: is under pressure."""
    if not LOCAL_ARCHIVE.exists() or not CLOUD_ARCHIVE.exists():
        return 0
    moved = 0
    for run in sorted(LOCAL_ARCHIVE.glob("language-routes-*")):
        if shutil.disk_usage(LOCAL_ARCHIVE).free >= RELIEF_TARGET_BYTES:
            break
        if not run.is_dir():
            continue
        destination = CLOUD_ARCHIVE / run.name
        try:
            if not destination.exists():
                shutil.copytree(run, destination)
            source_files = {p.relative_to(run) for p in run.rglob("*") if p.is_file()}
            destination_files = {p.relative_to(destination) for p in destination.rglob("*") if p.is_file()}
            if source_files != destination_files:
                raise IOError(f"F/G file-set mismatch: {run.name}")
            for relative in source_files:
                if sha256(run / relative) != sha256(destination / relative):
                    raise IOError(f"F/G hash mismatch: {run.name}/{relative}")
            shutil.rmtree(run)
            moved += 1
        except Exception as exc:
            print({"status": "relief_hold", "run": run.name, "error": f"{type(exc).__name__}: {exc}"}, flush=True)
    return moved


def process_upload_queue() -> int:
    """Upload arbitrary drop-folder files, then remove verified locals."""
    if not GoogleDriveApiUploader.configured():
        return 0
    UPLOAD_QUEUE.mkdir(parents=True, exist_ok=True)
    uploader = GoogleDriveApiUploader()
    moved = 0
    candidates = []
    for current_root, _dirs, files in os.walk(UPLOAD_QUEUE):
        for filename in sorted(files):
            if filename.endswith(".tmp"):
                continue
            cand_path = Path(current_root) / filename
            try:
                st = os.lstat(str(cand_path))
                if getattr(st, "st_reparse_tag", 0) == 0xa000001d or not cand_path.exists():
                    # Dead WSL link or broken surrogate: clean up to unblock queue
                    try:
                        cand_path.unlink()
                        print({"upload_queue": cand_path.name, "status": "pruned_broken_surrogate"}, flush=True)
                    except Exception:
                        pass
                    continue
            except Exception:
                continue
            candidates.append(cand_path)
            if len(candidates) >= UPLOAD_MAX_FILES_PER_CYCLE:
                break
        if len(candidates) >= UPLOAD_MAX_FILES_PER_CYCLE:
            break
    for index, source in enumerate(candidates):
        try:
            if index:
                time.sleep(UPLOAD_MIN_INTERVAL_SECONDS)
            receipt = uploader.upload_file(source, remote_name=source.name)
            UPLOAD_RECEIPTS.parent.mkdir(parents=True, exist_ok=True)
            with UPLOAD_RECEIPTS.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(receipt, sort_keys=True) + "\n")
            source.unlink()
            moved += 1
            print(_safe_str({"upload_queue": source.name, "status": "uploaded_verified_removed"}), flush=True)
        except Exception as exc:
            print(_safe_str({"upload_queue": source.name, "status": "hold", "error": f"{type(exc).__name__}: {exc}"}), flush=True)
    return moved


def acquire_lock():
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    handle = LOCK_PATH.open("a+")
    handle.seek(0)
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError as exc:
        handle.close()
        raise RuntimeError("archive supervisor already running") from exc
    return handle


def main() -> int:
    lock_handle = acquire_lock()
    try:
        while True:
            try:
                queued = process_upload_queue()
                moved = process_once()
                relieved = relieve_local_archive()
                stage_free = shutil.disk_usage(Path(r"D:\AIOS_RawDump")).free
                local_free = shutil.disk_usage(Path(r"F:\LocalCoder_Archive")).free
                if stage_free >= MIN_STAGE_FREE_BYTES and local_free >= MIN_LOCAL_FREE_BYTES:
                    stage_old_routes()
                else:
                    print({"status": "intake_hold", "stage_free": stage_free, "local_free": local_free}, flush=True)
                print({"moved": moved, "relieved": relieved, "queued": queued, "status": "ok"}, flush=True)
            except Exception as exc:
                print({"status": "hold", "error": f"{type(exc).__name__}: {exc}"}, flush=True)
            time.sleep(POLL_SECONDS)
    finally:
        lock_handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
