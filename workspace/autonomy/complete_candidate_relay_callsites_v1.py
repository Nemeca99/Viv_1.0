"""Append every source-observed helper callsite to a composed candidate route."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import candidate_compose_verified_helper_v1 as composition
import candidate_verified_function_store as store
from aios_rebuild.privacy_core.privacy_core import PrivacyCore

SOURCE_RECEIPT = HERE / "learning" / "neural_runs" / "composition_receipts" / (
    "compose_gregorian_leap_20261113T031835980905Z_daf2d675.json")
OUT_DIR = HERE / "learning" / "neural_runs" / "composition_receipts"


def main() -> None:
    run = json.loads(SOURCE_RECEIPT.read_text(encoding="utf-8"))
    admission = run["admission"]
    consumer = {"version_id": admission["version_id"],
                "function_key": admission["function_key"]}
    with store._connection() as db:
        provider_row = db.execute("""
            SELECT function_key,version_id,code,code_sha256 FROM function_versions
            WHERE version_id=? AND gate_status='ALLOW'
        """, (run["provider_function_version"],)).fetchone()
        consumer_row = db.execute("""
            SELECT function_key,version_id,code,code_sha256,gate_status
            FROM function_versions WHERE version_id=?
        """, (consumer["version_id"],)).fetchone()
        if provider_row is None or consumer_row is None or consumer_row[4] != "ALLOW":
            raise RuntimeError("COMPOSITION_VERSION_NOT_GATE_ADMITTED")
        provider = {"function_key": provider_row[0], "version_id": provider_row[1],
                    "code": provider_row[2], "code_sha256": provider_row[3]}
        if hashlib.sha256(provider["code"].encode()).hexdigest() != provider["code_sha256"]:
            raise RuntimeError("PROVIDER_CODE_HASH_MISMATCH")
        if hashlib.sha256(consumer_row[2].encode()).hexdigest() != consumer_row[3]:
            raise RuntimeError("CONSUMER_CODE_HASH_MISMATCH")
        active = db.execute("""
            SELECT version_id FROM active_versions WHERE function_key=?
        """, (consumer_row[0],)).fetchone()
    if active is None or active[0] != run["parent_function_version"]:
        raise RuntimeError("ACTIVE_FUNCTION_POINTER_CHANGED")

    sites = run["call_sites"]
    if len(sites) != 3:
        raise RuntimeError(f"EXPECTED_THREE_HELPER_CALLS:{len(sites)}")
    tests_hash = run["admission"]["tests_sha256"]
    relay_rows = [composition.record_relay(
        provider=provider, consumer=consumer, site=site,
        proposal_sha256=run["proposal_sha256"], tests_sha256=tests_hash)
        for site in sites]
    with store._connection() as db:
        persisted = db.execute("""
            SELECT relay_id,provider_version_id,consumer_version_id,
                   direction,provider_output_pin,consumer_input_pin,
                   callsite_json,callsite_sha256,receipt_sha256
            FROM function_relays WHERE consumer_version_id=? ORDER BY relay_id
        """, (consumer["version_id"],)).fetchall()
        if len(persisted) != len(sites):
            raise RuntimeError(f"RELAY_CALLSITE_COUNT_MISMATCH:{len(persisted)}")
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("CANDIDATE_STORE_QUICK_CHECK_FAILED")

    payload = {
        "schema": "viv_candidate_composition_relay_callsite_audit_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_composition_receipt": str(SOURCE_RECEIPT),
        "source_composition_receipt_sha256": hashlib.sha256(
            SOURCE_RECEIPT.read_bytes()).hexdigest(),
        "provider_function_version": provider["version_id"],
        "consumer_function_version": consumer["version_id"],
        "observed_callsite_count": len(sites),
        "relay_rows": [
            {"relay_id": row[0], "provider_version_id": row[1],
             "consumer_version_id": row[2], "direction": row[3],
             "provider_output_pin": row[4], "consumer_input_pin": row[5],
             "callsite": json.loads(row[6]), "callsite_sha256": row[7],
             "relay_receipt_sha256": row[8]}
            for row in persisted],
        "relay_insert_results": [
            {"relay_id": relay_id, "receipt_sha256": receipt_hash}
            for relay_id, receipt_hash in relay_rows],
        "active_function_version_unchanged": True,
        "candidate_store_quick_check": "ok",
        "promoted": False,
        "topology_write": False,
        "persistent_memory_write": False,
    }
    payload["receipt_sha256"] = store.canonical_hash(payload)
    target = OUT_DIR / "gregorian_leap_all_relay_callsites_v1.json"
    decision = PrivacyCore().authorize_file_write(str(target))
    if decision.get("allowed") is not True:
        raise PermissionError(f"PrivacyCore denied receipt path: {decision}")
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"state": "ALL_HELPER_CALLSITES_RECORDED",
                      "relay_ids": [row[0] for row in persisted],
                      "callsite_count": len(persisted),
                      "receipt": str(target),
                      "receipt_file_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                      "candidate_store_quick_check": "ok",
                      "active_function_version_unchanged": True,
                      "promoted": False}, indent=2), flush=True)


if __name__ == "__main__":
    main()
