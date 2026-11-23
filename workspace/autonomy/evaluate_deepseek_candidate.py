"""Compare the isolated DeepSeek candidate to its parent and restore the parent."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
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

import viv_code_learning_loop as code_loop
import viv_python_curriculum as python_curriculum
from viv_alu_transducer import transduce_digits_in_spec
from viv_reference_examples import STUDY

API = "http://127.0.0.1:1234"
PARENT = Path(os.environ.get("VIV_PARENT_ADAPTER", r"E:\Viv_Sandbox\playground\adapters\epoch_10001"))
CANDIDATE = Path(os.environ.get("VIV_CANDIDATE_ADAPTER", r"F:\LocalCoder_Archive\Viv_model_candidates\epoch_10002"))
RESTORE_ADAPTER = Path(os.environ.get("VIV_RESTORE_ADAPTER", r"E:\Viv_Sandbox\playground\adapters\epoch_10001"))
TASK_IDS = tuple(x for x in os.environ.get(
    "VIV_CANDIDATE_TASKS", "py_dedupe,py_is_palindrome,rs_fib,rs_reverse"
).split(",") if x)
OUT_DIR = HERE / "learning" / "deepseek_candidate_runs"


def _request(path: str, payload: dict | None = None, timeout: int = 240) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(API + path, data=data,
                                 headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _receipt_sha(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _tasks() -> list[dict]:
    tasks = {row["id"]: dict(row) for row in code_loop.CURRICULUM}
    tasks.update({row["id"]: dict(row) for row in python_curriculum.TASKS})
    tasks.update({
        "py_pairwise_differences": {
            "id": "py_pairwise_differences", "lang": "python",
            "spec": "def pairwise_differences(xs: list[int]) -> list[int]: return each next value minus the previous value",
            "tests": "assert pairwise_differences([2, 5, 9]) == [3, 4]\nassert pairwise_differences([]) == []\nassert pairwise_differences([7]) == []\nassert pairwise_differences([5, 1, 1]) == [-4, 0]",
        },
        "rs_gcd": {
            "id": "rs_gcd", "lang": "rust",
            "spec": "pub fn gcd(a: u64, b: u64) -> u64: greatest common divisor; gcd(a, 0) equals a",
            "tests": "#[cfg(test)] mod t { use super::*; #[test] fn a(){ assert_eq!(gcd(12,18),6); assert_eq!(gcd(7,0),7); assert_eq!(gcd(0,0),0); assert_eq!(gcd(17,5),1); } }",
        },
    })
    return [tasks[task_id] for task_id in TASK_IDS]


def _evaluate(adapter: str) -> list[dict]:
    results = []
    for task in _tasks():
        try:
            language = task["lang"]
            system = (f"You write clean, standard-library {language} code (do NOT import third-party "
                      "packages like numpy). Reply with ONLY one fenced code block containing the "
                      "implementation. No tests, no main, no explanation.")
            user = f"Implement: {transduce_digits_in_spec(task['spec'])}"
            if language == "python":
                user += ("\n(ALU word-number constants ZERO, ONE, TWO, THREE, FOUR, FIVE, SIX, "
                         "SEVEN, EIGHT, NINE, TEN, TWELVE, FIFTEEN, TWENTY, HUNDRED are also available.)")
            examples = list(STUDY.get(language, []))
            if examples:
                user += "\n\nVerified examples of your earlier work:\n" + "\n---\n".join(examples[-2:])
            prompt = f"SYSTEM: {system}\n\nUSER: {user}\n\nASSISTANT:"
            response = _request("/v1/completions", {
                "model": "deepseek-coder-6.7b-base", "prompt": prompt,
                "max_tokens": 256, "temperature": 0.0,
                "stop": ["\nUSER:", "\nSYSTEM:"],
            })
            raw = response["choices"][0]["text"]
            implementation = code_loop.extract_code(raw, task["lang"])
            if not implementation:
                passed, error = False, "NO_CODE_BLOCK"
            else:
                gate = code_loop.gate_python if task["lang"] == "python" else code_loop.gate_rust
                passed, error = gate(implementation, task["tests"])
            result = {"task": task["id"], "lang": task["lang"], "adapter": adapter,
                      "role": "trained_retention" if task["id"] == "py_dedupe" else "held_out",
                      "passed": passed, "error": error[:2000], "code": implementation,
                      "raw_output": raw}
        except Exception as exc:
            result = {"task": task["id"], "lang": task["lang"], "adapter": adapter,
                      "role": "trained_retention" if task["id"] == "py_dedupe" else "held_out",
                      "passed": False, "error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps({"eval": result}, ensure_ascii=False), flush=True)
        results.append(result)
    return results


def _evaluate_fact(adapter: str) -> list[dict]:
    questions = [
        "What is the serial label for the fictional Vesper device?",
        "Which unique identifier belongs to Vesper?",
    ]
    results = []
    for question in questions:
        response = _request("/v1/chat/completions", {
            "model": "deepseek-coder-6.7b-base",
            "messages": [
                {"role": "system", "content": "Answer the question directly in one short sentence."},
                {"role": "user", "content": question},
            ],
            "temperature": 0.0, "max_tokens": 80,
        })
        answer = response["choices"][0]["message"]["content"].strip()
        result = {"adapter": adapter, "question": question, "answer": answer,
                  "learned_fact_recalled": "brindle-qat-731" in answer.casefold()}
        results.append(result)
        print(json.dumps({"fact_eval": result}, ensure_ascii=False), flush=True)
    return results


def _activate(path: Path) -> dict:
    response = _request("/v1/reload_adapter", {"adapter_dir": str(path)})
    status = _request("/v1/status")
    if status.get("status") != "ACTIVE" or status.get("active_adapter") != path.name:
        raise RuntimeError(f"Expected {path.name} active, got {status}; response={response}")
    return status


def main() -> int:
    if not (CANDIDATE / "adapter_model.safetensors").is_file():
        raise FileNotFoundError(CANDIDATE)
    initial = _request("/v1/status")
    if initial.get("status") != "ACTIVE" or initial.get("active_adapter") != RESTORE_ADAPTER.name:
        raise RuntimeError(f"Unexpected live model state: {initial}")

    baseline, candidate, baseline_fact, fact_results = [], [], [], []
    candidate, restore, swap_error = [], None, None
    try:
        print(json.dumps({"phase": "load_parent_candidate", "path": str(PARENT)}), flush=True)
        _activate(PARENT)
        baseline = _evaluate(PARENT.name)
        baseline_fact = _evaluate_fact(PARENT.name)
        print(json.dumps({"phase": "load_candidate", "path": str(CANDIDATE)}), flush=True)
        _activate(CANDIDATE)
        candidate = _evaluate(CANDIDATE.name)
        fact_results = _evaluate_fact(CANDIDATE.name)
    except Exception as exc:
        swap_error = f"{type(exc).__name__}: {exc}"
        print(json.dumps({"candidate_error": swap_error}), flush=True)
    finally:
        try:
            restore = _activate(RESTORE_ADAPTER)
        except Exception as exc:
            restore = {"status": "RESTORE_FAILED", "error": f"{type(exc).__name__}: {exc}"}
            print(json.dumps({"restore_error": restore}), flush=True)

    status_ok = bool(restore and restore.get("status") == "ACTIVE"
                     and restore.get("active_adapter") == RESTORE_ADAPTER.name)
    training_receipts = Path(r"F:\LocalCoder_Archive\Viv_model_candidates\training_receipts.jsonl")
    training = json.loads(training_receipts.read_text(encoding="utf-8").splitlines()[-1])
    payload = {
        "schema": "viv_deepseek_candidate_comparison_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "live_adapter_initial": initial,
        "parent_adapter_path": str(PARENT),
        "parent_adapter_sha256": _sha(PARENT / "adapter_model.safetensors"),
        "candidate_adapter_path": str(CANDIDATE),
        "candidate_adapter_sha256": _sha(CANDIDATE / "adapter_model.safetensors"),
        "training": training,
        "held_out_tasks": list(TASK_IDS),
        "baseline": baseline,
        "candidate": candidate,
        "fact_recall": {"parent": baseline_fact, "candidate": fact_results},
        "candidate_swap_error": swap_error,
        "live_adapter_restored": restore,
        "promoted": False,
    }
    payload["receipt_sha256"] = _receipt_sha(payload)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"comparison_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        "receipt": str(path),
        "baseline_passed": sum(item.get("passed", False) for item in baseline),
        "baseline_total": len(baseline),
        "candidate_passed": sum(item.get("passed", False) for item in candidate),
        "candidate_total": len(candidate),
        "fact_recalled": sum(item.get("learned_fact_recalled", False) for item in fact_results),
        "parent_fact_recalled": sum(item.get("learned_fact_recalled", False) for item in baseline_fact),
        "candidate_swap_error": swap_error,
        "live_adapter_restored": status_ok, "active_adapter": restore.get("active_adapter") if restore else None,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0 if status_ok and len(candidate) == len(TASK_IDS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
