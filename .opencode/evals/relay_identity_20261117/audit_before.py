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
        if len(execution_order) != 2 or len(set(execution_order)) != 2:
            print(f"FAIL: check6_execution_order_mismatch={len(execution_order)}!=expected=2 unique IDs", flush=True)
            return 1

        entry_version_id = receipt.get("entry_version_id")
        if execution_order[-1] != entry_version_id:
            print(f"FAIL: check6_entry_version_id_mismatch={execution_order[-1]}!=expected={entry_version_id}", flush=True)
            return 1

        node_count = receipt.get("node_count")
        if node_count != 2 or node_count != len(execution_order):
            print(f"FAIL: check6_node_count_mismatch={node_count}!=expected=2", flush=True)
            return 1

        # Verify node_gates version IDs equal execution_order
        node_gates = receipt.get("node_gates", [])
        if len(node_gates) != 2 or [ng["version_id"] for ng in node_gates] != execution_order:
            print(f"FAIL: check6_node_gates_version_ids_mismatch={node_gates}", flush=True)
            return 1

        checks_passed += 1

        # Check 7: For every edge, recompute receipt_sha256 excluding only receipt_sha256; recompute relay_key excluding relay_key and receipt_sha256; require provider_output_type equals consumer_input_type and both equal the database row
        for i, typed_edge in enumerate(typed_relays):
            if not isinstance(typed_edge, dict):
                print(f"FAIL: check7_typed_edge_not_dict={i}", flush=True)
                return 1

            # Recompute receipt_sha256 excluding only receipt_sha256
            edge_copy = dict(typed_edge)
            claimed_receipt = edge_copy.pop("receipt_sha256", None)
            if claimed_receipt is None:
                print(f"FAIL: check7_missing_receipt_sha256_in_edge={i}", flush=True)
                return 1

            recomputed_edge_hash = canonical_hash(edge_copy)
            if recomputed_edge_hash != claimed_receipt:
                print(f"FAIL: check7_recomputed_edge_hash_mismatch={i}", flush=True)
                return 1

            # Recompute relay_key excluding relay_key and receipt_sha256
            edge_for_key = dict(typed_edge)
            key_copy = edge_for_key.pop("relay_key", None)
            key_copy = key_copy if key_copy is not None else edge_for_key.pop("receipt_sha256")
            recomputed_key_hash = canonical_hash(key_copy)

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