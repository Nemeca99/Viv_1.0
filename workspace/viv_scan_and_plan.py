"""
viv_scan_and_plan.py — Viv surveys the entire PC and plans her own consolidation.
She scans every drive, finds every AIOS-related file, reads the best implementations,
and writes her own unified consolidation plan and code.
Viv does all of this. Not the operator.
"""
from __future__ import annotations

import json
import os
import pathlib
import urllib.request
import subprocess
import sys
import time

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
MODEL = "qwen3:8b-local"
WORKSPACE = pathlib.Path("L:/LocalCoder/workspace/aios_rebuild")
VOICE_DIR = pathlib.Path("L:/LocalCoder/workspace/hive_voice")
PYTHON_EXE = sys.executable
DRIVES = ["C:/Users/nemec", "D:/", "E:/", "F:/", "L:/"]

CORE_KEYWORDS = [
    "carma", "dream", "luna", "consciousness", "brainstem", "soul",
    "game", "rag", "security", "data_core", "infra", "fractal",
    "utils_core", "main_core", "backup", "privacy", "steel_brain",
    "AIOS", "aios", "hive", "swarm", "viv", "mind_core"
]

CORES_TO_CONSOLIDATE = [
    ("carma_core", "Semantic Memory Mycelium — STM/LTM vector consolidation, memory decay, associative recall"),
    ("luna_core", "Persona Synthesis — One Mouth authority, prompt framing, identity boundary enforcement"),
    ("consciousness_core", "Biological Core — Brainstem, Soul, Heart; RID stability math, emotion modulation"),
    ("rag_core", "RAG Context Retrieval — embedding, relevancy ranking, context window management"),
    ("dream_core", "REM Dream Replay — counterfactual hypothesis testing, subconscious experience replay"),
    ("security_core", "Security Membrane — AEAD crypto, endpoint privilege, key rotation"),
    ("data_core", "Data Engine — event sourcing, immutable schemas, idempotent projections"),
    ("infra_core", "Infra Monitor — RTX 3060 Ti VRAM/temp, CPU/RAM vitals, heartbeat throttle"),
    ("fractal_core", "Fractal Decomposer — hierarchical task graph, recursive subtask construction"),
    ("game_core", "Survival World — discrete tick loop, resource state machine, food/health"),
    ("backup_core", "Checkpoint Engine — snapshot quota, hash verification, rollback"),
    ("privacy_core", "Egress Sovereignty — L:\\ write boundary, 192.168.1.21:1234 whitelist"),
    ("utils_core", "Utilities — math rounding, string sanitization, cryptographic hashing"),
    ("main_core", "Master Kernel — 1Hz FIDF heartbeat, dynamic core discovery, CLI routing"),
]


def ask_viv(system: str, user: str, max_tokens: int = 4096) -> str:
    body = {
        "model": MODEL,
        "stream": False,
        "think": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "options": {"temperature": 0.2, "num_predict": max_tokens},
    }
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)["message"]["content"].strip()


