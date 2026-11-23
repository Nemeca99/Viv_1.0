"""
Local Model Client for AIOS Viv Autonomy.
Unifies all offline LLM and embedding calls to the local LM Studio instance.
Zero cloud dependencies.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Union

try:
    from clawd_notifier import notify_clawd, ensure_clawd_running
except ImportError:
    try:
        from autonomy.clawd_notifier import notify_clawd, ensure_clawd_running
    except ImportError:
        def notify_clawd(*args, **kwargs): pass
        def ensure_clawd_running(): pass

DEFAULT_ENDPOINT = os.environ.get("LMSTUDIO_ENDPOINT", "http://192.168.40.21:1234/v1")
DEFAULT_MODEL = os.environ.get("LMSTUDIO_MODEL", "omnicoder-2-9b")
DEFAULT_EMBED_MODEL = os.environ.get("LMSTUDIO_EMBED_MODEL", "text-embedding-nomic-embed-text-v1.5")


class LocalModelClient:
    def __init__(
        self,
        endpoint: str = DEFAULT_ENDPOINT,
        model: str = DEFAULT_MODEL,
        embed_model: str = DEFAULT_EMBED_MODEL,
        timeout: float = 120.0,
    ):
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.embed_model = embed_model
        self.timeout = timeout

    def health_check(self) -> Dict[str, Any]:
        url = f"{self.endpoint}/models"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "LocalCoder-Autonomy/1.0"})
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = [m.get("id") for m in data.get("data", [])]
                is_ready = self.model in models or len(models) > 0
                return {
                    "status": "ONLINE" if is_ready else "DEGRADED",
                    "endpoint": self.endpoint,
                    "target_model": self.model,
                    "available_models": models,
                    "has_target_model": self.model in models,
                }
        except Exception as exc:
            return {
                "status": "OFFLINE",
                "endpoint": self.endpoint,
                "error": str(exc),
            }

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.1,
        max_tokens: int = 8192,
        stop: Optional[List[str]] = None,
        retries: int = 3,
    ) -> str:
        url = f"{self.endpoint}/chat/completions"
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if stop:
            payload["stop"] = stop

        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "LocalCoder-Autonomy/1.0",
        }

        last_error = None
        for attempt in range(1, retries + 1):
            try:
                req = urllib.request.Request(url, data=body, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    res_data = json.loads(resp.read().decode("utf-8"))
                    choices = res_data.get("choices", [])
                    if not choices:
                        raise ValueError(f"No choices returned from LLM: {res_data}")
                    content = choices[0].get("message", {}).get("content", "")
                    return content
            except urllib.error.HTTPError as http_err:
                err_content = http_err.read().decode("utf-8", errors="replace")
                last_error = f"HTTP {http_err.code}: {err_content}"
                if attempt < retries:
                    time.sleep(1.0 * attempt)
            except Exception as exc:
                last_error = str(exc)
                if attempt < retries:
                    time.sleep(1.0 * attempt)

        raise RuntimeError(f"LocalModelClient failed after {retries} attempts: {last_error}")

    def generate_code(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 8192,
    ) -> str:
        sys_msg = system_prompt or (
            "You are Viv, the sovereign AIOS Core Mind and engineer. "
            "Write valid, functional code adhering exactly to requirements. "
            "Output the code cleanly."
        )
        messages = [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": prompt},
        ]
        notify_clawd("thinking", "UserPromptSubmit", tool_name="local_model_inference")
        raw = self.chat(messages, temperature=temperature, max_tokens=max_tokens)
        notify_clawd("working", "PreToolUse", tool_name="code_extraction")
        return self._extract_code(raw)

    def embed(self, texts: Union[str, List[str]]) -> List[List[float]]:
        url = f"{self.endpoint}/embeddings"
        input_data = [texts] if isinstance(texts, str) else texts
        payload = {
            "model": self.embed_model,
            "input": input_data,
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "LocalCoder-Autonomy/1.0",
        }

        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=30.0) as resp:
            res_data = json.loads(resp.read().decode("utf-8"))
            embeddings = [item.get("embedding", []) for item in res_data.get("data", [])]
            return embeddings

    @staticmethod
    def _extract_code(text: str) -> str:
        """Extracts code from markdown blocks using regex, or returns cleaned text."""
        import re
        # Look for ```python or ```rust or bare ``` blocks
        pattern = r"```(?:[a-zA-Z0-9_\-+]*\n)?(.*?)```"
        matches = re.findall(pattern, text, re.DOTALL)
        if matches:
            # Pick the largest code block (usually the primary code implementation)
            best_block = max(matches, key=len).strip()
            return best_block

        # If no closing fence or incomplete fence, check for single opening fence
        if "```" in text:
            parts = text.split("```", 1)[1]
            if "\n" in parts:
                first_line, rest = parts.split("\n", 1)
                if first_line.strip().isalnum():
                    return rest.strip()
            return parts.strip()

        return text.strip()


# Global singleton instance
default_client = LocalModelClient()


if __name__ == "__main__":
    client = LocalModelClient()
    print("[*] Running LocalModelClient diagnostic...")
    status = client.health_check()
    print(f"[*] Health Check: {json.dumps(status, indent=2)}")
    if status["status"] == "ONLINE":
        sample = client.generate_code("Write a one-line Python function `def square(x): return x * x`")
        print(f"[*] Generated code sample:\n{sample}")
        try:
            embs = client.embed(["test vector embedding"])
            print(f"[*] Embedding dimension: {len(embs[0]) if embs else 'None'}")
        except Exception as e:
            print(f"[!] Embedding note: {e}")
        print("[+] LocalModelClient test completed successfully on silicon.")
    else:
        sys.exit(1)
