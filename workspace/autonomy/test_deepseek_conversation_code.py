"""Prove multi-turn tutor response and recursive Python through the real gates."""
from __future__ import annotations

from datetime import datetime, timezone
import ast
import hashlib
import json
from pathlib import Path
import urllib.request

import viv_code_learning_loop as code_loop

API = "http://127.0.0.1:1234"
LIVE = Path(r"E:\Viv_Sandbox\playground\adapters\epoch_10001")
CANDIDATE = Path(r"F:\LocalCoder_Archive\Viv_model_candidates\epoch_10002")
OUT = Path(__file__).resolve().parent / "learning" / "deepseek_candidate_runs"


def request(path: str, payload: dict | None = None, timeout: int = 240) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(API + path, data=data,
                                 headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_adapter(path: Path) -> dict:
    request("/v1/reload_adapter", {"adapter_dir": str(path)})
    status = request("/v1/status")
    if status.get("status") != "ACTIVE" or status.get("active_adapter") != path.name:
        raise RuntimeError(f"Expected {path.name} active, got {status}")
    return status


def chat(messages: list[dict], *, max_tokens: int) -> tuple[str, str | None]:
    result = request("/v1/chat/completions", {
        "model": "deepseek-coder-6.7b-base", "messages": messages,
        "temperature": 0.0, "max_tokens": max_tokens,
        "stop": ["\nUSER:", "\nSYSTEM:"],
    })
    return result["choices"][0]["message"]["content"].strip(), result.get("active_adapter")


def main() -> int:
    initial = request("/v1/status")
    if initial.get("active_adapter") != LIVE.name or initial.get("status") != "ACTIVE":
        raise RuntimeError(f"Unexpected live state: {initial}")
    if not (CANDIDATE / "adapter_model.safetensors").is_file():
        raise FileNotFoundError(CANDIDATE)

    first_question = "Explain recursion in simple words with a short analogy."
    code_question = "Now write a recursive Python factorial(n) function. No loops. Include a clear base case."
    system = "You are a local coding tutor. Explain clearly and write runnable Python when asked."
    first_answer = ""
    second_answer = ""
    code = ""
    gate_passed = False
    recursion_check = False
    gate_error = ""
    restore = None
    try:
        load_adapter(CANDIDATE)
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": first_question}]
        first_answer, adapter_one = chat(messages, max_tokens=140)
        messages.extend([{"role": "assistant", "content": first_answer},
                         {"role": "user", "content": code_question}])
        second_answer, adapter_two = chat(messages, max_tokens=240)
        code = code_loop.extract_code(second_answer, "python")
        try:
            tree = ast.parse(code)
            fn = next(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                      and n.name == "factorial")
            recursion_check = any(
                isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "factorial"
                for n in ast.walk(fn)
            )
        except (SyntaxError, StopIteration):
            recursion_check = False
        tests = (
            "assert factorial(0) == 1\n"
            "assert factorial(1) == 1\n"
            "assert factorial(5) == 120\n"
            "assert factorial(10) == 3628800"
        )
        if code:
            gate_passed, gate_error = code_loop.gate_python(code, tests)
        if adapter_one != CANDIDATE.name or adapter_two != CANDIDATE.name:
            raise RuntimeError(f"Chat used unexpected adapter: {adapter_one}, {adapter_two}")
    finally:
        restore = load_adapter(LIVE)

    passed = bool(first_answer and recursion_check and gate_passed and
                  restore.get("active_adapter") == LIVE.name)
    receipt = {
        "schema": "viv_deepseek_multiturn_recursive_python_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "initial_live_state": initial,
        "candidate_adapter": str(CANDIDATE),
        "candidate_adapter_sha256": sha(CANDIDATE / "adapter_model.safetensors"),
        "conversation": [
            {"user": first_question, "assistant": first_answer},
            {"user": code_question, "assistant": second_answer},
        ],
        "extracted_code": code,
        "recursive_call_present": recursion_check,
        "docker_gate_passed": gate_passed,
        "gate_error": gate_error,
        "restored_live_state": restore,
        "passed": passed,
        "promoted": False,
    }
    receipt["receipt_sha256"] = hashlib.sha256(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"conversation_code_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"receipt": str(path), "passed": passed,
                      "recursive_call_present": recursion_check,
                      "docker_gate_passed": gate_passed,
                      "active_adapter_restored": restore.get("active_adapter")},
                     ensure_ascii=False, indent=2), flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
