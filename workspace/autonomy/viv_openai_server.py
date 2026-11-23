"""OpenAI-compatible bridge for Viv's local checkpoint.

LM Studio cannot load the raw PyTorch checkpoint. This server exposes the
checkpoint through the same /v1 API shape OpenCode already uses, so a provider
entry can point at it:

  "viv-local": {
    "settings": { "baseURL": "http://127.0.0.1:8001/v1" },
    "models": { "viv-1.0-319m": { "name": "Viv 1.0 319M (local)" } }
  }

The voice goes through the turn policy and safety gate; the harness supplies the
tools. A 319M checkpoint is a dialogue voice, not a reliable tool-caller yet.
"""
import argparse
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import torch

sys.path.insert(0, "L:/LocalCoder/workspace/autonomy")
sys.path.insert(0, "L:/LocalCoder/workspace/native_nn_source")
import mirror_chat as mc  # noqa: E402
import turn_policy as tp  # noqa: E402


class Handler(BaseHTTPRequestHandler):
    tok = None
    model = None
    device = "cpu"

    def log_message(self, fmt, *args):
        print(f"[viv-server] {fmt % args}", flush=True)

    def _send_json(self, code: int, obj: dict):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/") in ("/v1/models", "/models"):
            self._send_json(200, {"object": "list", "data": [{
                "id": "viv-1.0-319m", "object": "model",
                "created": int(time.time()), "owned_by": "viv",
            }]})
        else:
            self._send_json(404, {"error": {"message": "not found"}})

    def do_POST(self):
        if self.path.rstrip("/") not in ("/v1/chat/completions", "/chat/completions"):
            self._send_json(404, {"error": {"message": "not found"}})
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send_json(400, {"error": {"message": "invalid json"}})
            return

        messages = body.get("messages", [])
        user = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user = m.get("content") or ""
                break
        conv = tp.Conversation()
        rec = mc.turn(self.tok, self.model, conv, user, self.device, 2, 64, 0.8, 32)
        text = rec.get("chosen") or ""

        model_id = body.get("model", "viv-1.0-319m")
        created = int(time.time())
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            chunk = {"id": "chatcmpl-viv", "object": "chat.completion.chunk",
                     "created": created, "model": model_id,
                     "choices": [{"index": 0, "delta": {"role": "assistant",
                                                        "content": text},
                                  "finish_reason": "stop"}]}
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return

        self._send_json(200, {
            "id": "chatcmpl-viv", "object": "chat.completion",
            "created": created, "model": model_id,
            "choices": [{"index": 0,
                         "message": {"role": "assistant", "content": text},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "viv": {"act": rec["act"], "shape": rec["shape"],
                    "released": rec["accepted"], "attempts": len(rec["attempts"])},
        })


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--checkpoint", type=Path, required=True)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8001)
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    tok, model = mc.load_model(args.checkpoint, device)
    Handler.tok, Handler.model, Handler.device = tok, model, device
    print(f"[viv-server] loaded {args.checkpoint} on {device}; "
          f"http://{args.host}:{args.port}/v1", flush=True)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
