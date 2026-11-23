"""Fixed-argument WSL Docker client for the deterministic Rust Body gate."""
from __future__ import annotations

import json
import math
import subprocess
import shutil
from pathlib import Path


BODY_IMAGE_PATH = Path(__file__).resolve().parents[1] / "body_runtime" / "image_id.txt"
try:
    BODY_IMAGE = BODY_IMAGE_PATH.read_text(encoding="utf-8").strip()
except FileNotFoundError:
    BODY_IMAGE = ""
WSL_DISTRIBUTION = "Ubuntu"
MAX_REQUEST_BYTES = 1_048_576
REQUEST_TIMEOUT_SECONDS = 10.0


def _hold(reason: str) -> dict:
    return {
        "schema": "aios_mind_runtime_gate_v1",
        "gate": "rust",
        "execution_boundary": "wsl_docker",
        "authority": "deterministic_aios_body_rust",
        "allowed": False,
        "disposition": "HOLD_MIND_RUNTIME",
        "reasons": [reason],
    }


def _command() -> list[str]:
    wsl = shutil.which("wsl.exe") or shutil.which("wsl") or "wsl.exe"
    return [
        wsl, "-d", WSL_DISTRIBUTION, "--", "docker", "run", "--rm", "--interactive",
        "--pull=never", "--network=none", "--read-only", "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true", "--user=10001:10001",
        "--memory=256m", "--memory-swap=256m", "--cpus=1", "--pids-limit=32",
        "--shm-size=8m",
        "--tmpfs=/tmp:rw,noexec,nosuid,size=32m,mode=1777",
        "--tmpfs=/opt/aios_rebuild/data_core/FractalCache:rw,noexec,nosuid,size=32m,mode=1777",
        "--tmpfs=/opt/aios_rebuild/data_core/log:rw,noexec,nosuid,size=8m,mode=1777",
        "--tmpfs=/opt/aios_rebuild/dream_core/state:rw,noexec,nosuid,size=16m,mode=1777",
        "--tmpfs=/opt/aios_rebuild/memory:rw,noexec,nosuid,size=16m,mode=1777",
        "--tmpfs=/opt/aios_rebuild/marketplace_core/config:rw,noexec,nosuid,size=8m,mode=1777",
        "--tmpfs=/opt/aios_rebuild/music_core/config:rw,noexec,nosuid,size=8m,mode=1777",
        "--tmpfs=/opt/aios_rebuild/music_core/music_library:rw,noexec,nosuid,size=8m,mode=1777",
        "--tmpfs=/opt/aios_rebuild/template_core/config:rw,noexec,nosuid,size=8m,mode=1777",
        "--env=AIOS_WORKSPACE_ROOT=/opt/aios_rebuild",
        "--env=AIOS_ROOT=/opt/aios_rebuild",
        "--env=AIOS_PYTHON_ENV_PATH=/usr/local/bin",
        "--env=AIOS_LOG_DIR=/tmp/aios/log",
        "--env=AIOS_DEBUG_DIR=/tmp/aios/debug",
        "--log-driver=none", BODY_IMAGE,
    ]


def _valid_request(request: object) -> bool:
    if not isinstance(request, dict):
        return False
    required = {"body_resources"}
    if not required.issubset(request) or not set(request).issubset(required | {"candidate_run_id"}):
        return False
    if "candidate_run_id" in request and not isinstance(request["candidate_run_id"], str):
        return False
    resources = request["body_resources"]
    if not isinstance(resources, dict) or not isinstance(resources.get("thermal_samples"), list):
        return False
    threads = resources.get("requested_threads")
    return isinstance(threads, int) and not isinstance(threads, bool)


def _valid_image_pin() -> bool:
    return (
        isinstance(BODY_IMAGE, str)
        and BODY_IMAGE.startswith("sha256:")
        and len(BODY_IMAGE) == 71
        and all(character in "0123456789abcdef" for character in BODY_IMAGE[7:])
    )


def _valid_verdict(verdict: dict) -> bool:
    required = {
        "allowed", "disposition", "authority", "reasons", "expected_core_count",
        "bound_core_count", "active_without_health_report", "stability_sn",
        "minimum_stability_sn", "requested_threads",
    }
    if set(verdict) != required:
        return False
    if not isinstance(verdict["allowed"], bool):
        return False
    if not isinstance(verdict["reasons"], list) or not all(
        isinstance(reason, str) for reason in verdict["reasons"]
    ):
        return False
    counts = (verdict["expected_core_count"], verdict["bound_core_count"])
    if not all(isinstance(count, int) and not isinstance(count, bool) and count >= 0
               for count in counts):
        return False
    unverified = verdict["active_without_health_report"]
    if not isinstance(unverified, list) or not all(isinstance(name, str) for name in unverified):
        return False
    minimum = verdict["minimum_stability_sn"]
    if not isinstance(minimum, (int, float)) or isinstance(minimum, bool):
        return False
    if not math.isfinite(float(minimum)):
        return False
    if float(minimum) != 0.45:
        return False
    stability = verdict["stability_sn"]
    if stability is not None and (
        not isinstance(stability, (int, float)) or isinstance(stability, bool)
        or not math.isfinite(float(stability))
    ):
        return False
    threads = verdict["requested_threads"]
    if threads is not None and (not isinstance(threads, int) or isinstance(threads, bool)):
        return False
    if verdict["allowed"]:
        return (
            verdict["disposition"] == "ALLOW_MIND_RUNTIME"
            and not verdict["reasons"]
            and not unverified
            and verdict["expected_core_count"] > 0
            and verdict["expected_core_count"] == verdict["bound_core_count"]
            and stability is not None
            and float(stability) >= float(minimum)
            and threads is not None
            and 1 <= threads <= 4
        )
    return verdict["disposition"] == "HOLD_MIND_RUNTIME"


def authorize(request: dict) -> dict:
    """Send one JSON request over stdin; never interpolate it into Docker arguments."""
    try:
        if not _valid_request(request):
            return _hold("body_request_schema_invalid")
        if not _valid_image_pin():
            return _hold("body_image_pin_unavailable_or_invalid")
        payload = json.dumps(request, ensure_ascii=True, separators=(",", ":"), sort_keys=True,
                             allow_nan=False)
        if len(payload.encode("utf-8")) > MAX_REQUEST_BYTES:
            return _hold("body_request_exceeds_1_mibibyte_limit")
        result = subprocess.run(
            _command(), input=payload, capture_output=True, text=True,
            timeout=REQUEST_TIMEOUT_SECONDS, check=False,
        )
    except subprocess.TimeoutExpired:
        return _hold("wsl_body_request_timed_out")
    except (OSError, TypeError, ValueError) as error:
        return _hold(f"wsl_body_request_failed:{type(error).__name__}")

    if result.returncode != 0:
        return _hold(f"wsl_body_nonzero_exit:{result.returncode}")
    if len(result.stdout.encode("utf-8")) > MAX_REQUEST_BYTES:
        return _hold("wsl_body_response_exceeds_1_mibibyte_limit")
    try:
        verdict = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        return _hold("wsl_body_response_invalid_json")
    if not isinstance(verdict, dict):
        return _hold("wsl_body_response_invalid_shape")
    if verdict.get("authority") != "deterministic_aios_body_rust":
        return _hold("wsl_body_response_authority_mismatch")
    if not _valid_verdict(verdict):
        return _hold("wsl_body_response_invalid_schema")
    verdict["schema"] = "aios_mind_runtime_gate_v1"
    verdict["gate"] = "rust"
    verdict["execution_boundary"] = "wsl_docker"
    verdict["body_image"] = BODY_IMAGE
    return verdict
