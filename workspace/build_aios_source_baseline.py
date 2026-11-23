"""Create a read-only, hash-pinned source catalog for the original AIOS tree.

The catalog is the source map for the full Viv rebuild. It deliberately excludes
archival cores, environments, generated output, and binary/model artifacts.
It never copies, imports, or executes files from the source tree.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

SOURCE_ROOT = Path(r"F:\AIOS_Clean")
OUTPUT_ROOT = Path(__file__).resolve().parent / "aios_rebuild" / "source_baseline"
CORE_NAMES = (
    "luna_core",
    "carma_core",
    "dream_core",
    "data_core",
    "support_core",
    "utils_core",
    "enterprise_core",
    "rag_core",
    "streamlit_core",
    "backup_core",
    "fractal_core",
    "game_core",
    "marketplace_core",
    "music_core",
    "privacy_core",
    "template_core",
    "main_core",
    "infra_core",
    "consciousness_core",
)
ROOT_DIRS = ("api", "config", "docs", "scripts", "tests")
ROOT_FILES = (
    "AIOS_MANUAL.md",
    "MANUAL_TOC.md",
    "AIOS_EXECUTIVE_SUMMARY.md",
    "AIOS_ENGINEERING_VALIDATION.md",
    "AIOS_TECHNICAL_VALIDATION_REPORT.md",
    "AIOS_V5_FINAL_STATUS.md",
    "README.md",
    "README_INSTALL.md",
    "pyproject.toml",
    "pytest.ini",
    "requirements.txt",
    "requirements-production.txt",
    "main.py",
    "luna_chat.py",
    "luna_launcher.py",
    "setup.ps1",
)
INCLUDED_SUFFIXES = {
    ".py",
    ".rs",
    ".toml",
    ".json",
    ".yaml",
    ".yml",
    ".md",
    ".txt",
    ".ini",
    ".ps1",
    ".sh",
    ".sql",
    ".html",
    ".css",
    ".js",
    ".tsx",
    ".ts",
    ".xml",
    ".cfg",
}
EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "target",
    "build",
    "dist",
    "node_modules",
    ".pytest_cache",
    ".hypothesis",
    ".mypy_cache",
    ".ruff_cache",
    ".specstory",
    "archive_dev_core",
    "logs",
    "log",
    "cache",
    "caches",
    "models",
    "model",
    "checkpoints",
    "artifacts",
    "runs",
    "temp",
    "tmp",
    "active_backup",
    "storage",
    "embedder_cache",
    "fractalcache",
    "data_backup_analysis",
    "conversations",
    "memshort",
    "drift_logs_test",
    "streamlit_main",
    "streamlit_components",
    "streamlit_docs",
    "streamlit_examples",
    "streamlit_llm_examples",
    "streamlit_docs",
    "streamlit_examples",
    "streamlit_llm_examples",
}
EXCLUDED_BASENAMES = {
    "blackwall_logs.md",
    "luna_learning_history.json",
    "aios_standards_check.json",
    "master_cache.json",
    "backup_cache.json",
    "test_summary.json",
}
MAX_FILE_BYTES = 8 * 1024 * 1024
CORE_SECTION = re.compile(
    r"^##\s+3\.(\d+)\s+([a-z0-9_]+)\s+-", re.MULTILINE | re.IGNORECASE
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_reparse(path: Path) -> bool:
    is_junction = getattr(os.path, "isjunction", None)
    return path.is_symlink() or bool(is_junction and is_junction(path))


STREAMLIT_VENDOR_DIRS = {
    "streamlit_main",
    "streamlit_components",
    "streamlit_docs",
    "streamlit_examples",
    "streamlit_llm_examples",
}


def _iter_tree(
    root: Path, source_root: Path, excluded_dirs: set[str] | None = None
) -> Iterable[Path]:
    root_resolved = source_root.resolve(strict=True)
    excluded = EXCLUDED_DIRS if excluded_dirs is None else excluded_dirs
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        kept: list[str] = []
        for dirname in dirs:
            child = current_path / dirname
            if dirname.casefold() in excluded or _is_reparse(child):
                continue
            try:
                if root_resolved not in child.resolve(strict=True).parents:
                    continue
            except (OSError, RuntimeError):
                continue
            kept.append(dirname)
        dirs[:] = kept
        for filename in files:
            path = current_path / filename
            if (
                _is_reparse(path)
                or path.suffix.casefold() not in INCLUDED_SUFFIXES
                or path.name.casefold() in EXCLUDED_BASENAMES
            ):
                continue
            try:
                if path.stat().st_size > MAX_FILE_BYTES:
                    continue
                if root_resolved not in path.resolve(strict=True).parents:
                    continue
            except (OSError, RuntimeError):
                continue
            yield path


def _imports_by_core(
    files: list[dict[str, object]], source_root: Path
) -> list[dict[str, str]]:
    edges: set[tuple[str, str, str]] = set()
    known = set(CORE_NAMES)
    for entry in files:
        relative = str(entry["path"])
        if not relative.endswith(".py"):
            continue
        parts = Path(relative).parts
        source_core = next((part for part in parts if part in known), None)
        if source_core is None:
            continue
        path = source_root / Path(relative)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except (OSError, UnicodeError, SyntaxError):
            continue
        for node in ast.walk(tree):
            module_names: list[str] = []
            if isinstance(node, ast.Import):
                module_names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                module_names.append(node.module)
            for module_name in module_names:
                target_core = next(
                    (part for part in module_name.split(".") if part in known), None
                )
                if target_core and target_core != source_core:
                    edges.add((source_core, target_core, "static_python_import"))
    return [
        {"consumer": source, "provider": target, "evidence": evidence}
        for source, target, evidence in sorted(edges)
    ]


def _dependency_layers(edges: list[dict[str, str]]) -> dict[str, object]:
    """Derive parallel rebuild cohorts from observed static import edges."""
    dependencies = {name: set() for name in CORE_NAMES}
    for edge in edges:
        dependencies[edge["consumer"]].add(edge["provider"])
    remaining = {name: set(providers) for name, providers in dependencies.items()}
    layers: list[list[str]] = []
    while remaining:
        ready = sorted(
            name
            for name, providers in remaining.items()
            if not (providers & remaining.keys())
        )
        if not ready:
            return {
                "method": "static_python_import_layers",
                "layers": layers,
                "cycle_nodes": sorted(remaining),
                "dependencies": {
                    name: sorted(providers)
                    for name, providers in sorted(dependencies.items())
                },
            }
        layers.append(ready)
        for name in ready:
            del remaining[name]
    return {
        "method": "static_python_import_layers",
        "layers": layers,
        "cycle_nodes": [],
        "dependencies": {
            name: sorted(providers) for name, providers in sorted(dependencies.items())
        },
    }


def build_manifest(
    source_root: Path = SOURCE_ROOT, *, include_streamlit_vendor: bool = False
) -> dict[str, object]:
    source_root = source_root.resolve(strict=True)
    sections_path = source_root / "AIOS_MANUAL.md"
    toc_path = source_root / "MANUAL_TOC.md"
    section_text = sections_path.read_text(encoding="utf-8")
    section_rows = [
        {"number": int(number), "core": name.lower()}
        for number, name in CORE_SECTION.findall(section_text)
    ]
    manual_cores = [row["core"] for row in section_rows]
    if tuple(manual_cores) != CORE_NAMES:
        raise ValueError(
            f"manual core order differs from the declared source list: {manual_cores}"
        )

    selected_roots = [source_root / name for name in (*CORE_NAMES, *ROOT_DIRS)]
    excluded_dirs = set(EXCLUDED_DIRS)
    if include_streamlit_vendor:
        excluded_dirs.difference_update(STREAMLIT_VENDOR_DIRS)
    files: list[dict[str, object]] = []
    for name in ROOT_FILES:
        path = source_root / name
        if (
            path.is_file()
            and not _is_reparse(path)
            and path.stat().st_size <= MAX_FILE_BYTES
        ):
            files.append(
                {
                    "path": name,
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    for root in selected_roots:
        if not root.is_dir() or _is_reparse(root):
            continue
        for path in _iter_tree(root, source_root, excluded_dirs):
            relative = path.relative_to(source_root).as_posix()
            files.append(
                {
                    "path": relative,
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    by_path = {str(row["path"]): row for row in files}
    files = [by_path[key] for key in sorted(by_path)]

    core_inventory = []
    for name in CORE_NAMES:
        rows = [row for row in files if str(row["path"]).startswith(name + "/")]
        core_inventory.append(
            {
                "name": name,
                "directory_present": (source_root / name).is_dir(),
                "catalogued_files": len(rows),
                "python_files": sum(str(row["path"]).endswith(".py") for row in rows),
                "source_bytes": sum(int(row["bytes"]) for row in rows),
            }
        )

    cross_core_edges = _imports_by_core(files, source_root)
    manifest: dict[str, object] = {
        "schema": "aios_clean_source_baseline_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_root": str(source_root),
        "workspace_target": "L:/LocalCoder/workspace/aios_rebuild",
        "scope": "19 active manual-listed cores plus API, config, docs, scripts, tests, and named root entrypoints"
        + (" including all cataloguable Streamlit vendor sources" if include_streamlit_vendor else ""),
        "excluded_archives": ["archive_dev_core"],
        "excluded_material": {
            "directories": sorted(excluded_dirs),
            "basenames": sorted(EXCLUDED_BASENAMES),
            "reason": "archives, runtime state, conversation/history data, caches, environments, and generated outputs are not implementation source",
        },
        "max_catalogued_file_bytes": MAX_FILE_BYTES,
        "manual_sha256": sha256_file(sections_path),
        "toc_sha256": sha256_file(toc_path),
        "manual_core_sections": section_rows,
        "cores": core_inventory,
        "file_count": len(files),
        "catalogued_bytes": sum(int(row["bytes"]) for row in files),
        "static_cross_core_import_edges": cross_core_edges,
        "static_rebuild_graph": _dependency_layers(cross_core_edges),
        "files": files,
    }
    return manifest


def stage_source_tree(
    manifest: dict[str, object], source_root: Path, target_root: Path
) -> dict[str, object]:
    """Copy manifest-listed sources without replacing a differing staged file."""
    source_root = source_root.resolve(strict=True)
    target_root = target_root.resolve()
    if source_root.drive.casefold() == target_root.drive.casefold():
        raise ValueError("staging target must be on a different drive from the source")
    target_root.mkdir(parents=True, exist_ok=True)
    copied = 0
    already_identical = 0
    failures: list[dict[str, str]] = []
    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise ValueError("source manifest file list is missing")
    for entry in entries:
        relative = Path(str(entry["path"]))
        if relative.is_absolute() or relative.drive or ".." in relative.parts:
            raise ValueError(f"unsafe relative source path: {relative}")
        source = source_root / relative
        target = target_root / relative
        expected = str(entry["sha256"])
        try:
            if source_root not in source.resolve(strict=True).parents or _is_reparse(
                source
            ):
                raise ValueError("source path escaped or is a reparse point")
            if sha256_file(source) != expected:
                raise ValueError("source hash changed after catalog")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if _is_reparse(target) or sha256_file(target) != expected:
                    raise ValueError("existing staged file differs; left unchanged")
                already_identical += 1
                continue
            temporary = target.with_name(target.name + ".hive-copy.tmp")
            if temporary.exists():
                raise ValueError("staging temp path already exists; left unchanged")
            shutil.copyfile(source, temporary)
            if sha256_file(temporary) != expected:
                temporary.unlink()
                raise ValueError("copied file hash mismatch")
            temporary.replace(target)
            copied += 1
        except (OSError, ValueError, KeyError, TypeError) as exc:
            failures.append({"path": str(relative), "reason": str(exc)})
    return {
        "schema": "aios_clean_source_staging_receipt_v1",
        "status": "PASS" if not failures else "HOLD",
        "source_root": str(source_root),
        "target_root": str(target_root),
        "catalogued_count": len(entries),
        "copied_count": copied,
        "already_identical_count": already_identical,
        "failure_count": len(failures),
        "failures": failures,
        "source_modified": False,
        "existing_target_files_overwritten": 0,
    }


def verify_staged_tree(
    manifest: dict[str, object], source_root: Path, target_root: Path
) -> dict[str, object]:
    """Independently compare source and staged hashes and compile Python syntax only."""
    source_root = source_root.resolve(strict=True)
    target_root = target_root.resolve(strict=True)
    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise ValueError("source manifest file list is missing")
    missing: list[str] = []
    source_changed: list[str] = []
    staged_mismatch: list[str] = []
    syntax_errors: list[dict[str, str]] = []
    warning_rows: list[dict[str, str]] = []
    expected_paths: set[str] = set()
    for entry in entries:
        relative_text = str(entry["path"])
        relative = Path(relative_text)
        if relative.is_absolute() or relative.drive or ".." in relative.parts:
            raise ValueError(f"unsafe relative source path: {relative_text}")
        expected_paths.add(relative.as_posix())
        source = source_root / relative
        staged = target_root / relative
        expected_sha = str(entry["sha256"])
        if not source.is_file() or not staged.is_file():
            missing.append(relative_text)
            continue
        if sha256_file(source) != expected_sha:
            source_changed.append(relative_text)
        if sha256_file(staged) != expected_sha:
            staged_mismatch.append(relative_text)
        if relative.suffix.casefold() == ".py":
            try:
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always", SyntaxWarning)
                    source_text = staged.read_text(encoding="utf-8")
                    compile(source_text, str(staged), "exec", dont_inherit=True)
                warning_rows.extend(
                    {"path": relative_text, "warning": str(row.message)}
                    for row in caught
                )
            except (OSError, UnicodeError, SyntaxError) as exc:
                syntax_errors.append({"path": relative_text, "error": str(exc)})

    actual_paths = {
        path.relative_to(target_root).as_posix()
        for path in target_root.rglob("*")
        if path.is_file()
    }
    unexpected = sorted(actual_paths - expected_paths)
    missing_from_tree = sorted(expected_paths - actual_paths)
    passed = not (
        missing
        or source_changed
        or staged_mismatch
        or syntax_errors
        or unexpected
        or missing_from_tree
    )
    return {
        "schema": "aios_clean_staged_source_verification_v1",
        "status": "PASS" if passed else "HOLD",
        "catalogued_file_count": len(entries),
        "manifest_file_count_verified": len(entries),
        "staged_file_count": len(actual_paths),
        "python_syntax_compiled_count": sum(
            str(row["path"]).endswith(".py") for row in entries
        ),
        "source_hash_mismatch_count": len(source_changed),
        "staged_hash_mismatch_count": len(staged_mismatch),
        "missing_file_count": len(set(missing + missing_from_tree)),
        "unexpected_file_count": len(unexpected),
        "python_syntax_error_count": len(syntax_errors),
        "python_syntax_warning_count": len(warning_rows),
        "source_files_executed": False,
        "source_files_modified": False,
        "source_hash_mismatches": source_changed,
        "staged_hash_mismatches": staged_mismatch,
        "missing_files": sorted(set(missing + missing_from_tree)),
        "unexpected_files": unexpected,
        "python_syntax_errors": syntax_errors,
        "python_syntax_warnings": warning_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    parser.add_argument(
        "--stage",
        action="store_true",
        help="copy the catalogued AIOS source tree into this workspace",
    )
    parser.add_argument(
        "--include-streamlit-vendor",
        action="store_true",
        help="include Streamlit vendor source, docs, and examples",
    )
    parser.add_argument(
        "--stage-dir",
        default="source_tree_v3",
        help="new staging directory name under --output",
    )
    args = parser.parse_args()
    manifest = build_manifest(
        args.source, include_streamlit_vendor=args.include_streamlit_vendor
    )
    args.output.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output / "source_manifest.json"
    encoded = (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode(
            "utf-8"
        )
        + b"\n"
    )
    manifest_path.write_bytes(encoded)
    digest = hashlib.sha256(encoded).hexdigest()
    (args.output / "source_manifest.sha256").write_text(
        f"{digest}  source_manifest.json\n", encoding="ascii"
    )
    receipt = {
        "schema": "aios_clean_source_catalog_receipt_v1",
        "status": "PASS",
        "source_root": manifest["source_root"],
        "manifest": str(manifest_path),
        "manifest_sha256": digest,
        "core_count": len(manifest["cores"]),
        "catalogued_files": manifest["file_count"],
        "catalogued_bytes": manifest["catalogued_bytes"],
        "static_cross_core_import_edge_count": len(
            manifest["static_cross_core_import_edges"]
        ),
        "builder_sha256": sha256_file(Path(__file__).resolve()),
        "builder_test_sha256": sha256_file(
            Path(__file__).resolve().parent / "test_build_aios_source_baseline.py"
        ),
        "source_manifest_sha256": digest,
        "source_modified": False,
        "source_code_executed": False,
        "archival_core_included": False,
        "streamlit_vendor_included": args.include_streamlit_vendor,
    }
    (args.output / "catalog_receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    if args.stage:
        if Path(args.stage_dir).name != args.stage_dir or args.stage_dir in {".", ".."}:
            raise ValueError("--stage-dir must be a plain directory name")
        staged_root = args.output / args.stage_dir
        staging = stage_source_tree(manifest, args.source, staged_root)
        staging["source_manifest_sha256"] = digest
        (args.output / "staging_receipt.json").write_text(
            json.dumps(staging, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        if staging["status"] != "PASS":
            print(json.dumps(staging, ensure_ascii=False, sort_keys=True))
            return 1
        verification = verify_staged_tree(manifest, args.source, staged_root)
        verification["source_manifest_sha256"] = digest
        (args.output / "verification_receipt.json").write_text(
            json.dumps(verification, ensure_ascii=False, sort_keys=True, indent=2)
            + "\n",
            encoding="utf-8",
        )
        if verification["status"] != "PASS":
            print(json.dumps(verification, ensure_ascii=False, sort_keys=True))
            return 1
        print(json.dumps(verification, ensure_ascii=False, sort_keys=True))
        print(json.dumps(staging, ensure_ascii=False, sort_keys=True))
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
