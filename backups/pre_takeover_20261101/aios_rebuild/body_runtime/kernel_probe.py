from __future__ import annotations

import contextlib
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path


MAX_REQUEST_BYTES = 1_048_576
RUST_BODY = "/usr/local/bin/aios-body-runtime"


def _body_health() -> dict:
    workspace = Path(os.environ["AIOS_WORKSPACE_ROOT"])
    sys.path.insert(0, str(workspace))

    with contextlib.redirect_stdout(sys.stderr):
        kernel_module = importlib.import_module("main_core.main_core")
        kernel = getattr(kernel_module, "kernel", None)
        if kernel is None:
            kernel = kernel_module.UnifiedAIOSKernel()
        health = kernel.get_system_health()

    if not isinstance(health, dict) or not isinstance(health.get("cores"), dict):
        raise RuntimeError("body_kernel_health_report_invalid")
    return health


def _build_rust_request(request: object) -> dict:
    if not isinstance(request, dict):
        raise ValueError("body_request_invalid_shape")
    if not set(request).issubset({"body_resources", "candidate_run_id"}):
        raise ValueError("body_request_has_unknown_fields")
    resources = request.get("body_resources")
    if not isinstance(resources, dict):
        raise ValueError("body_resources_invalid_shape")
    candidate_run_id = request.get("candidate_run_id")
    if candidate_run_id is not None and not isinstance(candidate_run_id, str):
        raise ValueError("candidate_run_id_invalid_type")

    rust_request = {
        "expected_cores": [],
        "health": _body_health(),
        "body_resources": resources,
    }
    if candidate_run_id is not None:
        rust_request["candidate_run_id"] = candidate_run_id
    return rust_request


def main() -> int:
    try:
        request_bytes = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if len(request_bytes) > MAX_REQUEST_BYTES:
            raise ValueError("body_request_exceeds_1_mibibyte_limit")
        request = json.loads(request_bytes)
        rust_request = _build_rust_request(request)
        rust_input = json.dumps(
            rust_request,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        result = subprocess.run(
            [RUST_BODY],
            input=rust_input,
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
        if result.stderr:
            sys.stderr.write(result.stderr)
        if result.returncode != 0:
            return result.returncode
        sys.stdout.write(result.stdout)
        return 0
    except Exception as error:
        print(f"body_kernel_probe_failed:{type(error).__name__}:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
