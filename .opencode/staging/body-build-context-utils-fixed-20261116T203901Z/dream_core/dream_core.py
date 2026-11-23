"""Dream Core for AIOS Viv.

Dream is a bounded offline memory pass, not a second authority. It reads only
explicitly configured sources, preserves them unchanged, writes hash-linked
consolidation receipts and candidate training turns, and never edits an active
adapter. Candidate admission/training remains a separate reviewed operation.

The 1 Hz kernel calls :meth:`tick`; the call is cheap while active or before
the configured idle threshold. A full pass is bounded by ``batch_size``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MEMORY_DIR = ROOT / "memory"
DEFAULT_STATE_DIR = Path(__file__).resolve().parent / "state"
SCHEMA = "aios_viv_dream_receipt_v1"
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_TEXT_CHARS = 8_000
TOKEN_RE = re.compile(r"[\w'-]+", re.UNICODE)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tokens(text: str) -> set[str]:
    return {token.casefold() for token in TOKEN_RE.findall(text) if len(token) > 2}


def _overlap(left: str, right: str) -> float:
    a, b = _tokens(left), _tokens(right)
    return len(a & b) / len(a | b) if a and b else 0.0


class DreamCore:
    """Idle-gated deterministic memory consolidation and candidate staging."""

    def __init__(
        self,
        memory_dir: Path | str = DEFAULT_MEMORY_DIR,
        state_dir: Path | str = DEFAULT_STATE_DIR,
        *,
        idle_seconds: float = 300.0,
        cycle_interval_seconds: float = 3600.0,
        batch_size: int = 32,
        similarity_threshold: float = 0.72,
        embedding_provider: Any | None = None,
        freshness_window_seconds: float = 24 * 60 * 60,
    ) -> None:
        if idle_seconds < 0 or cycle_interval_seconds < 0 or batch_size < 1:
            raise ValueError("idle/interval must be non-negative and batch_size >= 1")
        if not 0.0 <= similarity_threshold <= 1.0:
            raise ValueError("similarity_threshold must be between 0 and 1")
        if freshness_window_seconds < 0:
            raise ValueError("freshness_window_seconds must be non-negative")
        self.memory_dir = Path(memory_dir).resolve()
        self.state_dir = Path(state_dir).resolve()
        self.idle_seconds = float(idle_seconds)
        self.cycle_interval_seconds = float(cycle_interval_seconds)
        self.batch_size = int(batch_size)
        self.similarity_threshold = float(similarity_threshold)
        self.embedding_provider = embedding_provider
        self.freshness_window_seconds = float(freshness_window_seconds)
        self._lock = threading.Lock()
        self._idle_since: float | None = None
        self._last_cycle_at: float | None = None
        self._last_receipt: dict[str, Any] | None = None
        self._cycles = 0
        self._busy = False
        self.state_dir.mkdir(parents=True, exist_ok=True)

    @property
    def busy(self) -> bool:
        return self._busy

    def tick(self, *, system_busy: bool, now: float | None = None) -> dict[str, Any]:
        """Observe one heartbeat. Does no I/O while busy or before idle timeout."""
        current = time.monotonic() if now is None else float(now)
        if system_busy:
            self._idle_since = None
            return {"status": "deferred", "reason": "system_busy"}
        if self._idle_since is None:
            self._idle_since = current
            return {"status": "waiting", "reason": "idle_window_started"}
        if current - self._idle_since < self.idle_seconds:
            return {"status": "waiting", "reason": "idle_threshold_not_met"}
        if (
            self._last_cycle_at is not None
            and current - self._last_cycle_at < self.cycle_interval_seconds
        ):
            return {"status": "waiting", "reason": "cycle_cooldown"}
        result = self.run_cycle()
        if result.get("schema") == SCHEMA:
            self._last_cycle_at = current
        return result

    def run_cycle(
        self,
        records: Iterable[dict[str, Any]] | None = None,
        *,
        similarity_threshold: float | None = None,
    ) -> dict[str, Any]:
        """Run a bounded pass and append immutable receipt/candidates.

        ``records`` supports isolated deterministic harnesses. Normal operation
        reads the known workspace memory files; arbitrary paths are never read.
        """
        if not self._lock.acquire(blocking=False):
            return {"status": "deferred", "reason": "cycle_already_running"}
        self._busy = True
        started = time.monotonic()
        try:
            source_records = (
                list(records) if records is not None else self._load_workspace_records()
            )
            source_records = source_records[: self.batch_size]
            normalized, excluded = self._normalize_records(source_records)
            clusters = self._cluster(normalized, similarity_threshold)
            candidate_rows = self._new_candidates(self._candidate_turns(normalized))
            receipt = self._make_receipt(
                normalized, excluded, clusters, candidate_rows, started
            )
            self._append_jsonl(self.state_dir / "consolidations.jsonl", receipt)
            if candidate_rows:
                self._append_jsonl(
                    self.state_dir / "candidate_turns.jsonl", candidate_rows
                )
            self._last_receipt = receipt
            self._last_cycle_at = time.monotonic()
            self._cycles += 1
            self._busy = False
            self._write_status()
            return receipt
        finally:
            self._busy = False
            self._lock.release()

    def _load_workspace_records(self) -> list[dict[str, Any]]:
        """Read only workspace memory inputs and leave every source untouched."""
        records: list[dict[str, Any]] = []
        for filename in ("chat_transcript.json", "long_term_raw_dump.json"):
            path = self.memory_dir / filename
            if not path.is_file():
                continue
            size = path.stat().st_size
            if size > MAX_SOURCE_BYTES:
                records.append(
                    {"_excluded": f"source_too_large:{filename}", "source": filename}
                )
                continue
            raw = path.read_bytes()
            source_hash = _sha256(raw)
            try:
                data = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                records.append(
                    {
                        "_excluded": f"invalid_json:{filename}",
                        "source": filename,
                        "source_hash": source_hash,
                    }
                )
                continue
            groups = data if isinstance(data, list) else [data]
            for group_index, group in enumerate(groups):
                if not isinstance(group, dict):
                    continue
                turns = group.get("messages", group.get("raw_turns"))
                if not isinstance(turns, list):
                    turns = [group] if isinstance(group.get("role"), str) else []
                for turn_index, turn in enumerate(turns):
                    if not isinstance(turn, dict):
                        continue
                    records.append(
                        {
                            "source": filename,
                            "source_hash": source_hash,
                            "source_id": f"{filename}:{group_index}:{turn_index}",
                            "role": turn.get("role"),
                            "text": turn.get("content", turn.get("text", "")),
                            "timestamp": turn.get("timestamp"),
                            "provenance": "workspace_memory_unverified",
                        }
                    )
        return records

    def _normalize_records(
        self, records: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        normalized: list[dict[str, Any]] = []
        excluded: list[dict[str, str]] = []
        for index, item in enumerate(records):
            if not isinstance(item, dict):
                excluded.append({"index": str(index), "reason": "record_not_object"})
                continue
            if item.get("_excluded"):
                excluded.append({"index": str(index), "reason": str(item["_excluded"])})
                continue
            role, text = item.get("role"), item.get("text", item.get("content", ""))
            if role not in {"user", "assistant", "system", "tool"}:
                excluded.append({"index": str(index), "reason": "unknown_role"})
                continue
            if not isinstance(text, str) or not text.strip():
                excluded.append({"index": str(index), "reason": "empty_text"})
                continue
            text = text.strip()[:MAX_TEXT_CHARS]
            source = str(item.get("source", "provided_record"))
            source_id = str(item.get("source_id", f"record:{index}"))
            source_hash = str(item.get("source_hash") or _sha256(_canonical(item)))
            record = {
                "source": source,
                "source_id": source_id,
                "source_hash": source_hash,
                "role": role,
                "text": text,
                "text_hash": _sha256(text.encode("utf-8")),
                "timestamp": item.get("timestamp"),
                "provenance": str(item.get("provenance", "unverified")),
            }
            normalized.append(record)
        return normalized, excluded

    def consolidate_conversation_fragments(
        self,
        similarity_threshold: float = 0.8,
        verbose: bool = False,
        pulse_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Compatibility API for AIOS heartbeat callers; sources remain read-only."""
        if not 0.0 <= similarity_threshold <= 1.0:
            raise ValueError("similarity_threshold must be between 0 and 1")
        pulse_bpm = 0.0
        if pulse_context is not None:
            try:
                pulse_bpm = float(pulse_context.get("pulse_bpm", 0.0))
            except (TypeError, ValueError) as error:
                raise ValueError("pulse_bpm must be numeric") from error
            if not 0.0 <= pulse_bpm < float("inf"):
                raise ValueError("pulse_bpm must be finite and non-negative")
        hot = pulse_bpm >= 0.02
        mode = "hot_path" if hot else "cold_path"
        threshold = (
            min(0.9, similarity_threshold + 0.1) if hot else similarity_threshold
        )
        result = self.run_cycle(similarity_threshold=threshold)
        result.update(
            {
                "mode": mode,
                "pulse_bpm": pulse_bpm,
                "similarity_threshold": threshold,
                "verbose_requested": bool(verbose),
                "source_records_modified": False,
            }
        )
        return result

    def pulse(self, pulse_context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Legacy heartbeat entrypoint routed through the idle gate."""
        result = self.tick(system_busy=False)
        pulse_bpm = (
            0.0 if pulse_context is None else float(pulse_context.get("pulse_bpm", 0.0))
        )
        result["mode"] = "hot_path" if pulse_bpm >= 0.02 else "cold_path"
        result["pulse_bpm"] = pulse_bpm
        return result

    def _cluster(
        self,
        records: list[dict[str, Any]],
        similarity_threshold: float | None = None,
    ) -> list[list[dict[str, Any]]]:
        """Group near-duplicate turns by role; preserve all underlying source IDs."""
        threshold = (
            self.similarity_threshold
            if similarity_threshold is None
            else similarity_threshold
        )
        by_role: dict[str, list[list[dict[str, Any]]]] = defaultdict(list)
        embedding_cache: dict[str, Any] = {}
        similarity_mode = "token_jaccard_fallback"
        if self.embedding_provider is not None:
            import numpy as np

            for record in records:
                vector = np.asarray(
                    self.embedding_provider(record["text"]), dtype=np.float32
                )
                if vector.ndim != 1 or vector.size == 0 or not np.isfinite(vector).all():
                    raise ValueError("embedding provider must return a finite non-empty vector")
                embedding_cache[record["source_id"]] = vector
            dimensions = {vector.size for vector in embedding_cache.values()}
            if len(dimensions) > 1:
                raise ValueError("embedding vectors must have equal dimensions")
            similarity_mode = "cosine_embedding"

        def similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
            if similarity_mode == "cosine_embedding":
                import numpy as np

                a, b = embedding_cache[left["source_id"]], embedding_cache[right["source_id"]]
                denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
                return float(np.dot(a, b) / denominator) if denominator else 0.0
            return _overlap(left["text"], right["text"])

        for record in records:
            placed = False
            for cluster in by_role[record["role"]]:
                if any(
                    similarity(record, member) >= threshold
                    for member in cluster
                ):
                    cluster.append(record)
                    placed = True
                    break
            if not placed:
                by_role[record["role"]].append([record])
        self._last_similarity_mode = similarity_mode
        return [cluster for role in sorted(by_role) for cluster in by_role[role]]

    def _is_fresh(self, record: dict[str, Any], *, now: datetime | None = None) -> bool:
        """Fail closed for missing/invalid timestamps; recent records are immune."""
        timestamp = record.get("timestamp")
        if not isinstance(timestamp, str) or not timestamp.strip():
            return True
        try:
            observed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            return True
        if observed.tzinfo is None:
            return True
        current = now or datetime.now(timezone.utc)
        age = (current - observed.astimezone(timezone.utc)).total_seconds()
        return age < self.freshness_window_seconds

    def _candidate_turns(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Stage observed adjacent user/assistant turns, never auto-admitting."""
        candidates: list[dict[str, Any]] = []
        by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in records:
            # The source_id convention is <file>:<conversation-index>:<turn-index>.
            source_group = ":".join(record["source_id"].split(":")[:-1])
            by_source[source_group].append(record)
        code_terms = {
            "python",
            "rust",
            "function",
            "class",
            "compile",
            "import",
            "numpy",
            "code",
            "file",
        }
        for source_group, source_rows in sorted(by_source.items()):
            source_rows.sort(
                key=lambda row: (
                    int(row["source_id"].rsplit(":", 1)[-1])
                    if row["source_id"].rsplit(":", 1)[-1].isdigit()
                    else 0
                )
            )
            for user, assistant in zip(source_rows, source_rows[1:]):
                if user["role"] != "user" or assistant["role"] != "assistant":
                    continue
                if self._is_fresh(user) or self._is_fresh(assistant):
                    continue
                source_ids = [user["source_id"], assistant["source_id"]]
                source_hashes = sorted({user["source_hash"], assistant["source_hash"]})
                pair_id = _sha256(
                    _canonical({"sources": source_ids, "hashes": source_hashes})
                )
                lexical = _tokens(user["text"])
                suggestion = (
                    "skill_specialist_lora"
                    if lexical & code_terms
                    else "plugin_identity_lora"
                )
                candidates.append(
                    {
                        "schema": "aios_viv_dream_candidate_v1",
                        "candidate_id": pair_id,
                        "suggested_adapter_target": suggestion,
                        "state": "PENDING_QUALITY_CORRECTNESS_TRUTH_REVIEW",
                        "messages": [
                            {"role": "user", "content": user["text"]},
                            {"role": "assistant", "content": assistant["text"]},
                        ],
                        "source_ids": source_ids,
                        "source_sha256": source_hashes,
                        "provenance": [user["provenance"], assistant["provenance"]],
                        "source_group": source_group,
                        "quality": {"adjacent_observed_turn_pair": True},
                        "admitted_for_training": False,
                        "created_at": _utc_now(),
                    }
                )
        return candidates

    def _make_receipt(
        self,
        records: list[dict[str, Any]],
        excluded: list[dict[str, str]],
        clusters: list[list[dict[str, Any]]],
        candidates: list[dict[str, Any]],
        started: float,
    ) -> dict[str, Any]:
        payload = {
            "schema": SCHEMA,
            "created_at": _utc_now(),
            "status": "COMPLETE_WITH_QUARANTINE"
            if excluded or candidates
            else "COMPLETE_NO_PROMOTABLE_DATA",
            "source_count": len({row["source"] for row in records}),
            "records_processed": len(records),
            "records_excluded": excluded,
            "cluster_count": len(clusters),
            "duplicate_records_grouped": sum(
                max(0, len(group) - 1) for group in clusters
            ),
            "candidate_count": len(candidates),
            "similarity_mode": getattr(self, "_last_similarity_mode", "token_jaccard_fallback"),
            "freshness_window_seconds": self.freshness_window_seconds,
            "candidate_state": "PENDING_QUALITY_CORRECTNESS_TRUTH_REVIEW",
            "adapter_training_started": False,
            "source_records_modified": False,
            "active_adapters_modified": False,
            "duration_ms": round((time.monotonic() - started) * 1000, 3),
            "records": [
                {
                    key: row[key]
                    for key in (
                        "source",
                        "source_id",
                        "source_hash",
                        "role",
                        "text_hash",
                        "provenance",
                    )
                }
                for row in records
            ],
            "candidate_ids": [row["candidate_id"] for row in candidates],
        }
        payload["receipt_sha256"] = _sha256(_canonical(payload))
        return payload

    @staticmethod
    def _append_jsonl(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = value if isinstance(value, list) else [value]
        encoded = "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
        )
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())

    def _new_candidates(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Make repeated idle cycles idempotent for unchanged source turns."""
        path = self.state_dir / "candidate_turns.jsonl"
        known: set[str] = set()
        if path.is_file():
            with path.open("r", encoding="utf-8") as stream:
                for line in stream:
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(row, dict) and isinstance(
                        row.get("candidate_id"), str
                    ):
                        known.add(row["candidate_id"])
        return [row for row in candidates if row["candidate_id"] not in known]

    def _write_status(self) -> None:
        status = {
            "schema": "aios_viv_dream_status_v1",
            "updated_at": _utc_now(),
            "busy": self._busy,
            "cycles_completed": self._cycles,
            "last_cycle_monotonic": self._last_cycle_at,
            "last_receipt_sha256": self._last_receipt.get("receipt_sha256")
            if self._last_receipt
            else None,
            "mode": "idle_gated_candidate_generation_only",
        }
        temporary = self.state_dir / "status.json.tmp"
        temporary.write_text(
            json.dumps(status, indent=2, sort_keys=True), encoding="utf-8"
        )
        temporary.replace(self.state_dir / "status.json")

    def get_status(self) -> dict[str, Any]:
        return {
            "status": "busy" if self._busy else "idle",
            "cycles_completed": self._cycles,
            "last_receipt_sha256": self._last_receipt.get("receipt_sha256")
            if self._last_receipt
            else None,
            "mode": "idle_gated_candidate_generation_only",
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one bounded AIOS Viv Dream Core consolidation pass"
    )
    parser.add_argument("--memory-dir", type=Path, default=DEFAULT_MEMORY_DIR)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--idle-seconds", type=float, default=300.0)
    parser.add_argument("--similarity-threshold", type=float, default=0.72)
    args = parser.parse_args()
    core = DreamCore(
        args.memory_dir,
        args.state_dir,
        idle_seconds=args.idle_seconds,
        batch_size=args.batch_size,
        similarity_threshold=args.similarity_threshold,
    )
    print(json.dumps(core.run_cycle(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
