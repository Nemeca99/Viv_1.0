"""Teacher Bridge: Requests lesson proposals from LM Studio and gates them through SecondaryChecker.

Connects to authorized local endpoint (127.0.0.1:1234 or 192.168.1.21:1234).
"""

from __future__ import annotations

import json
import os
import re
import threading
from typing import Any
import urllib.request
import urllib.error

from autonomy.secondary_checker import DeterministicSecondaryChecker, SecondaryCheckerVerdict

DEFAULT_ENDPOINTS = [
    "http://127.0.0.1:1234/v1",
    "http://192.168.1.21:1234/v1",
]

TEACHER_SYSTEM_PROMPT = """You are an automated lesson generator for a topology-backed reading tutor.
You must output ONLY a single valid JSON object, and nothing else.
Do not write explanations, markdown fences, thinking, or preamble.

Required JSON format:
{
  "sentence": "a short sentence using the requested target",
  "target": "the requested target"
}

Critical Rules:
1. The sentence must be grounded only in the retrieved lesson context.
2. The sentence must be 3 to 8 words long, end with a period, and contain the requested target exactly as a token.
3. If the retrieved context is insufficient, return an empty JSON object.
"""

_TUTOR_REQUEST_LOCK = threading.Lock()


def extract_json_candidates(text: str) -> list[dict]:
    """Scan string for any syntactically valid JSON dictionaries."""
    cleaned_text = re.sub(r'\\([^\/\\\"bfnrtu])', r'\1', text)
    decoder = json.JSONDecoder()
    pos = 0
    results = []
    while pos < len(cleaned_text):
        idx = cleaned_text.find("{", pos)
        if idx == -1:
            break
        try:
            obj, end = decoder.raw_decode(cleaned_text, idx)
            if isinstance(obj, dict):
                results.append(obj)
            pos = max(pos + 1, end)
        except Exception:
            pos = idx + 1
    return results


class TeacherBridge:
    def __init__(self, base_url: str | None = None, checker: DeterministicSecondaryChecker | None = None):
        self.base_url = (base_url or DEFAULT_ENDPOINTS[0]).rstrip("/")
        self.checker = checker or DeterministicSecondaryChecker()
        self.last_model_id: str | None = None

    def get_loaded_models(self) -> list[str]:
        for endpoint in DEFAULT_ENDPOINTS:
            url = f"{endpoint}/models"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "NoxForge/1.0"})
                with urllib.request.urlopen(req, timeout=2) as resp:
                    if resp.status == 200:
                        self.base_url = endpoint
                        data = json.loads(resp.read().decode("utf-8"))
                        return [m.get("id") for m in data.get("data", [])]
            except Exception:
                continue
        return []

    def request_completion(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        model_id: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 256,
        timeout: int = 60,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        """Query LLM on local endpoint for a raw text completion."""
        loaded = self.get_loaded_models()
        if not loaded:
            raise RuntimeError("LM Studio endpoint is not responding or has no loaded model.")
        active_model = model_id or os.environ.get("VIV_TUTOR_MODEL") or loaded[0]
        if active_model not in loaded:
            raise RuntimeError(f"Requested tutor model is not loaded: {active_model}")
        self.last_model_id = active_model
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": active_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format is not None:
            payload["response_format"] = response_format
        url = f"{self.base_url}/chat/completions"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "NoxForge/1.0"},
            method="POST",
        )
        # If LM Studio supports parallel inference (e.g. --parallel 4), do not artificially
        # serialize in Python; otherwise acquire mutex to protect single-slot backends.
        parallel_slots = int(os.environ.get("VIV_TUTOR_PARALLEL_SLOTS", "4"))
        lock_context = _TUTOR_REQUEST_LOCK if parallel_slots <= 1 else threading.Lock()
        with lock_context:
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    choice = data["choices"][0]["message"]
                    return choice.get("content") or choice.get("reasoning_content") or ""
            except (urllib.error.HTTPError, urllib.error.URLError):
                comp_url = f"{self.base_url}/completions"
                raw_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
                comp_payload = {
                    "model": active_model,
                    "prompt": raw_prompt,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
                comp_req = urllib.request.Request(
                    comp_url,
                    data=json.dumps(comp_payload).encode("utf-8"),
                    headers={"Content-Type": "application/json", "User-Agent": "NoxForge/1.0"},
                    method="POST",
                )
                with urllib.request.urlopen(comp_req, timeout=timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    return data["choices"][0]["text"].strip()

    def request_lesson(
        self,
        focus_category: str | None = None,
        model_id: str | None = None,
        temperature: float = 0.0,
        prompt_override: str | None = None,
    ) -> tuple[dict[str, Any] | None, SecondaryCheckerVerdict]:
        """Request a proposed lesson from LM Studio and immediately verify it via SecondaryChecker."""
        loaded = self.get_loaded_models()
        if not loaded:
            return None, SecondaryCheckerVerdict(False, "LM Studio is running but no model is loaded. Load a model first.")

        active_model = model_id or os.environ.get("VIV_TUTOR_MODEL") or loaded[0]
        if active_model not in loaded:
            return None, SecondaryCheckerVerdict(False, f"Requested tutor model is not loaded: {active_model}")

        user_prompt = prompt_override or (
            f"Generate one lesson JSON object for the requested focus: {focus_category or 'the retrieved target'}.\n"
            "Use only vocabulary present in the retrieved lesson context.\n"
            "Return only the required JSON object; do not invent a target or relation."
        )
        payload = {
            "model": active_model,
            "messages": [
                {"role": "system", "content": TEACHER_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": 1024,
        }

        try:
            content = self.request_completion(
                user_prompt,
                system_prompt=TEACHER_SYSTEM_PROMPT,
                model_id=active_model,
                temperature=temperature,
                max_tokens=1024,
                timeout=90,
            )
            candidates = extract_json_candidates(content)
            
            proposal = None
            for cand in reversed(candidates):
                if "template" in cand and "target_filler" in cand:
                    proposal = cand
                    break
            if proposal is None and candidates:
                proposal = candidates[-1]
            if proposal is None:
                snippet = content[:100]
                return None, SecondaryCheckerVerdict(False, f"No JSON object found in teacher response: {snippet}...")
            
            # Normalize blank slot representation if model used underscores or dots
            if isinstance(proposal, dict) and "template" in proposal:
                tmpl = str(proposal["template"])
                if "[?]" not in tmpl:
                    normalized = re.sub(r"_{2,}|\.{3,}|\(\.\.\.\)|\[blank\]|<blank>", "[?]", tmpl)
                    proposal["template"] = normalized
        except urllib.error.URLError as err:
            return None, SecondaryCheckerVerdict(False, f"LM Studio connection error: {err}")
        except json.JSONDecodeError as err:
            return None, SecondaryCheckerVerdict(False, f"Teacher output was not valid JSON: {err}")
        except Exception as exc:
            return None, SecondaryCheckerVerdict(False, f"Teacher request error: {exc}")
        except urllib.error.URLError as err:
            return None, SecondaryCheckerVerdict(False, f"LM Studio connection error: {err}")
        except json.JSONDecodeError as err:
            return None, SecondaryCheckerVerdict(False, f"Teacher output was not valid JSON: {err}")
        except Exception as exc:
            return None, SecondaryCheckerVerdict(False, f"Teacher request error: {exc}")

        # Adjudicate via Secondary Checker
        verdict = self.checker.verify_lesson_proposal(proposal)
        return proposal, verdict
