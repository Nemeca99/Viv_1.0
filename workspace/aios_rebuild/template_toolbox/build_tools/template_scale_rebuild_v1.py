"""Deterministic candidate-catalog scale and reference-rebuild tooling.

This is an operator/developer surface for the deterministic template toolbox.
It does not generate Python.  The scale test copies the existing migration
catalog byte-for-byte into private temporary roots.  The reference rebuild
keeps the input module's non-function bytes and replaces top-level functions
only with an exact source span from the candidate catalog.  When a full
function is not present, the tool may deterministically recreate it by pairing
the input function's header with an indexed catalog body whose AST body and
parameter contract match.  That is body transplantation, not code synthesis.
An explicit input-span fallback remains available only for a human-authoring
hold; the random-file operation never enables it.

The active registry, production generation root, and active pointer are not
used as outputs by this module.  The command-line rebuild requires explicit
``--isolated`` and ``--no-publish`` guards, submits the hypothetical Python
write to the existing Rust membrane, and creates no output when Rust denies
it.  Receipts are JSON evidence only.  Unit/scale acceptance may use an
explicitly marked local adapter for a disposable temporary root after the
Rust denial is recorded; that adapter is never the AI/Viv path.
"""
from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import tempfile
import time
from typing import Any, Callable, Iterable, Mapping, Sequence


SCALE_RECEIPT_SCHEMA = "viv_code_template_scale_test_receipt_v1"
REBUILD_RECEIPT_SCHEMA = "viv_code_template_rebuild_receipt_v1"
REBUILD_SELECTION_SCHEMA = "viv_code_template_rebuild_selection_request_v1"
CPU_SELECTOR_REQUEST_SCHEMA = "viv_cpu_template_selector_request_v1"
MIGRATION_SCHEMA = "viv_aios_function_template_migration_v1"
BUILTIN_SURFACE_SCHEMA = "viv_python_builtin_surface_v1"
BUILTIN_SURFACE_REL = "foundation/code_templates/python_builtins_v1.json"