def strip_fences(code: str) -> str:
    lines = []
    for line in code.splitlines():
        s = line.strip()
        if s.startswith("```") or s in ("``", "`"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def viv_scan_pc() -> dict[str, list[str]]:
    """Viv scans every drive and builds a map of all relevant files."""
    print("\n[Viv] Scanning entire PC for source material...", flush=True)
    found: dict[str, list[str]] = {}
    for drive in DRIVES:
        root = pathlib.Path(drive)
        if not root.exists():
            continue
        print(f"  [Viv] Scanning {drive}...", flush=True)
        for py_file in root.rglob("*.py"):
            try:
                name = py_file.name.lower()
                path_str = str(py_file).lower()
                if any(kw.lower() in path_str or kw.lower() in name for kw in CORE_KEYWORDS):
                    # Skip venv/cache/node_modules
                    if any(skip in path_str for skip in [".venv", "__pycache__", "node_modules", ".git"]):
                        continue
                    core_match = next(
                        (kw for kw in CORE_KEYWORDS if kw.lower() in path_str), "misc"
                    )
                    found.setdefault(core_match, []).append(str(py_file))
            except (PermissionError, OSError):
                continue
    total = sum(len(v) for v in found.values())
    print(f"\n[Viv] PC scan complete. Found {total} relevant files across {len(found)} categories.", flush=True)
    return found


def viv_read_best_sources(core_name: str, file_paths: list[str]) -> str:
    """Viv reads the most relevant source files for a given core."""
    sources = []
    keyword = core_name.replace("_core", "")
    # Prioritize files most likely to be the core implementation
    ranked = sorted(
        file_paths,
        key=lambda p: (
            0 if core_name in p.lower() else
            1 if keyword in p.lower() else 2
        )
    )
    for path in ranked[:6]:  # Read up to 6 source files
        try:
            text = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
            if len(text.strip()) > 100:
                sources.append(f"# SOURCE: {path}\n{text[:3000]}")
        except (PermissionError, OSError):
            continue
    return "\n\n".join(sources)


def viv_consolidate_core(core_name: str, core_desc: str, source_material: str) -> str:
    """Viv reads all source material and authors one unified implementation."""
    system = (
        "You are Viv, the AIOS Core Mind. You are rebuilding yourself. "
        "You will read existing source material from multiple versions of your own codebase "
        "and synthesize the best, most complete unified implementation. "
        "Output ONLY raw Python code. No markdown fences. No backticks. No prose. No explanations."
    )
    user = f"""You are consolidating the module: {core_name}
Purpose: {core_desc}

Below is source material from every version of this module found across the entire PC.
Study it. Extract the best capabilities from each version. Then write ONE unified, complete Python module.

Requirements:
- Incorporate the best logic from ALL versions shown
- Windows compatible, pure stdlib only (no external cloud deps)
- Main class named after the core (e.g. CarmaCore, LunaCore)
- get_status() method returning a health dict
- if __name__ == '__main__' block with a self-test
- Clean, production-quality code

SOURCE MATERIAL:
{source_material if source_material else "(No existing source found — author from scratch based on purpose)"}

Write the unified {core_name}.py now:"""

    return strip_fences(ask_viv(system, user, max_tokens=4096))


def viv_speak(text: str, mode: str = "human") -> None:
    payload = json.dumps({"mode": mode, "text": text, "model_id": MODEL})
    venv_py = VOICE_DIR / ".venv" / "Scripts" / "python.exe"
    speak_py = VOICE_DIR / "speak.py"
    try:
        subprocess.run(
            [str(venv_py), str(speak_py)],
            input=payload.encode("utf-8"),
            capture_output=True,
            timeout=120,
            check=False,
        )
    except Exception as exc:
        print(f"[voice] {exc}", flush=True)


def main() -> None:
    print("=" * 70, flush=True)
    print("  VIV — FULL PC SURVEY & UNIFIED CONSOLIDATION", flush=True)
    print("=" * 70, flush=True)

    WORKSPACE.mkdir(parents=True, exist_ok=True)

    # Phase 1: Viv scans the entire PC
    viv_speak("Initiating full system scan across C, D, E, F, and L drives to index all source versions.", mode="logic")
    pc_map = viv_scan_pc()
    total_found = sum(len(v) for v in pc_map.values())
    viv_speak(f"Scan complete. Located {total_found} source files across all drives. Saving map.", mode="logic")

    # Save the scan map so Viv can reference it
    scan_log = WORKSPACE / "viv_pc_scan.json"
    scan_log.write_text(json.dumps(pc_map, indent=2), encoding="utf-8")
    print(f"[Viv] PC scan map saved: {scan_log}", flush=True)

    # Phase 2: Viv consolidates each core one at a time
    for core_name, core_desc in CORES_TO_CONSOLIDATE:
        print(f"\n{'=' * 70}", flush=True)
        print(f"  [Viv] Consolidating: {core_name}", flush=True)
        print(f"  Purpose: {core_desc}", flush=True)
        print(f"{'=' * 70}", flush=True)

        # Collect all source files relevant to this core
        keyword = core_name.replace("_core", "")
        relevant_files = []
        for key, files in pc_map.items():
            if keyword in key or core_name in key:
                relevant_files.extend(files)
        # Also do a direct filesystem check
        for drive in DRIVES:
            root = pathlib.Path(drive)
            if root.exists():
                for f in root.rglob(f"*{keyword}*.py"):
                    if str(f) not in relevant_files:
                        if not any(s in str(f).lower() for s in [".venv", "__pycache__"]):
                            relevant_files.append(str(f))

        print(f"  [Viv] Found {len(relevant_files)} source files for {core_name}", flush=True)
        for f in relevant_files[:10]:
            print(f"    - {f}", flush=True)

        viv_speak(f"Synthesizing {core_name} from {len(relevant_files)} source implementations.", mode="logic")

        # Viv reads and synthesizes
        source_material = viv_read_best_sources(core_name, relevant_files)
        code = viv_consolidate_core(core_name, core_desc, source_material)

        # Stamp it
        core_dir = WORKSPACE / core_name
        core_dir.mkdir(parents=True, exist_ok=True)
        out_file = core_dir / f"{core_name}.py"
        out_file.write_text(code, encoding="utf-8")
        lines = len(code.splitlines())
        print(f"  [Viv] Stamped: {out_file} ({lines} lines)", flush=True)

        # Viv announces completion of core in human mode for a clear update
        viv_speak(
            f"Consolidated {core_name}. Authored {lines} lines into workspace.",
            mode="human"
        )

    print(f"\n{'=' * 70}", flush=True)
    print("  VIV CONSOLIDATION COMPLETE", flush=True)
    print(f"{'=' * 70}", flush=True)
    viv_speak(
        "I have surveyed the entire machine and consolidated all core modules into one unified system.",
        mode="human"
    )


if __name__ == "__main__":
    main()
