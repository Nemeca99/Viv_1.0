"""Read-only loader and explicit executor for the deterministic code toolbox.

This module is the one-time runtime hook used by RID, AUTO, and UML.  It is
deliberately independent of the developer builder: runtime startup only reads
the active pointer, verifies immutable evidence, and imports a selected
generated module.  Importing a template never invokes ``main`` or a
``sub_main_*`` function; execution is an explicit call to
``execute_template``.
"""
from __future__ import annotations

import ast
import copy
from dataclasses import dataclass
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
from types import ModuleType, MappingProxyType
from typing import Any, Mapping


POINTER_SCHEMA = "viv_code_template_pointer_v1"
GENERATION_SCHEMA = "viv_code_template_generation_v1"
INDEX_SCHEMA = "viv_code_template_function_index_v1"
RECEIPT_SCHEMA = "viv_code_template_receipt_v1"
SELECTION_REQUEST_SCHEMA = "viv_code_template_selection_request_v1"
TARGET_PILLARS = frozenset({"rid", "auto", "uml"})
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_GENERATION_RE = re.compile(r"^gen_[a-f0-9]{16}$")


class TemplateRuntimeError(RuntimeError):
    """The active template generation is absent, stale, or unsafe."""


@dataclass(frozen=True)
class _RuntimePaths:
    root: Path
    source_root: Path
    generation_root: Path
    current_pointer: Path
    receipt_root: Path

    @classmethod
    def default(cls) -> "_RuntimePaths":
        root = Path(__file__).resolve().parents[2]
        return cls(
            root=root,
            source_root=root / "foundation" / "code_templates" / "source",
            generation_root=root / "sandbox" / "code" / "template_generations",
            current_pointer=root / "sandbox" / "code" / "template_current.json",
            receipt_root=root / "foundation" / "artifacts" / "auto" / "code_templates",
        )


@dataclass(frozen=True)
class _VerifiedSnapshot:
    pointer: Mapping[str, Any]
    manifest: Mapping[str, Any]
    index: Mapping[str, Any]
    receipt: Mapping[str, Any]
    generation_dir: Path
    modules: Mapping[str, Mapping[str, Any]]
    report: Mapping[str, Any]


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _posix(path: Path | str) -> str:
    return str(path).replace("\\", "/")


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _selection_request_hash(value: Mapping[str, Any]) -> str:
    return _sha256_bytes(_stable_json(value).encode("utf-8"))


def _verify_selection_metadata(
    manifest: Mapping[str, Any],
    receipt: Mapping[str, Any],
    modules: Any,
) -> None:
    """Verify the structured selection that produced the active generation."""
    request = manifest.get("selection_request")
    request_hash = manifest.get("selection_request_sha256")
    receipt_request = receipt.get("selection_request")
    receipt_hash = receipt.get("selection_request_sha256")
    if request is None:
        if request_hash is not None or receipt_request is not None or receipt_hash is not None:
            raise TemplateRuntimeError("selection_request_metadata_mismatch")
        return
    if not isinstance(request, dict) or set(request) != {"schema_version", "templates"}:
        raise TemplateRuntimeError("selection_request_invalid")
    if request.get("schema_version") != SELECTION_REQUEST_SCHEMA:
        raise TemplateRuntimeError("selection_request_schema_mismatch")
    rows = request.get("templates")
    if not isinstance(rows, list) or not rows or not isinstance(modules, list) or len(rows) != len(modules):
        raise TemplateRuntimeError("selection_request_templates_invalid")
    for row, module in zip(rows, modules):
        if not isinstance(row, dict) or set(row) != {"template_id", "target_pillars", "submain_order"}:
            raise TemplateRuntimeError("selection_request_row_invalid")
        if not isinstance(module, dict):
            raise TemplateRuntimeError("selection_request_module_invalid")
        if row.get("template_id") != module.get("template_id"):
            raise TemplateRuntimeError("selection_request_module_mismatch")
        if row.get("target_pillars") != module.get("target_pillars"):
            raise TemplateRuntimeError("selection_request_target_mismatch")
        if row.get("submain_order") != module.get("submain_order"):
            raise TemplateRuntimeError("selection_request_submain_mismatch")
    actual_hash = _selection_request_hash(request)
    if request_hash != actual_hash or receipt_hash != actual_hash or receipt_request != request:
        raise TemplateRuntimeError("selection_request_hash_mismatch")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TemplateRuntimeError(f"invalid_json:{path}:{exc}") from exc
    if not isinstance(value, dict):
        raise TemplateRuntimeError(f"json_object_required:{path}")
    return value


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink() or os.path.islink(path):
        return True
    is_junction = getattr(os.path, "isjunction", None)
    return bool(is_junction and is_junction(path))


