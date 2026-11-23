import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from viv_context_store import DualContextMemory, MemoryPressureHold, PrivacyCore


class DualContextMemoryTests(unittest.TestCase):
    def make_policy(self, allowed_root):
        policy = PrivacyCore.__new__(PrivacyCore)
        policy.config = {
            "file_write_boundary": {
                "allowed_directories": [str(allowed_root)],
                "blocked_extensions": [".exe", ".bat", ".sh"],
            }
        }
        return policy

    def test_compaction_preserves_raw_memory_without_starting_learning(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            memory_dir = Path(temporary_directory)
            calls = []
            engine = types.SimpleNamespace(
                distill_ltm_to_lora_dataset=lambda: calls.append("distill")
            )
            module = types.ModuleType("lora_distill_engine")
            module.lora_engine = engine
            paths = {
                "MEMORY_DIR": memory_dir,
                "STM_FILE": memory_dir / "short_term_context.json",
                "LTM_RAW_FILE": memory_dir / "long_term_raw_dump.json",
                "LTM_ARCHIVE_FILE": memory_dir / "long_term_memory.json",
                "CHAT_HISTORY_FILE": memory_dir / "chat_transcript.json",
            }
            with patch.multiple("viv_context_store", **paths), patch.dict(
                sys.modules, {"lora_distill_engine": module}
            ):
                memory = DualContextMemory(privacy_core=self.make_policy(memory_dir))
                for index in range(10):
                    memory.append_dialogue_turn("user", f"turn {index}")
                memory._save_ltm_archive()

                raw_dump = json.loads(paths["LTM_RAW_FILE"].read_text(encoding="utf-8"))
                chat_history = json.loads(
                    paths["CHAT_HISTORY_FILE"].read_text(encoding="utf-8")
                )

            self.assertEqual(len(raw_dump), 1)
            self.assertEqual(len(raw_dump[0]["raw_turns"]), 10)
            self.assertEqual(len(chat_history), 2)
            self.assertEqual(calls, [])

    def test_memory_writes_fail_closed_outside_configured_root(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "outside.json"
            memory = DualContextMemory.__new__(DualContextMemory)
            memory.privacy_core = self.make_policy(Path(temporary_directory) / "allowed")
            memory.stm = {"current_step": "must not persist"}
            with patch("viv_context_store.STM_FILE", target):
                with self.assertRaises(PermissionError):
                    memory._save_stm()
            self.assertFalse(target.exists())

    def test_ram_pressure_compacts_raw_turns_before_appending(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            memory_dir = Path(temporary_directory)
            pressure = [50.0]
            paths = {
                "MEMORY_DIR": memory_dir,
                "STM_FILE": memory_dir / "short_term_context.json",
                "LTM_RAW_FILE": memory_dir / "long_term_raw_dump.json",
                "LTM_ARCHIVE_FILE": memory_dir / "long_term_memory.json",
                "CHAT_HISTORY_FILE": memory_dir / "chat_transcript.json",
            }
            with patch.multiple("viv_context_store", **paths):
                memory = DualContextMemory(
                    privacy_core=self.make_policy(memory_dir),
                    memory_pressure_reader=lambda: pressure[0],
                    disk_free_reader=lambda: 10 * 1024 * 1024 * 1024,
                )
                for index in range(4):
                    memory.append_dialogue_turn("user", f"turn {index}")
                pressure[0] = 90.0
                memory.append_dialogue_turn("assistant", "pressure-triggered turn")
                raw = json.loads(paths["LTM_RAW_FILE"].read_text(encoding="utf-8"))

        self.assertEqual(raw[-1]["trigger"], "ram_pressure_compaction")
        self.assertEqual(raw[-1]["ram_percent"], 90.0)
        self.assertEqual(len(raw[-1]["raw_turns"]), 4)
        self.assertEqual(memory.chat_history[-1]["content"], "pressure-triggered turn")

    def test_ram_at_95_holds_append_and_keeps_existing_turns_archived(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            memory_dir = Path(temporary_directory)
            paths = {
                "MEMORY_DIR": memory_dir,
                "STM_FILE": memory_dir / "short_term_context.json",
                "LTM_RAW_FILE": memory_dir / "long_term_raw_dump.json",
                "LTM_ARCHIVE_FILE": memory_dir / "long_term_memory.json",
                "CHAT_HISTORY_FILE": memory_dir / "chat_transcript.json",
            }
            with patch.multiple("viv_context_store", **paths):
                memory = DualContextMemory(
                    privacy_core=self.make_policy(memory_dir),
                    memory_pressure_reader=lambda: 95.0,
                    disk_free_reader=lambda: 10 * 1024 * 1024 * 1024,
                )
                memory.chat_history = [
                    {"role": "user", "content": f"existing {index}"}
                    for index in range(4)
                ]
                with self.assertRaisesRegex(MemoryPressureHold, "held memory write"):
                    memory.append_dialogue_turn("user", "must wait")
                raw = json.loads(paths["LTM_RAW_FILE"].read_text(encoding="utf-8"))
                transcript = json.loads(paths["CHAT_HISTORY_FILE"].read_text(encoding="utf-8"))

        self.assertEqual(raw[-1]["trigger"], "ram_pressure_hold")
        self.assertEqual(len(raw[-1]["raw_turns"]), 4)
        self.assertEqual(len(transcript), 2)

    def test_missing_ram_or_low_disk_telemetry_holds_memory_writes(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            memory_dir = Path(temporary_directory)
            memory = DualContextMemory(
                privacy_core=self.make_policy(memory_dir),
                memory_pressure_reader=lambda: None,
                disk_free_reader=lambda: 10 * 1024 * 1024 * 1024,
            )
            memory.chat_history = []
            with self.assertRaisesRegex(MemoryPressureHold, "RAM telemetry unavailable"):
                memory.append_dialogue_turn("user", "not persisted")

            memory.memory_pressure_reader = lambda: 50.0
            memory.disk_free_reader = lambda: 1024
            with self.assertRaisesRegex(MemoryPressureHold, "below 2 GiB"):
                memory.append_dialogue_turn("user", "also not persisted")

        self.assertEqual(memory.chat_history, [])

    def test_update_short_term_obeys_ram_and_disk_holds(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            memory_dir = Path(temporary_directory)
            paths = {
                "MEMORY_DIR": memory_dir,
                "STM_FILE": memory_dir / "short_term_context.json",
                "LTM_RAW_FILE": memory_dir / "long_term_raw_dump.json",
                "LTM_ARCHIVE_FILE": memory_dir / "long_term_memory.json",
                "CHAT_HISTORY_FILE": memory_dir / "chat_transcript.json",
            }
            with patch.multiple("viv_context_store", **paths):
                memory = DualContextMemory(
                    privacy_core=self.make_policy(memory_dir),
                    memory_pressure_reader=lambda: 95.0,
                    disk_free_reader=lambda: 10 * 1024 * 1024 * 1024,
                )
                memory.chat_history = []
                original_task = memory.stm["active_task"]
                with self.assertRaises(MemoryPressureHold):
                    memory.update_short_term("must hold", "step", "no write")
                self.assertEqual(memory.stm["active_task"], original_task)

                memory.memory_pressure_reader = lambda: 50.0
                memory.disk_free_reader = lambda: 1024
                with self.assertRaisesRegex(MemoryPressureHold, "below 2 GiB"):
                    memory.update_short_term("must also hold", "step", "no write")
                self.assertEqual(memory.stm["active_task"], original_task)
                self.assertFalse(paths["STM_FILE"].exists())


if __name__ == "__main__":
    unittest.main()
