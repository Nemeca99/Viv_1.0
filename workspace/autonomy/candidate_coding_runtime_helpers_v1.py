"""Candidate-only coding runtime with verified SQLite helper composition.

This runtime reads the isolated verified-function store in read-only mode,
offers the admitted Python functions as retrieval context, resolves exact
function references and unambiguous standard-library imports, then gates the
composed source with the existing Rust/Python body gates. It never writes the
store, topology, or live adapter; the serving adapter is restored after eval.
"""
from __future__ import annotations

from datetime import datetime, timezone
import ast
import builtins
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
import urllib.request
import uuid

import candidate_coding_runtime_v1 as base
import candidate_efficiency_observations_v1 as efficiency
from aios_rebuild.privacy_core.privacy_core import PrivacyCore

HERE = Path(__file__).resolve().parent
STORE_DB = HERE / "learning" / "neural_runs" / "candidate_verified_functions.sqlite3"
SUITE = HERE / "learning" / "deepseek_candidate_runs" / "frozen_code_eval_v2_1.json"
MAX_HELPER_CHARS = 4000
SAFE_STDLIB_MODULES = (
    "itertools", "math", "collections", "functools", "operator", "heapq",
    "bisect", "statistics", "re", "string", "textwrap", "unicodedata",
    "decimal", "fractions", "datetime", "calendar", "typing",
)


def sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def stdlib_exports() -> dict[str, list[str]]:
    exports: dict[str, list[str]] = {}
    for module_name in SAFE_STDLIB_MODULES:
        module = importlib.import_module(module_name)
        exports.setdefault(module_name, []).append(module_name)
        for name in dir(module):
            if name.startswith("_"):
                continue
            try:
                value = getattr(module, name)
            except Exception:
                continue
            if callable(value):
                owner = getattr(value, "__module__", None)
                canonical_module = (owner if owner in SAFE_STDLIB_MODULES
                                   and getattr(importlib.import_module(owner), name, None) is value
                                   else module_name)
                exports.setdefault(name, []).append(canonical_module)
    return {name: sorted(set(modules)) for name, modules in exports.items()}


STDLIB_EXPORTS = stdlib_exports()


