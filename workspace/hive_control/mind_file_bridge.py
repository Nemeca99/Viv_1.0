"""Data-only transport for the vague-goal Hive probe."""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hive_foreman_memory import load_latest, routing_packet  # noqa: E402


def main() -> None:
    request = json.load(sys.stdin)
    foreman = routing_packet(load_latest())
    if request["phase"] == "plan":
        profile = request.get("capability_profile", "default")
        if profile not in ("default", "function_only"):
            raise ValueError("unknown capability profile")
        system = (
            "You are Viv, the Hive Mind. Interpret the user's deliberately vague goal. "
            "Choose a concrete small Python file behavior, filename, task graph, dependencies, "
            "and text variables. Use only the listed Rust Swarm capabilities. "
            "Each task is one action; Rust workers do the actions. Return JSON only. "
            "Do not claim any action has happened yet."
        )
        capabilities = [
            {
                "name": "create_file",
                "effect": "Create an empty Python file in the isolated run directory",
            },
            {
                "name": "stamp_function",
                "effect": "Append a function named perform that prints this task's value",
            },
            {"name": "stamp_call", "effect": "Append a guarded call to perform"},
            {"name": "run_file", "effect": "Run the Python file and capture stdout"},
        ]
        if profile == "default":
            capabilities.insert(
                1,
                {
                    "name": "stamp_print",
                    "effect": "Append a print statement using this task's value as a string literal",
                },
            )
        user = {
            "goal": request["goal"],
            "foreman": foreman,
            "capabilities": capabilities,
            "bounds": "Choose 3 to 5 tasks; create before stamps, run after stamps. Any stamps sharing the file must be ordered by dependencies. Use a short .py filename and printable one-line values.",
        }
        schema = {
            "type": "object",
            "properties": {
                "filename": {"type": "string"},
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
                                    "create_file",
                                    "stamp_print",
                                    "stamp_function",
                                    "stamp_call",
                                    "run_file",
                                ],
                            },
                            "objective": {"type": "string"},
                            "depends_on": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "value": {"type": "string"},
                        },
                        "required": [
                            "id",
                            "capability",
                            "objective",
                            "depends_on",
                            "value",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["filename", "intent", "tasks"],
            "additionalProperties": False,
        }
        max_predict = 850
    elif request["phase"] == "final":
        system = "You are Viv. Describe only the verified result in one or two plain sentences."
        user = request["verified_result"]
        schema = None
        max_predict = 120
    else:
        raise ValueError("unknown phase")
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
            "temperature": 0.4,
            "seed": 42,
            "num_ctx": 8192,
            "num_predict": max_predict,
        },
    }
    if schema is not None:
        body["format"] = schema
    http = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(http, timeout=300) as response:
        result = json.load(response)
    raw = result["message"]["content"]
    print(
        json.dumps(
            {
                "phase": request["phase"],
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
