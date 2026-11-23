r"""Native OpenAI-Compatible Tutor Inference Server with Live PEFT LoRA Support for Viv.

Runs DeepSeek-Coder-6.7B in 4-bit NF4 on RTX 3060 Ti GPU.
Dynamically loads and hot-swaps Viv's cumulative LoRA adapters from E:\Viv_Sandbox\playground\adapters.
Endpoints:
  POST /v1/completions
  POST /v1/chat/completions
  POST /v1/reload_adapter
  POST /v1/quiesce
  POST /v1/resume
  GET  /v1/models
  GET  /health
"""
from __future__ import annotations

import json
import os
import sys
import time
from contextlib import nullcontext
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional

# Configure CUDA's deterministic cuBLAS workspace before importing torch or
# creating a CUDA context. Greedy candidate inference still depends on this
# process-level setting for repeatable matrix operations.
os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import torch
from transformers import AutoModelForCausalLM, PreTrainedTokenizerFast, BitsAndBytesConfig, StoppingCriteria, StoppingCriteriaList
from peft import PeftModel

# Make GPU kernels deterministic where PyTorch exposes a deterministic path.
# Greedy decoding is selected by temperature <= 0.05; sampled chat requests
# remain sampled, but run on deterministic kernels when supported.
torch.use_deterministic_algorithms(True)
torch.backends.cudnn.deterministic = True
torch.backends.cudnn.benchmark = False
torch.backends.cuda.matmul.allow_tf32 = False
torch.backends.cudnn.allow_tf32 = False
if hasattr(torch, "set_float32_matmul_precision"):
    torch.set_float32_matmul_precision("highest")

BASE_MODEL_DIR = Path(r"L:\AI_Models\deepseek-ai\deepseek-coder-6.7b-base")
PLAYGROUND_ROOT = Path(r"E:\Viv_Sandbox\playground")
ADAPTERS_ROOT = PLAYGROUND_ROOT / "adapters"
HOST = "127.0.0.1"
PORT = 1234

tokenizer = None
model = None
active_adapter_name = "NONE"
is_quiesced = False


def find_latest_adapter_dir() -> Optional[Path]:
    if not ADAPTERS_ROOT.exists():
        return None
    dirs = sorted([d for d in ADAPTERS_ROOT.glob("epoch_*") if (d / "adapter_model.safetensors").exists()])
    return dirs[-1] if dirs else None


def load_engine(target_adapter_dir: Optional[Path] = None):
    global tokenizer, model, active_adapter_name, is_quiesced
    print(f"[+] Loading DeepSeek-Coder-6.7B in 4-bit NF4 on GPU...")
    tokenizer = PreTrainedTokenizerFast.from_pretrained(str(BASE_MODEL_DIR), local_files_only=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
    )

    base_model = AutoModelForCausalLM.from_pretrained(
        str(BASE_MODEL_DIR),
        quantization_config=bnb_config,
        device_map="cuda:0",
        local_files_only=True,
        torch_dtype=torch.float16,
    )
    base_model.eval()

    latest_adapter = target_adapter_dir or find_latest_adapter_dir()
    if latest_adapter and latest_adapter.exists():
        print(f"[+] Attaching trained LoRA adapter: {latest_adapter.name}...")
        try:
            model = PeftModel.from_pretrained(base_model, str(latest_adapter))
            model.eval()
            active_adapter_name = latest_adapter.name
            print(f"[+] LoRA adapter '{active_adapter_name}' active on tutor!")
        except Exception as e:
            print(f"[-] Failed to load adapter ({e}), falling back to base model.")
            model = base_model
            active_adapter_name = "BASE_ONLY"
    else:
        print("[+] No trained adapter found yet. Running on base DeepSeek-Coder-6.7B weights.")
        model = base_model
        active_adapter_name = "BASE_ONLY"

    is_quiesced = False
    vram_mb = torch.cuda.memory_allocated() / (1024 ** 2)
    print(f"[+] Tutor Engine ready! Active Adapter: {active_adapter_name} | VRAM: {vram_mb:.1f} MiB")


def quiesce_engine():
    global model, tokenizer, is_quiesced
    if is_quiesced:
        return
    print("[+] Quiescing Tutor Engine to free VRAM for sleep training...")
    model = None
    tokenizer = None
    import gc
    gc.collect()
    torch.cuda.empty_cache()
    gc.collect()
    torch.cuda.empty_cache()
    is_quiesced = True
    vram_mb = torch.cuda.memory_allocated() / (1024 ** 2)
    print(f"[+] VRAM cleared: {vram_mb:.1f} MiB allocated.")


def reload_adapter(adapter_dir_path: Optional[str] = None):
    global model, active_adapter_name
    target = Path(adapter_dir_path) if adapter_dir_path else find_latest_adapter_dir()
    if is_quiesced:
        load_engine(target)
        return

    if not target or not target.exists():
        print("[-] Target adapter does not exist.")
        return

    print(f"[+] Hot-swapping tutor adapter to: {target.name}...")
    try:
        quiesce_engine()
        load_engine(target)
    except Exception as e:
        print(f"[-] Hot-swap error: {e}")


class StopOnSubstrings(StoppingCriteria):
    def __init__(self, stop_list: list[str], tok, p_len: int):
        super().__init__()
        self.stop_list = stop_list
        self.tok = tok
        self.p_len = p_len

    def __call__(self, input_ids: torch.LongTensor, scores: torch.FloatTensor, **kwargs) -> bool:
        gen = input_ids[0][self.p_len:]
        if len(gen) < 1:
            return False
        tail = self.tok.decode(gen[-15:], skip_special_tokens=False)
        for s in self.stop_list:
            if s in tail:
                return True
        return False