def _safe_relative(root: Path, raw: Any, *, suffix: str = ".py") -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise TemplateRuntimeError("relative_path_required")
    candidate = Path(raw)
    if candidate.is_absolute() or candidate.drive or candidate.root or any(
        part in {"", ".", ".."} for part in candidate.parts
    ):
        raise TemplateRuntimeError(f"unsafe_relative_path:{raw}")
    if suffix and candidate.suffix.casefold() != suffix.casefold():
        raise TemplateRuntimeError(f"path_suffix_required:{raw}:{suffix}")
    lexical = root / candidate
    cursor = lexical
    while cursor != root and cursor != cursor.parent:
        if cursor.exists() and _is_reparse_point(cursor):
            raise TemplateRuntimeError(f"reparse_path:{raw}")
        cursor = cursor.parent
    resolved = (root / candidate).resolve(strict=False)
    try:
        resolved.relative_to(root.resolve(strict=False))
    except ValueError as exc:
        raise TemplateRuntimeError(f"path_outside_root:{raw}") from exc
    cursor = resolved
    root_resolved = root.resolve(strict=False)
    while cursor != root_resolved and cursor != cursor.parent:
        if _is_reparse_point(cursor):
            raise TemplateRuntimeError(f"reparse_path:{raw}")
        cursor = cursor.parent
    return candidate


def _security_status() -> dict[str, Any]:
    foundation = Path(__file__).resolve().parents[1]
    if str(foundation) not in sys.path:
        sys.path.insert(0, str(foundation))
    try:
        from lib.security_membrane import membrane_status  # type: ignore

        membrane = dict(membrane_status())
        armed = bool(membrane.get("armed"))
        return {
            "ok": armed,
            "rust_available": armed,
            "integrity": membrane.get("integrity"),
            "rust_error": membrane.get("rust_error"),
            "membrane": membrane,
        }
    except Exception as exc:
        return {"ok": False, "rust_available": False, "reason": f"security_status_unavailable:{exc}"}


def _source_span(lines: list[str], start: int, end: int, *, label: str) -> bytes:
    if not isinstance(start, int) or not isinstance(end, int) or not (1 <= start <= end <= len(lines)):
        raise TemplateRuntimeError(f"{label}_lines_invalid")
    return "".join(lines[start - 1 : end]).encode("utf-8")


