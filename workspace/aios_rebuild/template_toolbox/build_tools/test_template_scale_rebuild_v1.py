"""Tests for candidate-catalog scale measurement and exact-span rebuilding."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from build_tools.migrate_aios_functions_to_templates_v1 import MigrationPaths, migrate
from build_tools.template_scale_rebuild_v1 import (
    AUTOMATIC_REBUILD_BUILTINS,
    BUILTIN_SURFACE_SCHEMA,
    REVIEW_ONLY_BUILTINS,
    REBUILD_RECEIPT_SCHEMA,
    SCALE_RECEIPT_SCHEMA,
    load_candidate_catalog,
    rebuild_reference,
    run_rebuild_cli,
    run_scale_test,
    write_rebuild_receipt,
)


class TemplateScaleRebuildTests(unittest.TestCase):
    def _make_catalog(self, root: Path) -> tuple[Path, Path]:
        foundation = root / "foundation"
        lib = foundation / "lib"
        lib.mkdir(parents=True)
        for name in ("rid_main.py", "auto_main.py", "uml_main.py"):
            (foundation / name).write_text("def main(argv):\n    return argv\n", encoding="utf-8")
        source = (
            "from typing import Any\n"
            "\n"
            "LIMIT = 3\n"
            "\n"
            "def known(value: int) -> int:\n"
            "    return value + LIMIT\n"
            "\n"
            "@staticmethod\n"
            "def decorated(value: int) -> int:\n"
            "    return known(value)\n"
        )
        (lib / "aios_adapter_demo.py").write_text(source, encoding="utf-8")
        paths = MigrationPaths(
            repo_root=root,
            foundation_root=foundation,
            output_root=foundation / "code_templates/source/migrated_domains",
            artifact_root=foundation / "artifacts/auto/code_templates/migration",
        )
        report = migrate(paths, apply=True)
        self.assertTrue(report["ok"], report)
        return (
            paths.artifact_root / "AIOS_FUNCTION_TEMPLATE_MIGRATION.json",
            paths.artifact_root / "function_index.json",
        )

    def test_exact_catalog_rebuild_and_explicit_input_fallback(self) -> None:
        with tempfile.TemporaryDirectory(prefix="viv-scale-rebuild-unit-") as tmp:
            root = Path(tmp)
            manifest, function_index = self._make_catalog(root)
            catalog = load_candidate_catalog(
                repo_root=root,
                manifest_path=manifest,
                function_index_path=function_index,
            )
            module = catalog.modules[0]

            canonical_output = root / "isolated" / "canonical.py"
            canonical = rebuild_reference(
                module.template_path,
                catalog,
                canonical_output,
                isolated=True,
                no_publish=True,
                allow_input_fallback=False,
                test_only_local_assembly=True,
            )
            self.assertTrue(canonical["ok"], canonical)
            self.assertEqual(canonical["state"], "PASS_CANONICAL_REBUILD")
            self.assertEqual(canonical["output_sha256"], canonical["input_sha256"])
            self.assertEqual(canonical["input_fallback_count"], 0)

            missing_input = root / "missing.py"
            missing_input.write_bytes(
                module.template_path.read_bytes()
                + b"\n\ndef only_in_reference(value: int) -> int:\n    return value * 2\n"
            )
            held_output = root / "isolated" / "held.py"
            held = rebuild_reference(
                missing_input,
                catalog,
                held_output,
                isolated=True,
                no_publish=True,
                allow_input_fallback=False,
                test_only_local_assembly=True,
            )
            self.assertFalse(held["ok"])
            self.assertEqual(held["state"], "HOLD_MISSING_FUNCTIONS")
            self.assertFalse(held_output.exists())
            self.assertFalse(held["synthesis_performed"])

            fallback_output = root / "isolated" / "fallback.py"
            fallback = rebuild_reference(
                missing_input,
                catalog,
                fallback_output,
                isolated=True,
                no_publish=True,
                allow_input_fallback=True,
                test_only_local_assembly=True,
            )
            self.assertTrue(fallback["ok"], fallback)
            self.assertEqual(fallback["state"], "PASS_WITH_INPUT_FALLBACK")
            self.assertEqual(fallback["input_fallback_count"], 1)
            self.assertFalse(fallback["synthesis_performed"])
            self.assertEqual(fallback_output.read_bytes(), missing_input.read_bytes())

    def test_missing_function_is_recreated_from_an_indexed_catalog_body(self) -> None:
        with tempfile.TemporaryDirectory(prefix="viv-body-rebuild-unit-") as tmp:
            root = Path(tmp)
            manifest, function_index = self._make_catalog(root)
            catalog = load_candidate_catalog(
                repo_root=root,
                manifest_path=manifest,
                function_index_path=function_index,
            )
            reference = root / "random.py"
            reference.write_text(
                "LIMIT = 3\n\n"
                "def renamed(value: int) -> int:\n"
                "    return value  + LIMIT\n",
                encoding="utf-8",
            )
            output = root / "isolated" / "recreated.py"
            report = rebuild_reference(
                reference,
                catalog,
                output,
                isolated=True,
                no_publish=True,
                allow_input_fallback=False,
                test_only_local_assembly=True,
            )
            self.assertTrue(report["ok"], report)
            self.assertEqual(report["state"], "PASS_WITH_CATALOG_BODY_RECREATION")
            self.assertEqual(report["catalog_body_recreated_count"], 1)
            self.assertEqual(report["input_fallback_count"], 0)
            self.assertEqual(report["missing_functions"], [])
            self.assertFalse(report["synthesis_performed"])
            self.assertNotEqual(report["output_sha256"], report["input_sha256"])
            self.assertTrue(report["test_only_local_assembly"])
            self.assertTrue(report["security_hold_expected"])
            namespace: dict[str, object] = {}
            exec(compile(output.read_text(encoding="utf-8"), str(output), "exec"), namespace, namespace)
            self.assertEqual(namespace["renamed"](2), 5)
            replacement = report["replacements"][0]
            self.assertEqual(replacement["mode"], "catalog_body_recreation")
            self.assertIsNotNone(replacement["catalog_function_id"])

    def test_review_only_builtin_holds_catalog_body_recreation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="viv-builtin-hold-unit-") as tmp:
            root = Path(tmp)
            foundation = root / "foundation"
            lib = foundation / "lib"
            lib.mkdir(parents=True)
            for name in ("rid_main.py", "auto_main.py", "uml_main.py"):
                (foundation / name).write_text("def main(argv):\n    return argv\n", encoding="utf-8")
            (lib / "review_demo.py").write_text(
                "def review(value: str) -> str:\n"
                "    return input(value)\n",
                encoding="utf-8",
            )
            paths = MigrationPaths(
                repo_root=root,
                foundation_root=foundation,
                output_root=foundation / "code_templates/source/migrated_domains",
                artifact_root=foundation / "artifacts/auto/code_templates/migration",
            )
            migrated = migrate(paths, apply=True)
            self.assertTrue(migrated["ok"], migrated)
            catalog = load_candidate_catalog(
                repo_root=root,
                manifest_path=paths.artifact_root / "AIOS_FUNCTION_TEMPLATE_MIGRATION.json",
                function_index_path=paths.artifact_root / "function_index.json",
            )
            reference = root / "random.py"
            reference.write_text(
                "def renamed(value: str) -> str:\n"
                "    return input(value)\n",
                encoding="utf-8",
            )
            report = rebuild_reference(
                reference,
                catalog,
                root / "isolated" / "held.py",
                isolated=True,
                no_publish=True,
                allow_input_fallback=False,
                test_only_local_assembly=True,
            )
            self.assertFalse(report["ok"])
            self.assertEqual(report["state"], "HOLD_MISSING_FUNCTIONS")
            self.assertTrue(report["body_recreation_holds"])
            self.assertIn("review_only", report["body_recreation_holds"][0]["reason"])

    def test_builtin_surface_manifest_matches_rebuild_contract(self) -> None:
        manifest = Path(__file__).resolve().parents[1] / "foundation" / "code_templates" / "python_builtins_v1.json"
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], BUILTIN_SURFACE_SCHEMA)
        listed = {name for values in payload["categories"].values() for name in values}
        self.assertEqual(listed, AUTOMATIC_REBUILD_BUILTINS | REVIEW_ONLY_BUILTINS)
        self.assertEqual(set(payload["automatic_reconstruction"]["allowed"]), AUTOMATIC_REBUILD_BUILTINS)
        self.assertEqual(set(payload["automatic_reconstruction"]["review_only"]), REVIEW_ONLY_BUILTINS)

    def test_scale_receipt_is_repeatable_and_isolated(self) -> None:
        with tempfile.TemporaryDirectory(prefix="viv-scale-test-unit-") as tmp:
            root = Path(tmp)
            manifest, function_index = self._make_catalog(root)
            receipt_dir = root / "receipts"
            report = run_scale_test(
                repo_root=root,
                manifest_path=manifest,
                function_index_path=function_index,
                case_sizes=(1, 2, 10),
                repeats=2,
                seed=7,
                receipt_dir=receipt_dir,
            )
            self.assertTrue(report["ok"], report)
            self.assertEqual(report["state"], "PASS_SCALE_AND_REBUILD")
            self.assertEqual(report["schema_version"], SCALE_RECEIPT_SCHEMA)
            self.assertTrue(report["deterministic_repeated_hashes"])
            self.assertTrue(report["production_boundary_unchanged"])
            self.assertFalse(report["generated_files_created"])
            self.assertFalse(report["active_pointer_changed"])
            self.assertEqual(report["catalog"]["active_registry_updated"], False)
            self.assertTrue(Path(report["receipt"]["path"]).is_file())
            receipt = json.loads(Path(report["receipt"]["path"]).read_text(encoding="utf-8"))
            self.assertEqual(receipt["schema_version"], SCALE_RECEIPT_SCHEMA)
            self.assertEqual(receipt["final_state"], "PASS_SCALE_AND_REBUILD")

    def test_rebuild_receipt_is_separate_from_generation_receipts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="viv-rebuild-receipt-unit-") as tmp:
            root = Path(tmp)
            manifest, function_index = self._make_catalog(root)
            catalog = load_candidate_catalog(
                repo_root=root,
                manifest_path=manifest,
                function_index_path=function_index,
            )
            module = catalog.modules[0]
            report = rebuild_reference(
                module.template_path,
                catalog,
                root / "isolated" / "output.py",
                isolated=True,
                no_publish=True,
                allow_input_fallback=False,
                test_only_local_assembly=True,
            )
            receipt = write_rebuild_receipt(
                report,
                receipt_dir=root / "receipts",
                input_path=module.template_path,
                catalog=catalog,
            )
            payload = json.loads(Path(receipt["path"]).read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], REBUILD_RECEIPT_SCHEMA)
            self.assertFalse(payload["synthesis_performed"])
            self.assertEqual(receipt["sha256"], __import__("hashlib").sha256(Path(receipt["path"]).read_bytes()).hexdigest())

    def test_normal_rebuild_cli_honors_rust_sandbox_denial(self) -> None:
        with tempfile.TemporaryDirectory(prefix="viv-rust-rebuild-hold-unit-") as tmp:
            root = Path(tmp)
            manifest, function_index = self._make_catalog(root)
            catalog = load_candidate_catalog(
                repo_root=root,
                manifest_path=manifest,
                function_index_path=function_index,
            )
            module = catalog.modules[0]
            output = root / "isolated" / "rust_denied.py"
            report = run_rebuild_cli(
                input_path=module.template_path,
                output_path=output,
                repo_root=root,
                manifest_path=manifest,
                function_index_path=function_index,
                receipt_dir=root / "receipts",
                isolated=True,
                no_publish=True,
            )
            self.assertFalse(report["ok"], report)
            self.assertEqual(report["state"], "HOLD_SECURITY")
            self.assertFalse(output.exists())
            self.assertFalse(report["rust_security"].get("ok"))
            self.assertFalse(report["template_insertion_performed"])


if __name__ == "__main__":
    unittest.main()
