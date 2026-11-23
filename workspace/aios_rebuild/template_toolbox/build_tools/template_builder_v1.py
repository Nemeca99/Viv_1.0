"""Viv deterministic code-template toolbox.

This module is intentionally a copier and validator, not a code generator.
Source templates are parsed only to discover and validate exact source spans;
generated modules are assembled from those spans without formatting or code
rewriting.  The command-line surface is the portable toolbox presented to an
AI or operator: index, build, verify, publish, rollback, adopt, and status.

The normal CLI uses the existing Rust-gated Python writer for generated
``.py`` files.  A closed or unavailable security capability therefore leaves
publication fail-closed.  Unit tests inject an isolated security adapter so
transaction behavior can be tested without weakening the production path.
"""
from __future__ import annotations

import argparse
import ast
import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import py_compile
import re
import shutil
import sys
import tempfile
import time
from typing import Any, Iterable, Mapping, Sequence


TOOLBOX_SCHEMA = "viv_code_template_toolbox_v1"
REGISTRY_SCHEMA = "viv_code_template_registry_v1"
INDEX_SCHEMA = "viv_code_template_function_index_v1"
GENERATION_SCHEMA = "viv_code_template_generation_v1"
POINTER_SCHEMA = "viv_code_template_pointer_v1"
RECEIPT_SCHEMA = "viv_code_template_receipt_v1"
SELECTION_REQUEST_SCHEMA = "viv_code_template_selection_request_v1"
SOURCE_INDEX_RECEIPT_SCHEMA = "viv_code_template_source_index_receipt_v1"
SELF_TEST_RECEIPT_SCHEMA = "viv_code_template_self_test_receipt_v1"