def _source_inventory(paths: _RuntimePaths) -> tuple[list[dict[str, Any]], dict[str, list[str]], list[str]]:
    """Read the authoring registry and source metadata without importing source."""
    registry_path = paths.source_root.parent / "registry.json"
    try:
        registry = _read_json(registry_path)
    except TemplateRuntimeError as exc:
        return [], {}, [str(exc)]
    rows = registry.get("templates")
    if not isinstance(rows, list):
        return [], {}, ["registry_templates_invalid"]
    templates: list[dict[str, Any]] = []
    coverage: dict[str, list[str]] = {pillar: [] for pillar in sorted(TARGET_PILLARS)}
    warnings: list[str] = []
    seen_ids: set[str] = set()
    seen_sources: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            warnings.append("registry_row_invalid")
            continue
        template_id = str(row.get("template_id") or "")
        if not _ID_RE.fullmatch(template_id):
            warnings.append(f"invalid_template_id:{template_id}")
        source_text = str(row.get("source") or "")
        if template_id in seen_ids:
            warnings.append(f"duplicate_template_id:{template_id}")
        seen_ids.add(template_id)
        if source_text in seen_sources:
            warnings.append(f"duplicate_template_source:{source_text}")
        seen_sources.add(source_text)
        raw_targets = row.get("targets")
        if not isinstance(raw_targets, list) or not raw_targets:
            warnings.append(f"invalid_targets:{template_id}")
            raw_targets = []
        targets = [str(target) for target in raw_targets if target in TARGET_PILLARS]
        if len(targets) != len(raw_targets):
            warnings.append(f"undeclared_target_pillar:{template_id}")
        if len(targets) != len(set(targets)):
            warnings.append(f"duplicate_target_pillar:{template_id}")
        raw_submains = row.get("submain_order")
        if not isinstance(raw_submains, list):
            warnings.append(f"invalid_submain_order:{template_id}")
            raw_submains = []
        submain_order = [str(name) for name in raw_submains]
        if len(submain_order) != len(set(submain_order)):
            warnings.append(f"duplicate_submain_order:{template_id}")
        variable_keys: list[str] = []
        source_sha256: str | None = None
        try:
            source_rel = _safe_relative(paths.source_root, row.get("source"))
            source_path = paths.source_root / source_rel
            source_bytes = source_path.read_bytes()
            source_sha256 = _sha256_bytes(source_bytes)
            tree = ast.parse(source_bytes.decode("utf-8"), filename=str(source_path))
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    is_variables = len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "VARIABLES"
                elif isinstance(node, ast.AnnAssign):
                    is_variables = isinstance(node.target, ast.Name) and node.target.id == "VARIABLES"
                else:
                    is_variables = False
                if is_variables:
                    if isinstance(node.value, ast.Dict):
                        variable_keys = [key.value for key in node.value.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)]
                    break
        except (OSError, UnicodeError, SyntaxError, TemplateRuntimeError) as exc:
            warnings.append(f"source_inventory:{template_id}:{exc}")
        for target in targets:
            coverage.setdefault(target, []).append(template_id)
        templates.append(
            {
                "template_id": template_id,
                "source": source_text,
                "target_pillars": targets,
                "variables": sorted(variable_keys),
                "submain_order": submain_order,
                "submain_count": len(submain_order),
                "source_sha256": source_sha256,
            }
        )
    generated_paths: dict[str, list[str]] = {}
    for item in templates:
        generated_name = f"{str(item.get('template_id') or '').replace('.', '_')}.py"
        generated_paths.setdefault(generated_name, []).append(str(item.get("template_id") or ""))
    for generated_name, template_ids in sorted(generated_paths.items()):
        if len(template_ids) > 1:
            warnings.append(f"generated_path_collision:{generated_name}:{','.join(template_ids)}")
    return templates, coverage, warnings


