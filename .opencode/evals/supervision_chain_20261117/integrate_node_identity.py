"""Copy Viv's reviewed pure comparator and add a read-only evidence adapter."""
import ast
import hashlib
from pathlib import Path

root = Path('L:/LocalCoder')
target = root / 'workspace/autonomy/typed_composition_receipt_audit_v2_candidate.py'
candidate = root / 'workspace/autonomy/composition_node_identity_candidate.py'
source = target.read_text(encoding='utf-8')
assert hashlib.sha256(target.read_bytes()).hexdigest() == '831a0c7b4d94ddd0f0bc03aa349d305c9f2be930a53b582f0abb1118689c432a'
helper = candidate.read_text(encoding='utf-8')
tree = ast.parse(helper)
functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
assert len(functions) == 1 and functions[0].name == 'validate_node_identity'
assert all(isinstance(node, ast.FunctionDef) or (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)) for node in tree.body)
helper = ast.get_source_segment(helper, functions[0])
source = source.replace('def audit_receipt(receipt_path: Path, db_path: Path) -> int:', helper + '\n\n\ndef audit_receipt(receipt_path: Path, db_path: Path) -> int:')
old = '        if len(execution_order) != 2 or len(set(execution_order)) != 2:'
new = '''        if (not isinstance(execution_order, list) or
                any(type(vid) is not int for vid in execution_order)):
            print("FAIL: check6_execution_order_not_integer_list", flush=True)
            return 1
        if len(execution_order) != 2 or len(set(execution_order)) != 2:'''
assert source.count(old) == 1
source = source.replace(old, new)
source = source.replace('        if execution_order[-1] != entry_version_id:', '        if type(entry_version_id) is not int or execution_order[-1] != entry_version_id:')
source = source.replace('        if node_count != 2 or node_count != len(execution_order):', '''        if (type(node_count) is not int or node_count != 2 or
                node_count != len(execution_order) or type(receipt.get("relay_count")) is not int):''')
anchor = '''        checks_passed += 1

        # Check 7: For every edge'''
adapter = '''        # Bind each claimed node to the recorded version, never receipt prose.
        try:
            identity_db = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=15)
            try:
                recorded_versions = identity_db.execute("""
                    SELECT v.version_id,v.task_id,f.function_name,v.code_sha256,
                           v.tests_sha256,v.gate_status,f.language
                    FROM function_versions v JOIN functions f USING(function_key)
                    WHERE v.version_id IN (?,?)
                """, tuple(execution_order)).fetchall()
            finally:
                identity_db.close()
        except sqlite3.Error as exc:
            print(f"FAIL: check6_identity_sqlite_error={exc}", flush=True)
            return 1
        identity_keys = ("version_id", "task_id", "function_name", "code_sha256",
                         "tests_sha256", "gate_status", "language")
        identities = {row[0]: dict(zip(identity_keys, row)) for row in recorded_versions}
        endpoint_ids = {row[key] for row in rows
                        for key in ("provider_version_id", "consumer_version_id")}
        if set(execution_order) != endpoint_ids:
            print("FAIL: check6_circuit_ids_not_relay_endpoints", flush=True)
            return 1
        positions = {vid: index for index, vid in enumerate(execution_order)}
        if any(positions[row["provider_version_id"]] >= positions[row["consumer_version_id"]]
               for row in rows):
            print("FAIL: check6_provider_not_before_consumer", flush=True)
            return 1
        for node in node_gates:
            expected_count = sum(row["consumer_version_id"] == node["version_id"] for row in rows)
            error = validate_node_identity(node, identities.get(node["version_id"]), expected_count)
            if error is not None:
                print(f"FAIL: check6_node_identity={error}", flush=True)
                return 1
        if receipt.get("entry_function") != node_gates[-1]["function_name"]:
            print("FAIL: check6_entry_function_mismatch", flush=True)
            return 1

        checks_passed += 1

        # Check 7: For every edge'''
assert source.count(anchor) == 1
source = source.replace(anchor, adapter)
ast.parse(source)
target.write_text(source, encoding='utf-8')
print('Integrated Viv comparator with Queen read-only SQL/type/dependency adapter')
