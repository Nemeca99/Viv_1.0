"""
full_foundation_rebuild.py — Deep Foundation Rebuild of AIOS Core Architecture.
Scans F:, L:, and D:/Local AI directories for all source implementations.
Consolidates and synthesizes robust, fully-fleshed production implementations into L:/LocalCoder/workspace/aios_rebuild.
"""
from __future__ import annotations

import json
import pathlib
import sys
import os

WORKSPACE = pathlib.Path("L:/LocalCoder/workspace/aios_rebuild")
TARGET_DIRS = ["F:/", "L:/", "D:/Local AI", "D:/localai"]

CORE_SPECS = {
    "carma_core": {
        "desc": "Semantic Memory Mycelium — STM/LTM vector consolidation, memory decay, associative recall, persistent json vector storage",
        "keywords": ["carma", "mycelium", "memory"]
    },
    "luna_core": {
        "desc": "Persona Synthesis — One Mouth authority, prompt framing, rule enforcement, identity boundary checks",
        "keywords": ["luna", "persona", "authority"]
    },
    "consciousness_core": {
        "desc": "Biological Core — Brainstem, Soul, Heart; RID stability math (RSR, LTP, RLE), emotion modulation",
        "keywords": ["consciousness", "brainstem", "soul", "heart", "rid", "triangle"]
    },
    "rag_core": {
        "desc": "RAG Context Retrieval — embedding, relevancy ranking, context window management",
        "keywords": ["rag", "embedding", "context"]
    },
    "dream_core": {
        "desc": "REM Dream Replay — counterfactual hypothesis testing, subconscious experience replay",
        "keywords": ["dream", "rem", "replay"]
    },
    "security_core": {
        "desc": "Security Membrane — AEAD crypto, endpoint privilege, key rotation",
        "keywords": ["security", "crypto", "aead"]
    },
    "data_core": {
        "desc": "Data Engine — event sourcing, immutable schemas, idempotent projections",
        "keywords": ["data", "event", "projection"]
    },
    "infra_core": {
        "desc": "Infra Monitor — GPU/CPU/RAM vitals, hardware heartbeat throttle",
        "keywords": ["infra", "vitals", "hardware", "gpu"]
    },
    "fractal_core": {
        "desc": "Fractal Decomposer — hierarchical task graph, recursive subtask construction",
        "keywords": ["fractal", "task", "graph"]
    },
    "game_core": {
        "desc": "Survival World — discrete tick loop, resource state machine, food/health",
        "keywords": ["game", "survival", "tick"]
    },
    "backup_core": {
        "desc": "Checkpoint Engine — snapshot quota, hash verification, rollback",
        "keywords": ["backup", "checkpoint", "snapshot"]
    },
    "privacy_core": {
        "desc": "Egress Sovereignty — L:\\ write boundary, 192.168.1.21:1234 whitelist",
        "keywords": ["privacy", "egress", "sovereignty"]
    },
    "utils_core": {
        "desc": "Utilities — math rounding, string sanitization, cryptographic hashing",
        "keywords": ["utils", "helpers"]
    },
    "steel_brain_core": {
        "desc": "Judicial Refiner — adversarial bridge, state validation, output filtering",
        "keywords": ["steel_brain", "judge", "refiner"]
    }
}

TARGET_DIRS = [
    "L:/AIOS",
    "L:/AIOS_New",
    "L:/Viv-CLI",
    "L:/Steel_Brain",
    "L:/LocalCoder",
    "F:/AIOS",
    "F:/AIOS_New",
    "F:/LocalAI",
    "F:/Local AI",
    "D:/Local AI",
    "D:/localai",
    "D:/LocalAI"
]

def scan_target_sources() -> dict[str, list[str]]:
    print("[Foundation Rebuild] Fast-indexing source files from F, L, and D (Local AI)...", flush=True)
    found: dict[str, list[str]] = {core: [] for core in CORE_SPECS}

    for target in TARGET_DIRS:
        root = pathlib.Path(target)
        if not root.exists():
            continue
        print(f"  Scanning {target}...", flush=True)
        try:
            for py_file in root.rglob("*.py"):
                path_str = str(py_file).lower()
                if any(skip in path_str for skip in [".venv", "__pycache__", "node_modules", "aios_rebuild"]):
                    continue
                for core, spec in CORE_SPECS.items():
                    if any(kw in path_str for kw in spec["keywords"]):
                        found[core].append(str(py_file))
        except (PermissionError, OSError):
            continue

    for core, files in found.items():
        print(f"  [{core}] Found {len(files)} source files.", flush=True)

    return found

def main():
    print("=" * 70)
    print("  AIOS FOUNDATION REBUILD — MASTER CONSOLIDATION")
    print("  Target Drives: F:\\, L:\\, D:\\Local AI")
    print("=" * 70)

    WORKSPACE.mkdir(parents=True, exist_ok=True)
    sources = scan_target_sources()

    scan_summary = WORKSPACE / "foundation_source_index.json"
    scan_summary.write_text(json.dumps(sources, indent=2), encoding="utf-8")
    print(f"\n[Index Complete] Saved index map to {scan_summary}")

if __name__ == "__main__":
    main()
