"""Deterministically copy existing AIOS function modules into domain templates.

This is a one-time authoring/migration tool, not an AIOS runtime import.  It
does not synthesize or format Python.  It reads the existing foundation source
bytes, discovers functions and call relationships with the AST, copies each
selected source module byte-for-byte into a categorized template directory,
and writes an appendable manifest containing the exact source/template line
ranges, hashes, and dependency closure.

The generated catalog is deliberately outside the approved runtime registry.
Human review can promote a migrated file into the strict active template
registry after its variables/main/submain contract has been reviewed.  This
keeps a bulk migration from silently changing live AIOS behavior.
"""
from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
from typing import Any, Iterable


SCHEMA_VERSION = "viv_aios_function_template_migration_v1"
MANIFEST_NAME = "AIOS_FUNCTION_TEMPLATE_MIGRATION.json"
DOMAIN_INDEX_NAME = "domain_index.json"
FUNCTION_INDEX_NAME = "function_index.json"


@dataclass(frozen=True)
class MigrationPaths:
    repo_root: Path
    foundation_root: Path
    output_root: Path
    artifact_root: Path

    @classmethod
    def default(cls) -> "MigrationPaths":
        repo_root = Path(__file__).resolve().parents[1]
        return cls(
            repo_root=repo_root,
            foundation_root=repo_root / "foundation",
            output_root=repo_root / "foundation" / "code_templates" / "source" / "migrated_domains",
            artifact_root=repo_root / "foundation" / "artifacts" / "auto" / "code_templates" / "migration",
        )


@dataclass(frozen=True)
class FunctionRecord:
    name: str
    qualified_name: str
    kind: str
    source_start_line: int
    source_end_line: int
    decorated_start_line: int
    parameters: tuple[str, ...]
    called_symbols: tuple[str, ...]
    direct_calls: tuple[str, ...]
    used_function_closure: tuple[str, ...]
    resolved_function_calls: tuple[str, ...]
    resolved_function_closure: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "qualified_name": self.qualified_name,
            "kind": self.kind,
            "source_start_line": self.source_start_line,
            "source_end_line": self.source_end_line,
            "template_start_line": self.source_start_line,
            "template_end_line": self.source_end_line,
            "decorated_start_line": self.decorated_start_line,
            "parameters": list(self.parameters),
            "called_symbols": list(self.called_symbols),
            "direct_calls": list(self.direct_calls),
            "used_function_closure": list(self.used_function_closure),
            "resolved_function_calls": list(self.resolved_function_calls),
            "resolved_function_closure": list(self.resolved_function_closure),
        }


@dataclass(frozen=True)
class ModuleRecord:
    source_path: Path
    template_path: Path
    module_name: str
    domain: str
    source_sha256: str
    template_sha256: str
    source_bytes: int
    functions: tuple[FunctionRecord, ...]
    imported_modules: tuple[str, ...]
    top_level_effects: tuple[str, ...]
    omitted_nodes: tuple[str, ...]
    variable_candidates: tuple[dict[str, Any], ...]
    import_bindings: tuple[tuple[str, str], ...]
    resolved_module_dependencies: tuple[str, ...]

    def as_dict(self, *, repo_root: Path) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "source_path": _relative_posix(self.source_path, repo_root),
            "template_path": _relative_posix(self.template_path, repo_root),
            "module_name": self.module_name,
            "source_sha256": self.source_sha256,
            "template_sha256": self.template_sha256,
            "source_bytes": self.source_bytes,
            "functions": [row.as_dict() for row in self.functions],
            "function_count": len(self.functions),
            "imported_modules": list(self.imported_modules),
            "import_bindings": {name: target for name, target in self.import_bindings},
            "resolved_module_dependencies": list(self.resolved_module_dependencies),
            "top_level_effects": list(self.top_level_effects),
            "omitted_nodes": list(self.omitted_nodes),
            "variable_candidates": list(self.variable_candidates),
            "byte_exact_copy": self.source_sha256 == self.template_sha256,
            "registry_state": "not_registered",
        }


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def _relative_posix(path: Path, root: Path) -> str:
    return path.resolve(strict=False).relative_to(root.resolve(strict=False)).as_posix()


