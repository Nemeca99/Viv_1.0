"""Score a frozen held-out coding suite through the existing deterministic gates."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import ast
import re
import os
from pathlib import Path
import sys
import urllib.request

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import viv_code_learning_loop as gates

API = "http://127.0.0.1:1234"
LIVE = Path(r"E:\Viv_Sandbox\playground\adapters\epoch_10001")
CANDIDATE = Path(os.environ.get("VIV_CODE_CANDIDATE", r"F:\LocalCoder_Archive\Viv_model_candidates\epoch_10002"))
SUITE = HERE / "learning" / "deepseek_candidate_runs" / "frozen_code_eval_v1.json"
OUT_DIR = HERE / "learning" / "deepseek_candidate_runs"
MAX_NEW_TOKENS = 320


def request(path: str, payload: dict | None = None, timeout: int = 180) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(API + path, data=data,
                                 headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def activate(adapter: Path) -> dict:
    request("/v1/reload_adapter", {"adapter_dir": str(adapter)})
    status = request("/v1/status")
    if status.get("status") != "ACTIVE" or status.get("active_adapter") != adapter.name:
        raise RuntimeError(f"adapter load failed: {status}")
    return status


def extract_requested_function(raw: str, lang: str, spec: str) -> str:
    """Extract only the requested complete function, excluding model-added tests."""
    match = re.search(r"(?:def|pub\s+fn)\s+([A-Za-z_]\w*)\s*\(", spec)
    if not match:
        return ""
    name = match.group(1)
    fenced = re.search(r"```(?:rust|rs|python|py)?\s*\n(.*?)```", raw, re.S)
    text = fenced.group(1) if fenced else raw
    if lang == "python":
        lines = text.strip().splitlines()
        start = next((i for i, line in enumerate(lines)
                      if re.match(rf"^\s*def\s+{re.escape(name)}\s*\(", line)), None)
        if start is None:
            return ""
        base_indent = len(lines[start]) - len(lines[start].lstrip())
        end = start + 1
        while end < len(lines):
            line = lines[end]
            if not line.strip():
                end += 1
                continue
            indent = len(line) - len(line.lstrip())
            if indent <= base_indent:
                break
            end += 1
        block = lines[start:end]
        while block and not block[-1].strip():
            block.pop()
        chunk = "\n".join(block).strip()
        try:
            tree = ast.parse(chunk)
        except SyntaxError:
            return ""
        fn = next((node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and node.name == name), None)
        if fn is None:
            return ""
        return "\n".join(chunk.splitlines()[fn.lineno - 1:fn.end_lineno])

    for declaration in re.finditer(rf"\b(?:pub\s+)?fn\s+{re.escape(name)}\s*\(", text):
        opening = text.find("{", declaration.end())
        if opening < 0:
            continue
        depth = 0
        in_string = in_char = escaped = line_comment = block_comment = False
        i = opening
        while i < len(text):
            ch = text[i]
            nxt = text[i + 1] if i + 1 < len(text) else ""
            if line_comment:
                if ch == "\n":
                    line_comment = False
            elif block_comment:
                if ch == "*" and nxt == "/":
                    block_comment = False
                    i += 1
            elif in_string or in_char:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif (in_string and ch == '"') or (in_char and ch == "'"):
                    in_string = in_char = False
            elif ch == "/" and nxt == "/":
                line_comment = True
                i += 1
            elif ch == "/" and nxt == "*":
                block_comment = True
                i += 1
            elif ch == '"':
                in_string = True
            elif ch == "'":
                end_char = i + 1 + (2 if i + 1 < len(text) and text[i + 1] == "\\" else 1)
                if end_char < len(text) and text[end_char] == "'":
                    in_char = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[declaration.start():i + 1].strip()
            i += 1
    return ""


def evaluate(task: dict) -> dict:
    prompt = (
        f"SYSTEM: Write one correct, standard-library {task['lang']} implementation. "
        "Return only one fenced code block containing the requested function. No examples, tests, or explanation.\n\n"
        f"USER: Implement: {task['spec']}\n\nASSISTANT:"
    )
    try:
        response = request("/v1/completions", {
            "model": "deepseek-coder-6.7b-base", "prompt": prompt,
            "max_tokens": MAX_NEW_TOKENS, "temperature": 0.0,
            "stop": ["\nUSER:", "\nSYSTEM:", "\n// Test code", "\n# Test code", "\nfn main()"],
        })
        raw = response["choices"][0]["text"]
        code = extract_requested_function(raw, task["lang"], task["spec"])
        if not code:
            return {"task": task["id"], "lang": task["lang"], "passed": False,
                    "error": "NO_CODE", "code": "", "raw_output": raw}
        gate = gates.gate_python if task["lang"] == "python" else gates.gate_rust
        passed, error = gate(code, task["tests"])
        return {"task": task["id"], "lang": task["lang"], "passed": bool(passed),
                "error": error[:4000], "code": code, "raw_output": raw}
    except Exception as exc:
        return {"task": task["id"], "lang": task["lang"], "passed": False,
                "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    suite_payload = json.loads(SUITE.read_text(encoding="utf-8"))
    digest = suite_payload.pop("suite_sha256")
    canonical = json.dumps(suite_payload, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode("utf-8")
    if hashlib.sha256(canonical).hexdigest() != digest:
        raise ValueError("frozen suite hash mismatch")
    selected_langs = {item.strip().casefold() for item in os.environ.get("VIV_EVAL_LANGS", "python,rust").split(",") if item.strip()}
    suite_payload["held_out"] = [task for task in suite_payload["held_out"] if task["lang"] in selected_langs]
    initial = request("/v1/status")
    if initial.get("status") != "ACTIVE" or initial.get("active_adapter") != LIVE.name:
        raise RuntimeError(f"unexpected initial live adapter: {initial}")
    results = []
    restored = None
    try:
        activate(CANDIDATE)
        for index, task in enumerate(suite_payload["held_out"], 1):
            result = evaluate(task)
            results.append(result)
            print(json.dumps({"index": index, "total": len(suite_payload["held_out"]),
                              "task": result["task"], "lang": result["lang"],
                              "passed": result["passed"], "error": result.get("error", "")[:300]},
                             ensure_ascii=False), flush=True)
    finally:
        restored = activate(LIVE)

    summaries = {}
    for lang in ("python", "rust"):
        rows = [row for row in results if row["lang"] == lang]
        summaries[lang] = {"passed": sum(row["passed"] for row in rows), "total": len(rows)}
    output = {
        "schema": "viv_frozen_candidate_code_eval_result_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "suite_path": str(SUITE), "suite_sha256": digest,
        "generation_max_tokens": MAX_NEW_TOKENS, "requested_function_only": True,
        "adapter_path": str(CANDIDATE), "adapter_sha256": hashlib.sha256(
            (CANDIDATE / "adapter_model.safetensors").read_bytes()).hexdigest(),
        "live_adapter_before": initial, "live_adapter_restored": restored,
        "by_language": summaries, "results": results, "promoted": False,
    }
    output["receipt_sha256"] = hashlib.sha256(
        json.dumps(output, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"frozen_eval_v1_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"receipt": str(path), "by_language": summaries,
                      "active_adapter_restored": restored.get("active_adapter"), "promoted": False}, indent=2))
    return 0 if len(results) == len(suite_payload["held_out"]) and restored.get("active_adapter") == LIVE.name else 1


if __name__ == "__main__":
    raise SystemExit(main())
