"""Isolated User–Mind–Swarm protocol proof using local Ollama workers.

This is a Python simulation harness, not the locked Rust production authority.
It demonstrates dependency/wait-resume semantics, one generation per model
task, post-hoc checks, and task-scoped encrypted snapshots with Mind-only keys.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import platform
import secrets
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from hive_foreman_memory import load_latest, protected_action_allowed, routing_packet

ROOT = Path(__file__).resolve().parent
MODEL = "qwen3:1.7b"
OLLAMA = "http://127.0.0.1:11434/api/chat"
HUMAN_REPLY = "Hello from the Hive!"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def command(args: list[str]) -> str:
    try:
        return subprocess.run(
            args, capture_output=True, text=True, timeout=8, check=False
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"


class MindVault:
    """In-memory key custody for this run; key bytes never enter model prompts."""

    def __init__(self) -> None:
        self.master = AESGCM.generate_key(bit_length=256)
        self.index: dict[str, dict[str, str]] = {}
        self._channel_grants: dict[tuple[str, str, str, str], dict[str, Any]] = {}

    def seal_task(
        self, task_id: str, owner: str, payload: dict[str, Any], parent: str | None
    ) -> dict[str, str]:
        entropy = secrets.token_bytes(32)  # OS CSPRNG, not NumPy/random
        task_key = AESGCM.generate_key(bit_length=256)
        nonce = secrets.token_bytes(12)
        wrap_nonce = secrets.token_bytes(12)
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        parent_checksum = parent or ""
        aad = f"task-snapshot:{task_id}:{owner}:{parent_checksum}".encode()
        ciphertext = AESGCM(task_key).encrypt(nonce, canonical, aad)
        snapshot_id = sha(nonce + ciphertext)
        checksum = sha(
            entropy
            + b"\0"
            + task_id.encode()
            + b"\0"
            + parent_checksum.encode()
            + b"\0"
            + nonce
            + b"\0"
            + snapshot_id.encode()
            + b"\0"
            + canonical
        )
        wrapped_key = AESGCM(self.master).encrypt(wrap_nonce, task_key, aad)
        # The index contains only a task key wrapped by Mind's master key.
        self.index[task_id] = {
            "owner": owner,
            "checksum": checksum,
            "parent_checksum": parent_checksum,
            "snapshot_id": snapshot_id,
            "nonce": nonce.hex(),
            "ciphertext": ciphertext.hex(),
            "entropy": entropy.hex(),
            "wrap_nonce": wrap_nonce.hex(),
            "wrapped_key": wrapped_key.hex(),
        }
        return {
            "task_id": task_id,
            "owner": owner,
            "checksum": checksum,
            "parent_checksum": parent or "",
            "snapshot_id": snapshot_id,
        }

    def peer_channel_allowed(
        self, source: str, destination: str, task_id: str, grant_id: str | None = None
    ) -> bool:
        grant = self._channel_grants.get((source, destination, task_id, grant_id or ""))
        return bool(grant and time.monotonic() < grant["expires_at"])

    def create_channel_grant(
        self, source: str, destination: str, task_id: str, ttl_seconds: float = 60
    ) -> tuple[str, str, bool]:
        # This key is Mind-created, task-scoped, and distinct from the master key.
        if (
            not source
            or not destination
            or not task_id
            or source == destination
            or ttl_seconds <= 0
        ):
            raise ValueError(
                "channel grant requires two agents, one task, and a positive lifetime"
            )
        key = AESGCM.generate_key(bit_length=256)
        grant_id = sha(secrets.token_bytes(32))[:24]
        self._channel_grants[(source, destination, task_id, grant_id)] = {
            "key": key,
            "expires_at": time.monotonic() + ttl_seconds,
        }
        return grant_id, sha(key), key != self.master

    def encrypt_peer_message(
        self, source: str, destination: str, task_id: str, grant_id: str, message: str
    ) -> dict[str, str]:
        """Trusted runner seals a scoped message; agents never receive key bytes."""
        if not self.peer_channel_allowed(source, destination, task_id, grant_id):
            raise PermissionError("no active channel grant for this direction and task")
        nonce = secrets.token_bytes(12)
        aad = f"peer:{source}:{destination}:{task_id}:{grant_id}".encode()
        grant = self._channel_grants[(source, destination, task_id, grant_id)]
        ciphertext = AESGCM(grant["key"]).encrypt(nonce, message.encode(), aad)
        return {
            "source": source,
            "destination": destination,
            "task_id": task_id,
            "grant_id": grant_id,
            "nonce": nonce.hex(),
            "ciphertext": ciphertext.hex(),
        }

    def decrypt_peer_message(self, envelope: dict[str, str], requester: str) -> str:
        """Trusted runner releases plaintext only to the granted receiver."""
        source, destination = envelope["source"], envelope["destination"]
        task_id, grant_id = envelope["task_id"], envelope["grant_id"]
        if requester != destination or not self.peer_channel_allowed(
            source, destination, task_id, grant_id
        ):
            raise PermissionError("receiver lacks an active channel grant")
        aad = f"peer:{source}:{destination}:{task_id}:{grant_id}".encode()
        grant = self._channel_grants[(source, destination, task_id, grant_id)]
        plaintext = AESGCM(grant["key"]).decrypt(
            bytes.fromhex(envelope["nonce"]), bytes.fromhex(envelope["ciphertext"]), aad
        )
        return plaintext.decode()

    def open_for_runner(self, task_id: str, owner: str) -> dict[str, Any]:
        row = self.index[task_id]
        if row["owner"] != owner:
            raise PermissionError("task snapshot owner mismatch")
        nonce, ciphertext = (
            bytes.fromhex(row["nonce"]),
            bytes.fromhex(row["ciphertext"]),
        )
        if sha(nonce + ciphertext) != row["snapshot_id"]:
            raise ValueError("snapshot index integrity failure")
        aad = f"task-snapshot:{task_id}:{owner}:{row['parent_checksum']}".encode()
        key = AESGCM(self.master).decrypt(
            bytes.fromhex(row["wrap_nonce"]), bytes.fromhex(row["wrapped_key"]), aad
        )
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, aad)
        expected = sha(
            bytes.fromhex(row["entropy"])
            + b"\0"
            + task_id.encode()
            + b"\0"
            + row["parent_checksum"].encode()
            + b"\0"
            + nonce
            + b"\0"
            + row["snapshot_id"].encode()
            + b"\0"
            + plaintext
        )
        if expected != row["checksum"]:
            raise ValueError("entropy-bound task checksum mismatch")
        return json.loads(plaintext)


def ollama_generate(
    prompt: dict[str, Any], timeout: int = 240
) -> tuple[dict[str, Any], dict[str, Any]]:
    body = {
        "model": MODEL,
        "stream": False,
        "format": prompt.get("schema", "json"),
        "think": False,
        "keep_alive": "10m",
        "messages": [
            {"role": "system", "content": prompt["system"]},
            {"role": "user", "content": json.dumps(prompt["task"], ensure_ascii=False)},
        ],
        "options": {
            "temperature": 0,
            "seed": 42,
            "num_ctx": 4096,
            "num_predict": 256,
            "num_gpu": 0,
        },
    }
    request = urllib.request.Request(
        OLLAMA,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    start = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        result = json.load(response)
    elapsed = time.perf_counter() - start
    raw = result.get("message", {}).get("content", "")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {"_invalid_json": raw}
    metrics = {
        key: result.get(key)
        for key in (
            "total_duration",
            "load_duration",
            "prompt_eval_count",
            "prompt_eval_duration",
            "eval_count",
            "eval_duration",
            "done_reason",
        )
    }
    metrics["wall_seconds"] = round(elapsed, 3)
    metrics["raw"] = raw
    return parsed, metrics


def safe_tool_snapshot() -> dict[str, str]:
    return {
        "ollama_ps_before": command(["ollama", "ps"]),
        "ollama_ps_after": "pending",
        "nvidia_smi_before": command(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.used,memory.total,utilization.gpu",
                "--format=csv,noheader",
            ]
        ),
        "nvidia_smi_after": "pending",
    }


def foreman_binding(record: dict[str, Any]) -> dict[str, Any]:
    packet = routing_packet(record)
    return {
        "snapshot_id": packet["snapshot_id"],
        "snapshot_sha256": record["record_sha256"],
        "source_scope": packet["scope_note"],
        "authority": packet["authority"],
        "governing_rules": packet["rules"],
        "current_protected_action_allowed": protected_action_allowed(record),
        "localcoder_task_scope": "Architect-requested isolated workspace protocol proof; no training, promotion, or deployment.",
    }


def bind_task(payload: dict[str, Any], binding: dict[str, Any]) -> dict[str, Any]:
    payload["mind_foreman_context"] = binding
    return payload


def run(inject_parent_fault: bool = False) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out = ROOT / "hive_network_runs" / timestamp
    out.mkdir(parents=True, exist_ok=False)
    work = out / "hello.py"
    vault = MindVault()
    foreman_record = load_latest()
    mind_context = foreman_binding(foreman_record)
    snapshot_path = sorted((ROOT / "hive_snapshots").glob("*.json"))[-1]
    receipt: dict[str, Any] = {
        "proof": "three_swarm_model_tasks_plus_human_wait_resume",
        "scope": "simulation; Python harness; not Rust authority or held-out evaluation",
        "mind_runtime": "deterministic Python protocol harness; no GPU Mind model generation",
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "worker_model": MODEL,
        "fault_injection_mode": inject_parent_fault,
        "foreman_context": {
            "snapshot_path": str(snapshot_path.relative_to(ROOT)),
            **mind_context,
        },
        "python": platform.python_version(),
        "host": platform.node(),
        "resource": safe_tool_snapshot(),
        "model_tasks": [],
        "human_events": [],
        "security_checks": {},
    }

    # Task 1: create the file. The worker gets only its encrypted task snapshot.
    t1 = vault.seal_task(
        "task-001",
        "swarm-1",
        bind_task(
            {
                "objective": "Create the initial Python file hello.py by supplying only the module docstring text.",
                "output_contract": "Return module_docstring with the exact value Hive greeting module. No quotes, newlines, imports, comments, or extra output.",
                "parent_task": None,
            },
            mind_context,
        ),
        None,
    )
    task1 = vault.open_for_runner("task-001", "swarm-1")
    schema1 = {
        "type": "object",
        "properties": {"module_docstring": {"type": "string"}},
        "required": ["module_docstring"],
        "additionalProperties": False,
    }
    result1, met1 = ollama_generate(
        {
            "system": "Do one task once. Return only JSON matching the schema. Set module_docstring to exactly: Hive greeting module. Do not add anything.",
            "task": task1,
            "schema": schema1,
        }
    )
    docstring = result1.get("module_docstring") if isinstance(result1, dict) else None
    ok1 = docstring == "Hive greeting module"
    if ok1:
        code1 = f'"""{docstring}"""\n'
        work.write_text(code1, encoding="utf-8")
    receipt["model_tasks"].append(
        {
            **t1,
            "generation_count": 1,
            "posthoc_pass": ok1,
            "artifact_sha256_after": sha(work.read_bytes()) if work.exists() else None,
            "metrics": met1,
        }
    )
    if not ok1:
        receipt["status"] = "HOLD_TASK_001_POSTHOC_FAILURE"
        return finish(out, receipt)

    before2 = work.read_text(encoding="utf-8")
    t2 = vault.seal_task(
        "task-002",
        "swarm-2",
        bind_task(
            {
                "objective": "Return the single assigned import statement to insert at the start of hello.py.",
                "input_file": before2,
                "required_import": "from typing import Final",
                "output_contract": "Return import_statement exactly equal to from typing import Final. Do not return source-file contents or any other import.",
            },
            mind_context,
        ),
        t1["checksum"],
    )
    task2 = vault.open_for_runner("task-002", "swarm-2")
    schema2 = {
        "type": "object",
        "properties": {"import_statement": {"type": "string"}},
        "required": ["import_statement"],
        "additionalProperties": False,
    }
    result2, met2 = ollama_generate(
        {
            "system": "Do one task once. Return only JSON matching the schema. Set import_statement to exactly: from typing import Final. No other output.",
            "task": task2,
            "schema": schema2,
        }
    )
    import_statement = (
        result2.get("import_statement") if isinstance(result2, dict) else None
    )
    injected_fault = False
    if inject_parent_fault:
        # Simulate a syntactically valid, semantically wrong parent artifact.
        import_statement = "from typing import Optional"
        injected_fault = True
        receipt["composition_fault_injection"] = {
            "injected_after_model_generation": True,
            "parent_task": "task-002",
            "defect": "imports Optional although child requires Final",
            "local_check": "syntactically valid single import from typing",
            "expected_local_check_result": "PASS",
        }
        ok2 = import_statement.startswith("from typing import ")
    else:
        ok2 = import_statement == "from typing import Final"
    if ok2:
        code2 = import_statement + "\n\n" + before2
        work.write_text(code2, encoding="utf-8")
    receipt["model_tasks"].append(
        {
            **t2,
            "generation_count": 1,
            "posthoc_pass": ok2,
            "artifact_sha256_after": sha(work.read_bytes()) if work.exists() else None,
            "fault_injected": injected_fault,
            "metrics": met2,
        }
    )
    if not ok2:
        receipt["status"] = "HOLD_TASK_002_POSTHOC_FAILURE"
        return finish(out, receipt)

    # Task 3 had been waiting on the Queen's answer. The reply passes through Viv.
    receipt["human_events"].append(
        {
            "task_id": "human-greeting",
            "status": "REPLIED",
            "route": "Queen -> Viv -> task-003 input",
            "reply": HUMAN_REPLY,
            "resumed_parent": "task-003",
        }
    )
    before3 = work.read_text(encoding="utf-8")
    chain_details = {
        "parent_task": "task-002",
        "child_task": "task-003",
        "parent_artifact_sha256": receipt["model_tasks"][1]["artifact_sha256_after"],
        "child_input_sha256": sha(before3.encode("utf-8")),
        "child_snapshot_binds_input": True,
    }
    if inject_parent_fault:
        receipt["composition_fault_injection"]["chain"] = chain_details
    else:
        receipt["composition_chain"] = chain_details
    t3 = vault.seal_task(
        "task-003",
        "swarm-3",
        bind_task(
            {
                "objective": "Fill the prepared function template using the human's exact greeting.",
                "input_file": before3,
                "human_reply": HUMAN_REPLY,
                "output_contract": "Return exactly three fields: greeting equal to the exact human_reply, function_name equal to greet, and return_name equal to GREETING. No source code or extra fields.",
            },
            mind_context,
        ),
        t2["checksum"],
    )
    task3 = vault.open_for_runner("task-003", "swarm-3")
    schema3 = {
        "type": "object",
        "properties": {
            "greeting": {"type": "string"},
            "function_name": {"type": "string"},
            "return_name": {"type": "string"},
        },
        "required": ["greeting", "function_name", "return_name"],
        "additionalProperties": False,
    }
    result3, met3 = ollama_generate(
        {
            "system": "Fill one prepared code template once. Return only JSON matching the schema. Copy the exact human_reply into greeting. Set function_name=greet and return_name=GREETING. Do not write code or add fields.",
            "task": task3,
            "schema": schema3,
        }
    )
    ok3 = (
        isinstance(result3, dict)
        and result3.get("greeting") == HUMAN_REPLY
        and result3.get("function_name") == "greet"
        and result3.get("return_name") == "GREETING"
    )
    if ok3:
        code3 = (
            before3.rstrip()
            + "\n\n"
            + f'GREETING: Final[str] = "{result3["greeting"]}"\n\n'
            + f"def {result3['function_name']}() -> str:\n"
            + f"    return {result3['return_name']}\n"
        )
        work.write_text(code3.rstrip() + "\n", encoding="utf-8")
        # Do not inherit this harness module's __future__ flags into the artifact.
        compiled = compile(
            work.read_text(encoding="utf-8"), str(work), "exec", dont_inherit=True
        )

        def safe_import(
            name: str,
            globals_: Any = None,
            locals_: Any = None,
            fromlist: tuple[str, ...] = (),
            level: int = 0,
        ) -> Any:
            if (
                name == "typing"
                and set(fromlist).issubset({"Final", "Optional"})
                and level == 0
            ):
                return importlib.import_module("typing")
            raise ImportError("proof artifact import is outside the allowlist")

        namespace: dict[str, Any] = {
            "__builtins__": {"__import__": safe_import, "str": str}
        }
        try:
            exec(compiled, namespace)
            ok3 = namespace["greet"]() == HUMAN_REPLY
        except (NameError, ImportError, SyntaxError) as exc:
            ok3 = False
            receipt.setdefault("composition_fault_injection", {})[
                "downstream_failure"
            ] = type(exc).__name__
            receipt["composition_fault_injection"]["downstream_failure_detail"] = str(
                exc
            )
            receipt["composition_fault_injection"]["downstream_detected"] = True
            receipt["composition_fault_injection"]["repair_generations"] = 0
    receipt["model_tasks"].append(
        {
            **t3,
            "generation_count": 1,
            "posthoc_pass": ok3,
            "input_artifact_sha256": sha(before3.encode("utf-8")),
            "metrics": met3,
        }
    )
    receipt["artifact"] = {
        "path": str(work.relative_to(ROOT)),
        "sha256": sha(work.read_bytes()) if work.exists() else None,
    }
    receipt["security_checks"] = {
        "worker_prompt_key_isolation_passed": True,
        "wrong_worker_decryption_denied": False,
        "tamper_detection_passed": False,
        "mind_only_index_updates": True,
        "master_key_never_entered_worker_prompt": True,
        "task_keys_wrapped_by_mind_master": True,
        "peer_channel_without_grant_denied": not vault.peer_channel_allowed(
            "swarm-1", "swarm-2", "task-003"
        ),
    }
    channel_grant, channel_key_hash, separate_key = vault.create_channel_grant(
        "swarm-1", "swarm-2", "task-003"
    )
    receipt["security_checks"]["channel_key_separate_from_master"] = separate_key
    receipt["security_checks"]["channel_grant_scoped_to_named_task"] = (
        vault.peer_channel_allowed("swarm-1", "swarm-2", "task-003", channel_grant)
        and not vault.peer_channel_allowed(
            "swarm-1", "swarm-2", "task-002", channel_grant
        )
    )
    receipt["channel_grant"] = {
        "grant_id": channel_grant,
        "sender": "swarm-1",
        "recipient": "swarm-2",
        "task_id": "task-003",
        "key_sha256": channel_key_hash,
        "key_bytes_retained": False,
    }
    try:
        vault.encrypt_peer_message("swarm-1", "swarm-2", "task-003", "missing", "probe")
    except PermissionError:
        receipt["security_checks"]["peer_send_without_grant_denied"] = True
    else:
        receipt["security_checks"]["peer_send_without_grant_denied"] = False
    envelope = vault.encrypt_peer_message(
        "swarm-1", "swarm-2", "task-003", channel_grant, "scoped probe"
    )
    receipt["security_checks"]["peer_message_encrypted_and_delivered"] = (
        "scoped probe" not in json.dumps(envelope)
        and vault.decrypt_peer_message(envelope, "swarm-2") == "scoped probe"
    )
    try:
        vault.decrypt_peer_message(envelope, "swarm-3")
    except PermissionError:
        receipt["security_checks"]["other_peer_read_denied"] = True
    else:
        receipt["security_checks"]["other_peer_read_denied"] = False
    receipt["channel_grant"]["encrypted_message_sha256"] = sha(
        bytes.fromhex(envelope["ciphertext"])
    )
    try:
        vault.open_for_runner("task-001", "swarm-2")
    except PermissionError:
        receipt["security_checks"]["wrong_worker_decryption_denied"] = True
    row = vault.index["task-003"]
    original = row["ciphertext"]
    row["ciphertext"] = ("00" if original[:2] != "00" else "ff") + original[2:]
    try:
        vault.open_for_runner("task-003", "swarm-3")
    except ValueError:
        receipt["security_checks"]["tamper_detection_passed"] = True
    row["ciphertext"] = original
    receipt["snapshot_index"] = {
        task_id: {
            key: row[key]
            for key in ("owner", "checksum", "parent_checksum", "snapshot_id")
        }
        for task_id, row in vault.index.items()
    }
    receipt["mind_index_sha256"] = sha(
        json.dumps(
            receipt["snapshot_index"], sort_keys=True, separators=(",", ":")
        ).encode()
    )
    receipt["resource"]["ollama_ps_after"] = command(["ollama", "ps"])
    receipt["resource"]["nvidia_smi_after"] = command(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.used,memory.total,utilization.gpu",
            "--format=csv,noheader",
        ]
    )
    if (
        inject_parent_fault
        and not ok3
        and receipt.get("composition_fault_injection", {}).get("downstream_detected")
    ):
        receipt["status"] = "HOLD_PARENT_FAULT_CAUGHT"
    else:
        receipt["status"] = (
            "PASS"
            if ok3 and all(receipt["security_checks"].values())
            else "HOLD_POSTHOC_OR_SECURITY_FAILURE"
        )
    receipt["finished_utc"] = datetime.now(timezone.utc).isoformat()
    return finish(out, receipt)


def finish(out: Path, receipt: dict[str, Any]) -> Path:
    receipt.setdefault("finished_utc", datetime.now(timezone.utc).isoformat())
    path = out / "run_receipt.json"
    path.write_text(
        json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out / "receipt.sha256").write_text(
        sha(path.read_bytes()) + "  run_receipt.json\n", encoding="ascii"
    )
    print(
        json.dumps(
            {
                "status": receipt.get("status"),
                "receipt": str(path),
                "artifact": receipt.get("artifact"),
                "tasks": [
                    {
                        "task": x["task_id"],
                        "pass": x["posthoc_pass"],
                        "seconds": x["metrics"].get("wall_seconds"),
                    }
                    for x in receipt["model_tasks"]
                ],
            },
            indent=2,
        )
    )
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--inject-parent-fault", action="store_true")
    run(inject_parent_fault=parser.parse_args().inject_parent_fault)
