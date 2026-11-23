"""Benchmark Suite: Comparing Viv's Sandbox Reconstructed AIOS Organs against Original Source Organs.

Evaluates:
- LOC and Byte Footprint (Token Density)
- AST Node Complexity and Tree Depth (Structural Elegance)
- Formal Assertion Density (Semantic Graduation Verification)
- Standalone Execution Timing in Sandbox Container
"""
from __future__ import annotations

import ast
import json
import subprocess
import time
from pathlib import Path

MY_AIOS_DIR = Path(r"E:\Viv_Sandbox\playground\my_aios")
AIOS_SOURCE_DIR = Path(r"E:\Viv_Sandbox\playground\aios_source")
PROPOSALS_DIR = Path(r"E:\Viv_Sandbox\playground\proposals")
CONTAINER = "viv-vm"


def analyze_ast(code: str) -> dict:
    try:
        tree = ast.parse(code)
    except Exception as e:
        return {"valid": False, "error": str(e), "nodes": 0, "asserts": 0, "classes": 0, "funcs": 0, "max_depth": 0}

    nodes = list(ast.walk(tree))
    asserts = [n for n in nodes if isinstance(n, ast.Assert)]
    classes = [n for n in nodes if isinstance(n, ast.ClassDef)]
    funcs = [n for n in nodes if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]

    # Compute max AST depth
    def get_depth(node: ast.AST, cur: int = 1) -> int:
        child_depths = [get_depth(c, cur + 1) for c in ast.iter_child_nodes(node)]
        return max(child_depths) if child_depths else cur

    return {
        "valid": True,
        "nodes": len(nodes),
        "asserts": len(asserts),
        "classes": len(classes),
        "funcs": len(funcs),
        "max_depth": get_depth(tree)
    }


def run_benchmark():
    print("=" * 80)
    print(" AIOS ORGAN BENCHMARK: Sandbox-Reconstructed Organs vs. Source Reference")
    print("=" * 80)

    my_files = sorted(list(MY_AIOS_DIR.glob("*.py")))
    if not my_files:
        print("[!] No reconstructed organs found in", MY_AIOS_DIR)
        return

    results = []
    for f in my_files:
        my_code = f.read_text(encoding="utf-8", errors="replace")
        my_ast = analyze_ast(my_code)

        matching_src = list(AIOS_SOURCE_DIR.rglob(f.name))
        src_file = matching_src[0] if matching_src else None
        src_code = src_file.read_text(encoding="utf-8", errors="replace") if src_file else ""
        src_ast = analyze_ast(src_code) if src_code else {}

        # Benchmark standalone execution in viv-vm
        t0 = time.time()
        res = subprocess.run(
            ["docker", "exec", "-i", "-w", "/work", CONTAINER, "python", "-"],
            input=my_code.encode("utf-8"),
            capture_output=True,
            timeout=15
        )
        duration_ms = round((time.time() - t0) * 1000, 2)
        exec_ok = res.returncode == 0

        # Check proposal status
        prop_file = PROPOSALS_DIR / f"proposal_{f.stem}.json"
        prop_status = "UNKNOWN"
        if prop_file.exists():
            try:
                p_data = json.loads(prop_file.read_text(encoding="utf-8"))
                prop_status = p_data.get("status", "PENDING_ARCHITECT_REVIEW")
            except Exception:
                pass

        results.append({
            "organ": f.name,
            "status": prop_status,
            "exec_ok": exec_ok,
            "duration_ms": duration_ms,
            "my_loc": len(my_code.splitlines()),
            "src_loc": len(src_code.splitlines()) if src_code else "N/A",
            "my_bytes": len(my_code.encode("utf-8")),
            "src_bytes": len(src_code.encode("utf-8")) if src_code else "N/A",
            "my_asserts": my_ast.get("asserts", 0),
            "src_asserts": src_ast.get("asserts", 0) if src_ast else "N/A",
            "my_nodes": my_ast.get("nodes", 0),
            "src_nodes": src_ast.get("nodes", 0) if src_ast else "N/A",
            "my_depth": my_ast.get("max_depth", 0),
            "src_depth": src_ast.get("max_depth", 0) if src_ast else "N/A",
        })

    # Render results table
    print(f"\n{'Organ':<26} | {'Exec':<5} | {'Time(ms)':<8} | {'My LOC':<7} | {'Src LOC':<7} | {'Asserts':<7} | {'AST Nodes':<10} | {'Status'}")
    print("-" * 105)
    for r in results:
        e_str = "PASS" if r["exec_ok"] else "FAIL"
        print(f"{r['organ']:<26} | {e_str:<5} | {r['duration_ms']:<8} | {r['my_loc']:<7} | {str(r['src_loc']):<7} | {r['my_asserts']:<7} | {r['my_nodes']:<10} | {r['status']}")

    print("\n" + "=" * 80)
    print(" Detailed Architectural Insights:")
    for r in results:
        print(f"\n[+] Organ: {r['organ']}")
        print(f"    - Execution in viv-vm: {'Exit Code 0 (Success)' if r['exec_ok'] else 'Failed Gate'}")
        print(f"    - Execution Latency: {r['duration_ms']} ms")
        print(f"    - Compression Ratio: Reconstructed is {r['my_loc']} lines vs Original {r['src_loc']} lines")
        print(f"    - Invariant Verification: {r['my_asserts']} formal assertions protecting silicon state")
        print(f"    - Structural Complexity: {r['my_nodes']} AST nodes across max depth of {r['my_depth']}")
    print("=" * 80)


if __name__ == "__main__":
    run_benchmark()