# This is the CPU reconstruction contract represented by the attached
# built-in-function surface.  ``input``, ``help``, ``id``, and ``dir`` remain
# visible in the manifest but require explicit human authoring review because
# they block, expose interactive documentation, or depend on process/object
# identity rather than being a stable data transformation.
AUTOMATIC_REBUILD_BUILTINS = frozenset(
    {
        "print",
        "type",
        "int",
        "float",
        "str",
        "bool",
        "list",
        "tuple",
        "set",
        "dict",
        "len",
        "sorted",
        "reversed",
        "enumerate",
        "zip",
        "range",
        "sum",
        "min",
        "max",
        "abs",
        "round",
        "pow",
        "all",
        "any",
        "isinstance",
        "map",
        "filter",
    }
)
REVIEW_ONLY_BUILTINS = frozenset({"input", "help", "id", "dir"})
BUILTIN_SURFACE = AUTOMATIC_REBUILD_BUILTINS | REVIEW_ONLY_BUILTINS
DENIED_REBUILD_CALLS = frozenset({"__import__", "compile", "eval", "exec", "open"}) | REVIEW_ONLY_BUILTINS
DENIED_REBUILD_ROOTS = frozenset(
    {
        "builtins",
        "ctypes",
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


class ScaleRebuildContractError(ValueError):
    """The candidate catalog, input module, or safety boundary is invalid."""


SecurityProbe = Callable[[Path, bytes], Mapping[str, Any]]


@dataclass(frozen=True)
class CatalogFunction:
    function_id: str
    name: str
    qualified_name: str
    source_path: str
    template_path: Path
    start_line: int
    end_line: int
    span_sha256: str
    semantic_sha256: str
    body_sha256: str
    parameters: tuple[str, ...]


@dataclass(frozen=True)
class CatalogModule:
    domain: str
    source_path: Path
    template_path: Path
    source_rel: str
    template_rel: str
    source_sha256: str
    template_sha256: str
    source_bytes: int
    function_count: int
    functions: tuple[CatalogFunction, ...]


@dataclass(frozen=True)
class CandidateCatalog:
    repo_root: Path
    manifest_path: Path
    function_index_path: Path
    manifest_sha256: str
    function_index_sha256: str
    modules: tuple[CatalogModule, ...]
    functions: tuple[CatalogFunction, ...]
    by_semantic_sha256: Mapping[str, tuple[CatalogFunction, ...]]
    by_body_sha256: Mapping[str, tuple[CatalogFunction, ...]]
    builtin_surface_sha256: str | None


@dataclass(frozen=True)
class ReferenceFunction:
    name: str
    qualified_name: str
    start_line: int
    end_line: int
    start_offset: int
    end_offset: int
    semantic_sha256: str
    body_sha256: str
    body_start_line: int
    body_indent: str
    span_sha256: str
    parameters: tuple[str, ...]


def _utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _posix(path: Path | str) -> str:
    return str(path).replace("\\", "/")


def _is_reparse_point(path: Path) -> bool:
    try:
        stat_result = path.lstat()
    except OSError:
        return False
    if path.is_symlink():
        return True
    if os.name == "nt":
        try:
            import stat

            return bool(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400) & getattr(stat_result, "st_file_attributes", 0))
        except (AttributeError, OSError):
            return False
    return False


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ScaleRebuildContractError(f"invalid_json:{path}:{exc}") from exc
    if not isinstance(value, dict):
        raise ScaleRebuildContractError(f"json_object_required:{path}")
    return value


def _resolve_repo_path(repo_root: Path, raw: str, *, label: str) -> Path:
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    resolved = candidate.resolve(strict=False)
    root = repo_root.resolve(strict=False)
    if resolved != root and root not in resolved.parents:
        raise ScaleRebuildContractError(f"{label}_outside_repo:{raw}")
    if _is_reparse_point(candidate):
        raise ScaleRebuildContractError(f"{label}_reparse_path:{candidate}")
    return resolved


def _node_end(node: ast.AST) -> int:
    end = getattr(node, "end_lineno", None)
    if not isinstance(end, int):
        raise ScaleRebuildContractError(f"missing_end_lineno:{type(node).__name__}")
    return end


def _decorated_start(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    starts = [int(node.lineno)]
    starts.extend(
        int(item.lineno)
        for item in node.decorator_list
        if isinstance(getattr(item, "lineno", None), int)
    )
    return min(starts)


def _parameters(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, ...]:
    args = node.args
    positional = [*args.posonlyargs, *args.args, *args.kwonlyargs]
    names = [arg.arg for arg in positional]
    if args.vararg is not None:
        names.append(f"*{args.vararg.arg}")
    if args.kwarg is not None:
        names.append(f"**{args.kwarg.arg}")
    return tuple(names)


def _semantic_sha256(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    dumped = ast.dump(node, annotate_fields=True, include_attributes=False)
    return _sha256_bytes(dumped.encode("utf-8"))


def _body_semantic_sha256(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Hash only the executable body, excluding name, decorators, and signature."""
    if not node.body:
        raise ScaleRebuildContractError(f"function_body_empty:{node.name}")
    body_module = ast.Module(body=list(node.body), type_ignores=[])
    dumped = ast.dump(body_module, annotate_fields=True, include_attributes=False)
    return _sha256_bytes(dumped.encode("utf-8"))


def _body_start_line(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    if not node.body:
        raise ScaleRebuildContractError(f"function_body_empty:{node.name}")
    first = node.body[0]
    line = getattr(first, "lineno", None)
    if not isinstance(line, int):
        raise ScaleRebuildContractError(f"function_body_line_missing:{node.name}")
    return line


def _leading_indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip(" \t"))]


def _body_indent_from_bytes(body_bytes: bytes) -> str:
    try:
        text = body_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ScaleRebuildContractError("function_body_not_utf8") from exc
    for line in text.splitlines():
        if line.strip():
            return _leading_indent(line)
    raise ScaleRebuildContractError("function_body_has_no_code")


def _body_span(
    source_bytes: bytes,
    line_offsets: Sequence[int],
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bytes:
    return _byte_span(source_bytes, line_offsets, _body_start_line(node), _node_end(node))


def _reindent_body(body_bytes: bytes, *, source_indent: str, target_indent: str) -> bytes:
    """Move an approved body under the supplied header without rewriting code."""
    if source_indent == target_indent:
        return body_bytes
    try:
        text = body_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ScaleRebuildContractError("function_body_not_utf8") from exc
    output: list[str] = []
    for line in text.splitlines(keepends=True):
        if not line.strip():
            output.append(line)
            continue
        if not line.startswith(source_indent):
            raise ScaleRebuildContractError("function_body_indentation_incompatible")
        output.append(target_indent + line[len(source_indent) :])
    return "".join(output).encode("utf-8")


def _builtin_surface_receipt(repo_root: Path) -> dict[str, Any] | None:
    path = repo_root / BUILTIN_SURFACE_REL
    if not path.is_file():
        return None
    raw = path.read_bytes()
    data = _read_json(path)
    if data.get("schema_version") != BUILTIN_SURFACE_SCHEMA:
        raise ScaleRebuildContractError("builtin_surface_schema_mismatch")
    categories = data.get("categories")
    if not isinstance(categories, dict):
        raise ScaleRebuildContractError("builtin_surface_categories_invalid")
    listed: set[str] = set()
    for values in categories.values():
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise ScaleRebuildContractError("builtin_surface_category_invalid")
        listed.update(values)
    if listed != BUILTIN_SURFACE:
        raise ScaleRebuildContractError("builtin_surface_category_set_mismatch")
    automatic = data.get("automatic_reconstruction")
    if not isinstance(automatic, dict):
        raise ScaleRebuildContractError("builtin_surface_policy_invalid")
    if set(automatic.get("allowed") or []) != AUTOMATIC_REBUILD_BUILTINS:
        raise ScaleRebuildContractError("builtin_surface_allowed_set_mismatch")
    if set(automatic.get("review_only") or []) != REVIEW_ONLY_BUILTINS:
        raise ScaleRebuildContractError("builtin_surface_review_set_mismatch")
    return {
        "path": _posix(path),
        "sha256": _sha256_bytes(raw),
        "schema_version": BUILTIN_SURFACE_SCHEMA,
        "builtin_count": len(listed),
        "automatic_rebuild_count": len(AUTOMATIC_REBUILD_BUILTINS),
        "review_only_count": len(REVIEW_ONLY_BUILTINS),
    }


def _validate_recreated_body(node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
    """Reject sensitive or unapproved built-in calls in a transplanted body."""
    try:
        import builtins as python_builtins

        known_builtins = set(dir(python_builtins))
    except Exception as exc:  # pragma: no cover - interpreter invariant
        raise ScaleRebuildContractError(f"builtin_surface_unavailable:{exc}") from exc
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        if isinstance(child.func, ast.Name):
            name = child.func.id
            if name in DENIED_REBUILD_CALLS:
                raise ScaleRebuildContractError(f"recreated_body_builtin_review_only:{name}")
            if name in known_builtins and name not in AUTOMATIC_REBUILD_BUILTINS:
                raise ScaleRebuildContractError(f"recreated_body_builtin_not_allowlisted:{name}")
        elif isinstance(child.func, ast.Attribute):
            root = child.func.value.id if isinstance(child.func.value, ast.Name) else ""
            if root.casefold() in DENIED_REBUILD_ROOTS:
                raise ScaleRebuildContractError(f"recreated_body_unsafe_call:{root}.{child.func.attr}")


def builtin_surface_status(*, repo_root: Path | None = None) -> dict[str, Any]:
    """Read-only verification of the attached built-in primitive contract."""
    root = (repo_root or _repo_root()).resolve(strict=False)
    try:
        receipt = _builtin_surface_receipt(root)
        if receipt is None:
            return {"ok": False, "state": "HOLD", "reason": "builtin_surface_missing"}
        return {"ok": True, "state": "PASS", **receipt}
    except (OSError, ScaleRebuildContractError) as exc:
        return {"ok": False, "state": "HOLD", "reason": str(exc)}


def _line_offsets(source_bytes: bytes) -> list[int]:
    """Return one-based line-start byte offsets, preserving UTF-8 bytes."""
    offsets = [0]
    for index, byte in enumerate(source_bytes):
        if byte == 0x0A:
            offsets.append(index + 1)
    return offsets


def _byte_span(source_bytes: bytes, line_offsets: Sequence[int], start_line: int, end_line: int) -> bytes:
    if start_line < 1 or end_line < start_line or start_line > len(line_offsets):
        raise ScaleRebuildContractError(f"line_span_invalid:{start_line}:{end_line}")
    start = line_offsets[start_line - 1]
    end = line_offsets[end_line] if end_line < len(line_offsets) else len(source_bytes)
    return source_bytes[start:end]


def _parse_source(path: Path, source_bytes: bytes) -> ast.Module:
    try:
        source_text = source_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ScaleRebuildContractError(f"source_not_utf8:{path}") from exc
    try:
        return ast.parse(source_text, filename=str(path), type_comments=True)
    except SyntaxError as exc:
        raise ScaleRebuildContractError(f"syntax_error:{path}:{exc}") from exc


def _function_from_span(
    source_bytes: bytes,
    line_offsets: Sequence[int],
    *,
    start_line: int,
    end_line: int,
    expected_name: str,
) -> tuple[bytes, ast.FunctionDef | ast.AsyncFunctionDef]:
    span = _byte_span(source_bytes, line_offsets, start_line, end_line)
    try:
        text = span.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ScaleRebuildContractError("function_span_not_utf8") from exc
    # Migration entries also include methods and nested functions.  Their
    # exact bytes intentionally retain indentation; strip only the indentation
    # of the first source line for the temporary AST view.  ``textwrap`` can
    # be defeated by an unindented line inside a multiline string literal.
    source_lines = text.splitlines(keepends=True)
    first_code = next((line for line in source_lines if line.strip()), "")
    prefix_length = len(first_code) - len(first_code.lstrip(" \t"))
    prefix = first_code[:prefix_length]
    normalized_text = "".join(
        line[len(prefix) :] if prefix and line.startswith(prefix) else line
        for line in source_lines
    )
    tree = _parse_source(Path("<function-span>"), normalized_text.encode("utf-8"))
    functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if len(functions) != 1 or functions[0].name != expected_name:
        raise ScaleRebuildContractError(
            f"function_span_mismatch:{expected_name}:found={[getattr(node, 'name', None) for node in functions]}"
        )
    # The local parse is only used for a location-independent semantic digest;
    # the returned bytes remain the original exact source span.
    del text
    return span, functions[0]


def _reference_functions(source_path: Path, source_bytes: bytes) -> tuple[ReferenceFunction, ...]:
    tree = _parse_source(source_path, source_bytes)
    offsets = _line_offsets(source_bytes)
    rows: list[ReferenceFunction] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        start_line = _decorated_start(node)
        end_line = _node_end(node)
        span = _byte_span(source_bytes, offsets, start_line, end_line)
        body_start_line = _body_start_line(node)
        body_span = _body_span(source_bytes, offsets, node)
        rows.append(
            ReferenceFunction(
                name=node.name,
                qualified_name=node.name,
                start_line=start_line,
                end_line=end_line,
                start_offset=offsets[start_line - 1],
                end_offset=offsets[end_line] if end_line < len(offsets) else len(source_bytes),
                semantic_sha256=_semantic_sha256(node),
                body_sha256=_body_semantic_sha256(node),
                body_start_line=body_start_line,
                body_indent=_body_indent_from_bytes(body_span),
                span_sha256=_sha256_bytes(span),
                parameters=_parameters(node),
            )
        )
    return tuple(rows)


def load_candidate_catalog(
    *,
    repo_root: Path | None = None,
    manifest_path: Path | None = None,
    function_index_path: Path | None = None,
) -> CandidateCatalog:
    """Load and verify the human-review candidate catalog without registering it."""
    root = (repo_root or _repo_root()).resolve(strict=False)
    manifest = (manifest_path or root / "foundation/artifacts/auto/code_templates/migration/AIOS_FUNCTION_TEMPLATE_MIGRATION.json").resolve(strict=False)
    function_index = (function_index_path or root / "foundation/artifacts/auto/code_templates/migration/function_index.json").resolve(strict=False)
    manifest_bytes = manifest.read_bytes()
    index_bytes = function_index.read_bytes()
    manifest_data = _read_json(manifest)
    index_data = _read_json(function_index)
    if manifest_data.get("schema_version") != MIGRATION_SCHEMA or index_data.get("schema_version") != MIGRATION_SCHEMA:
        raise ScaleRebuildContractError("candidate_catalog_schema_mismatch")
    if manifest_data.get("active_registry_updated") is not False:
        raise ScaleRebuildContractError("candidate_catalog_must_not_update_active_registry")
    file_rows = manifest_data.get("files")
    index_rows = index_data.get("entries")
    if not isinstance(file_rows, list) or not isinstance(index_rows, list):
        raise ScaleRebuildContractError("candidate_catalog_shape_invalid")

    functions_by_template: dict[str, list[CatalogFunction]] = {}
    all_functions: list[CatalogFunction] = []
    for row in index_rows:
        if not isinstance(row, dict):
            raise ScaleRebuildContractError("candidate_function_row_invalid")
        template_rel = str(row.get("template_path") or "")
        template_path = _resolve_repo_path(root, template_rel, label="candidate_template")
        if not template_path.is_file():
            raise ScaleRebuildContractError(f"candidate_template_missing:{template_path}")
        start_line = int(row.get("template_start_line"))
        end_line = int(row.get("template_end_line"))
        template_bytes = template_path.read_bytes()
        span, node = _function_from_span(
            template_bytes,
            _line_offsets(template_bytes),
            start_line=start_line,
            end_line=end_line,
            expected_name=str(row.get("name") or ""),
        )
        function_id = f"{row.get('source_path')}::{row.get('qualified_name')}"
        function = CatalogFunction(
            function_id=function_id,
            name=str(row.get("name") or ""),
            qualified_name=str(row.get("qualified_name") or ""),
            source_path=str(row.get("source_path") or ""),
            template_path=template_path,
            start_line=start_line,
            end_line=end_line,
            span_sha256=_sha256_bytes(span),
            semantic_sha256=_semantic_sha256(node),
            body_sha256=_body_semantic_sha256(node),
            parameters=_parameters(node),
        )
        functions_by_template.setdefault(template_rel, []).append(function)
        all_functions.append(function)

    modules: list[CatalogModule] = []
    for row in file_rows:
        if not isinstance(row, dict):
            raise ScaleRebuildContractError("candidate_module_row_invalid")
        source_rel = str(row.get("source_path") or "")
        template_rel = str(row.get("template_path") or "")
        source_path = _resolve_repo_path(root, source_rel, label="candidate_source")
        template_path = _resolve_repo_path(root, template_rel, label="candidate_template")
        if not source_path.is_file() or not template_path.is_file():
            raise ScaleRebuildContractError(f"candidate_module_missing:{source_rel}")
        source_bytes = source_path.read_bytes()
        template_bytes = template_path.read_bytes()
        source_sha = _sha256_bytes(source_bytes)
        template_sha = _sha256_bytes(template_bytes)
        if source_sha != str(row.get("source_sha256") or ""):
            raise ScaleRebuildContractError(f"candidate_source_hash_mismatch:{source_rel}")
        if template_sha != str(row.get("template_sha256") or ""):
            raise ScaleRebuildContractError(f"candidate_template_hash_mismatch:{template_rel}")
        if source_bytes != template_bytes:
            raise ScaleRebuildContractError(f"candidate_copy_not_byte_exact:{template_rel}")
        functions = tuple(sorted(functions_by_template.get(template_rel, []), key=lambda item: (item.start_line, item.qualified_name)))
        expected_count = int(row.get("function_count") or len(functions))
        if len(functions) != expected_count:
            raise ScaleRebuildContractError(f"candidate_function_count_mismatch:{template_rel}")
        modules.append(
            CatalogModule(
                domain=str(row.get("domain") or "uncategorized"),
                source_path=source_path,
                template_path=template_path,
                source_rel=source_rel,
                template_rel=template_rel,
                source_sha256=source_sha,
                template_sha256=template_sha,
                source_bytes=len(source_bytes),
                function_count=len(functions),
                functions=functions,
            )
        )
    modules.sort(key=lambda item: item.template_rel.casefold())
    all_functions.sort(key=lambda item: (item.template_path.as_posix().casefold(), item.start_line, item.qualified_name))
    by_semantic: dict[str, list[CatalogFunction]] = {}
    by_body: dict[str, list[CatalogFunction]] = {}
    for function in all_functions:
        by_semantic.setdefault(function.semantic_sha256, []).append(function)
        by_body.setdefault(function.body_sha256, []).append(function)
    return CandidateCatalog(
        repo_root=root,
        manifest_path=manifest,
        function_index_path=function_index,
        manifest_sha256=_sha256_bytes(manifest_bytes),
        function_index_sha256=_sha256_bytes(index_bytes),
        modules=tuple(modules),
        functions=tuple(all_functions),
        by_semantic_sha256={key: tuple(value) for key, value in by_semantic.items()},
        by_body_sha256={key: tuple(value) for key, value in by_body.items()},
        builtin_surface_sha256=(
            (_builtin_surface_receipt(root) or {}).get("sha256")
            if (root / BUILTIN_SURFACE_REL).is_file()
            else None
        ),
    )


def _catalog_function_bytes(function: CatalogFunction) -> bytes:
    source_bytes = function.template_path.read_bytes()
    actual = _sha256_bytes(source_bytes)
    if not actual:
        raise ScaleRebuildContractError(f"catalog_function_source_unreadable:{function.function_id}")
    span, node = _function_from_span(
        source_bytes,
        _line_offsets(source_bytes),
        start_line=function.start_line,
        end_line=function.end_line,
        expected_name=function.name,
    )
    if (
        _sha256_bytes(span) != function.span_sha256
        or _semantic_sha256(node) != function.semantic_sha256
        or _body_semantic_sha256(node) != function.body_sha256
    ):
        raise ScaleRebuildContractError(f"catalog_function_drift:{function.function_id}")
    return span


def _catalog_function_parts(function: CatalogFunction) -> tuple[bytes, ast.FunctionDef | ast.AsyncFunctionDef, bytes]:
    source_bytes = function.template_path.read_bytes()
    span, node = _function_from_span(
        source_bytes,
        _line_offsets(source_bytes),
        start_line=function.start_line,
        end_line=function.end_line,
        expected_name=function.name,
    )
    if (
        _sha256_bytes(span) != function.span_sha256
        or _semantic_sha256(node) != function.semantic_sha256
        or _body_semantic_sha256(node) != function.body_sha256
    ):
        raise ScaleRebuildContractError(f"catalog_function_drift:{function.function_id}")
    return span, node, _body_span(span, _line_offsets(span), node)


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve(strict=False) == right.resolve(strict=False)
    except OSError:
        return False


def _select_catalog_function(
    reference: ReferenceFunction,
    reference_span_sha256: str,
    catalog: CandidateCatalog,
    *,
    reference_path: Path,
) -> CatalogFunction | None:
    candidates = list(catalog.by_semantic_sha256.get(reference.semantic_sha256, ()))
    if not candidates:
        return None
    exact_bytes = [candidate for candidate in candidates if candidate.span_sha256 == reference_span_sha256]
    ordered = exact_bytes or candidates
    # Prefer the same canonical module when the input is itself a catalog copy;
    # otherwise the stable catalog order prevents nondeterministic selection.
    for candidate in ordered:
        if _same_path(candidate.template_path, reference_path):
            return candidate
    return sorted(ordered, key=lambda item: (item.template_path.as_posix().casefold(), item.start_line, item.function_id))[0]


def _select_catalog_body_function(
    reference: ReferenceFunction,
    catalog: CandidateCatalog,
    *,
    reference_path: Path,
) -> CatalogFunction | None:
    """Find a body-equivalent catalog function with the same parameter contract."""
    candidates = [
        candidate
        for candidate in catalog.by_body_sha256.get(reference.body_sha256, ())
        if candidate.parameters == reference.parameters
    ]
    if not candidates:
        return None
    for candidate in candidates:
        if _same_path(candidate.template_path, reference_path):
            return candidate
    return sorted(candidates, key=lambda item: (item.template_path.as_posix().casefold(), item.start_line, item.function_id))[0]


def _selector_request_hash(request: Mapping[str, Any]) -> str:
    return _sha256_bytes(_stable_json(dict(request)).encode("utf-8"))


def _validate_cpu_selector_request(
    request: Mapping[str, Any],
    *,
    input_sha256: str,
    references: Sequence[ReferenceFunction],
    catalog: CandidateCatalog,
) -> tuple[dict[str, Any], dict[str, CatalogFunction]]:
    """Validate a model-selected catalog request without accepting source text."""

    if not isinstance(request, Mapping):
        raise ScaleRebuildContractError("cpu_selector_request_mapping_required")
    allowed = {
        "schema_version",
        "operation",
        "input_sha256",
        "selections",
        "variable_overrides",
    }
    unknown = sorted(set(request) - allowed)
    if unknown:
        raise ScaleRebuildContractError(f"cpu_selector_request_fields_not_allowed:{','.join(unknown)}")
    if request.get("schema_version") != CPU_SELECTOR_REQUEST_SCHEMA:
        raise ScaleRebuildContractError("cpu_selector_request_schema_mismatch")
    if request.get("operation") != "random_file_rebuild":
        raise ScaleRebuildContractError("cpu_selector_request_operation_mismatch")
    if request.get("input_sha256") != input_sha256:
        raise ScaleRebuildContractError("cpu_selector_request_input_hash_mismatch")
    variable_overrides = request.get("variable_overrides", {})
    if not isinstance(variable_overrides, Mapping):
        raise ScaleRebuildContractError("cpu_selector_request_variable_overrides_mapping_required")
    if variable_overrides:
        raise ScaleRebuildContractError("cpu_selector_request_variable_overrides_must_be_empty")
    selections = request.get("selections")
    if not isinstance(selections, list):
        raise ScaleRebuildContractError("cpu_selector_request_selections_list_required")
    expected_names = [reference.qualified_name for reference in references]
    if len(selections) != len(expected_names):
        raise ScaleRebuildContractError("cpu_selector_request_selection_count_mismatch")
    expected_set = set(expected_names)
    if len(expected_set) != len(expected_names):
        raise ScaleRebuildContractError("cpu_selector_reference_names_not_unique")
    references_by_name = {reference.qualified_name: reference for reference in references}
    catalog_by_id = {function.function_id: function for function in catalog.functions}
    selected: dict[str, CatalogFunction] = {}
    normalized_selections: list[dict[str, str]] = []
    for row in selections:
        if not isinstance(row, Mapping):
            raise ScaleRebuildContractError("cpu_selector_request_selection_mapping_required")
        if set(row) != {"reference_name", "candidate_function_id"}:
            raise ScaleRebuildContractError("cpu_selector_request_selection_fields_invalid")
        reference_name = row.get("reference_name")
        candidate_id = row.get("candidate_function_id")
        if not isinstance(reference_name, str) or not reference_name:
            raise ScaleRebuildContractError("cpu_selector_request_reference_name_required")
        if not isinstance(candidate_id, str) or not candidate_id:
            raise ScaleRebuildContractError("cpu_selector_request_candidate_id_required")
        if reference_name in selected:
            raise ScaleRebuildContractError(f"cpu_selector_request_duplicate_reference:{reference_name}")
        reference = references_by_name.get(reference_name)
        if reference is None:
            raise ScaleRebuildContractError(f"cpu_selector_request_unknown_reference:{reference_name}")
        candidate = catalog_by_id.get(candidate_id)
        if candidate is None:
            raise ScaleRebuildContractError(f"cpu_selector_request_unknown_candidate:{candidate_id}")
        if candidate.parameters != reference.parameters:
            raise ScaleRebuildContractError(f"cpu_selector_request_parameter_mismatch:{reference_name}")
        if (
            candidate.semantic_sha256 != reference.semantic_sha256
            and candidate.body_sha256 != reference.body_sha256
        ):
            raise ScaleRebuildContractError(f"cpu_selector_request_candidate_not_equivalent:{reference_name}")
        selected[reference_name] = candidate
        normalized_selections.append(
            {"reference_name": reference_name, "candidate_function_id": candidate.function_id}
        )
    if set(selected) != expected_set:
        raise ScaleRebuildContractError("cpu_selector_request_reference_set_mismatch")
    normalized = {
        "schema_version": CPU_SELECTOR_REQUEST_SCHEMA,
        "operation": "random_file_rebuild",
        "input_sha256": input_sha256,
        "selections": normalized_selections,
        "variable_overrides": {},
    }
    return normalized, selected


def _compose_catalog_body_replacement(
    *,
    source_bytes: bytes,
    offsets: Sequence[int],
    reference: ReferenceFunction,
    selected: CatalogFunction,
) -> tuple[bytes, str]:
    """Copy the input header and an approved, AST-matched catalog body."""
    _, catalog_node, catalog_body = _catalog_function_parts(selected)
    _validate_recreated_body(catalog_node)
    header_end_line = reference.body_start_line - 1
    if header_end_line < reference.start_line:
        raise ScaleRebuildContractError(f"reference_header_missing:{reference.name}")
    header = _byte_span(source_bytes, offsets, reference.start_line, header_end_line)
    body = _reindent_body(
        catalog_body,
        source_indent=_body_indent_from_bytes(catalog_body),
        target_indent=reference.body_indent,
    )
    return header + body, _sha256_bytes(catalog_body)


def _production_boundary(repo_root: Path) -> dict[str, Any]:
    generation_root = repo_root / "sandbox/code/template_generations"
    pointer = repo_root / "sandbox/code/template_current.json"
    registry = repo_root / "foundation/code_templates/registry.json"
    protected = [repo_root / "foundation" / name for name in ("rid_main.py", "auto_main.py", "uml_main.py")]
    def file_state(path: Path) -> dict[str, Any]:
        return {"path": _posix(path), "exists": path.exists(), "sha256": _sha256_bytes(path.read_bytes()) if path.is_file() else None}
    generation_files = 0
    if generation_root.is_dir():
        generation_files = sum(1 for path in generation_root.rglob("*") if path.is_file())
    return {
        "registry": file_state(registry),
        "pointer": file_state(pointer),
        "generation_root": {"path": _posix(generation_root), "exists": generation_root.exists(), "file_count": generation_files},
        "protected_mains": [file_state(path) for path in protected],
    }


def _boundary_unchanged(before: Mapping[str, Any], after: Mapping[str, Any]) -> bool:
    return _stable_json(before) == _stable_json(after)


def _selection_digest(modules: Sequence[CatalogModule]) -> tuple[str, int, int, int]:
    function_ids = [function.function_id for module in modules for function in module.functions]
    request = {
        "schema_version": REBUILD_SELECTION_SCHEMA,
        "modules": [module.template_rel for module in modules],
        "functions": function_ids,
    }
    request_text = _stable_json(request)
    code_bytes = sum(module.source_bytes for module in modules)
    code_tokens = (code_bytes + 3) // 4
    request_tokens = (len(request_text.encode("utf-8")) + 3) // 4
    digest = _sha256_bytes(request_text.encode("utf-8"))
    return digest, code_tokens, request_tokens, len(function_ids)


def _compile_bytes(source_bytes: bytes, filename: str) -> dict[str, Any]:
    try:
        compile(source_bytes.decode("utf-8"), filename, "exec", dont_inherit=True)
        return {"ok": True, "error": None}
    except (SyntaxError, UnicodeDecodeError, ValueError) as exc:
        return {"ok": False, "error": f"{type(exc).__name__}:{exc}"}


def _default_rust_security_probe(output_path: Path, rebuilt: bytes) -> Mapping[str, Any]:
    """Use the existing Rust Python-write membrane for a hypothetical output."""
    try:
        try:
            from build_tools.template_builder_v1 import RustSecurityAdapter
        except ModuleNotFoundError:
            # Direct CLI execution places ``build_tools`` itself on sys.path.
            from template_builder_v1 import RustSecurityAdapter  # type: ignore

        adapter = RustSecurityAdapter(forensic_buffer="Viv deterministic template sandbox")
        return adapter.probe_python_write(
            target_path=output_path,
            content_sha256=_sha256_bytes(rebuilt),
            content_bytes=len(rebuilt),
            operation_id=f"template-rebuild-{_sha256_bytes(f'{output_path}:{time.time_ns()}'.encode())[:20]}",
        )
    except Exception as exc:
        return {
            "ok": False,
            "state": "HOLD_SECURITY",
            "reason": f"rust_security_probe_failed:{exc}",
            "target_path": _posix(output_path),
            "test_adapter": False,
        }


def rebuild_reference(
    input_path: Path,
    catalog: CandidateCatalog,
    output_path: Path,
    *,
    isolated: bool = True,
    no_publish: bool = True,
    allow_input_fallback: bool = False,
    selection_request: Mapping[str, Any] | None = None,
    write_output: bool = True,
    security_probe: SecurityProbe | None = _default_rust_security_probe,
    test_only_local_assembly: bool = False,
) -> dict[str, Any]:
    """Rebuild one reference module using canonical spans and catalog body composition."""
    if not isolated or not no_publish:
        raise ScaleRebuildContractError("rebuild_requires_isolated_and_no_publish")
    input_path = input_path.resolve(strict=False)
    output_path = output_path.resolve(strict=False)
    if not input_path.is_file() or _is_reparse_point(input_path):
        raise ScaleRebuildContractError(f"reference_input_invalid:{input_path}")
    if _same_path(input_path, output_path):
        raise ScaleRebuildContractError("reference_output_must_differ_from_input")
    if _is_reparse_point(output_path) or _is_reparse_point(output_path.parent):
        raise ScaleRebuildContractError(f"reference_output_reparse_path:{output_path}")
    protected = {
        catalog.repo_root / "foundation/code_templates/registry.json",
        catalog.repo_root / "sandbox/code/template_current.json",
        catalog.repo_root / "foundation/rid_main.py",
        catalog.repo_root / "foundation/auto_main.py",
        catalog.repo_root / "foundation/uml_main.py",
    }
    if output_path in {item.resolve(strict=False) for item in protected}:
        raise ScaleRebuildContractError("reference_output_protected_path")
    if catalog.repo_root / "foundation/code_templates/source" in output_path.parents:
        raise ScaleRebuildContractError("reference_output_inside_source_templates")
    if catalog.repo_root / "sandbox/code/template_generations" in output_path.parents:
        raise ScaleRebuildContractError("reference_output_inside_production_generations")

    source_bytes = input_path.read_bytes()
    _parse_source(input_path, source_bytes)
    offsets = _line_offsets(source_bytes)
    references = _reference_functions(input_path, source_bytes)
    normalized_selection: dict[str, Any] | None = None
    selected_by_reference: dict[str, CatalogFunction] | None = None
    selection_request_sha256: str | None = None
    if selection_request is not None:
        try:
            normalized_selection, selected_by_reference = _validate_cpu_selector_request(
                selection_request,
                input_sha256=_sha256_bytes(source_bytes),
                references=references,
                catalog=catalog,
            )
        except ScaleRebuildContractError as exc:
            return {
                "ok": False,
                "state": "HOLD_SELECTION_REQUEST",
                "input_path": _posix(input_path),
                "output_path": _posix(output_path),
                "input_sha256": _sha256_bytes(source_bytes),
                "function_count": len(references),
                "selection_request_schema": CPU_SELECTOR_REQUEST_SCHEMA,
                "selection_request_rejected": True,
                "selection_request_error": str(exc),
                "synthesis_performed": False,
                "output_written": False,
                "generated_files_created": False,
                "active_pointer_changed": False,
                "sandbox_candidate": False,
                "human_approval_required_before_template_insertion": False,
                "template_insertion_performed": False,
                "rust_security": None,
                "test_only_local_assembly": bool(test_only_local_assembly),
            }
        selection_request_sha256 = _selector_request_hash(normalized_selection)
    selection_metadata = {
        "selection_request_schema": CPU_SELECTOR_REQUEST_SCHEMA if normalized_selection is not None else None,
        "selection_request": normalized_selection,
        "selection_request_sha256": selection_request_sha256,
    }
    replacements: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    body_recreation_holds: list[dict[str, Any]] = []
    for reference in references:
        reference_span = _byte_span(source_bytes, offsets, reference.start_line, reference.end_line)
        if selected_by_reference is not None:
            selected = selected_by_reference[reference.qualified_name]
            if selected.semantic_sha256 == reference.semantic_sha256:
                canonical = _catalog_function_bytes(selected)
                replacements.append(
                    {
                        "reference": reference,
                        "replacement": canonical,
                        "mode": "catalog_exact_span" if selected.span_sha256 == reference.span_sha256 else "catalog_semantic_span",
                        "catalog_function_id": selected.function_id,
                        "catalog_template_path": _posix(selected.template_path),
                        "catalog_body_sha256": selected.body_sha256,
                    }
                )
                continue
            try:
                body_replacement, catalog_body_sha256 = _compose_catalog_body_replacement(
                    source_bytes=source_bytes,
                    offsets=offsets,
                    reference=reference,
                    selected=selected,
                )
            except ScaleRebuildContractError as exc:
                body_recreation_holds.append(
                    {
                        "name": reference.name,
                        "qualified_name": reference.qualified_name,
                        "reason": str(exc),
                        "catalog_function_id": selected.function_id,
                        "catalog_template_path": _posix(selected.template_path),
                    }
                )
                missing.append(
                    {
                        "name": reference.name,
                        "qualified_name": reference.qualified_name,
                        "source_start_line": reference.start_line,
                        "source_end_line": reference.end_line,
                        "semantic_sha256": reference.semantic_sha256,
                        "body_sha256": reference.body_sha256,
                        "source_span_sha256": reference.span_sha256,
                        "fallback": "hold_or_copy_input_exact_span_with_explicit_authoring_flag",
                        "body_recreation": "rejected",
                    }
                )
                continue
            replacements.append(
                {
                    "reference": reference,
                    "replacement": body_replacement,
                    "mode": "catalog_body_recreation",
                    "catalog_function_id": selected.function_id,
                    "catalog_template_path": _posix(selected.template_path),
                    "catalog_body_sha256": catalog_body_sha256,
                }
            )
            continue
        selected = _select_catalog_function(
            reference,
            reference.span_sha256,
            catalog,
            reference_path=input_path,
        )
        if selected is None:
            body_selected = _select_catalog_body_function(
                reference,
                catalog,
                reference_path=input_path,
            )
            if body_selected is not None:
                try:
                    body_replacement, catalog_body_sha256 = _compose_catalog_body_replacement(
                        source_bytes=source_bytes,
                        offsets=offsets,
                        reference=reference,
                        selected=body_selected,
                    )
                except ScaleRebuildContractError as exc:
                    body_recreation_holds.append(
                        {
                            "name": reference.name,
                            "qualified_name": reference.qualified_name,
                            "reason": str(exc),
                            "catalog_function_id": body_selected.function_id,
                            "catalog_template_path": _posix(body_selected.template_path),
                        }
                    )
                else:
                    replacements.append(
                        {
                            "reference": reference,
                            "replacement": body_replacement,
                            "mode": "catalog_body_recreation",
                            "catalog_function_id": body_selected.function_id,
                            "catalog_template_path": _posix(body_selected.template_path),
                            "catalog_body_sha256": catalog_body_sha256,
                        }
                    )
                    continue
            missing_row = {
                "name": reference.name,
                "qualified_name": reference.qualified_name,
                "source_start_line": reference.start_line,
                "source_end_line": reference.end_line,
                "semantic_sha256": reference.semantic_sha256,
                "body_sha256": reference.body_sha256,
                "source_span_sha256": reference.span_sha256,
                "fallback": "hold_or_copy_input_exact_span_with_explicit_authoring_flag",
            }
            if body_selected is not None:
                missing_row["body_recreation"] = "rejected"
            missing.append(missing_row)
            if not allow_input_fallback:
                continue
            replacements.append(
                {
                    "reference": reference,
                    "replacement": reference_span,
                    "mode": "input_exact_fallback",
                    "catalog_function_id": None,
                    "catalog_template_path": None,
                    "catalog_body_sha256": None,
                }
            )
            continue
        canonical = _catalog_function_bytes(selected)
        replacements.append(
            {
                "reference": reference,
                "replacement": canonical,
                "mode": "catalog_exact_span" if selected.span_sha256 == reference.span_sha256 else "catalog_semantic_span",
                "catalog_function_id": selected.function_id,
                "catalog_template_path": _posix(selected.template_path),
                "catalog_body_sha256": selected.body_sha256,
            }
        )

    if missing and not allow_input_fallback:
        return {
            "ok": False,
            "state": "HOLD_MISSING_FUNCTIONS",
            "input_path": _posix(input_path),
            "input_sha256": _sha256_bytes(source_bytes),
            **selection_metadata,
            "builtin_surface_sha256": catalog.builtin_surface_sha256,
            "function_count": len(references),
            "catalog_resolved_count": len(replacements),
            "catalog_body_recreated_count": 0,
            "input_fallback_count": 0,
            "missing_functions": missing,
            "body_recreation_holds": body_recreation_holds,
            "synthesis_performed": False,
            "output_written": False,
            "generated_files_created": False,
            "active_pointer_changed": False,
            "sandbox_candidate": False,
            "human_approval_required_before_template_insertion": bool(body_recreation_holds),
            "template_insertion_performed": False,
            "rust_security": None,
            "test_only_local_assembly": bool(test_only_local_assembly),
        }

    rebuilt = source_bytes
    for item in sorted(replacements, key=lambda row: row["reference"].start_offset, reverse=True):
        reference = item["reference"]
        rebuilt = rebuilt[: reference.start_offset] + item["replacement"] + rebuilt[reference.end_offset :]
    compile_result = _compile_bytes(rebuilt, str(output_path))
    output_written = False
    output_sha256: str | None = _sha256_bytes(rebuilt)
    modes = {str(item["mode"]) for item in replacements}
    security_report: Mapping[str, Any] | None = None
    if compile_result.get("ok") and write_output and security_probe is not None:
        security_report = dict(security_probe(output_path, rebuilt))
        if not security_report.get("ok") and not test_only_local_assembly:
            return {
                "ok": False,
                "state": "HOLD_SECURITY",
                "input_path": _posix(input_path),
                "output_path": _posix(output_path),
                "input_sha256": _sha256_bytes(source_bytes),
                **selection_metadata,
                "output_sha256": output_sha256,
                "builtin_surface_sha256": catalog.builtin_surface_sha256,
                "output_equals_input": output_sha256 == _sha256_bytes(source_bytes),
                "function_count": len(references),
                "catalog_resolved_count": sum(1 for item in replacements if item["mode"].startswith("catalog_")),
                "catalog_body_recreated_count": sum(1 for item in replacements if item["mode"] == "catalog_body_recreation"),
                "input_fallback_count": sum(1 for item in replacements if item["mode"] == "input_exact_fallback"),
                "missing_functions": missing,
                "body_recreation_holds": body_recreation_holds,
                "synthesis_performed": False,
                "compile": compile_result,
                "output_written": False,
                "generated_files_created": False,
                "active_pointer_changed": False,
                "sandbox_candidate": True,
                "test_only_local_assembly": False,
                "security_hold_expected": False,
                "human_approval_required_before_template_insertion": bool(
                    "input_exact_fallback" in modes or "catalog_body_recreation" in modes
                ),
                "template_insertion_performed": False,
                "rust_security": dict(security_report),
                "replacements": [
                    {
                        "name": item["reference"].name,
                        "qualified_name": item["reference"].qualified_name,
                        "source_start_line": item["reference"].start_line,
                        "source_end_line": item["reference"].end_line,
                        "mode": item["mode"],
                        "catalog_function_id": item["catalog_function_id"],
                        "catalog_template_path": item["catalog_template_path"],
                        "catalog_body_sha256": item.get("catalog_body_sha256"),
                        "replacement_sha256": _sha256_bytes(item["replacement"]),
                    }
                    for item in replacements
                ],
            }
    if write_output:
        if output_path.exists():
            raise ScaleRebuildContractError(f"reference_output_exists:{output_path}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(rebuilt)
        output_written = True
        written = output_path.read_bytes()
        output_sha256 = _sha256_bytes(written)
        if written != rebuilt:
            raise ScaleRebuildContractError("reference_output_readback_mismatch")
    if "input_exact_fallback" in modes:
        state = "PASS_WITH_INPUT_FALLBACK"
    elif "catalog_body_recreation" in modes:
        state = "PASS_WITH_CATALOG_BODY_RECREATION"
    else:
        state = "PASS_CANONICAL_REBUILD"
    return {
        "ok": bool(compile_result.get("ok")) and (not write_output or output_written),
        "state": state if compile_result.get("ok") else "HOLD_COMPILE",
        "input_path": _posix(input_path),
        "output_path": _posix(output_path),
        "input_sha256": _sha256_bytes(source_bytes),
        **selection_metadata,
        "output_sha256": output_sha256,
        "builtin_surface_sha256": catalog.builtin_surface_sha256,
        "output_equals_input": output_sha256 == _sha256_bytes(source_bytes),
        "function_count": len(references),
        "catalog_resolved_count": sum(1 for item in replacements if item["mode"].startswith("catalog_")),
        "catalog_body_recreated_count": sum(1 for item in replacements if item["mode"] == "catalog_body_recreation"),
        "input_fallback_count": sum(1 for item in replacements if item["mode"] == "input_exact_fallback"),
        "missing_functions": missing,
        "body_recreation_holds": body_recreation_holds,
        "synthesis_performed": False,
        "compile": compile_result,
        "output_written": output_written,
        "generated_files_created": output_written,
        "active_pointer_changed": False,
        "sandbox_candidate": True,
        "human_approval_required_before_template_insertion": bool(
            "input_exact_fallback" in modes or "catalog_body_recreation" in modes
        ),
        "template_insertion_performed": False,
        "rust_security": dict(security_report) if security_report is not None else None,
        "test_only_local_assembly": bool(test_only_local_assembly),
        "security_hold_expected": bool(
            test_only_local_assembly and security_report is not None and not security_report.get("ok")
        ),
        "replacements": [
            {
                "name": item["reference"].name,
                "qualified_name": item["reference"].qualified_name,
                "source_start_line": item["reference"].start_line,
                "source_end_line": item["reference"].end_line,
                "mode": item["mode"],
                "catalog_function_id": item["catalog_function_id"],
                "catalog_template_path": item["catalog_template_path"],
                "catalog_body_sha256": item.get("catalog_body_sha256"),
                "replacement_sha256": _sha256_bytes(item["replacement"]),
            }
            for item in replacements
        ],
    }


def _copy_case(modules: Sequence[CatalogModule], output_root: Path) -> dict[str, Any]:
    started = time.perf_counter()
    output_root.mkdir(parents=True, exist_ok=True)
    copied: list[dict[str, Any]] = []
    compile_failures: list[str] = []
    total_bytes = 0
    function_count = 0
    for module in modules:
        source_bytes = module.template_path.read_bytes()
        destination = output_root / Path(module.template_rel).name
        # Names in the migration catalog are unique, but retain the path in the
        # digest so a future catalog collision cannot hide a wrong copy.
        if destination.exists():
            raise ScaleRebuildContractError(f"scale_output_collision:{destination}")
        destination.write_bytes(source_bytes)
        output_bytes = destination.read_bytes()
        if output_bytes != source_bytes or _sha256_bytes(output_bytes) != module.template_sha256:
            raise ScaleRebuildContractError(f"scale_copy_hash_mismatch:{module.template_rel}")
        compile_result = _compile_bytes(output_bytes, str(destination))
        if not compile_result["ok"]:
            compile_failures.append(module.template_rel)
        total_bytes += len(source_bytes)
        function_count += module.function_count
        copied.append({"path": module.template_rel, "sha256": module.template_sha256, "bytes": len(source_bytes)})
    copied_digest = _sha256_bytes(_stable_json(copied).encode("utf-8"))
    elapsed = max(time.perf_counter() - started, 1e-9)
    request_digest, code_tokens, request_tokens, request_functions = _selection_digest(modules)
    return {
        "module_count": len(modules),
        "function_count": function_count,
        "selection_function_count": request_functions,
        "source_bytes": total_bytes,
        "generated_bytes": total_bytes,
        "exact_byte_matches": len(copied),
        "compile_failures": compile_failures,
        "copy_digest": copied_digest,
        "selection_request_sha256": request_digest,
        "ordinary_code_estimated_tokens": code_tokens,
        "structured_selection_estimated_tokens": request_tokens,
        "estimated_tokens_saved_per_build": max(0, code_tokens - request_tokens),
        "elapsed_seconds": round(elapsed, 6),
        "bytes_per_second": round(total_bytes / elapsed, 3),
    }


def run_scale_test(
    *,
    repo_root: Path | None = None,
    manifest_path: Path | None = None,
    function_index_path: Path | None = None,
    case_sizes: Sequence[int] = (1, 10, 100, 310),
    repeats: int = 2,
    seed: int = 42,
    receipt_dir: Path | None = None,
) -> dict[str, Any]:
    """Benchmark candidate assembly at 1/10/100/all modules in private roots."""
    root = (repo_root or _repo_root()).resolve(strict=False)
    before = _production_boundary(root)
    run_id = f"scale_{_sha256_bytes(f'{_utc()}:{os.getpid()}:{time.time_ns()}'.encode())[:20]}"
    errors: list[str] = []
    catalog: CandidateCatalog | None = None
    repeated_runs: list[list[dict[str, Any]]] = []
    random_rebuild: dict[str, Any] = {}
    try:
        if not isinstance(repeats, int) or repeats <= 0:
            raise ScaleRebuildContractError("scale_repeats_must_be_positive")
        catalog = load_candidate_catalog(
            repo_root=root,
            manifest_path=manifest_path,
            function_index_path=function_index_path,
        )
        if not catalog.modules:
            raise ScaleRebuildContractError("candidate_catalog_empty")
        sizes = sorted({max(1, int(value)) for value in case_sizes})
        sizes = [min(value, len(catalog.modules)) for value in sizes]
        sizes = sorted(set(sizes))
        with tempfile.TemporaryDirectory(prefix="viv-template-scale-") as temporary:
            temporary_root = Path(temporary)
            for repeat in range(repeats):
                current: list[dict[str, Any]] = []
                for size in sizes:
                    selected = catalog.modules[:size]
                    current.append(_copy_case(selected, temporary_root / f"repeat_{repeat + 1}" / f"modules_{size}"))
                repeated_runs.append(current)
            rng = random.Random(seed)
            selected_module = rng.choice(catalog.modules)
            rebuild_output = temporary_root / "random_rebuild" / Path(selected_module.template_rel).name
            random_rebuild = rebuild_reference(
                selected_module.template_path,
                catalog,
                rebuild_output,
                isolated=True,
                no_publish=True,
                allow_input_fallback=False,
                write_output=True,
                test_only_local_assembly=True,
            )
            random_rebuild["selected_random_seed"] = seed
            random_rebuild["selected_random_template_path"] = selected_module.template_rel
            random_rebuild["temporary_output_only"] = True
    except Exception as exc:
        errors.append(str(exc))
    after = _production_boundary(root)
    boundary_unchanged = _boundary_unchanged(before, after)
    def normalized_run(run: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        # Runtime measurements are evidence, but not deterministic build
        # identity.  Hashes, counts, compile outcomes, and token estimates are
        # the comparison surface.
        volatile = {"elapsed_seconds", "bytes_per_second"}
        return [
            {key: value for key, value in dict(case).items() if key not in volatile}
            for case in run
        ]

    deterministic = bool(repeated_runs) and all(
        _stable_json(normalized_run(run)) == _stable_json(normalized_run(repeated_runs[0]))
        for run in repeated_runs[1:]
    )
    case_results = repeated_runs[0] if repeated_runs else []
    cases_passed = bool(case_results) and all(
        item["exact_byte_matches"] == item["module_count"] and not item["compile_failures"]
        for item in case_results
    )
    rebuild_passed = bool(random_rebuild.get("ok")) and bool(random_rebuild.get("compile", {}).get("ok"))
    final_state = "PASS_SCALE_AND_REBUILD" if not errors and cases_passed and deterministic and rebuild_passed and boundary_unchanged else "FAIL"
    catalog_summary = {
        "manifest_path": _posix(catalog.manifest_path) if catalog else None,
        "manifest_sha256": catalog.manifest_sha256 if catalog else None,
        "function_index_path": _posix(catalog.function_index_path) if catalog else None,
        "function_index_sha256": catalog.function_index_sha256 if catalog else None,
        "module_count": len(catalog.modules) if catalog else 0,
        "function_count": len(catalog.functions) if catalog else 0,
        "domain_count": len({module.domain for module in catalog.modules}) if catalog else 0,
        "active_registry_updated": False,
        "human_review_required_before_activation": True,
    }
    receipt: dict[str, Any] = {
        "schema_version": SCALE_RECEIPT_SCHEMA,
        "run_id": run_id,
        "created_utc": _utc(),
        "seed": seed,
        "repeats": repeats,
        "catalog": catalog_summary,
        "scale_cases": case_results,
        "repeated_runs": repeated_runs,
        "deterministic_repeated_hashes": deterministic,
        "random_rebuild": random_rebuild,
        "production_boundary_before": before,
        "production_boundary_after": after,
        "production_boundary_unchanged": boundary_unchanged,
        "generated_files_created": False,
        "active_pointer_changed": False,
        "synthesis_performed": False,
        "errors": errors,
        "final_state": final_state,
    }
    receipt_path: Path | None = None
    receipt_hash: str | None = None
    if receipt_dir is not None:
        receipt_dir = receipt_dir.resolve(strict=False)
        if _is_reparse_point(receipt_dir):
            raise ScaleRebuildContractError("scale_receipt_dir_reparse_path")
        receipt_dir.mkdir(parents=True, exist_ok=True)
        receipt_path = receipt_dir / f"{run_id}.json"
        receipt_path.write_bytes(_json_bytes(receipt))
        receipt_hash = _sha256_bytes(receipt_path.read_bytes())
    return {
        "ok": final_state == "PASS_SCALE_AND_REBUILD",
        "state": final_state,
        "schema_version": SCALE_RECEIPT_SCHEMA,
        "run_id": run_id,
        "catalog": catalog_summary,
        "scale_cases": case_results,
        "deterministic_repeated_hashes": deterministic,
        "random_rebuild": random_rebuild,
        "production_boundary_unchanged": boundary_unchanged,
        "generated_files_created": False,
        "active_pointer_changed": False,
        "receipt": {"path": _posix(receipt_path) if receipt_path else None, "sha256": receipt_hash},
        "errors": errors,
    }


def write_rebuild_receipt(
    report: Mapping[str, Any],
    *,
    receipt_dir: Path,
    input_path: Path,
    catalog: CandidateCatalog,
) -> dict[str, Any]:
    receipt_dir = receipt_dir.resolve(strict=False)
    if _is_reparse_point(receipt_dir):
        raise ScaleRebuildContractError("rebuild_receipt_dir_reparse_path")
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_id = f"rebuild_{_sha256_bytes(f'{_utc()}:{os.getpid()}:{time.time_ns()}'.encode())[:20]}"
    payload: dict[str, Any] = {
        "schema_version": REBUILD_RECEIPT_SCHEMA,
        "receipt_id": receipt_id,
        "created_utc": _utc(),
        "input_path": _posix(input_path),
        "catalog_manifest_sha256": catalog.manifest_sha256,
        "catalog_function_index_sha256": catalog.function_index_sha256,
        "builtin_surface": _builtin_surface_receipt(catalog.repo_root),
        "selection_request_schema": REBUILD_SELECTION_SCHEMA,
        "synthesis_performed": False,
        "report": dict(report),
    }
    path = receipt_dir / f"{receipt_id}.json"
    path.write_bytes(_json_bytes(payload))
    return {"path": _posix(path), "sha256": _sha256_bytes(path.read_bytes()), "schema_version": REBUILD_RECEIPT_SCHEMA}


def run_rebuild_cli(
    *,
    input_path: Path,
    output_path: Path,
    repo_root: Path | None = None,
    manifest_path: Path | None = None,
    function_index_path: Path | None = None,
    receipt_dir: Path | None = None,
    isolated: bool = False,
    no_publish: bool = False,
    allow_input_fallback: bool = False,
    selection_request: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    root = (repo_root or _repo_root()).resolve(strict=False)
    catalog = load_candidate_catalog(repo_root=root, manifest_path=manifest_path, function_index_path=function_index_path)
    report = rebuild_reference(
        input_path,
        catalog,
        output_path,
        isolated=isolated,
        no_publish=no_publish,
        allow_input_fallback=allow_input_fallback,
        selection_request=selection_request,
        write_output=True,
        security_probe=_default_rust_security_probe,
    )
    report = dict(report)
    report["receipt"] = (
        write_rebuild_receipt(report, receipt_dir=receipt_dir, input_path=input_path, catalog=catalog)
        if receipt_dir is not None
        else None
    )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="template_scale_rebuild_v1")
    parser.add_argument("--repo-root", default="")
    parser.add_argument("--manifest", default="")
    parser.add_argument("--function-index", default="")
    sub = parser.add_subparsers(dest="command", required=True)
    scale = sub.add_parser("scale-test", help="benchmark the candidate catalog in private temporary roots")
    scale.add_argument("--case-sizes", default="1,10,100,310")
    scale.add_argument("--repeats", type=int, default=2)
    scale.add_argument("--seed", type=int, default=42)
    scale.add_argument("--receipt-dir", default="")
    rebuild = sub.add_parser("rebuild", help="rebuild a reference Python file from exact catalog spans")
    rebuild.add_argument("--input", required=True)
    rebuild.add_argument("--output", required=True)
    rebuild.add_argument("--receipt-dir", default="")
    rebuild.add_argument("--isolated", action="store_true", help="mandatory safety guard")
    rebuild.add_argument("--no-publish", action="store_true", help="mandatory safety guard")
    rebuild.add_argument(
        "--allow-input-fallback",
        action="store_true",
        help="copy an absent function's exact input span and record it as an authoring candidate",
    )
    random_rebuild = sub.add_parser(
        "rebuild-random",
        help="rebuild a supplied Python file from catalog spans or deterministic catalog-body recreation",
    )
    random_rebuild.add_argument("--input", required=True)
    random_rebuild.add_argument("--output", required=True)
    random_rebuild.add_argument("--receipt-dir", default="")
    random_rebuild.add_argument("--isolated", action="store_true", help="mandatory safety guard")
    random_rebuild.add_argument("--no-publish", action="store_true", help="mandatory safety guard")
    sub.add_parser("builtin-surface", help="verify the read-only Python built-in primitive contract")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    root = Path(args.repo_root).resolve(strict=False) if args.repo_root else _repo_root()
    manifest = Path(args.manifest).resolve(strict=False) if args.manifest else None
    function_index = Path(args.function_index).resolve(strict=False) if args.function_index else None
    try:
        if args.command == "scale-test":
            sizes = tuple(int(item.strip()) for item in str(args.case_sizes).split(",") if item.strip())
            report = run_scale_test(
                repo_root=root,
                manifest_path=manifest,
                function_index_path=function_index,
                case_sizes=sizes,
                repeats=int(args.repeats),
                seed=int(args.seed),
                receipt_dir=Path(args.receipt_dir) if args.receipt_dir else None,
            )
        elif args.command == "builtin-surface":
            report = builtin_surface_status(repo_root=root)
        elif args.command == "rebuild":
            report = run_rebuild_cli(
                input_path=Path(args.input),
                output_path=Path(args.output),
                repo_root=root,
                manifest_path=manifest,
                function_index_path=function_index,
                receipt_dir=Path(args.receipt_dir) if args.receipt_dir else None,
                isolated=bool(args.isolated),
                no_publish=bool(args.no_publish),
                allow_input_fallback=bool(args.allow_input_fallback),
            )
        else:
            report = run_rebuild_cli(
                input_path=Path(args.input),
                output_path=Path(args.output),
                repo_root=root,
                manifest_path=manifest,
                function_index_path=function_index,
                receipt_dir=Path(args.receipt_dir) if args.receipt_dir else None,
                isolated=bool(args.isolated),
                no_publish=bool(args.no_publish),
                allow_input_fallback=False,
            )
    except (ScaleRebuildContractError, OSError, ValueError) as exc:
        report = {"ok": False, "state": "HOLD", "reason": str(exc)}
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
