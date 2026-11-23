"""Probe trained fact examples using the exact completion format used in SFT."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.request

API = "http://127.0.0.1:1234"
LIVE = Path(r"E:\Viv_Sandbox\playground\adapters\epoch_10001")
PARENT = Path(r"F:\LocalCoder_Archive\Viv_model_candidates\epoch_10002")
CANDIDATE = Path(r"F:\LocalCoder_Archive\Viv_model_candidates\epoch_10004")
OUT = Path(__file__).resolve().parent / "learning" / "deepseek_candidate_runs"
QUERIES = [
    "What is the serial label for the fictional Vesper device?",
    "Which unique identifier belongs to Vesper?",
    "Tell me Vesper's serial label.",
]


def request(path: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(API + path, data=data,
                                 headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=180) as response:
        return json.load(response)


def activate(adapter: Path) -> dict:
    request("/v1/reload_adapter", {"adapter_dir": str(adapter)})
    status = request("/v1/status")
    if status.get("status") != "ACTIVE" or status.get("active_adapter") != adapter.name:
        raise RuntimeError(f"adapter load failed: {status}")
    return status


def ask(adapter: Path, question: str) -> dict:
    prompt = f"USER: {question}\n\nASSISTANT:\n"
    response = request("/v1/completions", {
        "model": "deepseek-coder-6.7b-base", "prompt": prompt,
        "max_tokens": 48, "temperature": 0.0,
        "stop": ["\nUSER:", "\nSYSTEM:"],
    })
    answer = response["choices"][0]["text"].strip()
    return {"adapter": adapter.name, "question": question, "answer": answer,
            "fact_exactly_recalled": "brindle-qat-731" in answer.casefold()}


def main() -> int:
    initial = request("/v1/status")
    if initial.get("status") != "ACTIVE" or initial.get("active_adapter") != LIVE.name:
        raise RuntimeError(f"unexpected initial tutor: {initial}")
    results = {}
    restore = None
    try:
        for adapter in (PARENT, CANDIDATE):
            activate(adapter)
            results[adapter.name] = [ask(adapter, question) for question in QUERIES]
            for row in results[adapter.name]:
                print(json.dumps(row, ensure_ascii=False), flush=True)
    finally:
        restore = activate(LIVE)
    receipt = {
        "schema": "viv_deepseek_fact_completion_probe_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "initial_live_state": initial,
        "sft_prompt_format": "USER: question\\n\\nASSISTANT:\\n",
        "parent": str(PARENT), "candidate": str(CANDIDATE),
        "results": results, "restored_live_state": restore, "promoted": False,
    }
    raw = json.dumps(receipt, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    receipt["receipt_sha256"] = hashlib.sha256(raw).hexdigest()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"fact_completion_probe_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"receipt": str(path), "restored": restore}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
