"""Append-only conversation observation journal; this module does not train.

The previous implementation appended transcript rows and incremented a
``trained_turns_count`` field without updating any model weights. The old file
is retained as legacy evidence and is never consumed by this journal.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
MEMORY_DIR = ROOT / "memory"
OBSERVATION_FILE = MEMORY_DIR / "lora_adapters" / "unreviewed_observations.jsonl"
LEGACY_DATASET_FILE = MEMORY_DIR / "lora_adapters" / "realtime_lora_dataset.jsonl"
LEGACY_MANIFEST_FILE = MEMORY_DIR / "lora_adapters" / "active_lora_manifest.json"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ConversationObservationJournal:
    """Stores chat observations for later review; it never claims to train."""

    def __init__(self, path: Path = OBSERVATION_FILE):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record_observation(self, user_turn: str, assistant_turn: str) -> dict[str, Any]:
        if not isinstance(user_turn, str) or not isinstance(assistant_turn, str):
            raise TypeError("conversation turns must be strings")
        row: dict[str, Any] = {
            "schema": "viv_unreviewed_conversation_observation_v1",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "kind": "observation_only",
            "messages": [
                {"role": "user", "content": user_turn},
                {"role": "assistant", "content": assistant_turn},
            ],
            "source_sha256": [_sha256(user_turn), _sha256(assistant_turn)],
            "training_status": "NOT_TRAINED",
            "admitted_for_training": False,
        }
        canonical = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        row["event_sha256"] = _sha256(canonical)
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return {"status": "LOGGED_NOT_TRAINED", "event_sha256": row["event_sha256"], "path": str(self.path)}

    def training_status(self) -> dict[str, Any]:
        legacy_count = 0
        if LEGACY_DATASET_FILE.is_file():
            with LEGACY_DATASET_FILE.open("r", encoding="utf-8") as stream:
                legacy_count = sum(1 for line in stream if line.strip())
        return {
            "status": "NO_TRAINING_PERFORMED_BY_CHAT_JOURNAL",
            "weights_updated": False,
            "unreviewed_observation_file": str(self.path),
            "legacy_rows_quarantined_from_runtime_training": legacy_count,
            "legacy_manifest_path": str(LEGACY_MANIFEST_FILE),
        }

    def distill_ltm_to_lora_dataset(self) -> str:
        """Compatibility stub: old memory compaction code may call this method."""
        return "NO_TRAINING: LTM remains evidence; Dream admission is required before a separate candidate run."


# Existing caller name retained as a compatibility import; behavior is logging only.
RealtimeLoRAEngine = ConversationObservationJournal
lora_engine = ConversationObservationJournal()


if __name__ == "__main__":
    print(json.dumps(lora_engine.training_status(), indent=2))
