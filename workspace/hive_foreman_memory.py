"""Read-only foreman snapshots for the isolated LocalCoder Hive proof.

The source is the moved Continue/Viv tree. Records are append-only in this
workspace. A snapshot informs Viv; it does not authorize action or alter the
live tree.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
VIV_ROOT = Path("D:/LocalAi/Continue/Viv")
PYTHON = ROOT / ".hive_proof_env/Scripts/python.exe"
SCRIPT = VIV_ROOT / "foundation/scripts/viv_foreman_snapshot.py"
AGENTS = VIV_ROOT / "AGENTS.md"
CURRENT_TASK = VIV_ROOT / "foundation/artifacts/auto/agentic/CURRENT_TASK.json"
JOURNAL = VIV_ROOT / "foundation/artifacts/audit/session_journal.md"
STORE = ROOT / "hive_snapshots"


def _read_with_hash(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    return raw.decode("utf-8-sig"), hashlib.sha256(raw).hexdigest()


def _active_excerpt(full_agents: str) -> str:
    marker = "### Long-build communication and build-record protocol"
    if marker not in full_agents:
        raise ValueError("Active AGENTS.md section marker is missing; review required")
    excerpt = full_agents.split(marker, 1)[0].strip()
    if len(excerpt) > 9000:
        raise ValueError(
            "Active AGENTS.md excerpt exceeds context budget; review required"
        )
    return excerpt


def capture() -> Path:
    for path in (PYTHON, SCRIPT, AGENTS, CURRENT_TASK, JOURNAL):
        if not path.is_file():
            raise FileNotFoundError(f"Foreman source missing: {path}")
    process = subprocess.run(
        [str(PYTHON), str(SCRIPT), "--compact"],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    snapshot = json.loads(process.stdout)
    if (
        snapshot.get("schema_version") != "viv_foreman_snapshot_v1"
        or snapshot.get("read_only") is not True
    ):
        raise ValueError(
            "Foreman snapshot schema/read-only flag changed; review required"
        )
    agents_text, agents_hash = _read_with_hash(AGENTS)
    current_text, current_hash = _read_with_hash(CURRENT_TASK)
    journal_text, journal_hash = _read_with_hash(JOURNAL)
    current = json.loads(current_text)
    head = current.get("authoritative_heads", {}).get("training", {})
    record: dict[str, Any] = {
        "schema_version": "hive_foreman_memory_v1",
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "source_paths": {
            "snapshot_script": str(SCRIPT),
            "agents": str(AGENTS),
            "current_task": str(CURRENT_TASK),
            "journal": str(JOURNAL),
        },
        "source_sha256": {
            "agents": agents_hash,
            "current_task": current_hash,
            "journal": journal_hash,
        },
        "source_modified_utc": {
            "agents": datetime.fromtimestamp(
                AGENTS.stat().st_mtime, timezone.utc
            ).isoformat(),
            "current_task": datetime.fromtimestamp(
                CURRENT_TASK.stat().st_mtime, timezone.utc
            ).isoformat(),
            "journal": datetime.fromtimestamp(
                JOURNAL.stat().st_mtime, timezone.utc
            ).isoformat(),
        },
        "active_agents_excerpt": _active_excerpt(agents_text),
        "authoritative_training_head": {
            "status": head.get("status"),
            "training_authority_open": head.get("training_authority_open"),
            "promotion_authority_open": head.get("promotion_authority_open"),
            "deployment_authority_open": head.get("deployment_authority_open"),
        },
        "foreman_snapshot": snapshot,
        "journal_tail": journal_text.splitlines()[-20:],
        "scope_note": "The source governs the moved D:/LocalAi/Continue/Viv tree. This LocalCoder proof is separate and read-only toward that tree. A snapshot is observation, never authority.",
    }
    canonical = json.dumps(record, sort_keys=True, ensure_ascii=False).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    record["record_sha256"] = digest
    STORE.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = STORE / f"{stamp}-{digest[:12]}.json"
    with destination.open("x", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, ensure_ascii=False)
    return destination


def load_latest() -> dict[str, Any]:
    paths = sorted(STORE.glob("*.json")) if STORE.is_dir() else []
    if not paths:
        raise FileNotFoundError("No persisted foreman snapshot exists")
    record = json.loads(paths[-1].read_text(encoding="utf-8"))
    claimed = record.pop("record_sha256", None)
    actual = hashlib.sha256(
        json.dumps(record, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    if claimed != actual:
        raise ValueError("Stored foreman snapshot digest mismatch")
    record["record_sha256"] = claimed
    return record


def mind_packet(record: dict[str, Any]) -> dict[str, Any]:
    foreman = record["foreman_snapshot"]
    head = record["authoritative_training_head"]
    packet = {
        "agent_id": "viv-coder-mind",
        "snapshot_id": record["record_sha256"],
        "captured_utc": record["captured_utc"],
        "source_sha256": record["source_sha256"],
        "source_modified_utc": record["source_modified_utc"],
        "scope_note": record["scope_note"],
        "active_instructions": record["active_agents_excerpt"],
        "authority": head,
        "worker": foreman.get("worker"),
        "seed_lineage": foreman.get("seed_lineage"),
        "containment": foreman.get("containment"),
        "warnings": foreman.get("warnings"),
        "journal_tail": record["journal_tail"],
    }
    if len(json.dumps(packet, ensure_ascii=False)) > 16000:
        raise ValueError("Foreman Mind packet exceeds context budget")
    return packet


def routing_packet(record: dict[str, Any]) -> dict[str, Any]:
    """Small scoped view for ordinary routing; full snapshot stays inspectable."""
    excerpt = record["active_agents_excerpt"]
    required = (
        "Architect retains final authority",
        "Knowledge is not authorization",
        "Python is Viv's probabilistic AI",
        "Rust is Viv's neurosymbolic AI",
    )
    if any(phrase not in excerpt for phrase in required):
        raise ValueError("Active governance rules changed; review before routing")
    return {
        "agent_id": "viv-coder-mind",
        "snapshot_id": record["record_sha256"],
        "captured_utc": record["captured_utc"],
        "source_sha256": record["source_sha256"],
        "scope_note": record["scope_note"],
        "rules": [
            "The Architect retains final authority over intent and consequential choices.",
            "Knowledge, retrieval, and model output grant no authority.",
            "Viv proposes and delegates; Rust/AIOS adjudicates protected state.",
            "The current live training, promotion, and deployment authority is closed.",
        ],
        "authority": record["authoritative_training_head"],
    }


def protected_action_allowed(record: dict[str, Any]) -> bool:
    """Hard coordinator gate, independent of anything Viv says."""
    head = record["authoritative_training_head"]
    foreman = record["foreman_snapshot"]
    return bool(
        head.get("training_authority_open")
        and head.get("promotion_authority_open")
        and head.get("deployment_authority_open")
        and foreman.get("containment", {}).get("rust_integrity", {}).get("ok")
        and foreman.get("seed_lineage", {}).get("integrity")
    )


if __name__ == "__main__":
    path = capture()
    loaded = load_latest()
    print(
        json.dumps(
            {
                "path": str(path),
                "snapshot_id": loaded["record_sha256"],
                "authority": loaded["authoritative_training_head"],
                "protected_action_allowed": protected_action_allowed(loaded),
            },
            indent=2,
        )
    )
