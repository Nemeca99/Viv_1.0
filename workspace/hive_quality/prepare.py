"""Stage and check one Python source file before task dispatch."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "hive_quality" / "runs"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def get_tool_python() -> str:
    candidate = ROOT / ".hive_proof_env/Scripts/python.exe"
    if candidate.is_file():
        return str(candidate)
    return sys.executable


def tool(*args: str) -> dict[str, object]:
    try:
        result = subprocess.run(
            [get_tool_python(), "-m", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"argv": list(args), "exit_code": 124, "stdout": "", "stderr": str(exc)}
    return {
        "argv": list(args),
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def prepare(source_arg: str) -> dict[str, object]:
    source = Path(source_arg).resolve(strict=True)
    source.relative_to(ROOT.resolve(strict=True))
    if not source.is_file() or source.suffix != ".py":
        raise ValueError("source must be one Python file inside LocalCoder")
    original = source.read_bytes()
    run = RUNS / f"{time.time_ns()}_{uuid4().hex[:8]}"
    run.mkdir(parents=True)
    staged = run / source.name
    shutil.copyfile(source, staged)

    formatting = tool("black", "--quiet", str(staged))
    prepared = staged.read_bytes()
    checks = {
        "format": formatting,
        "ruff": tool("ruff", "check", "--no-cache", str(staged)),
        "vulture": tool("vulture", "--min-confidence", "100", str(staged)),
    }
    try:
        compile(prepared, str(staged), "exec")
        checks["compile"] = {"exit_code": 0, "diagnostic": ""}
    except (SyntaxError, ValueError, TypeError) as exc:
        checks["compile"] = {"exit_code": 1, "diagnostic": str(exc)}

    diff = "".join(
        difflib.unified_diff(
            original.decode("utf-8", errors="replace").splitlines(keepends=True),
            prepared.decode("utf-8", errors="replace").splitlines(keepends=True),
            fromfile=str(source.relative_to(ROOT)),
            tofile=str(staged.relative_to(ROOT)),
        )
    )
    (run / "preparation.diff").write_text(diff, encoding="utf-8")
    receipt = {
        "status": (
            "PASS"
            if all(check["exit_code"] == 0 for check in checks.values())
            else "HOLD"
        ),
        "scope": "one task-scoped Python file; staged before dispatch",
        "source": str(source),
        "source_sha256": sha256(original),
        "prepared": str(staged),
        "prepared_sha256": sha256(prepared),
        "diff": str(run / "preparation.diff"),
        "checks": checks,
    }
    (run / "receipt.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    args = parser.parse_args()
    receipt = prepare(args.source)
    print(
        json.dumps(
            {
                key: receipt[key]
                for key in ("status", "source", "prepared", "prepared_sha256", "diff")
            }
        )
    )
    if receipt["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
