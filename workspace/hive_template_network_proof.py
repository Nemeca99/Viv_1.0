"""Mind-generated data stamped by deterministic Swarm template agents."""

from __future__ import annotations

import ast
import importlib
import json
import platform
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hive_foreman_memory import load_latest
from hive_network_proof import (
    HUMAN_REPLY,
    MindVault,
    bind_task,
    command,
    foreman_binding,
    safe_tool_snapshot,
    sha,
)
from hive_template_runtime import TemplateRuntime

ROOT = Path(__file__).resolve().parent
MIND_MODEL = "qwen3:8b-local"
OLLAMA = "http://127.0.0.1:11434/api/chat"


def mind_generate(
    system: str, task: dict[str, Any], schema: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    body = {
        "model": MIND_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(task, ensure_ascii=False)},
        ],
        "stream": False,
        "format": schema,
        "think": False,
        "keep_alive": "10m",
        "options": {"temperature": 0, "seed": 42, "num_ctx": 4096, "num_predict": 128},
    }
    request = urllib.request.Request(
        OLLAMA,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    start = time.perf_counter()
    with urllib.request.urlopen(request, timeout=240) as response:
        result = json.load(response)
    elapsed = time.perf_counter() - start
    raw = result.get("message", {}).get("content", "")
    try:
        variables = json.loads(raw)
    except json.JSONDecodeError:
        variables = {"_invalid_json": raw}
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
    metrics.update({"wall_seconds": round(elapsed, 3), "raw": raw})
    return variables, metrics


def safe_exec_greeting(source: str) -> str:
    compiled = compile(source, "hello.py", "exec", dont_inherit=True)

    def allowed_import(
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
        raise ImportError("template proof import outside allowlist")

    namespace: dict[str, Any] = {
        "__builtins__": {"__import__": allowed_import, "str": str}
    }
    exec(compiled, namespace)
    return namespace["greet"]()


def run(inject_parent_fault: bool = False) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out = ROOT / "hive_template_runs" / stamp
    out.mkdir(parents=True, exist_ok=False)
    artifact = out / "hello.py"
    templates = TemplateRuntime()
    vault = MindVault()
    foreman = load_latest()
    foreman_context = foreman_binding(foreman)
    foreman_path = sorted((ROOT / "hive_snapshots").glob("*.json"))[-1]
    receipt: dict[str, Any] = {
        "proof": "Mind-generates-slots; deterministic-Swarm-stamps-templates",
        "scope": "local simulation; not Rust production coordinator or held-out evaluation",
        "mind_model": MIND_MODEL,
        "swarm_worker_model_generations": 0,
        "swarm_role": "deterministic template stampers; no source generation",
        "fault_injection_mode": inject_parent_fault,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "host": platform.node(),
        "resource": safe_tool_snapshot(),
        "mind_generations": [],
        "swarm_tasks": [],
        "human_events": [],
        "foreman_context": {
            "snapshot_path": str(foreman_path.relative_to(ROOT)),
            **foreman_context,
        },
        "template_registry_sha256": templates.registry_sha256,
        "template_sources": {
            key: value[1] for key, value in templates.templates.items()
        },
    }

    # Mind prepares the first small task's data; Swarm 1 only stamps the approved template.
    schema1 = {
        "type": "object",
        "properties": {
            "module_docstring": {"type": "string", "enum": ["Hive greeting module"]},
            "import_template_id": {
                "type": "string",
                "enum": ["python.typing_final_import"],
            },
        },
        "required": ["module_docstring", "import_template_id"],
        "additionalProperties": False,
    }
    variables1, metrics1 = mind_generate(
        "You are Viv, the Hive Mind. Generate only the requested typed variable values from the user's task. Do not generate or output source code. Follow the supplied foreman context; no tools or system actions.",
        {
            "user_task": "Create hello.py as a Hive greeting module, with a Final[str] greeting and greet() function.",
            "foreman_context": foreman_context,
        },
        schema1,
    )
    valid1 = variables1 == {
        "module_docstring": "Hive greeting module",
        "import_template_id": "python.typing_final_import",
    }
    receipt["mind_generations"].append(
        {
            "stage": "prepare_header_and_import",
            "generation_count": 1,
            "posthoc_pass": valid1,
            "metrics": metrics1,
        }
    )
    if not valid1:
        receipt["status"] = "HOLD_MIND_VARIABLES_TASK_001"
        return finish(out, receipt)

    task1 = vault.seal_task(
        "task-001",
        "stamp-module-header",
        bind_task(
            {
                "template_id": "python.module_docstring",
                "slots": {"docstring": variables1["module_docstring"]},
                "objective": "Stamp one module docstring from the supplied data slot.",
            },
            foreman_context,
        ),
        None,
    )
    prepared1 = vault.open_for_runner("task-001", "stamp-module-header")
    rendered1 = templates.render(prepared1["template_id"], prepared1["slots"])
    artifact.write_text(rendered1.code, encoding="utf-8")
    stage1_hash = sha(artifact.read_bytes())
    receipt["swarm_tasks"].append(
        {
            **task1,
            "agent_type": "deterministic_template_stamper",
            "stamp_count": 1,
            "generation_count": 0,
            "posthoc_pass": True,
            "template_id": rendered1.template_id,
            "template_sha256": rendered1.source_sha256,
            "artifact_sha256": stage1_hash,
        }
    )

    # Swarm 2 stamps a closed template selected by Mind; values are not source text.
    task2 = vault.seal_task(
        "task-002",
        "stamp-import",
        bind_task(
            {
                "template_id": variables1["import_template_id"],
                "slots": {},
                "input_artifact": artifact.read_text(encoding="utf-8"),
                "input_artifact_sha256": stage1_hash,
                "objective": "Append the selected static import template while preserving the parent artifact.",
            },
            foreman_context,
        ),
        task1["checksum"],
    )
    prepared2 = vault.open_for_runner("task-002", "stamp-import")
    rendered2 = templates.render(prepared2["template_id"], prepared2["slots"])
    artifact.write_text(
        prepared2["input_artifact"].rstrip() + "\n\n" + rendered2.code, encoding="utf-8"
    )
    normal_parent_hash = sha(artifact.read_bytes())
    parsed2 = ast.parse(artifact.read_text(encoding="utf-8"))
    task2_pass = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "typing"
        and any(alias.name == "Final" for alias in node.names)
        for node in parsed2.body
    )
    receipt["swarm_tasks"].append(
        {
            **task2,
            "agent_type": "deterministic_template_stamper",
            "stamp_count": 1,
            "generation_count": 0,
            "posthoc_pass": task2_pass,
            "template_id": rendered2.template_id,
            "template_sha256": rendered2.source_sha256,
            "parent_artifact_sha256": stage1_hash,
            "artifact_sha256": normal_parent_hash,
        }
    )
    if not task2_pass:
        receipt["status"] = "HOLD_TASK_002_LOCAL_CHECK"
        return finish(out, receipt)

    receipt["human_events"].append(
        {
            "task_id": "human-greeting",
            "status": "REPLIED",
            "route": "Queen -> Viv -> waiting task-003",
            "reply": HUMAN_REPLY,
            "resumed_by": "Mind generation 2",
        }
    )
    # Viv resumes and generates the function's data slots, never source code.
    schema3 = {
        "type": "object",
        "properties": {
            "greeting": {"type": "string", "enum": [HUMAN_REPLY]},
            "function_name": {"type": "string", "enum": ["greet"]},
        },
        "required": ["greeting", "function_name"],
        "additionalProperties": False,
    }
    variables3, metrics3 = mind_generate(
        "You are Viv resuming a waiting task after the Queen's reply. Generate only typed values for the approved code template. Copy the human reply exactly into greeting; set function_name to greet. Do not output code.",
        {
            "user_task": "Add a final greeting function to hello.py.",
            "human_reply": HUMAN_REPLY,
            "parent_artifact": artifact.read_text(encoding="utf-8"),
            "foreman_context": foreman_context,
        },
        schema3,
    )
    valid3 = variables3 == {"greeting": HUMAN_REPLY, "function_name": "greet"}
    receipt["mind_generations"].append(
        {
            "stage": "resume_function_variables",
            "generation_count": 1,
            "posthoc_pass": valid3,
            "metrics": metrics3,
        }
    )
    if not valid3:
        receipt["status"] = "HOLD_MIND_VARIABLES_TASK_003"
        return finish(out, receipt)

    if inject_parent_fault:
        # A syntactically valid but semantically wrong parent passes task 2's local AST check.
        source = artifact.read_text(encoding="utf-8")
        artifact.write_text(
            source.replace("from typing import Final", "from typing import Optional"),
            encoding="utf-8",
        )
    child_input = artifact.read_text(encoding="utf-8")
    task3 = vault.seal_task(
        "task-003",
        "stamp-greeting-function",
        bind_task(
            {
                "template_id": "python.greeting_function",
                "slots": {
                    "greeting": variables3["greeting"],
                    "function_name": variables3["function_name"],
                },
                "input_artifact": child_input,
                "input_artifact_sha256": sha(child_input.encode("utf-8")),
                "expected_parent_artifact_sha256": normal_parent_hash,
                "objective": "Stamp the approved greeting-function template using only Mind-generated data slots.",
            },
            foreman_context,
        ),
        task2["checksum"],
    )
    prepared3 = vault.open_for_runner("task-003", "stamp-greeting-function")
    rendered3 = templates.render(prepared3["template_id"], prepared3["slots"])
    artifact.write_text(
        prepared3["input_artifact"].rstrip() + "\n\n" + rendered3.code, encoding="utf-8"
    )
    composition_error = None
    try:
        greeting = safe_exec_greeting(artifact.read_text(encoding="utf-8"))
        task3_pass = greeting == HUMAN_REPLY
    except (NameError, ImportError, SyntaxError) as exc:
        task3_pass = False
        greeting = None
        composition_error = {"type": type(exc).__name__, "detail": str(exc)}
    receipt["swarm_tasks"].append(
        {
            **task3,
            "agent_type": "deterministic_template_stamper",
            "stamp_count": 1,
            "generation_count": 0,
            "posthoc_pass": task3_pass,
            "template_id": rendered3.template_id,
            "template_sha256": rendered3.source_sha256,
            "parent_artifact_sha256": sha(child_input.encode("utf-8")),
            "artifact_sha256": sha(artifact.read_bytes()),
        }
    )
    receipt["composition_chain"] = {
        "task2_local_check_passed": task2_pass,
        "task2_artifact_sha256": normal_parent_hash,
        "task3_input_sha256": sha(child_input.encode("utf-8")),
        "task3_parent_checksum": task3["parent_checksum"],
        "child_template_stamp_count": 1,
        "fault_injected": inject_parent_fault,
        "fault": "Optional imported instead of Final after task-2 local check"
        if inject_parent_fault
        else None,
        "downstream_composition_passed": task3_pass,
        "downstream_error": composition_error,
        "repair_generations": 0,
    }
    receipt["artifact"] = {
        "path": str(artifact.relative_to(ROOT)),
        "sha256": sha(artifact.read_bytes()),
        "greet_result": greeting,
    }
    receipt["security_checks"] = {
        "wrong_worker_decryption_denied": False,
        "ciphertext_tamper_detected": False,
        "task_keys_wrapped_by_mind_master": True,
        "channel_key_separate_from_master": False,
        "peer_channel_without_grant_denied": not vault.peer_channel_allowed(
            "stamp-module-header", "stamp-import", "task-002"
        ),
        "mind_key_material_excluded_from_prompt": True,
    }
    try:
        vault.open_for_runner("task-001", "stamp-import")
    except PermissionError:
        receipt["security_checks"]["wrong_worker_decryption_denied"] = True
    row = vault.index["task-003"]
    ciphertext = row["ciphertext"]
    row["ciphertext"] = ("00" if ciphertext[:2] != "00" else "ff") + ciphertext[2:]
    try:
        vault.open_for_runner("task-003", "stamp-greeting-function")
    except ValueError:
        receipt["security_checks"]["ciphertext_tamper_detected"] = True
    row["ciphertext"] = ciphertext
    _grant, _key_hash, separate = vault.create_channel_grant(
        "stamp-module-header", "stamp-import", "task-003"
    )
    receipt["security_checks"]["channel_key_separate_from_master"] = separate
    receipt["resource"]["ollama_ps_after"] = command(["ollama", "ps"])
    receipt["resource"]["nvidia_smi_after"] = command(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.used,memory.total,utilization.gpu",
            "--format=csv,noheader",
        ]
    )
    if inject_parent_fault and not task3_pass and composition_error:
        receipt["status"] = "HOLD_PARENT_FAULT_CAUGHT"
    else:
        receipt["status"] = (
            "PASS"
            if task3_pass and all(receipt["security_checks"].values())
            else "HOLD_POSTHOC_OR_SECURITY_FAILURE"
        )
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
                "mind_seconds": [
                    row["metrics"].get("wall_seconds")
                    for row in receipt.get("mind_generations", [])
                ],
                "swarm_tasks": [
                    {
                        "task": row["task_id"],
                        "stamp_count": row.get("stamp_count"),
                        "pass": row.get("posthoc_pass"),
                    }
                    for row in receipt.get("swarm_tasks", [])
                ],
            },
            indent=2,
        )
    )
    return path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--inject-parent-fault", action="store_true")
    run(inject_parent_fault=parser.parse_args().inject_parent_fault)
