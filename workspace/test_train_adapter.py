"""Regression tests for assistant-target masking and prompt truncation."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from aios_rebuild.main_core.mind_runtime_gate import BodyRuntimeHold
from swarm_adapters import train_adapter
from swarm_adapters.train_adapter import BodyRuntimeCallback, ChatDataset


class CharacterTokenizer:
    """Small deterministic tokenizer sufficient to test dataset boundary logic."""

    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt,
                            enable_thinking=False):
        text = "".join(f"<{message['role']}>\n{message['content']}\n"
                       for message in messages)
        if add_generation_prompt:
            text += "<assistant>\n"
        return text

    def __call__(self, text, *, add_special_tokens=False, truncation=False,
                 max_length=None):
        tokens = [ord(char) for char in text]
        if truncation and max_length is not None:
            tokens = tokens[:max_length]
        return {"input_ids": tokens}


class ChatDatasetTests(unittest.TestCase):
    def make_dataset(self, assistant_text: str, max_length: int):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "train.jsonl"
        row = {"messages": [
            {"role": "system", "content": "law and task instructions " * 20},
            {"role": "user", "content": "source evidence and question " * 20},
            {"role": "assistant", "content": assistant_text},
        ]}
        path.write_text(json.dumps(row) + "\n", encoding="utf-8")
        return ChatDataset(path, CharacterTokenizer(), max_length)

    def test_left_truncation_preserves_assistant_targets(self):
        dataset = self.make_dataset("useful answer", max_length=48)
        row = dataset[0]
        self.assertEqual(len(row["input_ids"]), 48)
        self.assertGreater(dataset.supervised_token_counts[0], 0)
        self.assertEqual(dataset.supervised_token_counts[0], len("useful answer\n"))
        self.assertEqual(row["input_ids"][-len("useful answer\n"):].tolist(),
                         [ord(char) for char in "useful answer\n"])
        self.assertEqual(dataset.context_truncated_rows, 1)

    def test_empty_assistant_target_fails_before_training(self):
        with self.assertRaisesRegex(ValueError, "empty assistant target content"):
            self.make_dataset("", max_length=48)

    def test_assistant_target_larger_than_context_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "does not fit max_length"):
            self.make_dataset("answer" * 20, max_length=48)


class BodyRuntimeTrainingGateTests(unittest.TestCase):
    def test_direct_training_body_hold_prevents_cuda_setup_and_output_creation(self):
        guard = type("HeldGuard", (), {
            "check": lambda self, force=False: (_ for _ in ()).throw(
                BodyRuntimeHold({"allowed": False, "disposition": "HOLD_MIND_RUNTIME"})
            ),
        })()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "candidate"
            arguments = [
                "train_adapter.py",
                "--base", str(root / "base"),
                "--dataset", str(root / "dataset.jsonl"),
                "--output", str(output),
                "--adapter-name", "candidate",
            ]
            with patch("sys.argv", arguments), \
                 patch.object(train_adapter, "_body_runtime_guard", return_value=guard), \
                 patch.object(train_adapter.torch.cuda, "manual_seed_all") as seed_gpu, \
                 patch.object(train_adapter.AutoTokenizer, "from_pretrained") as load_tokenizer:
                with self.assertRaises(BodyRuntimeHold):
                    train_adapter.main()
            seed_gpu.assert_not_called()
            load_tokenizer.assert_not_called()
            self.assertFalse(output.exists())

    def test_training_callback_rechecks_body_before_an_optimizer_step(self):
        guard = type("Guard", (), {"check": lambda self: {"allowed": True}})()
        callback = BodyRuntimeCallback(guard)
        control = object()
        self.assertIs(callback.on_step_begin(None, None, control), control)


if __name__ == "__main__":
    unittest.main()
