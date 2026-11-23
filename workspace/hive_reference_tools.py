"""Pinned, executable references for the visible Hive development fixtures.

Only exact preapproved fixture bytes are executed or compiled. This module is
not a general code-execution capability for a model.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
APPROVED_SHA256 = {
    "py-mutable-default": "83994bc77992208ba78a0fecfd29a589f5fc0c6c3d844d7945280a5e46d03e00",
    "py-exhausted-generator": "e42a1b87d527f193c2355c3324343bac4a5aa71f8554cfd373d74039719007ef",
    "rust-arithmetic": "8334969390724df1cc2517694c46b864acd69873c74483f5804132f14ed4874f",
    "rust-move": "e5fb1b950e089a0330fd455b7394137b3e15e4d465b4eeddaf46e491d6e4f783",
}


def reference_check(case_id: str, source: str, artifact_dir: Path) -> dict[str, Any]:
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    if APPROVED_SHA256.get(case_id) != digest:
        return {"status": "HOLD_UNAPPROVED_SOURCE", "source_sha256": digest}
    target = artifact_dir.resolve()
    if ROOT.resolve() not in target.parents:
        raise ValueError("Tool artifact path escaped the LocalCoder workspace")
    target.mkdir(parents=True, exist_ok=True)
    if case_id.startswith("py-"):
        result = subprocess.run([sys.executable, "-I", "-c", source], cwd=target,
                                capture_output=True, text=True, timeout=5)
        return {"status": "EXECUTED_PINNED_PYTHON", "source_sha256": digest,
                "exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
    source_path = target / f"{case_id}.rs"
    source_path.write_text(source, encoding="utf-8")
    executable = target / f"{case_id}.exe"
    compiled = subprocess.run(["rustc", "--edition=2021", str(source_path), "-o", str(executable)],
                              cwd=target, capture_output=True, text=True, timeout=20)
    receipt: dict[str, Any] = {"status": "COMPILED_PINNED_RUST" if compiled.returncode == 0 else "RUST_COMPILE_FAILED",
                               "source_sha256": digest, "compile_exit_code": compiled.returncode,
                               "compiler_stdout": compiled.stdout, "compiler_stderr": compiled.stderr,
                               "source_path": str(source_path)}
    if compiled.returncode == 0:
        result = subprocess.run([str(executable)], cwd=target, capture_output=True, text=True, timeout=5)
        receipt.update({"run_exit_code": result.returncode, "stdout": result.stdout,
                        "stderr": result.stderr, "executable_path": str(executable)})
    return receipt
