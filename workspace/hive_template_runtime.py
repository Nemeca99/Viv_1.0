"""Hash-checked, data-only code templates owned by the LocalCoder workspace."""

from __future__ import annotations

import hashlib
import json
import keyword
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
TEMPLATE_ROOT = ROOT / "code_templates"
REGISTRY_PATH = TEMPLATE_ROOT / "registry.json"
SCHEMA = "hive_code_template_registry_v1"
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class TemplateError(ValueError):
    """Template registry, slot, or source failed its closed contract."""


@dataclass(frozen=True)
class RenderedTemplate:
    template_id: str
    source_sha256: str
    output_sha256: str
    code: str


class TemplateRuntime:
    """Materialize a small allowlisted set of Python templates from data slots."""

    SLOT_RULES: dict[str, tuple[set[str], set[str]]] = {
        "python.module_docstring": ({"docstring"}, {"docstring_literal"}),
        "python.typing_final_import": (set(), set()),
        "python.greeting_function": (
            {"greeting", "function_name"},
            {"greeting_literal", "function_name"},
        ),
    }

    def __init__(self, registry_path: Path = REGISTRY_PATH) -> None:
        self.registry_path = registry_path.resolve(strict=True)
        self.template_root = self.registry_path.parent.resolve(strict=True)
        try:
            registry = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise TemplateError(f"registry_invalid:{exc}") from exc
        if not isinstance(registry, dict) or registry.get("schema_version") != SCHEMA:
            raise TemplateError("registry_schema_invalid")
        rows = registry.get("templates")
        if not isinstance(rows, list):
            raise TemplateError("registry_templates_invalid")
        self.registry_sha256 = self._sha(self.registry_path.read_bytes())
        self.templates: dict[str, tuple[str, str]] = {}
        for row in rows:
            if not isinstance(row, dict) or set(row) != {
                "template_id",
                "path",
                "sha256",
            }:
                raise TemplateError("registry_row_invalid")
            template_id, relative, expected = (
                row["template_id"],
                row["path"],
                row["sha256"],
            )
            if template_id not in self.SLOT_RULES or template_id in self.templates:
                raise TemplateError(f"template_id_invalid:{template_id}")
            rel = Path(relative)
            if (
                rel.is_absolute()
                or rel.drive
                or any(part in {"", ".", ".."} for part in rel.parts)
            ):
                raise TemplateError("template_path_not_relative")
            lexical = self.template_root / rel
            cursor = lexical
            while cursor != self.template_root and cursor != cursor.parent:
                if cursor.exists() and self._is_reparse(cursor):
                    raise TemplateError("template_path_reparse")
                cursor = cursor.parent
            path = lexical.resolve(strict=True)
            if self.template_root not in path.parents or self._is_reparse(path):
                raise TemplateError("template_path_outside_root")
            actual = self._sha(path.read_bytes())
            if actual != expected:
                raise TemplateError(f"template_hash_mismatch:{template_id}")
            self.templates[template_id] = (str(path), actual)
        if set(self.templates) != set(self.SLOT_RULES):
            raise TemplateError("template_registry_incomplete")

    @staticmethod
    def _sha(raw: bytes) -> str:
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _is_reparse(path: Path) -> bool:
        import os

        if path.is_symlink() or os.path.islink(path):
            return True
        is_junction = getattr(os.path, "isjunction", None)
        return bool(is_junction and is_junction(path))

    def render(self, template_id: str, values: dict[str, Any]) -> RenderedTemplate:
        if template_id not in self.templates:
            raise TemplateError(f"template_not_allowed:{template_id}")
        required_values, slots = self.SLOT_RULES[template_id]
        if not isinstance(values, dict) or set(values) != required_values:
            raise TemplateError(f"slot_schema_mismatch:{template_id}")
        if template_id == "python.module_docstring":
            value = values["docstring"]
            if not isinstance(value, str) or not value.strip() or len(value) > 200:
                raise TemplateError("docstring_value_invalid")
            replacements = {"docstring_literal": json.dumps(value, ensure_ascii=False)}
        elif template_id == "python.typing_final_import":
            replacements = {}
        else:
            greeting = values["greeting"]
            name = values["function_name"]
            if (
                not isinstance(greeting, str)
                or not greeting.strip()
                or len(greeting) > 200
            ):
                raise TemplateError("greeting_value_invalid")
            if (
                not isinstance(name, str)
                or not IDENTIFIER.fullmatch(name)
                or keyword.iskeyword(name)
            ):
                raise TemplateError("function_name_invalid")
            replacements = {
                "greeting_literal": json.dumps(greeting, ensure_ascii=False),
                "function_name": name,
            }
        source_path, source_hash = self.templates[template_id]
        code = Path(source_path).read_text(encoding="utf-8")
        found = set(re.findall(r"\{\{([a-z_]+)\}\}", code))
        if found != slots:
            raise TemplateError(f"template_slot_mismatch:{template_id}")
        for slot, value in replacements.items():
            code = code.replace("{{" + slot + "}}", value)
        if "{{" in code or "}}" in code:
            raise TemplateError(f"unresolved_template_slot:{template_id}")
        return RenderedTemplate(
            template_id, source_hash, self._sha(code.encode("utf-8")), code
        )
