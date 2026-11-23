"""Index exact source spans as reusable deterministic AIOS function templates.

The catalog builder parses but never imports or executes AIOS source. Templates
are byte-preserved function/class spans; model output supplies IDs/data only.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _decorated_span(node: ast.AST) -> tuple[int, int]:
    decorators = getattr(node, "decorator_list", [])
    start = min([node.lineno, *(item.lineno for item in decorators)])
    return start, node.end_lineno


def _calls(node: ast.AST) -> list[str]:
    names: set[str] = set()
    for item in ast.walk(node):
        if not isinstance(item, ast.Call):
            continue
        func = item.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            parts = [func.attr]
            base = func.value
            while isinstance(base, ast.Attribute):
                parts.append(base.attr)
                base = base.value
            if isinstance(base, ast.Name):
                parts.append(base.id)
            names.add(".".join(reversed(parts)))
    return sorted(names)


def _parameters(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    args = node.args
    values = [arg.arg for arg in args.posonlyargs + args.args]
    if args.vararg:
        values.append("*" + args.vararg.arg)
    values.extend(arg.arg for arg in args.kwonlyargs)
    if args.kwarg:
        values.append("**" + args.kwarg.arg)
    return values


def _nodes(body: list[ast.stmt], prefix: str = "") -> Iterable[tuple[ast.AST, str, str]]:
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qualname = f"{prefix}.{node.name}" if prefix else node.name
            yield node, qualname, "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function"
        elif isinstance(node, ast.ClassDef):
            qualname = f"{prefix}.{node.name}" if prefix else node.name
            yield node, qualname, "class"
            yield from _nodes(node.body, qualname)


def build(
    candidate: Path,
    manifest_path: Path,
    transform_receipt_path: Path,
    output: Path,
) -> dict[str, Any]:
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    transform = json.loads(transform_receipt_path.read_text(encoding="utf-8"))
    transform_hash = transform.get("receipt_sha256")
    compile_exclusions = {row["path"]: row["reason"] for row in transform["compile_exclusions"]}
    transformed = {row["path"]: row["after_candidate_sha256"] for row in transform["transforms"]}
    core_names = [row["name"] for row in manifest["cores"]]
    core_by_path = {
        row["path"]: core
        for row in manifest["files"]
        for core in core_names
        if row["path"].startswith(core + "/")
    }
    catalog: list[dict[str, Any]] = []
    source_file_count = 0
    source_hash_errors: list[str] = []
    syntax_errors: list[dict[str, str]] = []
    for relative in sorted(core_by_path):
        if not relative.endswith(".py"):
            continue
        source_file_count += 1
        if relative in compile_exclusions:
            continue
        path = candidate / Path(relative)
        if not path.is_file():
            source_hash_errors.append(f"missing:{relative}")
            continue
        raw = path.read_bytes()
        digest = sha(raw)
        expected = transformed.get(relative)
        if expected is None:
            row = next(item for item in manifest["files"] if item["path"] == relative)
            expected = row["sha256"]
        if digest != expected:
            source_hash_errors.append(f"hash:{relative}")
            continue
        try:
            text = raw.decode("utf-8")
            tree = ast.parse(text, filename=relative)
        except (UnicodeError, SyntaxError) as error:
            syntax_errors.append({"path": relative, "error": str(error)})
            continue
        lines = text.splitlines(keepends=True)
        core = core_by_path[relative]
        for node, qualname, kind in _nodes(tree.body):
            start, end = _decorated_span(node)
            snippet = "".join(lines[start - 1 : end])
            encoded = snippet.encode("utf-8")
            identity = f"{relative}\0{qualname}\0{start}\0{end}\0{sha(encoded)}"
            catalog.append({
                "template_id": "fn-" + sha(identity.encode("utf-8")),
                "core": core,
                "source_path": relative,
                "source_file_sha256": digest,
                "qualified_name": qualname,
                "kind": kind,
                "start_line": start,
                "end_line": end,
                "parameters": _parameters(node) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else [],
                "direct_calls": _calls(node),
                "snippet_sha256": sha(encoded),
                "snippet_utf8": snippet,
            })
    catalog.sort(key=lambda row: (row["source_path"], row["start_line"], row["qualified_name"]))
    output.mkdir(parents=True, exist_ok=False)
    index: dict[str, int] = {}
    data_path = output / "functions.jsonl"
    with data_path.open("wb") as stream:
        for row in catalog:
            offset = stream.tell()
            if row["template_id"] in index:
                raise ValueError(f"duplicate template id: {row['template_id']}")
            index[row["template_id"]] = offset
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n")
        stream.flush()
    data_hash = sha(data_path.read_bytes())
    index_path = output / "lookup.json"
    index_path.write_text(json.dumps(index, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    registry = {
        "schema": "aios_19_core_function_template_registry_v1",
        "source_manifest_sha256": sha(manifest_bytes),
        "transformation_receipt_sha256": transform_hash,
        "core_names": core_names,
        "python_source_files_indexed": source_file_count,
        "python_source_files_excluded": compile_exclusions,
        "template_count": len(catalog),
        "functions_jsonl_sha256": data_hash,
        "lookup_sha256": sha(index_path.read_bytes()),
        "synthesis_performed": False,
        "source_imported_or_executed": False,
        "status": "PASS" if not source_hash_errors and not syntax_errors else "HOLD",
        "source_hash_errors": source_hash_errors,
        "syntax_errors": syntax_errors,
    }
    registry_path = output / "registry.json"
    registry_path.write_text(json.dumps(registry, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return registry


def verify(output: Path, candidate: Path) -> dict[str, Any]:
    registry = json.loads((output / "registry.json").read_text(encoding="utf-8"))
    index = json.loads((output / "lookup.json").read_text(encoding="utf-8"))
    data_path = output / "functions.jsonl"
    data_hash = sha(data_path.read_bytes())
    failures: list[str] = []
    if data_hash != registry["functions_jsonl_sha256"]:
        failures.append("functions_jsonl_hash")
    if sha((output / "lookup.json").read_bytes()) != registry["lookup_sha256"]:
        failures.append("lookup_hash")
    seen: set[str] = set()
    with data_path.open("rb") as stream:
        for template_id, offset in index.items():
            stream.seek(offset)
            line = stream.readline()
            try:
                row = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError):
                failures.append(f"invalid_index_row:{template_id}")
                continue
            if row.get("template_id") != template_id or template_id in seen:
                failures.append(f"index_identity:{template_id}")
                continue
            seen.add(template_id)
            snippet = row["snippet_utf8"].encode("utf-8")
            if sha(snippet) != row["snippet_sha256"]:
                failures.append(f"snippet_hash:{template_id}")
                continue
            source = candidate / Path(row["source_path"])
            if not source.is_file() or sha(source.read_bytes()) != row["source_file_sha256"]:
                failures.append(f"source_hash:{template_id}")
                continue
            text = source.read_bytes().decode("utf-8")
            lines = text.splitlines(keepends=True)
            extracted = "".join(lines[row["start_line"] - 1 : row["end_line"]])
            if extracted != row["snippet_utf8"]:
                failures.append(f"source_span:{template_id}")
    return {
        "schema": "aios_function_template_catalog_verification_v1",
        "status": "PASS" if not failures and len(seen) == registry["template_count"] else "HOLD",
        "template_count": registry["template_count"],
        "indexed_templates": len(seen),
        "failures": failures,
        "synthesis_performed": False,
        "source_imported_or_executed": False,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--transform-receipt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        result = verify(args.output, args.candidate)
    else:
        result = build(args.candidate, args.manifest, args.transform_receipt, args.output)
    output = dict(result)
    if isinstance(output.get("failures"), list):
        output["failure_count"] = len(output["failures"])
        output["failures"] = output["failures"][:20]
    print(json.dumps(output, ensure_ascii=False))
    raise SystemExit(0 if result["status"] == "PASS" else 1)
