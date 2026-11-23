"""Carry one Rust request through NumPy host arrays and CuPy GPU arrays."""

from __future__ import annotations

import json
import sys

from gpu_backend import run


def main() -> int:
    try:
        request = json.loads(sys.stdin.readline())
        response = run(request)
        print(json.dumps({"status": "RESULT", "data": response}), flush=True)
        return 0
    except (KeyError, TypeError, ValueError, RuntimeError) as exc:
        print(
            json.dumps({"status": "ERROR", "reason": f"{type(exc).__name__}: {exc}"}),
            flush=True,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
