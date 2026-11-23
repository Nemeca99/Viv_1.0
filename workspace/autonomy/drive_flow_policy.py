"""Explicit drive-direction policy for Viv storage movement."""
from __future__ import annotations

from pathlib import Path


class DriveFlowDenied(PermissionError):
    pass


def _drive(path: Path | str) -> str:
    drive = Path(path).drive.upper()
    return drive.rstrip(":")


def authorize_transfer(source: Path | str, destination: Path | str, *, architect_approved: bool = False) -> dict:
    src = _drive(source)
    dst = _drive(destination)
    allowed = False
    reason = "drive_flow_not_allowlisted"
    if src == "L" and dst in {"D", "F", "G"}:
        allowed, reason = True, "active_archive_flow"
    elif src == "D" and dst in {"F", "G"}:
        allowed, reason = True, "staging_archive_flow"
    elif src == "D" and dst == "L" and architect_approved:
        allowed, reason = True, "architect_approved_restore"
    elif src == "E" and dst == "L":
        allowed, reason = True, "sandbox_export_to_canonical"
    elif src == "E":
        reason = "sandbox_may_only_export_to_L"
    elif src == "D" and dst == "L":
        reason = "D_to_L_requires_architect_approval"
    if not allowed:
        raise DriveFlowDenied(f"Denied drive flow {src}: -> {dst}: ({reason})")
    return {"allowed": True, "source_drive": src, "destination_drive": dst, "reason": reason}

