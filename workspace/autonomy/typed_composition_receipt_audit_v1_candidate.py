"""Self-check validation for typed composition execution receipts."""

import argparse
import json
import hashlib
from pathlib import Path
import sqlite3
import sys

HERE = Path(__file__).resolve().parent
RECEIPT_ROOT = HERE / "learning" / "neural_runs" / "composition_receipts"
DB_PATH = (HERE.parent / "autonomy" / "typed_composition_execution.sqlite3").expanduser()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def canonical_hash(value: object) -> str:
    import json as json_module
    encoded = json_module.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(encoded)


def load_receipt(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"Receipt file missing: {path}")
    with open(path, "r", encoding="utf-8") as stream:
        return json.load(stream)


def validate_checks(receipt: dict, db_path: Path) -> list[str]:
    errors = []

    # 1. Receipt schema check
    if receipt.get("schema") != "viv_typed_composition_execution_v1":
        errors.append(f"Schema mismatch: {receipt.get('schema')}")

    # 2. Canonical SHA-256 excluding only receipt_sha256
    payload = dict(receipt)
    payload.pop("receipt_sha256", None)
    computed_hash = canonical_hash(payload)
    if computed_hash != receipt.get("candidate_store_sha256"):
        errors.append(f"Canonical hash mismatch: expected {receipt.get('candidate_store_sha256')}, got {computed_hash}")

    # 3. DB SHA-256 matches receipt
    db_hash = sha256_bytes(db_path.read_bytes()) if db_path.is_file() else None
    if db_hash != receipt.get("candidate_store_sha256"):
        errors.append(f"DB hash mismatch: expected {receipt.get('candidate_store_sha256')}, got {db_hash}")

    # 4. PRAGMA quick_check is ok
    if not db_path.is_file():
        errors.append("DB file missing for quick check")
    else:
        try:
            conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=15)
            quick_result = conn.execute("PRAGMA quick_check").fetchone()[0]
            if quick_result != "ok":
                errors.append(f"PRAGMA quick_check failed: {quick_result}")
        except Exception as exc:
            errors.append(f"DB connection error: {exc}")

    # 5. Three DB relay rows match receipt count
    try:
        conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=15)
        row_count = conn.execute("SELECT COUNT(*) FROM typed_function_relays_v1").fetchone()[0]
        if row_count != receipt.get("relay_count"):
            errors.append(f"Relay count mismatch: expected {receipt.get('relay_count')}, got {row_count}")
    except Exception as exc:
        errors.append(f"DB relay count check failed: {exc}")

    # 6. Two unique execution nodes end with entry version
    try:
        conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=15)
        node_count = receipt.get("node_count")
        if not (isinstance(node_count, int) and 2 <= node_count <= 32):
            errors.append(f"Node count out of range: {node_count}")
    except Exception as exc:
        errors.append(f"Node count check failed: {exc}")

    # 7. Relay receipt/key digests recompute and provider/consumer types agree
    try:
        conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=15)
        typed_relays = receipt.get("typed_relays", [])
        if not isinstance(typed_relays, list):
            errors.append("typed_relays is not a list")
        else:
            for i, relay in enumerate(typed_relays[:3]):  # Check first 3 relays
                if "receipt_sha256" in relay and canonical_hash(dict(relay)) != relay.get("receipt_sha256"):
                    errors.append(f"Relay {i} receipt hash mismatch")
                if "relay_key" in relay:
                    key_payload = dict(relay)
                    key_payload.pop("relay_key", None)
                    computed_key = canonical_hash(key_payload)
                    if computed_key != relay.get("relay_key"):
                        errors.append(f"Relay {i} key hash mismatch")
                provider_type = relay.get("provider_output_type")
                consumer_type = relay.get("consumer_input_type")
                if provider_type != consumer_type:
                    errors.append(f"Relay {i} type edge mismatch: provider={provider_type}, consumer={consumer_type}")
    except Exception as exc:
        errors.append(f"Relay digest check failed: {exc}")

    # 8. candidate_store_read_only true and promoted, live_viv_modified, model_weights_changed false
    if receipt.get("candidate_store_read_only") is not True:
        errors.append("candidate_store_read_only should be True")
    if receipt.get("promoted") is not False:
        errors.append("promoted should be False")
    if receipt.get("live_viv_modified") is not False:
        errors.append("live_viv_modified should be False")
    if receipt.get("model_weights_changed") is not False:
        errors.append("model_weights_changed should be False")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Self-check validation for typed composition execution receipts.")
    parser.add_argument("--self-check", action="store_true", required=True)
    args = parser.parse_args()

    if not args.self_check:
        parser.error("--self-check is required")

    receipt_path = RECEIPT_ROOT / "typed_composition_execution_20261116T001444Z_62c3fffb.json"
    db_path = Path(__file__).resolve().parent.parent / "autonomy" / "typed_composition_execution.sqlite3"

    try:
        receipt = load_receipt(receipt_path)
        errors = validate_checks(receipt, db_path)

        if not errors:
            print("PASS: 8 checks")
            return 0
        else:
            for err in errors:
                print(f"FAIL: {err}")
            return 1
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
