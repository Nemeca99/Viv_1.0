"""Data-only transport for Viv-Mind swarm planning and synthesis.

Viv-Mind decomposes high-level goals into swarm capabilities (Stage 1 preparation,
Python specialist, Rust specialist, Cohort verification) and synthesizes the final
verified receipt for voice utterance.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hive_foreman_memory import load_latest, routing_packet  # noqa: E402


def plan_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "intent": {"type": "string"},
            "tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "capability": {
                            "type": "string",
                            "enum": [
                                "stage-input-source",
                                "execute-python-task",
                                "execute-rust-task",
                                "verify-cohort",
                            ],
                        },
                        "objective": {"type": "string"},
                        "depends_on": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "target_file": {"type": "string"},
                    },
                    "required": ["id", "capability", "objective", "depends_on"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["intent", "tasks"],
        "additionalProperties": False,
    }


def full_rebuild_plan_schema(
    task_contracts: list[dict[str, Any]], approved_tools: list[str]
) -> dict[str, Any]:
    """Constrain Viv's whole-AIOS plan to the hash-derived Rust task graph."""
    task_ids = [row["id"] for row in task_contracts]
    if len(set(task_ids)) != len(task_ids) or not task_ids:
        raise ValueError("full rebuild task IDs must be unique and non-empty")
    dependency_ids = ["mind_plan", *task_ids]
    return {
        "type": "object",
        "properties": {
            "intent": {"type": "string", "maxLength": 500},
            "tasks": {
                "type": "array",
                "minItems": len(task_ids),
                "maxItems": len(task_ids),
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "enum": task_ids},
                        "additional_depends_on": {
                            "type": "array",
                            "uniqueItems": True,
                            "items": {"type": "string", "enum": dependency_ids},
                        },
                        "sequencing_reason": {
                            "type": "string",
                            "minLength": 20,
                            "maxLength": 160,
                        },
                    },
                    "required": [
                        "id",
                        "additional_depends_on",
                        "sequencing_reason",
                    ],
                    "additionalProperties": False,
                },
            },
            "approved_tools": {
                "type": "array",
                "minItems": len(approved_tools),
                "maxItems": len(approved_tools),
                "uniqueItems": True,
                "items": {"type": "string", "enum": approved_tools},
            },
        },
        "required": ["intent", "tasks", "approved_tools"],
        "additionalProperties": False,
    }


def call_ollama(body: dict[str, Any]) -> dict[str, Any]:
    http = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    from aios_rebuild.main_core.mind_runtime_gate import open_authorized_model_request

    with open_authorized_model_request(http, timeout=300, requested_threads=2) as response:
        return json.load(response)


def main() -> None:
    request = json.load(sys.stdin)
    foreman = routing_packet(load_latest())
    phase = request["phase"]

    if phase == "full_rebuild_plan":
        task_contracts = request["task_contracts"]
        approved_tools = request["approved_tools"]
        system = (
            "You are Viv, the Hive Mind. Plan execution of the complete manifest-bound AIOS "
            "candidate across every listed core and workspace files. This run assembles and "
            "verifies a prepared 3,641-file baseline; it does not regenerate AIOS code. The "
            "coordinator inserts all required dependencies; do not restate or remove them. You "
            "may add dependency edges among the provided tasks "
            "to choose a safe schedule and limit overlapping resource-heavy work. Do not remove "
            "a required edge, invent a task, create a cycle, or change task scope. Return every "
            "provided task exactly once and explain each task's placement briefly in "
            "sequencing_reason. Approve exactly the listed tools. Do not claim completion."
        )
        user = {
            "goal": request["goal"],
            "foreman": foreman,
            "source_manifest_sha256": request["source_manifest_sha256"],
            "core_count": request["core_count"],
            "catalogued_file_count": request["catalogued_file_count"],
            "static_import_layers": request["static_import_layers"],
            "task_contracts": task_contracts,
            "approved_tools": approved_tools,
            "bounds": "Use only the provided tasks, fixed scopes, and allowlisted tools. Treat required_depends_on as mandatory; additional dependencies may reference listed task IDs or mind_plan, and must form an acyclic graph. The source baseline is read-only. Candidate output is confined to one new LocalCoder run directory. No training, promotion, deployment, or edits to the source baseline are authorized.",
        }
        schema = full_rebuild_plan_schema(task_contracts, approved_tools)
        max_predict = 3072
    elif phase == "plan":
        system = (
            "You are Viv, the Hive Mind. Decompose the Architect's goal into a precise "
            "multi-step execution graph across the Rust Swarm and Specialist Workers. "
            "Capabilities available:\n"
            "- stage-input-source: Stage and verify file formatting and quality with zero findings\n"
            "- execute-python-task: Autonomous Python LoRA specialist code generation\n"
            "- execute-rust-task: Autonomous Rust LoRA specialist code generation\n"
            "- verify-cohort: Static bounded checks, lint/format, and Rust metadata-only compilation; generated code is not executed\n"
            "Return JSON matching the schema strictly. Do not claim any task has completed."
        )
        capabilities = [
            {
                "name": "stage-input-source",
                "effect": "Format and lint check a target source file before model generation",
            },
            {
                "name": "execute-python-task",
                "effect": "Generate Python function implementation satisfying the objective",
            },
            {
                "name": "execute-rust-task",
                "effect": "Generate Rust function implementation satisfying the objective",
            },
            {
                "name": "verify-cohort",
                "effect": "Lint, format, and statically inspect bounded Python and Rust outputs; compile Rust metadata only; never execute generated code",
            },
        ]
        user = {
            "goal": request["goal"],
            "foreman": foreman,
            "capabilities": capabilities,
            "bounds": "Include exactly four tasks: stage-prep (stage-input-source), py-task (execute-python-task), rust-task (execute-rust-task), and verify-cohort. Python and Rust tasks are independent and depend on stage-prep. verify-cohort depends on stage-prep, py-task, and rust-task. Do not add AIOS, numerical, or other tasks to this coding-only proof.",
        }
        schema = plan_schema()
        max_predict = 1024
    elif phase in {"final", "full_rebuild_final"}:
        system = (
            "You are Viv, speaking with One Mouth. Summarize only the checks explicitly "
            "present in the verified result. Do not claim broader correctness, source "
            "truth, or successful quality checks beyond those fields."
        )
        user = request["verified_result"]
        schema = None
        max_predict = 512 if phase == "full_rebuild_final" else 180
    else:
        raise ValueError(f"unknown phase: {phase}")

    body = {
        "model": "qwen3:8b-local",
        "stream": False,
        "think": False,
        "keep_alive": "10m",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
        "options": {
            "temperature": 0.3,
            "seed": 42,
            "num_ctx": 8192,
            "num_predict": max_predict,
        },
    }
    if schema is not None:
        body["format"] = schema

    result = call_ollama(body)
    raw = result["message"]["content"]
    print(
        json.dumps(
            {
                "phase": phase,
                "foreman_snapshot_id": foreman["snapshot_id"],
                "request": body,
                "raw": raw,
                "parsed": json.loads(raw) if schema is not None else None,
                "metrics": {
                    key: result.get(key)
                    for key in (
                        "total_duration",
                        "load_duration",
                        "prompt_eval_count",
                        "eval_count",
                        "done_reason",
                    )
                },
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