TARGET_PILLARS = frozenset({"rid", "auto", "uml"})
VARIABLES_BEGIN = "# TEMPLATE VARIABLES BEGIN"
VARIABLES_END = "# TEMPLATE VARIABLES END"
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_GENERATION_RE = re.compile(r"^gen_[a-f0-9]{16}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_ZERO_SHA256 = "0" * 64

# Imports that make a template an unsafe implicit runtime capability.  Domain
# code may still call safe, already-authorized foundation functions explicitly
# from ``main``; it may not smuggle process, network, filesystem, or dynamic
# import authority into a module at import time.
DENIED_IMPORT_ROOTS = frozenset(
    {
        "builtins",
        "ctypes",
        "httpx",
        "importlib",
        "multiprocessing",
        "os",
        "pathlib",
        "requests",
        "shutil",
        "socket",
        "subprocess",
        "sys",
        "tempfile",
        "urllib",
    }
)
DENIED_CALL_NAMES = frozenset(
    {
        "__import__",
        "compile",
        "eval",
        "exec",
        "input",
        "open",
    }
)
ALLOWED_DECORATORS = frozenset({"typing.no_type_check"})


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ToolboxPaths:
    """Resolved source, generation, pointer, and evidence paths."""

    repo_root: Path
    source_root: Path
    registry_path: Path
    toolbox_manifest: Path
    generation_root: Path
    current_pointer: Path
    receipt_root: Path

    @classmethod
    def default(cls) -> "ToolboxPaths":
        root = _repo_root()
        return cls(
            repo_root=root,
            source_root=root / "foundation" / "code_templates" / "source",
            registry_path=root / "foundation" / "code_templates" / "registry.json",
            toolbox_manifest=root / "foundation" / "code_templates" / "TOOLBOX.json",
            generation_root=root / "sandbox" / "code" / "template_generations",
            current_pointer=root / "sandbox" / "code" / "template_current.json",
            receipt_root=root / "foundation" / "artifacts" / "auto" / "code_templates",
        )


@dataclass(frozen=True)
class Section:
    name: str
    kind: str
    source_start_line: int
    source_end_line: int
    decorated: bool = False


@dataclass(frozen=True)
class ParsedTemplate:
    template_id: str
    source_rel: str
    source_path: Path
    source_sha256: str
    source_text: str
    lines: tuple[str, ...]
    imports: Section | None
    variables: Section
    main: Section
    submains: tuple[Section, ...]
    variable_keys: tuple[str, ...]
    targets: tuple[str, ...]
    submain_order: tuple[str, ...]


@dataclass(frozen=True)
class GeneratedModule:
    template: ParsedTemplate
    generated_rel: str
    generated_text: str
    generated_sha256: str
    sections: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class GenerationPlan:
    generation_id: str
    input_sha256: str
    parent_generation: str | None
    lineage_tail: tuple[str, ...]
    templates: tuple[ParsedTemplate, ...]
    modules: tuple[GeneratedModule, ...]
    index: dict[str, Any]
    manifest: dict[str, Any]
    selection_request: dict[str, Any] | None = None
    selection_request_sha256: str | None = None


class TemplateContractError(ValueError):
    """Source or registry violates the deterministic template contract."""


class GenerationVerificationError(ValueError):
    """A generation, pointer, receipt, or source hash is not trustworthy."""


def _validate_toolbox_paths(paths: ToolboxPaths) -> None:
    """Keep generated outputs and pointers away from source and protected mains."""
    source_root = paths.source_root.resolve(strict=False)
    generation_root = paths.generation_root.resolve(strict=False)
    current_pointer = paths.current_pointer.resolve(strict=False)
    for label, candidate in (
        ("source_root", paths.source_root),
        ("generation_root", paths.generation_root),
        ("current_pointer", paths.current_pointer),
        ("receipt_root", paths.receipt_root),
    ):
        if candidate.exists() and _is_reparse_point(candidate):
            raise TemplateContractError(f"{label}_reparse_path")
    protected_files = {
        (paths.repo_root / "foundation" / name).resolve(strict=False)
        for name in ("rid_main.py", "auto_main.py", "uml_main.py")
    }
    if generation_root == source_root or source_root in generation_root.parents:
        raise TemplateContractError("generated_root_inside_source_root")
    if generation_root in source_root.parents:
        raise TemplateContractError("source_root_inside_generated_root")
    if current_pointer == source_root or source_root in current_pointer.parents:
        raise TemplateContractError("pointer_inside_source_root")
    if current_pointer == generation_root or generation_root in current_pointer.parents:
        raise TemplateContractError("pointer_inside_generated_root")
    if generation_root in protected_files or current_pointer in protected_files:
        raise TemplateContractError("protected_main_output_path")
    if generation_root == paths.repo_root.resolve(strict=False) / "foundation":
        raise TemplateContractError("generated_root_is_foundation")


def _source_index_path(paths: ToolboxPaths) -> Path:
    return paths.receipt_root / "source_function_index.json"


def _source_index_receipt_path(paths: ToolboxPaths) -> Path:
    return paths.receipt_root / "source_function_index.receipt.json"


def _source_index_receipt_payload(
    paths: ToolboxPaths,
    index: Mapping[str, Any],
    index_bytes: bytes,
) -> dict[str, Any]:
    return {
        "schema_version": SOURCE_INDEX_RECEIPT_SCHEMA,
        "created_utc": _utc(),
        "index_path": _posix(_source_index_path(paths)),
        "index_sha256": _sha256_bytes(index_bytes),
        "registry_sha256": index.get("registry_sha256"),
        "source_root": _posix(paths.source_root),
    }


def _utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _posix(path: Path | str) -> str:
    return str(path).replace("\\", "/")


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _indexed_write_provenance(module: GeneratedModule, *, origin: str) -> dict[str, Any]:
    """Bind a Python write to the approved template spans that produced it."""
    section_hashes = {
        str(row.get("section")): str(row.get("source_sha256"))
        for row in module.sections
        if isinstance(row, Mapping)
    }
    return {
        "schema_version": "viv_indexed_source_write_provenance_v1",
        "origin": origin,
        "template_id": module.template.template_id,
        "source_path": module.template.source_rel,
        "source_sha256": module.template.source_sha256,
        "content_sha256": module.generated_sha256,
        "section_hashes": section_hashes,
        "source_index_sha256": _sha256_text(_stable_json(module.sections)),
    }


def _read_bytes(path: Path) -> bytes:
    return path.read_bytes()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GenerationVerificationError(f"invalid_json:{path}:{exc}") from exc
    if not isinstance(value, dict):
        raise GenerationVerificationError(f"json_object_required:{path}")
    return value


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def _estimated_tokens(text: str) -> int:
    """Model-agnostic planning estimate; exact counts require the model tokenizer."""
    return max(1, math.ceil(len(text) / 4)) if text else 0


def _redact_protected_paths(value: Any) -> Any:
    """Keep evidence useful without echoing protected runtime paths into gates."""
    if isinstance(value, Mapping):
        return {str(key): _redact_protected_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_protected_paths(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_protected_paths(item) for item in value)
    if isinstance(value, str) and "sandbox/code" in value.casefold():
        return "<protected-generated-root>"
    if isinstance(value, str) and "security_core" in value.casefold():
        redacted = value.replace("security_core", "rust_security")
        return redacted.split(" path=", 1)[0] + " path=<protected-security-runtime>"
    return value


def _manifest_path_value(paths: ToolboxPaths, path: Path, token: str) -> str:
    default_root = _repo_root().resolve(strict=False)
    try:
        if paths.repo_root.resolve(strict=False) == default_root:
            return token
    except OSError:
        pass
    return _posix(path)


def _safe_relative(root: Path, raw: str, *, suffix: str | None = None) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise TemplateContractError("relative_path_required")
    candidate = Path(raw)
    if candidate.is_absolute() or candidate.drive or candidate.root or any(
        part in {"", ".", ".."} for part in candidate.parts
    ):
        raise TemplateContractError(f"unsafe_relative_path:{raw}")
    if suffix and candidate.suffix.lower() != suffix.lower():
        raise TemplateContractError(f"path_suffix_required:{raw}:{suffix}")
    lexical = root / candidate
    cursor = lexical
    root_resolved = root.resolve(strict=False)
    while cursor != root and cursor != cursor.parent:
        if cursor.exists() and _is_reparse_point(cursor):
            raise TemplateContractError(f"reparse_path:{raw}")
        cursor = cursor.parent
    resolved = (root / candidate).resolve(strict=False)
    try:
        resolved.relative_to(root.resolve(strict=False))
    except ValueError as exc:
        raise TemplateContractError(f"path_outside_root:{raw}") from exc
    cursor = resolved
    while cursor != root_resolved and cursor != cursor.parent:
        if _is_reparse_point(cursor):
            raise TemplateContractError(f"reparse_path:{raw}")
        cursor = cursor.parent
    return candidate


def _is_reparse_point(path: Path) -> bool:
    """Reject symlinks/junctions in source and generated path walks."""
    if path.is_symlink() or os.path.islink(path):
        return True
    is_junction = getattr(os.path, "isjunction", None)
    return bool(is_junction and is_junction(path))


def _line_text(lines: Sequence[str], line: int) -> str:
    return lines[line - 1].rstrip("\r\n") if 1 <= line <= len(lines) else ""


def _find_marker(lines: Sequence[str], marker: str) -> list[int]:
    return [i for i, line in enumerate(lines, 1) if line.rstrip("\r\n").strip() == marker]


def _call_name(node: ast.Call) -> str:
    value: ast.AST = node.func
    parts: list[str] = []
    while isinstance(value, ast.Attribute):
        parts.append(value.attr)
        value = value.value
    if isinstance(value, ast.Name):
        parts.append(value.id)
    return ".".join(reversed(parts))


def _attribute_name(value: ast.AST) -> str:
    parts: list[str] = []
    cursor = value
    while isinstance(cursor, ast.Attribute):
        parts.append(cursor.attr)
        cursor = cursor.value
    if isinstance(cursor, ast.Name):
        parts.append(cursor.id)
    return ".".join(reversed(parts))


def _node_start(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    lines: Sequence[str] | None = None,
) -> tuple[int, bool]:
    starts = [int(node.lineno)]
    for decorator in node.decorator_list:
        start = int(decorator.lineno)
        if lines is not None:
            cursor = start
            while cursor > 1:
                text = _line_text(lines, cursor)
                if text.lstrip().startswith("@"):
                    start = cursor
                    break
                if not text.strip() or text.lstrip().startswith(("def ", "async def ")):
                    break
                cursor -= 1
        starts.append(start)
    return min(starts), bool(node.decorator_list)


def _node_end(node: ast.AST) -> int:
    end = getattr(node, "end_lineno", None)
    if not isinstance(end, int):
        raise TemplateContractError("python_end_lineno_unavailable")
    return end


def _root_name(module: str) -> str:
    return module.split(".", 1)[0].casefold()


def _validate_import(node: ast.Import | ast.ImportFrom) -> None:
    names = [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.module:
        names.append(node.module)
    for name in names:
        if _root_name(name) in DENIED_IMPORT_ROOTS:
            raise TemplateContractError(f"unsafe_import:{name}")


def _validate_decorators(node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Call):
            raise TemplateContractError(f"decorator_call_not_allowed:{node.name}")
        if not isinstance(decorator, (ast.Name, ast.Attribute)):
            raise TemplateContractError(f"decorator_shape_not_allowed:{node.name}")
        name = _call_name(decorator) if isinstance(decorator, ast.Call) else _attribute_name(decorator)
        if name not in ALLOWED_DECORATORS:
            raise TemplateContractError(f"decorator_not_allowed:{node.name}:{name}")


def _validate_signature(node: ast.FunctionDef, *, template_id: str) -> None:
    positional = [*node.args.posonlyargs, *node.args.args]
    names = [argument.arg for argument in positional]
    if names != ["context", "variables"]:
        raise TemplateContractError(f"signature_invalid:{template_id}:{node.name}")
    if node.args.defaults or node.args.kw_defaults or node.args.vararg or node.args.kwarg:
        raise TemplateContractError(f"signature_defaults_or_variadic_not_allowed:{template_id}:{node.name}")
    if node.args.kwonlyargs:
        raise TemplateContractError(f"signature_keyword_only_not_allowed:{template_id}:{node.name}")


def _validate_function_body(node: ast.FunctionDef) -> None:
    for child in ast.walk(node):
        if child is node:
            continue
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            raise TemplateContractError(f"helper_functions_not_allowed:{node.name}:{child.name}")
        if isinstance(child, (ast.Import, ast.ImportFrom)):
            raise TemplateContractError(f"imports_must_be_top_level:{node.name}")
        if isinstance(child, ast.Call):
            name = _call_name(child)
            root = name.split(".", 1)[0].casefold()
            if name in DENIED_CALL_NAMES or root in DENIED_IMPORT_ROOTS:
                raise TemplateContractError(f"unsafe_call:{node.name}:{name}")


def _assignment_name(node: ast.Assign | ast.AnnAssign) -> str | None:
    targets: list[ast.AST]
    if isinstance(node, ast.Assign):
        targets = list(node.targets)
    else:
        targets = [node.target]
    if len(targets) != 1 or not isinstance(targets[0], ast.Name):
        return None
    return targets[0].id


def _literal_variables(node: ast.Assign | ast.AnnAssign) -> dict[str, Any]:
    value = node.value
    if not isinstance(value, ast.Dict):
        raise TemplateContractError("VARIABLES_must_be_dict_literal")
    try:
        parsed = ast.literal_eval(value)
    except (ValueError, TypeError, SyntaxError) as exc:
        raise TemplateContractError("VARIABLES_must_be_literal") from exc
    if not isinstance(parsed, dict) or any(not isinstance(key, str) for key in parsed):
        raise TemplateContractError("VARIABLES_keys_must_be_strings")
    return parsed


def _validate_registry(paths: ToolboxPaths) -> list[dict[str, Any]]:
    registry = _read_json(paths.registry_path)
    if registry.get("schema_version") != REGISTRY_SCHEMA:
        raise TemplateContractError("registry_schema_mismatch")
    rows = registry.get("templates")
    if not isinstance(rows, list):
        raise TemplateContractError("registry_templates_must_be_list")
    seen_ids: set[str] = set()
    seen_sources: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise TemplateContractError("registry_row_must_be_object")
        template_id = row.get("template_id")
        if not isinstance(template_id, str) or not _ID_RE.fullmatch(template_id):
            raise TemplateContractError(f"invalid_template_id:{template_id}")
        if template_id in seen_ids:
            raise TemplateContractError(f"duplicate_template_id:{template_id}")
        source_rel = _safe_relative(paths.source_root, row.get("source", ""), suffix=".py")
        source_posix = _posix(source_rel)
        if source_posix in seen_sources:
            raise TemplateContractError(f"duplicate_template_source:{source_posix}")
        targets = row.get("targets")
        if not isinstance(targets, list) or not targets or any(
            not isinstance(target, str) or target not in TARGET_PILLARS for target in targets
        ):
            raise TemplateContractError(f"invalid_targets:{template_id}")
        if len(set(targets)) != len(targets):
            raise TemplateContractError(f"duplicate_targets:{template_id}")
        submain_order = row.get("submain_order", [])
        if not isinstance(submain_order, list) or any(
            not isinstance(name, str) or not name.startswith("sub_main_") for name in submain_order
        ):
            raise TemplateContractError(f"invalid_submain_order:{template_id}")
        if len(set(submain_order)) != len(submain_order):
            raise TemplateContractError(f"duplicate_submain_order:{template_id}")
        seen_ids.add(template_id)
        seen_sources.add(source_posix)
        normalized.append(
            {
                "template_id": template_id,
                "source": source_posix,
                "targets": list(targets),
                "submain_order": list(submain_order),
            }
        )
    return normalized


def _normalize_selection_request(
    rows: Sequence[Mapping[str, Any]],
    request: Mapping[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Validate the AI-facing selection payload and return registry row copies.

    The payload can select a subset of approved templates, narrow a template to
    already-declared target pillars, and permute its already-declared submains.
    It cannot name a source path, function body, import, or arbitrary code.
    """
    if request is None:
        return [dict(row) for row in rows], None
    if not isinstance(request, Mapping):
        raise TemplateContractError("selection_request_object_required")
    allowed_keys = {"schema_version", "templates"}
    unknown_keys = sorted(str(key) for key in request if str(key) not in allowed_keys)
    if unknown_keys:
        raise TemplateContractError(f"selection_request_fields_not_allowed:{','.join(unknown_keys)}")
    if request.get("schema_version") != SELECTION_REQUEST_SCHEMA:
        raise TemplateContractError("selection_request_schema_mismatch")
    request_rows = request.get("templates")
    if not isinstance(request_rows, list) or not request_rows:
        raise TemplateContractError("selection_request_templates_must_be_nonempty_list")

    by_id = {str(row["template_id"]): row for row in rows}
    seen_ids: set[str] = set()
    selected: list[dict[str, Any]] = []
    normalized_rows: list[dict[str, Any]] = []
    target_order = {name: index for index, name in enumerate(sorted(TARGET_PILLARS))}
    for item in request_rows:
        if not isinstance(item, Mapping):
            raise TemplateContractError("selection_request_template_row_must_be_object")
        item_keys = {str(key) for key in item}
        unsupported = sorted(item_keys - {"template_id", "target_pillars", "submain_order"})
        if unsupported:
            raise TemplateContractError(
                f"selection_request_template_fields_not_allowed:{','.join(unsupported)}"
            )
        template_id = item.get("template_id")
        if not isinstance(template_id, str) or template_id not in by_id:
            raise TemplateContractError(f"selection_request_unknown_template:{template_id}")
        if template_id in seen_ids:
            raise TemplateContractError(f"selection_request_duplicate_template:{template_id}")
        seen_ids.add(template_id)
        registry_row = by_id[template_id]

        requested_targets = item.get("target_pillars", registry_row["targets"])
        if not isinstance(requested_targets, list) or not requested_targets:
            raise TemplateContractError(f"selection_request_targets_invalid:{template_id}")
        if any(not isinstance(target, str) or target not in TARGET_PILLARS for target in requested_targets):
            raise TemplateContractError(f"selection_request_targets_invalid:{template_id}")
        if len(set(requested_targets)) != len(requested_targets):
            raise TemplateContractError(f"selection_request_duplicate_target:{template_id}")
        undeclared_targets = sorted(set(requested_targets) - set(registry_row["targets"]))
        if undeclared_targets:
            raise TemplateContractError(
                f"selection_request_target_not_declared:{template_id}:{','.join(undeclared_targets)}"
            )
        canonical_targets = sorted(requested_targets, key=lambda target: target_order[target])

        requested_order = item.get("submain_order", registry_row["submain_order"])
        if not isinstance(requested_order, list) or any(
            not isinstance(name, str) or not name.startswith("sub_main_") for name in requested_order
        ):
            raise TemplateContractError(f"selection_request_submain_order_invalid:{template_id}")
        if len(set(requested_order)) != len(requested_order):
            raise TemplateContractError(f"selection_request_duplicate_submain:{template_id}")
        if set(requested_order) != set(registry_row["submain_order"]):
            raise TemplateContractError(f"selection_request_submain_set_mismatch:{template_id}")

        selected.append(
            {
                "template_id": template_id,
                "source": str(registry_row["source"]),
                "targets": canonical_targets,
                "submain_order": list(requested_order),
            }
        )
        normalized_rows.append(
            {
                "template_id": template_id,
                "target_pillars": canonical_targets,
                "submain_order": list(requested_order),
            }
        )

    normalized = {
        "schema_version": SELECTION_REQUEST_SCHEMA,
        "templates": normalized_rows,
    }
    return selected, normalized


def _selection_request_hash(request: Mapping[str, Any] | None) -> str | None:
    if request is None:
        return None
    return _sha256_text(_stable_json(request))


def _validate_normalized_selection_request(
    request: Any,
    modules: Sequence[Mapping[str, Any]],
) -> None:
    """Validate selection metadata stored in a generation before trusting it."""
    if not isinstance(request, dict):
        raise GenerationVerificationError("generation_selection_request_invalid")
    if set(request) != {"schema_version", "templates"}:
        raise GenerationVerificationError("generation_selection_request_fields_invalid")
    if request.get("schema_version") != SELECTION_REQUEST_SCHEMA:
        raise GenerationVerificationError("generation_selection_request_schema_mismatch")
    rows = request.get("templates")
    if not isinstance(rows, list) or not rows or len(rows) != len(modules):
        raise GenerationVerificationError("generation_selection_request_templates_invalid")
    for request_row, module in zip(rows, modules):
        if not isinstance(request_row, dict):
            raise GenerationVerificationError("generation_selection_request_row_invalid")
        if set(request_row) != {"template_id", "target_pillars", "submain_order"}:
            raise GenerationVerificationError("generation_selection_request_row_fields_invalid")
        if request_row.get("template_id") != module.get("template_id"):
            raise GenerationVerificationError("generation_selection_request_module_order_mismatch")
        if request_row.get("target_pillars") != module.get("target_pillars"):
            raise GenerationVerificationError("generation_selection_request_target_mismatch")
        if request_row.get("submain_order") != module.get("submain_order"):
            raise GenerationVerificationError("generation_selection_request_submain_mismatch")


def parse_template(row: Mapping[str, Any], paths: ToolboxPaths) -> ParsedTemplate:
    """Validate and index one source file without modifying it."""
    template_id = str(row["template_id"])
    source_rel = str(row["source"])
    source_path = paths.source_root / Path(source_rel)
    if not source_path.is_file():
        raise TemplateContractError(f"source_missing:{source_path}")
    source_bytes = _read_bytes(source_path)
    try:
        source_text = source_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TemplateContractError(f"source_not_utf8:{source_path}") from exc
    lines = tuple(source_text.splitlines(keepends=True))
    try:
        tree = ast.parse(source_text, filename=str(source_path), type_comments=True)
    except SyntaxError as exc:
        raise TemplateContractError(f"syntax_error:{source_path}:{exc}") from exc

    begin = _find_marker(lines, VARIABLES_BEGIN)
    end = _find_marker(lines, VARIABLES_END)
    if len(begin) != 1 or len(end) != 1 or begin[0] >= end[0]:
        raise TemplateContractError(f"VARIABLES_markers_invalid:{template_id}")
    variables_begin, variables_end = begin[0], end[0]

    imports: list[ast.Import | ast.ImportFrom] = []
    functions: list[ast.FunctionDef] = []
    variable_nodes: list[ast.Assign | ast.AnnAssign] = []
    unexpected: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            _validate_import(node)
            imports.append(node)
        elif isinstance(node, ast.FunctionDef):
            _validate_decorators(node)
            _validate_function_body(node)
            _validate_signature(node, template_id=template_id)
            functions.append(node)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            variable_nodes.append(node)
        else:
            unexpected.append(type(node).__name__)
    if unexpected:
        raise TemplateContractError(f"top_level_nodes_not_allowed:{template_id}:{','.join(unexpected)}")

    variables_candidates = [
        node
        for node in variable_nodes
        if variables_begin < int(node.lineno) <= variables_end
        and _assignment_name(node) == "VARIABLES"
        and _node_end(node) <= variables_end
    ]
    if len(variables_candidates) != 1:
        raise TemplateContractError(f"VARIABLES_assignment_invalid:{template_id}")
    variables_node = variables_candidates[0]
    if any(node is not variables_node for node in variable_nodes):
        raise TemplateContractError(f"top_level_assignment_not_allowed:{template_id}")
    variables = _literal_variables(variables_node)

    main_nodes = [node for node in functions if node.name == "main"]
    submain_nodes = {node.name: node for node in functions if node.name.startswith("sub_main_")}
    unsupported_functions = [node.name for node in functions if node.name != "main" and not node.name.startswith("sub_main_")]
    duplicate_submains = sorted(
        name for name in submain_nodes if sum(1 for node in functions if node.name == name) > 1
    )
    if len(main_nodes) != 1:
        raise TemplateContractError(f"main_count_invalid:{template_id}")
    if unsupported_functions:
        raise TemplateContractError(f"helper_functions_not_allowed:{template_id}:{','.join(unsupported_functions)}")
    if duplicate_submains:
        raise TemplateContractError(f"submain_count_invalid:{template_id}:{','.join(duplicate_submains)}")
    main_node = main_nodes[0]
    if not isinstance(main_node, ast.FunctionDef):
        raise TemplateContractError(f"async_main_not_allowed:{template_id}")

    registry_order = tuple(str(name) for name in row.get("submain_order", []))
    if set(registry_order) != set(submain_nodes):
        raise TemplateContractError(
            f"submain_order_mismatch:{template_id}:declared={list(registry_order)}:source={sorted(submain_nodes)}"
        )

    if imports:
        imports_start = min(int(node.lineno) for node in imports)
        imports_end = max(_node_end(node) for node in imports)
        imports_section = Section("__imports__", "imports", imports_start, imports_end)
        if imports_start > variables_begin or imports_end >= variables_begin:
            raise TemplateContractError(f"imports_not_above_variables:{template_id}")
    else:
        imports_section = None

    main_start, main_decorated = _node_start(main_node, lines)
    main_end = _node_end(main_node)
    if not variables_begin < variables_end < main_start:
        raise TemplateContractError(f"variables_not_above_main:{template_id}")

    sections: list[Section] = []
    for node in functions:
        start, decorated = _node_start(node, lines)
        end_line = _node_end(node)
        if start <= variables_end:
            raise TemplateContractError(f"function_overlaps_variables:{template_id}:{node.name}")
        sections.append(Section(node.name, "main" if node.name == "main" else "submain", start, end_line, decorated))
    if any(section.source_start_line < main_start for section in sections if section.name.startswith("sub_main_")):
        raise TemplateContractError(f"main_after_submain:{template_id}")
    ordered_submains = tuple(
        next(section for section in sections if section.name == name) for name in registry_order
    )

    return ParsedTemplate(
        template_id=template_id,
        source_rel=source_rel,
        source_path=source_path,
        source_sha256=_sha256_bytes(source_bytes),
        source_text=source_text,
        lines=lines,
        imports=imports_section,
        variables=Section("VARIABLES", "variables", variables_begin, variables_end),
        main=Section("main", "main", main_start, main_end, main_decorated),
        submains=ordered_submains,
        variable_keys=tuple(sorted(variables)),
        targets=tuple(str(target) for target in row["targets"]),
        submain_order=registry_order,
    )


def _span(lines: Sequence[str], start: int, end: int) -> str:
    return "".join(lines[start - 1 : end])


def _newline_for(text: str) -> str:
    if "\r\n" in text:
        return "\r\n"
    return "\n"


def _generated_end_line(start: int, text: str) -> int:
    if not text:
        return start - 1
    return start + text.count("\n") - (1 if text.endswith("\n") else 0)


def _assemble_template(template: ParsedTemplate) -> tuple[str, tuple[dict[str, Any], ...]]:
    newline = _newline_for(template.source_text)
    blocks: list[tuple[str, str, int, int, bool]] = []
    if template.imports is not None:
        section = template.imports
        blocks.append(
            (section.name, section.kind, section.source_start_line, section.source_end_line, section.decorated)
        )
    blocks.append(
        (
            template.variables.name,
            template.variables.kind,
            template.variables.source_start_line,
            template.variables.source_end_line,
            False,
        )
    )
    blocks.append(
        (template.main.name, template.main.kind, template.main.source_start_line, template.main.source_end_line, template.main.decorated)
    )
    blocks.extend(
        (section.name, section.kind, section.source_start_line, section.source_end_line, section.decorated)
        for section in template.submains
    )

    parts: list[str] = []
    offsets: list[tuple[str, str, int, int, bool, int, int]] = []
    offset = 0
    for index, (name, kind, start, end, decorated) in enumerate(blocks):
        if index:
            separator = newline
            parts.append(separator)
            offset += len(separator)
        block = _span(template.lines, start, end)
        block_start = offset
        parts.append(block)
        offset += len(block)
        offsets.append((name, kind, start, end, decorated, block_start, len(block)))
    generated_text = "".join(parts)

    section_rows: list[dict[str, Any]] = []
    for name, kind, source_start, source_end, decorated, block_start, block_length in offsets:
        generated_prefix = generated_text[:block_start]
        generated_block = generated_text[block_start : block_start + block_length]
        generated_start = generated_prefix.count("\n") + 1
        generated_end = _generated_end_line(generated_start, generated_block)
        section_rows.append(
            {
                "name": name,
                "kind": kind,
                "source_start_line": source_start,
                "source_end_line": source_end,
                "generated_start_line": generated_start,
                "generated_end_line": generated_end,
                "decorated": decorated,
                "source_sha256": _sha256_text(_span(template.lines, source_start, source_end)),
                "generated_sha256": _sha256_text(generated_block),
                "target_pillars": list(template.targets),
                "submain_order": list(template.submain_order),
            }
        )
    return generated_text, tuple(section_rows)


def _source_index(templates: Sequence[ParsedTemplate]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    modules: list[dict[str, Any]] = []
    for template in templates:
        sections: list[Section] = []
        if template.imports is not None:
            sections.append(template.imports)
        sections.extend([template.variables, template.main, *template.submains])
        for section in sections:
            entries.append(
                {
                    "template_id": template.template_id,
                    "generation_id": None,
                    "source_path": template.source_rel,
                    "section": section.name,
                    "section_type": section.kind,
                    "source_start_line": section.source_start_line,
                    "source_end_line": section.source_end_line,
                    "generated_start_line": None,
                    "generated_end_line": None,
                    "source_sha256": _sha256_text(_span(template.lines, section.source_start_line, section.source_end_line)),
                    "generated_sha256": None,
                    "source_file_sha256": template.source_sha256,
                    "generated_file_sha256": None,
                    "target_pillars": list(template.targets),
                    "submain_order": list(template.submain_order),
                    "decorated": section.decorated,
                }
            )
        modules.append(
            {
                "template_id": template.template_id,
                "source_path": template.source_rel,
                "source_sha256": template.source_sha256,
                "variable_keys": list(template.variable_keys),
                "target_pillars": list(template.targets),
                "submain_order": list(template.submain_order),
            }
        )
    return {
        "schema_version": INDEX_SCHEMA,
        "generation_id": None,
        "modules": modules,
        "entries": entries,
    }


def _generation_input(
    templates: Sequence[ParsedTemplate],
    registry_bytes: bytes,
    selection_request: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "registry_sha256": _sha256_bytes(registry_bytes),
        "templates": [
            {
                "template_id": template.template_id,
                "source": template.source_rel,
                "source_sha256": template.source_sha256,
                "targets": list(template.targets),
                "submain_order": list(template.submain_order),
            }
            for template in templates
        ],
    }
    if selection_request is not None:
        payload["selection_request"] = dict(selection_request)
    return payload


def _load_current_pointer(paths: ToolboxPaths) -> dict[str, Any] | None:
    if not paths.current_pointer.is_file():
        return None
    pointer = _read_json(paths.current_pointer)
    return _validate_pointer_payload(pointer)


def _validate_pointer_payload(pointer: Mapping[str, Any]) -> dict[str, Any]:
    """Validate pointer JSON before it can influence publication or loading."""
    if pointer.get("schema_version") != POINTER_SCHEMA:
        raise GenerationVerificationError("pointer_schema_mismatch")
    generation_id = pointer.get("generation_id")
    if not isinstance(generation_id, str) or not _GENERATION_RE.fullmatch(generation_id):
        raise GenerationVerificationError("pointer_generation_invalid")
    for field in ("manifest_path", "index_path", "receipt_path"):
        if not isinstance(pointer.get(field), str) or not str(pointer.get(field)).strip():
            raise GenerationVerificationError(f"pointer_{field}_invalid")
    for field in ("manifest_sha256", "index_sha256", "receipt_sha256"):
        value = pointer.get(field)
        if value is not None and (not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)):
            raise GenerationVerificationError(f"pointer_{field}_invalid")
    return dict(pointer)


def _validate_pointer_for_generation(
    pointer: Mapping[str, Any],
    generation_dir: Path,
    generation_id: str,
) -> dict[str, Any]:
    validated = _validate_pointer_payload(pointer)
    if validated.get("generation_id") != generation_id:
        raise GenerationVerificationError("pointer_generation_mismatch")
    expected = {
        "manifest_path": generation_dir / "generation_manifest.json",
        "index_path": generation_dir / "function_index.json",
        "receipt_path": generation_dir / "generation_receipt.json",
    }
    for field, expected_path in expected.items():
        actual = Path(str(validated[field])).resolve(strict=False)
        if actual != expected_path.resolve(strict=False):
            raise GenerationVerificationError(f"pointer_{field}_path_mismatch")
    return validated


def _lineage_tail(paths: ToolboxPaths, parent_generation: str | None) -> tuple[str, ...]:
    if not parent_generation:
        return ()
    manifest_path = paths.generation_root / parent_generation / "generation_manifest.json"
    if not manifest_path.is_file():
        raise GenerationVerificationError(f"parent_manifest_missing:{parent_generation}")
    parent = _read_json(manifest_path)
    prior = [str(value) for value in parent.get("lineage_tail", []) if isinstance(value, str)]
    return tuple((prior + [parent_generation])[-5:])


def _check_source_approval(
    paths: ToolboxPaths,
    templates: Sequence[ParsedTemplate],
    parent_generation: str | None,
) -> None:
    """Require a fresh source index before publishing an edited source layer."""
    index_path = _source_index_path(paths)
    approved: dict[str, str] | None = None
    if index_path.is_file():
        try:
            indexed = _read_json(index_path)
        except GenerationVerificationError as exc:
            raise TemplateContractError(f"source_index_invalid:{exc}") from exc
        if indexed.get("schema_version") != INDEX_SCHEMA:
            raise TemplateContractError("source_index_schema_mismatch")
        receipt_path = _source_index_receipt_path(paths)
        if not receipt_path.is_file():
            raise TemplateContractError("source_index_receipt_missing")
        try:
            index_receipt = _read_json(receipt_path)
        except GenerationVerificationError as exc:
            raise TemplateContractError(f"source_index_receipt_invalid:{exc}") from exc
        if index_receipt.get("schema_version") != SOURCE_INDEX_RECEIPT_SCHEMA:
            raise TemplateContractError("source_index_receipt_schema_mismatch")
        if index_receipt.get("index_sha256") != _sha256_bytes(index_path.read_bytes()):
            raise TemplateContractError("source_index_receipt_hash_mismatch")
        if Path(str(index_receipt.get("index_path") or "")).resolve(strict=False) != index_path.resolve(strict=False):
            raise TemplateContractError("source_index_receipt_path_mismatch")
        if index_receipt.get("registry_sha256") != _sha256_bytes(paths.registry_path.read_bytes()):
            raise TemplateContractError("source_index_registry_hash_mismatch")
        try:
            if Path(str(index_receipt.get("source_root") or "")).resolve(strict=False) != paths.source_root.resolve(strict=False):
                raise TemplateContractError("source_index_root_mismatch")
        except OSError as exc:
            raise TemplateContractError(f"source_index_root_unresolvable:{exc}") from exc
        rows = indexed.get("modules")
        if not isinstance(rows, list):
            raise TemplateContractError("source_index_modules_invalid")
        approved = {
            str(row.get("template_id")): str(row.get("source_sha256"))
            for row in rows
            if isinstance(row, dict) and isinstance(row.get("template_id"), str)
        }
    elif parent_generation:
        parent_manifest_path = paths.generation_root / parent_generation / "generation_manifest.json"
        try:
            parent_manifest = _read_json(parent_manifest_path)
        except GenerationVerificationError as exc:
            raise TemplateContractError(f"parent_manifest_invalid:{exc}") from exc
        rows = parent_manifest.get("modules")
        if not isinstance(rows, list):
            raise TemplateContractError("parent_manifest_modules_invalid")
        approved = {
            str(row.get("template_id")): str(row.get("source_sha256"))
            for row in rows
            if isinstance(row, dict) and isinstance(row.get("template_id"), str)
        }

    if approved is None:
        return
    current = {template.template_id: template.source_sha256 for template in templates}
    missing = sorted(template_id for template_id in current if template_id not in approved)
    if missing:
        raise TemplateContractError(f"source_index_template_missing:{','.join(missing)}")
    for template_id, source_sha256 in current.items():
        if approved.get(template_id) != source_sha256:
            raise TemplateContractError(f"source_drift_after_index:{template_id}")


def plan_generation(
    paths: ToolboxPaths,
    selection_request: Mapping[str, Any] | None = None,
) -> GenerationPlan:
    """Read, validate, and plan a complete deterministic generation."""
    _validate_toolbox_paths(paths)
    registry_bytes = _read_bytes(paths.registry_path)
    rows = _validate_registry(paths)
    selected_rows, normalized_request = _normalize_selection_request(rows, selection_request)
    templates = tuple(parse_template(row, paths) for row in selected_rows)
    input_payload = _generation_input(templates, registry_bytes, normalized_request)
    input_sha256 = _sha256_text(_stable_json(input_payload))
    selection_request_sha256 = _selection_request_hash(normalized_request)

    pointer = _load_current_pointer(paths)
    parent_generation = pointer.get("generation_id") if pointer else None
    lineage_tail = _lineage_tail(paths, parent_generation)
    _check_source_approval(paths, templates, parent_generation)
    generation_seed = _stable_json(
        {"input_sha256": input_sha256, "parent_generation": parent_generation}
    )
    generation_id = f"gen_{_sha256_text(generation_seed)[:16]}"

    modules: list[GeneratedModule] = []
    index = _source_index(templates)
    index_entries_by_key: dict[tuple[str, str], dict[str, Any]] = {
        (str(entry["template_id"]), str(entry["section"])): entry
        for entry in index["entries"]
    }
    generated_names: set[str] = set()
    for template in templates:
        generated_text, section_rows = _assemble_template(template)
        generated_rel = f"{template.template_id.replace('.', '_')}.py"
        if generated_rel in generated_names:
            raise TemplateContractError(f"generated_path_collision:{generated_rel}")
        generated_names.add(generated_rel)
        generated_sha256 = _sha256_text(generated_text)
        for row in section_rows:
            index_entry = index_entries_by_key[(template.template_id, str(row["name"]))]
            index_entry["generated_start_line"] = row["generated_start_line"]
            index_entry["generated_end_line"] = row["generated_end_line"]
            index_entry["generated_sha256"] = row["generated_sha256"]
            index_entry["generated_file_sha256"] = generated_sha256
        modules.append(
            GeneratedModule(
                template=template,
                generated_rel=generated_rel,
                generated_text=generated_text,
                generated_sha256=generated_sha256,
                sections=section_rows,
            )
        )
    index["generation_id"] = generation_id
    index["input_sha256"] = input_sha256
    for entry in index["entries"]:
        entry["generation_id"] = generation_id
    index["entries"] = sorted(index["entries"], key=lambda row: (row["template_id"], row["source_start_line"], row["section"]))
    index_sha256 = _sha256_bytes(_json_bytes(index))
    manifest = {
        "schema_version": GENERATION_SCHEMA,
        "generation_id": generation_id,
        "input_sha256": input_sha256,
        "parent_generation": parent_generation,
        "lineage_tail": list(lineage_tail),
        "lineage_display_limit": 5,
        "source_root": _manifest_path_value(paths, paths.source_root, "<source-template-root>"),
        "registry_path": _manifest_path_value(paths, paths.registry_path, "<template-registry>"),
        "registry_sha256": _sha256_bytes(registry_bytes),
        "function_index_sha256": index_sha256,
        "selection_request": normalized_request,
        "selection_request_sha256": selection_request_sha256,
        "modules": [
            {
                "template_id": module.template.template_id,
                "source_path": module.template.source_rel,
                "source_sha256": module.template.source_sha256,
                "generated_path": module.generated_rel,
                "generated_sha256": module.generated_sha256,
                "variable_keys": list(module.template.variable_keys),
                "target_pillars": list(module.template.targets),
                "submain_order": list(module.template.submain_order),
                "sections": list(module.sections),
            }
            for module in modules
        ],
    }
    return GenerationPlan(
        generation_id=generation_id,
        input_sha256=input_sha256,
        parent_generation=parent_generation,
        lineage_tail=lineage_tail,
        templates=templates,
        modules=tuple(modules),
        index=index,
        manifest=manifest,
        selection_request=normalized_request,
        selection_request_sha256=selection_request_sha256,
    )


class SecurityAdapter:
    """Interface used by the builder; production uses the Rust-backed adapter."""

    def probe(self, plan: GenerationPlan, paths: ToolboxPaths) -> dict[str, Any]:
        raise NotImplementedError

    def write_python(
        self,
        path: Path,
        content: str,
        *,
        operation_id: str,
        provenance: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def write_json(self, path: Path, content: bytes) -> dict[str, Any]:
        raise NotImplementedError


class RustSecurityAdapter(SecurityAdapter):
    """Request client for the existing Rust membrane and Python-write gate."""

    def __init__(self, *, master_s_n: float | None = None, forensic_buffer: str = "Do I? template toolbox") -> None:
        self.master_s_n = float(master_s_n) if master_s_n is not None else self._read_s_n()
        self.forensic_buffer = forensic_buffer

    @staticmethod
    def _read_s_n() -> float:
        try:
            foundation = _repo_root() / "foundation"
            if str(foundation) not in sys.path:
                sys.path.insert(0, str(foundation))
            from lib.master_rid import load_master_rid  # type: ignore

            master = load_master_rid()
            return float(master.master_s_n) if master is not None else 1.0
        except Exception:
            return 1.0

    def _imports(self) -> tuple[Any, Any, Any]:
        foundation = _repo_root() / "foundation"
        if str(foundation) not in sys.path:
            sys.path.insert(0, str(foundation))
        from lib.security_bridge import authorize_python_write, integrity_status, rust_available  # type: ignore
        from lib.security_membrane import tool_gate  # type: ignore

        return authorize_python_write, integrity_status, (rust_available, tool_gate)

    def probe(self, plan: GenerationPlan, paths: ToolboxPaths) -> dict[str, Any]:
        try:
            authorize_python_write, integrity_status, security = self._imports()
            rust_available, tool_gate = security
            armed = bool(rust_available())
            integrity = dict(integrity_status())
        except Exception as exc:
            return {"ok": False, "state": "HOLD_SECURITY", "reason": f"security_import_failed:{exc}"}

        rows: list[dict[str, Any]] = []
        for module in plan.modules:
            target = paths.generation_root / plan.generation_id / module.generated_rel
            request = {
                "action": "WRITE_PYTHON",
                "actor": "viv_autonomous",
                "operation_id": f"template-publish-{plan.generation_id}-{module.template.template_id}",
                "request_id": f"template-dry-run-{plan.generation_id}-{module.template.template_id}",
                "target_path": _posix(target).lower(),
                "parent_sha256": _ZERO_SHA256,
                "content_sha256": module.generated_sha256,
                "content_bytes": len(module.generated_text.encode("utf-8")),
                "process_id": os.getpid(),
                "master_s_n": self.master_s_n,
                "forensic_buffer": self.forensic_buffer,
            }
            try:
                verdict = dict(authorize_python_write(request))
            except Exception as exc:
                verdict = {"allowed": False, "reason": f"python_write_probe_failed:{exc}"}
            rows.append(
                {
                    "template_id": module.template.template_id,
                    "target_path": _posix(target),
                    "allowed": bool(verdict.get("allowed")),
                    "verdict": verdict,
                }
            )

        pointer_payload = {
            "schema_version": POINTER_SCHEMA,
            "generation_id": plan.generation_id,
            "manifest_path": _posix(paths.generation_root / plan.generation_id / "generation_manifest.json"),
            "input_sha256": plan.input_sha256,
        }
        try:
            pointer_verdict = dict(
                tool_gate(
                    "write_file",
                    {"path": _posix(paths.current_pointer), "content": json.dumps(pointer_payload, sort_keys=True)},
                    self.master_s_n,
                    forensic_buffer=self.forensic_buffer,
                )
            )
        except Exception as exc:
            pointer_verdict = {"allowed": False, "reason": f"pointer_probe_failed:{exc}"}
        allowed = armed and bool(integrity.get("ok")) and bool(pointer_verdict.get("allowed")) and all(
            row["allowed"] for row in rows
        )
        return {
            "ok": allowed,
            "state": "PASS" if allowed else "HOLD_SECURITY",
            "rust_available": armed,
            "integrity": integrity,
            "master_s_n": self.master_s_n,
            "python_write_decisions": rows,
            "pointer_decision": pointer_verdict,
            "reason": None if allowed else "rust_security_denied_or_unavailable",
        }

    def probe_python_write(
        self,
        *,
        target_path: Path,
        content_sha256: str,
        content_bytes: int,
        operation_id: str,
    ) -> dict[str, Any]:
        """Ask Rust about one isolated code artifact without writing it.

        The caller may use a disposable test adapter only in an explicitly
        marked self-test.  This probe itself never falls back to Python and is
        the authority check for sandbox rebuild output.
        """
        try:
            authorize_python_write, integrity_status, security = self._imports()
            rust_available, _tool_gate = security
            armed = bool(rust_available())
            integrity = dict(integrity_status())
        except Exception as exc:
            return {
                "ok": False,
                "state": "HOLD_SECURITY",
                "reason": f"security_import_failed:{exc}",
                "target_path": _posix(target_path),
            }
        request = {
            "action": "WRITE_PYTHON",
            "actor": "viv_autonomous",
            "operation_id": operation_id,
            "request_id": f"{operation_id}-probe",
            "target_path": _posix(target_path).lower(),
            "parent_sha256": _ZERO_SHA256,
            "content_sha256": content_sha256,
            "content_bytes": int(content_bytes),
            "process_id": os.getpid(),
            "master_s_n": self.master_s_n,
            "forensic_buffer": self.forensic_buffer,
        }
        try:
            verdict = dict(authorize_python_write(request))
        except Exception as exc:
            verdict = {"allowed": False, "reason": f"python_write_probe_failed:{exc}"}
        allowed = armed and bool(integrity.get("ok")) and bool(verdict.get("allowed"))
        return {
            "ok": allowed,
            "state": "PASS" if allowed else "HOLD_SECURITY",
            "rust_available": armed,
            "integrity": integrity,
            "target_path": _posix(target_path),
            "content_sha256": content_sha256,
            "content_bytes": int(content_bytes),
            "decision": verdict,
            "reason": None if allowed else str(verdict.get("reason") or "rust_security_denied_or_unavailable"),
            "test_adapter": False,
        }

    def write_python(
        self,
        path: Path,
        content: str,
        *,
        operation_id: str,
        provenance: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        foundation = _repo_root() / "foundation"
        if str(foundation) not in sys.path:
            sys.path.insert(0, str(foundation))
        from lib.viv_python_writer import write_python_source  # type: ignore

        return dict(
            write_python_source(
                path,
                content,
                master_s_n=self.master_s_n,
                forensic_buffer=self.forensic_buffer,
                operation_id=operation_id,
                provenance=provenance,
            )
        )

    def write_json(self, path: Path, content: bytes) -> dict[str, Any]:
        foundation = _repo_root() / "foundation"
        if str(foundation) not in sys.path:
            sys.path.insert(0, str(foundation))
        from lib.security_membrane import tool_gate  # type: ignore

        text = content.decode("utf-8")
        verdict = dict(tool_gate("write_file", {"path": _posix(path), "content": text}, self.master_s_n, forensic_buffer=self.forensic_buffer))
        if not verdict.get("allowed"):
            return {"ok": False, "error": str(verdict.get("reason") or "security_denied"), "verdict": verdict}
        return _atomic_write(path, content)


class LocalTestSecurityAdapter(SecurityAdapter):
    """Isolated test adapter; never used by the production CLI."""

    def probe(self, plan: GenerationPlan, paths: ToolboxPaths) -> dict[str, Any]:
        return {"ok": True, "state": "PASS", "test_adapter": True}

    def write_python(
        self,
        path: Path,
        content: str,
        *,
        operation_id: str,
        provenance: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        del operation_id, provenance
        return _atomic_write(path, content.encode("utf-8"))

    def write_json(self, path: Path, content: bytes) -> dict[str, Any]:
        return _atomic_write(path, content)


def _atomic_write(path: Path, content: bytes) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", prefix="._viv_template_", suffix=path.suffix, dir=path.parent, delete=False) as handle:
            temp_name = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        temp_name = None
        if path.read_bytes() != content:
            return {"ok": False, "error": "post_write_hash_mismatch", "path": _posix(path)}
        return {"ok": True, "path": _posix(path), "sha256": _sha256_bytes(content), "bytes": len(content)}
    except OSError as exc:
        return {"ok": False, "error": f"atomic_write_failed:{exc}", "path": _posix(path)}
    finally:
        if temp_name:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass


def _pointer_temp_path(paths: ToolboxPaths) -> Path:
    """Return the same-directory temporary pointer required by the contract."""
    return paths.current_pointer.with_name(paths.current_pointer.name + ".tmp")


def _remove_private_staging_dir(path: Path, generation_root: Path) -> None:
    """Remove only a builder-owned staging directory under the generation root."""
    try:
        resolved = path.resolve(strict=False)
        root = generation_root.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, ValueError):
        return
    if path.name.startswith(".") and ".staging-" in path.name:
        shutil.rmtree(path, ignore_errors=True)


def _receipt_payload(plan: GenerationPlan, security: Mapping[str, Any], paths: ToolboxPaths) -> dict[str, Any]:
    manifest_bytes = _json_bytes(plan.manifest)
    index_bytes = _json_bytes(plan.index)
    return {
        "schema_version": RECEIPT_SCHEMA,
        "receipt_id": f"receipt_{plan.generation_id}",
        "created_utc": _utc(),
        "generation_id": plan.generation_id,
        "parent_generation": plan.parent_generation,
        "parent_receipt": (
            _posix(paths.receipt_root / "receipts" / f"{plan.parent_generation}.json")
            if plan.parent_generation
            else None
        ),
        "lineage_tail": list(plan.lineage_tail),
        "selection_request": plan.selection_request,
        "selection_request_sha256": plan.selection_request_sha256,
        "manifest_sha256": _sha256_bytes(manifest_bytes),
        "function_index_sha256": _sha256_bytes(index_bytes),
        "module_hashes": {
            module.template.template_id: module.generated_sha256 for module in plan.modules
        },
        "security": dict(security),
        "source_root": "<source-template-root>",
        "generated_root": "<protected-generated-root>",
        "archive_path": _posix(paths.receipt_root / "receipts" / f"{plan.generation_id}.json"),
    }


def _pointer_payload(plan: GenerationPlan, generation_dir: Path, receipt: Mapping[str, Any]) -> dict[str, Any]:
    manifest_bytes = _json_bytes(plan.manifest)
    index_bytes = _json_bytes(plan.index)
    receipt_bytes = _json_bytes(receipt)
    return {
        "schema_version": POINTER_SCHEMA,
        "generation_id": plan.generation_id,
        "manifest_path": _posix(generation_dir / "generation_manifest.json"),
        "index_path": _posix(generation_dir / "function_index.json"),
        "receipt_path": _posix(generation_dir / "generation_receipt.json"),
        "manifest_sha256": _sha256_bytes(manifest_bytes),
        "index_sha256": _sha256_bytes(index_bytes),
        "receipt_sha256": _sha256_bytes(receipt_bytes),
        "input_sha256": plan.input_sha256,
        "updated_utc": _utc(),
    }


def _verify_generation_files(
    generation_dir: Path,
    *,
    expected_pointer: Mapping[str, Any] | None = None,
    expected_source_root: Path | None = None,
    expected_receipt_root: Path | None = None,
    expected_generation_id: str | None = None,
) -> dict[str, Any]:
    manifest_path = generation_dir / "generation_manifest.json"
    index_path = generation_dir / "function_index.json"
    receipt_path = generation_dir / "generation_receipt.json"
    manifest = _read_json(manifest_path)
    index = _read_json(index_path)
    receipt = _read_json(receipt_path)
    generation_id = manifest.get("generation_id")
    if manifest.get("schema_version") != GENERATION_SCHEMA or not isinstance(generation_id, str):
        raise GenerationVerificationError("generation_manifest_invalid")
    expected_directory_id = expected_generation_id or generation_dir.name
    if generation_id != expected_directory_id or not _GENERATION_RE.fullmatch(generation_id):
        raise GenerationVerificationError("generation_directory_mismatch")
    if receipt.get("schema_version") != RECEIPT_SCHEMA or receipt.get("generation_id") != generation_id:
        raise GenerationVerificationError("generation_receipt_invalid")
    if index.get("schema_version") != INDEX_SCHEMA or index.get("generation_id") != generation_id:
        raise GenerationVerificationError("generation_index_invalid")
    manifest_bytes = manifest_path.read_bytes()
    index_bytes = index_path.read_bytes()
    receipt_bytes = receipt_path.read_bytes()
    if receipt.get("manifest_sha256") != _sha256_bytes(manifest_bytes):
        raise GenerationVerificationError("manifest_receipt_hash_mismatch")
    if receipt.get("function_index_sha256") != _sha256_bytes(index_bytes):
        raise GenerationVerificationError("index_receipt_hash_mismatch")
    if manifest.get("function_index_sha256") != _sha256_bytes(index_bytes):
        raise GenerationVerificationError("manifest_index_hash_mismatch")
    parent_generation = manifest.get("parent_generation")
    if receipt.get("parent_generation") != parent_generation:
        raise GenerationVerificationError("receipt_parent_generation_mismatch")
    expected_parent_receipt = (
        (expected_receipt_root or (_repo_root() / "foundation" / "artifacts" / "auto" / "code_templates"))
        / "receipts"
        / f"{parent_generation}.json"
        if isinstance(parent_generation, str) and parent_generation
        else None
    )
    if expected_parent_receipt is None:
        if receipt.get("parent_receipt") is not None:
            raise GenerationVerificationError("receipt_parent_receipt_unexpected")
    else:
        if Path(str(receipt.get("parent_receipt") or "")).resolve(strict=False) != expected_parent_receipt.resolve(strict=False):
            raise GenerationVerificationError("receipt_parent_receipt_path_mismatch")
        if not expected_parent_receipt.is_file():
            raise GenerationVerificationError("receipt_parent_receipt_missing")
    selection_request = manifest.get("selection_request")
    selection_request_sha256 = manifest.get("selection_request_sha256")
    if selection_request is None:
        if selection_request_sha256 is not None or receipt.get("selection_request_sha256") is not None:
            raise GenerationVerificationError("selection_request_hash_present_without_request")
    else:
        _validate_normalized_selection_request(selection_request, manifest.get("modules") or [])
        actual_selection_hash = _selection_request_hash(selection_request)
        if selection_request_sha256 != actual_selection_hash:
            raise GenerationVerificationError("selection_request_hash_mismatch")
        if receipt.get("selection_request_sha256") != selection_request_sha256:
            raise GenerationVerificationError("receipt_selection_request_hash_mismatch")
    archive_raw = receipt.get("archive_path")
    if not isinstance(archive_raw, str) or not archive_raw:
        raise GenerationVerificationError("receipt_archive_path_missing")
    archive_path = Path(archive_raw)
    if expected_receipt_root is not None:
        expected_archive = expected_receipt_root / "receipts" / f"{generation_id}.json"
        if archive_path.resolve(strict=False) != expected_archive.resolve(strict=False):
            raise GenerationVerificationError("receipt_archive_path_mismatch")
    if not archive_path.is_file() or _sha256_bytes(archive_path.read_bytes()) != _sha256_bytes(receipt_bytes):
        raise GenerationVerificationError("receipt_archive_mismatch")
    if expected_pointer:
        for field, expected_path in (
            ("manifest_path", manifest_path),
            ("index_path", index_path),
            ("receipt_path", receipt_path),
        ):
            if Path(str(expected_pointer.get(field) or "")).resolve(strict=False) != expected_path.resolve(strict=False):
                raise GenerationVerificationError(f"pointer_{field}_mismatch")
        for key, value in (
            ("manifest_sha256", _sha256_bytes(manifest_bytes)),
            ("index_sha256", _sha256_bytes(index_bytes)),
            ("receipt_sha256", _sha256_bytes(receipt_bytes)),
        ):
            if expected_pointer.get(key) != value:
                raise GenerationVerificationError(f"pointer_{key}_mismatch")

    modules = manifest.get("modules")
    if not isinstance(modules, list):
        raise GenerationVerificationError("manifest_modules_invalid")
    source_root_raw = manifest.get("source_root")
    if not isinstance(source_root_raw, str) or not source_root_raw:
        raise GenerationVerificationError("manifest_source_root_invalid")
    source_root = expected_source_root if source_root_raw == "<source-template-root>" and expected_source_root is not None else Path(source_root_raw)
    if source_root_raw == "<source-template-root>" and expected_source_root is None:
        source_root = _repo_root() / "foundation" / "code_templates" / "source"
    if expected_source_root is not None:
        try:
            if source_root.resolve(strict=False) != expected_source_root.resolve(strict=False):
                raise GenerationVerificationError("manifest_source_root_mismatch")
        except OSError as exc:
            raise GenerationVerificationError(f"manifest_source_root_unresolvable:{exc}") from exc

    index_entries = index.get("entries")
    if not isinstance(index_entries, list):
        raise GenerationVerificationError("generation_index_entries_invalid")
    index_by_key: dict[tuple[str, str], Mapping[str, Any]] = {}
    for entry in index_entries:
        if not isinstance(entry, dict):
            raise GenerationVerificationError("generation_index_entry_invalid")
        key = (str(entry.get("template_id") or ""), str(entry.get("section") or ""))
        if key in index_by_key:
            raise GenerationVerificationError(f"generation_index_duplicate:{key[0]}:{key[1]}")
        index_by_key[key] = entry

    module_reports: list[dict[str, Any]] = []
    seen_module_ids: set[str] = set()
    for module in modules:
        if not isinstance(module, dict):
            raise GenerationVerificationError("manifest_module_invalid")
        template_id = str(module.get("template_id") or "")
        if not _ID_RE.fullmatch(template_id) or template_id in seen_module_ids:
            raise GenerationVerificationError(f"manifest_module_id_invalid:{template_id}")
        seen_module_ids.add(template_id)
        try:
            source_rel = _safe_relative(source_root, str(module.get("source_path") or ""), suffix=".py")
            generated_rel = _safe_relative(generation_dir, str(module.get("generated_path") or ""), suffix=".py")
        except TemplateContractError as exc:
            raise GenerationVerificationError(str(exc)) from exc
        source_path = source_root / source_rel
        generated_path = generation_dir / generated_rel
        if _is_reparse_point(source_path) or _is_reparse_point(generated_path):
            raise GenerationVerificationError(f"reparse_path:{template_id}")
        if not source_path.is_file() or not generated_path.is_file():
            raise GenerationVerificationError(f"module_file_missing:{template_id}")
        source_bytes = source_path.read_bytes()
        generated_bytes = generated_path.read_bytes()
        actual_source = _sha256_bytes(source_bytes)
        actual_generated = _sha256_bytes(generated_bytes)
        if actual_source != module.get("source_sha256"):
            raise GenerationVerificationError(f"source_hash_drift:{template_id}")
        if actual_generated != module.get("generated_sha256"):
            raise GenerationVerificationError(f"generated_hash_mismatch:{template_id}")

        try:
            source_lines = source_bytes.decode("utf-8").splitlines(keepends=True)
            generated_lines = generated_bytes.decode("utf-8").splitlines(keepends=True)
        except UnicodeDecodeError as exc:
            raise GenerationVerificationError(f"module_not_utf8:{template_id}") from exc

        sections = module.get("sections")
        if not isinstance(sections, list) or not sections:
            raise GenerationVerificationError(f"manifest_sections_invalid:{template_id}")
        expected_section_names = [
            "__imports__" if any(str(item.get("name") or "") == "__imports__" for item in sections if isinstance(item, dict)) else None,
            "VARIABLES",
            "main",
            *(str(name) for name in (module.get("submain_order") or [])),
        ]
        expected_section_names = [name for name in expected_section_names if name is not None]
        actual_section_names = [str(item.get("name") or "") for item in sections if isinstance(item, dict)]
        if actual_section_names != expected_section_names:
            raise GenerationVerificationError(f"manifest_section_order_invalid:{template_id}")
        module_keys: set[tuple[str, str]] = set()
        for section in sections:
            if not isinstance(section, dict):
                raise GenerationVerificationError(f"manifest_section_invalid:{template_id}")
            name = str(section.get("name") or "")
            key = (template_id, name)
            if key in module_keys:
                raise GenerationVerificationError(f"manifest_section_duplicate:{template_id}:{name}")
            module_keys.add(key)
            entry = index_by_key.get(key)
            if entry is None:
                raise GenerationVerificationError(f"index_section_missing:{template_id}:{name}")
            if entry.get("generation_id") != generation_id:
                raise GenerationVerificationError(f"index_generation_id_mismatch:{template_id}:{name}")
            if any(section.get(field) != entry.get(field) for field in (
                "source_start_line", "source_end_line", "generated_start_line", "generated_end_line",
                "source_sha256", "generated_sha256", "target_pillars", "submain_order", "decorated",
            )):
                raise GenerationVerificationError(f"index_section_metadata_mismatch:{template_id}:{name}")
            try:
                source_start = int(section["source_start_line"])
                source_end = int(section["source_end_line"])
                generated_start = int(section["generated_start_line"])
                generated_end = int(section["generated_end_line"])
            except (KeyError, TypeError, ValueError) as exc:
                raise GenerationVerificationError(f"section_lines_invalid:{template_id}:{name}") from exc
            if not (1 <= source_start <= source_end <= len(source_lines)):
                raise GenerationVerificationError(f"source_section_lines_invalid:{template_id}:{name}")
            if not (1 <= generated_start <= generated_end <= len(generated_lines)):
                raise GenerationVerificationError(f"generated_section_lines_invalid:{template_id}:{name}")
            source_span = "".join(source_lines[source_start - 1 : source_end]).encode("utf-8")
            generated_span = "".join(generated_lines[generated_start - 1 : generated_end]).encode("utf-8")
            if source_span != generated_span:
                raise GenerationVerificationError(f"section_byte_mismatch:{template_id}:{name}")
            if _sha256_bytes(source_span) != section.get("source_sha256"):
                raise GenerationVerificationError(f"source_section_hash_mismatch:{template_id}:{name}")
            if _sha256_bytes(generated_span) != section.get("generated_sha256"):
                raise GenerationVerificationError(f"generated_section_hash_mismatch:{template_id}:{name}")

        if module_keys != {(template_id, str(entry.get("section") or "")) for entry in index_entries if entry.get("template_id") == template_id}:
            raise GenerationVerificationError(f"index_section_set_mismatch:{template_id}")
        module_reports.append(
            {
                "template_id": template_id,
                "source_sha256": actual_source,
                "generated_sha256": actual_generated,
                "ok": True,
            }
        )
    index_template_ids = {str(entry.get("template_id") or "") for entry in index_entries}
    if index_template_ids != seen_module_ids:
        raise GenerationVerificationError("generation_index_module_set_mismatch")
    return {
        "ok": True,
        "state": "PASS",
        "generation_id": generation_id,
        "module_count": len(module_reports),
        "modules": module_reports,
        "manifest_sha256": _sha256_bytes(manifest_bytes),
        "index_sha256": _sha256_bytes(index_bytes),
        "receipt_sha256": _sha256_bytes(receipt_bytes),
    }


def verify_generation(paths: ToolboxPaths, generation_id: str | None = None) -> dict[str, Any]:
    pointer = _load_current_pointer(paths)
    target = generation_id or (pointer or {}).get("generation_id")
    if not isinstance(target, str) or not _GENERATION_RE.fullmatch(target):
        return {"ok": False, "state": "EMPTY", "reason": "no_active_generation"}
    try:
        generation_dir = paths.generation_root / target
        report = _verify_generation_files(
            generation_dir,
            expected_pointer=pointer if generation_id is None else None,
            expected_source_root=paths.source_root,
            expected_receipt_root=paths.receipt_root,
        )
        return report
    except (GenerationVerificationError, OSError) as exc:
        return {"ok": False, "state": "HOLD", "generation_id": target, "reason": str(exc)}


def index_templates(paths: ToolboxPaths, *, write: bool = True) -> dict[str, Any]:
    _validate_toolbox_paths(paths)
    rows = _validate_registry(paths)
    templates = tuple(parse_template(row, paths) for row in rows)
    index = _source_index(templates)
    index["registry_sha256"] = _sha256_bytes(paths.registry_path.read_bytes())
    index["source_root"] = _posix(paths.source_root)
    content = _json_bytes(index)
    output = _source_index_path(paths)
    receipt_output = _source_index_receipt_path(paths)
    write_result: dict[str, Any] | None = None
    receipt_write_result: dict[str, Any] | None = None
    receipt = _source_index_receipt_payload(paths, index, content)
    if write:
        try:
            write_result = RustSecurityAdapter().write_json(output, content)
            if write_result.get("ok"):
                receipt_write_result = RustSecurityAdapter().write_json(receipt_output, _json_bytes(receipt))
        except Exception as exc:
            write_result = {"ok": False, "error": f"index_write_failed:{exc}"}
    write_ok = bool(write_result and write_result.get("ok")) and bool(
        receipt_write_result and receipt_write_result.get("ok")
    ) if write else True
    return {
        "ok": write_ok,
        "state": "PASS" if write_ok else "HOLD",
        "template_count": len(templates),
        "index_path": _posix(output),
        "index_sha256": _sha256_bytes(content),
        "write": write_result,
        "index_receipt_path": _posix(receipt_output),
        "index_receipt": receipt,
        "index_receipt_write": receipt_write_result,
        "index": index,
    }


def _inventory_function_rows(path: Path, *, repo_root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Read-only AST inventory for existing AIOS code; never imports the file."""
    source_bytes = _read_bytes(path)
    try:
        source_text = source_bytes.decode("utf-8")
        tree = ast.parse(source_text, filename=str(path), type_comments=True)
    except (UnicodeDecodeError, SyntaxError) as exc:
        return (
            {
                "path": _posix(path.relative_to(repo_root)),
                "ok": False,
                "source_sha256": _sha256_bytes(source_bytes),
                "error": f"parse_failed:{exc}",
                "functions": [],
            },
            [],
        )
    lines = tuple(source_text.splitlines(keepends=True))
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    def qualname(node: ast.AST) -> str:
        names: list[str] = []
        cursor: ast.AST | None = node
        while cursor is not None:
            if isinstance(cursor, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.append(cursor.name)
            cursor = parents.get(cursor)
        return ".".join(reversed(names))

    function_rows: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        start, decorated = _node_start(node, lines)
        positional = [*node.args.posonlyargs, *node.args.args]
        parameter_names = [argument.arg for argument in positional]
        module_level = isinstance(parents.get(node), ast.Module)
        compatible = (
            isinstance(node, ast.FunctionDef)
            and module_level
            and parameter_names == ["context", "variables"]
            and not node.args.defaults
            and not node.args.kw_defaults
            and node.args.vararg is None
            and node.args.kwarg is None
            and not node.args.kwonlyargs
            and node.name == "main"
        )
        if isinstance(node, ast.FunctionDef) and module_level and node.name.startswith("sub_main_"):
            compatible = (
                parameter_names == ["context", "variables"]
                and not node.args.defaults
                and not node.args.kw_defaults
                and node.args.vararg is None
                and node.args.kwarg is None
                and not node.args.kwonlyargs
            )
        unsafe_calls = sorted(
            {
                _call_name(call)
                for call in ast.walk(node)
                if isinstance(call, ast.Call)
                and (
                    _call_name(call) in DENIED_CALL_NAMES
                    or _root_name(_call_name(call)) in DENIED_IMPORT_ROOTS
                )
            }
        )
        function_rows.append(
            {
                "name": node.name,
                "qualified_name": qualname(node),
                "kind": "main" if node.name == "main" else "submain" if node.name.startswith("sub_main_") else "helper",
                "scope": "module" if module_level else "nested",
                "async": isinstance(node, ast.AsyncFunctionDef),
                "decorated": decorated,
                "source_start_line": start,
                "source_end_line": _node_end(node),
                "parameters": parameter_names,
                "template_contract_candidate": compatible and not unsafe_calls,
                "unsafe_calls": unsafe_calls,
            }
        )
    function_rows.sort(key=lambda row: (int(row["source_start_line"]), int(row["source_end_line"]), str(row["qualified_name"])))
    top_level_effects = [
        type(node).__name__
        for node in tree.body
        if not isinstance(node, (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    return (
        {
            "path": _posix(path.relative_to(repo_root)),
            "ok": True,
            "source_sha256": _sha256_bytes(source_bytes),
            "source_line_count": len(lines),
            "top_level_effects": top_level_effects,
            "function_count": len(function_rows),
            "functions": function_rows,
        },
        function_rows,
    )


def inventory_aios_functions(paths: ToolboxPaths | None = None) -> dict[str, Any]:
    """Expose existing AIOS functions as read-only authoring candidates."""
    paths = paths or ToolboxPaths.default()
    foundation = paths.repo_root / "foundation"
    requested = [foundation / name for name in ("rid_main.py", "auto_main.py", "uml_main.py")]
    lib_root = foundation / "lib"
    if lib_root.is_dir():
        requested.extend(sorted(lib_root.rglob("*.py")))
    files: list[Path] = []
    seen: set[str] = set()
    for path in requested:
        key = _posix(path)
        if key in seen or not path.is_file():
            continue
        seen.add(key)
        if _is_reparse_point(path):
            return {"ok": False, "state": "HOLD", "reason": f"reparse_path:{path}"}
        files.append(path)

    reports: list[dict[str, Any]] = []
    function_count = 0
    compatible_count = 0
    for path in files:
        report, rows = _inventory_function_rows(path, repo_root=paths.repo_root)
        reports.append(report)
        function_count += len(rows)
        compatible_count += sum(1 for row in rows if row.get("template_contract_candidate"))
    reports.sort(key=lambda row: str(row["path"]))
    pillar_map = {"rid_main.py": "rid", "auto_main.py": "auto", "uml_main.py": "uml"}
    return {
        "ok": True,
        "state": "PASS",
        "schema_version": "viv_aios_function_inventory_v1",
        "read_only": True,
        "files_scanned": len(reports),
        "function_count": function_count,
        "template_contract_candidate_count": compatible_count,
        "pillar_entrypoints": pillar_map,
        "files": reports,
    }


def token_cost_report(
    paths: ToolboxPaths,
    selection_request: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare code-emission tokens with a structured toolbox request estimate."""
    try:
        plan = plan_generation(paths, selection_request)
        generated_text = "".join(module.generated_text for module in plan.modules)
        request = plan.selection_request or {
            "schema_version": SELECTION_REQUEST_SCHEMA,
            "templates": [
                {
                    "template_id": module.template.template_id,
                    "target_pillars": sorted(module.template.targets),
                    "submain_order": list(module.template.submain_order),
                }
                for module in plan.modules
            ],
        }
        request_text = _stable_json(request)
        code_chars = len(generated_text)
        code_bytes = len(generated_text.encode("utf-8"))
        code_tokens = _estimated_tokens(generated_text)
        request_tokens = _estimated_tokens(request_text)
        template_context_tokens = _estimated_tokens("".join(template.source_text for template in plan.templates))
        saved = max(0, code_tokens - request_tokens)
        break_even_builds = (
            math.ceil(template_context_tokens / saved)
            if saved > 0 and template_context_tokens > 0
            else None
        )
        amortized: list[dict[str, int]] = []
        for build_count in (1, 10, 100):
            ordinary_total = code_tokens * build_count
            toolbox_total = template_context_tokens + request_tokens * build_count
            amortized.append(
                {
                    "builds": build_count,
                    "ordinary_tokens": ordinary_total,
                    "toolbox_tokens_including_one_time_template_context": toolbox_total,
                    "saved_tokens": ordinary_total - toolbox_total,
                }
            )
        return {
            "ok": True,
            "state": "PASS",
            "model_token_cost_scope": "ordinary_generated_code_vs_structured_tool_request",
            "estimate_method": "ceil(utf8_text_characters/4); replace with the active model tokenizer for billing-grade counts",
            "ordinary_code": {
                "characters": code_chars,
                "bytes": code_bytes,
                "estimated_output_tokens": code_tokens,
            },
            "tool_request": {
                "characters": len(request_text),
                "bytes": len(request_text.encode("utf-8")),
                "estimated_tokens": request_tokens,
                "payload": request,
            },
            "one_time_template_context": {
                "characters": sum(len(template.source_text) for template in plan.templates),
                "estimated_tokens": template_context_tokens,
                "scope": "template comprehension or first-use context; amortize across repeated selections",
            },
            "estimated_saved_tokens": saved,
            "estimated_reduction_ratio": round(saved / code_tokens, 6) if code_tokens else 0.0,
            "steady_state_break_even_builds": break_even_builds,
            "amortized_examples": amortized,
            "code_bytes_sent_to_model": 0,
            "caveat": "This excludes one-time template comprehension, status responses, tool-schema tokens, explanations, and tokenizer-specific billing behavior.",
        }
    except (TemplateContractError, GenerationVerificationError, OSError) as exc:
        return {"ok": False, "state": "HOLD", "reason": str(exc)}


def build_dry_run(
    paths: ToolboxPaths,
    *,
    security: SecurityAdapter | None = None,
    selection_request: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        plan = plan_generation(paths, selection_request)
        adapter = security or RustSecurityAdapter()
        security_report = adapter.probe(plan, paths)
        dry_receipt = _redact_protected_paths(_receipt_payload(plan, security_report, paths))
        dry_receipt["receipt_id"] = (
            f"dry_{plan.generation_id}_"
            f"{_sha256_text(f'{_utc()}:{os.getpid()}:{time.time_ns()}')[:16]}"
        )
        dry_receipt["dry_run"] = True
        dry_receipt["generated_files_created"] = False
        dry_receipt["active_pointer_changed"] = False
        dry_receipt_path = paths.receipt_root / f"{dry_receipt['receipt_id']}.json"
        dry_receipt_result = adapter.write_json(dry_receipt_path, _json_bytes(dry_receipt))
        return {
            "ok": True,
            "state": "PASS" if security_report.get("ok") else "HOLD_SECURITY",
            "dry_run": True,
            "generation_id": plan.generation_id,
            "input_sha256": plan.input_sha256,
            "parent_generation": plan.parent_generation,
            "lineage_tail": list(plan.lineage_tail),
            "selection_request": plan.selection_request,
            "selection_request_sha256": plan.selection_request_sha256,
            "modules": [
                {
                    "template_id": module.template.template_id,
                    "generated_path": module.generated_rel,
                    "generated_sha256": module.generated_sha256,
                    "bytes": len(module.generated_text.encode("utf-8")),
                    "targets": list(module.template.targets),
                }
                for module in plan.modules
            ],
            "security": security_report,
            "token_cost": token_cost_report(paths, selection_request),
            "receipt": {
                "path": _posix(dry_receipt_path),
                "write": dry_receipt_result,
                "written": bool(dry_receipt_result.get("ok")),
            },
            "writes_performed": False,
        }
    except (TemplateContractError, GenerationVerificationError, OSError) as exc:
        return {"ok": False, "state": "HOLD", "dry_run": True, "reason": str(exc), "writes_performed": False}


def _file_sha256_or_none(path: Path) -> str | None:
    try:
        return _sha256_bytes(path.read_bytes()) if path.is_file() else None
    except OSError:
        return None


def _self_test_protected_state(paths: ToolboxPaths) -> dict[str, Any]:
    """Capture the small protected surface that an isolated self-test must not change."""

    current_task_path = paths.repo_root / "foundation" / "artifacts" / "auto" / "agentic" / "CURRENT_TASK.json"
    current_task: dict[str, Any] = {}
    try:
        value = json.loads(current_task_path.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            current_task = value
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        current_task = {}
    heads = current_task.get("authoritative_heads") if isinstance(current_task, dict) else {}
    training = heads.get("training") if isinstance(heads, dict) else {}
    seed = current_task.get("seed_lineage") if isinstance(current_task, dict) else {}
    if not isinstance(training, dict):
        training = {}
    if not isinstance(seed, dict):
        seed = {}

    generation_ids: list[str] = []
    try:
        if paths.generation_root.is_dir():
            generation_ids = sorted(
                child.name
                for child in paths.generation_root.iterdir()
                if child.is_dir() and _GENERATION_RE.fullmatch(child.name)
            )
    except OSError:
        generation_ids = ["<unreadable>"]

    protected_mains = {
        name: _file_sha256_or_none(paths.repo_root / "foundation" / name)
        for name in ("rid_main.py", "auto_main.py", "uml_main.py")
    }
    checkpoint = paths.repo_root / "foundation" / "models" / "Training" / "runs" / "viv_slm" / "v154_autonomous_owner" / "trial_0005" / "candidate_checkpoint.pt"
    rust: dict[str, Any]
    try:
        _, integrity_status, security_imports = RustSecurityAdapter()._imports()
        rust_available, _ = security_imports
        rust = {
            "rust_available": bool(rust_available()),
            "integrity": dict(integrity_status()),
        }
    except Exception as exc:
        rust = {"ok": False, "reason": f"security_status_unavailable:{exc}"}
    return {
        "active_pointer": {
            "exists": paths.current_pointer.is_file(),
            "sha256": _file_sha256_or_none(paths.current_pointer),
        },
        "production_generation_ids": generation_ids,
        "registry_sha256": _file_sha256_or_none(paths.registry_path),
        "protected_main_sha256": protected_mains,
        "seed_checkpoint_sha256": _file_sha256_or_none(checkpoint),
        "authoritative_training": {
            "status": training.get("status"),
            "worker_pid": (training.get("worker") or {}).get("pid") if isinstance(training.get("worker"), dict) else None,
            "worker_state": (training.get("worker") or {}).get("state") if isinstance(training.get("worker"), dict) else None,
            "training_authority_open": training.get("training_authority_open"),
            "promotion_authority_open": training.get("promotion_authority_open"),
            "deployment_authority_open": training.get("deployment_authority_open"),
        },
        "seed_lineage": {
            "head_name": seed.get("head_name"),
            "head_generation": seed.get("head_generation"),
            "replacement_gate": seed.get("replacement_gate"),
            "integrity": seed.get("integrity"),
        },
        "live_model_changed": (current_task.get("containment") or {}).get("live_model_changed") if isinstance(current_task.get("containment"), dict) else None,
        "rust": rust,
    }


def _validate_self_test_receipt_dir(paths: ToolboxPaths, receipt_dir: Path) -> Path:
    receipt_dir = receipt_dir.resolve(strict=False)
    if receipt_dir.exists() and _is_reparse_point(receipt_dir):
        raise TemplateContractError("self_test_receipt_dir_reparse_path")
    source_root = paths.source_root.resolve(strict=False)
    generation_root = paths.generation_root.resolve(strict=False)
    pointer = paths.current_pointer.resolve(strict=False)
    if receipt_dir == source_root or source_root in receipt_dir.parents:
        raise TemplateContractError("self_test_receipt_dir_inside_source_root")
    if receipt_dir == generation_root or generation_root in receipt_dir.parents:
        raise TemplateContractError("self_test_receipt_dir_inside_generation_root")
    if receipt_dir == pointer or pointer in receipt_dir.parents:
        raise TemplateContractError("self_test_receipt_dir_overlaps_pointer")
    return receipt_dir


def _self_test_selection_request(paths: ToolboxPaths, template_id: str) -> dict[str, Any]:
    rows = _validate_registry(paths)
    row = next((item for item in rows if item.get("template_id") == template_id), None)
    if row is None:
        raise TemplateContractError(f"self_test_unknown_template:{template_id}")
    return {
        "schema_version": SELECTION_REQUEST_SCHEMA,
        "templates": [
            {
                "template_id": template_id,
                "target_pillars": list(row["targets"]),
                "submain_order": list(row["submain_order"]),
            }
        ],
    }


def _self_test_call_trace(
    generated_path: Path,
    function_names: set[str],
) -> tuple[Any, list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []
    expected_filename = str(generated_path.resolve(strict=False))

    def trace(frame: Any, event: str, arg: Any) -> Any:
        if event == "call" and str(frame.f_code.co_filename) == expected_filename and frame.f_code.co_name in function_names:
            variables = frame.f_locals.get("variables")
            if isinstance(variables, Mapping):
                observed: Any = copy.deepcopy(dict(variables))
            else:
                observed = {"__invalid__": repr(variables)}
            calls.append({"name": frame.f_code.co_name, "variables": observed})
        return trace

    return trace, calls


def _self_test_import_without_execution(
    generated_path: Path,
    template_id: str,
    function_names: set[str],
) -> tuple[Any, dict[str, Any]]:
    """Import one generated module while tracing calls to main/submains."""

    module_name = f"_viv_self_test_{template_id.replace('.', '_')}_{os.getpid()}"
    trace, calls = _self_test_call_trace(generated_path, function_names)
    prior_trace = sys.gettrace()
    module: Any = None
    try:
        spec = importlib.util.spec_from_file_location(module_name, generated_path)
        if spec is None or spec.loader is None:
            raise GenerationVerificationError("self_test_module_spec_unavailable")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        sys.settrace(trace)
        spec.loader.exec_module(module)
    finally:
        sys.settrace(prior_trace)
        sys.modules.pop(module_name, None)
    if calls:
        raise GenerationVerificationError(f"self_test_import_executed_template_function:{calls}")
    variables = getattr(module, "VARIABLES", None)
    if not isinstance(variables, Mapping):
        raise GenerationVerificationError("self_test_generated_variables_invalid")
    return module, {
        "ok": True,
        "executed_template_functions": calls,
        "declared_variable_keys": sorted(str(key) for key in variables),
    }


def _self_test_execute(
    runtime: Any,
    runtime_paths: Any,
    generated_path: Path,
    template_id: str,
    pillar: str,
    context: Mapping[str, Any],
    overrides: Mapping[str, Any] | None,
) -> tuple[Any, list[dict[str, Any]]]:
    trace, calls = _self_test_call_trace(
        generated_path,
        {"main", *(str(name) for name in runtime_paths.submain_order)},
    )
    prior_trace = sys.gettrace()
    try:
        sys.settrace(trace)
        result = runtime.execute_template(
            template_id,
            pillar,
            context,
            overrides,
            _paths=runtime_paths.runtime_paths,
        )
    finally:
        sys.settrace(prior_trace)
    return result, calls


def _self_test_result_hash(result: Any) -> str:
    return _sha256_text(json.dumps(result, sort_keys=True, separators=(",", ":"), default=repr))


def _self_test_override(declared: Mapping[str, Any], template_id: str) -> dict[str, Any]:
    if "message" in declared:
        return {"message": "self-test-override"}
    if not declared:
        return {}
    key = sorted(str(name) for name in declared)[0]
    value = declared[key]
    if isinstance(value, bool):
        changed: Any = not value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        changed = value + 1
    elif isinstance(value, str):
        changed = f"{value}-override"
    else:
        changed = copy.deepcopy(value)
    return {key: changed}


def _self_test_security_ids(value: Any) -> list[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).casefold() in {"request_id", "decision_id", "receipt_id"} and isinstance(item, str):
                found.add(item)
            found.update(_self_test_security_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_self_test_security_ids(item))
    return sorted(found)


def _self_test_expected_failure(name: str, operation: Any) -> dict[str, Any]:
    try:
        result = operation()
    except Exception as exc:
        return {"name": name, "passed": True, "error": str(exc)}
    if isinstance(result, Mapping) and not bool(result.get("ok")):
        return {"name": name, "passed": True, "result": dict(result)}
    return {"name": name, "passed": False, "result": result}


def _self_test_one_run(
    paths: ToolboxPaths,
    selection_request: Mapping[str, Any],
    template_id: str,
    pillar: str,
    run_number: int,
) -> dict[str, Any]:
    """Run one complete assembly in a private temporary root."""

    import py_compile as _py_compile

    with tempfile.TemporaryDirectory(prefix=f"viv-template-self-test-{run_number}-") as tmp:
        isolated_root = Path(tmp)
        isolated_paths = ToolboxPaths(
            repo_root=paths.repo_root,
            source_root=paths.source_root,
            registry_path=paths.registry_path,
            toolbox_manifest=paths.toolbox_manifest,
            generation_root=isolated_root / "generations",
            current_pointer=isolated_root / "template_current.json",
            receipt_root=isolated_root / "receipts",
        )
        plan = plan_generation(isolated_paths, selection_request)
        # Probe the real production destination as a hypothetical write, then
        # assemble only through the local test adapter in the private root.
        rust_security = RustSecurityAdapter().probe(plan, paths)
        local_publish = publish_generation(
            isolated_paths,
            security=LocalTestSecurityAdapter(),
            selection_request=selection_request,
        )
        if not local_publish.get("ok"):
            raise GenerationVerificationError(f"self_test_isolated_publish_failed:{local_publish}")
        verification = verify_generation(isolated_paths)
        if not verification.get("ok"):
            raise GenerationVerificationError(f"self_test_isolated_verify_failed:{verification}")
        module = plan.modules[0]
        generated_path = isolated_paths.generation_root / plan.generation_id / module.generated_rel
        generated_bytes = generated_path.read_bytes()
        source_bytes = module.template.source_path.read_bytes()
        function_names = {"main", *(section.name for section in module.template.submains)}
        compiled = False
        compile_error: str | None = None
        try:
            _py_compile.compile(str(generated_path), doraise=True)
            compiled = True
        except Exception as exc:
            compile_error = str(exc)

        imported_module, import_report = _self_test_import_without_execution(
            generated_path,
            template_id,
            function_names,
        )
        declared_variables = copy.deepcopy(dict(imported_module.VARIABLES))
        override_values = _self_test_override(declared_variables, template_id)

        foundation = paths.repo_root / "foundation"
        if str(foundation) not in sys.path:
            sys.path.insert(0, str(foundation))
        from lib import code_template_runtime as runtime  # type: ignore

        runtime_paths = runtime._RuntimePaths(
            root=paths.repo_root,
            source_root=paths.source_root,
            generation_root=isolated_paths.generation_root,
            current_pointer=isolated_paths.current_pointer,
            receipt_root=isolated_paths.receipt_root,
        )
        runtime_snapshot = runtime._snapshot(runtime_paths)
        discoveries = {
            target: runtime.discover_templates(target, _paths=runtime_paths)
            for target in ("rid", "auto", "uml")
        }
        context = {"self_test": True}
        runtime_proxy = type(
            "_RuntimeSelfTestProxy",
            (),
            {"runtime_paths": runtime_paths, "submain_order": module.template.submain_order},
        )()
        baseline_result, baseline_calls = _self_test_execute(
            runtime,
            runtime_proxy,
            generated_path,
            template_id,
            pillar,
            context,
            None,
        )
        override_result, override_calls = _self_test_execute(
            runtime,
            runtime_proxy,
            generated_path,
            template_id,
            pillar,
            context,
            override_values,
        )

        expected_baseline_calls = [*module.template.submain_order, "main"]
        expected_override_calls = [*module.template.submain_order, "main"]
        if [str(row["name"]) for row in baseline_calls] != expected_baseline_calls:
            raise GenerationVerificationError(f"self_test_baseline_call_order_invalid:{baseline_calls}")
        if [str(row["name"]) for row in override_calls] != expected_override_calls:
            raise GenerationVerificationError(f"self_test_override_call_order_invalid:{override_calls}")
        baseline_main = next(row for row in baseline_calls if row["name"] == "main")
        override_main = next(row for row in override_calls if row["name"] == "main")
        if baseline_main["variables"] != declared_variables:
            raise GenerationVerificationError("self_test_declared_variables_changed_without_override")
        expected_override_variables = dict(declared_variables)
        expected_override_variables.update(override_values)
        if override_main["variables"] != expected_override_variables:
            raise GenerationVerificationError("self_test_runtime_override_not_applied_as_data")

        negative_results = [
            _self_test_expected_failure(
                "undeclared_variable_override",
                lambda: runtime.execute_template(
                    template_id,
                    pillar,
                    context,
                    {"__self_test_undeclared__": True},
                    _paths=runtime_paths,
                ),
            ),
            _self_test_expected_failure(
                "unknown_template_selection",
                lambda: _normalize_selection_request(
                    _validate_registry(paths),
                    {
                        "schema_version": SELECTION_REQUEST_SCHEMA,
                        "templates": [{"template_id": "fixture.unknown", "target_pillars": [pillar], "submain_order": []}],
                    },
                ),
            ),
            _self_test_expected_failure(
                "raw_source_selection_field",
                lambda: _normalize_selection_request(
                    _validate_registry(paths),
                    {
                        "schema_version": SELECTION_REQUEST_SCHEMA,
                        "templates": [{"template_id": template_id, "target_pillars": [pillar], "submain_order": list(module.template.submain_order), "source": "not_accepted.py"}],
                    },
                ),
            ),
        ]

        generation_dir = isolated_paths.generation_root / plan.generation_id
        manifest_path = generation_dir / "generation_manifest.json"
        manifest_bytes = manifest_path.read_bytes()
        manifest_path.write_bytes(manifest_bytes + b" ")
        negative_results.append(
            _self_test_expected_failure("manifest_tamper", lambda: verify_generation(isolated_paths))
        )
        manifest_path.write_bytes(manifest_bytes)

        generated_original = generated_path.read_bytes()
        generated_path.write_bytes(generated_original + b"\n# self-test tamper\n")
        negative_results.append(
            _self_test_expected_failure("generated_source_tamper", lambda: verify_generation(isolated_paths))
        )
        generated_path.write_bytes(generated_original)

        pointer_bytes = isolated_paths.current_pointer.read_bytes()
        pointer_payload = json.loads(pointer_bytes.decode("utf-8"))
        pointer_payload["receipt_sha256"] = _ZERO_SHA256
        isolated_paths.current_pointer.write_bytes(_json_bytes(pointer_payload))
        negative_results.append(
            _self_test_expected_failure("pointer_tamper", lambda: verify_generation(isolated_paths))
        )
        isolated_paths.current_pointer.write_bytes(pointer_bytes)
        restored_verification = verify_generation(isolated_paths)
        if not restored_verification.get("ok"):
            raise GenerationVerificationError(f"self_test_restore_verification_failed:{restored_verification}")

        discovery_ids = {
            target: [str(item["template_id"]) for item in values]
            for target, values in discoveries.items()
        }
        signature = {
            "generation_id": plan.generation_id,
            "input_sha256": plan.input_sha256,
            "source_sha256": module.template.source_sha256,
            "generated_sha256": module.generated_sha256,
            "manifest_sha256": verification.get("manifest_sha256"),
            "index_sha256": verification.get("index_sha256"),
            "full_source_byte_equal": source_bytes == generated_bytes,
            "compiled": compiled,
            "import_without_execution": bool(import_report.get("ok")) and not import_report.get("executed_template_functions"),
            "discovery_ids": discovery_ids,
            "baseline_call_order": [str(row["name"]) for row in baseline_calls],
            "override_call_order": [str(row["name"]) for row in override_calls],
            "baseline_main_variables": baseline_main["variables"],
            "override_main_variables": override_main["variables"],
            "baseline_result_sha256": _self_test_result_hash(baseline_result),
            "override_result_sha256": _self_test_result_hash(override_result),
            "negative_names": [str(row["name"]) for row in negative_results if row.get("passed")],
        }
        return {
            "run_number": run_number,
            "generation_id": plan.generation_id,
            "input_sha256": plan.input_sha256,
            "security": rust_security,
            "isolated_generation": {
                "generated_files_created": True,
                "active_pointer_changed": True,
                "generation_id": plan.generation_id,
                "manifest_sha256": verification.get("manifest_sha256"),
                "index_sha256": verification.get("index_sha256"),
                "receipt_sha256": verification.get("receipt_sha256"),
                "pointer_sha256": _file_sha256_or_none(isolated_paths.current_pointer),
            },
            "source": {
                "path": module.template.source_rel,
                "sha256": module.template.source_sha256,
                "source_index_sha256": _file_sha256_or_none(_source_index_path(paths)),
                "source_index_receipt_sha256": _file_sha256_or_none(_source_index_receipt_path(paths)),
            },
            "generated_source_sha256": module.generated_sha256,
            "compile": {"ok": compiled, "error": compile_error},
            "import_before_execution": import_report,
            "runtime_snapshot": runtime_snapshot.report,
            "discoveries": discoveries,
            "declared_variable_keys": sorted(str(key) for key in declared_variables),
            "declared_variables": declared_variables,
            "runtime_variable_overrides": override_values,
            "submain_count": len(module.template.submains),
            "submain_order": list(module.template.submain_order),
            "baseline_execution": {
                "result_sha256": _self_test_result_hash(baseline_result),
                "calls": baseline_calls,
            },
            "override_execution": {
                "result_sha256": _self_test_result_hash(override_result),
                "calls": override_calls,
            },
            "negative_tests": negative_results,
            "signature": signature,
        }


def template_self_test(
    paths: ToolboxPaths,
    *,
    template_id: str = "fixture.echo",
    pillar: str = "auto",
    repeats: int = 10,
    isolated: bool = False,
    no_publish: bool = False,
    receipt_dir: Path | None = None,
) -> dict[str, Any]:
    """Run the CPU/toolbox acceptance loop without touching production generation state."""

    run_id = f"self_test_{_sha256_text(f'{_utc()}:{os.getpid()}:{time.time_ns()}')[:20]}"
    before = _self_test_protected_state(paths)
    receipt_root = _validate_self_test_receipt_dir(paths, receipt_dir or (paths.receipt_root / "self_tests"))
    request: dict[str, Any] | None = None
    runs: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        if not isolated or not no_publish:
            raise TemplateContractError("self_test_requires_isolated_and_no_publish")
        if not isinstance(repeats, int) or repeats <= 0:
            raise TemplateContractError("self_test_repeats_must_be_positive")
        if pillar not in TARGET_PILLARS:
            raise TemplateContractError(f"self_test_unknown_pillar:{pillar}")
        request = _self_test_selection_request(paths, template_id)
        for run_number in range(1, repeats + 1):
            runs.append(_self_test_one_run(paths, request, template_id, pillar, run_number))
    except Exception as exc:
        errors.append(str(exc))
    after = _self_test_protected_state(paths)
    protected_unchanged = before == after
    signatures = [row.get("signature") for row in runs]
    deterministic = bool(signatures) and all(signature == signatures[0] for signature in signatures)
    all_negative_passed = all(
        bool(item.get("passed"))
        for row in runs
        for item in row.get("negative_tests", [])
    )
    all_runs_passed = len(runs) == repeats and not errors and all(
        bool(row.get("compile", {}).get("ok"))
        and bool(row.get("import_before_execution", {}).get("ok"))
        and bool(row.get("runtime_snapshot", {}).get("ok"))
        and all_negative_passed
        for row in runs
    )
    security_reports = [row.get("security") for row in runs if isinstance(row.get("security"), Mapping)]
    security_denied = bool(security_reports) and all(not bool(report.get("ok")) for report in security_reports)
    rust_security = security_reports[0] if security_reports else None
    normalized = {
        "template_id": template_id,
        "pillar": pillar,
        "selection_request": request,
        "repeated_signatures": signatures,
        "deterministic": deterministic,
    }
    normalized_digest = _sha256_text(_stable_json(normalized))
    expected_hold = all_runs_passed and protected_unchanged and deterministic and security_denied
    if expected_hold:
        final_state = "PASS_WITH_EXPECTED_SECURITY_HOLD"
    elif all_runs_passed and protected_unchanged and deterministic and security_reports and any(bool(report.get("ok")) for report in security_reports):
        final_state = "HOLD_UNEXPECTED_SECURITY_ALLOW"
    else:
        final_state = "FAIL"
    first_run = runs[0] if runs else {}
    receipt: dict[str, Any] = {
        "schema_version": SELF_TEST_RECEIPT_SCHEMA,
        "run_id": run_id,
        "created_utc": _utc(),
        "template_id": template_id,
        "pillar": pillar,
        "selection_request": request,
        "selection_request_sha256": _selection_request_hash(request),
        "runtime_variable_overrides": first_run.get("runtime_variable_overrides"),
        "source": first_run.get("source"),
        "rust_security": {
            "decision": rust_security,
            "rule": rust_security.get("reason") if isinstance(rust_security, Mapping) else None,
            "reason": rust_security.get("reason") if isinstance(rust_security, Mapping) else None,
            "integrity": rust_security.get("integrity") if isinstance(rust_security, Mapping) else None,
            "decision_ids": _self_test_security_ids(rust_security),
        },
        "generated_files_created": False,
        "active_pointer_changed": False,
        "isolated_generation": first_run.get("isolated_generation"),
        "generated_source_sha256": first_run.get("generated_source_sha256"),
        "compile": first_run.get("compile"),
        "import_before_execution": first_run.get("import_before_execution"),
        "execution": {
            "baseline": first_run.get("baseline_execution"),
            "runtime_override": first_run.get("override_execution"),
            "declared_variable_keys": first_run.get("declared_variable_keys"),
        },
        "declared_variable_keys": first_run.get("declared_variable_keys"),
        "submain_count": first_run.get("submain_count"),
        "submain_order": first_run.get("submain_order"),
        "negative_tests": first_run.get("negative_tests", []),
        "repeated_run_count": repeats,
        "repeated_runs": [
            {
                "run_number": row.get("run_number"),
                "generation_id": row.get("generation_id"),
                "signature": row.get("signature"),
                "security_denied": not bool((row.get("security") or {}).get("ok")),
            }
            for row in runs
        ],
        "normalized_deterministic_comparison_digest": normalized_digest,
        "deterministic_comparison": {
            "volatile_fields_excluded": ["created_utc", "run_id", "temporary_paths", "request_id", "decision_id"],
            "all_signatures_equal": deterministic,
            "signature_count": len(signatures),
        },
        "protected_state_before": before,
        "protected_state_after": after,
        "protected_state_unchanged": protected_unchanged,
        "token_cost": token_cost_report(paths, request),
        "errors": errors,
        "generated_files_created_in_production": False,
        "active_pointer_changed_in_production": False,
        "final_state": final_state,
    }
    receipt_path = receipt_root / f"{run_id}.json"
    receipt_write: dict[str, Any]
    try:
        receipt_write = RustSecurityAdapter().write_json(
            receipt_path,
            _json_bytes(_redact_protected_paths(receipt)),
        )
    except Exception as exc:
        receipt_write = {"ok": False, "error": f"self_test_receipt_write_failed:{exc}"}
    report = {
        "ok": final_state == "PASS_WITH_EXPECTED_SECURITY_HOLD" and bool(receipt_write.get("ok")),
        "state": final_state if receipt_write.get("ok") else "HOLD_RECEIPT_WRITE",
        "schema_version": SELF_TEST_RECEIPT_SCHEMA,
        "run_id": run_id,
        "template_id": template_id,
        "pillar": pillar,
        "repeated_run_count": repeats,
        "selection_request": request,
        "rust_security": rust_security,
        "generated_files_created": False,
        "active_pointer_changed": False,
        "protected_state_unchanged": protected_unchanged,
        "deterministic": deterministic,
        "receipt": {"path": _posix(receipt_path), "write": receipt_write},
        "errors": errors,
    }
    return report


def publish_generation(
    paths: ToolboxPaths,
    *,
    security: SecurityAdapter | None = None,
    selection_request: Mapping[str, Any] | None = None,
    publish_pointer: bool = True,
) -> dict[str, Any]:
    """Publish a verified generation, optionally leaving the active pointer untouched.

    ``publish_pointer=False`` is the approval-bound production-generation
    mode.  It writes and verifies a new immutable generation only; changing
    ``template_current.json`` remains a separate authority-bearing operation.
    The default remains the historical builder behavior for existing callers.
    """
    staging_dir: Path | None = None
    try:
        plan = plan_generation(paths, selection_request)
        adapter = security or RustSecurityAdapter()
        security_report = adapter.probe(plan, paths)
        if not security_report.get("ok"):
            return {
                "ok": False,
                "state": "HOLD_SECURITY",
                "generation_id": plan.generation_id,
                "selection_request": plan.selection_request,
                "selection_request_sha256": plan.selection_request_sha256,
                "security": security_report,
                "writes_performed": False,
            }
        active = _load_current_pointer(paths)
        if active:
            active_generation_dir = paths.generation_root / str(active.get("generation_id"))
            active_manifest_path = active_generation_dir / "generation_manifest.json"
            if active_manifest_path.is_file():
                try:
                    active_manifest = _read_json(active_manifest_path)
                except GenerationVerificationError:
                    active_manifest = {}
                if active_manifest.get("input_sha256") == plan.input_sha256:
                    active_verification = verify_generation(paths)
                    if active_verification.get("ok"):
                        return {
                            "ok": True,
                            "state": "PASS",
                            "generation_id": active.get("generation_id"),
                            "selection_request": plan.selection_request,
                            "selection_request_sha256": plan.selection_request_sha256,
                            "security": security_report,
                            "verification": active_verification,
                            "pointer": active,
                            "pointer_sha256": _sha256_bytes(paths.current_pointer.read_bytes()),
                            "idempotent": True,
                            "writes_performed": False,
                        }
        generation_dir = paths.generation_root / plan.generation_id
        if generation_dir.exists():
            existing = verify_generation(paths, plan.generation_id)
            if existing.get("ok"):
                active = _load_current_pointer(paths)
                if active and active.get("generation_id") == plan.generation_id:
                    return {
                        "ok": True,
                        "state": "PASS",
                        "generation_id": plan.generation_id,
                        "selection_request": plan.selection_request,
                        "selection_request_sha256": plan.selection_request_sha256,
                        "security": security_report,
                        "verification": existing,
                        "pointer": active,
                        "pointer_sha256": _sha256_bytes(paths.current_pointer.read_bytes()),
                        "idempotent": True,
                        "writes_performed": False,
                    }
                return {
                    "ok": False,
                    "state": "HOLD",
                    "reason": "immutable_generation_exists_not_active",
                    "verification": existing,
                    "writes_performed": False,
                }
            return {
                "ok": False,
                "state": "HOLD",
                "reason": "existing_generation_invalid",
                "verification": existing,
                "writes_performed": False,
            }
        archive_path = paths.receipt_root / "receipts" / f"{plan.generation_id}.json"
        if archive_path.exists():
            return {
                "ok": False,
                "state": "HOLD",
                "reason": "immutable_receipt_archive_exists_without_generation",
                "archive_path": _posix(archive_path),
                "writes_performed": False,
            }
        pointer_temp = _pointer_temp_path(paths)
        if pointer_temp.exists():
            return {
                "ok": False,
                "state": "HOLD",
                "reason": "pointer_temp_exists",
                "path": _posix(pointer_temp),
                "writes_performed": False,
            }
        paths.generation_root.mkdir(parents=True, exist_ok=True)
        staging_dir = Path(
            tempfile.mkdtemp(prefix=f".{plan.generation_id}.staging-", dir=str(paths.generation_root))
        )
        for module in plan.modules:
            target = staging_dir / module.generated_rel
            result = adapter.write_python(
                target,
                module.generated_text,
                operation_id=f"template-publish-{plan.generation_id}-{module.template.template_id}",
                provenance=_indexed_write_provenance(module, origin="indexed_template_span"),
            )
            if not result.get("ok"):
                return {"ok": False, "state": "HOLD", "reason": "python_write_failed", "write": result, "writes_performed": True}

        index_path = staging_dir / "function_index.json"
        manifest_path = staging_dir / "generation_manifest.json"
        receipt_path = staging_dir / "generation_receipt.json"
        index_result = adapter.write_json(index_path, _json_bytes(plan.index))
        if not index_result.get("ok"):
            return {"ok": False, "state": "HOLD", "reason": "index_write_failed", "write": index_result, "writes_performed": True}
        manifest_result = adapter.write_json(manifest_path, _json_bytes(plan.manifest))
        if not manifest_result.get("ok"):
            return {"ok": False, "state": "HOLD", "reason": "manifest_write_failed", "write": manifest_result, "writes_performed": True}
        receipt = _redact_protected_paths(_receipt_payload(plan, security_report, paths))
        receipt_result = adapter.write_json(receipt_path, _json_bytes(receipt))
        if not receipt_result.get("ok"):
            return {"ok": False, "state": "HOLD", "reason": "receipt_write_failed", "write": receipt_result, "writes_performed": True}
        archive_path = paths.receipt_root / "receipts" / f"{plan.generation_id}.json"
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        archive_result = adapter.write_json(archive_path, _json_bytes(receipt))
        if not archive_result.get("ok"):
            return {"ok": False, "state": "HOLD", "reason": "receipt_archive_write_failed", "write": archive_result, "writes_performed": True}
        verification = _verify_generation_files(
            staging_dir,
            expected_source_root=paths.source_root,
            expected_receipt_root=paths.receipt_root,
            expected_generation_id=plan.generation_id,
        )
        os.replace(staging_dir, generation_dir)
        staging_dir = None
        pointer = _pointer_payload(plan, generation_dir, receipt)
        if not publish_pointer:
            active = _load_current_pointer(paths)
            final_verification = _verify_generation_files(
                generation_dir,
                expected_source_root=paths.source_root,
                expected_receipt_root=paths.receipt_root,
            )
            return {
                "ok": bool(final_verification.get("ok")),
                "state": "PASS_GENERATION_ONLY" if final_verification.get("ok") else "HOLD_GENERATION_VERIFICATION",
                "generation_id": plan.generation_id,
                "selection_request": plan.selection_request,
                "selection_request_sha256": plan.selection_request_sha256,
                "security": security_report,
                "verification": final_verification,
                "pointer": active,
                "pointer_sha256": _sha256_bytes(paths.current_pointer.read_bytes()) if paths.current_pointer.is_file() else None,
                "active_pointer_changed": False,
                "writes_performed": True,
            }
        pointer_result = adapter.write_json(pointer_temp, _json_bytes(pointer))
        if not pointer_result.get("ok"):
            return {"ok": False, "state": "HOLD", "reason": "pointer_write_failed", "write": pointer_result, "verification": verification, "writes_performed": True}
        try:
            staged_pointer = _read_json(pointer_temp)
            _validate_pointer_for_generation(staged_pointer, generation_dir, plan.generation_id)
            if staged_pointer != pointer:
                raise GenerationVerificationError("pointer_temp_payload_mismatch")
        except (GenerationVerificationError, OSError) as exc:
            pointer_temp.unlink(missing_ok=True)
            return {
                "ok": False,
                "state": "HOLD",
                "reason": f"pointer_temp_validation_failed:{exc}",
                "verification": verification,
                "writes_performed": True,
            }
        os.replace(pointer_temp, paths.current_pointer)
        if _sha256_bytes(paths.current_pointer.read_bytes()) != pointer_result.get("sha256"):
            return {"ok": False, "state": "HOLD", "reason": "active_pointer_post_replace_hash_mismatch", "writes_performed": True}
        active = _load_current_pointer(paths)
        final_verification = _verify_generation_files(
            generation_dir,
            expected_pointer=active,
            expected_source_root=paths.source_root,
            expected_receipt_root=paths.receipt_root,
        )
        return {
            "ok": True,
            "state": "PASS",
            "generation_id": plan.generation_id,
            "selection_request": plan.selection_request,
            "selection_request_sha256": plan.selection_request_sha256,
            "security": security_report,
            "verification": final_verification,
            "pointer": active,
            "pointer_sha256": _sha256_bytes(paths.current_pointer.read_bytes()),
            "writes_performed": True,
        }
    except (TemplateContractError, GenerationVerificationError, OSError) as exc:
        return {"ok": False, "state": "HOLD", "reason": str(exc), "writes_performed": False}
    finally:
        if staging_dir is not None:
            _remove_private_staging_dir(staging_dir, paths.generation_root)


def rollback_generation(paths: ToolboxPaths, generation_id: str, *, security: SecurityAdapter | None = None) -> dict[str, Any]:
    _validate_toolbox_paths(paths)
    if not _GENERATION_RE.fullmatch(str(generation_id)):
        return {"ok": False, "state": "HOLD", "reason": "invalid_generation_id"}
    generation_dir = paths.generation_root / generation_id
    try:
        verification = _verify_generation_files(
            generation_dir,
            expected_source_root=paths.source_root,
            expected_receipt_root=paths.receipt_root,
        )
        manifest = _read_json(generation_dir / "generation_manifest.json")
        pointer = {
            "schema_version": POINTER_SCHEMA,
            "generation_id": generation_id,
            "manifest_path": _posix(generation_dir / "generation_manifest.json"),
            "index_path": _posix(generation_dir / "function_index.json"),
            "receipt_path": _posix(generation_dir / "generation_receipt.json"),
            "manifest_sha256": verification["manifest_sha256"],
            "index_sha256": verification["index_sha256"],
            "receipt_sha256": verification["receipt_sha256"],
            "input_sha256": manifest.get("input_sha256"),
            "parent_generation": manifest.get("parent_generation"),
            "lineage_tail": list(manifest.get("lineage_tail") or [])[-5:],
            "selection_request": manifest.get("selection_request"),
            "selection_request_sha256": manifest.get("selection_request_sha256"),
            "updated_utc": _utc(),
        }
        adapter = security or RustSecurityAdapter()
        pointer_temp = _pointer_temp_path(paths)
        if pointer_temp.exists():
            return {"ok": False, "state": "HOLD", "reason": "pointer_temp_exists", "path": _posix(pointer_temp)}
        pointer_result = adapter.write_json(pointer_temp, _json_bytes(pointer))
        if not pointer_result.get("ok"):
            return {"ok": False, "state": "HOLD_SECURITY", "reason": "rollback_pointer_write_denied", "write": pointer_result, "verification": verification}
        try:
            staged_pointer = _read_json(pointer_temp)
            _validate_pointer_for_generation(staged_pointer, generation_dir, generation_id)
            if staged_pointer != pointer:
                raise GenerationVerificationError("rollback_pointer_temp_payload_mismatch")
        except (GenerationVerificationError, OSError) as exc:
            pointer_temp.unlink(missing_ok=True)
            return {
                "ok": False,
                "state": "HOLD",
                "reason": f"rollback_pointer_temp_validation_failed:{exc}",
                "verification": verification,
            }
        os.replace(pointer_temp, paths.current_pointer)
        if _sha256_bytes(paths.current_pointer.read_bytes()) != pointer_result.get("sha256"):
            return {"ok": False, "state": "HOLD", "reason": "rollback_pointer_post_replace_hash_mismatch", "verification": verification}
        active = _load_current_pointer(paths)
        return {
            "ok": True,
            "state": "PASS",
            "generation_id": generation_id,
            "verification": _verify_generation_files(
                generation_dir,
                expected_pointer=active,
                expected_source_root=paths.source_root,
                expected_receipt_root=paths.receipt_root,
            ),
            "pointer": active,
        }
    except (TemplateContractError, GenerationVerificationError, OSError) as exc:
        return {"ok": False, "state": "HOLD", "generation_id": generation_id, "reason": str(exc)}


def adopt_template(
    paths: ToolboxPaths,
    generation_id: str,
    template_id: str,
    *,
    security: SecurityAdapter | None = None,
    human_approval: bool = False,
) -> dict[str, Any]:
    """Copy an immutable generated template into a new editable source layer.

    Adoption is the live template-insertion boundary.  A sandbox rebuild may
    create a candidate without approval, but inserting that candidate into the
    editable source layer and registry always requires an explicit human
    approval flag in addition to the Rust security decision.
    """
    _validate_toolbox_paths(paths)
    if not human_approval:
        return {
            "ok": False,
            "state": "HOLD_HUMAN_APPROVAL",
            "reason": "live_template_insertion_requires_human_approval",
            "template_insertion_performed": False,
            "sandbox_candidate_allowed": True,
        }
    if not _GENERATION_RE.fullmatch(str(generation_id)) or not _ID_RE.fullmatch(str(template_id)):
        return {"ok": False, "state": "HOLD", "reason": "invalid_adoption_identifier"}
    generation_dir = paths.generation_root / generation_id
    try:
        _verify_generation_files(
            generation_dir,
            expected_source_root=paths.source_root,
            expected_receipt_root=paths.receipt_root,
        )
        manifest = _read_json(generation_dir / "generation_manifest.json")
        module = next((row for row in manifest.get("modules", []) if row.get("template_id") == template_id), None)
        if not isinstance(module, dict):
            return {"ok": False, "state": "HOLD", "reason": "template_not_in_generation"}
        source_path = generation_dir / Path(str(module["generated_path"]))
        adopted_rel = Path("adopted") / f"{template_id.replace('.', '_')}__{generation_id}.py"
        adopted_path = paths.source_root / adopted_rel
        if adopted_path.exists():
            return {"ok": False, "state": "HOLD", "reason": "adoption_target_exists", "path": _posix(adopted_path)}
        adopted_path.parent.mkdir(parents=True, exist_ok=True)
        adapter = security or RustSecurityAdapter()
        adopted_bytes = source_path.read_bytes()
        source_result = adapter.write_python(
            adopted_path,
            adopted_bytes.decode("utf-8"),
            operation_id=f"template-adopt-{generation_id}-{template_id}",
            provenance={
                "schema_version": "viv_indexed_source_write_provenance_v1",
                "origin": "template_adoption",
                "template_id": template_id,
                "source_path": module.get("source_path"),
                "source_sha256": str(module.get("source_sha256") or module.get("generated_sha256") or ""),
                "content_sha256": _sha256_bytes(adopted_bytes),
                "section_hashes": {},
                "source_index_sha256": _sha256_text(_stable_json(module)),
            },
        )
        if not source_result.get("ok"):
            return {"ok": False, "state": "HOLD", "reason": "adopted_source_write_failed", "write": source_result}
        registry = _read_json(paths.registry_path)
        registry_before_bytes = paths.registry_path.read_bytes()
        registry_before_sha256 = _sha256_bytes(registry_before_bytes)
        rows = [row for row in registry.get("templates", []) if row.get("template_id") != template_id]
        rows.append(
            {
                "template_id": template_id,
                "source": _posix(adopted_rel),
                "targets": list(module.get("target_pillars") or []),
                "submain_order": list(module.get("submain_order") or []),
            }
        )
        registry["templates"] = sorted(rows, key=lambda row: str(row.get("template_id")))
        registry_result = adapter.write_json(paths.registry_path, _json_bytes(registry))
        if not registry_result.get("ok"):
            adopted_path.unlink(missing_ok=True)
            return {"ok": False, "state": "HOLD", "reason": "registry_write_failed", "write": registry_result}
        adoption = {
            "schema_version": "viv_code_template_adoption_v1",
            "adoption_id": f"adopt_{generation_id}_{template_id.replace('.', '_')}",
            "created_utc": _utc(),
            "template_id": template_id,
            "parent_generation": generation_id,
            "human_approval": True,
            "template_insertion_performed": True,
            "parent_receipt": _posix(generation_dir / "generation_receipt.json"),
            "lineage_display_tail": [*manifest.get("lineage_tail", []), generation_id][-5:],
            "source_path": _posix(adopted_path),
            "source_sha256": _sha256_bytes(adopted_path.read_bytes()),
            "registry_before_sha256": registry_before_sha256,
            "registry_after_sha256": _sha256_bytes(paths.registry_path.read_bytes()),
        }
        adoption_path = paths.receipt_root / "adoptions" / f"{adoption['adoption_id']}.json"
        adoption_result = adapter.write_json(adoption_path, _json_bytes(adoption))
        if not adoption_result.get("ok"):
            adapter.write_json(paths.registry_path, registry_before_bytes)
            adopted_path.unlink(missing_ok=True)
            return {"ok": False, "state": "HOLD", "reason": "adoption_receipt_write_failed", "write": adoption_result}
        return {
            "ok": True,
            "state": "PASS",
            "template_id": template_id,
            "source_path": _posix(adopted_path),
            "parent_generation": generation_id,
            "source_sha256": _sha256_bytes(adopted_path.read_bytes()),
            "lineage_display_tail": [generation_id],
            "full_lineage_receipt": _posix(generation_dir / "generation_receipt.json"),
            "adoption_receipt": _posix(adoption_path),
            "human_approval": True,
            "template_insertion_performed": True,
            "sandbox_candidate_allowed": True,
        }
    except (GenerationVerificationError, OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "state": "HOLD", "reason": str(exc)}


def _migration_catalog_status(paths: ToolboxPaths) -> dict[str, Any]:
    """Read the existing-function migration catalog without registering it."""
    migration_root = paths.receipt_root / "migration"
    manifest_path = migration_root / "AIOS_FUNCTION_TEMPLATE_MIGRATION.json"
    function_index_path = migration_root / "function_index.json"
    if not manifest_path.is_file() or not function_index_path.is_file():
        return {"state": "ABSENT", "active_registry_updated": False}
    try:
        manifest = _read_json(manifest_path)
        function_index = _read_json(function_index_path)
        rows = manifest.get("files")
        entries = function_index.get("entries")
        if not isinstance(rows, list) or not isinstance(entries, list):
            return {"state": "HOLD", "reason": "migration_catalog_shape_invalid", "active_registry_updated": False}
        domains: dict[str, int] = {}
        mismatches: list[str] = []
        for row in rows:
            if not isinstance(row, dict):
                mismatches.append("manifest_row_invalid")
                continue
            source_path = paths.repo_root / Path(str(row.get("source_path") or ""))
            template_path = paths.repo_root / Path(str(row.get("template_path") or ""))
            try:
                source_bytes = source_path.read_bytes()
                template_bytes = template_path.read_bytes()
                if source_bytes != template_bytes:
                    mismatches.append(str(row.get("source_path") or "source_path"))
                if _sha256_bytes(source_bytes) != str(row.get("source_sha256") or ""):
                    mismatches.append(f"source_hash:{row.get('source_path')}")
                if _sha256_bytes(template_bytes) != str(row.get("template_sha256") or ""):
                    mismatches.append(f"template_hash:{row.get('template_path')}")
            except OSError:
                mismatches.append(str(row.get("source_path") or "source_path_missing"))
            domain = str(row.get("domain") or "uncategorized")
            domains[domain] = domains.get(domain, 0) + 1
        return {
            "state": "HOLD" if mismatches else "CANDIDATE_CATALOG",
            "active_registry_updated": False,
            "human_review_required_before_activation": True,
            "files_scanned": len(rows),
            "function_count": len(entries),
            "domain_count": len(domains),
            "domains": dict(sorted(domains.items())),
            "manifest": _posix(manifest_path),
            "function_index": _posix(function_index_path),
            "byte_hash_mismatches": mismatches[:25],
        }
    except (OSError, UnicodeError, TypeError, ValueError, TemplateContractError) as exc:
        return {"state": "HOLD", "reason": f"migration_catalog_invalid:{exc}", "active_registry_updated": False}


def _python_builtin_surface_status(paths: ToolboxPaths) -> dict[str, Any]:
    """Expose the read-only built-in primitive manifest to template status."""
    path = paths.repo_root / "foundation" / "code_templates" / "python_builtins_v1.json"
    if not path.is_file():
        return {"state": "ABSENT", "path": _posix(path)}
    try:
        payload = _read_json(path)
        categories = payload.get("categories") if isinstance(payload, dict) else None
        listed = {
            str(name)
            for values in (categories or {}).values()
            if isinstance(values, list)
            for name in values
        }
        policy = payload.get("automatic_reconstruction") if isinstance(payload, dict) else {}
        return {
            "state": "PASS" if payload.get("schema_version") == "viv_python_builtin_surface_v1" else "HOLD",
            "schema_version": payload.get("schema_version"),
            "path": _posix(path),
            "sha256": _sha256_bytes(path.read_bytes()),
            "builtin_count": len(listed),
            "automatic_rebuild_count": len(set(policy.get("allowed") or [])),
            "review_only_count": len(set(policy.get("review_only") or [])),
            "review_only": sorted(str(item) for item in (policy.get("review_only") or [])),
        }
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        return {"state": "HOLD", "path": _posix(path), "reason": f"builtin_surface_invalid:{exc}"}


def toolbox_status(paths: ToolboxPaths | None = None, *, pillar: str | None = None) -> dict[str, Any]:
    paths = paths or ToolboxPaths.default()
    try:
        rows = _validate_registry(paths)
        parsed = {template.template_id: template for template in (parse_template(row, paths) for row in rows)}
        filtered = [row for row in rows if pillar is None or pillar in row["targets"]]
        active = _load_current_pointer(paths)
        verification = verify_generation(paths) if active else {"ok": True, "state": "EMPTY", "reason": "no_active_generation"}
        source_drift: dict[str, Any] = {"detected": False}
        try:
            _check_source_approval(paths, tuple(parsed.values()), (active or {}).get("generation_id"))
        except TemplateContractError as exc:
            source_drift = {"detected": True, "reason": str(exc)}
        security: dict[str, Any]
        try:
            _, integrity_status, security_imports = RustSecurityAdapter()._imports()
            rust_available, _ = security_imports
            security = {
                "rust_available": bool(rust_available()),
                "integrity": dict(integrity_status()),
            }
        except Exception as exc:
            security = {"ok": False, "detail": f"security_status_unavailable:{exc}"}
        warnings: list[str] = []
        migration_catalog = _migration_catalog_status(paths)
        builtin_surface = _python_builtin_surface_status(paths)
        target_to_ids: dict[str, list[str]] = {target: [] for target in sorted(TARGET_PILLARS)}
        generated_to_ids: dict[str, list[str]] = {}
        for row in rows:
            template_id = str(row["template_id"])
            for target in row["targets"]:
                target_to_ids.setdefault(str(target), []).append(template_id)
            generated_name = f"{template_id.replace('.', '_')}.py"
            generated_to_ids.setdefault(generated_name, []).append(template_id)
        warnings.extend(
            f"generated_path_collision:{name}:{','.join(ids)}"
            for name, ids in generated_to_ids.items()
            if len(ids) > 1
        )
        return {
            "ok": bool(verification.get("ok")) and not source_drift["detected"],
            "state": "HOLD" if source_drift["detected"] else verification.get("state", "HOLD"),
            "toolbox": "viv_deterministic_code_templates",
            "pillar": pillar,
            "template_count": len(filtered),
            "templates": [
                {
                    "template_id": row["template_id"],
                    "source": row["source"],
                    "targets": row["targets"],
                    "submain_order": row["submain_order"],
                    "variables": list(parsed[str(row["template_id"])].variable_keys),
                    "submain_count": len(parsed[str(row["template_id"])].submains),
                    "source_sha256": parsed[str(row["template_id"])].source_sha256,
                }
                for row in filtered
            ],
            "active_generation": (active or {}).get("generation_id"),
            "verification": verification,
            "security": security,
            "domain_coverage": target_to_ids,
            "source_drift": source_drift,
            "lineage_tail": ((active or {}).get("lineage_tail") or [])[-5:],
            "duplicate_conflict_warnings": warnings,
            "migration_catalog": migration_catalog,
            "python_builtin_surface": builtin_surface,
            "source_root": _posix(paths.source_root),
            "generated_root": _posix(paths.generation_root),
            "operations": [
                "status",
                "inventory",
                "index",
                "build --dry-run",
                "self-test",
                "cost",
                "scale-test (template_scale_rebuild_v1.py)",
                "rebuild (template_scale_rebuild_v1.py)",
                "rebuild-random (template_scale_rebuild_v1.py)",
                "builtin-surface (template_scale_rebuild_v1.py)",
                "verify",
                "publish",
                "rollback",
                "adopt",
            ],
        }
    except (TemplateContractError, GenerationVerificationError, OSError) as exc:
        return {"ok": False, "state": "HOLD", "reason": str(exc), "pillar": pillar}


def _paths_from_args(args: argparse.Namespace) -> ToolboxPaths:
    default = ToolboxPaths.default()
    return ToolboxPaths(
        repo_root=default.repo_root,
        source_root=Path(args.source_root) if args.source_root else default.source_root,
        registry_path=Path(args.registry) if args.registry else default.registry_path,
        toolbox_manifest=default.toolbox_manifest,
        generation_root=Path(args.generation_root) if args.generation_root else default.generation_root,
        current_pointer=Path(args.pointer) if args.pointer else default.current_pointer,
        receipt_root=Path(args.receipt_root) if args.receipt_root else default.receipt_root,
    )


def _selection_request_from_args(args: argparse.Namespace) -> dict[str, Any] | None:
    raw_path = str(getattr(args, "request", "") or "")
    if not raw_path:
        return None
    return _read_json(Path(raw_path))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="template_builder_v1", description="Viv deterministic code-template toolbox")
    parser.add_argument("--source-root", default="")
    parser.add_argument("--registry", default="")
    parser.add_argument("--generation-root", default="")
    parser.add_argument("--pointer", default="")
    parser.add_argument("--receipt-root", default="")
    parser.add_argument("--request", default="", help="JSON selection request; may appear before or after build/cost/publish")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="Read-only toolbox status")
    sub.add_parser("inventory", help="Read-only inventory of existing AIOS functions")
    sub.add_parser("index", help="Validate and write the source function index")
    build = sub.add_parser("build", help="Plan a deterministic copy; no files are written")
    build.add_argument("--dry-run", action="store_true", help="Explicitly select the no-write build operation")
    build.add_argument("--request", dest="request", default=argparse.SUPPRESS, help="JSON selection request")
    self_test = sub.add_parser("self-test", help="Run isolated deterministic toolbox and runtime acceptance tests")
    self_test.add_argument("--template-id", default="fixture.echo")
    self_test.add_argument("--pillar", choices=sorted(TARGET_PILLARS), default="auto")
    self_test.add_argument("--repeats", type=int, default=10)
    self_test.add_argument("--isolated", action="store_true", help="Mandatory: use only a private temporary generation root")
    self_test.add_argument("--no-publish", action="store_true", help="Mandatory: never activate the production pointer")
    self_test.add_argument("--receipt-dir", default="", help="Directory for JSON self-test evidence only")
    cost = sub.add_parser("cost", help="Estimate code-emission tokens versus a structured toolbox request")
    cost.add_argument("--request", dest="request", default=argparse.SUPPRESS, help="JSON selection request")
    publish = sub.add_parser("publish", help="Publish a Rust-gated generation")
    publish.add_argument("--request", dest="request", default=argparse.SUPPRESS, help="JSON selection request")
    verify = sub.add_parser("verify", help="Verify the active or named generation")
    verify.add_argument("generation_id", nargs="?")
    rollback = sub.add_parser("rollback", help="Atomically activate a verified prior generation")
    rollback.add_argument("generation_id")
    adopt = sub.add_parser("adopt", help="Copy a generated template into a new source layer")
    adopt.add_argument("generation_id")
    adopt.add_argument("template_id")
    adopt.add_argument(
        "--human-approval",
        action="store_true",
        help="Explicitly approve live insertion into the editable source layer and registry",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    paths = _paths_from_args(args)
    try:
        selection_request = _selection_request_from_args(args)
        if selection_request is not None and args.command not in {"build", "cost", "publish"}:
            report = {"ok": False, "state": "HOLD", "reason": "request_not_supported_for_command"}
        elif args.command == "status":
            report = toolbox_status(paths)
        elif args.command == "inventory":
            report = inventory_aios_functions(paths)
        elif args.command == "index":
            report = index_templates(paths, write=True)
        elif args.command == "build":
            if not args.dry_run:
                report = {
                    "ok": False,
                    "state": "HOLD",
                    "dry_run": True,
                    "reason": "explicit_build_dry_run_flag_required",
                    "writes_performed": False,
                }
            else:
                report = build_dry_run(paths, selection_request=selection_request)
        elif args.command == "self-test":
            report = template_self_test(
                paths,
                template_id=str(args.template_id),
                pillar=str(args.pillar),
                repeats=int(args.repeats),
                isolated=bool(args.isolated),
                no_publish=bool(args.no_publish),
                receipt_dir=Path(args.receipt_dir) if args.receipt_dir else None,
            )
        elif args.command == "cost":
            report = token_cost_report(paths, selection_request)
        elif args.command == "publish":
            report = publish_generation(paths, selection_request=selection_request)
        elif args.command == "verify":
            report = verify_generation(paths, args.generation_id)
        elif args.command == "rollback":
            report = rollback_generation(paths, args.generation_id)
        elif args.command == "adopt":
            report = adopt_template(
                paths,
                args.generation_id,
                args.template_id,
                human_approval=bool(args.human_approval),
            )
        else:
            report = {"ok": False, "state": "HOLD", "reason": "unsupported_command"}
    except (GenerationVerificationError, OSError) as exc:
        report = {"ok": False, "state": "HOLD", "reason": str(exc)}
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
