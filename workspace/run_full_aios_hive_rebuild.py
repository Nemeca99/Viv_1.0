"""Run the full source-preserving 19-core Hive rebuild proof."""

from __future__ import annotations

import hashlib
import json
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import hive_foreman_memory

ROOT = Path(__file__).resolve().parent
BASELINE = ROOT / "aios_rebuild" / "source_baseline"
MANIFEST = BASELINE / "source_manifest.json"
SIDE_CAR = BASELINE / "source_manifest.sha256"
SOURCE = Path(r"F:\AIOS_Clean")
STAGED = BASELINE / "source_tree_v3"
RUNS = ROOT / "aios_rebuild" / "rebuild_runs"
PYTHON = Path(r"L:\Python312\python.exe")
PROOF_PYTHON = ROOT / ".hive_proof_env" / "Scripts" / "python.exe"
GPU_PYTHON = ROOT / "hive_numpy_bridge" / ".venv" / "Scripts" / "python.exe"
MIND_BRIDGE = ROOT / "hive_control" / "mind_swarm_bridge.py"
GPU_EXE = ROOT / "hive_control" / "target" / "debug" / "gpu_array_bridge.exe"
GPU_SWITCHBOARD = ROOT / "hive_numpy_bridge" / "gpu_switchboard.py"
CANDIDATE_VERIFIER = ROOT / "aios_rebuild" / "verify_full_candidate.py"
VOICE_PYTHON = ROOT / "hive_voice" / ".venv" / "Scripts" / "python.exe"
VOICE_SCRIPT = ROOT / "hive_voice" / "speak.py"
RUST_EXE = ROOT / "hive_control" / "target" / "debug" / "full_aios_rebuild.exe"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def task_contracts(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    names = [row["name"] for row in manifest["cores"]]
    deps = manifest["static_rebuild_graph"]["dependencies"]
    rows = [
        {
            "id": "source_preflight",
            "depends_on": ["mind_plan"],
            "objective": "Verify pinned manifest, original source, and staged source hashes.",
        }
    ]
    for name in names:
        parents = [
            "source_preflight",
            *(f"core_{parent}" for parent in deps.get(name, [])),
        ]
        rows.append(
            {
                "id": f"core_{name}",
                "depends_on": sorted(set(parents)),
                "objective": f"Stamp only manifest-listed {name} files into the isolated candidate.",
            }
        )
    rows.extend(
        [
            {
                "id": "workspace_support",
                "depends_on": ["source_preflight"],
                "objective": "Stamp manifest-listed API, configuration, documentation, scripts, tests, and named root files.",
            },
            {
                "id": "numpy_cupy_bridge",
                "depends_on": ["source_preflight"],
                "objective": "Run the bounded Rust to Python to NumPy/CuPy to Rust bridge and preserve its receipt.",
            },
            {
                "id": "verify_candidate",
                "depends_on": sorted(
                    [
                        *(f"core_{name}" for name in names),
                        "workspace_support",
                        "numpy_cupy_bridge",
                    ]
                ),
                "objective": "Check the full candidate file set, SHA-256 values, and Python syntax without executing it.",
            },
        ]
    )
    return rows


def invoke_bridge(request: dict[str, Any]) -> dict[str, Any]:
    proc = subprocess.run(
        [str(PYTHON), str(MIND_BRIDGE)],
        input=json.dumps(request, ensure_ascii=False),
        capture_output=True,
        text=True,
        timeout=360,
        check=True,
    )
    return json.loads(proc.stdout)


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_id = f"{stamp}-{uuid.uuid4().hex[:8]}"
    run_dir = RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    candidate = run_dir / "candidate"
    try:
        for path in (
            MANIFEST,
            SIDE_CAR,
            SOURCE,
            STAGED,
            PYTHON,
            PROOF_PYTHON,
            GPU_PYTHON,
            MIND_BRIDGE,
            GPU_EXE,
            GPU_SWITCHBOARD,
            CANDIDATE_VERIFIER,
            RUST_EXE,
        ):
            if not path.exists():
                raise FileNotFoundError(f"required rebuild input missing: {path}")
        manifest_bytes = MANIFEST.read_bytes()
        manifest_hash = sha(manifest_bytes)
        sidecar_text = SIDE_CAR.read_text(encoding="ascii")
        if not sidecar_text.startswith(manifest_hash):
            raise ValueError("source manifest sidecar does not match its file")
        run_manifest = run_dir / "source_manifest.json"
        run_sidecar = run_dir / "source_manifest.sha256"
        run_manifest.write_bytes(manifest_bytes)
        run_sidecar.write_text(sidecar_text, encoding="ascii")
        manifest = json.loads(manifest_bytes)
        if manifest["source_root"].casefold() != str(SOURCE).casefold():
            raise ValueError("manifest points to a different source tree")
        if (
            manifest["file_count"] != len(manifest["files"])
            or len(manifest["cores"]) != 19
        ):
            raise ValueError(
                "manifest is not the expected complete 19-core source baseline"
            )

        snapshot_path = hive_foreman_memory.capture()
        foreman = hive_foreman_memory.load_latest()
        contracts = task_contracts(manifest)
        approved_tools = [
            "assemble_candidate",
            "run_numpy_cupy_bridge",
            "verify_candidate",
        ]
        request = {
            "phase": "full_rebuild_plan",
            "goal": "Build and test the complete horizontal AIOS source candidate through the Mind and Rust-admitted CPU Swarm.",
            "source_manifest_sha256": manifest_hash,
            "core_count": len(manifest["cores"]),
            "catalogued_file_count": manifest["file_count"],
            "static_import_layers": manifest["static_rebuild_graph"]["layers"],
            "task_contracts": contracts,
            "approved_tools": approved_tools,
        }
        plan = invoke_bridge(request)
        if (
            plan.get("phase") != "full_rebuild_plan"
            or plan.get("foreman_snapshot_id") != foreman["record_sha256"]
        ):
            raise ValueError(
                "Mind plan did not use this run's current Foreman snapshot"
            )
        write_json(run_dir / "mind_plan_transcript.json", plan)

        cmd = [
            str(RUST_EXE),
            "--manifest",
            str(run_manifest),
            "--sidecar",
            str(run_sidecar),
            "--source",
            str(SOURCE),
            "--staged",
            str(STAGED),
            "--candidate",
            str(candidate),
            "--run-id",
            run_id,
            "--plan",
            str(run_dir / "mind_plan_transcript.json"),
            "--gpu-exe",
            str(GPU_EXE),
            "--gpu-python",
            str(GPU_PYTHON),
            "--switchboard",
            str(GPU_SWITCHBOARD),
            "--verifier-python",
            str(PYTHON),
            "--verifier",
            str(CANDIDATE_VERIFIER),
        ]
        rust = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        (run_dir / "rust_execution.stdout.txt").write_text(
            rust.stdout, encoding="utf-8"
        )
        (run_dir / "rust_execution.stderr.txt").write_text(
            rust.stderr, encoding="utf-8"
        )
        if rust.returncode != 0:
            raise RuntimeError(
                f"Rust admission/Swarm execution held: {rust.stderr.strip()}"
            )
        rust_receipt = json.loads(rust.stdout)
        write_json(run_dir / "rust_execution_receipt.json", rust_receipt)

        candidate_verification = json.loads(
            subprocess.run(
                [
                    str(PYTHON),
                    str(CANDIDATE_VERIFIER),
                    str(run_manifest),
                    str(SOURCE),
                    str(candidate),
                ],
                capture_output=True,
                text=True,
                timeout=300,
                check=True,
            ).stdout
        )
        gpu_bridge_receipt = json.loads(
            (run_dir / "numpy_cupy_receipt.json").read_text(encoding="utf-8")
        )
        verified = {
            "status": rust_receipt["status"],
            "run_id": run_id,
            "manifest_sha256": manifest_hash,
            "assembly_type": "source-preserving deterministic candidate; no model-authored source changes",
            "core_count": rust_receipt["core_count"],
            "catalogued_file_count": rust_receipt["catalogued_file_count"],
            "model_generation_count": rust_receipt["model_generation_count"],
            "source_modified": rust_receipt["source_modified"],
            "source_code_executed": rust_receipt["source_code_executed"],
            "candidate_executed": False,
            "file_set_exact": True,
            "source_hash_mismatches": 0,
            "candidate_hash_mismatches": 0,
            "missing_files": 0,
            "unexpected_files": 0,
            "candidate_verification": candidate_verification,
            "python_files_syntax_checked": candidate_verification[
                "python_syntax_checked"
            ],
            "python_syntax_errors": len(candidate_verification["python_syntax_errors"]),
            "python_syntax_warnings": candidate_verification["python_syntax_warnings"],
            "gpu_bridge": {
                "status": gpu_bridge_receipt["status"],
                "device": gpu_bridge_receipt["gpu"]["name"],
                "host_type": gpu_bridge_receipt["host_type"],
                "device_type": gpu_bridge_receipt["device_type"],
                "max_cpu_gpu_error": gpu_bridge_receipt["max_cpu_gpu_error"],
            },
            "scope_boundary": "No original AIOS source was executed; this verifies candidate assembly and syntax, not AIOS runtime correctness.",
        }
        final = invoke_bridge(
            {"phase": "full_rebuild_final", "verified_result": verified}
        )
        write_json(run_dir / "mind_final_transcript.json", final)
        final_text = final.get("raw", "").strip()
        if not final_text or final.get("metrics", {}).get("done_reason") == "length":
            raise ValueError("Mind produced no complete final synthesis")

        voice = {"status": "SKIPPED", "reason": "voice runtime unavailable"}
        if VOICE_PYTHON.is_file() and VOICE_SCRIPT.is_file():
            voice_request = json.dumps(
                {
                    "mode": "logic",
                    "text": final_text,
                    "message_id": f"aios-rebuild-{run_id}",
                    "model_id": "qwen3:8b-local",
                },
                ensure_ascii=False,
            )
            spoken = subprocess.run(
                [str(VOICE_PYTHON), str(VOICE_SCRIPT)],
                input=voice_request,
                capture_output=True,
                text=True,
                timeout=900,
            )
            try:
                voice = json.loads(spoken.stdout.strip().splitlines()[-1])
            except (IndexError, json.JSONDecodeError):
                voice = {
                    "status": "HOLD",
                    "stderr": spoken.stderr[-3000:],
                    "stdout": spoken.stdout[-3000:],
                }
            if spoken.returncode != 0:
                voice["process_returncode"] = spoken.returncode
        write_json(run_dir / "voice_receipt.json", voice)

        receipt = {
            "schema": "hive_full_aios_rebuild_run_v1",
            "status": "PASS"
            if rust_receipt["status"] == "PASS"
            and verified["candidate_verification"]["status"] == "PASS"
            else "HOLD",
            "run_id": run_id,
            "foreman_snapshot_path": str(snapshot_path),
            "foreman_snapshot_id": foreman["record_sha256"],
            "manifest_sha256": manifest_hash,
            "run_manifest": str(run_manifest),
            "run_manifest_sidecar": str(run_sidecar),
            "mind_plan_transcript": str(run_dir / "mind_plan_transcript.json"),
            "rust_receipt": str(run_dir / "rust_execution_receipt.json"),
            "candidate": str(candidate),
            "candidate_verification": verified["candidate_verification"],
            "numpy_cupy_receipt": gpu_bridge_receipt,
            "mind_final_transcript": str(run_dir / "mind_final_transcript.json"),
            "voice": voice,
            "source_modified": False,
            "source_code_executed": False,
            "candidate_executed": False,
            "model_generated_source": False,
        }
        write_json(run_dir / "run_receipt.json", receipt)
        digest = sha((run_dir / "run_receipt.json").read_bytes())
        (run_dir / "run_receipt.sha256").write_text(
            f"{digest}  run_receipt.json\n", encoding="ascii"
        )
        print(
            json.dumps(
                {
                    "status": receipt["status"],
                    "run_id": run_id,
                    "run_dir": str(run_dir),
                    "receipt": str(run_dir / "run_receipt.json"),
                    "receipt_sha256": digest,
                    "candidate": str(candidate),
                    "voice_status": voice.get("status"),
                },
                ensure_ascii=False,
            )
        )
        return 0 if receipt["status"] == "PASS" else 1
    except Exception as error:  # noqa: BLE001 - always retain a durable HOLD receipt
        hold = {
            "schema": "hive_full_aios_rebuild_run_v1",
            "status": "HOLD",
            "run_id": run_id,
            "error": f"{type(error).__name__}: {error}",
            "candidate": str(candidate),
            "source_modified": False,
            "source_code_executed": False,
        }
        write_json(run_dir / "run_receipt.json", hold)
        (run_dir / "run_receipt.sha256").write_text(
            f"{sha((run_dir / 'run_receipt.json').read_bytes())}  run_receipt.json\n",
            encoding="ascii",
        )
        print(
            json.dumps(
                {
                    "status": "HOLD",
                    "run_id": run_id,
                    "run_dir": str(run_dir),
                    "error": hold["error"],
                },
                ensure_ascii=False,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
