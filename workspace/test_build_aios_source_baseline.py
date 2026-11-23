"""Tests for source-boundary and dependency-map behavior in the AIOS catalog."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from build_aios_source_baseline import CORE_NAMES, build_manifest


class SourceBaselineTests(unittest.TestCase):
    def test_catalog_tracks_all_manual_cores_and_static_cross_core_imports(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sections = "\n".join(
                f"## 3.{index} {name} - Test"
                for index, name in enumerate(CORE_NAMES, 1)
            )
            (root / "AIOS_MANUAL.md").write_text(sections, encoding="utf-8")
            (root / "MANUAL_TOC.md").write_text("# TOC\n", encoding="utf-8")
            for name in CORE_NAMES:
                core = root / name
                core.mkdir()
                (core / "__init__.py").write_text("\n", encoding="utf-8")
            (root / "luna_core" / "links.py").write_text(
                "from carma_core import memory\n", encoding="utf-8"
            )
            (root / "carma_core" / "links.py").write_text(
                "from utils_core import hashing\n", encoding="utf-8"
            )
            private_state = root / "carma_core" / "storage"
            private_state.mkdir()
            (private_state / "conversation.json").write_text("{}", encoding="utf-8")
            active_backup = root / "backup_core" / "active_backup"
            active_backup.mkdir()
            (active_backup / "copied_core.py").write_text(
                "broken !!!", encoding="utf-8"
            )

            manifest = build_manifest(root)
            self.assertEqual(
                [row["name"] for row in manifest["cores"]], list(CORE_NAMES)
            )
            self.assertEqual(manifest["file_count"], len(manifest["files"]))
            paths = {row["path"] for row in manifest["files"]}
            self.assertIn("luna_core/links.py", paths)
            self.assertNotIn("carma_core/storage/conversation.json", paths)
            self.assertNotIn("backup_core/active_backup/copied_core.py", paths)
            edges = {
                (row["consumer"], row["provider"])
                for row in manifest["static_cross_core_import_edges"]
            }
            self.assertIn(("luna_core", "carma_core"), edges)
            self.assertIn(("carma_core", "utils_core"), edges)
            graph = manifest["static_rebuild_graph"]
            self.assertEqual(graph["cycle_nodes"], [])
            positions = {
                name: layer_index
                for layer_index, layer in enumerate(graph["layers"])
                for name in layer
            }
            self.assertEqual(set(positions), set(CORE_NAMES))
            for consumer, providers in graph["dependencies"].items():
                for provider in providers:
                    self.assertLess(positions[provider], positions[consumer])

    def test_manual_core_order_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "AIOS_MANUAL.md").write_text(
                "## 3.1 wrong_core - Test\n", encoding="utf-8"
            )
            (root / "MANUAL_TOC.md").write_text("# TOC\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "manual core order differs"):
                build_manifest(root)


if __name__ == "__main__":
    unittest.main()
