"""
Universal Autonomous Core Rebuilder for AIOS Viv.
Accepts any core name (e.g. privacy_core, utils_core, consciousness_core, carma_core).
Queries the 11,395-span AIOS catalog in viv_code_topology.sqlite3 for exact AST contracts,
generates a 3-step DAG, executes tests and code on silicon, and seals ancestral receipts.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

AUTONOMY_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = AUTONOMY_DIR.parent
REBUILD_ROOT = WORKSPACE_ROOT / "aios_rebuild"
TOPOLOGY_DB = AUTONOMY_DIR / "viv_code_topology.sqlite3"

sys.path.insert(0, str(AUTONOMY_DIR))
from dag_orchestrator import DAGOrchestrator
from topological_context_injector import TopologicalContextInjector


def extract_core_spec_from_catalog(core_name: str) -> str:
    """Extracts high-level class and method contracts for a core from the catalog."""
    if not TOPOLOGY_DB.exists():
        return f"Core module `{core_name}` with clean, zero-cloud implementation and comprehensive unit tests."

    conn = sqlite3.connect(TOPOLOGY_DB)
    try:
        rows = conn.execute(
            """
            SELECT kind, qualified_name, parameters
            FROM aios_catalog_templates
            WHERE core = ?
            ORDER BY CASE WHEN kind = 'class' THEN 0 ELSE 1 END ASC, start_line ASC
            LIMIT 15
            """,
            (core_name,),
        ).fetchall()

        if not rows:
            return f"Core module `{core_name}` with clean, zero-cloud implementation and comprehensive unit tests."

        classes = []
        functions = []
        for kind, qname, params_json in rows:
            params = json.loads(params_json) if params_json else []
            p_str = ", ".join(params)
            if kind == "class":
                classes.append(f"`{qname}`")
            elif "." in qname:
                functions.append(f"`{qname}({p_str})`")
            else:
                functions.append(f"`{qname}({p_str})`")

        if core_name == "privacy_core":
            functions.insert(0, "`PrivacyCore.authorize_file_write(self, file_path)`: validates path traversal, checks allowed_directories / blocked_extensions; returns dict with 'allowed' (bool) and 'reason' (str)")
            functions.insert(1, "`PrivacyCore.write_text(self, file_path, content, encoding='utf-8')`: authorizes write; writes content if allowed or raises PermissionError")

        spec_lines = [
            f"Autonomous implementation of `{core_name}` satisfying authentic AIOS baseline contracts.",
            f"Primary classes: {', '.join(classes) if classes else 'None declared'}.",
            "Required methods and function signatures:",
        ]
        for fn in functions[:10]:
            spec_lines.append(f"- {fn}")
        spec_lines.append("Zero external cloud dependencies. All standard library imports at top of file.")
        return "\n".join(spec_lines)
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="AIOS Viv Autonomous Core Rebuilder")
    parser.add_argument("core", nargs="?", default="privacy_core", help="Target core name (e.g. privacy_core, utils_core)")
    parser.add_argument("--retries", type=int, default=3, help="Max self-healing attempts")
    parser.add_argument("--language", default="python", help="Implementation language (python or rust)")
    args = parser.parse_args()

    core_name = args.core
    target_dir = REBUILD_ROOT / core_name

    print("==========================================================================")
    print(f"   AIOS VIV AUTONOMOUS CORE REBUILD: {core_name.upper()}")
    print("   Architect: Human Architect (Absolute Authority)")
    print("   Substrate: 100% Offline Local Model (omnicoder-2-9b)")
    print(f"   Target Territory: {target_dir}")
    print(f"   Retry Budget: {args.retries} Bounded Attempts")
    print("==========================================================================")

    # 1. Initialize Topological Context Injector
    injector = TopologicalContextInjector()

    # 2. Extract Authentic Baseline Specification from Ingested Catalog
    core_desc = extract_core_spec_from_catalog(core_name)
    print(f"[*] Topological Specification for {core_name}:\n{core_desc}\n")

    # 3. Initialize DAG Orchestrator
    orchestrator = DAGOrchestrator(injector=injector)
    goal_id = f"GOAL_REBUILD_{core_name.upper()}_{int(time.time())}"

    # 4. Create 3-step DAG in SQLite
    tasks = orchestrator.create_goal_dag(
        goal_id=goal_id,
        core_name=core_name,
        core_description=core_desc,
        target_dir=target_dir,
        language=args.language,
    )
    print(f"[*] Created {len(tasks)} tasks in DAG for goal: {goal_id}")

    # 5. Execute Autonomous Goal
    t0 = time.time()
    success = orchestrator.run_autonomous_goal(goal_id=goal_id, language=args.language)
    elapsed = time.time() - t0

    print("\n==========================================================================")
    print(f"   {core_name.upper()} REBUILD RESULT: {'SUCCESS' if success else 'FAILED'}")
    print(f"   Total Elapsed Time: {elapsed:.2f} seconds")
    print("==========================================================================")

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
