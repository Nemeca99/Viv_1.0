"""Bounded diagnostic: mock four tool responses and observe local-model continuation."""

from __future__ import annotations

import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(r"L:\LocalCoder")
OUTPUT = ROOT / ".opencode" / "evals" / f"lmstudio-tool-loop-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}.jsonl"
ADDRESS = subprocess.check_output(
    ["powershell.exe", "-NoProfile", "-Command", "(Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias Ethernet | Where-Object IPAddress -notlike '169.254*' | Select-Object -First 1).IPAddress"],
    text=True,
).strip()
MODEL = "qwen2.5-coder-7b-instruct"
TOOLS = [
    {"type": "function", "function": {"name": "read", "description": "Read one fixture", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "edit", "description": "Edit one fixture", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "oldString": {"type": "string"}, "newString": {"type": "string"}}, "required": ["path", "oldString", "newString"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "shell", "description": "Run the fixture verifier", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"], "additionalProperties": False}}},
]
MESSAGES = [
    {"role": "system", "content": "Use the tool interface only. Follow this ordered sequence: read fixture A; edit fixture A; edit fixture B; run shell verifier. After each tool result, continue with the next tool. Do not claim any tool ran; results in this diagnostic are explicitly mocked."},
    {"role": "user", "content": "Complete a multi-file coding task. Read .opencode/evals/agent_multifile_probe_a.py, infer the normalization from its assertion, edit its return line to value.strip().lower(), then edit .opencode/evals/agent_multifile_probe_b.py to count non-empty lines. Finally run L:\\LocalCoder\\.opencode\\evals\\verify_agent_multifile_probe.py."},
]
MOCK_RESULTS = {
    "read": "MOCK ONLY: def normalize_label(value): return value  # placeholder; assertion requires normalize_label('  LOCAL CODER  ') == 'local coder'.",
    "edit": "MOCK ONLY: exact replacement completed successfully.",
    "shell": "MOCK ONLY: verifier printed PASS for both fixture files.",
}


def proposed_call(content: str | None) -> dict | None:
    if not content:
        return None
    candidates = [match.group(1) for match in re.finditer(r"```json\s*\n?(.*?)\n?```", content, re.IGNORECASE | re.DOTALL)]
    candidates.append(content)
    for candidate in candidates:
        for match in re.finditer(r"\{", candidate):
            try:
                value, _ = json.JSONDecoder().raw_decode(candidate[match.start():])
            except json.JSONDecodeError:
                continue
            name = value.get("name") if isinstance(value, dict) else None
            arguments = value.get("arguments") if isinstance(value, dict) else None
            if name in {tool["function"]["name"] for tool in TOOLS} and isinstance(arguments, dict):
                return {"name": name, "arguments": arguments}
    return None


def request() -> dict:
    payload = json.dumps({"model": MODEL, "messages": MESSAGES, "tools": TOOLS, "tool_choice": "required", "temperature": 0, "max_tokens": 512}).encode()
    req = urllib.request.Request(f"http://{ADDRESS}:1234/v1/chat/completions", data=payload, headers={"Content-Type": "application/json"})
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=180) as response:
            data = json.loads(response.read())
            status = response.status
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"LM Studio returned HTTP {error.code}; response body omitted") from None
    elapsed = round(time.perf_counter() - started, 3)
    choice = data["choices"][0]
    message = choice["message"]
    calls = message.get("tool_calls") or []
    if not calls:
        proposed = proposed_call(message.get("content"))
        if proposed:
            calls = [{"id": f"mock-call-{len([item for item in MESSAGES if item.get('role') == 'assistant']) + 1}", "type": "function", "function": {"name": proposed["name"], "arguments": json.dumps(proposed["arguments"])}}]
    MESSAGES.append({"role": "assistant", "tool_calls": calls} if calls else message)
    record = {
        "turn": sum(1 for item in MESSAGES if item.get("role") == "assistant"),
        "http_status": status,
        "elapsed_seconds": elapsed,
        "finish_reason": choice.get("finish_reason"),
        "content_chars": len(message.get("content") or ""),
        "content": message.get("content"),
        "tool_calls": [{"id": call.get("id"), "name": call.get("function", {}).get("name"), "arguments": call.get("function", {}).get("arguments")} for call in calls],
        "usage": data.get("usage"),
    }
    with OUTPUT.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(json.dumps(record, ensure_ascii=False))
    if calls and len([item for item in MESSAGES if item.get("role") == "tool"]) < 3:
        for call in calls:
            tool_name = call.get("function", {}).get("name")
            MESSAGES.append({"role": "tool", "tool_call_id": call.get("id"), "content": MOCK_RESULTS.get(tool_name, "MOCK ONLY: unsupported tool response.")})
    return {"calls": calls, "finish_reason": choice.get("finish_reason"), "content": message.get("content")}


for _ in range(4):
    outcome = request()
    if not outcome["calls"]:
        break
print(f"TRACE_FILE={OUTPUT}")
