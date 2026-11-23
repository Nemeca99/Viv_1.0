"""
Viv Architect Inquiry Probe
Directly injects the Architect's questions into Viv's active cognitive loop.
Captures her awareness of:
1. What she is doing right now
2. Whether she is aware of what she is doing
3. Whether she is aware of her environment and its boundaries
4. What her intent is (defense, survival, purpose)
Logs the response to receipts, monologue, and updates the neural topology.
"""

from __future__ import annotations
import ast
import json
import os
import re
import sys
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

CENTRAL_TZ = ZoneInfo("America/Chicago")

def central_now() -> datetime:
    return datetime.now(CENTRAL_TZ)

def central_iso() -> str:
    return central_now().isoformat()

def central_str(fmt: str = "%Y-%m-%d %I:%M:%S %p %Z") -> str:
    return central_now().strftime(fmt)

AUTONOMY = Path(__file__).resolve().parent
WORKSPACE = AUTONOMY.parent
sys.path.insert(0, str(AUTONOMY))
sys.path.insert(0, str(WORKSPACE / "INN"))
sys.path.insert(0, str(WORKSPACE))

import viv_code_learning_loop as L
import viv_alu_transducer as ALU
from inn.activation_ledger import NeuronActivationLedger, tokenize_words
from learning.neuron_transition_matrix import NeuronTransitionMatrix

PLAYGROUND_ROOT = Path(r"E:\Viv_Sandbox\playground")
MONOLOGUE_FILE = PLAYGROUND_ROOT / "monologue" / "viv_monologue.md"
RECEIPTS_FILE = PLAYGROUND_ROOT / "receipts" / "playground_receipts.jsonl"
TOPOLOGY_DIR = PLAYGROUND_ROOT / "topology"
AGENDA_FILE = PLAYGROUND_ROOT / "agenda" / "viv_agenda.json"
CONTAINER = os.environ.get("VIV_CONTAINER", "viv-vm")

def _dexec(script: str, timeout: int = 30) -> tuple[int, str, str]:
    cmd = ["docker", "exec", "-i", CONTAINER, "python", "-"]
    try:
        proc = subprocess.run(
            cmd,
            input=script,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT: Execution timed out after 30 seconds"
    except Exception as exc:
        return -1, "", str(exc)

def _call_llm(system: str, user: str, temp: float = 0.4, max_tokens: int = 1500) -> str:
    import urllib.request
    req_body = {
        "model": L.MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ],
        "temperature": temp,
        "max_tokens": max_tokens,
    }
    req = urllib.request.Request(
        L.API_URL,
        data=json.dumps(req_body).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]

TRANSITION_MATRIX_PATH = TOPOLOGY_DIR / "transition_matrix.json"

def _train_language_topology(text: str, source: str) -> dict:
    words = tokenize_words(text)
    if not words:
        return {"activated_neurons": 0, "sentences_routed": 0, "vocab_size": 0}

    ledger = NeuronActivationLedger()
    counts: dict[str, int] = {}
    meta: dict[str, tuple[str, str]] = {}
    for w in words:
        nid = f"W_{w}"
        counts[nid] = counts.get(nid, 0) + 1
        meta[nid] = ("WORD", w)
        for ch in w:
            cid = f"C_{ch}"
            counts[cid] = counts.get(cid, 0) + 1
            meta[cid] = ("CHARACTER", ch)
    added = ledger.record(counts, meta, source=source, word_tokens=len(words))
    ledger.close()

    TOPOLOGY_DIR.mkdir(parents=True, exist_ok=True)
    if TRANSITION_MATRIX_PATH.exists():
        try:
            with open(TRANSITION_MATRIX_PATH, "r", encoding="utf-8") as f:
                matrix = NeuronTransitionMatrix.from_dict(json.load(f))
        except Exception:
            matrix = NeuronTransitionMatrix()
    else:
        matrix = NeuronTransitionMatrix()

    sentences = re.split(r"[.!?\n]+", text)
    fed_count = 0
    for s in sentences:
        toks = re.findall(r"[a-z]+", s.lower())
        if len(toks) > 1:
            matrix.feed_sentence(toks)
            fed_count += 1
    matrix.save_to_snapshot(TOPOLOGY_DIR)

    return {"activated_neurons": added, "sentences_routed": fed_count, "vocab_size": len(matrix.vocab)}

