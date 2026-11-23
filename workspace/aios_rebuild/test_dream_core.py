"""Behavioral checks for Dream's idle, evidence, and no-promotion boundaries."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dream_core.dream_core import DreamCore
from dream_core.training_gate import stage_admitted_candidates


class DreamCoreBehaviorTests(unittest.TestCase):
    def test_legacy_pulse_mode_is_returned_when_no_conversation_directory_exists(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            core = DreamCore(root / "missing-memory", root / "state", idle_seconds=0)
            hot = core.consolidate_conversation_fragments(
                pulse_context={"pulse_bpm": 0.05}
            )
            cold = core.consolidate_conversation_fragments(
                pulse_context={"pulse_bpm": 0.01}
            )
            self.assertEqual(hot["mode"], "hot_path")
            self.assertEqual(cold["mode"], "cold_path")
            self.assertFalse(hot["source_records_modified"])

    def test_idle_gate_runs_once_and_busy_activity_resets_window(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            core = DreamCore(
                root / "memory",
                root / "state",
                idle_seconds=2,
                cycle_interval_seconds=100,
                batch_size=8,
            )
            self.assertEqual(core.tick(system_busy=False, now=0)["status"], "waiting")
            self.assertEqual(
                core.tick(system_busy=True, now=1)["reason"], "system_busy"
            )
            self.assertEqual(
                core.tick(system_busy=False, now=2)["reason"], "idle_window_started"
            )
            self.assertEqual(core.tick(system_busy=False, now=3)["status"], "waiting")
            receipt = core.tick(system_busy=False, now=4)
            self.assertEqual(receipt["schema"], "aios_viv_dream_receipt_v1")
            self.assertEqual(
                core.tick(system_busy=False, now=5)["reason"], "cycle_cooldown"
            )

    def test_source_is_preserved_candidates_are_linked_and_never_auto_admitted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            memory = root / "memory"
            state = root / "state"
            memory.mkdir()
            transcript = memory / "chat_transcript.json"
            transcript.write_text(
                json.dumps(
                    [
                        {
                            "messages": [
                                {
                                    "role": "user",
                                    "content": "Write a Python function to add two numbers.",
                                    "timestamp": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
                                },
                                {
                                    "role": "assistant",
                                    "content": "def add(a, b): return a + b",
                                    "timestamp": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
                                },
                                {
                                    "role": "user",
                                    "content": "How should we validate it?",
                                    "timestamp": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
                                },
                                {
                                    "role": "assistant",
                                    "content": "Run a deterministic unit test.",
                                    "timestamp": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
                                },
                            ]
                        }
                    ]
                ),
                encoding="utf-8",
            )
            original_bytes = transcript.read_bytes()
            original_hash = hashlib.sha256(original_bytes).hexdigest()

            core = DreamCore(memory, state, batch_size=16)
            first = core.run_cycle()
            self.assertEqual(first["candidate_count"], 2)
            self.assertFalse(first["source_records_modified"])
            self.assertFalse(first["active_adapters_modified"])
            self.assertFalse(first["adapter_training_started"])
            self.assertEqual(
                hashlib.sha256(transcript.read_bytes()).hexdigest(), original_hash
            )

            candidate_path = state / "candidate_turns.jsonl"
            candidates = [
                json.loads(line)
                for line in candidate_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(candidates), 2)
            self.assertTrue(
                all(row["admitted_for_training"] is False for row in candidates)
            )
            self.assertTrue(
                all(
                    row["state"] == "PENDING_QUALITY_CORRECTNESS_TRUTH_REVIEW"
                    for row in candidates
                )
            )
            self.assertRegex(first["receipt_sha256"], r"^[0-9a-f]{64}$")

            second = core.run_cycle()
            self.assertEqual(
                second["candidate_count"],
                0,
                "unchanged source must not duplicate candidates",
            )
            self.assertEqual(
                len(candidate_path.read_text(encoding="utf-8").splitlines()), 2
            )

    def test_recent_turns_are_excluded_without_repairing_adjacency(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            now = datetime.now(timezone.utc)
            old = (now - timedelta(days=2)).isoformat()
            fresh = now.isoformat()
            records = [
                {"role": "user", "text": "old request", "source_id": "c:0", "timestamp": old},
                {"role": "assistant", "text": "recent answer", "source_id": "c:1", "timestamp": fresh},
                {"role": "user", "text": "recent request", "source_id": "c:2", "timestamp": fresh},
                {"role": "assistant", "text": "old answer", "source_id": "c:3", "timestamp": old},
            ]
            core = DreamCore(root / "memory", root / "state")
            receipt = core.run_cycle(records)
            self.assertEqual(receipt["candidate_count"], 0)

    def test_cosine_embedding_provider_is_used_and_labeled(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def provider(text: str) -> list[float]:
                return [1.0, 0.0] if "alpha" in text else [0.0, 1.0]

            core = DreamCore(root / "memory", root / "state", embedding_provider=provider)
            old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
            core.run_cycle([
                {"role": "user", "text": "alpha", "source_id": "a", "timestamp": old},
                {"role": "user", "text": "beta", "source_id": "b", "timestamp": old},
            ])
            receipt = json.loads((root / "state" / "consolidations.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(receipt["similarity_mode"], "cosine_embedding")
            self.assertEqual(receipt["duplicate_records_grouped"], 0)

    def test_missing_timestamp_is_not_admitted_for_candidate_generation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            core = DreamCore(root / "memory", root / "state")
            receipt = core.run_cycle([
                {"role": "user", "text": "request", "source_id": "c:0"},
                {"role": "assistant", "text": "answer", "source_id": "c:1"},
            ])
            self.assertEqual(receipt["candidate_count"], 0)

    def test_training_gate_rejects_pending_rows_and_stages_only_explicitly_admitted(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate_path = root / "candidates.jsonl"
            pending = {
                "candidate_id": "pending-1",
                "state": "PENDING_QUALITY_CORRECTNESS_TRUTH_REVIEW",
                "admitted_for_training": False,
                "messages": [
                    {"role": "user", "content": "u"},
                    {"role": "assistant", "content": "a"},
                ],
            }
            candidate_path.write_text(json.dumps(pending) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "no candidates passed"):
                stage_admitted_candidates(candidate_path, root / "staged")

            approved = {
                **pending,
                "candidate_id": "approved-1",
                "state": "ADMITTED_BY_ARCHITECT",
                "admitted_for_training": True,
                "adapter_target": "skill_specialist_lora",
                "source_ids": ["transcript:0:0", "transcript:0:1"],
                "source_sha256": ["a" * 64],
                "review": {
                    "quality": "PASS",
                    "correctness": "PASS",
                    "truth": "PASS",
                    "reviewer": "Architect",
                    "reviewed_at": "2026-09-29T00:00:00Z",
                    "evidence": ["test-receipt-sha256"],
                },
            }
            candidate_path.write_text(
                json.dumps(pending) + "\n" + json.dumps(approved) + "\n",
                encoding="utf-8",
            )
            manifest = stage_admitted_candidates(candidate_path, root / "staged")
            self.assertEqual(len(manifest["accepted_candidates"]), 1)
            self.assertEqual(set(manifest["datasets"]), {"skill_specialist_lora"})
            dataset_path = Path(manifest["datasets"]["skill_specialist_lora"])
            staged_row = json.loads(dataset_path.read_text(encoding="utf-8").strip())
            self.assertEqual(staged_row["messages"], approved["messages"])
            self.assertFalse(manifest["active_adapter_modified"])
            self.assertFalse(manifest["training_started"])


if __name__ == "__main__":
    unittest.main()
