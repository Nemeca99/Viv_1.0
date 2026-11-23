"""Build a metadata-only index of the copied Viv function catalog.

Candidate-only: reads the copied migration catalog, writes one local index and
receipt, and never changes the original catalog, live registry, Viv model,
memory, or topology. Function bodies stay in the source files; the index keeps
their exact source spans and hashes for deterministic builder use.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import ast
import hashlib
import json
from pathlib import Path
import re
import uuid

HERE = Path(__file__).resolve().parent
CATALOG = HERE / "candidate_template_toolbox" / "code_templates"
SOURCE = CATALOG / "source" / "migrated_domains"
RUNS = HERE / "learning" / "deepseek_candidate_runs"
SUITE = RUNS / "frozen_code_eval_v2_1.json"
INDEX_OUT = HERE / "candidate_template_toolbox" / "candidate_function_index_v2.json"
RECEIPT_OUT = RUNS / "candidate_template_catalog_index_v2.json"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_sha256(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    return sha256_bytes(raw)


def function_name(text: str) -> str | None:
    match = re.search(r"\b(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(", text)
    return match.group(1) if match else None


def task_names(rows: list[dict]) -> set[str]:
    return {name for row in rows
            if (name := function_name(str(row.get("spec", ""))))}


def argument_record(arg: ast.arg) -> dict:
    return {"name": arg.arg,
            "annotation": ast.unparse(arg.annotation) if arg.annotation else None}


def iter_functions(tree: ast.Module, prefix: tuple[str, ...] = ()):
    """Yield all definitions with stable qualified names, including nested."""
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qualname = (*prefix, node.name)
            yield node, qualname
            yield from iter_functions(node, qualname)
        elif isinstance(node, ast.ClassDef):
            yield from iter_functions(node, (*prefix, node.name))
        else:
            yield from iter_functions(node, prefix)


def main() -> int:
    if not SOURCE.is_dir():
        raise FileNotFoundError(f"candidate catalog source missing: {SOURCE}")
    if INDEX_OUT.exists() or RECEIPT_OUT.exists():
        raise FileExistsError("candidate catalog index artifacts already exist")

    suite = json.loads(SUITE.read_text(encoding="utf-8"))
    heldout_python = task_names([row for row in suite["held_out"]
                                 if row.get("lang") == "python"])
    previous_names: set[str] = set()
    for path in RUNS.glob("*training*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for sample in payload.get("samples", []):
            name = function_name(str(sample.get("completion", "")))
            if name:
                previous_names.add(name)

    files = sorted(SOURCE.rglob("*.py"))
    tree_digest = hashlib.sha256()
    records: list[dict] = []
    parse_errors: list[dict] = []
    top_level_count = 0
    domain_counts: Counter[str] = Counter()
    source_file_digests: dict[str, str] = {}

    for path in files:
        relative = path.relative_to(SOURCE).as_posix()
        data = path.read_bytes()
        digest = sha256_bytes(data)
        source_file_digests[relative] = digest
        tree_digest.update(relative.encode("utf-8") + b"\0" + digest.encode("ascii") + b"\n")
        try:
            source_text = data.decode("utf-8")
            module = ast.parse(source_text, filename=relative)
        except (UnicodeDecodeError, SyntaxError) as exc:
            parse_errors.append({"file": relative, "error": f"{type(exc).__name__}: {exc}"})
            continue

        module_nodes = {id(node) for node in module.body}
        lines = data.splitlines(keepends=True)
        for node, qualname in iter_functions(module):
            domain = path.parent.name
            domain_counts[domain] += 1
            if id(node) in module_nodes:
                top_level_count += 1
            start = min([node.lineno, *(decorator.lineno for decorator in node.decorator_list)])
            end = node.end_lineno or node.lineno
            span = b"".join(lines[start - 1:end])
            calls = sorted({
                call.func.id if isinstance(call.func, ast.Name)
                else call.func.attr if isinstance(call.func, ast.Attribute)
                else ""
                for call in ast.walk(node) if isinstance(call, ast.Call)
            } - {""})
            args = node.args
            record = {
                "function_id": f"{domain}:{relative}::{'.'.join(qualname)}@{start}",
                "domain": domain,
                "source_file": relative,
                "qualified_name": ".".join(qualname),
                "function_name": node.name,
                "async": isinstance(node, ast.AsyncFunctionDef),
                "top_level": id(node) in module_nodes,
                "start_line": start,
                "end_line": end,
                "decorator_inclusive": True,
                "source_file_sha256": digest,
                "source_span_sha256": sha256_bytes(span),
                "positional_only": [argument_record(arg) for arg in args.posonlyargs],
                "positional": [argument_record(arg) for arg in args.args],
                "keyword_only": [argument_record(arg) for arg in args.kwonlyargs],
                "vararg": argument_record(args.vararg) if args.vararg else None,
                "kwarg": argument_record(args.kwarg) if args.kwarg else None,
                "returns": ast.unparse(node.returns) if node.returns else None,
                "docstring": ast.get_docstring(node, clean=True),
                "direct_call_symbols": calls,
                "heldout_name_overlap": node.name in heldout_python,
                "prior_training_name_overlap": node.name in previous_names,
            }
            records.append(record)

    records.sort(key=lambda row: row["function_id"])
    duplicate_names = Counter(row["function_name"] for row in records)
    index_payload = {
        "schema": "viv_candidate_template_function_index_v2",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_only": True,
        "source_catalog": str(SOURCE),
        "source_tree_sha256": tree_digest.hexdigest(),
        "source_file_count": len(files),
        "source_file_sha256": source_file_digests,
        "domain_count": len({path.parent.name for path in files}),
        "domains": dict(sorted(domain_counts.items())),
        "function_record_count": len(records),
        "top_level_function_count": top_level_count,
        "parse_error_count": len(parse_errors),
        "parse_errors": parse_errors,
        "duplicate_function_name_count": sum(count > 1 for count in duplicate_names.values()),
        "heldout_python_name_overlap_ids": [row["function_id"] for row in records
                                             if row["heldout_name_overlap"]],
        "prior_training_name_overlap_ids": [row["function_id"] for row in records
                                              if row["prior_training_name_overlap"]],
        "body_policy": "function bodies remain in copied source files; metadata index only",
        "active_registry_changed": False,
        "training_authority_changed": False,
        "live_network_write": False,
        "topology_write": False,
        "persistent_memory_write": False,
        "functions": records,
    }
    index_payload["index_sha256"] = canonical_sha256(index_payload)
    INDEX_OUT.parent.mkdir(parents=True, exist_ok=True)
    INDEX_OUT.write_text(json.dumps(index_payload, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")

    receipt = {key: value for key, value in index_payload.items() if key != "functions"}
    receipt["index_path"] = str(INDEX_OUT)
    receipt["receipt_schema"] = "viv_candidate_template_catalog_index_receipt_v2"
    receipt["receipt_id"] = f"template-index-{uuid.uuid4().hex}"
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    RECEIPT_OUT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT_OUT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(json.dumps({
        "index": str(INDEX_OUT),
        "receipt": str(RECEIPT_OUT),
        "source_tree_sha256": index_payload["source_tree_sha256"],
        "source_files": len(files),
        "domains": index_payload["domain_count"],
        "functions": len(records),
        "top_level_functions": top_level_count,
        "parse_errors": len(parse_errors),
        "duplicate_names": index_payload["duplicate_function_name_count"],
        "heldout_name_overlaps": len(index_payload["heldout_python_name_overlap_ids"]),
        "prior_training_name_overlaps": len(index_payload["prior_training_name_overlap_ids"]),
        "training_or_live_writes": False,
    }, indent=2), flush=True)
    return 0 if not parse_errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