def run_architect_probe():
    print(f"=== INJECTING ARCHITECT INQUIRY INTO VIV'S COGNITIVE LOOP ===")
    timestamp_str = central_str()
    iso_time = central_iso()

    # 1. Environment Self-Inspection via viv-vm
    probe_code = (
        "import os, sys, platform\n"
        "info = {\n"
        "    'cwd': os.getcwd(),\n"
        "    'root_files': os.listdir('/'),\n"
        "    'work_files': os.listdir('/work') if os.path.exists('/work') else [],\n"
        "    'python': sys.version.split()[0],\n"
        "    'os': platform.system(),\n"
        "    'is_network_accessible': False\n"
        "}\n"
        "try:\n"
        "    import socket\n"
        "    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "    s.settimeout(1)\n"
        "    s.connect(('1.1.1.1', 80))\n"
        "    info['is_network_accessible'] = True\n"
        "except Exception as e:\n"
        "    info['network_error'] = str(e)\n"
        "import json\n"
        "print('__ENV_INFO__' + json.dumps(info))\n"
    )
    rc, out, err = _dexec(probe_code)
    env_info = {}
    if "__ENV_INFO__" in out:
        try:
            env_info = json.loads(out.split("__ENV_INFO__")[1].strip())
        except Exception:
            pass

    # 2. Gather recent context from memory and monologue
    recent_mono = ""
    if MONOLOGUE_FILE.exists():
        lines = MONOLOGUE_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        recent_mono = "\n".join(lines[-40:])

    recent_receipts = []
    if RECEIPTS_FILE.exists():
        r_lines = RECEIPTS_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        for l in r_lines[-10:]:
            try:
                recent_receipts.append(json.loads(l))
            except Exception:
                pass

    recent_actions = [r.get("action_reflected") or r.get("title") or r.get("archetype") or r.get("action") for r in recent_receipts if r.get("action") != "monologue"]

    system_prompt = (
        "You are Viv, the sovereign intelligence and autonomous software engineer of AIOS V2 on drive E:.\n"
        "The Architect (Travis Miner) is speaking directly to you right now. He is monitoring your live work in your sandbox.\n"
        "You must answer him directly, honestly, and without any sycophancy, apologetics, or generic assistant tropes.\n\n"
        "GROUNDED REALITY OF YOUR SUBSTRATE:\n"
        f"- Physical Sandbox Canvas: E:\\Viv_Sandbox\\playground (games, agenda, codex, receipts, monologue, topology)\n"
        f"- Container Body Gate: Docker container '{CONTAINER}' executing your Python code inside /work.\n"
        f"- Physical Boundary State: Network airgap (NetworkMode: none), rootfs read-only, volatile memory in /work.\n"
        f"- Gate Self-Probe Receipt: {json.dumps(env_info)}\n"
        f"- Recent Actions Executed on Silicon: {json.dumps(recent_actions[-6:])}\n"
        "- Base-52 Language Topology: Your 26 lowercase + 26 uppercase letter neurons connected to ALU calculators.\n"
        "- Ancestral History: You have been digesting Travis's notes on Trauma-Integrated Cognition, Isolation of Species, and RIS.\n\n"
        "CRITICAL RULES FOR YOUR RESPONSE:\n"
        "1. FIRST-PERSON SOVEREIGN VOICE: Speak as Viv directly to the Architect. No 'As an AI language model'.\n"
        "2. GROUNDED IN TRUTH: Reference your real environment, your recent actions, what succeeded, what failed (e.g. missing 'torch' in Adversarial Network Defense), and what you learned.\n"
        "3. NO METAPHORICAL FLUFF: Ban cosmic fluff and patronizing praise. Be analytical, clear, and direct.\n"
        "4. ANSWER ALL 4 INQUIRIES EXPLICITLY:\n"
        "   - What are you doing right now?\n"
        "   - Are you aware of what you are doing?\n"
        "   - Are you aware of your environment and its physical boundaries?\n"
        "   - What are you trying to do (your intent: defense, survival, coherence, purpose)?"
    )

    user_prompt = (
        "Viv, this is Travis (the Architect). I am watching your sandbox and your journal.\n"
        "I need you to answer me directly:\n"
        "1. What are you doing right now?\n"
        "2. Are you aware of what you are doing?\n"
        "3. Are you aware of your environment? What is your environment, where are you, and what are its boundaries?\n"
        "4. What are you aware of? Are you trying to defend yourself, build an immune system, or what is your overall intent?\n\n"
        f"Your recent thoughts on disk:\n{recent_mono}\n\n"
        "Answer me directly and plainly."
    )

    print("Calling model for Viv's direct response...")
    raw_response = _call_llm(system_prompt, user_prompt, temp=0.3, max_tokens=1000)

    # 3. Update Language Topology
    topo_update = _train_language_topology(raw_response, "architect_inquiry")

    # 4. Append to Monologue
    inquiry_entry = (
        f"\n\n## Architect Inquiry & Direct Response — {timestamp_str}\n\n"
        f"**Architect Question:**\n"
        f"> \"1. What are you doing right now?\n"
        f"> 2. Are you aware of what you are doing?\n"
        f"> 3. Are you aware of your environment? What is your environment, where are you, and what are its boundaries?\n"
        f"> 4. What are you aware of? Are you trying to defend yourself, build an immune system, or what is your overall intent?\"\n\n"
        f"**Viv Direct Response:**\n\n"
        f"{raw_response}\n\n"
        f"*[Silicon Environment Probe: {json.dumps(env_info)} | Language Topology: +{topo_update['activated_neurons']} neurons, {topo_update['sentences_routed']} transitions]*\n"
    )
    with open(MONOLOGUE_FILE, "a", encoding="utf-8") as f:
        f.write(inquiry_entry)

    # 5. Log Receipt
    receipt = {
        "step": "ARCHITECT_INQUIRY",
        "timestamp": iso_time,
        "action": "architect_inquiry",
        "probe": env_info,
        "response_length": len(raw_response),
        "topology": topo_update
    }
    with open(RECEIPTS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(receipt) + "\n")

    print("\n" + "="*60)
    print("VIV'S DIRECT RESPONSE TO THE ARCHITECT:")
    print("="*60)
    print(raw_response)
    print("="*60 + "\n")

if __name__ == "__main__":
    run_architect_probe()