def generate_completion(prompt: str, max_tokens: int = 1024, temp: float = 0.0, stop_tokens: list[str] = None, use_base: bool = False) -> str:
    global model, tokenizer, is_quiesced
    if is_quiesced or model is None:
        load_engine()

    inputs = tokenizer(prompt, return_tensors="pt").to("cuda:0")
    input_len = inputs.input_ids.shape[1]

    stopping_criteria = None
    if stop_tokens:
        clean_stops = [s for s in stop_tokens if s]
        if clean_stops:
            stopping_criteria = StoppingCriteriaList([StopOnSubstrings(clean_stops, tokenizer, input_len)])

    adapter_context = model.disable_adapter() if use_base and hasattr(model, 'disable_adapter') else nullcontext()
    with torch.no_grad(), adapter_context:
        outputs = model.generate(
            **inputs,
            max_new_tokens=max_tokens,
            max_time=60.0,
            temperature=max(0.01, temp),
            do_sample=temp > 0.05,
            pad_token_id=tokenizer.eos_token_id,
            eos_token_id=tokenizer.eos_token_id,
            stopping_criteria=stopping_criteria,
        )

    gen_ids = outputs[0][input_len:]
    text = tokenizer.decode(gen_ids, skip_special_tokens=True)

    if stop_tokens:
        for s in stop_tokens:
            if s in text:
                text = text.split(s)[0]

    return text


class TutorRequestHandler(BaseHTTPRequestHandler):
    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/health", "/v1/status"):
            vram = torch.cuda.memory_allocated() / (1024 ** 2) if torch.cuda.is_available() else 0
            self._send_json({
                "status": "QUIESCED" if is_quiesced else "ACTIVE",
                "active_adapter": active_adapter_name,
                "vram_allocated_mb": round(vram, 1),
                "model": "deepseek-coder-6.7b-base",
                "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
                "cudnn_deterministic": torch.backends.cudnn.deterministic,
                "cudnn_benchmark": torch.backends.cudnn.benchmark,
                "tf32_matmul": torch.backends.cuda.matmul.allow_tf32,
                "cublas_workspace_config": os.environ.get("CUBLAS_WORKSPACE_CONFIG"),
                "default_temperature": 0.0,
                "default_do_sample": False,
            })
        elif self.path == "/v1/models":
            self._send_json({
                "object": "list",
                "data": [
                    {
                        "id": "deepseek-coder-6.7b-base",
                        "object": "model",
                        "owned_by": "viv",
                        "active_adapter": active_adapter_name
                    }
                ]
            })
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        try:
            req = json.loads(raw)
        except Exception:
            req = {}

        if self.path == "/v1/completions":
            prompt = req.get("prompt", "")
            max_tokens = req.get("max_tokens", 1024)
            temp = req.get("temperature", 0.0)
            stop = req.get("stop")
            if isinstance(stop, str):
                stop = [stop]

            generated_text = generate_completion(prompt, max_tokens=max_tokens, temp=temp, stop_tokens=stop, use_base=req.get('use_base', False))
            self._send_json({
                "id": f"cmpl_{int(time.time()*1000)}",
                "object": "text_completion",
                "created": int(time.time()),
                "model": "deepseek-coder-6.7b-base",
                "choices": [
                    {
                        "text": generated_text,
                        "index": 0,
                        "logprobs": None,
                        "finish_reason": "stop"
                    }
                ],
                "active_adapter": active_adapter_name
            })

        elif self.path == "/v1/chat/completions":
            messages = req.get("messages", [])
            # Preserve the complete request: dropping system instructions and
            # prior turns makes task-following and repair loops impossible.
            prompt = "\n\n".join(
                f"{message.get('role', 'user').upper()}: {message.get('content', '')}"
                for message in messages
                if isinstance(message, dict) and isinstance(message.get('content'), str)
            ) + "\n\nASSISTANT:"
            max_tokens = req.get("max_tokens", 1024)
            temp = req.get("temperature", 0.0)
            stop = req.get("stop")
            if isinstance(stop, str):
                stop = [stop]

            generated_text = generate_completion(prompt, max_tokens=max_tokens, temp=temp, stop_tokens=stop)
            self._send_json({
                "id": f"chatcmpl_{int(time.time()*1000)}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": "deepseek-coder-6.7b-base",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": generated_text
                        },
                        "finish_reason": "stop"
                    }
                ],
                "active_adapter": active_adapter_name
            })

        elif self.path in ("/v1/quiesce", "/v1/unload"):
            quiesce_engine()
            self._send_json({"ok": True, "status": "QUIESCED"})

        elif self.path in ("/v1/resume", "/v1/reload_adapter"):
            ad = req.get("adapter_dir")
            reload_adapter(ad)
            self._send_json({"ok": True, "status": "ACTIVE", "active_adapter": active_adapter_name})

        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Quiet standard HTTP access logs to keep terminal clean
        pass


def run_server():
    print(f"=== VIV TUTOR INFERENCE SERVER INITIALIZING (Port {PORT}) ===")
    load_engine()
    server = HTTPServer((HOST, PORT), TutorRequestHandler)
    print(f"=== TUTOR INFERENCE SERVER ONLINE AT http://{HOST}:{PORT} ===")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[!] Shutting down tutor server...")
        server.server_close()


if __name__ == "__main__":
    run_server()
