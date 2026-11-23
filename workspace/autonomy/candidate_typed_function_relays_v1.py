"""Build and execute a candidate-only typed relay from admitted Python functions.

The executor reads immutable active function versions, derives type evidence
from their ASTs, composes the exact provider and caller functions, and passes
the composition through the existing deterministic Python body gate. Optional
SQLite persistence adds rows to a new append-only candidate graph table; it
does not alter function versions, live Viv state, or promotion pointers.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import uuid

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
ROOT = WORKSPACE.parent
sys.path[:0] = [str(WORKSPACE), str(HERE)]

import candidate_verified_function_store as store
import viv_code_learning_loop as gates
from aios_rebuild.privacy_core.privacy_core import PrivacyCore

DB_PATH = store.DB_PATH
CURRICULUM_PATH = HERE / "python_edge_curriculum_test_10017.py"
RECEIPT_ROOT = HERE / "learning" / "neural_runs" / "composition_receipts"
GOAL_ID = "01a1d847-3b27-7533-bbc2-c718ace48ae7"
DEFAULT_PROVIDER_TASK = "py24_divisible_zero_safe"
DEFAULT_CONSUMER_TASK = "py24_gregorian_leap_rule"
TABLE = "typed_function_relays_v1"
SUPPORTED_TYPES = {"int", "bool", "str", "float", "bytes", "None"}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def canonical_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return sha256_bytes(payload)


def load_curriculum_task(task_id: str) -> dict:
    spec = importlib.util.spec_from_file_location(
        "candidate_typed_relay_curriculum", CURRICULUM_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("CURRICULUM_IMPORT_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows = module.CURRICULUM + module.EDGE_TRANSFER_CURRICULUM
    matches = [row for row in rows if row.get("id") == task_id]
    if len(matches) != 1:
        raise ValueError(f"CURRICULUM_TASK_NOT_UNIQUE:{task_id}")
    return matches[0]


def body_preflight() -> dict:
    command = [
        str(Path(sys.executable)), "-m",
        "aios_rebuild.main_core.mind_runtime_gate",
        "--goal-id", GOAL_ID,
    ]
    completed = subprocess.run(
        command, cwd=WORKSPACE, capture_output=True, text=True,
        encoding="utf-8", timeout=45,
    )
    if completed.returncode != 0:
        raise RuntimeError("RUST_BODY_PREFLIGHT_FAILED:" + completed.stderr[-1200:])
    try:
        result = json.loads(completed.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError("RUST_BODY_PREFLIGHT_RETURNED_INVALID_JSON") from exc
    if (result.get("allowed") is not True
            or result.get("authority") != "deterministic_aios_body_rust"
            or result.get("disposition") != "ALLOW_MIND_RUNTIME"):
        raise PermissionError("RUST_BODY_PREFLIGHT_DENIED:" + json.dumps(result))
    return result


def load_admitted_version(function_name: str, task: dict,
                          must_call: str | None = None) -> dict:
    uri = f"file:{DB_PATH.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute("""
            SELECT f.function_key,f.function_name,f.signature,f.specification,
                   v.version_id,v.task_id,v.source_kind,v.source_sha256,v.code,
                   v.code_sha256,v.tests_sha256,v.gate_name,v.gate_status,
                   v.gate_output,v.gate_receipt_sha256,v.admitted_utc,
                   CASE WHEN a.version_id IS NULL THEN 0 ELSE 1 END AS is_active
            FROM function_versions v
            JOIN functions f USING(function_key)
            LEFT JOIN active_versions a ON a.version_id=v.version_id
            WHERE f.language='python' AND f.function_name=?
              AND f.specification=? AND v.tests_sha256=?
              AND v.gate_status='ALLOW'
            ORDER BY v.version_id DESC
        """, (function_name, task["spec"], sha256_text(task["tests"]))).fetchall()
        quick = db.execute("PRAGMA quick_check").fetchone()[0]
    if quick != "ok":
        raise RuntimeError("CANDIDATE_STORE_QUICK_CHECK_FAILED")
    eligible = []
    for raw in rows:
        candidate = dict(raw)
        try:
            _, node = extract_function(candidate["code"], function_name)
        except (SyntaxError, ValueError):
            continue
        calls = {
            item.func.id for item in ast.walk(node)
            if isinstance(item, ast.Call) and isinstance(item.func, ast.Name)
        }
        if must_call is not None and must_call not in calls:
            continue
        eligible.append(candidate)
    if must_call is None:
        active = [row for row in eligible if row["is_active"]]
        eligible = active if active else eligible
    if len(eligible) != 1:
        qualifier = f":calling:{must_call}" if must_call else ""
        raise RuntimeError(
            f"ADMITTED_VERSION_NOT_UNIQUE:{function_name}{qualifier}:"
            f"{len(eligible)}"
        )
    row = eligible[0]
    if row["specification"] != task["spec"]:
        raise RuntimeError(f"CURRICULUM_SPEC_MISMATCH:{function_name}")
    if row["gate_status"] != "ALLOW":
        raise RuntimeError(f"FUNCTION_NOT_GATE_ADMITTED:{function_name}")
    if sha256_text(row["code"]) != row["code_sha256"]:
        raise RuntimeError(f"FUNCTION_CODE_HASH_MISMATCH:{function_name}")
    if sha256_text(task["tests"]) != row["tests_sha256"]:
        raise RuntimeError(f"FUNCTION_TEST_HASH_MISMATCH:{function_name}")
    gate_evidence = {
        "task_id": row["task_id"], "language": "python",
        "function_key": row["function_key"],
        "code_sha256": row["code_sha256"],
        "tests_sha256": row["tests_sha256"], "gate": row["gate_name"],
        "status": row["gate_status"], "output": row["gate_output"],
        "created_utc": row["admitted_utc"],
    }
    if canonical_hash(gate_evidence) != row["gate_receipt_sha256"]:
        raise RuntimeError(f"FUNCTION_GATE_RECEIPT_MISMATCH:{function_name}")
    return row


def extract_function(code: str, name: str) -> tuple[str, ast.FunctionDef]:
    tree = ast.parse(code)
    matches = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    ]
    if len(matches) != 1:
        raise ValueError(f"FUNCTION_DEFINITION_NOT_UNIQUE:{name}")
    segment = ast.get_source_segment(code, matches[0])
    if not segment:
        raise ValueError(f"FUNCTION_SOURCE_UNAVAILABLE:{name}")
    if isinstance(matches[0], ast.AsyncFunctionDef):
        raise ValueError(f"ASYNC_FUNCTION_UNSUPPORTED:{name}")
    return segment, matches[0]


def annotation(node: ast.AST | None, owner: str) -> str:
    if node is None:
        raise ValueError(f"UNANNOTATED_TYPE:{owner}")
    value = ast.unparse(node)
    if value not in SUPPORTED_TYPES:
        raise ValueError(f"UNSUPPORTED_TYPE_ANNOTATION:{owner}:{value}")
    return value


def positional_parameters(node: ast.FunctionDef) -> list[ast.arg]:
    if node.args.vararg or node.args.kwarg or node.args.kwonlyargs:
        raise ValueError(f"UNSUPPORTED_PARAMETER_SHAPE:{node.name}")
    return [*node.args.posonlyargs, *node.args.args]


def parse_contract_signature(signature: str) -> ast.FunctionDef:
    try:
        tree = ast.parse(signature + "\n    pass\n")
    except SyntaxError as exc:
        raise ValueError("ADMITTED_SIGNATURE_PARSE_FAILED") from exc
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        raise ValueError("ADMITTED_SIGNATURE_NOT_ONE_FUNCTION")
    return tree.body[0]


def infer_literal_type(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant):
        if node.value is None:
            return "None"
        return type(node.value).__name__
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        return infer_literal_type(node.operand)
    return None


def boolean_use(call: ast.Call, parents: dict[ast.AST, ast.AST],
                caller: ast.FunctionDef, caller_return_type: str) -> str:
    cursor: ast.AST = call
    while cursor in parents:
        parent = parents[cursor]
        if isinstance(parent, ast.UnaryOp) and isinstance(parent.op, ast.Not):
            return "boolean_negation:bool"
        if isinstance(parent, ast.BoolOp):
            return "boolean_operator:bool"
        if isinstance(parent, ast.If) and parent.test is cursor:
            return "if_test:bool"
        if isinstance(parent, ast.While) and parent.test is cursor:
            return "while_test:bool"
        if isinstance(parent, ast.Return) and parent.value is cursor:
            return "function_return:" + caller_return_type
        if isinstance(parent, (ast.Assign, ast.AnnAssign, ast.Expr)):
            break
        cursor = parent
    raise ValueError(f"UNSUPPORTED_CALL_RESULT_CONTEXT:{caller.name}:{call.lineno}")


def typed_calls(provider: dict, caller: dict, provider_code: str,
                caller_code: str, provider_node: ast.FunctionDef,
                caller_node: ast.FunctionDef) -> list[dict]:
    provider_contract = parse_contract_signature(provider["signature"])
    caller_contract = parse_contract_signature(caller["signature"])
    provider_parameters = positional_parameters(provider_contract)
    caller_parameters = positional_parameters(caller_contract)
    if ([item.arg for item in provider_parameters]
            != [item.arg for item in positional_parameters(provider_node)]):
        raise ValueError("PROVIDER_CODE_CONTRACT_PARAMETER_MISMATCH")
    if ([item.arg for item in caller_parameters]
            != [item.arg for item in positional_parameters(caller_node)]):
        raise ValueError("CALLER_CODE_CONTRACT_PARAMETER_MISMATCH")
    provider_types = [
        annotation(item.annotation, provider_contract.name + "." + item.arg)
        for item in provider_parameters
    ]
    caller_types = {
        item.arg: annotation(item.annotation, caller_contract.name + "." + item.arg)
        for item in caller_parameters
    }
    provider_return = annotation(
        provider_contract.returns, provider_contract.name + ".return"
    )
    caller_return = annotation(
        caller_contract.returns, caller_contract.name + ".return"
    )
    caller_tree = ast.parse(caller_code)
    function = next(
        node for node in caller_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == caller_node.name
    )
    parents = {child: parent for parent in ast.walk(function)
               for child in ast.iter_child_nodes(parent)}
    calls = [
        node for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == provider_node.name
    ]
    if not calls:
        raise ValueError("CALLER_DOES_NOT_USE_ADMITTED_PROVIDER")
    result = []
    for call in sorted(calls, key=lambda node: (node.lineno, node.col_offset)):
        if call.keywords or any(isinstance(arg, ast.Starred) for arg in call.args):
            raise ValueError(f"UNSUPPORTED_CALL_ARGUMENT_SHAPE:{call.lineno}")
        if len(call.args) != len(provider_parameters):
            raise ValueError(f"PROVIDER_ARITY_MISMATCH:{call.lineno}")
        actual_rows = []
        for index, (arg, param) in enumerate(zip(call.args, provider_parameters)):
            expected = provider_types[index]
            actual = caller_types.get(arg.id) if isinstance(arg, ast.Name) else infer_literal_type(arg)
            if actual is None:
                raise ValueError(
                    f"UNRESOLVED_ARGUMENT_TYPE:{caller_node.name}:{call.lineno}:"
                    f"{ast.unparse(arg)}"
                )
            if actual != expected:
                raise ValueError(
                    f"ARGUMENT_TYPE_MISMATCH:{call.lineno}:{param.arg}:{actual}!={expected}"
                )
            actual_rows.append({
                "provider_parameter": param.arg,
                "expression": ast.unparse(arg),
                "actual_type": actual,
                "required_type": expected,
                "compatible": True,
            })
        use = boolean_use(call, parents, function, caller_return)
        expected_return = use.rsplit(":", 1)[-1]
        if provider_return != expected_return:
            raise ValueError(
                f"RETURN_TYPE_MISMATCH:{call.lineno}:{provider_return}!={expected_return}"
            )
        callsite = {
            "line": call.lineno,
            "column": call.col_offset,
            "dependency_name": provider_node.name,
            "arguments": actual_rows,
            "provider_return_type": provider_return,
            "consumer_use": use,
            "consumer_return_type": caller_return,
            "ast_sha256": sha256_text(ast.dump(call, include_attributes=True)),
        }
        edge_evidence = {
            "schema": "viv_typed_function_relay_v1",
            "provider_version_id": provider["version_id"],
            "consumer_version_id": caller["version_id"],
            "provider_function_key": provider["function_key"],
            "consumer_function_key": caller["function_key"],
            "provider_function_name": provider["function_name"],
            "consumer_function_name": caller["function_name"],
            "direction": "PROVIDER_RETURN_TO_CALLER_TYPED_USE",
            "provider_output_type": provider_return,
            "consumer_input_type": expected_return,
            "provider_contract_sha256": sha256_text(provider["signature"]),
            "consumer_contract_sha256": sha256_text(caller["signature"]),
            "type_contract_source": "admitted_candidate_function_signature",
            "callsite": callsite,
            "provider_code_sha256": provider["code_sha256"],
            "consumer_code_sha256": caller["code_sha256"],
            "provider_tests_sha256": provider["tests_sha256"],
            "consumer_tests_sha256": caller["tests_sha256"],
            "provider_source_kind": provider["source_kind"],
            "consumer_source_kind": caller["source_kind"],
            "provider_source_sha256": provider["source_sha256"],
            "consumer_source_sha256": caller["source_sha256"],
        }
        edge_evidence["relay_key"] = canonical_hash(edge_evidence)
        edge_evidence["receipt_sha256"] = canonical_hash(edge_evidence)
        result.append(edge_evidence)
    return result


def write_candidate_graph(edges: list[dict]) -> dict:
    decision = PrivacyCore().authorize_file_write(str(DB_PATH))
    if decision.get("allowed") is not True:
        raise PermissionError("PRIVACYCORE_DENIED_CANDIDATE_GRAPH:" + json.dumps(decision))
    before_hash = sha256_bytes(DB_PATH.read_bytes())
    uri = f"file:{DB_PATH.as_posix()}?mode=rw"
    inserted = 0
    already_present = 0
    with sqlite3.connect(uri, uri=True, timeout=15) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("BEGIN IMMEDIATE")
        db.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE} (
                relay_key TEXT PRIMARY KEY,
                provider_version_id INTEGER NOT NULL REFERENCES function_versions(version_id),
                consumer_version_id INTEGER NOT NULL REFERENCES function_versions(version_id),
                provider_function_name TEXT NOT NULL,
                consumer_function_name TEXT NOT NULL,
                direction TEXT NOT NULL CHECK(direction='PROVIDER_RETURN_TO_CALLER_TYPED_USE'),
                provider_output_type TEXT NOT NULL,
                consumer_input_type TEXT NOT NULL,
                callsite_json TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                receipt_sha256 TEXT NOT NULL,
                created_utc TEXT NOT NULL
            )
        """)
        db.execute(f"""
            CREATE TRIGGER IF NOT EXISTS {TABLE}_no_update
            BEFORE UPDATE ON {TABLE}
            BEGIN SELECT RAISE(ABORT,'APPEND_ONLY_TYPED_RELAY'); END
        """)
        db.execute(f"""
            CREATE TRIGGER IF NOT EXISTS {TABLE}_no_delete
            BEFORE DELETE ON {TABLE}
            BEGIN SELECT RAISE(ABORT,'APPEND_ONLY_TYPED_RELAY'); END
        """)
        for edge in edges:
            existing = db.execute(
                f"SELECT receipt_sha256 FROM {TABLE} WHERE relay_key=?",
                (edge["relay_key"],),
            ).fetchone()
            if existing:
                if existing[0] != edge["receipt_sha256"]:
                    raise RuntimeError("PERSISTED_RELAY_HASH_CONFLICT")
                already_present += 1
                continue
            created = datetime.now(timezone.utc).isoformat()
            db.execute(f"""
                INSERT INTO {TABLE}(
                    relay_key,provider_version_id,consumer_version_id,
                    provider_function_name,consumer_function_name,direction,
                    provider_output_type,consumer_input_type,callsite_json,
                    evidence_json,receipt_sha256,created_utc
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                edge["relay_key"], edge["provider_version_id"],
                edge["consumer_version_id"], edge["provider_function_name"],
                edge["consumer_function_name"],
                "PROVIDER_RETURN_TO_CALLER_TYPED_USE",
                edge["provider_output_type"], edge["consumer_input_type"],
                json.dumps(edge["callsite"], ensure_ascii=False, sort_keys=True),
                json.dumps(edge, ensure_ascii=False, sort_keys=True),
                edge["receipt_sha256"], created,
            ))
            inserted += 1
        check = db.execute("PRAGMA quick_check").fetchone()[0]
        if check != "ok":
            raise RuntimeError("CANDIDATE_STORE_QUICK_CHECK_FAILED_AFTER_GRAPH_WRITE")
        db.commit()
    after_hash = sha256_bytes(DB_PATH.read_bytes())
    return {
        "table": TABLE, "inserted": inserted,
        "already_present": already_present,
        "quick_check": check, "database_sha256_before": before_hash,
        "database_sha256_after": after_hash,
    }


def run(provider_task_id: str, consumer_task_id: str,
        persist_candidate: bool) -> dict:
    body = body_preflight()
    provider_task = load_curriculum_task(provider_task_id)
    consumer_task = load_curriculum_task(consumer_task_id)
    provider_name = provider_task["spec"].split("(", 1)[0].removeprefix("def ")
    consumer_name = consumer_task["spec"].split("(", 1)[0].removeprefix("def ")
    provider = load_admitted_version(provider_name, provider_task)
    consumer = load_admitted_version(
        consumer_name, consumer_task, must_call=provider_name
    )
    provider_code, provider_node = extract_function(
        provider["code"], provider["function_name"]
    )
    consumer_code, consumer_node = extract_function(
        consumer["code"], consumer["function_name"]
    )
    edges = typed_calls(
        provider, consumer, provider_code, consumer_code, provider_node, consumer_node
    )
    composed_code = provider_code.rstrip() + "\n\n" + consumer_code.rstrip() + "\n"
    provider_ok, provider_output = gates.gate_python(
        provider_code, provider_task["tests"]
    )
    if not provider_ok:
        raise RuntimeError("ADMITTED_PROVIDER_GATE_FAILED:" + provider_output[:2000])
    composed_ok, composed_output = gates.gate_python(
        composed_code, consumer_task["tests"]
    )
    if not composed_ok:
        raise RuntimeError("TYPED_COMPOSITION_GATE_FAILED:" + composed_output[:2000])

    write_result = None
    if persist_candidate:
        body_preflight()
        write_result = write_candidate_graph(edges)

    receipt = {
        "schema": "viv_candidate_typed_function_composition_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "provider_task_id": provider_task_id,
        "consumer_task_id": consumer_task_id,
        "provider_version_id": provider["version_id"],
        "consumer_version_id": consumer["version_id"],
        "provider_source_kind": provider["source_kind"],
        "consumer_source_kind": consumer["source_kind"],
        "provider_code_sha256": provider["code_sha256"],
        "consumer_code_sha256": consumer["code_sha256"],
        "provider_tests_sha256": provider["tests_sha256"],
        "consumer_tests_sha256": consumer["tests_sha256"],
        "typed_relay_count": len(edges),
        "typed_relays": edges,
        "provider_gate": {"status": "ALLOW", "output": provider_output[-1000:]},
        "composition_gate": {"status": "ALLOW", "output": composed_output[-1000:]},
        "candidate_graph_write": write_result,
        "body_preflight": {
            "authority": body.get("authority"),
            "disposition": body.get("disposition"),
            "body_image": body.get("body_image"),
        },
        "live_viv_modified": False,
        "promoted": False,
        "model_weights_changed": False,
    }
    receipt["receipt_sha256"] = canonical_hash(receipt)
    if persist_candidate:
        body_preflight()
        decision = PrivacyCore().authorize_file_write(str(RECEIPT_ROOT))
        if decision.get("allowed") is not True:
            raise PermissionError("PRIVACYCORE_DENIED_RECEIPT_DIRECTORY:" + json.dumps(decision))
        RECEIPT_ROOT.mkdir(parents=True, exist_ok=True)
        target = RECEIPT_ROOT / (
            f"typed_function_composition_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_"
            f"{uuid.uuid4().hex[:8]}.json"
        )
        decision = PrivacyCore().authorize_file_write(str(target))
        if decision.get("allowed") is not True:
            raise PermissionError("PRIVACYCORE_DENIED_RECEIPT:" + json.dumps(decision))
        encoded = json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
        with target.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(encoded)
        receipt["receipt_path"] = str(target)
        receipt["receipt_file_sha256"] = sha256_bytes(target.read_bytes())
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--persist-candidate", action="store_true")
    parser.add_argument("--provider-task", default=DEFAULT_PROVIDER_TASK)
    parser.add_argument("--consumer-task", default=DEFAULT_CONSUMER_TASK)
    args = parser.parse_args()
    if not args.self_check:
        parser.error("--self-check is required")
    result = run(args.provider_task, args.consumer_task, args.persist_candidate)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
