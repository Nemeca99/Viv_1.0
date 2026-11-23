"""Audit and Purge Engine for Wikipedia Emergent Shapes Database.

Runs DualParserVerifier across all PENDING shapes in wikipedia_emergent_shapes.db:
1. Cross-checks Parser 1 extractions against Parser 2 curated [[Category:...]] tags and short descriptions.
2. Identifies and marks false positives as REJECTED with full forensic reason.
3. Promotes double-checked pure shapes to VERIFIED.
4. Leaves HELD_OUT and CERTIFIED records untouched.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import sys
import time

WORKSPACE = Path(r"L:\LocalCoder\workspace")
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from autonomy.dual_parser_verifier import DualParserVerifier

DB_PATH = WORKSPACE / "autonomy/data/wikipedia_emergent_shapes.db"
DATASET_ROOT = Path(r"F:\AI_Datasets\wikipedia_deduplicated")


def audit_database(limit: int = 0, dry_run: bool = False):
    print("=" * 72)
    print("NOX FORGE · DUAL-PARSER EPISTEMIC DATABASE AUDITOR")
    print(f"Target Database: {DB_PATH}")
    print(f"Dataset Root:    {DATASET_ROOT}")
    print(f"Dry Run:         {dry_run}")
    print("=" * 72, flush=True)

    if not DB_PATH.is_file():
        print(f"Error: Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    query = """
        SELECT id, entity, category, provenance_batch, provenance_file, short_desc, source_title
        FROM emergent_shapes
        WHERE status = 'PENDING'
        ORDER BY id ASC
    """
    if limit > 0:
        query += f" LIMIT {limit}"

    rows = cur.execute(query).fetchall()
    total = len(rows)
    print(f"Found {total} PENDING shapes to audit.", flush=True)

    verified_count = 0
    rejected_count = 0
    missing_file_count = 0

    rejections_sample: list[tuple[str, str, str]] = []

    start_time = time.monotonic()

    for idx, r in enumerate(rows, 1):
        db_id, entity, category, p_batch, p_file, short_desc, title = r
        filepath = DATASET_ROOT / f"batch_{p_batch:04d}" / p_file

        if not filepath.is_file():
            missing_file_count += 1
            if not dry_run:
                cur.execute(
                    "UPDATE emergent_shapes SET status = 'REJECTED', rejection_reason = ? WHERE id = ?",
                    (f"Source file missing: {filepath.name}", db_id),
                )
            continue

        res = DualParserVerifier.verify_file(
            filepath,
            entity,
            category,
            short_desc=short_desc or "",
            title=title or "",
        )

        if res["verified"]:
            verified_count += 1
            if not dry_run:
                cur.execute(
                    "UPDATE emergent_shapes SET status = 'VERIFIED' WHERE id = ?",
                    (db_id,),
                )
        else:
            rejected_count += 1
            reason = res["reason"]
            if len(rejections_sample) < 25:
                rejections_sample.append((entity, category, reason))
            if not dry_run:
                cur.execute(
                    "UPDATE emergent_shapes SET status = 'REJECTED', rejection_reason = ? WHERE id = ?",
                    (reason, db_id),
                )

        if idx % 200 == 0 or idx == total:
            elapsed = time.monotonic() - start_time
            rate = idx / elapsed if elapsed > 0 else 0
            print(f"Progress: [{idx}/{total}] ({(idx/total)*100:.1f}%) | "
                  f"Verified: {verified_count} | Rejected: {rejected_count} | Rate: {rate:.1f} shapes/s",
                  flush=True)

    if not dry_run:
        conn.commit()

    conn.close()

    elapsed = time.monotonic() - start_time
    print("\n" + "=" * 72)
    print(f"AUDIT COMPLETE in {elapsed:.2f}s")
    print(f"Total Scanned:  {total}")
    print(f"Verified:       {verified_count} ({(verified_count/max(1, total))*100:.1f}%)")
    print(f"Rejected:       {rejected_count} ({(rejected_count/max(1, total))*100:.1f}%)")
    print(f"Missing Files:  {missing_file_count}")
    print("=" * 72)

    if rejections_sample:
        print("\n[SAMPLE INTERCEPTED REJECTIONS]")
        for ent, cat, rsn in rejections_sample:
            print(f"  • '{ent}' as '{cat}' -> REJECTED: {rsn}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Audit and clean emergent shapes DB")
    parser.add_argument("--limit", type=int, default=0, help="Max shapes to scan (0 = all)")
    parser.add_argument("--dry-run", action="store_true", help="Do not update database")
    args = parser.parse_args()
    audit_database(limit=args.limit, dry_run=args.dry_run)
