"""Direct Google Drive API archive uploader.

The uploader is inert until user OAuth files exist.  It never deletes a local
buffer; callers must receive a complete, checksum-verified receipt first.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import time
from pathlib import Path
from typing import Any

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
DEFAULT_CONFIG_DIR = Path(os.environ.get("VIV_GOOGLE_DRIVE_CONFIG_DIR", r"C:\Users\nemec\.config\viv-google-drive"))
CLIENT_SECRET_PATH = Path(os.environ.get("VIV_GOOGLE_DRIVE_CREDENTIALS", str(DEFAULT_CONFIG_DIR / "credentials.json")))
TOKEN_PATH = Path(os.environ.get("VIV_GOOGLE_DRIVE_TOKEN", str(DEFAULT_CONFIG_DIR / "token.json")))
FOLDER_ID_PATH = DEFAULT_CONFIG_DIR / "folder_id.txt"
FOLDER_ID = os.environ.get("VIV_GOOGLE_DRIVE_FOLDER_ID", "").strip()
if not FOLDER_ID and FOLDER_ID_PATH.is_file():
    FOLDER_ID = FOLDER_ID_PATH.read_text(encoding="utf-8").strip()


class GoogleDriveNotConfigured(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class GoogleDriveApiUploader:
    def __init__(self, *, root_folder_id: str | None = None):
        self.root_folder_id = root_folder_id or FOLDER_ID
        self._service = None
        self._folder_cache: dict[tuple[str, str], str] = {}
        self._last_upload = 0.0
        self._min_upload_interval = max(0.5, float(os.environ.get("VIV_DRIVE_MIN_INTERVAL_SECONDS", "1")))

    def _throttle_upload(self) -> None:
        elapsed = time.monotonic() - self._last_upload
        if elapsed < self._min_upload_interval:
            time.sleep(self._min_upload_interval - elapsed)
        self._last_upload = time.monotonic()

    @staticmethod
    def _execute_with_backoff(request_factory, *, max_retries: int = 6):
        """Execute a Drive request with Google's documented 403/429 backoff."""
        try:
            from googleapiclient.errors import HttpError
        except ImportError:
            HttpError = ()
        for attempt in range(max_retries + 1):
            try:
                return request_factory().execute()
            except HttpError as exc:
                status = getattr(exc.resp, "status", None)
                if status not in (403, 429) or attempt >= max_retries:
                    raise
                delay = min((2 ** attempt) + random.uniform(0.0, 1.0), 64.0)
                time.sleep(delay)

    @classmethod
    def configured(cls) -> bool:
        return CLIENT_SECRET_PATH.is_file() and TOKEN_PATH.is_file() and bool(FOLDER_ID)

    def _service_or_raise(self):
        if self._service is not None:
            return self._service
        if not CLIENT_SECRET_PATH.is_file() or not TOKEN_PATH.is_file() or not self.root_folder_id:
            raise GoogleDriveNotConfigured(
                f"Provide credentials={CLIENT_SECRET_PATH}, token={TOKEN_PATH}, and "
                "VIV_GOOGLE_DRIVE_FOLDER_ID before API archival is enabled"
            )
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise GoogleDriveNotConfigured("Google Drive client libraries are not installed") from exc
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
            TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        if not creds.valid:
            raise GoogleDriveNotConfigured("Google OAuth token is invalid or needs interactive authorization")
        self._service = build("drive", "v3", credentials=creds, cache_discovery=False)
        return self._service

    def _folder(self, name: str, parent_id: str) -> str:
        key = (parent_id, name)
        if key in self._folder_cache:
            return self._folder_cache[key]
        service = self._service_or_raise()
        query = (
            "trashed=false and mimeType='application/vnd.google-apps.folder' "
            f"and name={json.dumps(name)} and '{parent_id}' in parents"
        )
        found = self._execute_with_backoff(lambda: service.files().list(q=query, fields="files(id,name)", pageSize=10)).get("files", [])
        if found:
            folder_id = found[0]["id"]
        else:
            folder_id = self._execute_with_backoff(lambda: service.files().create(
                body={"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]},
                fields="id",
            ))["id"]
        self._folder_cache[key] = folder_id
        return folder_id

    def upload_run(self, run: Path) -> dict[str, Any]:
        service = self._service_or_raise()
        root = self._folder(run.name, self.root_folder_id)
        uploaded: list[dict[str, Any]] = []
        for source in sorted(p for p in run.rglob("*") if p.is_file()):
            parent = root
            relative_parent = source.parent.relative_to(run)
            for part in relative_parent.parts:
                parent = self._folder(part, parent)
            digest = _sha256(source)
            query = f"trashed=false and name={json.dumps(source.name)} and '{parent}' in parents"
            existing = self._execute_with_backoff(lambda: service.files().list(q=query, fields="files(id,name,size,md5Checksum)", pageSize=10)).get("files", [])
            match = next((item for item in existing if item.get("md5Checksum") == _md5(source)), None)
            if match is None:
                from googleapiclient.http import MediaFileUpload
                self._throttle_upload()
                media = MediaFileUpload(str(source), resumable=True, chunksize=8 * 1024 * 1024)
                match = self._execute_with_backoff(lambda: service.files().create(
                    body={"name": source.name, "parents": [parent]}, media_body=media,
                    fields="id,name,size,md5Checksum",
                ))
            expected_md5 = _md5(source)
            if int(match.get("size", -1)) != source.stat().st_size or match.get("md5Checksum") != expected_md5:
                raise IOError(f"Drive size verification failed: {source}")
            uploaded.append({"path": str(source.relative_to(run)), "id": match["id"], "sha256": digest, "bytes": source.stat().st_size})
        return {"schema": "viv_google_drive_api_receipt_v1", "run": run.name, "folder_id": root, "files": uploaded}

    def upload_file(self, source: Path, *, remote_name: str | None = None) -> dict[str, Any]:
        """Upload one arbitrary file to the configured Drive folder."""
        service = self._service_or_raise()
        name = remote_name or source.name
        expected_md5 = _md5(source)
        # Google Drive API q string uses single quotes with backslash escape for single quotes
        safe_name = name.replace("\\", "\\\\").replace("'", "\\'")
        query = f"trashed=false and name='{safe_name}' and '{self.root_folder_id}' in parents"
        try:
            existing = self._execute_with_backoff(lambda: service.files().list(q=query, fields="files(id,name,size,md5Checksum)", pageSize=20)).get("files", [])
        except Exception:
            existing = []
        match = next((item for item in existing if item.get("md5Checksum") == expected_md5), None)
        if match is None:
            from googleapiclient.http import MediaFileUpload
            self._throttle_upload()
            media = MediaFileUpload(str(source), resumable=True, chunksize=8 * 1024 * 1024)
            match = self._execute_with_backoff(lambda: service.files().create(
                body={"name": name, "parents": [self.root_folder_id]}, media_body=media,
                fields="id,name,size,md5Checksum",
            ))
        if int(match.get("size", -1)) != source.stat().st_size or match.get("md5Checksum") != expected_md5:
            raise IOError(f"Drive verification failed: {source}")
        return {"schema": "viv_google_drive_file_receipt_v1", "source": str(source), "name": name, "file_id": match["id"], "bytes": source.stat().st_size, "md5": expected_md5}


__all__ = ["GoogleDriveApiUploader", "GoogleDriveNotConfigured"]
