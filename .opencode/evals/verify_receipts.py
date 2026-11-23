"""Read-only integrity check for LocalCoder OpenCode tool receipts."""

from __future__ import annotations

import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RECEIPTS = ROOT / ".opencode" / "receipts"
SNAPSHOTS = ROOT / ".opencode" / "snapshots"
HEX_SHA256 = set("0123456789abcdef")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def valid_hash(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and set(value.lower()) <= HEX_SHA256
    )


def inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=True).relative_to(parent.resolve(strict=True))
        return True
    except (OSError, ValueError):
        return False


def main() -> int:
    if not RECEIPTS.is_dir() or not SNAPSHOTS.is_dir():
        print("FAIL: receipt or snapshot directory is missing")
        return 1

    errors: list[str] = []
    groups: dict[str, list[tuple[Path, dict]]] = defaultdict(list)
    count = 0

    for file in sorted(RECEIPTS.glob("*.json")):
        count += 1
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            errors.append(f"{file.name}: unreadable JSON ({error})")
            continue
        if data.get("schema") != "opencode_tool_v1":
            errors.append(f"{file.name}: unexpected schema")
        if data.get("event") not in {"before", "after", "blocked"}:
            errors.append(f"{file.name}: unexpected event")
        receipt_id = data.get("receipt_id")
        if not isinstance(receipt_id, str) or not receipt_id:
            errors.append(f"{file.name}: missing receipt_id")
            continue
        groups[receipt_id].append((file, data))

        input_hash = data.get("input_sha256")
        if input_hash is not None and not valid_hash(input_hash):
            errors.append(f"{file.name}: malformed input_sha256")
        for key in ("before_sha256", "after_sha256"):
            if data.get(key) is not None and not valid_hash(data[key]):
                errors.append(f"{file.name}: malformed {key}")

        snapshot_value = data.get("snapshot")
        if snapshot_value:
            snapshot = Path(snapshot_value)
            if not snapshot.is_absolute() or not inside(snapshot, SNAPSHOTS):
                errors.append(f"{file.name}: snapshot escapes project snapshot directory")
            elif not snapshot.is_file():
                errors.append(f"{file.name}: referenced snapshot is missing")
            elif data.get("before_sha256") and sha256(snapshot) != data["before_sha256"]:
                errors.append(f"{file.name}: snapshot hash differs from before_sha256")

    paired = 0
    legacy_unmatched: dict[tuple[str, str], dict[str, list[dict]]] = defaultdict(lambda: {"before": [], "after": []})
    blocked = 0
    for receipt_id, items in groups.items():
        before = [data for _, data in items if data.get("event") == "before"]
        after = [data for _, data in items if data.get("event") == "after"]
        denied = [data for _, data in items if data.get("event") == "blocked"]
        if denied:
            blocked += len(denied)
            if before or after or len(denied) != 1:
                errors.append(f"{receipt_id}: blocked receipt is duplicated or mixed with execution receipts")
            continue
        if len(before) != 1 or len(after) != 1:
            if len(before) == 1 and not after:
                item = before[0]
                legacy_unmatched[(str(item.get("session_id", "")), str(item.get("tool", "")))]["before"].append(item)
            elif len(after) == 1 and not before:
                item = after[0]
                legacy_unmatched[(str(item.get("session_id", "")), str(item.get("tool", "")))]["after"].append(item)
            else:
                errors.append(f"{receipt_id}: expected one before and one after receipt")
            continue
        first, last = before[0], after[0]
        for key in ("session_id", "tool", "input_sha256", "path", "before_sha256", "snapshot"):
            if first.get(key) != last.get(key):
                errors.append(f"{receipt_id}: before/after {key} mismatch")
        paired += 1

    reconciled = 0
    for (session_id, tool), sides in legacy_unmatched.items():
        before, after = sides["before"], sides["after"]
        if len(before) != 1 or len(after) != 1 or not session_id or not tool:
            errors.append(f"{session_id}/{tool}: ambiguous legacy receipt pairing")
            continue
        first, last = before[0], after[0]
        if first.get("input_sha256") is None:
            errors.append(f"{session_id}/{tool}: legacy before receipt has no input hash")
            continue
        try:
            first_at = datetime.fromisoformat(first["captured_at"].replace("Z", "+00:00"))
            last_at = datetime.fromisoformat(last["captured_at"].replace("Z", "+00:00"))
            elapsed = abs((last_at - first_at).total_seconds())
        except (KeyError, TypeError, ValueError):
            errors.append(f"{session_id}/{tool}: invalid timestamps for legacy receipt pairing")
            continue
        if elapsed > 30 or first.get("session_id") != last.get("session_id") or first.get("tool") != last.get("tool"):
            errors.append(f"{session_id}/{tool}: legacy receipt events do not form a unique time-bounded pair")
            continue
        paired += 1
        reconciled += 1

    if errors:
        print(f"FAIL: checked {count} receipts; {paired} pairs and {blocked} blocked events")
        for error in errors:
            print(f"  - {error}")
        return 1

    suffix = f"; {reconciled} unique legacy hook-key pair(s) reconciled by session, tool, and timestamp" if reconciled else ""
    print(f"PASS: {count} receipts; {paired} matched before/after pairs; {blocked} blocked events; snapshot hashes verified{suffix}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
