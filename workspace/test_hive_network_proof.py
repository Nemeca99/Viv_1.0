"""Fast security-boundary tests for the isolated Hive protocol proof."""
from __future__ import annotations

import unittest

from hive_network_proof import MindVault


class MindVaultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.vault = MindVault()
        self.ref = self.vault.seal_task(
            "task-test", "swarm-test", {"objective": "bounded", "parent": None}, None
        )

    def test_assigned_worker_opens_only_its_snapshot(self) -> None:
        self.assertEqual(self.vault.open_for_runner("task-test", "swarm-test"),
                         {"objective": "bounded", "parent": None})
        with self.assertRaises(PermissionError):
            self.vault.open_for_runner("task-test", "other-swarm")

    def test_worker_index_contains_only_master_wrapped_task_key(self) -> None:
        row = self.vault.index["task-test"]
        self.assertIn("wrapped_key", row)
        self.assertNotIn("task_key", row)
        self.assertNotEqual(bytes.fromhex(row["wrapped_key"]), self.vault.master)

    def test_ciphertext_tampering_is_detected(self) -> None:
        row = self.vault.index["task-test"]
        original = row["ciphertext"]
        row["ciphertext"] = ("00" if original[:2] != "00" else "ff") + original[2:]
        with self.assertRaises(ValueError):
            self.vault.open_for_runner("task-test", "swarm-test")

    def test_peer_channel_requires_direction_and_task_scoped_grant(self) -> None:
        self.assertFalse(self.vault.peer_channel_allowed("a", "b", "task-test"))
        grant, _key_hash, distinct = self.vault.create_channel_grant("a", "b", "task-test")
        self.assertTrue(distinct)
        self.assertTrue(self.vault.peer_channel_allowed("a", "b", "task-test", grant))
        self.assertFalse(self.vault.peer_channel_allowed("b", "a", "task-test", grant))
        self.assertFalse(self.vault.peer_channel_allowed("a", "b", "other-task", grant))

    def test_peer_message_is_encrypted_and_released_only_to_granted_receiver(self) -> None:
        with self.assertRaises(PermissionError):
            self.vault.encrypt_peer_message("a", "b", "task-test", "missing", "private")
        grant, _key_hash, _distinct = self.vault.create_channel_grant("a", "b", "task-test")
        envelope = self.vault.encrypt_peer_message("a", "b", "task-test", grant, "private")
        self.assertNotIn("private", str(envelope))
        self.assertEqual(self.vault.decrypt_peer_message(envelope, "b"), "private")
        with self.assertRaises(PermissionError):
            self.vault.decrypt_peer_message(envelope, "c")
        with self.assertRaises(PermissionError):
            self.vault.encrypt_peer_message("b", "a", "task-test", grant, "reverse")
        tampered = {**envelope, "ciphertext": "00" + envelope["ciphertext"][2:]}
        if tampered["ciphertext"] == envelope["ciphertext"]:
            tampered["ciphertext"] = "ff" + envelope["ciphertext"][2:]
        with self.assertRaises(Exception):
            self.vault.decrypt_peer_message(tampered, "b")

    def test_peer_channel_expires(self) -> None:
        grant, _key_hash, _distinct = self.vault.create_channel_grant("a", "b", "task-test")
        self.vault._channel_grants[("a", "b", "task-test", grant)]["expires_at"] = 0
        self.assertFalse(self.vault.peer_channel_allowed("a", "b", "task-test", grant))
        with self.assertRaises(PermissionError):
            self.vault.encrypt_peer_message("a", "b", "task-test", grant, "late")


if __name__ == "__main__":
    unittest.main()
