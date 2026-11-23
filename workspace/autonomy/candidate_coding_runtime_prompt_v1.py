"""Candidate-only coding runtime: propose, deterministically gate, retain every attempt.

This module intentionally does not call the live learning loop's store_verified()
or mutate topology.  Adapter use is temporary; the prior live adapter is restored
before the immutable run receipt is written.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.request
import uuid

import evaluate_frozen_candidate_code_v1 as evaluator
from candidate_uml_grounding_v1 import UML_ENGINE_PATH, context_for_task as uml_context_for_task
import viv_code_learning_loop as gates

HERE = Path(__file__).resolve().parent
RUNS = HERE / "learning" / "deepseek_candidate_runs"
API = os.environ.get("VIV_CANDIDATE_API", "http://127.0.0.1:1234")
LIVE = Path(os.environ.get("VIV_CANDIDATE_LIVE_ADAPTER", r"E:\Viv_Sandbox\playground\adapters\epoch_10001"))
DEFAULT_CANDIDATE = Path(os.environ.get("VIV_CODE_CANDIDATE", r"F:\LocalCoder_Archive\Viv_model_candidates\epoch_10008"))
MAX_ATTEMPTS = 3
GENERATION_TEMPERATURE = 0.0  # Tutor server maps this to greedy decoding (do_sample=False).


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical_hash(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def rust_signature(spec: str) -> tuple[str, str] | None:
    match = re.search(r"pub\s+fn\s+[A-Za-z_]\w*\s*\(", spec)
    if not match:
        return None
    paren = spec.find("(", match.start())
    depth = 0
    close = -1
    for index in range(paren, len(spec)):
        if spec[index] == "(":
            depth += 1
        elif spec[index] == ")":
            depth -= 1
            if depth == 0:
                close = index
                break
    colon = spec.find(":", close + 1)
    if close < 0 or colon < 0:
        return None
    return spec[:colon].strip() + " {", spec[colon + 1:].strip()


def request_completion(prompt: str, temperature: float) -> str:
    payload = {"model": "deepseek-coder-6.7b-base", "prompt": prompt,
               "max_tokens": 384, "temperature": temperature,
               "stop": ["\n#[cfg(test)]", "\n# Test code", "\n// Test code", "\nfn main()"]}
    req = urllib.request.Request(API + "/v1/completions", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=240) as response:
        return json.load(response)["choices"][0]["text"]


def proposal(task: dict, attempt: int, previous: dict | None,
             uml_grounding: dict | None = None) -> tuple[str, str, str]:
    lang = task["lang"]
    spec = task["spec"]
    grounding = uml_grounding if uml_grounding is not None else uml_context_for_task(task)
    context = grounding.get("prompt_context", "")
    if lang == "rust":
        parsed = rust_signature(spec)
        if not parsed:
            raise ValueError("RUST_SIGNATURE_PARSE_FAILED")
        header, description = parsed
        feedback = ""
        if previous:
            test_comments = "\n".join("# " + line for line in task["tests"].splitlines())
            feedback = ("# Last candidate body:\n" + "\n".join("# " + line for line in previous["raw"].splitlines())
                        + "\n# Deterministic Rust gate output:\n"
                        + "\n".join("# " + line for line in previous["error"][:3000].splitlines())
                        + "\n# Deterministic test cases that must pass:\n" + test_comments
                        + "\n# Correct the reported error. Return a complete function body.\n")
        uml_note = "" if not context else "# Deterministic UML reference:\n" + "\n".join(
            "# " + line for line in context.splitlines()) + "\n"
        prompt = ("# Implement one self-contained, correct standard-library Rust function. Do not depend on other top-level helpers. "
                  "Handle empty and boundary inputs.\n"
                  f"{uml_note}# Task: {description}\n{feedback}{header}\n")
        raw = request_completion(prompt, GENERATION_TEMPERATURE)
        full = header + raw
    else:
        feedback = ""
        if previous:
            tests = task["tests"]
            feedback = ("\n\nThe previous implementation failed the deterministic tests.\n"
                        f"Gate output:\n{previous['error'][:3000]}\n"
                        f"Deterministic tests to pass:\n{tests}\n"
                        "Correct the failure. Implement this as one self-contained function with no dependency on other top-level helpers. "
                        "Return the complete requested function only.\n")
        uml_note = "" if not context else "\n".join("# " + line for line in context.splitlines()) + "\n"
        retry_note = ""
        if feedback:
            retry_note = "\n".join("# " + line for line in feedback.splitlines()) + "\n"
        # Base-model completion prompt: code comments and task text, no chat-role
        # markers and no instruction to emit markdown fences.
        prompt = ("# Write one self-contained, correct, standard-library Python function. "
                  "Do not depend on other top-level helpers.\n"
                  "# Task: " + spec + "\n" + uml_note + retry_note)
        raw = request_completion(prompt, GENERATION_TEMPERATURE)
        full = raw
    code = evaluator.extract_requested_function(full, lang, spec)
    return raw, code, header if lang == "rust" else ""


def run_task(task: dict, candidate: Path = DEFAULT_CANDIDATE) -> dict:
    gate = gates.gate_python if task["lang"] == "python" else gates.gate_rust
    attempts = []
    previous = None
    uml_grounding = uml_context_for_task(task)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        raw, code, header = proposal(task, attempt, previous, uml_grounding)
        if not code:
            ok, error = False, "NO_COMPLETE_REQUESTED_FUNCTION"
        else:
            ok, error = gate(code, task["tests"])
        row = {"attempt": attempt, "passed": bool(ok), "error": error[:4000],
               "raw_output": raw, "code": code, "signature_prefix": header,
               "uml_grounding": uml_grounding}
        attempts.append(row)
        print(json.dumps({"task": task["id"], "language": task["lang"], "attempt": attempt,
                          "passed": bool(ok), "gate": error[:180]}, ensure_ascii=False), flush=True)
        if ok:
            break
        previous = {"raw": raw, "error": error}
    return {"task": task["id"], "lang": task["lang"], "first_pass": attempts[0]["passed"],
            "final_pass": attempts[-1]["passed"], "uml_grounding": uml_grounding,
            "attempts": attempts}


def run_suite(suite_path: Path, candidate: Path = DEFAULT_CANDIDATE) -> Path:
    envelope = json.loads(suite_path.read_text(encoding="utf-8"))
    expected = envelope.pop("suite_sha256", None)
    if expected != canonical_hash(envelope):
        raise ValueError("FROZEN_SUITE_HASH_MISMATCH")
    before = evaluator.request("/v1/status")
    if before.get("status") != "ACTIVE" or before.get("active_adapter") != LIVE.name:
        raise RuntimeError("UNEXPECTED_LIVE_ADAPTER: " + json.dumps(before))
    adapter_hash = sha256(candidate / "adapter_model.safetensors")
    results = []
    restored = None
    try:
        evaluator.activate(candidate)
        for task in envelope["held_out"]:
            results.append(run_task(task, candidate))
    finally:
        restored = evaluator.activate(LIVE)
    by_language = {}
    for lang in ("python", "rust"):
        rows = [row for row in results if row["lang"] == lang]
        by_language[lang] = {"first_pass": sum(row["first_pass"] for row in rows),
                             "final_pass": sum(row["final_pass"] for row in rows), "total": len(rows)}
    receipt = {"schema": "viv_candidate_coding_runtime_v1", "created_utc": datetime.now(timezone.utc).isoformat(),
               "suite_path": str(suite_path), "suite_sha256": expected,
               "candidate_path": str(candidate), "candidate_sha256": adapter_hash,
               "runtime_script_sha256": sha256(Path(__file__).resolve()),
               "uml_engine_path": str(UML_ENGINE_PATH),
               "uml_engine_sha256": sha256(UML_ENGINE_PATH),
               "uml_grounding_contract": "UML_Calc results are read-only proposal context; deterministic language gates still decide acceptance",
               "prompt_contract": "Python completion-style comments without chat-role markers or markdown request; Rust prompt unchanged; retries include deterministic tests and exact gate output",
               "generation": {"temperature": GENERATION_TEMPERATURE, "do_sample": False},
               "attempt_limit": MAX_ATTEMPTS, "by_language": by_language, "results": results,
               "live_before": before, "live_restored": restored, "promoted": False,
               "topology_write": False, "persistent_memory_write": False}
    receipt["receipt_sha256"] = canonical_hash(receipt)
    RUNS.mkdir(parents=True, exist_ok=True)
    target = RUNS / (f"candidate_runtime_v1_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
                     f"_{uuid.uuid4().hex[:8]}.json")
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"receipt": str(target), "by_language": by_language,
                      "live_restored": restored.get("active_adapter"), "promoted": False}, indent=2), flush=True)
    return target


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("suite", type=Path)
    parser.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    args = parser.parse_args()
    run_suite(args.suite, args.candidate)
