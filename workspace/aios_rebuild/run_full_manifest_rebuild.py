"""Run the manifest-wide candidate build through Mind, Rust, NumPy, and CuPy.

The source is the already verified, transformed 3,641-file v5 candidate. The
F: source and D: Viv runtime remain read-only. A fresh run keeps its manifest,
stage copy, model request/transcript, Rust receipts, verifier output, tests, and
hash sidecars together under rebuild_runs/full_manifest_rebuilds/.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

WORKSPACE = Path(__file__).resolve().parents[1]
AIOS = WORKSPACE / "aios_rebuild"
BASELINE = AIOS / "source_baseline_v4"
V5 = AIOS / "rebuild_runs" / "full_horizontal_candidate_v5"
SOURCE = V5 / "candidate"
TRANSFORM_RECEIPT = V5 / "streamlit_vendor_normalization_receipt.json"
VERIFICATION = V5 / "candidate_verification_fresh.json"
RUNS = AIOS / "rebuild_runs" / "full_manifest_rebuilds"
PYTHON = WORKSPACE / ".hive_proof_env" / "Scripts" / "python.exe"
HIVE = WORKSPACE / "hive_control"
BRIDGE = WORKSPACE / "hive_numpy_bridge"
BRIDGE_PYTHON = BRIDGE / ".venv" / "Scripts" / "python.exe"
BRIDGE_SOURCE = BRIDGE / "rust_frontend.rs"
BRIDGE_SWITCHBOARD = BRIDGE / "python_switchboard.py"
RUST_BINARY = HIVE / "target" / "debug" / "full_aios_rebuild.exe"
MIND_BRIDGE = HIVE / "mind_swarm_bridge.py"
VERIFIER = AIOS / "verify_full_candidate.py"
APPROVED_TOOLS = [
    "assemble_candidate",
    "run_numpy_cupy_bridge",
    "verify_candidate",
]


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha_file(path: Path) -> str:
    return sha(path.read_bytes())


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_new(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def write_json_new(path: Path, value: Any) -> str:
    raw = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        + b"\n"
    )
    write_new(path, raw)
    return sha(raw)


def safe_rel(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or "\\" in value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"unsafe manifest path: {value!r}")
    return path.as_posix()


def inventory(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        parent = Path(current)
        for name in dirnames:
            item = parent / name
            if item.is_symlink() or getattr(os.path, "isjunction", lambda _: False)(
                item
            ):
                raise ValueError(f"candidate crosses a reparse point: {item}")
        for name in filenames:
            item = parent / name
            if item.is_symlink() or not item.is_file():
                raise ValueError(f"candidate contains a non-regular file: {item}")
            relative = item.relative_to(root).as_posix()
            rows.append(
                {
                    "path": safe_rel(relative),
                    "sha256": sha_file(item),
                    "bytes": item.stat().st_size,
                }
            )
    rows.sort(key=lambda row: row["path"])
    return rows


def verify_upstream() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    source_manifest = read_json(BASELINE / "source_manifest.json")
    generated = read_json(V5 / "candidate_generation_receipt.json")
    verification = read_json(VERIFICATION)
    transform = read_json(TRANSFORM_RECEIPT)
    manifest_hash = sha_file(BASELINE / "source_manifest.json")
    if source_manifest.get("schema") != "aios_clean_source_baseline_v1":
        raise ValueError("source baseline schema changed")
    if generated.get("source_manifest_sha256") != manifest_hash:
        raise ValueError("v5 candidate is not bound to the full source manifest")
    if verification.get("source_manifest_sha256") != manifest_hash:
        raise ValueError("v5 verification is not bound to the full source manifest")
    if verification.get("transform_receipt_sha256") != transform.get("receipt_sha256"):
        raise ValueError("v5 transform receipt digest does not match verification")
    if (
        verification.get("status") != "PASS"
        or verification.get("catalogued_file_count") != 3641
        or verification.get("candidate_file_count") != 3641
        or verification.get("source_modified") is not False
        or verification.get("source_code_executed") is not False
        or verification.get("candidate_executed") is not False
    ):
        raise ValueError("full v5 candidate did not pass its source-derived gate")
    if generated.get("status") != "CANDIDATE_VALIDATED_SELF_REBUILD_NOT_PROVEN":
        raise ValueError("v5 candidate generation receipt changed")
    return source_manifest, verification, transform


def build_manifest(
    source_manifest: dict[str, Any],
    verification: dict[str, Any],
    transform: dict[str, Any],
) -> dict[str, Any]:
    expected_paths = {safe_rel(row["path"]) for row in source_manifest["files"]}
    files = inventory(SOURCE)
    found_paths = {row["path"] for row in files}
    if found_paths != expected_paths:
        raise ValueError(
            f"v5 candidate file set differs from baseline: "
            f"missing={len(expected_paths - found_paths)} extra={len(found_paths - expected_paths)}"
        )
    exclusion_rows = transform.get("compile_exclusions")
    if not isinstance(exclusion_rows, list) or len(exclusion_rows) != 6:
        raise ValueError("the v5 compile-exclusion list changed")
    for row in exclusion_rows:
        if row.get("path") not in found_paths or not row["path"].endswith(".py"):
            raise ValueError("v5 compile exclusion is outside the full manifest")
    return {
        "schema": "aios_clean_source_baseline_v1",
        "source_root": str(SOURCE),
        "file_count": len(files),
        "catalogued_bytes": sum(row["bytes"] for row in files),
        "files": files,
        "cores": source_manifest["cores"],
        "static_rebuild_graph": source_manifest["static_rebuild_graph"],
        "compile_exclusions": exclusion_rows,
        "lineage": {
            "baseline_manifest": str(BASELINE / "source_manifest.json"),
            "baseline_manifest_sha256": sha_file(BASELINE / "source_manifest.json"),
            "candidate_verification": str(VERIFICATION),
            "candidate_verification_sha256": sha_file(VERIFICATION),
            "candidate_transform_receipt": str(TRANSFORM_RECEIPT),
            "candidate_transform_receipt_sha256": sha_file(TRANSFORM_RECEIPT),
            "candidate_transform_receipt_declared_digest": transform["receipt_sha256"],
            "candidate_verification_status": verification["status"],
        },
    }


def core_for(path: str, core_names: list[str]) -> str | None:
    for core in core_names:
        if path.startswith(f"{core}/"):
            return core
    return None


def task_contracts(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    entries = manifest["files"]
    names = [row["name"] for row in manifest["cores"]]
    deps = manifest["static_rebuild_graph"]["dependencies"]
    counts: dict[str, tuple[int, int]] = {}
    for core in names:
        rows = [row for row in entries if core_for(row["path"], names) == core]
        counts[core] = (len(rows), sum(row["bytes"] for row in rows))
    workspace_rows = [row for row in entries if core_for(row["path"], names) is None]
    contracts: list[dict[str, Any]] = [
        {
            "id": "source_preflight",
            "required_depends_on": ["mind_plan"],
            "objective": "Verify the pinned full manifest, source candidate, and stage copy.",
            "scope_file_count": len(entries),
            "scope_bytes": sum(row["bytes"] for row in entries),
        }
    ]
    for core in names:
        providers = sorted(set(deps.get(core, [])))
        required = ["core_" + provider for provider in providers]
        required.append("source_preflight")
        count, size = counts[core]
        contracts.append(
            {
                "id": f"core_{core}",
                "required_depends_on": sorted(required),
                "objective": f"Stamp every manifest-listed {core} file into the candidate.",
                "scope_file_count": count,
                "scope_bytes": size,
            }
        )
    contracts.append(
        {
            "id": "workspace_support",
            "required_depends_on": ["source_preflight"],
            "objective": "Stamp all manifest-listed workspace support and root files.",
            "scope_file_count": len(workspace_rows),
            "scope_bytes": sum(row["bytes"] for row in workspace_rows),
        }
    )
    contracts.append(
        {
            "id": "numpy_cupy_bridge",
            "required_depends_on": ["source_preflight"],
            "objective": "Run and Rust-verify the NumPy/CuPy transfer bridge.",
            "scope_file_count": 0,
            "scope_bytes": 0,
        }
    )
    final_deps = ["core_" + core for core in names]
    final_deps.extend(["workspace_support", "numpy_cupy_bridge"])
    contracts.append(
        {
            "id": "verify_candidate",
            "required_depends_on": sorted(final_deps),
            "objective": "Verify every candidate path, file hash, and eligible Python syntax.",
            "scope_file_count": len(entries),
            "scope_bytes": sum(row["bytes"] for row in entries),
        }
    )
    return contracts


def run_process(
    command: list[str],
    *,
    cwd: Path,
    timeout: int = 600,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if command and Path(command[0]).name.casefold() == "cargo":
        env["RUSTFLAGS"] = "-D warnings"
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        input=input_text,
        capture_output=True,
        timeout=timeout,
        check=False,
        env=env,
    )


def main() -> int:
    RUNS.mkdir(parents=True, exist_ok=True)
    source_manifest, verification, transform = verify_upstream()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_id = f"full-horizontal-{stamp}-{uuid.uuid4().hex[:8]}"
    run_dir = RUNS / run_id
    run_dir.mkdir(parents=False, exist_ok=False)
    candidate = run_dir / "candidate"
    staged = run_dir / "staged_source"
    receipt: dict[str, Any] = {
        "schema": "hive_full_manifest_rebuild_run_v1",
        "run_id": run_id,
        "status": "IN_PROGRESS",
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "source_modified": False,
        "source_code_executed": False,
        "candidate_executed": False,
        "model_generated_source": False,
        "source_manifest_sha256": None,
        "foreman_snapshot_id": None,
        "mind_plan_sha256": None,
        "rust_receipt_sha256": None,
        "candidate_file_count": 0,
        "core_count": 0,
        "model_generation_count": 0,
        "swarm_generation_count": 0,
        "hold_reason": None,
    }
    write_json_new(run_dir / "run_started.json", receipt)
    try:
        manifest = build_manifest(source_manifest, verification, transform)
        manifest_hash = write_json_new(run_dir / "source_manifest.json", manifest)
        write_new(
            run_dir / "source_manifest.sha256",
            f"{manifest_hash}  source_manifest.json\n".encode("ascii"),
        )
        receipt["source_manifest_sha256"] = manifest_hash
        receipt["candidate_file_count"] = manifest["file_count"]
        receipt["core_count"] = len(manifest["cores"])

        print(
            f"BOUND source files={manifest['file_count']} cores={len(manifest['cores'])} "
            f"bytes={manifest['catalogued_bytes']} manifest_sha256={manifest_hash}",
            flush=True,
        )
        shutil.copytree(SOURCE, staged, copy_function=shutil.copy2)
        staged_inventory = inventory(staged)
        if staged_inventory != manifest["files"]:
            raise ValueError("staged source copy differs from its full manifest")
        stage_receipt = {
            "schema": "aios_full_manifest_stage_receipt_v1",
            "status": "PASS",
            "run_id": run_id,
            "manifest_sha256": manifest_hash,
            "file_count": len(staged_inventory),
            "staged_bytes": sum(row["bytes"] for row in staged_inventory),
            "staged_source": str(staged),
            "source_modified": False,
        }
        write_json_new(run_dir / "stage_receipt.json", stage_receipt)

        snapshot = run_process(
            [str(PYTHON), str(WORKSPACE / "hive_foreman_memory.py")],
            cwd=WORKSPACE,
            timeout=90,
        )
        if snapshot.returncode != 0:
            raise RuntimeError(f"Foreman capture failed: {snapshot.stderr[-4000:]}")
        snapshot_result = json.loads(snapshot.stdout)
        foreman_id = snapshot_result["snapshot_id"]
        receipt["foreman_snapshot_id"] = foreman_id
        receipt["foreman_snapshot_path"] = snapshot_result["path"]
        print(
            f"FOREMAN snapshot={foreman_id}; protected actions remain closed",
            flush=True,
        )

        contracts = task_contracts(manifest)
        plan_input = {
            "phase": "full_rebuild_plan",
            "goal": (
                "Reassemble and verify the entire normalized AIOS candidate from its "
                "hash-pinned full manifest, covering every core and workspace file."
            ),
            "source_manifest_sha256": manifest_hash,
            "core_count": len(manifest["cores"]),
            "catalogued_file_count": manifest["file_count"],
            "static_import_layers": manifest["static_rebuild_graph"]["layers"],
            "task_contracts": contracts,
            "approved_tools": APPROVED_TOOLS,
        }
        write_json_new(run_dir / "mind_plan_input.json", plan_input)
        mind = run_process(
            [str(PYTHON), str(MIND_BRIDGE)],
            cwd=HIVE,
            timeout=360,
            input_text=json.dumps(plan_input, ensure_ascii=False),
        )
        write_new(run_dir / "mind_bridge_stdout.txt", mind.stdout.encode("utf-8"))
        write_new(run_dir / "mind_bridge_stderr.txt", mind.stderr.encode("utf-8"))
        if mind.returncode != 0:
            raise RuntimeError(f"Mind planning failed: {mind.stderr[-4000:]}")
        mind_transcript = json.loads(mind.stdout)
        if mind_transcript.get("foreman_snapshot_id") != foreman_id:
            raise ValueError("Mind used a different Foreman snapshot than this run")
        write_json_new(run_dir / "mind_plan_transcript.json", mind_transcript)
        mind_hash = sha_file(run_dir / "mind_plan_transcript.json")
        receipt["mind_plan_sha256"] = mind_hash
        receipt["mind_plan_metrics"] = mind_transcript.get("metrics")
        receipt["model_generation_count"] = 1
        print(
            f"MIND plan captured; tokens={mind_transcript.get('metrics', {}).get('eval_count')} "
            f"reason={mind_transcript.get('metrics', {}).get('done_reason')}",
            flush=True,
        )

        rustfmt = run_process(["cargo", "fmt", "--check"], cwd=HIVE, timeout=120)
        if rustfmt.returncode != 0:
            raise RuntimeError(f"Rust format check failed: {rustfmt.stdout[-3000:]}")
        tests = run_process(
            ["cargo", "test", "--offline", "--bin", "full_aios_rebuild"],
            cwd=HIVE,
            timeout=300,
        )
        write_new(run_dir / "rust_tests.log", (tests.stdout + tests.stderr).encode())
        if tests.returncode != 0:
            raise RuntimeError(
                f"Rust plan/control tests failed: {tests.stderr[-4000:]}"
            )
        build = run_process(
            ["cargo", "build", "--offline", "--bin", "full_aios_rebuild"],
            cwd=HIVE,
            timeout=300,
        )
        write_new(run_dir / "rust_build.log", (build.stdout + build.stderr).encode())
        if build.returncode != 0:
            raise RuntimeError(f"Rust coordinator build failed: {build.stderr[-4000:]}")

        bridge_build = run_dir / "bridge_build"
        bridge_build.mkdir()
        bridge_exe = bridge_build / "rust_frontend.exe"
        fmt = run_process(
            ["rustfmt", "--edition", "2021", "--check", str(BRIDGE_SOURCE)],
            cwd=BRIDGE,
            timeout=120,
        )
        if fmt.returncode != 0:
            raise RuntimeError(
                f"NumPy/CuPy bridge format check failed: {fmt.stderr[-3000:]}"
            )
        bridge_tests = run_process(
            [str(BRIDGE_PYTHON), "-m", "unittest", "discover", "-s", "tests", "-v"],
            cwd=BRIDGE,
            timeout=180,
        )
        write_new(
            run_dir / "numpy_cupy_tests.log",
            (bridge_tests.stdout + bridge_tests.stderr).encode(),
        )
        if bridge_tests.returncode != 0:
            raise RuntimeError(
                f"NumPy/CuPy bridge tests failed: {bridge_tests.stderr[-4000:]}"
            )
        compile_bridge = run_process(
            [
                "rustc",
                "--edition=2021",
                "-D",
                "warnings",
                str(BRIDGE_SOURCE),
                "-o",
                str(bridge_exe),
            ],
            cwd=BRIDGE,
            timeout=300,
        )
        write_new(
            run_dir / "numpy_cupy_rustc.log",
            (compile_bridge.stdout + compile_bridge.stderr).encode(),
        )
        if compile_bridge.returncode != 0:
            raise RuntimeError(
                f"NumPy/CuPy Rust bridge build failed: {compile_bridge.stderr[-4000:]}"
            )

        command = [
            str(RUST_BINARY),
            "--manifest",
            str(run_dir / "source_manifest.json"),
            "--sidecar",
            str(run_dir / "source_manifest.sha256"),
            "--source",
            str(SOURCE),
            "--staged",
            str(staged),
            "--candidate",
            str(candidate),
            "--run-id",
            run_id,
            "--plan",
            str(run_dir / "mind_plan_transcript.json"),
            "--foreman-id",
            foreman_id,
            "--gpu-exe",
            str(bridge_exe),
            "--gpu-python",
            str(BRIDGE_PYTHON),
            "--switchboard",
            str(BRIDGE_SWITCHBOARD),
            "--verifier-python",
            str(PYTHON),
            "--verifier",
            str(VERIFIER),
        ]
        execution = run_process(command, cwd=HIVE, timeout=1800)
        write_new(run_dir / "rust_execution_stdout.txt", execution.stdout.encode())
        write_new(run_dir / "rust_execution_stderr.txt", execution.stderr.encode())
        if execution.returncode != 0:
            raise RuntimeError(
                f"Rust full-manifest execution held: {execution.stderr[-5000:]}"
            )
        rust_receipt = json.loads(execution.stdout)
        write_json_new(run_dir / "rust_execution_receipt.json", rust_receipt)
        receipt["rust_receipt_sha256"] = sha_file(
            run_dir / "rust_execution_receipt.json"
        )
        if (
            rust_receipt.get("status") != "PASS"
            or rust_receipt.get("catalogued_file_count") != manifest["file_count"]
            or rust_receipt.get("core_count") != len(manifest["cores"])
        ):
            raise ValueError("Rust receipt does not prove full manifest coverage")

        from verify_full_candidate import verify as verify_candidate

        independent = verify_candidate(
            run_dir / "source_manifest.json", SOURCE, candidate
        )
        write_json_new(run_dir / "independent_candidate_verification.json", independent)
        if (
            independent.get("status") != "PASS"
            or independent.get("manifest_file_count") != 3641
            or independent.get("candidate_file_count") != 3641
        ):
            raise ValueError("independent full-candidate verification held")
        receipt.update(
            {
                "status": "PASS_SOURCE_PRESERVING_FULL_MANIFEST_ASSEMBLY",
                "finished_utc": datetime.now(timezone.utc).isoformat(),
                "candidate": str(candidate),
                "candidate_verification": independent,
                "source_modified": False,
                "source_code_executed": False,
                "candidate_executed": False,
                "model_generated_source": False,
                "swarm_generation_count": 0,
                "task_count": rust_receipt.get("task_count"),
                "mind_intent": rust_receipt.get("mind_intent"),
                "mind_task_dependencies": [
                    {
                        "id": row["id"],
                        "required_depends_on": next(
                            contract["required_depends_on"]
                            for contract in contracts
                            if contract["id"] == row["id"]
                        ),
                        "additional_depends_on": row["additional_depends_on"],
                    }
                    for row in mind_transcript["parsed"]["tasks"]
                ],
                "numpy_cupy_receipt": read_json(run_dir / "numpy_cupy_receipt.json"),
            }
        )
    except Exception as error:  # Keep failed attempts with all available evidence.
        receipt.update(
            {
                "status": "HOLD",
                "finished_utc": datetime.now(timezone.utc).isoformat(),
                "hold_reason": f"{type(error).__name__}: {error}",
                "source_modified": False,
                "candidate_executed": False,
            }
        )
        print(f"HOLD {receipt['hold_reason']}", file=sys.stderr, flush=True)
    finally:
        receipt["artifact_sha256"] = {
            path.name: sha_file(path)
            for path in sorted(run_dir.iterdir())
            if path.is_file()
            and path.name not in {"run_receipt.json", "run_receipt.sha256"}
        }
        receipt_hash = write_json_new(run_dir / "run_receipt.json", receipt)
        write_new(
            run_dir / "run_receipt.sha256",
            f"{receipt_hash}  run_receipt.json\n".encode("ascii"),
        )
        print(f"RUN={run_dir} STATUS={receipt['status']}", flush=True)
    return (
        0 if receipt["status"] == "PASS_SOURCE_PRESERVING_FULL_MANIFEST_ASSEMBLY" else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
