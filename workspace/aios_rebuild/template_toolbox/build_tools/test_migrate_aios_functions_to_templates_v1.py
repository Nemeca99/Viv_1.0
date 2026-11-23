from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from build_tools.migrate_aios_functions_to_templates_v1 import MigrationPaths, migrate


class AiosFunctionTemplateMigrationTests(unittest.TestCase):
    def _paths(self, root: Path) -> MigrationPaths:
        foundation = root / "foundation"
        return MigrationPaths(
            repo_root=root,
            foundation_root=foundation,
            output_root=foundation / "code_templates" / "source" / "migrated_domains",
            artifact_root=foundation / "artifacts" / "auto" / "code_templates" / "migration",
        )

    def _write_fixture_sources(self, root: Path) -> tuple[Path, bytes, bytes]:
        foundation = root / "foundation"
        lib = foundation / "lib"
        lib.mkdir(parents=True)
        (foundation / "rid_main.py").write_text(
            "from typing import Any\n\n\ndef main(argv):\n    return argv\n",
            encoding="utf-8",
        )
        (foundation / "auto_main.py").write_text(
            "def main(argv):\n    return argv\n",
            encoding="utf-8",
        )
        (foundation / "uml_main.py").write_text(
            "def main(argv):\n    return argv\n",
            encoding="utf-8",
        )
        source = (
            "from typing import Any\n"
            "\n"
            "LIMIT = 3\n"
            "\n"
            "def helper(value):\n"
            "    return value + LIMIT\n"
            "\n"
            "def main(argv):\n"
            "    return helper(argv)\n"
        ).encode("utf-8")
        path = lib / "aios_adapter_demo.py"
        path.write_bytes(
            source.replace(
                b"from typing import Any\n",
                b"from typing import Any\nfrom lib.helper_mod import external\n",
            ).replace(
                b"    return helper(argv)\n",
                b"    return external(helper(argv))\n",
            )
        )
        (lib / "helper_mod.py").write_text(
            "def external(value):\n    return value\n",
            encoding="utf-8",
        )
        source = path.read_bytes()
        return path, source, b""

    def test_dry_run_scans_without_creating_templates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_fixture_sources(root)
            paths = self._paths(root)
            report = migrate(paths, apply=False)
            self.assertTrue(report["ok"])
            self.assertEqual(report["state"], "DRY_RUN")
            self.assertFalse(paths.output_root.exists())
            self.assertFalse(paths.artifact_root.exists())
            self.assertGreaterEqual(report["function_count"], 4)

    def test_apply_copies_source_bytes_and_records_function_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path, source_bytes, _ = self._write_fixture_sources(root)
            paths = self._paths(root)
            report = migrate(paths, apply=True)
            self.assertTrue(report["ok"])
            self.assertFalse(report["active_registry_updated"])
            self.assertTrue(report["human_review_required_before_activation"])
            destination = paths.output_root / "adapters" / "foundation__lib__aios_adapter_demo.py"
            self.assertEqual(destination.read_bytes(), source_bytes)

            manifest = json.loads((paths.artifact_root / "AIOS_FUNCTION_TEMPLATE_MIGRATION.json").read_text(encoding="utf-8"))
            row = next(item for item in manifest["files"] if item["source_path"] == "foundation/lib/aios_adapter_demo.py")
            self.assertEqual(row["template_path"], "foundation/code_templates/source/migrated_domains/adapters/foundation__lib__aios_adapter_demo.py")
            self.assertTrue(row["byte_exact_copy"])
            main = next(item for item in row["functions"] if item["name"] == "main")
            self.assertEqual(main["source_start_line"], 9)
            self.assertEqual(main["source_end_line"], 10)
            self.assertEqual(main["template_start_line"], 9)
            self.assertEqual(main["template_end_line"], 10)
            self.assertEqual(main["direct_calls"], ["helper"])
            self.assertEqual(main["used_function_closure"], ["helper", "main"])
            self.assertEqual(
                main["resolved_function_calls"],
                ["lib.aios_adapter_demo:helper", "lib.helper_mod:external"],
            )
            self.assertEqual(row["resolved_module_dependencies"], ["lib.helper_mod"])
            self.assertIn("lib.aios_adapter_demo:helper", main["resolved_function_closure"])
            self.assertIn("lib.helper_mod:external", main["resolved_function_closure"])
            self.assertEqual(row["source_sha256"], row["template_sha256"])
            function_index = json.loads((paths.artifact_root / "function_index.json").read_text(encoding="utf-8"))
            indexed_main = next(item for item in function_index["entries"] if item["source_path"] == row["source_path"] and item["name"] == "main")
            self.assertEqual(indexed_main["template_path"], row["template_path"])
            self.assertEqual(indexed_main["template_start_line"], 9)
            self.assertEqual(indexed_main["template_end_line"], 10)

    def test_existing_output_requires_explicit_replace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_fixture_sources(root)
            paths = self._paths(root)
            self.assertTrue(migrate(paths, apply=True)["ok"])
            held = migrate(paths, apply=True)
            self.assertFalse(held["ok"])
            self.assertEqual(held["reason"], "migration_output_exists_use_replace")
            stale = paths.output_root / "obsolete" / "old.py"
            stale.parent.mkdir(parents=True)
            stale.write_text("obsolete = True\n", encoding="utf-8")
            replaced = migrate(paths, apply=True, replace=True)
            self.assertTrue(replaced["ok"])
            self.assertFalse(stale.exists())
            self.assertIn("foundation/code_templates/source/migrated_domains/obsolete/old.py", replaced["stale_generated_templates_removed"])


if __name__ == "__main__":
    unittest.main()
