"""Contract and transaction tests for the deterministic template toolbox."""
from __future__ import annotations

import ast
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from build_tools.template_builder_v1 import (
    LocalTestSecurityAdapter,
    SELECTION_REQUEST_SCHEMA,
    TemplateContractError,
    ToolboxPaths,
    _atomic_write,
    _json_bytes,
    _is_reparse_point,
    _sha256_bytes,
    _span,
    _source_index_receipt_payload,
    build_dry_run,
    adopt_template,
    index_templates,
    parse_template,
    plan_generation,
    publish_generation,
    rollback_generation,
    token_cost_report,
    verify_generation,
)


_ZERO_SUBMAIN_SOURCE = (
    "from typing import Any, Mapping\n"
    "\n"
    "# TEMPLATE VARIABLES BEGIN\n"
    "VARIABLES = {\n"
    "    \"message\": \"hello\",\n"
    "    \"count\": 1,\n"
    "}\n"
    "# TEMPLATE VARIABLES END\n"
    "\n"
    "def main(context: Mapping[str, Any], variables: Mapping[str, Any]) -> dict[str, Any]:\n"
    "    return {\"context\": dict(context), \"variables\": dict(variables)}\n"
)


_SUBMAIN_SOURCE = (
    "import typing\n"
    "from typing import Any, Mapping\n"
    "\n"
    "# TEMPLATE VARIABLES BEGIN\n"
    "VARIABLES = {\n"
    "    \"order\": \"original\",\n"
    "    \"value\": 1,\n"
    "}\n"
    "# TEMPLATE VARIABLES END\n"
    "\n"
    "@(\n"
    "    typing.no_type_check\n"
    ")\n"
    "def main(context: Mapping[str, Any], variables: Mapping[str, Any]) -> dict[str, Any]:\n"
    "    return {\"order\": variables[\"order\"], \"value\": variables[\"value\"]}\n"
    "\n"
    "@typing.no_type_check\n"
    "def sub_main_first(context: Mapping[str, Any], variables: Mapping[str, Any]) -> Mapping[str, Any]:\n"
    "    updated = dict(variables)\n"
    "    updated[\"order\"] = updated[\"order\"] + \":first\"\n"
    "    return updated\n"
    "\n"
    "@typing.no_type_check\n"
    "def sub_main_second(context: Mapping[str, Any], variables: Mapping[str, Any]) -> Mapping[str, Any]:\n"
    "    updated = dict(variables)\n"
    "    updated[\"order\"] = updated[\"order\"] + \":second\"\n"
    "    return updated\n"
)


_DUPLICATE_MAIN_SOURCE = _ZERO_SUBMAIN_SOURCE + (
    "\n"
    "def main(context: Mapping[str, Any], variables: Mapping[str, Any]) -> dict[str, Any]:\n"
    "    return {}\n"
)


class _DenySecurityAdapter(LocalTestSecurityAdapter):
    def probe(self, plan, paths):  # type: ignore[no-untyped-def]
        del plan, paths
        return {"ok": False, "state": "HOLD_SECURITY", "reason": "test_denial"}


class _FailManifestSecurityAdapter(LocalTestSecurityAdapter):
    def write_json(self, path, content):  # type: ignore[no-untyped-def]
        if path.name == "generation_manifest.json":
            return {"ok": False, "error": "test_manifest_write_failure"}
        return super().write_json(path, content)


class _TamperPointerTempSecurityAdapter(LocalTestSecurityAdapter):
    def write_json(self, path, content):  # type: ignore[no-untyped-def]
        result = super().write_json(path, content)
        if result.get("ok") and path.name == "template_current.json.tmp":
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["manifest_path"] = str(path.parent / "not_the_generation" / "generation_manifest.json")
            result = _atomic_write(path, _json_bytes(payload))
        return result


class TemplateBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="viv-template-test-")
        root = Path(self._tmp.name)
        self.source_root = root / "source"
        self.generation_root = root / "generations"
        self.receipt_root = root / "receipts"
        self.source_root.mkdir(parents=True)
        self.registry_path = root / "registry.json"
        self.pointer = root / "template_current.json"
        self.paths = ToolboxPaths(
            repo_root=root,
            source_root=self.source_root,
            registry_path=self.registry_path,
            toolbox_manifest=root / "TOOLBOX.json",
            generation_root=self.generation_root,
            current_pointer=self.pointer,
            receipt_root=self.receipt_root,
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _registry(self, *rows: dict) -> None:
        self.registry_path.write_text(
            json.dumps(
                {"schema_version": "viv_code_template_registry_v1", "toolbox_id": "test", "templates": list(rows)},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def _write(self, name: str, source: str) -> None:
        path = self.source_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8", newline="")

    def _zero_registry(self) -> None:
        self._write("zero.py", _ZERO_SUBMAIN_SOURCE)
        self._registry(
            {"template_id": "fixture.zero", "source": "zero.py", "targets": ["rid", "auto", "uml"], "submain_order": []}
        )

    def _submain_registry(self, order: list[str] | None = None) -> None:
        self._write("ordered.py", _SUBMAIN_SOURCE)
        self._registry(
            {"template_id": "fixture.ordered", "source": "ordered.py", "targets": ["rid"],
             "submain_order": order or ["sub_main_first", "sub_main_second"]}
        )

    def _write_index_approval(self) -> None:
        indexed = index_templates(self.paths, write=False)
        index_bytes = _json_bytes(indexed["index"])
        self.assertTrue(_atomic_write(self.receipt_root / "source_function_index.json", index_bytes)["ok"])
        receipt = _source_index_receipt_payload(self.paths, indexed["index"], index_bytes)
        self.assertTrue(
            _atomic_write(
                self.receipt_root / "source_function_index.receipt.json",
                _json_bytes(receipt),
            )["ok"]
        )

    def test_zero_submain_main_receives_declared_variables_unchanged(self) -> None:
        self._zero_registry()
        result = publish_generation(self.paths, security=LocalTestSecurityAdapter())
        self.assertTrue(result["ok"], result)

        foundation = Path(__file__).resolve().parents[1] / "foundation"
        if str(foundation) not in sys.path:
            sys.path.insert(0, str(foundation))
        from lib import code_template_runtime as runtime

        runtime_paths = runtime._RuntimePaths(
            root=self.paths.repo_root,
            source_root=self.paths.source_root,
            generation_root=self.paths.generation_root,
            current_pointer=self.paths.current_pointer,
            receipt_root=self.paths.receipt_root,
        )
        snapshot = runtime._verify_snapshot(runtime_paths)
        loaded = runtime._load_verified_module(snapshot, "fixture.zero", "rid")
        self.assertFalse(any(name.startswith("sub_main_") for name in dir(loaded)))
        output = runtime._execute_with_snapshot(snapshot, "fixture.zero", "rid", {"turn": 1})
        self.assertEqual(output["variables"], {"message": "hello", "count": 1})
        with patch.object(runtime._RuntimePaths, "default", return_value=runtime_paths), patch.object(
            runtime,
            "_security_status",
            return_value={"ok": True, "rust_available": True, "integrity": {"ok": True}},
        ):
            status = runtime.template_status("rid")
            discovered = runtime.discover_templates("rid")
            loaded = runtime.load_template("fixture.zero", "rid")
        self.assertTrue(status["ok"], status)
        self.assertEqual(status["active_generation"], result["generation_id"])
        self.assertEqual(status["templates"][0]["variables"], ["count", "message"])
        self.assertFalse(status["source_drift"]["detected"])
        self.assertEqual(discovered[0]["template_id"], "fixture.zero")
        self.assertTrue(callable(loaded.main))
        overridden = runtime._execute_with_snapshot(
            snapshot,
            "fixture.zero",
            "rid",
            {"turn": 1},
            {"message": "from_tool_call"},
        )
        self.assertEqual(overridden["variables"], {"message": "from_tool_call", "count": 1})
        with self.assertRaises(runtime.TemplateRuntimeError):
            runtime._execute_with_snapshot(
                snapshot,
                "fixture.zero",
                "rid",
                {},
                {"not_declared": True},
            )

    def test_ordered_submains_run_before_main(self) -> None:
        self._submain_registry()
        published = publish_generation(self.paths, security=LocalTestSecurityAdapter())
        self.assertTrue(published["ok"], published)
        foundation = Path(__file__).resolve().parents[1] / "foundation"
        if str(foundation) not in sys.path:
            sys.path.insert(0, str(foundation))
        from lib import code_template_runtime as runtime

        runtime_paths = runtime._RuntimePaths(
            root=self.paths.repo_root,
            source_root=self.paths.source_root,
            generation_root=self.paths.generation_root,
            current_pointer=self.paths.current_pointer,
            receipt_root=self.paths.receipt_root,
        )
        snapshot = runtime._verify_snapshot(runtime_paths)
        result = runtime._execute_with_snapshot(snapshot, "fixture.ordered", "rid", {})
        self.assertEqual(result["order"], "original:first:second")

    def test_runtime_rejects_submain_variable_key_changes(self) -> None:
        changed = _SUBMAIN_SOURCE.replace(
            '    updated["order"] = updated["order"] + ":first"\n'
            "    return updated",
            '    updated["order"] = updated["order"] + ":first"\n'
            '    updated["unexpected"] = True\n'
            "    return updated",
            1,
        )
        self._write("changed.py", changed)
        self._registry(
            {
                "template_id": "fixture.changed",
                "source": "changed.py",
                "targets": ["rid"],
                "submain_order": ["sub_main_first", "sub_main_second"],
            }
        )
        published = publish_generation(self.paths, security=LocalTestSecurityAdapter())
        self.assertTrue(published["ok"], published)
        foundation = Path(__file__).resolve().parents[1] / "foundation"
        if str(foundation) not in sys.path:
            sys.path.insert(0, str(foundation))
        from lib import code_template_runtime as runtime

        runtime_paths = runtime._RuntimePaths(
            root=self.paths.repo_root,
            source_root=self.paths.source_root,
            generation_root=self.paths.generation_root,
            current_pointer=self.paths.current_pointer,
            receipt_root=self.paths.receipt_root,
        )
        snapshot = runtime._verify_snapshot(runtime_paths)
        with self.assertRaises(runtime.TemplateRuntimeError):
            runtime._execute_with_snapshot(snapshot, "fixture.changed", "rid", {})

    def test_selection_request_copies_only_approved_templates_and_reorders_submains(self) -> None:
        self._submain_registry()
        request = {
            "schema_version": SELECTION_REQUEST_SCHEMA,
            "templates": [
                {
                    "template_id": "fixture.ordered",
                    "target_pillars": ["rid"],
                    "submain_order": ["sub_main_second", "sub_main_first"],
                }
            ],
        }
        first = plan_generation(self.paths, request)
        second = plan_generation(self.paths, request)
        self.assertEqual(first.generation_id, second.generation_id)
        self.assertEqual(first.selection_request, request)
        self.assertIsNotNone(first.selection_request_sha256)
        self.assertEqual(first.modules[0].template.submain_order, ("sub_main_second", "sub_main_first"))
        self.assertEqual(first.modules[0].template.targets, ("rid",))
        published = publish_generation(
            self.paths,
            security=LocalTestSecurityAdapter(),
            selection_request=request,
        )
        self.assertTrue(published["ok"], published)
        manifest = json.loads(
            (self.generation_root / published["generation_id"] / "generation_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(manifest["selection_request"], request)
        self.assertEqual(manifest["selection_request_sha256"], first.selection_request_sha256)

        foundation = Path(__file__).resolve().parents[1] / "foundation"
        if str(foundation) not in sys.path:
            sys.path.insert(0, str(foundation))
        from lib import code_template_runtime as runtime

        runtime_paths = runtime._RuntimePaths(
            root=self.paths.repo_root,
            source_root=self.paths.source_root,
            generation_root=self.paths.generation_root,
            current_pointer=self.paths.current_pointer,
            receipt_root=self.paths.receipt_root,
        )
        snapshot = runtime._verify_snapshot(runtime_paths)
        result = runtime._execute_with_snapshot(snapshot, "fixture.ordered", "rid", {})
        self.assertEqual(result["order"], "original:second:first")

    def test_selection_request_rejects_unknown_targets_duplicates_and_partial_submain_sets(self) -> None:
        self._submain_registry()
        cases = {
            "unknown": {
                "schema_version": SELECTION_REQUEST_SCHEMA,
                "templates": [{"template_id": "fixture.missing"}],
            },
            "target": {
                "schema_version": SELECTION_REQUEST_SCHEMA,
                "templates": [{"template_id": "fixture.ordered", "target_pillars": ["auto"]}],
            },
            "duplicate": {
                "schema_version": SELECTION_REQUEST_SCHEMA,
                "templates": [
                    {"template_id": "fixture.ordered"},
                    {"template_id": "fixture.ordered"},
                ],
            },
            "partial_submains": {
                "schema_version": SELECTION_REQUEST_SCHEMA,
                "templates": [
                    {
                        "template_id": "fixture.ordered",
                        "submain_order": ["sub_main_first"],
                    }
                ],
            },
        }
        for name, request in cases.items():
            with self.subTest(name=name), self.assertRaises(TemplateContractError):
                plan_generation(self.paths, request)

    def test_decorators_are_indexed_and_section_bytes_are_exact(self) -> None:
        self._submain_registry()
        row = {"template_id": "fixture.ordered", "source": "ordered.py", "targets": ["rid"],
               "submain_order": ["sub_main_first", "sub_main_second"]}
        parsed = parse_template(row, self.paths)
        tree = ast.parse(_SUBMAIN_SOURCE)
        main_node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
        expected_start = next(index for index, line in enumerate(_SUBMAIN_SOURCE.splitlines(), 1) if line.startswith("@("))
        self.assertEqual(parsed.main.source_start_line, expected_start)
        self.assertTrue(parsed.main.decorated)
        plan = plan_generation(self.paths)
        module = plan.modules[0]
        source_lines = list(module.template.lines)
        generated_lines = module.generated_text.splitlines(keepends=True)
        for section in module.sections:
            source_span = _span(source_lines, section["source_start_line"], section["source_end_line"])
            generated_span = _span(generated_lines, section["generated_start_line"], section["generated_end_line"])
            self.assertEqual(source_span, generated_span, section)
            self.assertEqual(section["source_sha256"], _sha256_bytes(source_span.encode("utf-8")))
            self.assertEqual(section["generated_sha256"], _sha256_bytes(generated_span.encode("utf-8")))
        indexed = index_templates(self.paths, write=False)
        self.assertTrue(indexed["ok"])
        self.assertEqual(len(indexed["index"]["entries"]), 5)

    def test_source_without_final_newline_stays_byte_exact(self) -> None:
        self._write("no_newline.py", _ZERO_SUBMAIN_SOURCE.rstrip("\n"))
        self._registry(
            {"template_id": "fixture.no_newline", "source": "no_newline.py", "targets": ["rid"], "submain_order": []}
        )
        plan = plan_generation(self.paths)
        self.assertFalse(plan.modules[0].generated_text.endswith("\n"))
        source_bytes = (self.source_root / "no_newline.py").read_bytes()
        self.assertEqual(plan.modules[0].generated_text.encode("utf-8").split(b"\n\n")[-1], source_bytes.split(b"\n\n")[-1])

    def test_repeated_plan_is_deterministic(self) -> None:
        self._zero_registry()
        first = plan_generation(self.paths)
        second = plan_generation(self.paths)
        self.assertEqual(first.generation_id, second.generation_id)
        self.assertEqual(first.input_sha256, second.input_sha256)
        self.assertEqual(first.modules[0].generated_sha256, second.modules[0].generated_sha256)
        self.assertEqual(first.modules[0].generated_text, second.modules[0].generated_text)
        self.assertEqual(json.dumps(first.index, sort_keys=True), json.dumps(second.index, sort_keys=True))
        self.assertEqual(json.dumps(first.manifest, sort_keys=True), json.dumps(second.manifest, sort_keys=True))

    def test_source_index_rebuild_is_deterministic(self) -> None:
        self._zero_registry()
        first = index_templates(self.paths, write=False)
        second = index_templates(self.paths, write=False)
        self.assertEqual(first["index_sha256"], second["index_sha256"])
        self.assertEqual(first["index"], second["index"])

    def test_generated_template_reindexes_and_rebuilds_idempotently(self) -> None:
        self._zero_registry()
        published = publish_generation(self.paths, security=LocalTestSecurityAdapter())
        self.assertTrue(published["ok"], published)
        generated = self.generation_root / published["generation_id"] / "fixture_zero.py"
        self._write("roundtrip.py", generated.read_text(encoding="utf-8"))
        self._registry(
            {
                "template_id": "fixture.roundtrip",
                "source": "roundtrip.py",
                "targets": ["rid"],
                "submain_order": [],
            }
        )
        self._write_index_approval()
        first = plan_generation(self.paths)
        second = plan_generation(self.paths)
        self.assertEqual(first.generation_id, second.generation_id)
        self.assertEqual(first.modules[0].generated_text, generated.read_text(encoding="utf-8"))
        self.assertEqual(first.modules[0].generated_sha256, second.modules[0].generated_sha256)

    def test_repeated_publish_does_not_rewrite_immutable_active_generation(self) -> None:
        self._zero_registry()
        first = publish_generation(self.paths, security=LocalTestSecurityAdapter())
        self.assertTrue(first["ok"], first)
        generation_dir = self.generation_root / first["generation_id"]
        before = {
            path.name: path.read_bytes()
            for path in sorted(generation_dir.iterdir())
            if path.is_file()
        }
        pointer_before = self.pointer.read_bytes()
        second = publish_generation(self.paths, security=LocalTestSecurityAdapter())
        self.assertTrue(second["ok"], second)
        self.assertTrue(second["idempotent"])
        self.assertFalse(second["writes_performed"])
        self.assertEqual(pointer_before, self.pointer.read_bytes())
        self.assertEqual(
            before,
            {path.name: path.read_bytes() for path in sorted(generation_dir.iterdir()) if path.is_file()},
        )

    def test_generation_only_mode_keeps_pointer_untouched(self) -> None:
        self._zero_registry()
        report = publish_generation(
            self.paths,
            security=LocalTestSecurityAdapter(),
            publish_pointer=False,
        )
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["state"], "PASS_GENERATION_ONLY")
        self.assertFalse(report["active_pointer_changed"])
        self.assertFalse(self.pointer.exists())
        self.assertTrue((self.generation_root / report["generation_id"] / "fixture_zero.py").is_file())
        verification = verify_generation(self.paths, report["generation_id"])
        self.assertTrue(verification["ok"], verification)
        second = publish_generation(
            self.paths,
            security=LocalTestSecurityAdapter(),
            publish_pointer=False,
        )
        self.assertFalse(second["ok"])
        self.assertEqual(second["reason"], "immutable_generation_exists_not_active")

    def test_failed_staging_leaves_active_pointer_unchanged(self) -> None:
        self._zero_registry()
        first = publish_generation(self.paths, security=LocalTestSecurityAdapter())
        self.assertTrue(first["ok"], first)
        pointer_before = self.pointer.read_bytes()
        blocked = publish_generation(
            self.paths,
            security=_FailManifestSecurityAdapter(),
            selection_request={
                "schema_version": SELECTION_REQUEST_SCHEMA,
                "templates": [{"template_id": "fixture.zero", "target_pillars": ["rid"]}],
            },
        )
        self.assertFalse(blocked["ok"])
        self.assertEqual(blocked["reason"], "manifest_write_failed")
        self.assertEqual(pointer_before, self.pointer.read_bytes())
        self.assertEqual(
            [path.name for path in self.generation_root.iterdir() if path.is_dir()],
            [first["generation_id"]],
        )

    def test_token_cost_report_counts_code_and_structured_selection(self) -> None:
        self._zero_registry()
        report = token_cost_report(self.paths)
        self.assertTrue(report["ok"], report)
        self.assertGreater(report["ordinary_code"]["bytes"], 0)
        self.assertGreater(report["tool_request"]["bytes"], 0)
        self.assertGreater(report["one_time_template_context"]["estimated_tokens"], 0)
        self.assertIsNotNone(report["steady_state_break_even_builds"])
        self.assertEqual(len(report["amortized_examples"]), 3)
        self.assertEqual(report["code_bytes_sent_to_model"], 0)

    def test_legacy_raw_coder_surface_is_denied(self) -> None:
        foundation = Path(__file__).resolve().parents[1] / "foundation"
        if str(foundation) not in sys.path:
            sys.path.insert(0, str(foundation))
        from lib.aios_coder import run_sandbox_tool, write_sandbox_tool

        raw_write = write_sandbox_tool(tool="fixture.echo", source="print('raw')")
        self.assertFalse(raw_write["ok"])
        self.assertEqual(raw_write["reason"], "raw_python_source_forbidden")
        implicit_write = write_sandbox_tool()
        self.assertFalse(implicit_write["ok"])
        self.assertEqual(implicit_write["reason"], "template_id_required")
        raw_run = run_sandbox_tool(path=str(self.source_root / "raw.txt"))
        self.assertFalse(raw_run["ok"])
        self.assertEqual(raw_run["reason"], "raw_python_source_execution_forbidden")
        implicit_run = run_sandbox_tool()
        self.assertFalse(implicit_run["ok"])
        self.assertEqual(implicit_run["reason"], "template_id_required")
        for relative in (
            "foundation/lib/aios_coder.py",
            "foundation/lib/aios_builder.py",
            "foundation/lib/aios_self.py",
            "foundation/lib/prt_capability_expand.py",
        ):
            tree = ast.parse((Path(__file__).resolve().parents[1] / relative).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                function_name = node.func.id if isinstance(node.func, ast.Name) else ""
                if function_name == "write_sandbox_tool":
                    self.assertFalse(any(keyword.arg == "source" for keyword in node.keywords))
                if function_name == "run_sandbox_tool":
                    self.assertFalse(any(keyword.arg == "path" for keyword in node.keywords))

    def test_contract_rejects_missing_main_helpers_side_effects_and_bad_paths(self) -> None:
        cases = {
            "missing": _ZERO_SUBMAIN_SOURCE.replace("def main", "def helper", 1),
            "duplicate_main": _DUPLICATE_MAIN_SOURCE,
            "helper": _ZERO_SUBMAIN_SOURCE.replace(
                "\ndef main", "\ndef helper(context, variables):\n    return variables\n\ndef main", 1
            ),
            "effect": _ZERO_SUBMAIN_SOURCE.replace("# TEMPLATE VARIABLES END", "# TEMPLATE VARIABLES END\n\nprint('side effect')", 1),
            "assignment": _ZERO_SUBMAIN_SOURCE.replace("# TEMPLATE VARIABLES END", "# TEMPLATE VARIABLES END\n\nOTHER = 1", 1),
            "unsafe_import": _ZERO_SUBMAIN_SOURCE.replace("from typing import Any, Mapping", "import os", 1),
            "unsafe_decorator": _ZERO_SUBMAIN_SOURCE.replace("def main", "@evil\ndef main", 1),
            "invalid_variables": _ZERO_SUBMAIN_SOURCE.replace("VARIABLES = {", "VARIABLES = [", 1).replace(
                "    \"count\": 1,\n}", "    \"count\": 1,\n]", 1
            ),
        }
        for name, source in cases.items():
            with self.subTest(name=name):
                self._write(f"{name}.py", source)
                self._registry(
                    {"template_id": f"fixture.{name}", "source": f"{name}.py", "targets": ["rid"], "submain_order": []}
                )
                with self.assertRaises(TemplateContractError):
                    plan_generation(self.paths)
        self._write("valid.py", _ZERO_SUBMAIN_SOURCE)
        self._registry(
            {"template_id": "fixture.dup", "source": "valid.py", "targets": ["rid"], "submain_order": []},
            {"template_id": "fixture.dup", "source": "valid.py", "targets": ["rid"], "submain_order": []},
        )
        with self.assertRaises(TemplateContractError):
            plan_generation(self.paths)

    def test_contract_rejects_unsafe_nested_imports_and_duplicate_submains(self) -> None:
        nested_import = _ZERO_SUBMAIN_SOURCE.replace(
            "def main(context: Mapping[str, Any], variables: Mapping[str, Any]) -> dict[str, Any]:\n",
            "def main(context: Mapping[str, Any], variables: Mapping[str, Any]) -> dict[str, Any]:\n"
            "    import typing\n",
            1,
        )
        self._write("nested_import.py", nested_import)
        self._registry(
            {
                "template_id": "fixture.nested_import",
                "source": "nested_import.py",
                "targets": ["rid"],
                "submain_order": [],
            }
        )
        with self.assertRaises(TemplateContractError):
            plan_generation(self.paths)

        duplicate_submain = _SUBMAIN_SOURCE + (
            "\n\n@typing.no_type_check\n"
            "def sub_main_first(context: Mapping[str, Any], variables: Mapping[str, Any]) -> Mapping[str, Any]:\n"
            "    return variables\n"
        )
        self._write("duplicate_submain.py", duplicate_submain)
        self._registry(
            {
                "template_id": "fixture.duplicate_submain",
                "source": "duplicate_submain.py",
                "targets": ["rid"],
                "submain_order": ["sub_main_first", "sub_main_second"],
            }
        )
        with self.assertRaises(TemplateContractError):
            plan_generation(self.paths)

    def test_contract_rejects_source_ordering_violations(self) -> None:
        imports_after_variables = _ZERO_SUBMAIN_SOURCE + "\nimport typing\n"
        self._write("imports_after_variables.py", imports_after_variables)
        self._registry(
            {
                "template_id": "fixture.imports_after_variables",
                "source": "imports_after_variables.py",
                "targets": ["rid"],
                "submain_order": [],
            }
        )
        with self.assertRaises(TemplateContractError):
            plan_generation(self.paths)

        variables_after_main = (
            "from typing import Any, Mapping\n\n"
            "def main(context: Mapping[str, Any], variables: Mapping[str, Any]) -> dict[str, Any]:\n"
            "    return dict(variables)\n\n"
            "# TEMPLATE VARIABLES BEGIN\n"
            "VARIABLES = {}\n"
            "# TEMPLATE VARIABLES END\n"
        )
        self._write("variables_after_main.py", variables_after_main)
        self._registry(
            {
                "template_id": "fixture.variables_after_main",
                "source": "variables_after_main.py",
                "targets": ["rid"],
                "submain_order": [],
            }
        )
        with self.assertRaises(TemplateContractError):
            plan_generation(self.paths)

        submain_before_main = (
            "from typing import Any, Mapping\n\n"
            "# TEMPLATE VARIABLES BEGIN\n"
            "VARIABLES = {}\n"
            "# TEMPLATE VARIABLES END\n\n"
            "def sub_main_first(context: Mapping[str, Any], variables: Mapping[str, Any]) -> Mapping[str, Any]:\n"
            "    return dict(variables)\n\n"
            "def main(context: Mapping[str, Any], variables: Mapping[str, Any]) -> dict[str, Any]:\n"
            "    return dict(variables)\n"
        )
        self._write("submain_before_main.py", submain_before_main)
        self._registry(
            {
                "template_id": "fixture.submain_before_main",
                "source": "submain_before_main.py",
                "targets": ["rid"],
                "submain_order": ["sub_main_first"],
            }
        )
        with self.assertRaises(TemplateContractError):
            plan_generation(self.paths)

    def test_registry_rejects_path_traversal_and_generated_collisions(self) -> None:
        self._write("safe.py", _ZERO_SUBMAIN_SOURCE)
        self._registry(
            {"template_id": "fixture.traversal", "source": "../safe.py", "targets": ["rid"], "submain_order": []}
        )
        with self.assertRaises(TemplateContractError):
            plan_generation(self.paths)

        self._write("one.py", _ZERO_SUBMAIN_SOURCE)
        self._write("two.py", _ZERO_SUBMAIN_SOURCE)
        self._registry(
            {"template_id": "fixture.same", "source": "one.py", "targets": ["rid"], "submain_order": []},
            {"template_id": "fixture_same", "source": "two.py", "targets": ["rid"], "submain_order": []},
        )
        with self.assertRaises(TemplateContractError):
            plan_generation(self.paths)

    def test_reparse_and_mixed_generation_pointers_are_rejected(self) -> None:
        self._zero_registry()
        published = publish_generation(self.paths, security=LocalTestSecurityAdapter())
        self.assertTrue(published["ok"], published)
        mixed = dict(published["pointer"])
        mixed["manifest_path"] = str(self.generation_root / "gen_0000000000000000" / "generation_manifest.json")
        self.pointer.write_text(json.dumps(mixed), encoding="utf-8")
        mixed_report = verify_generation(self.paths)
        self.assertFalse(mixed_report["ok"])
        self.assertIn("pointer_manifest_path_mismatch", mixed_report["reason"])
        self.pointer.write_text(json.dumps(published["pointer"]), encoding="utf-8")

        real_dir = self.source_root / "real_source"
        link_dir = self.source_root / "link_source"
        real_dir.mkdir()
        real = real_dir / "template.py"
        link = link_dir / "template.py"
        real.write_text(_ZERO_SUBMAIN_SOURCE, encoding="utf-8")
        try:
            os.symlink(real_dir, link_dir, target_is_directory=True)
        except (OSError, NotImplementedError):
            if os.name != "nt":
                self.fail("controlled reparse-point fixture unavailable outside Windows")
            result = subprocess.run(
                ["cmd.exe", "/c", "mklink", "/J", str(link_dir), str(real_dir)],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                self.fail(f"controlled Windows junction fixture unavailable: {result.stdout} {result.stderr}")
        self.assertTrue(_is_reparse_point(link_dir))
        self._registry(
            {"template_id": "fixture.link", "source": "link_source/template.py", "targets": ["rid"], "submain_order": []}
        )
        try:
            with self.assertRaises(TemplateContractError):
                plan_generation(self.paths)
        finally:
            os.rmdir(link_dir)

    def test_dry_run_security_denial_writes_nothing(self) -> None:
        self._zero_registry()
        report = build_dry_run(self.paths, security=_DenySecurityAdapter())
        self.assertTrue(report["ok"])
        self.assertEqual(report["state"], "HOLD_SECURITY")
        self.assertFalse(report["writes_performed"])
        self.assertTrue(report["receipt"]["written"])
        self.assertFalse(self.pointer.exists())
        self.assertFalse(self.generation_root.exists())
        denied_publish = publish_generation(self.paths, security=_DenySecurityAdapter())
        self.assertFalse(denied_publish["ok"])
        self.assertFalse(self.pointer.exists())

    def test_pointer_temp_is_validated_before_atomic_replace(self) -> None:
        self._zero_registry()
        report = publish_generation(self.paths, security=_TamperPointerTempSecurityAdapter())
        self.assertFalse(report["ok"])
        self.assertIn("pointer_temp_validation_failed", report["reason"])
        self.assertFalse(self.pointer.exists())
        self.assertFalse((self.pointer.parent / "template_current.json.tmp").exists())

    def test_desync_receipt_tamper_and_rollback(self) -> None:
        self._submain_registry()
        first = publish_generation(self.paths, security=LocalTestSecurityAdapter())
        self.assertTrue(first["ok"], first)
        first_generation = first["generation_id"]

        self._registry(
            {"template_id": "fixture.ordered", "source": "ordered.py", "targets": ["rid"],
             "submain_order": ["sub_main_second", "sub_main_first"]}
        )
        second = publish_generation(self.paths, security=LocalTestSecurityAdapter())
        self.assertTrue(second["ok"], second)
        self.assertNotEqual(first_generation, second["generation_id"])
        self.assertEqual(second["pointer"]["generation_id"], second["generation_id"])
        self.assertEqual(second["pointer_sha256"], _sha256_bytes(self.pointer.read_bytes()))

        rollback = rollback_generation(self.paths, first_generation, security=LocalTestSecurityAdapter())
        self.assertTrue(rollback["ok"], rollback)
        self.assertEqual(rollback["pointer"]["generation_id"], first_generation)
        self.assertEqual(verify_generation(self.paths)["generation_id"], first_generation)

        manifest_path = self.generation_root / first_generation / "generation_manifest.json"
        receipt_path = self.generation_root / first_generation / "generation_receipt.json"
        original_manifest = manifest_path.read_bytes()
        manifest_path.write_bytes(original_manifest + b" ")
        self.assertFalse(verify_generation(self.paths)["ok"])
        manifest_path.write_bytes(original_manifest)
        receipt_path.write_bytes(receipt_path.read_bytes() + b" ")
        self.assertFalse(verify_generation(self.paths)["ok"])

    def test_source_drift_is_rejected_even_when_generated_bytes_are_unchanged(self) -> None:
        self._zero_registry()
        published = publish_generation(self.paths, security=LocalTestSecurityAdapter())
        self.assertTrue(published["ok"], published)
        source_path = self.source_root / "zero.py"
        source_path.write_text(source_path.read_text(encoding="utf-8") + "\n# manual drift\n", encoding="utf-8")
        report = verify_generation(self.paths)
        self.assertFalse(report["ok"])
        self.assertIn("source_hash_drift", report["reason"])
        foundation = Path(__file__).resolve().parents[1] / "foundation"
        if str(foundation) not in sys.path:
            sys.path.insert(0, str(foundation))
        from lib import code_template_runtime as runtime

        runtime_paths = runtime._RuntimePaths(
            root=self.paths.repo_root,
            source_root=self.paths.source_root,
            generation_root=self.paths.generation_root,
            current_pointer=self.paths.current_pointer,
            receipt_root=self.paths.receipt_root,
        )
        with patch.object(runtime._RuntimePaths, "default", return_value=runtime_paths), patch.object(
            runtime,
            "_security_status",
            return_value={"ok": True, "rust_available": True, "integrity": {"ok": True}},
        ):
            status = runtime.template_status("rid")
        self.assertFalse(status["ok"])
        self.assertEqual(status["state"], "HOLD")
        self.assertTrue(status["source_drift"]["detected"])
        blocked = publish_generation(self.paths, security=LocalTestSecurityAdapter())
        self.assertFalse(blocked["ok"])
        self.assertIn("source_drift_after_index", blocked["reason"])
        self._write_index_approval()
        approved = publish_generation(self.paths, security=LocalTestSecurityAdapter())
        self.assertTrue(approved["ok"], approved)

    def test_source_index_and_receipt_tampering_blocks_publication(self) -> None:
        self._zero_registry()
        self._write_index_approval()
        index_path = self.receipt_root / "source_function_index.json"
        receipt_path = self.receipt_root / "source_function_index.receipt.json"
        original_index = index_path.read_bytes()
        index_path.write_bytes(original_index + b" ")
        with self.assertRaises(TemplateContractError) as index_error:
            plan_generation(self.paths)
        self.assertIn("source_index_receipt_hash_mismatch", str(index_error.exception))
        index_path.write_bytes(original_index)

        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["index_sha256"] = "0" * 64
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        with self.assertRaises(TemplateContractError) as receipt_error:
            plan_generation(self.paths)
        self.assertIn("source_index_receipt_hash_mismatch", str(receipt_error.exception))

    def test_toolbox_paths_reject_source_generation_and_protected_main_overlap(self) -> None:
        self._zero_registry()
        with self.assertRaises(TemplateContractError):
            plan_generation(replace(self.paths, generation_root=self.source_root / "generated"))
        with self.assertRaises(TemplateContractError):
            plan_generation(replace(self.paths, source_root=self.generation_root / "source"))
        with self.assertRaises(TemplateContractError):
            plan_generation(replace(self.paths, current_pointer=self.generation_root / "pointer.json"))
        with self.assertRaises(TemplateContractError):
            plan_generation(replace(self.paths, generation_root=self.paths.repo_root / "foundation" / "rid_main.py"))

    def test_publication_does_not_modify_protected_main_files(self) -> None:
        self._zero_registry()
        protected = {}
        for name in ("rid_main.py", "auto_main.py", "uml_main.py"):
            path = self.paths.repo_root / "foundation" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((f"# protected {name}\n").encode("utf-8"))
            protected[path] = path.read_bytes()
        published = publish_generation(self.paths, security=LocalTestSecurityAdapter())
        self.assertTrue(published["ok"], published)
        for path, before in protected.items():
            self.assertEqual(path.read_bytes(), before)

    def test_pointer_temp_name_is_same_directory_contract_name(self) -> None:
        from build_tools.template_builder_v1 import _pointer_temp_path

        self.assertEqual(_pointer_temp_path(self.paths).name, "template_current.json.tmp")

    def test_lineage_tail_is_bounded_and_parented(self) -> None:
        self._submain_registry()
        generations: list[str] = []
        for index in range(7):
            order = ["sub_main_first", "sub_main_second"] if index % 2 == 0 else ["sub_main_second", "sub_main_first"]
            self._registry(
                {"template_id": "fixture.ordered", "source": "ordered.py", "targets": ["rid"], "submain_order": order}
            )
            report = publish_generation(self.paths, security=LocalTestSecurityAdapter())
            self.assertTrue(report["ok"], report)
            generations.append(report["generation_id"])
        manifest = json.loads(
            (self.generation_root / generations[-1] / "generation_manifest.json").read_text(encoding="utf-8")
        )
        self.assertLessEqual(len(manifest["lineage_tail"]), 5)
        self.assertEqual(manifest["lineage_tail"][-1], generations[-2])
        self.assertTrue(
            all((self.receipt_root / "receipts" / f"{generation}.json").is_file() for generation in generations)
        )

    def test_adopt_creates_new_source_layer_and_provenance_receipt(self) -> None:
        self._zero_registry()
        published = publish_generation(self.paths, security=LocalTestSecurityAdapter())
        self.assertTrue(published["ok"], published)
        blocked = adopt_template(
            self.paths,
            published["generation_id"],
            "fixture.zero",
            security=LocalTestSecurityAdapter(),
        )
        self.assertFalse(blocked["ok"])
        self.assertEqual(blocked["state"], "HOLD_HUMAN_APPROVAL")
        self.assertFalse(blocked["template_insertion_performed"])
        adopted = adopt_template(
            self.paths,
            published["generation_id"],
            "fixture.zero",
            security=LocalTestSecurityAdapter(),
            human_approval=True,
        )
        self.assertTrue(adopted["ok"], adopted)
        adopted_path = Path(adopted["source_path"])
        self.assertTrue(adopted_path.is_file())
        generated_path = self.generation_root / published["generation_id"] / "fixture_zero.py"
        self.assertEqual(adopted_path.read_bytes(), generated_path.read_bytes())
        self.assertEqual(adopted["parent_generation"], published["generation_id"])
        self.assertTrue(Path(adopted["adoption_receipt"]).is_file())


if __name__ == "__main__":
    unittest.main()