def load_helper_catalog() -> tuple[dict[str, dict], dict]:
    """Read and hash-check only active, off-split, ALLOW Python functions."""
    if not STORE_DB.is_file():
        raise FileNotFoundError(STORE_DB)
    suite = json.loads(SUITE.read_text(encoding="utf-8"))
    claimed = suite.pop("suite_sha256", None)
    if claimed != base.canonical_hash(suite):
        raise ValueError("FROZEN_SUITE_HASH_MISMATCH")
    held_ids = {str(row["id"]) for row in suite["held_out"]}
    held_names = set()
    for row in suite["held_out"]:
        match = re.search(r"\bdef\s+([A-Za-z_]\w*)\s*\(", row["spec"])
        if match:
            held_names.add(match.group(1))

    uri = f"file:{STORE_DB.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute("""
            SELECT f.function_key,f.function_name,f.signature,f.specification,
                   v.version_id,v.task_id,v.code,v.code_sha256,v.tests_sha256,
                   v.gate_name,v.gate_status,v.gate_output,v.gate_receipt_sha256,
                   v.admitted_utc
            FROM active_versions a
            JOIN functions f USING(function_key)
            JOIN function_versions v ON v.version_id=a.version_id
            WHERE f.language='python'
            ORDER BY f.function_name
        """).fetchall()
    catalog: dict[str, dict] = {}
    duplicates: set[str] = set()
    for row in rows:
        name = row["function_name"]
        if row["task_id"] in held_ids or name in held_names:
            raise ValueError(f"HELDOUT_HELPER_IN_CANDIDATE_STORE:{name}")
        if row["gate_status"] != "ALLOW":
            raise ValueError(f"UNVERIFIED_HELPER_STATUS:{name}")
        if sha_text(row["code"]) != row["code_sha256"]:
            raise ValueError(f"HELPER_CODE_HASH_MISMATCH:{name}")
        evidence = {
            "task_id": row["task_id"], "language": "python",
            "function_key": row["function_key"],
            "code_sha256": row["code_sha256"],
            "tests_sha256": row["tests_sha256"], "gate": row["gate_name"],
            "status": row["gate_status"], "output": row["gate_output"],
            "created_utc": row["admitted_utc"],
        }
        if base.canonical_hash(evidence) != row["gate_receipt_sha256"]:
            raise ValueError(f"HELPER_RECEIPT_HASH_MISMATCH:{name}")
        if len(row["code"]) > MAX_HELPER_CHARS:
            continue
        try:
            tree = ast.parse(row["code"])
        except SyntaxError as exc:
            raise ValueError(f"HELPER_AST_INVALID:{name}") from exc
        fn_defs = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        if name not in fn_defs:
            raise ValueError(f"HELPER_ENTRYPOINT_MISSING:{name}")
        if name in catalog:
            duplicates.add(name)
        catalog[name] = {
            "name": name, "signature": row["signature"],
            "specification": row["specification"], "version_id": row["version_id"],
            "task_id": row["task_id"], "function_key": row["function_key"],
            "code": row["code"], "code_sha256": row["code_sha256"],
            "tests_sha256": row["tests_sha256"],
            "gate_receipt_sha256": row["gate_receipt_sha256"],
        }
    for name in duplicates:
        catalog.pop(name, None)
    store_hash = base.sha256(STORE_DB)
    return catalog, {"database_sha256": store_hash, "helper_count": len(catalog),
                     "excluded_oversize": sum(len(r["code"]) > MAX_HELPER_CHARS for r in rows),
                     "heldout_task_count": len(held_ids)}


def _raw_code_region(raw: str) -> str:
    match = re.search(r"```(?:python|py)?\s*\n(.*?)```", raw, re.S)
    text = match.group(1) if match else raw
    for marker in ("\nUSER:", "\nSYSTEM:", "\nASSISTANT:"):
        if marker in text:
            text = text.split(marker, 1)[0]
    return text


def extract_imports(raw: str) -> list[str]:
    """Retain only top-level import statements emitted by the model."""
    lines = _raw_code_region(raw).splitlines()
    found: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if re.match(r"^\s*(?:import\s|from\s)", line):
            block = [line]
            balance = line.count("(") - line.count(")")
            while balance > 0 and index + 1 < len(lines):
                index += 1
                block.append(lines[index])
                balance += lines[index].count("(") - lines[index].count(")")
            found.append("\n".join(block).strip())
        index += 1
    if not found:
        return []
    tree = ast.parse("\n".join(found))
    result = []
    for node in tree.body:
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            raise ValueError("NON_IMPORT_TOP_LEVEL_OUTPUT")
        module = node.module if isinstance(node, ast.ImportFrom) else None
        roots = ([module.split(".")[0]] if module else
                 [alias.name.split(".")[0] for alias in node.names])
        if any(root not in sys.stdlib_module_names for root in roots):
            raise ValueError("NON_STDLIB_IMPORT_DENIED")
        result.append(ast.unparse(node))
    return list(dict.fromkeys(result))


def _global_names(code: str) -> tuple[set[str], set[str]]:
    tree = ast.parse(code)
    loads = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)
             and isinstance(n.ctx, ast.Load)}
    stores = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)
              and isinstance(n.ctx, (ast.Store, ast.Param))}
    stores.update(n.name for n in ast.walk(tree)
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
    stores.update(a.arg for a in ast.walk(tree) if isinstance(a, ast.arg))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.update(alias.asname or alias.name for alias in node.names)
    calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name)}
    return loads - stores - imported - set(dir(builtins)), calls


def compose_python(raw: str, function_code: str, catalog: dict[str, dict]) -> dict:
    imports = extract_imports(raw)
    import_names = set()
    for statement in imports:
        node = ast.parse(statement).body[0]
        if isinstance(node, ast.Import):
            import_names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
        else:
            import_names.update(alias.asname or alias.name for alias in node.names)

    selected: dict[str, dict] = {}
    helper_order: list[str] = []
    auto_imports: dict[str, str] = {}
    unresolved_history: list[str] = []

    def visit(code: str, depth: int = 0) -> None:
        if depth > 12:
            raise ValueError("HELPER_DEPENDENCY_DEPTH_EXCEEDED")
        missing, calls = _global_names(code)
        for name in sorted(missing - import_names):
            if name in selected:
                continue
            if name in catalog and name in calls:
                helper = catalog[name]
                selected[name] = helper
                visit(helper["code"], depth + 1)
                helper_order.append(name)
                continue
            modules = STDLIB_EXPORTS.get(name, [])
            if len(modules) == 1:
                auto_imports[name] = modules[0]
            elif len(modules) > 1:
                unresolved_history.append(f"AMBIGUOUS_STDLIB_SYMBOL:{name}")
            else:
                unresolved_history.append(f"UNRESOLVED_NAME:{name}")

    visit(function_code)
    for name, module in sorted(auto_imports.items()):
        statement = f"from {module} import {name}"
        if statement not in imports:
            imports.append(statement)

    composed_parts = [*imports]
    for name in helper_order:
        composed_parts.append(selected[name]["code"])
    composed_parts.append(function_code)
    composed = "\n\n".join(part for part in composed_parts if part.strip())
    # A missing global may have been introduced in a helper and is never
    # silently repaired; the body gate receives the exact unresolved code.
    return {
        "code": composed, "imports": imports,
        "auto_imports": [{"name": name, "module": module}
                         for name, module in sorted(auto_imports.items())],
        "helpers": [selected[name] for name in sorted(selected)],
        "resolution_notes": unresolved_history,
        "source_code_sha256": sha_text(function_code),
        "composed_code_sha256": sha_text(composed),
    }


def python_proposal(task: dict, attempt: int, previous: dict | None,
                    grounding: dict, catalog: dict[str, dict]) -> tuple[str, str, dict]:
    spec = task["spec"]
    context = grounding.get("prompt_context", "")
    helper_context = "\n\n".join(
        f"# verified helper {row['name']} version={row['version_id']} sha256={row['code_sha256']}\n{row['code']}"
        for row in catalog.values())
    feedback = ""
    if previous:
        feedback = (
            "\n\nPrevious attempt failed the deterministic gate.\n"
            f"Gate output:\n{previous['error'][:3000]}\n"
            f"Tests to satisfy:\n{task['tests']}\n"
            "Return the complete requested Python function only. Include required standard-library imports.\n"
        )
    uml = "" if not context else "\n\nVerified UML context:\n" + context
    prompt = (
        "SYSTEM: Write one correct standard-library Python function for the task. "
        "You may call the exact verified helper functions listed below; their source will be linked into the candidate before deterministic testing. "
        "The runtime resolves unambiguous standard-library imports. Do not use third-party packages. "
        "Return one fenced Python function and any required standard-library imports; no tests or explanation.\n\n"
        "VERIFIED CANDIDATE STORE HELPERS (off-split, ALLOW, hash-validated):\n"
        + helper_context + "\n\nUSER: Implement: " + spec + uml + feedback + "\n\nASSISTANT:"
    )
    with efficiency.measure_completion() as generation_metrics:
        raw = base.request_completion(prompt, base.GENERATION_TEMPERATURE)
    code = base.evaluator.extract_requested_function(raw, "python", spec)
    generation_metrics["output_entropy_proxy"] = efficiency.output_entropy_proxy(raw)
    generation_metrics["generated_characters"] = len(raw)
    generation_metrics["generated_characters_per_second"] = (
        len(raw) / generation_metrics["wall_seconds"]
        if generation_metrics.get("wall_seconds", 0) else None)
    generation_metrics["steps"] = {"value": None, "unit": "model_tokens",
                                    "state": "UNAVAILABLE_API_DID_NOT_RETURN_TOKEN_IDS"}
    return raw, code, generation_metrics


def run_task(task: dict, candidate: Path, catalog: dict[str, dict]) -> dict:
    if task["lang"] != "python":
        # Preserve the established Rust proposal and gate contracts while
        # attaching measurements to each proposal and deterministic gate run.
        observed_proposals: list[dict] = []
        observed_gates: dict[int, dict] = {}
        original_request = base.request_completion
        original_gate = base.gates.gate_rust

        def measured_request(*args, **kwargs):
            with efficiency.measure_completion() as sample:
                raw = original_request(*args, **kwargs)
            sample["generated_characters"] = len(raw)
            sample["generated_characters_per_second"] = (
                len(raw) / sample["wall_seconds"] if sample.get("wall_seconds", 0) else None)
            sample["output_entropy_proxy"] = efficiency.output_entropy_proxy(raw)
            sample["steps"] = {"value": None, "unit": "model_tokens",
                               "state": "UNAVAILABLE_API_DID_NOT_RETURN_TOKEN_IDS"}
            observed_proposals.append(sample)
            return raw

        def measured_gate(code, tests):
            started = time.perf_counter()
            with efficiency.GpuPowerSampler() as sampler:
                passed, error = original_gate(code, tests)
            observed_gates[len(observed_proposals)] = {
                "gate_wall_seconds": time.perf_counter() - started,
                "gpu": sampler.report(),
                "steps": {"value": None, "unit": "native_instructions",
                          "state": "UNAVAILABLE_NATIVE_STEP_COUNTER"}}
            return passed, error

        base.request_completion = measured_request
        base.gates.gate_rust = measured_gate
        try:
            result = base.run_task(task, candidate)
        finally:
            base.request_completion = original_request
            base.gates.gate_rust = original_gate
        for index, attempt_row in enumerate(result["attempts"]):
            if index < len(observed_proposals):
                attempt_row["efficiency_observations"] = {
                    "generation": observed_proposals[index],
                    "output_entropy_proxy": observed_proposals[index]["output_entropy_proxy"],
                }
            if index + 1 in observed_gates:
                attempt_row.setdefault("efficiency_observations", {})[
                    "deterministic_gate"] = observed_gates[index + 1]
        return result
    attempts = []
    previous = None
    grounding = base.uml_context_for_task(task)
    for attempt in range(1, base.MAX_ATTEMPTS + 1):
        raw, function_code, generation_metrics = python_proposal(task, attempt, previous, grounding, catalog)
        composition = {"code": "", "helpers": [], "imports": [], "auto_imports": [],
                       "resolution_notes": [], "source_code_sha256": None,
                       "composed_code_sha256": None}
        if not function_code:
            ok, error = False, "NO_COMPLETE_REQUESTED_FUNCTION"
        else:
            try:
                composition = compose_python(raw, function_code, catalog)
                ok, error = base.gates.gate_python(composition["code"], task["tests"])
            except (SyntaxError, ValueError) as exc:
                ok, error = False, f"COMPOSITION_RESOLUTION_ERROR:{type(exc).__name__}:{exc}"
        execution_metrics = {"state": "NOT_RUN_UNTIL_GATE_ALLOW"}
        if ok:
            names = [node.name for node in ast.walk(ast.parse(composition["code"]))
                     if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
            _, execution_metrics, _ = efficiency.profile_python_execution(
                composition["code"], task["tests"], names)
        row = {
            "attempt": attempt, "passed": bool(ok), "error": error[:4000],
            "raw_output": raw, "code": function_code,
            "composed_code": composition["code"],
            "composition": {key: value for key, value in composition.items() if key != "code"},
            "signature_prefix": "", "uml_grounding": grounding,
            "efficiency_observations": {
                "generation": generation_metrics,
                "output_entropy_proxy": generation_metrics["output_entropy_proxy"],
                "deterministic_gate_and_execution": execution_metrics,
                "aggregate_efficiency_score": None,
                "score_state": "NOT_COMPUTED_FORMULA_AND_NORMALIZATION_NOT_LOCKED",
            },
        }
        attempts.append(row)
        print(json.dumps({"task": task["id"], "language": "python", "attempt": attempt,
                          "passed": bool(ok), "helpers": [h["name"] for h in composition["helpers"]],
                          "auto_imports": composition["auto_imports"],
                          "gate": error[:180]}, ensure_ascii=False), flush=True)
        if ok:
            break
        previous = {"raw": raw, "error": error}
    return {"task": task["id"], "lang": task["lang"],
            "first_pass": attempts[0]["passed"], "final_pass": attempts[-1]["passed"],
            "uml_grounding": grounding, "attempts": attempts}


def run_suite(suite_path: Path, candidate: Path) -> Path:
    envelope = json.loads(suite_path.read_text(encoding="utf-8"))
    expected = envelope.pop("suite_sha256", None)
    if expected != base.canonical_hash(envelope):
        raise ValueError("FROZEN_SUITE_HASH_MISMATCH")
    before = base.evaluator.request("/v1/status")
    if before.get("status") != "ACTIVE" or before.get("active_adapter") != base.LIVE.name:
        raise RuntimeError("UNEXPECTED_LIVE_ADAPTER:" + json.dumps(before))
    catalog, store_info = load_helper_catalog()
    adapter_hash = base.sha256(candidate / "adapter_model.safetensors")
    results = []
    restored = None
    try:
        base.evaluator.activate(candidate)
        for task in envelope["held_out"]:
            results.append(run_task(task, candidate, catalog))
    finally:
        restored = base.evaluator.activate(base.LIVE)
    by_language = {}
    for lang in ("python", "rust"):
        rows = [r for r in results if r["lang"] == lang]
        by_language[lang] = {
            "first_pass": sum(bool(r["first_pass"]) for r in rows),
            "final_pass": sum(bool(r["final_pass"]) for r in rows), "total": len(rows),
        }
    receipt = {
        "schema": "viv_candidate_coding_runtime_helpers_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "suite_path": str(suite_path), "suite_sha256": expected,
        "candidate_path": str(candidate), "candidate_sha256": adapter_hash,
        "runtime_script_sha256": base.sha256(Path(__file__).resolve()),
        "base_runtime_sha256": base.sha256(Path(base.__file__).resolve()),
        "helper_store": store_info,
        "helper_contract": "active off-split ALLOW rows only; SQLite opened read-only; code and gate receipts SHA-256 checked; no store writes",
        "stdlib_import_contract": "unambiguous exports from a fixed standard-library module set are imported deterministically",
        "efficiency_observation_contract": "raw generation wall/process CPU time, sampled whole-board GPU power/energy, and output character-entropy proxy; accepted Python code gets dynamic source-line step profiling; Rust records gate wall time and board telemetry but native instruction steps remain unavailable; no aggregate reward score computed",
        "generation": {"temperature": base.GENERATION_TEMPERATURE, "do_sample": False},
        "attempt_limit": base.MAX_ATTEMPTS, "by_language": by_language,
        "results": results, "live_before": before, "live_restored": restored,
        "promoted": False, "topology_write": False, "persistent_memory_write": False,
    }
    receipt["receipt_sha256"] = base.canonical_hash(receipt)
    receipt_dir = HERE / "learning" / "neural_runs"
    target = receipt_dir / (f"candidate_runtime_helpers_v1_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}_{uuid.uuid4().hex[:8]}.json")
    auth = PrivacyCore().authorize_file_write(str(target))
    if auth.get("allowed") is not True:
        raise PermissionError(f"PrivacyCore denied candidate receipt: {auth}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"receipt": str(target), "by_language": by_language,
                      "live_restored": restored.get("active_adapter"), "promoted": False}, indent=2), flush=True)
    return target


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("suite", type=Path, default=SUITE, nargs="?")
    parser.add_argument("--candidate", type=Path, default=base.DEFAULT_CANDIDATE)
    args = parser.parse_args()
    run_suite(args.suite, args.candidate)