def _source_drift(paths: _RuntimePaths, templates: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare the read-only source catalog with its approved index receipt."""
    index_path = paths.receipt_root / "source_function_index.json"
    receipt_path = paths.receipt_root / "source_function_index.receipt.json"
    if not index_path.is_file() and not receipt_path.is_file():
        return {"detected": False, "state": "UNINDEXED"}
    if not index_path.is_file() or not receipt_path.is_file():
        return {"detected": True, "reason": "source_index_or_receipt_missing"}
    try:
        index = _read_json(index_path)
        receipt = _read_json(receipt_path)
        if index.get("schema_version") != "viv_code_template_function_index_v1":
            return {"detected": True, "reason": "source_index_schema_mismatch"}
        if receipt.get("schema_version") != "viv_code_template_source_index_receipt_v1":
            return {"detected": True, "reason": "source_index_receipt_schema_mismatch"}
        if receipt.get("index_sha256") != _sha256_bytes(index_path.read_bytes()):
            return {"detected": True, "reason": "source_index_receipt_hash_mismatch"}
        if Path(str(receipt.get("index_path") or "")).resolve(strict=False) != index_path.resolve(strict=False):
            return {"detected": True, "reason": "source_index_receipt_path_mismatch"}
        registry_path = paths.source_root.parent / "registry.json"
        if receipt.get("registry_sha256") != _sha256_bytes(registry_path.read_bytes()):
            return {"detected": True, "reason": "source_index_registry_hash_mismatch"}
        receipt_source_root = Path(str(receipt.get("source_root") or ""))
        if receipt_source_root.resolve(strict=False) != paths.source_root.resolve(strict=False):
            return {"detected": True, "reason": "source_index_root_mismatch"}
        approved = {
            str(row.get("template_id")): str(row.get("source_sha256"))
            for row in (index.get("modules") or [])
            if isinstance(row, dict) and row.get("template_id")
        }
        current = {
            str(row.get("template_id")): str(row.get("source_sha256"))
            for row in templates
            if isinstance(row, dict) and row.get("template_id")
        }
        if set(approved) != set(current):
            return {"detected": True, "reason": "source_index_template_set_mismatch"}
        drifted = sorted(template_id for template_id in current if approved.get(template_id) != current[template_id])
        if drifted:
            return {"detected": True, "reason": f"source_hash_drift:{','.join(drifted)}"}
        return {"detected": False, "state": "INDEXED"}
    except (OSError, UnicodeError, TemplateRuntimeError, TypeError, ValueError) as exc:
        return {"detected": True, "reason": f"source_index_invalid:{exc}"}


def _migration_catalog_status(paths: _RuntimePaths) -> dict[str, Any]:
    """Expose the existing-function migration as read-only candidates.

    These copied modules are intentionally not treated as active runtime
    registrations: they retain their original AIOS signatures and module
    behavior until a human reviews and promotes a strict runtime template.
    """
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
        mismatches: list[str] = []
        domains: dict[str, int] = {}
        for row in rows:
            if not isinstance(row, dict):
                mismatches.append("manifest_row_invalid")
                continue
            source_raw = str(row.get("source_path") or "")
            template_raw = str(row.get("template_path") or "")
            try:
                source_path = paths.root / Path(source_raw)
                template_path = paths.root / Path(template_raw)
                if not source_path.is_file() or not template_path.is_file():
                    mismatches.append(source_raw or "source_path_missing")
                    continue
                source_bytes = source_path.read_bytes()
                template_bytes = template_path.read_bytes()
                if source_bytes != template_bytes:
                    mismatches.append(source_raw)
                if _sha256_bytes(source_bytes) != str(row.get("source_sha256") or ""):
                    mismatches.append(f"source_hash:{source_raw}")
                if _sha256_bytes(template_bytes) != str(row.get("template_sha256") or ""):
                    mismatches.append(f"template_hash:{template_raw}")
                domain = str(row.get("domain") or "uncategorized")
                domains[domain] = domains.get(domain, 0) + 1
            except (OSError, ValueError) as exc:
                mismatches.append(f"{source_raw}:{exc}")
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
    except (OSError, UnicodeError, TypeError, ValueError, TemplateRuntimeError) as exc:
        return {"state": "HOLD", "reason": f"migration_catalog_invalid:{exc}", "active_registry_updated": False}


def _verify_snapshot(paths: _RuntimePaths) -> _VerifiedSnapshot:
    pointer = _read_json(paths.current_pointer)
    if pointer.get("schema_version") != POINTER_SCHEMA:
        raise TemplateRuntimeError("pointer_schema_mismatch")
    generation_id = pointer.get("generation_id")
    if not isinstance(generation_id, str) or not _GENERATION_RE.fullmatch(generation_id):
        raise TemplateRuntimeError("pointer_generation_invalid")
    generation_dir = paths.generation_root / generation_id
    if _is_reparse_point(generation_dir):
        raise TemplateRuntimeError("generation_reparse_path")
    try:
        generation_dir.resolve(strict=False).relative_to(paths.generation_root.resolve(strict=False))
    except ValueError as exc:
        raise TemplateRuntimeError("generation_outside_root") from exc

    manifest_path = generation_dir / "generation_manifest.json"
    index_path = generation_dir / "function_index.json"
    receipt_path = generation_dir / "generation_receipt.json"
    expected_paths = {
        "manifest_path": manifest_path,
        "index_path": index_path,
        "receipt_path": receipt_path,
    }
    for field, expected in expected_paths.items():
        if Path(str(pointer.get(field) or "")).resolve(strict=False) != expected.resolve(strict=False):
            raise TemplateRuntimeError(f"pointer_{field}_mismatch")

    manifest = _read_json(manifest_path)
    index = _read_json(index_path)
    receipt = _read_json(receipt_path)
    manifest_bytes = manifest_path.read_bytes()
    index_bytes = index_path.read_bytes()
    receipt_bytes = receipt_path.read_bytes()
    if manifest.get("schema_version") != GENERATION_SCHEMA or manifest.get("generation_id") != generation_id:
        raise TemplateRuntimeError("generation_manifest_invalid")
    if index.get("schema_version") != INDEX_SCHEMA or index.get("generation_id") != generation_id:
        raise TemplateRuntimeError("generation_index_invalid")
    if receipt.get("schema_version") != RECEIPT_SCHEMA or receipt.get("generation_id") != generation_id:
        raise TemplateRuntimeError("generation_receipt_invalid")
    for field, actual in (
        ("manifest_sha256", _sha256_bytes(manifest_bytes)),
        ("index_sha256", _sha256_bytes(index_bytes)),
        ("receipt_sha256", _sha256_bytes(receipt_bytes)),
    ):
        if pointer.get(field) != actual:
            raise TemplateRuntimeError(f"pointer_{field}_mismatch")
    if receipt.get("manifest_sha256") != _sha256_bytes(manifest_bytes):
        raise TemplateRuntimeError("manifest_receipt_hash_mismatch")
    if receipt.get("function_index_sha256") != _sha256_bytes(index_bytes):
        raise TemplateRuntimeError("index_receipt_hash_mismatch")
    if manifest.get("function_index_sha256") != _sha256_bytes(index_bytes):
        raise TemplateRuntimeError("manifest_index_hash_mismatch")
    parent_generation = manifest.get("parent_generation")
    if receipt.get("parent_generation") != parent_generation:
        raise TemplateRuntimeError("receipt_parent_generation_mismatch")
    parent_receipt_raw = receipt.get("parent_receipt")
    if parent_generation:
        expected_parent_receipt = paths.receipt_root / "receipts" / f"{parent_generation}.json"
        if Path(str(parent_receipt_raw or "")).resolve(strict=False) != expected_parent_receipt.resolve(strict=False):
            raise TemplateRuntimeError("receipt_parent_receipt_path_mismatch")
        if not expected_parent_receipt.is_file():
            raise TemplateRuntimeError("receipt_parent_receipt_missing")
    elif parent_receipt_raw is not None:
        raise TemplateRuntimeError("receipt_parent_receipt_unexpected")

    archive_path = Path(str(receipt.get("archive_path") or ""))
    expected_archive = paths.receipt_root / "receipts" / f"{generation_id}.json"
    if archive_path.resolve(strict=False) != expected_archive.resolve(strict=False):
        raise TemplateRuntimeError("receipt_archive_path_mismatch")
    if not archive_path.is_file() or _sha256_bytes(archive_path.read_bytes()) != _sha256_bytes(receipt_bytes):
        raise TemplateRuntimeError("receipt_archive_mismatch")

    source_root_raw = str(manifest.get("source_root") or "")
    source_root = paths.source_root if source_root_raw == "<source-template-root>" else Path(source_root_raw)
    if source_root.resolve(strict=False) != paths.source_root.resolve(strict=False):
        raise TemplateRuntimeError("manifest_source_root_mismatch")
    modules = manifest.get("modules")
    entries = index.get("entries")
    if not isinstance(modules, list) or not isinstance(entries, list):
        raise TemplateRuntimeError("generation_modules_or_entries_invalid")
    _verify_selection_metadata(manifest, receipt, modules)
    entries_by_key: dict[tuple[str, str], Mapping[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise TemplateRuntimeError("generation_index_entry_invalid")
        key = (str(entry.get("template_id") or ""), str(entry.get("section") or ""))
        if key in entries_by_key:
            raise TemplateRuntimeError(f"generation_index_duplicate:{key[0]}:{key[1]}")
        entries_by_key[key] = entry

    verified_modules: dict[str, Mapping[str, Any]] = {}
    reports: list[dict[str, Any]] = []
    for module in modules:
        if not isinstance(module, dict):
            raise TemplateRuntimeError("generation_module_invalid")
        template_id = str(module.get("template_id") or "")
        if not _ID_RE.fullmatch(template_id) or template_id in verified_modules:
            raise TemplateRuntimeError(f"generation_module_id_invalid:{template_id}")
        targets = module.get("target_pillars")
        if not isinstance(targets, list) or not targets or any(target not in TARGET_PILLARS for target in targets):
            raise TemplateRuntimeError(f"generation_target_mapping_invalid:{template_id}")
        try:
            source_rel = _safe_relative(source_root, module.get("source_path"))
            generated_rel = _safe_relative(generation_dir, module.get("generated_path"))
        except TemplateRuntimeError as exc:
            raise TemplateRuntimeError(f"module_path_invalid:{template_id}:{exc}") from exc
        source_path = source_root / source_rel
        generated_path = generation_dir / generated_rel
        if _is_reparse_point(source_path) or _is_reparse_point(generated_path):
            raise TemplateRuntimeError(f"module_reparse_path:{template_id}")
        if not source_path.is_file() or not generated_path.is_file():
            raise TemplateRuntimeError(f"module_file_missing:{template_id}")
        source_bytes = source_path.read_bytes()
        generated_bytes = generated_path.read_bytes()
        if _sha256_bytes(source_bytes) != module.get("source_sha256"):
            raise TemplateRuntimeError(f"source_hash_drift:{template_id}")
        if _sha256_bytes(generated_bytes) != module.get("generated_sha256"):
            raise TemplateRuntimeError(f"generated_hash_mismatch:{template_id}")
        try:
            source_lines = source_bytes.decode("utf-8").splitlines(keepends=True)
            generated_lines = generated_bytes.decode("utf-8").splitlines(keepends=True)
        except UnicodeDecodeError as exc:
            raise TemplateRuntimeError(f"module_not_utf8:{template_id}") from exc
        sections = module.get("sections")
        submain_order = module.get("submain_order")
        if not isinstance(sections, list) or not isinstance(submain_order, list):
            raise TemplateRuntimeError(f"module_sections_invalid:{template_id}")
        expected_names = [
            "__imports__" if any(isinstance(item, dict) and item.get("name") == "__imports__" for item in sections) else None,
            "VARIABLES",
            "main",
            *(str(name) for name in submain_order),
        ]
        expected_names = [name for name in expected_names if name is not None]
        actual_names = [str(item.get("name") or "") for item in sections if isinstance(item, dict)]
        if actual_names != expected_names:
            raise TemplateRuntimeError(f"module_section_order_invalid:{template_id}")
        section_keys: set[tuple[str, str]] = set()
        for section in sections:
            if not isinstance(section, dict):
                raise TemplateRuntimeError(f"module_section_invalid:{template_id}")
            name = str(section.get("name") or "")
            key = (template_id, name)
            if key in section_keys or key not in entries_by_key:
                raise TemplateRuntimeError(f"module_section_index_invalid:{template_id}:{name}")
            section_keys.add(key)
            entry = entries_by_key[key]
            if entry.get("generation_id") != generation_id:
                raise TemplateRuntimeError(f"module_section_generation_id_mismatch:{template_id}:{name}")
            for field in (
                "source_start_line", "source_end_line", "generated_start_line", "generated_end_line",
                "source_sha256", "generated_sha256", "target_pillars", "submain_order", "decorated",
            ):
                if section.get(field) != entry.get(field):
                    raise TemplateRuntimeError(f"module_section_metadata_mismatch:{template_id}:{name}")
            source_span = _source_span(
                source_lines,
                int(section["source_start_line"]),
                int(section["source_end_line"]),
                label=f"source_section:{template_id}:{name}",
            )
            generated_span = _source_span(
                generated_lines,
                int(section["generated_start_line"]),
                int(section["generated_end_line"]),
                label=f"generated_section:{template_id}:{name}",
            )
            if source_span != generated_span:
                raise TemplateRuntimeError(f"section_byte_mismatch:{template_id}:{name}")
            if _sha256_bytes(source_span) != section.get("source_sha256"):
                raise TemplateRuntimeError(f"source_section_hash_mismatch:{template_id}:{name}")
            if _sha256_bytes(generated_span) != section.get("generated_sha256"):
                raise TemplateRuntimeError(f"generated_section_hash_mismatch:{template_id}:{name}")
        if section_keys != {(template_id, str(entry.get("section") or "")) for entry in entries if entry.get("template_id") == template_id}:
            raise TemplateRuntimeError(f"module_section_set_mismatch:{template_id}")
        verified_modules[template_id] = module
        reports.append(
            {
                "template_id": template_id,
                "variables": list(module.get("variable_keys") or []),
                "target_pillars": list(targets),
                "submain_order": list(submain_order),
                "submain_count": len(submain_order),
                "source_sha256": module.get("source_sha256"),
                "generated_sha256": module.get("generated_sha256"),
            }
        )

    if {str(entry.get("template_id") or "") for entry in entries} != set(verified_modules):
        raise TemplateRuntimeError("generation_index_module_set_mismatch")
    report = {
        "ok": True,
        "state": "PASS",
        "generation_id": generation_id,
        "module_count": len(reports),
        "modules": reports,
    }
    return _VerifiedSnapshot(pointer, manifest, index, receipt, generation_dir, verified_modules, report)


def _snapshot(paths: _RuntimePaths | None = None) -> _VerifiedSnapshot:
    paths = paths or _RuntimePaths.default()
    if not paths.current_pointer.is_file():
        raise TemplateRuntimeError("no_active_generation")
    security = _security_status()
    if not security.get("ok"):
        raise TemplateRuntimeError(f"security_hold:{security.get('reason') or security.get('rust_error') or 'integrity_unavailable'}")
    return _verify_snapshot(paths)


def template_status(pillar: str | None = None) -> dict[str, Any]:
    """Return read-only toolbox coverage and active-generation status."""
    paths = _RuntimePaths.default()
    security = _security_status()
    all_source_templates, coverage, inventory_warnings = _source_inventory(paths)
    source_drift = _source_drift(paths, all_source_templates)
    migration_catalog = _migration_catalog_status(paths)
    source_templates = all_source_templates
    if pillar is not None:
        source_templates = [item for item in source_templates if pillar in item.get("target_pillars", [])]
    if not paths.current_pointer.is_file():
        return {
            "ok": not inventory_warnings and not source_drift.get("detected"),
            "state": "HOLD" if inventory_warnings or source_drift.get("detected") else "EMPTY",
            "toolbox": "viv_deterministic_code_templates",
            "pillar": pillar,
            "active_generation": None,
            "selection_request": None,
            "templates": source_templates,
            "domain_coverage": coverage,
            "source_drift": source_drift,
            "lineage_tail": [],
            "security": security,
            "duplicate_conflict_warnings": [*inventory_warnings, *([source_drift.get("reason")] if source_drift.get("reason") else [])],
            "migration_catalog": migration_catalog,
        }
    try:
        snapshot = _verify_snapshot(paths) if security.get("ok") else None
        if snapshot is None:
            raise TemplateRuntimeError(f"security_hold:{security.get('reason') or security.get('rust_error') or 'integrity_unavailable'}")
        active_by_id = {str(item["template_id"]): item for item in snapshot.report["modules"]}
        templates = []
        for item in source_templates:
            merged = dict(item)
            active = active_by_id.get(str(item.get("template_id")))
            if active:
                merged["generated_sha256"] = active.get("generated_sha256")
                merged["active_generation"] = snapshot.report["generation_id"]
            templates.append(merged)
        manifest = snapshot.manifest
        return {
            "ok": not inventory_warnings and not source_drift.get("detected"),
            "state": "HOLD" if inventory_warnings or source_drift.get("detected") else "PASS",
            "toolbox": "viv_deterministic_code_templates",
            "pillar": pillar,
            "active_generation": snapshot.report["generation_id"],
            "selection_request": manifest.get("selection_request"),
            "selection_request_sha256": manifest.get("selection_request_sha256"),
            "templates": templates,
            "domain_coverage": coverage,
            "source_drift": source_drift,
            "lineage_tail": list(manifest.get("lineage_tail") or [])[-5:],
            "security": security,
            "duplicate_conflict_warnings": [*inventory_warnings, *([source_drift.get("reason")] if source_drift.get("reason") else [])],
            "migration_catalog": migration_catalog,
        }
    except TemplateRuntimeError as exc:
        reason = str(exc)
        return {
            "ok": False,
            "state": "HOLD_SECURITY" if reason.startswith("security_hold:") else "HOLD",
            "toolbox": "viv_deterministic_code_templates",
            "pillar": pillar,
            "active_generation": None,
            "selection_request": None,
            "templates": source_templates,
            "domain_coverage": coverage,
            "source_drift": source_drift if source_drift.get("detected") else {"detected": reason.startswith("source_hash_drift:"), "reason": reason},
            "lineage_tail": [],
            "security": security,
            "duplicate_conflict_warnings": [*inventory_warnings, *([source_drift.get("reason")] if source_drift.get("reason") else []), reason],
            "migration_catalog": migration_catalog,
            "reason": reason,
        }


def discover_templates(
    pillar: str,
    *,
    _paths: _RuntimePaths | None = None,
) -> list[dict[str, Any]]:
    """Discover verified registrations for one pillar without importing code."""
    if pillar not in TARGET_PILLARS:
        raise TemplateRuntimeError(f"unknown_pillar:{pillar}")
    snapshot = _snapshot(_paths)
    return [
        {
            "template_id": template_id,
            "target_pillars": list(module["target_pillars"]),
            "variables": list(module.get("variable_keys") or []),
            "submain_order": list(module.get("submain_order") or []),
            "generated_path": _posix(snapshot.generation_dir / str(module["generated_path"])),
        }
        for template_id, module in snapshot.modules.items()
        if pillar in module.get("target_pillars", [])
    ]


def _load_verified_module(snapshot: _VerifiedSnapshot, template_id: str, pillar: str) -> ModuleType:
    if pillar not in TARGET_PILLARS:
        raise TemplateRuntimeError(f"unknown_pillar:{pillar}")
    module_meta = snapshot.modules.get(template_id)
    if module_meta is None:
        raise TemplateRuntimeError(f"template_not_found:{template_id}")
    if pillar not in module_meta.get("target_pillars", []):
        raise TemplateRuntimeError(f"template_not_targeted:{template_id}:{pillar}")
    try:
        generated_rel = _safe_relative(snapshot.generation_dir, module_meta.get("generated_path"))
    except TemplateRuntimeError as exc:
        raise TemplateRuntimeError(f"generated_path_invalid:{template_id}:{exc}") from exc
    path = snapshot.generation_dir / generated_rel
    module_name = f"_viv_template_{snapshot.report['generation_id']}_{template_id.replace('.', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise TemplateRuntimeError(f"module_spec_unavailable:{template_id}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop(module_name, None)
        raise TemplateRuntimeError(f"template_import_failed:{template_id}:{exc}") from exc
    variables = getattr(module, "VARIABLES", None)
    main = getattr(module, "main", None)
    if not isinstance(variables, Mapping) or not all(isinstance(key, str) for key in variables):
        raise TemplateRuntimeError(f"template_variables_invalid:{template_id}")
    if sorted(str(key) for key in variables) != sorted(str(key) for key in (module_meta.get("variable_keys") or [])):
        raise TemplateRuntimeError(f"template_variable_keys_mismatch:{template_id}")
    if not callable(main):
        raise TemplateRuntimeError(f"template_main_missing:{template_id}")
    for name in module_meta.get("submain_order", []):
        if not callable(getattr(module, str(name), None)):
            raise TemplateRuntimeError(f"template_submain_missing:{template_id}:{name}")
    return module


def load_template(
    template_id: str,
    pillar: str,
    *,
    _paths: _RuntimePaths | None = None,
) -> ModuleType:
    """Load one verified module; no template function is executed here."""
    snapshot = _snapshot(_paths)
    return _load_verified_module(snapshot, template_id, pillar)


def execute_template(
    template_id: str,
    pillar: str,
    context: Mapping[str, Any],
    variable_overrides: Mapping[str, Any] | None = None,
    *,
    _paths: _RuntimePaths | None = None,
) -> Any:
    """Run ordered submains, then ``main`` exactly once.

    ``variable_overrides`` is structured data only.  It may replace values for
    keys already declared by the approved template, but it cannot add keys or
    alter source code.
    """
    if not isinstance(context, Mapping):
        raise TemplateRuntimeError("context_mapping_required")
    if variable_overrides is not None and not isinstance(variable_overrides, Mapping):
        raise TemplateRuntimeError("variable_overrides_mapping_required")
    snapshot = _snapshot(_paths)
    return _execute_with_snapshot(snapshot, template_id, pillar, context, variable_overrides)


def _execute_with_snapshot(
    snapshot: _VerifiedSnapshot,
    template_id: str,
    pillar: str,
    context: Mapping[str, Any],
    variable_overrides: Mapping[str, Any] | None = None,
) -> Any:
    """Testable execution core after a caller has supplied a verified snapshot."""
    module = _load_verified_module(snapshot, template_id, pillar)
    module_meta = snapshot.modules[template_id]
    try:
        variables = copy.deepcopy(dict(module.VARIABLES))
    except Exception as exc:
        raise TemplateRuntimeError(f"variables_copy_failed:{template_id}:{exc}") from exc
    if variable_overrides is not None:
        if not all(isinstance(key, str) for key in variable_overrides):
            raise TemplateRuntimeError(f"variable_override_keys_must_be_strings:{template_id}")
        unknown = sorted(set(variable_overrides) - set(variables))
        if unknown:
            raise TemplateRuntimeError(f"variable_override_key_not_declared:{template_id}:{','.join(unknown)}")
        try:
            variables.update(copy.deepcopy(dict(variable_overrides)))
        except Exception as exc:
            raise TemplateRuntimeError(f"variable_overrides_copy_failed:{template_id}:{exc}") from exc
    for name in module_meta.get("submain_order", []):
        submain = getattr(module, str(name))
        returned = submain(context, MappingProxyType(variables))
        if not isinstance(returned, Mapping):
            raise TemplateRuntimeError(f"submain_return_mapping_required:{template_id}:{name}")
        if set(returned) != set(variables):
            raise TemplateRuntimeError(f"submain_variable_keys_changed:{template_id}:{name}")
        variables = dict(returned)
    return module.main(context, variables)


__all__ = ["discover_templates", "execute_template", "load_template", "template_status"]