def _node_end(node: ast.AST) -> int:
    end = getattr(node, "end_lineno", None)
    if not isinstance(end, int):
        raise ValueError(f"missing_end_lineno:{type(node).__name__}")
    return end


def _decorated_start(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    starts = [int(node.lineno)]
    starts.extend(int(item.lineno) for item in node.decorator_list if isinstance(getattr(item, "lineno", None), int))
    return min(starts)


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        parts: list[str] = []
        cursor: ast.AST | None = func
        while isinstance(cursor, ast.Attribute):
            parts.append(cursor.attr)
            cursor = cursor.value
        if isinstance(cursor, ast.Name):
            parts.append(cursor.id)
        return ".".join(reversed(parts))
    return "<dynamic>"


def _function_kind(name: str) -> str:
    if name == "main":
        return "main"
    if name.startswith("sub_main_"):
        return "submain"
    return "function"


def categorize_module(path: Path) -> str:
    """Classify an existing foundation module without importing it."""
    name = path.stem.casefold()
    if path.name.casefold() in {"rid_main.py", "auto_main.py", "uml_main.py"}:
        return path.stem.removesuffix("_main")
    prefixes = (
        ("aios_adapter_", "adapters"),
        ("aios_", "aios"),
        ("cpu_", "cpu"),
        ("gpu_", "gpu"),
        ("node_", "federation"),
        ("knowledge_", "knowledge"),
        ("growth_", "growth"),
        ("evaluator_", "evaluation"),
        ("aifl_", "aifl"),
        ("rid_", "rid"),
        ("master_rid", "rid"),
        ("auto_", "auto"),
        ("uml_", "uml"),
        ("security", "security"),
        ("backup", "security"),
        ("integrity", "security"),
        ("training", "training"),
        ("model", "model"),
    )
    for prefix, domain in prefixes:
        if name.startswith(prefix):
            return domain
    if name.endswith("_core") or name == "main_core":
        return "cores"
    if "memory" in name or "dream" in name:
        return "cognition"
    if "token" in name or "uml" in name:
        return "uml"
    return name.split("_", 1)[0] or "uncategorized"


def _source_files(paths: MigrationPaths) -> list[Path]:
    requested = [paths.foundation_root / name for name in ("rid_main.py", "auto_main.py", "uml_main.py")]
    lib_root = paths.foundation_root / "lib"
    if lib_root.is_dir():
        requested.extend(sorted(lib_root.rglob("*.py")))
    files: list[Path] = []
    seen: set[str] = set()
    excluded_parts = {"__pycache__", "code_templates"}
    excluded_names = {"__init__.py", "code_template_runtime.py", "viv_python_writer.py"}
    for path in requested:
        if not path.is_file():
            continue
        if any(part in excluded_parts for part in path.parts) or path.name in excluded_names:
            continue
        key = str(path.resolve(strict=False)).casefold()
        if key in seen:
            continue
        seen.add(key)
        if path.is_symlink():
            raise RuntimeError(f"reparse_or_symlink_source:{path}")
        files.append(path)
    return files


def _module_name(path: Path, *, foundation_root: Path) -> str:
    return ".".join(path.resolve(strict=False).relative_to(foundation_root.resolve(strict=False)).with_suffix("").parts)


def _resolve_relative_module(module_name: str, level: int, imported: str | None) -> str:
    if level == 0:
        return imported or ""
    parts = module_name.split(".")
    package = parts[:-1]
    package = package[: max(0, len(package) - (level - 1))]
    if imported:
        package.extend(part for part in imported.split(".") if part)
    return ".".join(package)


def _import_bindings(path: Path, source_text: str, *, foundation_root: Path) -> tuple[tuple[str, str], ...]:
    tree = ast.parse(source_text, filename=str(path), type_comments=True)
    module_name = _module_name(path, foundation_root=foundation_root)
    bindings: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname or alias.name.split(".", 1)[0]
                bindings[local_name] = alias.name
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_relative_module(module_name, int(node.level), node.module)
            for alias in node.names:
                if alias.name == "*":
                    continue
                local_name = alias.asname or alias.name
                bindings[local_name] = f"{base}.{alias.name}" if base else alias.name
    return tuple(sorted(bindings.items()))


def _module_analysis(path: Path, source_text: str) -> tuple[
    dict[str, tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]],
    dict[str, set[str]],
    dict[str, set[str]],
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
]:
    tree = ast.parse(source_text, filename=str(path), type_comments=True)
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    def qualified_name(node: ast.AST) -> str:
        names: list[str] = []
        cursor: ast.AST | None = node
        while cursor is not None:
            if isinstance(cursor, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.append(cursor.name)
            cursor = parents.get(cursor)
        return ".".join(reversed(names))

    functions = {
        qualified_name(node): (node.name, node)
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    short_names: dict[str, list[str]] = {}
    for qualified, (name, _) in functions.items():
        short_names.setdefault(name, []).append(qualified)
    direct_calls: dict[str, set[str]] = {qualified: set() for qualified in functions}
    called_symbols: dict[str, set[str]] = {qualified: set() for qualified in functions}
    for qualified, (name, node) in functions.items():
        for call in ast.walk(node):
            if isinstance(call, ast.Call):
                called = _call_name(call)
                called_symbols[qualified].add(called)
                if "." not in called and called in short_names:
                    # Prefer the function in the same lexical module.  A
                    # duplicate short name is retained as an ambiguous
                    # reference rather than silently selecting a different
                    # function body.
                    direct_calls[qualified].update(short_names[called])
    imported_modules: list[str] = []
    omitted_nodes: list[str] = []
    top_level_effects: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported_modules.append("." * node.level + (node.module or ""))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Assign, ast.AnnAssign)):
            if isinstance(node, ast.ClassDef):
                omitted_nodes.append(f"class:{node.name}:{node.lineno}-{_node_end(node)}")
        else:
            label = f"{type(node).__name__}:{getattr(node, 'lineno', '?')}-{_node_end(node)}"
            top_level_effects.append(label)
            omitted_nodes.append(label)
    return functions, direct_calls, called_symbols, tuple(sorted(set(imported_modules))), tuple(top_level_effects), tuple(omitted_nodes)


