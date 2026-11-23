"""Viv's reasoning loop: Rust injects facts, the model reasons, answers in English.

The model holds no knowledge of its own. Every fact it reasons over comes from
the Rust system, injected into the prompt as context. The model's only job is to
reason about what to do with that information and say it in English.

Usage:
  python viv_reason.py --context-file <rust-facts.json> --query "what should I do"
The context file is produced by the Rust system (receipts, task state, hashes).
Thinking mode is disabled: the model reasons straight to the answer.
"""
from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

SERVED_MODEL = "L:/LocalCoder/models/qwen3-8b-q4_k_m.gguf"
URL = "http://127.0.0.1:1235/v1/chat/completions"

VIV = (
    "Your name is Viv. You are the local AIOS coding agent. "
    "You serve in the Drone role under the human Architect. "
    "You are not Qwen and not Alibaba Cloud. "
    "You hold no knowledge of your own: every fact you reason over is in the prompt, "
    "supplied by the Rust system. Reason about only that information. "
    "Answer directly and briefly, in plain English."
)


def reason(context: str, query: str, model: str = SERVED_MODEL) -> str:
    payload = {
        "model": model,
        "temperature": 0.2,
        "max_tokens": 400,
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [
            {"role": "system", "content": VIV},
            {"role": "user", "content": f"Facts from the Rust system:\n{context}\n\nQuestion: {query}"},
        ],
    }
    req = urllib.request.Request(
        URL, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    out = json.loads(urllib.request.urlopen(req, timeout=180).read())
    msg = out["choices"][0]["message"]
    return msg.get("content", "").strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--context-file", type=Path, required=True)
    ap.add_argument("--query", required=True)
    args = ap.parse_args()

    context = args.context_file.read_text(encoding="utf-8", errors="replace")
    answer = reason(context, args.query)
    print(json.dumps({"context_file": str(args.context_file), "query": args.query,
                      "answer": answer}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
