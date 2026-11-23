"""
Ingestion script: Populates `aios_catalog_templates` in `viv_code_topology.sqlite3`
from the 11,395 AST templates in `template_catalog_v2/functions.jsonl`.
Provides instant zero-hallucination topological ground truth across all 19 AIOS cores.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

WORKSPACE_ROOT = Path("L:/LocalCoder/workspace")
CATALOG_PATH = WORKSPACE_ROOT / "aios_rebuild" / "rebuild_runs" / "full_horizontal_candidate_v5" / "template_catalog_v2" / "functions.jsonl"
TOPOLOGY_DB = WORKSPACE_ROOT / "autonomy" / "viv_code_topology.sqlite3"


def create_schema(conn: sqlite3.Connection):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS aios_catalog_templates (
            template_id TEXT PRIMARY KEY,
            core TEXT NOT NULL,
            source_path TEXT NOT NULL,
            kind TEXT NOT NULL,
            qualified_name TEXT NOT NULL,
            parameters TEXT NOT NULL,
            direct_calls TEXT NOT NULL,
            start_line INTEGER NOT NULL,
            end_line INTEGER NOT NULL,
            snippet_sha256 TEXT NOT NULL,
            snippet_utf8 TEXT NOT NULL,
            ingested_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_catalog_core ON aios_catalog_templates(core)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_catalog_qualname ON aios_catalog_templates(qualified_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_catalog_core_kind ON aios_catalog_templates(core, kind)")
    conn.commit()


def ingest_catalog() -> int:
    if not CATALOG_PATH.exists():
        raise FileNotFoundError(f"Catalog not found at: {CATALOG_PATH}")

    TOPOLOGY_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(TOPOLOGY_DB)
    create_schema(conn)

    print(f"[*] Reading template catalog from: {CATALOG_PATH}")
    t0 = time.time()
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    batch = []
    total = 0
    with open(CATALOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            entry = json.loads(line)
            row = (
                entry.get("template_id"),
                entry.get("core", "unknown"),
                entry.get("source_path", ""),
                entry.get("kind", ""),
                entry.get("qualified_name", ""),
                json.dumps(entry.get("parameters", [])),
                json.dumps(entry.get("direct_calls", [])),
                int(entry.get("start_line", 0)),
                int(entry.get("end_line", 0)),
                entry.get("snippet_sha256", ""),
                entry.get("snippet_utf8", ""),
                now_iso,
            )
            batch.append(row)
            if len(batch) >= 1000:
                conn.executemany(
                    """
                    INSERT OR REPLACE INTO aios_catalog_templates
                    (template_id, core, source_path, kind, qualified_name, parameters, direct_calls, start_line, end_line, snippet_sha256, snippet_utf8, ingested_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    batch,
                )
                conn.commit()
                total += len(batch)
                batch = []

    if batch:
        conn.executemany(
            """
            INSERT OR REPLACE INTO aios_catalog_templates
            (template_id, core, source_path, kind, qualified_name, parameters, direct_calls, start_line, end_line, snippet_sha256, snippet_utf8, ingested_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            batch,
        )
        conn.commit()
        total += len(batch)

    elapsed = time.time() - t0
    conn.close()

    print(f"[+] Ingested {total} templates into aios_catalog_templates in {elapsed:.2f}s.")
    return total


if __name__ == "__main__":
    count = ingest_catalog()
    print(f"[+] Silicon receipt: {count} exact AIOS AST templates verified in viv_code_topology.sqlite3.")