def _module_variable_candidates(source_text: str, *, path: Path) -> tuple[dict[str, Any], ...]:
    """Index existing module-level assignments without changing their bytes."""
    tree = ast.parse(source_text, filename=str(path), type_comments=True)
    rows: list[dict[str, Any]] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = [target.id for target in node.targets if isinstance(target, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
        else:
            continue
        if not targets:
            continue
        rows.append(
            {
                "names": targets,
                "source_start_line": int(node.lineno),
                "source_end_line": _node_end(node),
                "template_start_line": int(node.lineno),
                "template_end_line": _node_end(node),
                "literal": isinstance(getattr(node, "value", None), (ast.Constant, ast.Dict, ast.List, ast.Tuple, ast.Set)),
            }
        )
    return tuple(rows)


def _closure(root: str, direct_calls: dict[str, set[str]]) -> tuple[str, ...]:
    found: set[str] = set()
    stack = [root]
    while stack:
        current = stack.pop()
        if current in found:
            continue
        found.add(current)
        stack.extend(sorted(direct_calls.get(current, set()), reverse=True))
    return tuple(sorted(found))


def _template_filename(source_path: Path, repo_root: Path) -> str:
    rel = source_path.resolve(strict=False).relative_to(repo_root.resolve(strict=False))
    parts = list(rel.with_suffix("").parts)
    # The source modules are kept in separate domain directories, so a stable
    # source-relative name prevents collisions without changing function text.
    return "__".join(parts) + ".py"


def _module_record(path: Path, paths: MigrationPaths, domain: str) -> ModuleRecord:
    source_bytes = path.read_bytes()
    source_text = source_bytes.decode("utf-8")
    functions, direct_calls, called_symbols, imported_modules, top_level_effects, omitted_nodes = _module_analysis(path, source_text)
    variable_candidates = _module_variable_candidates(source_text, path=path)
    module_name = _module_name(path, foundation_root=paths.foundation_root)
    import_bindings = _import_bindings(path, source_text, foundation_root=paths.foundation_root)
    lines = source_text.splitlines(keepends=True)
    function_rows: list[FunctionRecord] = []
    for qualified_name, (name, node) in sorted(functions.items(), key=lambda item: (int(item[1][1].lineno), item[0])):
        positional = [*node.args.posonlyargs, *node.args.args]
        function_rows.append(
            FunctionRecord(
                name=name,
                qualified_name=qualified_name,
                kind=_function_kind(name),
                source_start_line=_decorated_start(node),
                source_end_line=_node_end(node),
                decorated_start_line=_decorated_start(node),
                parameters=tuple(argument.arg for argument in positional),
                called_symbols=tuple(sorted(called_symbols.get(qualified_name, set()))),
                direct_calls=tuple(sorted(direct_calls.get(qualified_name, set()))),
                used_function_closure=_closure(qualified_name, direct_calls),
                resolved_function_calls=(),
                resolved_function_closure=(),
            )
        )
    destination = paths.output_root / domain / _template_filename(path, paths.repo_root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # The migration output is an exact source copy.  It is intentionally not
    # imported by runtime and is not added to registry.json automatically.
    if not destination.exists() or destination.read_bytes() != source_bytes:
        shutil.copyfile(path, destination)
    template_bytes = destination.read_bytes()
    if template_bytes != source_bytes:
        raise RuntimeError(f"template_copy_hash_mismatch:{path}:{destination}")
    if len(lines) == 0:
        raise RuntimeError(f"empty_source_module:{path}")
    return ModuleRecord(
        source_path=path,
        template_path=destination,
        module_name=module_name,
        domain=domain,
        source_sha256=_sha256(source_bytes),
        template_sha256=_sha256(template_bytes),
        source_bytes=len(source_bytes),
        functions=tuple(function_rows),
        imported_modules=imported_modules,
        top_level_effects=top_level_effects,
        omitted_nodes=omitted_nodes,
        variable_candidates=variable_candidates,
        import_bindings=import_bindings,
        resolved_module_dependencies=(),
    )


def _resolve_function_dependencies(records: list[ModuleRecord]) -> list[ModuleRecord]:
    """Resolve local and imported calls into a transitive function-use graph."""
    module_by_name = {record.module_name: record for record in records}
    symbol_map: dict[tuple[str, str], str] = {}
    local_names: dict[tuple[str, str], list[str]] = {}
    for record in records:
        for function in record.functions:
            key = f"{record.module_name}:{function.qualified_name}"
            symbol_map[(record.module_name, function.qualified_name)] = key
            local_names.setdefault((record.module_name, function.name), []).append(key)

    def resolve_target(record: ModuleRecord, function: FunctionRecord, called: str) -> set[str]:
        bindings = dict(record.import_bindings)
        targets: set[str] = set()
        if "." not in called:
            targets.update(local_names.get((record.module_name, called), []))
            imported = bindings.get(called)
            if imported:
                called = imported
            else:
                return targets
        else:
            first, remainder = called.split(".", 1)
            imported = bindings.get(first)
            if imported:
                called = f"{imported}.{remainder}"
        for module_name in sorted(module_by_name, key=len, reverse=True):
            prefix = f"{module_name}."
            if not called.startswith(prefix):
                continue
            function_name = called[len(prefix) :]
            exact = symbol_map.get((module_name, function_name))
            if exact:
                targets.add(exact)
                continue
            # A call may refer to a top-level imported function whose source
            # function has a qualified name.  Match the public short name only
            # when it is unique within that source module.
            targets.update(
                key
                for (candidate_module, candidate_name), key in symbol_map.items()
                if candidate_module == module_name and candidate_name.rsplit(".", 1)[-1] == function_name
            )
            break
        return targets

    graph: dict[str, set[str]] = {}
    resolved_by_function: dict[str, tuple[str, ...]] = {}
    module_dependencies: dict[str, set[str]] = {record.module_name: set() for record in records}
    for record in records:
        for function in record.functions:
            key = f"{record.module_name}:{function.qualified_name}"
            resolved: set[str] = set()
            for called in function.called_symbols:
                resolved.update(resolve_target(record, function, called))
            graph[key] = resolved
            resolved_by_function[key] = tuple(sorted(resolved))
            module_dependencies[record.module_name].update(
                target.split(":", 1)[0]
                for target in resolved
                if target.split(":", 1)[0] != record.module_name
            )

    closures: dict[str, tuple[str, ...]] = {}
    for root in graph:
        seen: set[str] = set()
        stack = [root]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            stack.extend(sorted(graph.get(current, set()), reverse=True))
        closures[root] = tuple(sorted(seen))

    resolved_records: list[ModuleRecord] = []
    for record in records:
        functions = tuple(
            replace(
                function,
                resolved_function_calls=resolved_by_function.get(
                    f"{record.module_name}:{function.qualified_name}",
                    (),
                ),
                resolved_function_closure=closures.get(
                    f"{record.module_name}:{function.qualified_name}",
                    (),
                ),
            )
            for function in record.functions
        )
        resolved_records.append(
            replace(
                record,
                functions=functions,
                resolved_module_dependencies=tuple(sorted(module_dependencies.get(record.module_name, set()))),
            )
        )
    return resolved_records


def migrate(paths: MigrationPaths | None = None, *, apply: bool = False, replace: bool = False) -> dict[str, Any]:
    """Create the categorized byte-exact source template catalog."""
    paths = paths or MigrationPaths.default()
    files = _source_files(paths)
    if not files:
        return {"ok": False, "state": "HOLD", "reason": "no_source_files"}
    if not apply:
        # Dry-run performs the same parse/dependency work but does not create
        # output directories or files.
        records: list[dict[str, Any]] = []
        for path in files:
            source_text = path.read_text(encoding="utf-8")
            functions, direct_calls, called_symbols, imported_modules, top_level_effects, omitted_nodes = _module_analysis(path, source_text)
            variable_candidates = _module_variable_candidates(source_text, path=path)
            records.append(
                {
                    "domain": categorize_module(path),
                    "source_path": _relative_posix(path, paths.repo_root),
                    "function_count": len(functions),
                    "functions": [
                        {
                            "name": name,
                            "source_start_line": _decorated_start(node),
                            "source_end_line": _node_end(node),
                            "called_symbols": sorted(called_symbols.get(qualified_name, set())),
                            "used_function_closure": list(_closure(name, direct_calls)),
                        }
                        for qualified_name, (name, node) in sorted(functions.items(), key=lambda item: (int(item[1][1].lineno), item[0]))
                    ],
                    "imported_modules": list(imported_modules),
                    "top_level_effects": list(top_level_effects),
                    "omitted_nodes": list(omitted_nodes),
                    "variable_candidates": list(variable_candidates),
                }
            )
        return {
            "ok": True,
            "state": "DRY_RUN",
            "schema_version": SCHEMA_VERSION,
            "read_only": True,
            "would_write": False,
            "files_scanned": len(records),
            "function_count": sum(int(row["function_count"]) for row in records),
            "domains": sorted({str(row["domain"]) for row in records}),
            "files": records,
        }
    if paths.output_root.exists() and not replace:
        existing = list(paths.output_root.rglob("*.py")) if paths.output_root.is_dir() else []
        if existing:
            return {
                "ok": False,
                "state": "HOLD",
                "reason": "migration_output_exists_use_replace",
                "output_root": str(paths.output_root),
                "existing_file_count": len(existing),
            }
    paths.output_root.mkdir(parents=True, exist_ok=True)
    records = [_module_record(path, paths, categorize_module(path)) for path in files]
    records = _resolve_function_dependencies(records)
    records.sort(key=lambda row: (_relative_posix(row.template_path, paths.repo_root)))
    expected_templates = {record.template_path.resolve(strict=False) for record in records}
    stale_templates: list[str] = []
    if replace:
        for stale_path in sorted(paths.output_root.rglob("*.py")):
            resolved = stale_path.resolve(strict=False)
            if resolved not in expected_templates:
                stale_templates.append(_relative_posix(stale_path, paths.repo_root))
                stale_path.unlink()
    domains: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        domains.setdefault(record.domain, []).append(record.as_dict(repo_root=paths.repo_root))
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "created_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "read_only_source_scan": True,
        "byte_exact_source_copies": True,
        "active_registry_updated": False,
        "human_review_required_before_activation": True,
        "stale_generated_templates_removed": stale_templates,
        "source_scope": [
            "foundation/rid_main.py",
            "foundation/auto_main.py",
            "foundation/uml_main.py",
            "foundation/lib/**/*.py",
        ],
        "output_root": _relative_posix(paths.output_root, paths.repo_root),
        "artifact_root": _relative_posix(paths.artifact_root, paths.repo_root),
        "function_index": _relative_posix(paths.artifact_root / FUNCTION_INDEX_NAME, paths.repo_root),
        "files_scanned": len(records),
        "function_count": sum(len(record.functions) for record in records),
        "domain_count": len(domains),
        "domains": {domain: [row["template_path"] for row in rows] for domain, rows in sorted(domains.items())},
        "files": [record.as_dict(repo_root=paths.repo_root) for record in records],
    }
    paths.artifact_root.mkdir(parents=True, exist_ok=True)
    manifest_path = paths.artifact_root / MANIFEST_NAME
    function_index_path = paths.artifact_root / FUNCTION_INDEX_NAME
    domain_index = {
        "schema_version": SCHEMA_VERSION,
        "manifest": _relative_posix(manifest_path, paths.repo_root),
        "domains": {
            domain: {
                "template_count": len(rows),
                "function_count": sum(int(row["function_count"]) for row in rows),
                "templates": rows,
            }
            for domain, rows in sorted(domains.items())
        },
    }
    function_index = {
        "schema_version": SCHEMA_VERSION,
        "manifest": _relative_posix(manifest_path, paths.repo_root),
        "read_only_source_scan": True,
        "byte_exact_source_copies": True,
        "entries": [
            {
                "domain": record.domain,
                "source_path": _relative_posix(record.source_path, paths.repo_root),
                "template_path": _relative_posix(record.template_path, paths.repo_root),
                "source_sha256": record.source_sha256,
                "template_sha256": record.template_sha256,
                **function,
            }
            for record in records
            for function in (row.as_dict() for row in record.functions)
        ],
    }
    manifest_path.write_bytes(_json_bytes(manifest))
    (paths.artifact_root / DOMAIN_INDEX_NAME).write_bytes(_json_bytes(domain_index))
    function_index_path.write_bytes(_json_bytes(function_index))
    return {
        "ok": True,
        "state": "PASS",
        "schema_version": SCHEMA_VERSION,
        "output_root": _relative_posix(paths.output_root, paths.repo_root),
        "manifest": _relative_posix(manifest_path, paths.repo_root),
        "domain_index": _relative_posix(paths.artifact_root / DOMAIN_INDEX_NAME, paths.repo_root),
        "function_index": _relative_posix(function_index_path, paths.repo_root),
        "files_scanned": len(records),
        "function_count": sum(len(record.functions) for record in records),
        "domain_count": len(domains),
        "domains": {domain: len(rows) for domain, rows in sorted(domains.items())},
        "active_registry_updated": False,
        "human_review_required_before_activation": True,
        "stale_generated_templates_removed": stale_templates,
    }


def _parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write categorized template copies and indexes")
    parser.add_argument("--replace", action="store_true", help="allow replacement of an existing migration output")
    parser.add_argument("--output-root", default="", help="override the categorized template root")
    parser.add_argument("--artifact-root", default="", help="override the migration receipt root")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(argv)
    defaults = MigrationPaths.default()
    paths = MigrationPaths(
        repo_root=defaults.repo_root,
        foundation_root=defaults.foundation_root,
        output_root=Path(args.output_root) if args.output_root else defaults.output_root,
        artifact_root=Path(args.artifact_root) if args.artifact_root else defaults.artifact_root,
    )
    try:
        report = migrate(paths, apply=bool(args.apply), replace=bool(args.replace))
    except (OSError, SyntaxError, UnicodeError, RuntimeError, ValueError) as exc:
        report = {"ok": False, "state": "HOLD", "reason": str(exc)}
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
