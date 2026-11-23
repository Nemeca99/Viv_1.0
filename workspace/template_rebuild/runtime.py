"""Small read-only runtime for the isolated rebuilt fixture.echo template."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Mapping


class TemplateRuntimeError(ValueError):
    """A rebuilt template or requested variable override failed verification."""


class TemplateRuntime:
    """Verify a pinned template before import; execute only on an explicit call."""

    def __init__(self, run_dir: Path, reference: Path) -> None:
        self.run_dir = run_dir.resolve(strict=True)
        self.reference = reference.resolve(strict=True)
        registry_path = self.run_dir / "registry.json"
        try:
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            if registry.get("schema_version") != "hive_rebuilt_template_registry_v1":
                raise TemplateRuntimeError("registry schema mismatch")
            (row,) = registry["templates"]
            if set(row) != {
                "template_id",
                "source",
                "source_sha256",
                "declared_variables",
            }:
                raise TemplateRuntimeError("registry row shape mismatch")
            if (
                row["template_id"] != "fixture.echo"
                or row["source"] != "fixture_echo.py"
            ):
                raise TemplateRuntimeError("template outside allowlist")
            if row["declared_variables"] != ["message", "suffix"]:
                raise TemplateRuntimeError("declared variables changed")
            self.source = self.run_dir / row["source"]
            raw = self.source.read_bytes()
            if hashlib.sha256(raw).hexdigest() != row["source_sha256"]:
                raise TemplateRuntimeError("template hash mismatch")
            source_text = raw.decode("utf-8")
            original = self.reference.read_text(encoding="utf-8")
            begin = "# TEMPLATE VARIABLES BEGIN\n"
            end = "# TEMPLATE VARIABLES END\n"
            left, rest = source_text.split(begin, 1)
            _, right = rest.split(end, 1)
            original_left, original_rest = original.split(begin, 1)
            _, original_right = original_rest.split(end, 1)
            if left != original_left or right != original_right:
                raise TemplateRuntimeError("non-variable source span changed")
            tree = ast.parse(source_text)
            assignments = [
                node
                for node in tree.body
                if isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "VARIABLES"
            ]
            if len(assignments) != 1:
                raise TemplateRuntimeError("VARIABLES assignment invalid")
            values = ast.literal_eval(assignments[0].value)
            if not isinstance(values, dict) or set(values) != {"message", "suffix"}:
                raise TemplateRuntimeError("variable keys invalid")
            if not all(isinstance(value, str) and value for value in values.values()):
                raise TemplateRuntimeError("variable values invalid")
            compile(source_text, str(self.source), "exec")
            self.variables = values
            self._module = None
        except (
            OSError,
            UnicodeError,
            KeyError,
            TypeError,
            SyntaxError,
            ValueError,
        ) as exc:
            if isinstance(exc, TemplateRuntimeError):
                raise
            raise TemplateRuntimeError(f"template invalid: {exc}") from exc

    def execute(
        self, context: Mapping[str, Any], overrides: Mapping[str, str] | None = None
    ) -> dict[str, Any]:
        if not isinstance(context, Mapping):
            raise TemplateRuntimeError("context must be a mapping")
        extra = dict(overrides or {})
        if set(extra) - set(self.variables):
            raise TemplateRuntimeError("undeclared variable override")
        if not all(
            isinstance(value, str) and value and len(value) <= 80
            for value in extra.values()
        ):
            raise TemplateRuntimeError("override value invalid")
        values = self.variables | extra
        if self._module is None:
            spec = importlib.util.spec_from_file_location(
                "hive_rebuilt_fixture_echo", self.source
            )
            if spec is None or spec.loader is None:
                raise TemplateRuntimeError("module import unavailable")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self._module = module
        return self._module.main(context, values)
