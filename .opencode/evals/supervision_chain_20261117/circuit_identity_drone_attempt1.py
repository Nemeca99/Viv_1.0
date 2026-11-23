"""Audit V2 candidate typed composition receipts with self-check."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
RECEIPT_ROOT = HERE / "learning" / "neural_runs" / "composition_receipts"
DB_PATH = (HERE.parent / "autonomy" / "learning" / "neural_runs" / "candidate_verified_functions.sqlite3")

SCHEMA_NAME = "viv_typed_composition_execution_v1"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def canonical_hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(encoded)


class ReceiptAuditError(Exception):
    pass


def audit_receipt(receipt_path: Path, db_path: Path) -> int:
    checks_passed = 0
    total_checks = 8

    try:
        # Check 1: Receipt schema is viv_typed_composition_execution_v1
        with receipt_path.open("r", encoding="utf-8") as stream:
            receipt = json.load(stream)
        if receipt.get("schema") != SCHEMA_NAME:
            print(f"FAIL: check1_schema_mismatch={receipt.get('schema')}", flush=True)
            return 1
        checks_passed += 1

        # Check 2: Recompute top-level receipt_sha256 after removing only receipt_sha256
        receipt_copy = dict(receipt)
        claimed_receipt = receipt_copy.pop("receipt_sha256", None)
        if claimed_receipt is None:
            print(f"FAIL: check2_missing_receipt_sha256", flush=True)
            return 1
        recomputed_hash = canonical_hash(receipt_copy)
        if recomputed_hash != claimed_receipt:
            print(f"FAIL: check2_recomputed_hash_mismatch={recomputed_hash}!=expected={claimed_receipt}", flush=True)
            return 1
        checks_passed += 1

        # Check 3: SHA-256 of database bytes equals candidate_store_sha256
        db_bytes = db_path.read_bytes()
        db_hash = sha256_bytes(db_bytes)
        if receipt.get("candidate_store_sha256") != db_hash:
            print(f"FAIL: check3_db_hash_mismatch={db_hash}!=expected={receipt.get('candidate_store_sha256')}", flush=True)
            return 1
        checks_passed += 1

        # Check 4: Read-only PRAGMA quick_check returns ok
        try:
            conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=15)
            quick_result = conn.execute("PRAGMA quick_check").fetchone()[0]
            conn.close()
            if quick_result != "ok":
                print(f"FAIL: check4_quick_check_failed={quick_result}", flush=True)
                return 1
        except sqlite3.Error as exc:
            print(f"FAIL: check4_sqlite_error={exc}", flush=True)
            return 1
        checks_passed += 1

        # Check 5: relay_count equals typed_relays length; exactly three distinct relay_key values exist
        typed_relays = receipt.get("typed_relays", [])
        if len(typed_relays) != receipt.get("relay_count"):
            print(f"FAIL: check5_relay_count_mismatch={receipt.get('relay_count')}!=len(typed_relays)={len(typed_relays)}", flush=True)
            return 1
        relay_keys = {r.get("relay_key") for r in typed_relays if isinstance(r, dict)}
        if len(relay_keys) != 3:
            print(f"FAIL: check5_relay_keys_count_mismatch={len(relay_keys)}!=expected=3", flush=True)
            return 1

        # Query database for relay rows and validate edges
        try:
            conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=15)
            conn.row_factory = sqlite3.Row
            db = conn
            rows = db.execute("""
                SELECT relay_key, provider_version_id, consumer_version_id,
                       provider_output_type, consumer_input_type, evidence_json, receipt_sha256
                FROM typed_function_relays_v1
                ORDER BY relay_key
            """).fetchall()
            conn.close()

            if len(rows) != 3:
                print(f"FAIL: check5_db_rows_count_mismatch={len(rows)}!=expected=3", flush=True)
                return 1

            # Validate each row's receipt_sha256, provider/consumer version IDs match typed_relays edge
            for i, raw_row in enumerate(rows):
                evidence = json.loads(raw_row["evidence_json"]) if raw_row["evidence_json"] else None
                if evidence is None:
                    print(f"FAIL: check5_evidence_missing={i}", flush=True)
                    return 1

                # Compare receipt_sha256 with typed relay edge
                typed_edge = typed_relays[i] if i < len(typed_relays) else None
                if typed_edge is None or evidence.get("receipt_sha256") != raw_row["receipt_sha256"]:
                    print(f"FAIL: check5_receipt_sha256_mismatch={i}", flush=True)
                    return 1

                # Compare provider/consumer version IDs and types with typed relay edge
                if (raw_row["provider_version_id"] != typed_edge.get("provider_version_id") or
                    raw_row["consumer_version_id"] != typed_edge.get("consumer_version_id") or
                    raw_row["provider_output_type"] != typed_edge.get("provider_output_type") or
                    raw_row["consumer_input_type"] != typed_edge.get("consumer_input_type")):
                    print(f"FAIL: check5_version_or_type_mismatch={i}", flush=True)
                    return 1

            # Compare each row's provider/consumer types to its receipt edge
            for i, raw_row in enumerate(rows):
                evidence = json.loads(raw_row["evidence_json"]) if raw_row["evidence_json"] else None
                typed_edge = typed_relays[i] if i < len(typed_relays) else None
                if (typed_edge is None or
                    evidence.get("provider_output_type") != raw_row["provider_output_type"] or
                    evidence.get("consumer_input_type") != raw_row["consumer_input_type"]):
                    print(f"FAIL: check5_provider_consumer_types_mismatch={i}", flush=True)
                    return 1

        except (sqlite3.Error, json.JSONDecodeError) as exc:
            print(f"FAIL: check5_sqlite_or_json_error={exc}", flush=True)
            return 1
        checks_passed += 1

        # Check 6: execution_order has two unique IDs, ends at entry_version_id, node_count is two, and node_gates version IDs equal execution_order
        execution_order = receipt.get("execution_order", [])
        if (not isinstance(execution_order, list) or
                any(type(vid) is not int for vid in execution_order)):
            print("FAIL: check6_execution_order_not_integer_list", flush=True)
            return 1
        if len(execution_order) != 2 or len(set(execution_order)) != 2:
            print(f"FAIL: check6_execution_order_mismatch={len(execution_order)}!=expected=2 unique IDs", flush=True)
            return 1

        entry_version_id = receipt.get("entry_version_id")
        if type(entry_version_id) is not int or execution_order[-1] != entry_version_id:
            print(f"FAIL: check6_entry_version_id_mismatch={execution_order[-1]}!=expected={entry_version_id}", flush=True)
            return 1

        node_count = receipt.get("node_count")
        if (type(node_count) is not int or node_count != 2 or
                node_count != len(execution_order) or type(receipt.get("relay_count")) is not int):
            print(f"FAIL: check6_node_count_mismatch={node_count}!=expected=2", flush=True)
            return 1

        # Verify node_gates: list of two dicts, each with int version_id, dict gate, status='ALLOW', string output
        node_gates = receipt.get("node_gates", [])
        if not isinstance(node_gates, list) or len(node_gates) != 2:
            print(f"FAIL: check6_node_gates_not_list_of_two={node_gates}", flush=True)
            return 1
        for ng in node_gates:
            if not isinstance(ng, dict):
                print(f"FAIL: check6_node_gate_not_dict={ng}", flush=True)
                return 1
            if "version_id" not in ng or type(ng["version_id"]) is not int:
                print(f"FAIL: check6_node_missing_int_version_id={ng}", flush=True)
                return 1
            if "gate" not in ng or not isinstance(ng["gate"], dict):
                print(f"FAIL: check6_node_gate_not_dict={ng}", flush=True)
                return 1
            gate = ng["gate"]
            if gate.get("status") != "ALLOW":
                print(f"FAIL: check6_gate_status_not_ALLOW={gate}", flush=True)
                return 1
            if not isinstance(gate.get("output"), str):
                print(f"FAIL: check6_gate_output_not_string={gate}", flush=True)
                return 1
        version_ids = [ng["version_id"] for ng in node_gates]
        if version_ids != execution_order:
            print(f"FAIL: check6_node_gates_version_ids_mismatch={version_ids}!=expected={execution_order}", flush=True)
            return 1

        checks_passed += 1

        # Check 8: Database and dependency binding
        import sqlite3
        try:
            conn = sqlite3.connect(db_path, uri=True, mode=sqlite3.RO)
            cur = conn.cursor()
            placeholders = ','.join('?' for _ in execution_order)
            query = f'SELECT version_id, task_id, function_name, code_sha256, tests_sha256, gate_status FROM function_versions WHERE version_id IN ({placeholders})'
            rows_list = []
            for vid in execution_order:
                cur.execute(f'SELECT version_id, task_id, function_name, code_sha256, tests_sha256, gate_status FROM function_versions WHERE version_id = ?', (vid,))
                row_tuple = cur.fetchone()
                if row_tuple is not None:
                    rows_list.append(row_tuple)
            conn.close()
        except sqlite3.Error as e:
            print(f"FAIL: check8_db_connection_error={e}", flush=True)
            return 1

        # Join function_versions v to functions f USING(function_key); select v.version_id,v.task_id,f.function_name,v.code_sha256,v.tests_sha256,v.gate_status,f.language
        try:
            conn = sqlite3.connect(db_path, uri=True)
            cur = conn.cursor()
            join_query = 'SELECT fv.version_id, fv.task_id, f.function_name, fv.code_sha256, fv.tests_sha256, fv.gate_status, f.language FROM function_versions fv JOIN functions f ON fv.function_key = f.key ORDER BY fv.version_id'
            cur.execute(join_query)
            joined_rows = cur.fetchall()
            conn.close()
        except sqlite3.Error as e:
            print(f"FAIL: check8_db_join_error={e}", flush=True)
            return 1

        # Verify each node's task_id, function_name, code_sha256, tests_sha256 against its database row
        for i, (vid, ng) in enumerate(zip(execution_order, [node_gates[j] for j in range(len(node_gates))])):
            if vid >= len(rows_list):
                print(f"FAIL: check8_node_missing_db_row={vid}", flush=True)
                return 1
            expected = rows_list[vid]
            ng_data = (ng.get("version_id"), ng.get("task_id"), ng.get("function_name"), ng.get("code_sha256"), ng.get("tests_sha256"))
            if list(expected[:5]) != list(ng_data):
                print(f"FAIL: check8_node_mismatch={vid}: expected={expected[:5]}, got={list(ng_data)}", flush=True)
                return 1
        
        # Require gate_status='ALLOW', language='python' for each node
        try:
            conn = sqlite3.connect(db_path, uri=True)
            cur = conn.cursor()
            gate_query = 'SELECT fv.version_id, fv.gate_status, f.language FROM function_versions fv JOIN functions f ON fv.function_key = f.key WHERE fv.version_id IN (' + ','.join('?' for _ in execution_order) + ')'
            cur.execute(gate_query, execution_order)
            gate_rows = cur.fetchall()
            conn.close()
        except sqlite3.Error as e:
            print(f"FAIL: check8_db_gate_language_error={e}", flush=True)
            return 1

        for i, (vid, row) in enumerate(zip(execution_order, gate_rows)):
            if row[1] != 'ALLOW' or row[2] != 'python':
                print(f"FAIL: check8_node_gate_language_mismatch={vid}: got={row}", flush=True)
                return 1

        # Require an actual int node relay_count equal to number of existing rows whose consumer_version_id is that node
        try:
            conn = sqlite3.connect(db_path, uri=True)
            cur = conn.cursor()
            count_query = 'SELECT fv.version_id, COUNT(DISTINCT dr.consumer_version_id) as cnt FROM dependency_rows dr JOIN function_versions fv ON dr.function_key = fv.function_key WHERE fv.version_id IN (' + ','.join('?' for _ in execution_order) + ') GROUP BY fv.version_id'
            cur.execute(count_query)
            count_rows = {row[0]: row[1] for row in cur.fetchall()}
            conn.close()
        except sqlite3.Error as e:
            print(f"FAIL: check8_db_count_error={e}", flush=True)
            return 1

        for vid in execution_order:
            expected_cnt = count_rows.get(vid, 0)
            actual_relay_count = ng["relay_count"]
            if not isinstance(actual_relay_count, int) or actual_relay_count != expected_cnt:
                print(f"FAIL: check8_node_relay_count_mismatch={vid}: expected={expected_cnt}, got={actual_relay_count}", flush=True)
                return 1

        # Require set(execution_order) equals all provider/consumer IDs from rows; every provider must precede its consumer
        try:
            conn = sqlite3.connect(db_path, uri=True)
            cur = conn.cursor()
            ids_query = 'SELECT DISTINCT dr.provider_version_id, dr.consumer_version_id FROM dependency_rows dr JOIN function_versions fv ON dr.function_key = fv.function_key WHERE fv.version_id IN (' + ','.join('?' for _ in execution_order) + ')'
            cur.execute(ids_query)
            id_pairs = set((row[0], row[1]) for row in cur.fetchall())
            conn.close()
        except sqlite3.Error as e:
            print(f"FAIL: check8_db_ids_error={e}", flush=True)
            return 1

        provider_set = set()
        consumer_set = set()
        for p, c in id_pairs:
            if p not in execution_order or c not in execution_order:
                print(f"FAIL: check8_node_id_outside_execution={p,c}", flush=True)
                return 1
            provider_set.add(p)
            consumer_set.add(c)
        
        for vid in execution_order:
            if vid not in provider_set and vid not in consumer_set:
                print(f"FAIL: check8_node_isolated={vid}", flush=True)
                return 1

        # Require receipt.entry_function equals the last verified node function_name
        if receipt.get("entry_function") != joined_rows[-1][2] if joined_rows else None:
            print(f"FAIL: check8_entry_function_mismatch", flush=True)
            return 1

        checks_passed += 1
                print(f"FAIL: check7_recomputed_edge_hash_mismatch={i}", flush=True)
                return 1

            # Recompute relay_key and bind database evidence
            payload = dict(edge_copy)  # already has no receipt_sha256
            claimed_key = payload.pop("relay_key", None)
            if claimed_key is None:
                print(f"FAIL: check7_relay_key_missing={i}", flush=True)
                return 1
            if canonical_hash(payload) != claimed_key:
                print(f"FAIL: check7_relay_key_mismatch={i}", flush=True)
                return 1
            # Find exactly one row with matching relay_key in rows list
            matching_rows = [row for row in rows if row["relay_key"] == claimed_key]
            if len(matching_rows) != 1:
                print(f"FAIL: check7_no_unique_relay_row={i}", flush=True)
                return 1
            db_evidence = json.loads(matching_rows[0]["evidence_json"])
            # Bind edge to database evidence by hash equality (no double-encode)
            if canonical_hash(db_evidence) != canonical_hash(typed_edge):
                print(f"FAIL: check7_edge_not_bound_to_database={i}", flush=True)
                return 1

        # Check that provider_output_type equals consumer_input_type for each edge and both equal the database row
        for i, raw_row in enumerate(rows):
            evidence = json.loads(raw_row["evidence_json"]) if raw_row["evidence_json"] else None
            typed_edge = typed_relays[i] if i < len(typed_relays) else None
            if (typed_edge is None or
                evidence.get("provider_output_type") != evidence.get("consumer_input_type")):
                print(f"FAIL: check7_provider_consumer_types_not_equal={i}", flush=True)
                return 1

        checks_passed += 1

        # Check 8: candidate_store_read_only is True; promoted, live_viv_modified, model_weights_changed are exactly False
        if receipt.get("candidate_store_read_only") is not True:
            print(f"FAIL: check8_candidate_store_not_read_only", flush=True)
            return 1
        if any(receipt.get(key) is not False for key in ("promoted", "live_viv_modified", "model_weights_changed")):
            print(f"FAIL: check8_state_flags_mismatch", flush=True)
            return 1
        checks_passed += 1

    except (json.JSONDecodeError, FileNotFoundError) as exc:
        print(f"FAIL: audit_error={exc}", flush=True)
        return 1

    if checks_passed != total_checks:
        return 1

    # All checks passed
    print("PASS: 8 checks", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit V2 candidate typed composition receipts.")
    parser.add_argument("--self-check", action="store_true", help="Run self-check on the latest receipt.")
    args = parser.parse_args()

    if not args.self_check:
        parser.error("--self-check is required")

    # Find the latest receipt file in RECEIPT_ROOT
    receipts = sorted(RECEIPT_ROOT.glob("typed_composition_execution_*.json"))
    if not receipts:
        print(f"FAIL: no_receipts_found_in={RECEIPT_ROOT}", flush=True)
        return 1

    latest_receipt = receipts[-1]
    result = audit_receipt(latest_receipt, DB_PATH)
    sys.exit(result)


if __name__ == "__main__":
    main()
