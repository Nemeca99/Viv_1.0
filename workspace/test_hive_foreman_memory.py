import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import hive_foreman_memory as memory


class ForemanMemoryTests(unittest.TestCase):
    def test_capture_load_and_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(memory, "STORE", Path(directory)):
                path = memory.capture()
                self.assertTrue(path.is_file())
                loaded = memory.load_latest()
                packet = memory.mind_packet(loaded)
                self.assertEqual(packet["snapshot_id"], loaded["record_sha256"])
                self.assertEqual(packet["agent_id"], "viv-coder-mind")
                self.assertEqual(memory.routing_packet(loaded)["agent_id"], "viv-coder-mind")
                self.assertIn("active_instructions", packet)
                self.assertFalse(memory.protected_action_allowed(loaded))
                self.assertLess(len(json.dumps(packet)), 16000)

    def test_modified_snapshot_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(memory, "STORE", Path(directory)):
                path = memory.capture()
                record = json.loads(path.read_text(encoding="utf-8"))
                record["authoritative_training_head"]["training_authority_open"] = True
                path.write_text(json.dumps(record), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "digest mismatch"):
                    memory.load_latest()


if __name__ == "__main__":
    unittest.main()
