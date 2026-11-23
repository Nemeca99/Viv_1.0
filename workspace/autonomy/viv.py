"""
Viv CLI & SDK — Sovereign Inverted Enigma Product Interface
===========================================================
Architect: Travis (Nox Forge / AIOS V2)
Usage:
  python viv.py "Who was Honest Abe?"
  python viv.py "What is 15 plus 27?"
  python viv.py --chat
  python viv.py --web
  python viv.py --help
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.request
import webbrowser
from typing import Any, Dict, Iterator, List, Optional

SERVER_URL = "http://127.0.0.1:1235"
TOPOLOGY_DB = r"L:\LocalCoder\workspace\autonomy\viv_code_topology.sqlite3"
RNN_CANDIDATE = r"L:\LocalCoder\workspace\autonomy\.tmp\rnn_candidate.json"
PERSISTENT_MEMORY = r"L:\LocalCoder\workspace\aios_rebuild\memory\persistent_memory.json"


def grounded_rnn_query(query: str) -> dict[str, Any]:
    """Opt-in grounded path; default Viv Network behavior is unchanged."""
    workspace = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if workspace not in sys.path:
        sys.path.insert(0, workspace)
    from autonomy.grounded_rnn_answer_bridge import GroundedRNNAnswerBridge

    topology_hash = hashlib.sha256(open(TOPOLOGY_DB, "rb").read()).hexdigest()
    bridge = GroundedRNNAnswerBridge(PERSISTENT_MEMORY, RNN_CANDIDATE, topology_sha256=topology_hash)
    return bridge.answer(query)


class VivClient:
    """Zero-dependency official Python client for Viv's Sovereign Inverted Enigma Engine."""

    def __init__(self, base_url: str = SERVER_URL):
        self.base_url = base_url.rstrip("/")

    def health(self) -> Dict[str, Any]:
        with urllib.request.urlopen(f"{self.base_url}/health", timeout=3) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def chat(
        self,
        messages: List[Dict[str, str]],
        persona: str = "jarvis",
        temperature: float = 0.0,
        stream: bool = False
    ) -> Any:
        url = f"{self.base_url}/v1/chat/completions"
        payload = {
            "messages": messages,
            "persona": persona,
            "temperature": temperature,
            "stream": stream
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"}
        )

        if stream:
            return self._stream_response(req)
        else:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))

    def _stream_response(self, req: urllib.request.Request) -> Iterator[str]:
        with urllib.request.urlopen(req, timeout=15) as resp:
            while True:
                line = resp.readline().decode("utf-8")
                if not line:
                    break
                line_str = line.strip()
                if line_str.startswith("data: "):
                    val = line_str[6:]
                    if val == "[DONE]":
                        break
                    try:
                        parsed = json.loads(val)
                        delta = parsed["choices"][0]["delta"].get("content", "")
                        if delta:
                            yield delta
                    except Exception:
                        pass

    def ask(
        self,
        query: str,
        persona: str = "jarvis",
        temperature: float = 0.0,
        stream: bool = False
    ) -> Any:
        return self.chat([{"role": "user", "content": query}], persona=persona, temperature=temperature, stream=stream)


def interactive_chat(persona: str = "jarvis", temperature: float = 0.0):
    client = VivClient()
    try:
        status = client.health()
        print("=" * 65)
        print(" VIV // INVERTED ENIGMA INTERACTIVE COGNITIVE SHELL")
        print(f" Engine Status: {status.get('status')} | Active Rotor: {status.get('active_domain').upper()} | VRAM: {status.get('vram_mb')} MiB")
        print(f" Persona: {persona.upper()} | Temperature: {temperature} (T=0.0: Deterministic Hop 1)")
        print(" Type 'exit' or 'quit' to end session. Type 'clear' to reset discourse.")
        print("=" * 65)
    except Exception as e:
        print(f"[-] Error connecting to Viv on {SERVER_URL}: {e}")
        print("    Ensure the engine daemon is running: python viv_enigma_engine.py --port 1234")
        return

    history: List[Dict[str, str]] = []

    while True:
        try:
            prompt = input("\n[User] > ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nSession terminated.")
            break

        if not prompt:
            continue
        if prompt.lower() in ("exit", "quit"):
            print("Session terminated.")
            break
        if prompt.lower() == "clear":
            history.clear()
            print("[*] Discourse history cleared.")
            continue

        history.append({"role": "user", "content": prompt})

        print(f"\n[Viv // {persona.upper()}] > ", end="", flush=True)
        try:
            full_reply = ""
            for chunk in client.chat(history, persona=persona, temperature=temperature, stream=True):
                print(chunk, end="", flush=True)
                full_reply += chunk
            print()
            history.append({"role": "assistant", "content": full_reply})
        except Exception as e:
            print(f"\n[-] Transmission fault: {e}")


def main():
    parser = argparse.ArgumentParser(description="Viv: Sovereign Inverted Enigma Cognitive Product")
    parser.add_argument("query", nargs="?", help="Direct query for Viv (e.g. 'Who was Honest Abe?')")
    parser.add_argument("--chat", action="store_true", help="Launch interactive multi-turn terminal chat")
    parser.add_argument("--web", action="store_true", help="Launch Viv Web UI in default browser")
    parser.add_argument("--persona", default="jarvis", choices=["jarvis", "valley_girl", "raw"], help="Persona delivery gauge")
    parser.add_argument("--temp", type=float, default=0.0, help="Temperature dial (0.0=Deterministic, 0.7=Associative)")
    parser.add_argument("--stream", action="store_true", help="Stream response tokens in real time")
    parser.add_argument("--grounded-rnn", action="store_true", help="Use the opt-in topology-RNN grounded answer path")

    args = parser.parse_args()

    if args.grounded_rnn:
        if not args.query:
            parser.error("--grounded-rnn requires a query")
        result = grounded_rnn_query(args.query)
        print(result["answer"])
        print(json.dumps(result["evidence_receipt"], sort_keys=True))
        return

    if args.web:
        print(f"[*] Opening Viv Web Dashboard at {SERVER_URL}...")
        webbrowser.open(SERVER_URL)
        return

    if args.chat or not args.query:
        interactive_chat(persona=args.persona, temperature=args.temp)
        return

    client = VivClient()
    try:
        if args.stream:
            for chunk in client.ask(args.query, persona=args.persona, temperature=args.temp, stream=True):
                print(chunk, end="", flush=True)
            print()
        else:
            res = client.ask(args.query, persona=args.persona, temperature=args.temp, stream=False)
            reply = res["choices"][0]["message"]["content"]
            trace = res.get("enigma_trace", {})
            print(reply)
            if trace.get("plugboard_swap"):
                print(f"\n[Plugboard]: {trace['plugboard_swap']}")
            if trace.get("gate_status"):
                print(f"[Gate]: {trace['gate_status']} (Latency: {trace.get('latency_ms')} ms)")
    except Exception as e:
        print(f"[-] Execution error: {e}")


if __name__ == "__main__":
    main()
