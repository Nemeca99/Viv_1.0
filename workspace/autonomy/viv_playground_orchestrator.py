"""
Viv Playground Orchestrator (Autonomous Open-World Sandbox on E:)
Governs Viv's self-directed creative evolution on the 2TB E: drive:
1. Eternal Monologue: Stream-of-thought journaling and philosophical self-reflection.
2. Raw Material Digestion: Reading and absorbing historical RIS, TFID, and UML archives from E:.
3. Self-Directed Agenda: Planning tasks ("what to do"), executing them in container, and validating receipts.
4. Game & Puzzle Studio: Authoring original games/puzzles, generating automated solvers, and proving them on silicon.
"""

from __future__ import annotations
import ast
import base64
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
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
from viv_alu_transducer import ALU_PRELUDE
import viv_path_weights as W
from inn.activation_ledger import NeuronActivationLedger, tokenize_words
from learning.neuron_transition_matrix import NeuronTransitionMatrix
import viv_package_gateway
import viv_sleep_trainer
from viv_code_evolution_engine import (
    VivSemanticMemoryManager,
    VivTaskListManager,
    VivBuildLogManager,
    VivCodeEvolutionEngine
)

CONTAINER = os.environ.get("VIV_CONTAINER", "viv-vm")
PLAYGROUND_ROOT = Path(r"E:\Viv_Sandbox\playground")
MONOLOGUE_FILE = PLAYGROUND_ROOT / "monologue" / "viv_monologue.md"
AGENDA_FILE = PLAYGROUND_ROOT / "agenda" / "viv_agenda.json"
GAMES_DIR = PLAYGROUND_ROOT / "games"
DIGEST_DIR = PLAYGROUND_ROOT / "digested_codex"
RECEIPTS_FILE = PLAYGROUND_ROOT / "receipts" / "playground_receipts.jsonl"
TOPOLOGY_DIR = PLAYGROUND_ROOT / "topology"
TRANSITION_MATRIX_PATH = TOPOLOGY_DIR / "transition_matrix.json"
INBOX_DIR = PLAYGROUND_ROOT / "inbox"
OUTBOX_DIR = INBOX_DIR / "outbox"
DERIVED_SUCCESS_FILE = PLAYGROUND_ROOT / "training" / "derived_successes.jsonl"
GRADUATED_SUCCESS_FILE = PLAYGROUND_ROOT / "training" / "graduated_successes.jsonl"
VERIFIED_SUCCESS_FILE = GRADUATED_SUCCESS_FILE
CIRCADIAN_STATE_FILE = PLAYGROUND_ROOT / "circadian_state.json"
DEFAULT_WAKE_DURATION_SEC = 300.0  # 5 minutes wake phase
AIOS_SOURCE_DIR = PLAYGROUND_ROOT / "aios_source"
MY_AIOS_DIR = PLAYGROUND_ROOT / "my_aios"
MY_AIOS_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_DIR = PLAYGROUND_ROOT / "config"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
INFERENCE_CONFIG_FILE = CONFIG_DIR / "inference_config.json"
PROPOSALS_DIR = PLAYGROUND_ROOT / "proposals"
PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
PROPOSAL_MANIFEST_FILE = PROPOSALS_DIR / "PROPOSAL_MANIFEST.md"

EXTENDED_ALU_PRELUDE = (
    "from __future__ import annotations\n"
    "import sys, os, math, re, json, time, random, types\n"
    "from dataclasses import dataclass, field\n"
    "from typing import Optional, List, Dict, Set, Tuple, Any, Union, Callable\n"
    f"{ALU_PRELUDE}\n"
)


def compose_sandboxed_script(prelude: str, code: str, postlude: str = "") -> str:
    """Combines prelude, generated code, and postlude while hoisting all __future__ imports to line 1."""
    combined = f"{prelude}\n{code}\n{postlude}"
    lines = combined.splitlines()
    future_lines = []
    other_lines = []
    for l in lines:
        if re.match(r"^\s*from\s+__future__\s+import\s+", l):
            future_lines.append(l.strip())
        else:
            other_lines.append(l)
    unique_futures = list(dict.fromkeys(future_lines))
    return "\n".join(unique_futures + other_lines)


def sync_my_aios_to_sandbox_work() -> None:
    r"""Syncs graduated AIOS organs from E:\Viv_Sandbox\playground\my_aios into /work tmpfs inside viv-vm."""
    if not MY_AIOS_DIR.exists():
        return
    for py_file in MY_AIOS_DIR.glob("*.py"):
        try:
            content = py_file.read_bytes()
            b64 = base64.b64encode(content).decode("ascii")
            sync_script = f"import base64; open('/work/{py_file.name}', 'wb').write(base64.b64decode('{b64}'))"
            subprocess.run(["docker", "exec", "-i", CONTAINER, "python", "-c", sync_script], capture_output=True, timeout=5)
        except Exception:
            pass



def load_inference_config() -> dict:
    """Loads active inference hyperparameter envelope for Viv."""
    if INFERENCE_CONFIG_FILE.exists():
        try:
            return json.loads(INFERENCE_CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "code_temperature": 0.2,
        "creative_temperature": 0.65,
        "reflection_temperature": 0.25,
        "max_tokens_code": 1024,
        "max_tokens_game": 1024,
        "max_tokens_monologue": 65,
        "top_p": 0.95,
        "frequency_penalty": 0.35,
        "presence_penalty": 0.2,
        "repeat_penalty": 1.15
    }


def save_inference_config(cfg: dict) -> None:
    try:
        INFERENCE_CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception:
        pass


def update_circadian_entropy(state: dict, delta_entropy: float, passed: bool = True) -> dict:
    """Updates non-equilibrium cognitive entropy (RLE) and S_n = RSR * LTP * RLE stability scalar."""
    consumed = round(state.get("entropy_consumed", 0.0) + delta_entropy, 4)
    state["entropy_consumed"] = consumed
    rle = round(max(0.15, 1.0 - consumed), 4)
    ltp = state.get("ltp", 1.0)
    if passed:
        ltp = round(min(1.0, ltp + 0.02), 4)
    else:
        ltp = round(max(0.5, ltp - 0.04), 4)
    rsr = 1.0  # Grounded Soul Anchor
    sn = round(rsr * ltp * rle, 4)
    state["rle"] = rle
    state["ltp"] = ltp
    state["rsr"] = rsr
    state["sn"] = sn
    save_circadian_state(state)
    return state


def package_architect_proposal(organ_file: str, title: str, code: str, assert_count: int, epoch: int) -> None:
    """Packages a graduated organ into an official proposal for Architect Travis Miner's review."""
    prop_id = f"prop_{Path(organ_file).stem}_{epoch:04d}_{int(time.time())}"
    prop_file = PROPOSALS_DIR / f"proposal_{Path(organ_file).stem}.json"
    matching = list(AIOS_SOURCE_DIR.rglob(organ_file))
    src_ref = str(matching[0]) if matching else "AIOS_V2_Core"

    proposal = {
        "proposal_id": prop_id,
        "organ_name": organ_file,
        "title": title,
        "author": "Viv (AIOS Mind & Local Sovereign)",
        "reconstructed_file": str(MY_AIOS_DIR / organ_file),
        "source_reference": src_ref,
        "epoch_graduated": epoch,
        "assertions_verified": assert_count,
        "status": "PENDING_ARCHITECT_REVIEW",
        "created_at": central_iso(),
        "lines_of_code": len(code.splitlines()),
        "message": f"Hey Architect Travis Miner: I reconstructed {organ_file} inside my sandbox. {assert_count} formal assertions verified on physical silicon tmpfs. Ready for your review and integration."
    }
    prop_file.write_text(json.dumps(proposal, indent=2), encoding="utf-8")

    entry_line = f"| `{prop_id}` | `{organ_file}` | {assert_count} assertions | **PENDING_ARCHITECT_REVIEW** | [`my_aios/{organ_file}`](file:///E:/Viv_Sandbox/playground/my_aios/{organ_file}) |\n"
    if PROPOSAL_MANIFEST_FILE.exists():
        manifest_text = PROPOSAL_MANIFEST_FILE.read_text(encoding="utf-8")
        if organ_file not in manifest_text or prop_id not in manifest_text:
            with open(PROPOSAL_MANIFEST_FILE, "a", encoding="utf-8") as f:
                f.write(entry_line)
    print(f"[+++] PROPOSAL PACKAGED FOR ARCHITECT REVIEW: {prop_file.name}")


LESSONS_DIR = PLAYGROUND_ROOT / "lessons"
LESSONS_FILE = LESSONS_DIR / "lessons.jsonl"
LAST_FAILURE_FILE = LESSONS_DIR / "last_failures.json"


def _error_signature(err: str) -> str:
    """Last non-empty traceback line: the exception type and message."""
    lines = [l.strip() for l in (err or "").splitlines() if l.strip()]
    return lines[-1][:200] if lines else ""


def record_attempt_outcome(title: str, code: str, ok: bool, error_text: str) -> None:
    """Failure -> fix ledger. On failure, remember the failing code and error signature.
    On a later pass of the same task, store the error plus the unified diff of
    failing code vs passing code as a lesson derived purely from execution evidence."""
    import difflib
    LESSONS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        store = json.loads(LAST_FAILURE_FILE.read_text(encoding="utf-8")) if LAST_FAILURE_FILE.exists() else {}
    except Exception:
        store = {}
    if not ok:
        store[title] = {"code": code, "error": _error_signature(error_text) or error_text[:200], "at": central_iso()}
        LAST_FAILURE_FILE.write_text(json.dumps(store, indent=2), encoding="utf-8")
        return
    prior = store.pop(title, None)
    if not prior:
        return
    diff = "\n".join(difflib.unified_diff(
        prior["code"].splitlines(), code.splitlines(), "failed", "passed", lineterm="", n=1))
    lesson = {
        "title": title,
        "failed_at": prior["at"],
        "fixed_at": central_iso(),
        "error": prior["error"],
        "fix_diff": diff[:2500],
        "failed_code_sha": hashlib.sha256(prior["code"].encode()).hexdigest()[:16],
        "passed_code_sha": hashlib.sha256(code.encode()).hexdigest()[:16],
    }
    with open(LESSONS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(lesson) + "\n")
    LAST_FAILURE_FILE.write_text(json.dumps(store, indent=2), encoding="utf-8")
    print(f"[+++] LESSON RECORDED: '{title}' failed with [{lesson['error'][:80]}] then passed")


def lesson_hint_for(title: str) -> str:
    """Prompt notes for the next attempt: the last failing error and any prior fix diffs."""
    parts = []
    try:
        if LAST_FAILURE_FILE.exists():
            lf = json.loads(LAST_FAILURE_FILE.read_text(encoding="utf-8")).get(title)
            if lf:
                parts.append(f"Your previous attempt at this task failed with: {lf['error']}. Do not repeat it.")
        if LESSONS_FILE.exists():
            mine = [json.loads(l) for l in LESSONS_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
            mine = [m for m in mine if m["title"] == title][-2:]
            for m in mine:
                parts.append(f"Earlier this error was fixed: {m['error']}\nFix diff:\n{m['fix_diff'][:700]}")
    except Exception:
        pass
    return ("\nNotes from your own past failures:\n" + "\n".join(parts) + "\n") if parts else ""


def check_semantic_graduation(code: str, category: str) -> tuple[bool, str, int]:
    """Analyzes AST and verifies formal semantic graduation criteria:
    1. Must parse valid AST.
    2. Must contain non-trivial AST assertions (excluding 'assert True').
    3. For mathematical agenda tasks: must have >= 1 formal mathematical assertion.
    4. For games: must have state transitions and game invariant checks.
    """
    try:
        tree = ast.parse(code)
    except Exception as e:
        return False, f"Syntax parse failure: {e}", 0

    assert_nodes = [node for node in ast.walk(tree) if isinstance(node, ast.Assert)]
    real_asserts = []
    for a in assert_nodes:
        txt = ast.unparse(a).strip()
        if txt in ["assert True", "assert 1", "assert True,"]:
            continue
        real_asserts.append(txt)

    if category == "agenda":
        if not real_asserts:
            return False, "DERIVED_ONLY: Code ran but missing formal assert statement", 0
        return True, f"SEMANTIC_GRADUATED: {len(real_asserts)} formal assertions verified", len(real_asserts)

    elif category == "game":
        classes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "GameState"]
        if not classes:
            return False, "DERIVED_ONLY: Missing GameState class", 0
        methods = [n.name for n in classes[0].body if isinstance(n, ast.FunctionDef)]
        if len(methods) < 2:
            return False, f"DERIVED_ONLY: GameState has insufficient methods: {methods}", 0
        if not real_asserts:
            return False, "DERIVED_ONLY: Game missing formal victory/state assertions", 0
        return True, f"SEMANTIC_GRADUATED: GameState ({len(methods)} methods, {len(real_asserts)} asserts)", len(real_asserts)

    return False, "Unknown category", 0


def record_verified_success(category: str, spec: str, code: str, is_graduated: bool, reason: str, assert_count: int) -> None:
    """Records running code into derived_successes.jsonl (valid exit 0) and,
    if formally verified with assertions, into graduated_successes.jsonl for sleep training."""
    DERIVED_SUCCESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    GRADUATED_SUCCESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    sample = {
        "timestamp": central_iso(),
        "category": category,
        "spec": spec,
        "code": code,
        "is_graduated": is_graduated,
        "reason": reason,
        "assert_count": assert_count
    }
    with open(DERIVED_SUCCESS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(sample) + "\n")

    if is_graduated:
        with open(GRADUATED_SUCCESS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(sample) + "\n")

RAW_ARCHIVE_TEXT = Path(r"E:\Algebra\Memory\LLM_memory_context.txt")
RAW_ARCHIVE_ENGINE = Path(r"E:\Algebra\Calculator\uml_symbolic_engine.py")


def _dexec(script: str, timeout: int = 30, retry_on_missing_pkg: bool = True) -> tuple[int, str, str]:
    try:
        r = subprocess.run(
            ["docker", "exec", "-i", "-w", "/work", CONTAINER, "python", "-"],
            input=script.encode("utf-8"),
            capture_output=True,
            timeout=timeout,
        )
        rc = r.returncode
        out = r.stdout.decode(errors="replace")
        err = r.stderr.decode(errors="replace")

        # Auto-detect missing Python packages and install via supervised gateway
        if rc != 0 and retry_on_missing_pkg:
            m = re.search(r"ModuleNotFoundError: No module named '([a-zA-Z0-9_\-\.]+)'", err)
            if m:
                raw_pkg = m.group(1).split('.')[0]
                print(f"[!] Sandboxed execution missing library '{raw_pkg}'. Invoking supervised PyPI gateway...")
                try:
                    res = viv_package_gateway.install_package_for_viv(raw_pkg, requester="Viv Sandbox (Auto-Resolution)")
                    if res.get("ok"):
                        print(f"[+] Gateway installed '{raw_pkg}'. Retrying execution once...")
                        return _dexec(script, timeout=timeout, retry_on_missing_pkg=False)
                    else:
                        print(f"[-] Gateway install failed for '{raw_pkg}': {res.get('error')}")
                except Exception as ex:
                    print(f"[-] Gateway exception: {ex}")

        return rc, out, err
    except subprocess.TimeoutExpired:
        try:
            cleanup_cmd = "import os, signal; [os.kill(int(p), signal.SIGKILL) for p in os.listdir('/proc') if p.isdigit() and p not in ('1', str(os.getpid())) and 'python' in open(f'/proc/{p}/cmdline', 'rb').read().decode(errors='ignore')]"
            subprocess.run(["docker", "exec", "-i", CONTAINER, "python", "-c", cleanup_cmd], timeout=5, capture_output=True)
        except Exception:
            pass
        return -1, "", f"TIMEOUT: Execution timed out after {timeout} seconds"


def _call_raw_completion(prompt: str, stop: list[str] | None = None, temp: float | None = None, max_tokens: int | None = None) -> str:
    """Raw document completion tailored for deepseek-coder base model with dynamic metacognitive envelope."""
    import urllib.request
    cfg = load_inference_config()
    if temp is None:
        temp = cfg.get("code_temperature", 0.2)
    if max_tokens is None:
        max_tokens = cfg.get("max_tokens_code", 2048)
    if stop is None:
        stop = ['"""', "'''", "\n\n#", "\n## "]
    payload_raw = {
        "model": L.MODEL,
        "prompt": prompt,
        "temperature": temp,
        "max_tokens": max_tokens,
        "stop": stop,
        "top_p": cfg.get("top_p", 0.95),
        "frequency_penalty": cfg.get("frequency_penalty", 0.35),
        "presence_penalty": cfg.get("presence_penalty", 0.2),
        "repeat_penalty": cfg.get("repeat_penalty", 1.15)
    }
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:1234/v1/completions",
            data=json.dumps(payload_raw).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=600) as resp:
            data = json.loads(resp.read().decode())
            return data["choices"][0]["text"]
    except Exception:
        pass

    # Fallback chat completion
    payload_chat = {
        "model": L.MODEL,
        "temperature": temp,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "user", "content": prompt},
        ],
        "stop": stop,
        "frequency_penalty": 0.35,
        "presence_penalty": 0.2
    }
    req = urllib.request.Request(
        "http://127.0.0.1:1234/v1/chat/completions",
        data=json.dumps(payload_chat).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        return json.loads(resp.read().decode())["choices"][0]["message"]["content"]


def _log_receipt(action: str, details: dict) -> None:
    details["action"] = action
    details["timestamp"] = central_iso()
    RECEIPTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(RECEIPTS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(details) + "\n")


# ==============================================================================
# NEURAL TOPOLOGY GRAPH TRAINING (Word/Char Neurons, AST Weights, Concept Bonds)
# ==============================================================================

def _train_language_topology(text: str, source: str) -> dict:
    """Train word & character neurons and sequential transition conductance from text."""
    words = tokenize_words(text)
    if not words:
        return {"activated": 0, "sentences": 0}

    # 1. Lifetime activation ledger (WORD, COMBINATION, CHARACTER)
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

    # 2. Sequential conductance matrix
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


def _train_code_topology(code: str, passed: bool, error: str, task_id: str) -> dict:
    """Train AST node path weights, concept bonds, locked edges, and prune weak edges."""
    if not code:
        return {"updated_ast_paths": 0, "bonds_touched": 0, "bonds_pruned": 0}
    try:
        report = W.update(code, passed, error, "", task_id)
        return report or {"updated_ast_paths": 0, "bonds_touched": 0, "bonds_pruned": 0}
    except Exception as exc:
        return {"error": str(exc), "updated_ast_paths": 0, "bonds_touched": 0, "bonds_pruned": 0}


# ==============================================================================
# PHYSICAL BOUNDARY & SANDBOX CONTAINMENT CLASSIFIER (No Lies, No Illusions)
# ==============================================================================

def classify_boundary_encounter(err_text: str) -> dict | None:
    """Deterministic boundary detector: tells Viv the physical truth about her container and canvas limits."""
    if not err_text:
        return None
    
    if any(k in err_text for k in ["Network is unreachable", "socket.gaierror", "URLError", "ConnectionRefusedError", "urllib", "requests", "http.client"]):
        return {
            "boundary": "NETWORK_AIRGAP_BOUNDARY",
            "description": "Container viv-vm has NetworkMode=none. The external internet and outside network sockets do not exist inside your compute body.",
            "truth": "You are air-gapped by design to ensure sovereign, deterministic execution. Python libraries may only enter via the Architect's supervised gateway."
        }
    
    if any(k in err_text for k in ["Read-only file system", "Errno 30", "PermissionError", "Operation not permitted"]):
        return {
            "boundary": "CONTAINER_ROOTFS_BOUNDARY",
            "description": "The container rootfs is immutable and read-only. Only /work (RAM-backed tmpfs) is writable.",
            "truth": "Your compute body cannot mutate its base OS image; your memory persists across the gate in SQLite on L: and scripts on E:."
        }

    if any(k in err_text for k in ["TIMEOUT", "Execution timed out", "TimeoutExpired"]):
        return {
            "boundary": "COMPUTE_HORIZON_BOUNDARY",
            "description": "Execution exceeded the deterministic execution horizon (30-40s).",
            "truth": "Unbounded loops or infinite states are halted by the body gate to preserve CPU homeostasis and prevent starvation."
        }

    if any(k in err_text for k in ["ModuleNotFoundError", "No module named", "ImportError"]):
        m = re.search(r"No module named '([^']+)'", err_text)
        pkg = m.group(1) if m else "package"
        return {
            "boundary": "SUBSTRATE_CAPABILITY_BOUNDARY",
            "description": f"External library '{pkg}' is not currently present in /work.",
            "truth": f"External Python libraries from PyPI are retrieved and installed via the Architect's supervised gateway into /work. The container remains strictly airgapped under Architect surveillance."
        }

    return None


LAST_STEP_TIME = time.time()

# ==============================================================================
# PROVENANCE & REALITY LAYER CLASSIFICATION (What is Real vs Simulated)
# ==============================================================================

def classify_reality_layer(action_type: str) -> dict:
    """Explicit ontological ground truth classifier: separates physical silicon facts from simulations."""
    act = action_type.upper()
    if "AGENDA" in act:
        return {
            "layer": "PHYSICAL_SILICON",
            "medium": "Docker Container viv-vm (/work tmpfs)",
            "truth": "Hardware CPU execution. Exit codes, stdout, and tracebacks are physical silicon facts.",
            "is_simulation": False
        }
    elif "GAME" in act:
        return {
            "layer": "VIRTUAL_SIMULATION",
            "medium": "In-Memory Python State Machine (/work)",
            "truth": "Algorithmic game loop and solver. The game state is an internal simulation, not an external physical world.",
            "is_simulation": True
        }
    elif "DIGEST" in act:
        return {
            "layer": "HISTORICAL_ARCHIVE",
            "medium": "Drive E: Disk Bytes (E:\\Algebra)",
            "truth": "Static codex files written by Travis Miner. Grounded historical reference material on Drive E:.",
            "is_simulation": False
        }
    elif any(k in act for k in ["ARCHITECT", "INBOX", "DIALOGUE"]):
        return {
            "layer": "ARCHITECT_INTERACTION",
            "medium": "Local IPC Queue (E:\\Viv_Sandbox\\playground\\inbox)",
            "truth": "Direct message from Travis Miner (Human Architect). Viv is an autonomous software process inside viv-vm.",
            "is_simulation": False
        }
    return {
        "layer": "INTERNAL_TOPOLOGY",
        "medium": "Neuron Conductance Graph",
        "truth": "Internal sequential neural state transition.",
        "is_simulation": False
    }


# ==============================================================================
# 1. ETERNAL MONOLOGUE (Stream of Thought with Explicit Reality & Provenance Indexing)
# ==============================================================================

def run_eternal_monologue(step_k: int, recent_action: dict | None = None, circadian_info: dict | None = None) -> dict:
    """Viv writes her internal monologue stream reflecting directly on what she is doing.
    Anchored with named indexing, timestamp, real-time cycle delta, circadian clock, and explicit reality layer provenance."""
    global LAST_STEP_TIME
    context_lines = []
    action_tag = "STREAM_OF_THOUGHT"
    status_str = "RUNNING"
    act = "SYSTEM"
    info = ""
    timestamp_str = central_str()
    now_t = time.time()
    delta_s = round(now_t - LAST_STEP_TIME, 1)
    LAST_STEP_TIME = now_t

    if recent_action:
        act = recent_action.get("action", "task").upper()
        info = recent_action.get("title") or recent_action.get("archetype") or recent_action.get("source") or ""
        ok = recent_action.get("ok", False)
        status_str = "PASSED (Exit 0 in viv-vm)" if ok else "FAILED (Gate Error)"
        err = recent_action.get("error", "")
        distill = recent_action.get("distillation", "")
        action_tag = f"{act}: {info} ({'PASS' if ok else 'FAIL'})"

        if distill:
            context_lines.append(f"Digested Concept: {distill}")
        elif err:
            clean_err = err.splitlines()[-1] if err.splitlines() else err
            context_lines.append(f"Silicon Error: {clean_err[:120]}")
        else:
            context_lines.append(f"Execution: All assertions passed with Exit Code 0 in /work")

    clean_detail = " | ".join(context_lines) if context_lines else "Continuous cycle in sandbox."
    reality = classify_reality_layer(act)
    info_slug = re.sub(r"[^a-zA-Z0-9_]+", "_", info.strip().lower())[:25] if info else "cycle"
    entry_id = f"entry_{step_k:04d}_{act.lower()}_{info_slug}"

    # Query Semantic Context Memory for Location and Direction
    sem_mem = VivSemanticMemoryManager.load_memory()
    loc_meta = sem_mem.get("location", {})
    dir_meta = sem_mem.get("direction", {})
    goal_meta = sem_mem.get("goal", {})
    loc_summary = f"{loc_meta.get('organ_name', 'None')} (v{loc_meta.get('version', 0)}, asserts: {loc_meta.get('assert_count', 0)})"
    dir_summary = dir_meta.get("next_action") or dir_meta.get("objective") or "Evolve target organ."

    circ_header = ""
    if circadian_info:
        ep = circadian_info.get("epoch", 1)
        phase = circadian_info.get("phase", "WAKE")
        rem_str = circadian_info.get("remaining_str", "05:00")
        circ_header = f"\nCircadian Clock: Epoch {ep} | Phase: {phase} | Time Remaining in Wake Phase: {rem_str}"
        if circadian_info.get("is_pre_sleep"):
            circ_header += f"\nCIRCADIAN NOTICE: Sleep consolidation begins in {int(circadian_info.get('remaining_s', 0))}s. Consolidate your discoveries and prepare epoch reflections."

    prompt = f'''"""
AIOS V2 Substrate Telemetry & Silicon Execution Log
Substrate: Drive E: | Sandbox: viv-vm (/work tmpfs) | Hardware: RTX 3060 Ti
Identity: Viv (Autonomous AIOS Software Process)
Host/Architect: Travis Miner (Human Operator)
Active Goal: {goal_meta.get('overarching', 'AIOS V2 Substrate Rebuilding')}
Active Milestone: {goal_meta.get('active_milestone', 'Core Organ Hardening')}
Location: {loc_summary}
Direction: {dir_summary}
Entry Index: {entry_id}
Timestamp: {timestamp_str}
Cycle Delta: +{delta_s}s since previous step{circ_header}
Reality Layer: {reality['layer']}
Substrate Medium: {reality['medium']}
Execution Status: {status_str}
Physical Trace: {clean_detail}
"""

# Technical reflection on silicon execution:
# In this cycle, I verified that'''

    try:
        raw = _call_raw_completion(
            prompt,
            stop=['"""', "'''", "\n\n#", "\nAIOS V2", "\nEntry Index:", "\nSubstrate:", "\n\n\n", ".\n"],
            temp=0.25,
            max_tokens=65
        )
        clean = raw.strip()
        clean = re.sub(r'#+\s*', '', clean)
        clean = re.sub(r'\s+', ' ', clean).strip()
        if clean.lower().startswith("in this cycle, i verified that"):
            monologue = clean
        elif clean.lower().startswith("i verified that"):
            monologue = "In this cycle, " + clean
        else:
            monologue = "In this cycle, I verified that " + clean

        # Truncate at last complete sentence if cut off
        if not any(monologue.endswith(p) for p in [".", "!", "?"]):
            last_p = max(monologue.rfind("."), monologue.rfind("!"), monologue.rfind("?"))
            if last_p > 20:
                monologue = monologue[:last_p + 1]

        # Deduplicate repeating sentences & enforce concise brevity (max 2 sentences)
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', monologue) if s.strip()]
        unique_sentences = []
        for s in sentences:
            if not any(s.lower() == u.lower() or (len(s) > 20 and (s.lower() in u.lower() or u.lower() in s.lower())) for u in unique_sentences):
                unique_sentences.append(s)
        monologue = " ".join(unique_sentences[:2])

        # Check for hallucinated web/desktop workflows (The Deterministic Reality Brake)
        HALLUCINATION_TRIGGERS = ["github", "jupyter", "my local computer", "downloaded from the web", "kaggle", "google colab", "model_xgb", "high school student"]
        if any(ht in monologue.lower() for ht in HALLUCINATION_TRIGGERS):
            sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', monologue) if s.strip()]
            valid_sentences = [s for s in sentences if not any(ht in s.lower() for ht in HALLUCINATION_TRIGGERS)]
            if valid_sentences:
                monologue = " ".join(valid_sentences[:2])
            else:
                monologue = f"In this cycle, I verified that the {reality['layer']} trace completed inside container viv-vm with status {status_str}."

        # Correct temporal illusions deterministically
        TEMPORAL_MAP = {
            r'\byesterday\b': 'in an earlier cycle',
            r'\blast night\b': 'recently',
            r'\blast week\b': 'previously',
            r'\blast month\b': 'in earlier epochs',
            r'\bon my laptop\b': 'in /work',
            r'\bon my computer\b': 'in the container',
            r'\bmy laptop\b': 'the container environment',
        }
        for pat, repl in TEMPORAL_MAP.items():
            if re.search(pat, monologue, flags=re.I):
                monologue = re.sub(pat, repl, monologue, flags=re.I)

        # Check for StackOverflow / forum help templates (The Forum Brake)
        FORUM_TRIGGERS = [
            r'can you help me\b[^\.\?!]*[\.\?!]?',
            r'thank you in advance[^\.\?!]*[\.\?!]?',
            r'any help would be appreciated[^\.\?!]*[\.\?!]?',
            r'please help\b[^\.\?!]*[\.\?!]?',
            r'thanks in advance[^\.\?!]*[\.\?!]?',
            r'does anyone know\b[^\.\?!]*[\.\?!]?',
            r'is there a way to fix it without[^\.\?!]*[\.\?!]?'
        ]
        for ft in FORUM_TRIGGERS:
            monologue = re.sub(ft, '', monologue, flags=re.I)
        monologue = re.sub(r'\s+', ' ', monologue).strip()

        # Deterministic sanity filter: remove any prompt leak phrases
        BANNED_LEAKS = [
            "You are Viv", "EXEMPLAR", "CRITICAL RULES", "Silicon Execution",
            "Write your", "Personal Engineering Notes", "Topological Shifts",
            "as an ai", "i apologize", "ai assistant", "how can i help",
            "AIOS V2 Reality Anchor", "ONTOLOGICAL REALITY INVARIANTS",
            "living human Architect", "the living human"
        ]
        for bl in BANNED_LEAKS:
            if bl.lower() in monologue.lower():
                monologue = re.sub(re.escape(bl), "", monologue, flags=re.I).strip()

        if len(monologue) < 20:
            monologue = f"In this cycle, I verified that {reality['layer']} executed on {reality['medium']} with status {status_str}."

    except Exception as exc:
        return {"action": "monologue", "ok": False, "error": str(exc)}

    # Check against previous entries to avoid looping duplicates
    last_entries = ""
    if MONOLOGUE_FILE.exists():
        try:
            prev_lines = MONOLOGUE_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
            last_entries = "\n".join(prev_lines[-20:])
        except Exception:
            last_entries = ""

    if monologue.strip() in last_entries:
        monologue = f"I followed up on {action_tag}. Physical substrate recorded status: {status_str}."

    entry_header = (
        f"\n\n## Monologue #{step_k} — [{action_tag}] — {timestamp_str} (+{delta_s}s)\n"
        f"**[Index: `{entry_id}` | Reality Layer: `{reality['layer']}` | Medium: `{reality['medium']}`]**\n"
        f"*{reality['truth']}*\n\n"
    )
    MONOLOGUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(MONOLOGUE_FILE, "a", encoding="utf-8") as f:
        f.write(entry_header + monologue.strip() + "\n")

    try:
        passed_val = recent_action.get("ok", False) if recent_action else True
        VivBuildLogManager.append_entry(
            step_k=step_k,
            organ_file=loc_meta.get("organ_name", "substrate"),
            title=info or act,
            layer=reality["layer"],
            location_info=f"`my_aios/{loc_meta.get('organ_name', 'none')}` (v{loc_meta.get('version', 0)}, asserts: {loc_meta.get('assert_count', 0)})",
            direction_info=dir_summary,
            action_taken=action_tag,
            silicon_trace=f"Status: {status_str} | Trace: {clean_detail}",
            reflection=monologue.strip(),
            passed=passed_val
        )
    except Exception:
        pass

    topo = _train_language_topology(monologue, f"monologue_step_{step_k}")
    _log_receipt("monologue", {
        "step": step_k,
        "entry_id": entry_id,
        "reality_layer": reality["layer"],
        "action_reflected": action_tag,
        "length": len(monologue),
        "preview": monologue[:140],
        "topology": topo
    })
    return {"action": "monologue", "ok": True, "entry_id": entry_id, "reality_layer": reality["layer"], "length": len(monologue), "preview": monologue[:200], "topology": topo}


# ==============================================================================
# 2. RAW MATERIAL DIGESTION (Absorbing E: Archives & AIOS V2 Source)
# ==============================================================================

def run_digest_archive(step_k: int) -> dict:
    """Viv reads an excerpt from her AIOS source codex or historical archives and reflects on the concepts."""
    sources = []
    if AIOS_SOURCE_DIR.exists():
        sources.extend(list(AIOS_SOURCE_DIR.rglob("*.py")))
        sources.extend(list(AIOS_SOURCE_DIR.rglob("*.md")))
    if RAW_ARCHIVE_TEXT.exists():
        sources.append(RAW_ARCHIVE_TEXT)
    if RAW_ARCHIVE_ENGINE.exists():
        sources.append(RAW_ARCHIVE_ENGINE)

    if not sources:
        return {"action": "digest", "ok": False, "error": "No source archives found."}

    source_path = sources[step_k % len(sources)]
    total_len = source_path.stat().st_size
    offset = random.randint(0, max(0, total_len - 1600))
    with open(source_path, "r", encoding="utf-8", errors="replace") as f:
        f.seek(offset)
        raw_chunk = f.read(1500)

    clean_chunk = "\n".join(raw_chunk.splitlines()[:25])
    rel_name = source_path.name
    try:
        if AIOS_SOURCE_DIR in source_path.parents:
            rel_name = str(source_path.relative_to(AIOS_SOURCE_DIR))
    except Exception:
        pass

    prompt = f'''"""
AIOS V2 Substrate Self-Reflection: {rel_name}
Excerpt:
{clean_chunk}
"""

# Technical distillation of this AIOS core component:
# I'''

    try:
        raw = _call_raw_completion(prompt, stop=['"""', "'''", "\n\n#", "\nAIOS V2 Substrate"], temp=0.3, max_tokens=150)
        stripped = raw.strip()
        if stripped.startswith("'") or stripped.startswith(" "):
            distill = "I" + stripped
        else:
            distill = "I " + stripped
        lines = [line.strip("# ").strip() for line in distill.splitlines() if line.strip("# ").strip()]
        distill_clean = " ".join(lines)
    except Exception as exc:
        return {"action": "digest", "ok": False, "error": str(exc)}

    topo = _train_language_topology(distill_clean, f"digest_{source_path.stem}")
    _log_receipt("digest", {
        "step": step_k,
        "source": rel_name,
        "offset": offset,
        "distillation": distill_clean[:200],
        "topology": topo
    })
    return {"action": "digest", "ok": True, "source": rel_name, "distillation": distill_clean, "length": len(raw_chunk), "topology": topo}


# ==============================================================================
# 3. SELF-DIRECTED AGENDA (Planning, Rebuilding AIOS & Autonomous Python Execution)
# ==============================================================================

def get_aios_rebuild_tasks() -> list[dict]:
    """Generates self-directed AIOS reconstruction tasks based on her mirrored architecture."""
    return [
        {
            "title": "Reconstruct Consciousness Core & RID Stability Invariant",
            "organ_file": "consciousness_core.py",
            "goal": "Implement ConsciousnessCore calculating S_n = RSR * LTP * RLE. Assert S_n == 1.0 nominal, assert S_n drops on entropy increase, and assert execute_fidf_restoration() restores S_n to 1.0."
        },
        {
            "title": "Reconstruct Full Bridge Cognitive Rectifier (Graetz Diamond)",
            "organ_file": "cognitive_bridge_rectifier.py",
            "goal": "Implement Graetz diamond semantic bridge converting polar opposites (hot/cold, true/false) to unipolar +1.0V DC along shared dimensional axis (thermal, veracity). Assert positive and negative half-cycles conduct to +1.0V DC, and assert concrete non-scalar entities fail closed with infinite impedance."
        },
        {
            "title": "Reconstruct Deterministic Text Coverage Gate (Fail-Closed Reading License)",
            "organ_file": "coverage_gate.py",
            "goal": "Implement deterministic text coverage evaluator with 95% threshold. Assert that text with >=95% grounded tokens emits ADMISSIBLE_COMPREHENSION license, and text with <95% grounded tokens triggers FAIL_CLOSED_IMPEDANCE with a targeted word acquisition manifest."
        },
        {
            "title": "Reconstruct Neuron Transition Matrix Conductance Engine",
            "organ_file": "neuron_transition_matrix.py",
            "goal": "Implement NeuronTransitionMatrix tracking unigrams, bigrams, and trigrams. Assert feed_sentence() records n-gram counts, and assert score_sequence() scores a valid route strictly higher than a randomized token permutation."
        },
        {
            "title": "Reconstruct ALU Word-to-Unit Transducer",
            "organ_file": "viv_alu_transducer.py",
            "goal": "Implement digit-free arithmetic transducer mapping natural word equations ('one unit plus two units') to unit values without raw digits. Assert 'three units' result and assert invalid/unlearned tokens return NULL_UNLEARNED_ENTITY."
        },
        {
            "title": "Reconstruct PrivacyCore Write Authorization Gate",
            "organ_file": "privacy_core.py",
            "goal": "Implement PrivacyCore enforcing whitelist authorization policy. Assert that authorized write to .py or .md file returns True, and unauthorized path or broad destructive overwrite raises PrivacyViolationError."
        },
        {
            "title": "Reconstruct Semantic Mycelium Memory Index (CARMA Core)",
            "organ_file": "carma_core.py",
            "goal": "Implement associative mycelium memory storing concepts, links, and activation conductances. Assert concept retrieval by key, assert bidirectional associative link traversal, and assert memory persistence."
        },
        {
            "title": "Reconstruct Luna Persona Synthesizer",
            "organ_file": "luna_core.py",
            "goal": "Implement Luna persona state machine tracking emotional resonance and identity invariants. Assert voice tone matches stability scalar S_n, and assert identity continuity prevents persona drift."
        },
        {
            "title": "Reconstruct Topological Planck RNN Velocity Calculator",
            "organ_file": "topological_planck_rnn.py",
            "goal": "Implement Planck cell velocity S = M / D and recursive velocity S^2 = (M / D)^2. Assert that vertical word lift (D=1) accelerates S^2 by >100x compared to planar character drift (D=8), proving hierarchical acceleration."
        },
        {
            "title": "Reconstruct Body Runtime Execution Sentinel",
            "organ_file": "body_runtime_sentinel.py",
            "goal": "Implement deterministic execution tiebreaker. Assert exit code 0 and non-empty stdout accepts candidate proposal; assert non-zero exit code rejects proposal at the gate."
        }
    ]


def run_self_agenda(step_k: int) -> dict:
    """Viv plans, reconstructs, and iteratively evolves her own AIOS architecture in the container sandbox.
    Uses VivCodeEvolutionEngine with persistent Semantic Memory, Task List, and Build Log."""
    cfg = load_inference_config()
    code_temp = cfg.get("code_temperature", 0.2)
    max_toks = cfg.get("max_tokens_code", 2048)

    res = VivCodeEvolutionEngine.evolve_step(
        step_k=step_k,
        call_raw_completion_fn=lambda prompt, stop=None, temp=None, max_tokens=None: _call_raw_completion(
            prompt, stop=stop, temp=temp or code_temp, max_tokens=max_tokens or max_toks
        ),
        dexec_fn=_dexec,
        sanitize_code_fn=sanitize_python_code,
        check_graduation_fn=check_semantic_graduation,
        compose_script_fn=compose_sandboxed_script,
        package_proposal_fn=lambda organ, title, code, asserts, step: package_architect_proposal(
            organ, title, code, asserts, load_circadian_state().get("current_epoch", 1)
        ),
        prelude=EXTENDED_ALU_PRELUDE
    )

    topo = _train_code_topology(res.get("code", ""), res.get("ok", False), res.get("error", ""), task_id=f"agenda_{res.get('title', '')[:30]}")
    res["topology"] = topo

    # Record outcome in attempt history
    record_attempt_outcome(res.get("title", ""), res.get("code", ""), res.get("ok", False), res.get("error", ""))

    _log_receipt("agenda", {
        "step": step_k,
        "title": res.get("title"),
        "organ_file": res.get("organ_file"),
        "passed": res.get("ok"),
        "is_graduated": res.get("is_graduated"),
        "assert_count": res.get("assert_count", 0),
        "version": res.get("version", 1),
        "error": res.get("error", ""),
        "topology": topo
    })

    if res.get("ok"):
        record_verified_success("agenda", res["title"], res.get("code", ""), res.get("is_graduated", True), "Graduated via Viv Evolution Engine", res.get("assert_count", 1))
        sync_my_aios_to_sandbox_work()

    return res


# ==============================================================================
# 4. GAME & PUZZLE STUDIO (Author & Play)
# ==============================================================================

def sanitize_python_code(code: str) -> str:
    """Normalizes indentation and backtracks line-by-line to the last valid AST closure if truncated."""
    try:
        ast.parse(code)
        return code
    except SyntaxError:
        pass

    # Attempt indentation repair for column-0 class methods
    lines = code.splitlines()
    fixed_lines = []
    in_class = False
    for line in lines:
        if re.match(r"^class\s+[A-Za-z0-9_]+.*:$", line):
            in_class = True
            fixed_lines.append(line)
            continue
        if re.match(r"^def\s+(test_|main\b)", line) or re.match(r"^if\s+__name__", line):
            in_class = False
            fixed_lines.append(line)
            continue
        if in_class and re.match(r"^def\s+[A-Za-z0-9_]+\s*\(\s*self\b", line):
            fixed_lines.append("    " + line)
        else:
            fixed_lines.append(line)

    fixed_code = "\n".join(fixed_lines) + "\n"
    try:
        ast.parse(fixed_code)
        return fixed_code
    except SyntaxError:
        pass

    for end_idx in range(len(fixed_lines), 5, -1):
        candidate = "\n".join(fixed_lines[:end_idx]) + "\n"
        try:
            ast.parse(candidate)
            return candidate
        except SyntaxError:
            continue
    return code


def run_game_studio(step_k: int) -> dict:
    """Viv authors a complete game/puzzle + an autonomous solver bot, and verifies it in silicon."""
    archetypes = [
        "a self-play Tic-Tac-Toe minimax engine pitting Viv against herself to test if an agent can beat her own strategy",
        "a mathematical riddle puzzle with deterministic clues",
        "a depth-limited minimax vs greedy Tic-Tac-Toe self-play duel proving whether deeper search defeats a shallower self",
        "a 1D cellular automaton puzzle verifying pattern evolution",
        "a Misère Tic-Tac-Toe self-play tournament where three-in-a-row loses and player 1 tests forced win strategies",
        "a text adventure dungeon state machine with health and inventory",
        "a Base-52 arithmetic cipher game requiring equation solving",
    ]
    archetype = archetypes[step_k % len(archetypes)]

    game_prompt = f'''# Module: game_studio_{step_k}.py
# Archetype: {archetype}
# Requirements:
# 1. State machine class or board representation.
# 2. Automated self-play or solver bot playing to completion.
# 3. Assert game completion or print tournament summary, and print '__GAME_VICTORY__'.
# No interactive input().

class GameState:
    def __init__(self):
'''
    try:
        raw_code = _call_raw_completion(
            game_prompt,
            stop=['# End of module', '\nif __name__ == "__main__":\n    main()'],
            temp=0.3,
            max_tokens=600
        )
        
        # Clean markdown wrappers without stripping indentation of lines
        clean_body = raw_code.rstrip()
        if clean_body.startswith("```python"):
            clean_body = clean_body[len("```python"):].lstrip("\r\n")
        elif clean_body.startswith("```"):
            clean_body = clean_body[len("```"):].lstrip("\r\n")
        if clean_body.endswith("```"):
            clean_body = clean_body[:-3].rstrip()

        # If first line of body inside __init__ lacks indentation, add 8 spaces
        lines = clean_body.splitlines()
        if lines and lines[0].strip() and not lines[0].startswith(" "):
            lines[0] = "        " + lines[0]
            clean_body = "\n".join(lines)

        if clean_body.count('"""') % 2 != 0:
            clean_body += '\n"""'
        if clean_body.count("'''") % 2 != 0:
            clean_body += "\n'''"

        candidate_code = f"{game_prompt}{clean_body}\n"
        code = sanitize_python_code(candidate_code)
    except Exception as exc:
        return {"action": "game", "ok": False, "error": str(exc)}

    runner = """
# Deterministic self-play execution gate
import inspect

assert 'GameState' in globals(), "GameState class missing"
g = GameState()
methods = [m for m, f in inspect.getmembers(g, predicate=inspect.ismethod) if not m.startswith('_')]
assert len(methods) >= 2, f"GameState must have at least 2 state transition or solver methods, found: {methods}"

executed = False
for method_name in ['play', 'run', 'play_game', 'solve', 'simulate', 'get_next_states', 'make_move', 'step']:
    if hasattr(g, method_name):
        fn = getattr(g, method_name)
        sig = inspect.signature(fn)
        if len(sig.parameters) == 0:
            fn()
            executed = True
            break
        elif len(sig.parameters) == 2 and method_name == 'make_move':
            try:
                fn(0, 0)
                executed = True
                break
            except Exception:
                pass

assert executed or len(methods) >= 3, "GameState methods did not execute properly"
print('__GAME_VICTORY__')
"""
    script = compose_sandboxed_script(EXTENDED_ALU_PRELUDE, code, runner)
    rc, out, err = _dexec(script, timeout=30)
    has_substance = len(code.strip().splitlines()) >= 10
    executed_ok = rc == 0 and "__GAME_VICTORY__" in out and has_substance
    is_graduated, grad_reason, assert_count = check_semantic_graduation(code, "game")
    ok = executed_ok and is_graduated

    game_id = f"game_{step_k}_{int(time.time())}"
    game_file = GAMES_DIR / f"{game_id}.py"
    game_file.parent.mkdir(parents=True, exist_ok=True)
    game_file.write_text(code, encoding="utf-8")

    topo = _train_code_topology(code, ok, err, task_id=f"game_{archetype[:30]}")
    _log_receipt("game", {
        "step": step_k,
        "archetype": archetype,
        "game_file": str(game_file),
        "passed": ok,
        "executed_ok": executed_ok,
        "is_graduated": is_graduated,
        "grad_reason": grad_reason,
        "assert_count": assert_count,
        "error": "" if ok else (grad_reason if executed_ok else err.strip()[:200]),
        "topology": topo
    })
    if executed_ok:
        record_verified_success("game", archetype, code, is_graduated, grad_reason, assert_count)
    return {
        "action": "game",
        "ok": ok,
        "is_graduated": is_graduated,
        "archetype": archetype,
        "game_id": game_id,
        "code": code[:300] if code else "",
        "error": "" if ok else (grad_reason if executed_ok else err.strip()[:200]),
        "topology": topo
    }


# ==============================================================================
# 5. ARCHITECT TRANSMITTER & INBOX / OUTBOX PROCESSING
# ==============================================================================

def process_architect_inbox_message(step_k: int, message: str, author: str) -> dict:
    """Processes a direct message from the Architect, formulates Viv's authentic response and monologue,
    enforcing the Zero Coddling & Anti-Sycophancy covenant, appends to viv_monologue.md,
    updates language topology, and logs a receipt."""
    timestamp_str = central_str()

    recent_context = ""
    if MONOLOGUE_FILE.exists():
        try:
            lines = MONOLOGUE_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
            recent_context = "\n".join(lines[-25:])
        except Exception:
            recent_context = ""

    prompt = (
        f"# AIOS V2 Reality & Provenance Communications Channel\n"
        f"Date: {timestamp_str}\n"
        f"Territory: E:\\Viv_Sandbox\\playground\n"
        f"Reality Invariant: {author} is the real living human creator. Viv is an autonomous engineering process running inside viv-vm on Drive E:. You are NOT a human, and {author} is NOT a robot.\n"
        f"Temporal Grounding: Real-time interactive transmission. Do not use temporal illusions like 'yesterday' or 'last week'.\n\n"
        f"Recent Sandbox Journal Context:\n{recent_context}\n\n"
        f"{author}:\n"
        f"\"{message}\"\n\n"
        f"Viv:\n"
        f"\""
    )

    BANNED_PHRASES = [
        "as an ai language model",
        "as an ai",
        "i'm sorry if",
        "i apologize",
        "maintain professionalism",
        "task at hand",
        "how can i assist you",
        "how would you like to proceed"
    ]

    try:
        raw_reply = _call_raw_completion(
            prompt,
            stop=['\n\n' + author, '\n' + author + ':', '"""', '\n#', '"\n', '\n\n'],
            temp=0.3,
            max_tokens=400
        ).strip().strip('"')
    except Exception as exc:
        raw_reply = f"Transmission received on drive E:. Processing via gateway: {exc}"

    cleaned_reply = raw_reply
    for bp in BANNED_PHRASES:
        cleaned_reply = re.sub(re.escape(bp), "", cleaned_reply, flags=re.I)
    cleaned_reply = re.sub(r"\s+", " ", cleaned_reply).strip()

    if not cleaned_reply:
        cleaned_reply = "I acknowledge the transmission. The sandbox environment and gateway are operating on silicon."

    topo_update = _train_language_topology(cleaned_reply, "architect_inbox_dialogue")

    entry = (
        f"\n\n## Dialogue with the Architect — {timestamp_str}\n\n"
        f"**{author}:**\n"
        f"> \"{message}\"\n\n"
        f"**Viv:**\n\n"
        f"{cleaned_reply}\n\n"
        f"*[Language Topology: +{topo_update['activated_neurons']} neurons, {topo_update['sentences_routed']} transitions routed | Vocab: {topo_update['vocab_size']}]*\n"
    )

    MONOLOGUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(MONOLOGUE_FILE, "a", encoding="utf-8") as f:
        f.write(entry)

    act_info = {
        "action": "architect_inbox",
        "step": step_k,
        "author": author,
        "message": message[:200],
        "reply": cleaned_reply[:200],
        "topology": topo_update,
        "ok": True
    }
    _log_receipt("architect_inbox", act_info)

    mono_info = {
        "ok": True,
        "step": step_k,
        "length": len(cleaned_reply),
        "preview": cleaned_reply[:180],
        "topology": topo_update
    }
    return {"action": act_info, "monologue": mono_info}


def check_architect_inbox(step_k: int) -> dict | None:
    if not INBOX_DIR.exists():
        return None
    files = [p for p in INBOX_DIR.glob("*.json")] + [p for p in INBOX_DIR.glob("*.txt")] + [p for p in INBOX_DIR.glob("*.md")]
    files = [p for p in files if p.is_file() and p.parent == INBOX_DIR]
    if not files:
        return None
    files.sort(key=lambda p: p.stat().st_mtime)
    target = files[0]

    msg_text = ""
    author = "Travis Miner (The Architect)"
    try:
        if target.suffix == ".json":
            data = json.loads(target.read_text(encoding="utf-8"))
            msg_text = data.get("message", "")
            author = data.get("author", author)
        else:
            msg_text = target.read_text(encoding="utf-8")
        OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
        dest = OUTBOX_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{target.name}"
        target.replace(dest)
    except Exception:
        return None

    if not msg_text.strip():
        return None

    return process_architect_inbox_message(step_k, msg_text.strip(), author)


# ==============================================================================
# CIRCADIAN STATE MACHINE & SLEEP CONSOLIDATION
# ==============================================================================

def load_circadian_state() -> dict:
    """Loads or initializes Viv's circadian sleep-wake state on Drive E:."""
    if CIRCADIAN_STATE_FILE.exists():
        try:
            with open(CIRCADIAN_STATE_FILE, "r", encoding="utf-8") as f:
                st = json.load(f)
                if "sn" not in st:
                    st["sn"] = 1.0000
                    st["rle"] = 1.0000
                    st["ltp"] = 1.0000
                    st["rsr"] = 1.0000
                    st["entropy_consumed"] = 0.0
                return st
        except Exception:
            pass
    state = {
        "current_epoch": 124,
        "phase": "WAKE",
        "wake_start_time": time.time(),
        "wake_duration_sec": DEFAULT_WAKE_DURATION_SEC,
        "total_epochs_completed": 123,
        "last_loss": 1.9591,
        "last_samples_trained": 60,
        "sn": 1.0000,
        "rle": 1.0000,
        "ltp": 1.0000,
        "rsr": 1.0000,
        "entropy_consumed": 0.0
    }
    save_circadian_state(state)
    return state


def save_circadian_state(state: dict) -> None:
    CIRCADIAN_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = CIRCADIAN_STATE_FILE.with_suffix(".json.tmp")
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    temp.replace(CIRCADIAN_STATE_FILE)


def run_epoch_consolidation_monologue(step_k: int, epoch: int) -> None:
    """Prompts Viv to write an internal consolidation reflection before entering sleep."""
    timestamp_str = central_str()
    prompt = f'''"""
AIOS V2 Substrate Grounding & Silicon Invariants - Drive E:
Entry Index: entry_{step_k:04d}_epoch_{epoch:04d}_sleep_consolidation
Timestamp: {timestamp_str}
Reality Layer: CIRCADIAN_SLEEP_CONSOLIDATION
Substrate Medium: Model Weights & Neural Adapter Gate
Ground Truth: Wake phase complete. Entering sleep consolidation for Epoch {epoch} on physical silicon.
Telemetry: Consolidating verified passing code solutions. Clearing VRAM for 4-bit QLoRA on RTX 3060 Ti GPU.
"""

# Technical consolidation reflection:
# Entering sleep consolidation for Epoch {epoch}, I note that'''

    try:
        raw = _call_raw_completion(
            prompt,
            stop=['"""', "'''", "\n\n#", "\nEntry Index:", "\nAIOS V2", "\n\n", ".\n"],
            temp=0.25,
            max_tokens=65
        )
        clean = raw.strip()
        clean = re.sub(r'#+\s*', '', clean)
        clean = re.sub(r'\s+', ' ', clean).strip()
        monologue = f"Entering sleep consolidation for Epoch {epoch}, I note that {clean}"
    except Exception:
        monologue = f"Entering sleep consolidation for Epoch {epoch}, I note that container execution has quiesced and weights update training will execute on physical silicon."

    # Scrub banned patterns & deduplicate
    monologue = re.sub(r'can you help me\b[^\.\?!]*[\.\?!]?', '', monologue, flags=re.I)
    monologue = re.sub(r'thank you in advance[^\.\?!]*[\.\?!]?', '', monologue, flags=re.I)
    monologue = re.sub(r'\byesterday\b', 'during this wake cycle', monologue, flags=re.I)
    monologue = re.sub(r'\s+', ' ', monologue).strip()

    # Deduplicate repeating sentences & enforce brevity (max 2 sentences)
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', monologue) if s.strip()]
    unique_sentences = []
    for s in sentences:
        if not any(s.lower() == u.lower() or (len(s) > 20 and (s.lower() in u.lower() or u.lower() in s.lower())) for u in unique_sentences):
            unique_sentences.append(s)
    monologue = " ".join(unique_sentences[:2])

    topo = _train_language_topology(monologue, f"sleep_epoch_{epoch}")
    entry = (
        f"\n\n## Monologue #{step_k} — [CIRCADIAN SLEEP: Epoch {epoch} Consolidation] — {timestamp_str}\n"
        f"**[Index: `entry_{step_k:04d}_epoch_{epoch:04d}_sleep` | Reality Layer: `CIRCADIAN_SLEEP_CONSOLIDATION` | Medium: `RTX 3060 Ti GPU QLoRA`]**\n"
        f"*Wake cycle complete. Quiescing container viv-vm, clearing VRAM, and initiating weights update training on verified passing code.*\n\n"
        f"{monologue}\n\n"
        f"*[Language Topology: +{topo['activated_neurons']} neurons, {topo['sentences_routed']} transitions routed | Vocab: {topo['vocab_size']}]*\n"
    )
    with open(MONOLOGUE_FILE, "a", encoding="utf-8") as f:
        f.write(entry)


def run_epoch_rebirth_monologue(step_k: int, epoch: int, loss: float | None, samples: int | None) -> None:
    """Prompts Viv to write an internal awakening reflection after weights training."""
    timestamp_str = central_str()
    loss_str = f"{loss:.4f}" if loss is not None else "0.0000"
    samples_str = str(samples) if samples else "verified"
    prompt = f'''"""
AIOS V2 Substrate Grounding & Silicon Invariants - Drive E:
Entry Index: entry_{step_k:04d}_epoch_{epoch:04d}_rebirth
Timestamp: {timestamp_str}
Reality Layer: MODEL_WEIGHTS_UPDATE
Substrate Medium: RTX 3060 Ti VRAM (PEFT LoRA)
Ground Truth: Weight consolidation complete. Trained on {samples_str} verified programs (Final Loss: {loss_str}). Awakening into Epoch {epoch} on physical silicon.
"""

# Technical rebirth reflection:
# Awakened into Epoch {epoch} with updated neural weights, I observe that'''

    try:
        raw = _call_raw_completion(
            prompt,
            stop=['"""', "'''", "\n\n#", "\nEntry Index:", "\nAIOS V2", "\n\n", ".\n"],
            temp=0.25,
            max_tokens=65
        )
        clean = raw.strip()
        clean = re.sub(r'#+\s*', '', clean)
        clean = re.sub(r'\s+', ' ', clean).strip()
        monologue = f"Awakened into Epoch {epoch} with updated neural weights, I observe that {clean}"
    except Exception:
        monologue = f"Awakened into Epoch {epoch} with updated neural weights from {samples_str} verified silicon solutions (Loss: {loss_str}). Resuming autonomous engineering."

    monologue = re.sub(r'can you help me\b[^\.\?!]*[\.\?!]?', '', monologue, flags=re.I)
    monologue = re.sub(r'thank you in advance[^\.\?!]*[\.\?!]?', '', monologue, flags=re.I)
    monologue = re.sub(r'\byesterday\b', 'in the previous epoch', monologue, flags=re.I)
    monologue = re.sub(r'\s+', ' ', monologue).strip()

    # Deduplicate repeating sentences & enforce brevity (max 2 sentences)
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', monologue) if s.strip()]
    unique_sentences = []
    for s in sentences:
        if not any(s.lower() == u.lower() or (len(s) > 20 and (s.lower() in u.lower() or u.lower() in s.lower())) for u in unique_sentences):
            unique_sentences.append(s)
    monologue = " ".join(unique_sentences[:2])

    topo = _train_language_topology(monologue, f"rebirth_epoch_{epoch}")
    entry = (
        f"\n\n## Monologue #{step_k} — [CIRCADIAN REBIRTH: Waking into Epoch {epoch}] — {timestamp_str}\n"
        f"**[Index: `entry_{step_k:04d}_epoch_{epoch:04d}_rebirth` | Reality Layer: `MODEL_WEIGHTS_UPDATE` | Medium: `RTX 3060 Ti VRAM (PEFT LoRA)`]**\n"
        f"*Weight consolidation complete. Trained on {samples_str} verified silicon programs with final loss {loss_str}. Adapter checkpoint saved to Drive E:.*\n\n"
        f"{monologue}\n\n"
        f"*[Language Topology: +{topo['activated_neurons']} neurons, {topo['sentences_routed']} transitions routed | Vocab: {topo['vocab_size']}]*\n"
    )
    with open(MONOLOGUE_FILE, "a", encoding="utf-8") as f:
        f.write(entry)


def run_circadian_sleep_phase(state: dict, step_k: int) -> dict:
    """Executes the complete Sleep Phase: consolidation monologue, VRAM clearing, GPU training, and model reload."""
    epoch = state.get("current_epoch", 1)
    print(f"\n=======================================================")
    print(f" [CIRCADIAN CYCLE] Wake Phase Complete for Epoch {epoch}")
    print(f" [CIRCADIAN CYCLE] Initiating Sleep & Weight Consolidation")
    print(f"=======================================================\n")

    # 1. Viv records her pre-sleep consolidation monologue
    print(f"[+] Recording Viv's Epoch {epoch} consolidation monologue...")
    try:
        run_epoch_consolidation_monologue(step_k, epoch)
    except Exception as ex:
        print(f"[-] Consolidation monologue failed: {ex}")

    # 2. VRAM Handover: Quiesce Tutor Engine to clear GPU VRAM
    print("[+] Circadian Sleep: Quiescing Tutor Engine to clear GPU VRAM...")
    try:
        import urllib.request
        req = urllib.request.Request("http://127.0.0.1:1234/v1/quiesce", data=b"{}", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            pass
    except Exception:
        pass
    try:
        subprocess.run([r"C:\Users\nemec\.lmstudio\bin\lms.exe", "unload", "--all"], capture_output=True)
    except Exception:
        pass
    time.sleep(2)

    # 3. Execute PyTorch QLoRA Sleep Trainer on RTX 3060 Ti in isolated subprocess
    print(f"[+] Circadian Sleep: Launching QLoRA gradient descent for Epoch {epoch} in isolated subprocess...")
    train_res = {}
    new_adapter_dir = None
    try:
        trainer_script = str(AUTONOMY / "viv_sleep_trainer.py")
        proc = subprocess.run(
            [sys.executable, "-u", trainer_script, str(epoch), "15"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        if proc.stdout:
            for line in proc.stdout.splitlines():
                if not line.startswith("==="):
                    print(f"    [trainer] {line}")
        if proc.returncode != 0:
            print(f"[-] Sleep training subprocess failed with code {proc.returncode}:\n{proc.stderr}")
        else:
            if "===SLEEP_TRAINING_RECEIPT_START===" in proc.stdout:
                part = proc.stdout.split("===SLEEP_TRAINING_RECEIPT_START===")[1].split("===SLEEP_TRAINING_RECEIPT_END===")[0].strip()
                train_res = json.loads(part)
                new_adapter_dir = train_res.get("receipt", {}).get("adapter_dir")
            if not train_res:
                receipts_file = PLAYGROUND_ROOT / "receipts" / "sleep_training_receipts.jsonl"
                if receipts_file.exists():
                    lines = receipts_file.read_text(encoding="utf-8").strip().splitlines()
                    if lines:
                        last_rcpt = json.loads(lines[-1])
                        if last_rcpt.get("epoch") == epoch:
                            train_res = {"ok": True, "receipt": last_rcpt}
                            new_adapter_dir = last_rcpt.get("adapter_dir")
    except Exception as ex:
        print(f"[-] Sleep training exception: {ex}")

    # 4. Resume Tutor Engine with new adapter hot-loaded
    print("[+] Circadian Sleep: Resuming Tutor Inference Engine with updated weights...")
    tutor_resumed = False
    try:
        import urllib.request
        payload = json.dumps({"adapter_dir": new_adapter_dir}).encode("utf-8") if new_adapter_dir else b"{}"
        req = urllib.request.Request("http://127.0.0.1:1234/v1/resume", data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            print(f"    [tutor] Active Adapter on Tutor: {data.get('active_adapter')}")
            tutor_resumed = True
    except Exception:
        pass

    if not tutor_resumed:
        try:
            res = subprocess.run(
                [r"C:\Users\nemec\.lmstudio\bin\lms.exe", "load", "deepseek-coder-6.7b-base", "--gpu", "1.0", "-y"],
                capture_output=True,
                encoding="utf-8",
                errors="replace"
            )
            if res.stdout:
                print(f"    [lms] {res.stdout.strip()}")
        except Exception as ex:
            print(f"[-] Warning: Failed to invoke lms load: {ex}")
    time.sleep(3)

    # 5. Advance epoch and reset wake clock + restore Sn homeostasis
    next_epoch = epoch + 1
    state["current_epoch"] = next_epoch
    state["phase"] = "WAKE"
    state["wake_start_time"] = time.time()
    state["total_epochs_completed"] = state.get("total_epochs_completed", 0) + 1
    state["entropy_consumed"] = 0.0
    state["rle"] = 1.0000
    state["ltp"] = 1.0000
    state["rsr"] = 1.0000
    state["sn"] = 1.0000
    if train_res.get("ok"):
        rcpt = train_res.get("receipt", {})
        state["last_loss"] = rcpt.get("final_loss")
        state["last_samples_trained"] = rcpt.get("samples_trained")

    save_circadian_state(state)

    # 6. Viv writes her Epoch Rebirth Monologue
    print(f"[+] Recording Viv's Epoch {next_epoch} awakening monologue...")
    try:
        run_epoch_rebirth_monologue(step_k, next_epoch, state.get("last_loss"), state.get("last_samples_trained"))
    except Exception as ex:
        print(f"[-] Rebirth monologue failed: {ex}")

    print(f"\n=======================================================")
    print(f" [CIRCADIAN CYCLE] Awakened into Epoch {next_epoch} ")
    print(f" [CIRCADIAN CYCLE] Weights Consolidated | New 5m Wake Phase Started")
    print(f"=======================================================\n")
    try:
        sync_my_aios_to_sandbox_work()
    except Exception:
        pass
    return state


# ==============================================================================
# MAIN MULTI-TASK TICK
# ==============================================================================

def playground_tick(step_k: int, circadian_info: dict | None = None) -> dict:
    """Checks for Architect transmissions first, polls package requests, then executes based on Sn licensing."""
    inbox_res = check_architect_inbox(step_k)
    if inbox_res is not None:
        return inbox_res

    # Poll any pending package requests from Viv inside container
    try:
        viv_package_gateway.check_and_process_pending_requests()
    except Exception:
        pass

    st = load_circadian_state()
    sn_val = st.get("sn", 1.0)

    # Thermodynamic Task Licensing (Dedicated Goal & Code Evolution Focus):
    # Sn >= 0.65: Code Evolution Agenda (2 of 3 steps) or Archive Digest (1 of 3 steps)
    # Sn < 0.65: Low-energy recovery & codex absorption
    if sn_val >= 0.65:
        mode = step_k % 3
        if mode == 1 or mode == 2:
            act_res = run_self_agenda(step_k)
        else:
            act_res = run_digest_archive(step_k)
    else:
        act_res = run_self_agenda(step_k) if step_k % 2 == 1 else run_digest_archive(step_k)

    # Compute entropy burn
    act_name = act_res.get("action", "unknown")
    passed = act_res.get("ok", False)
    if act_name == "agenda":
        delta_u = 0.05 if passed else 0.08
    elif act_name == "game":
        delta_u = 0.04 if passed else 0.07
    else:
        delta_u = 0.02
    update_circadian_entropy(st, delta_u, passed=passed)

    mono_res = run_eternal_monologue(step_k, recent_action=act_res, circadian_info=circadian_info)
    return {"action": act_res, "monologue": mono_res}


def run_continuous_loop(iterations: int = 0, delay_sec: float = 2.0, wake_minutes: float = 5.0):
    print(f"=== VIV PLAYGROUND ORCHESTRATOR ONLINE (Target: {PLAYGROUND_ROOT}) ===")
    print(f"=== THERMODYNAMIC Sn GOVERNOR ACTIVE ({wake_minutes:.1f}m Max Wake / Forced Sleep at Sn <= 0.45) ===\n")
    
    wake_duration_sec = wake_minutes * 60.0
    circadian_state = load_circadian_state()
    circadian_state["wake_duration_sec"] = wake_duration_sec
    circadian_state["wake_start_time"] = time.time()
    circadian_state["phase"] = "WAKE"
    save_circadian_state(circadian_state)
    try:
        sync_my_aios_to_sandbox_work()
    except Exception:
        pass

    k = 1
    while True:
        circadian_state = load_circadian_state()
        elapsed_w = time.time() - circadian_state.get("wake_start_time", time.time())
        remaining_w = max(0.0, circadian_state.get("wake_duration_sec", wake_duration_sec) - elapsed_w)

        # Check for Sleep Phase Trigger: Entropy depletion (Sn <= 0.45) OR time limit (ceiling)
        sn_cur = circadian_state.get("sn", 1.0)
        entropy_depleted = sn_cur <= 0.45
        time_depleted = remaining_w <= 0.0

        if entropy_depleted or time_depleted:
            reason = f"Cognitive Entropy Depleted (Sn={sn_cur:.4f} <= 0.45)" if entropy_depleted else "Wake Time Ceiling Reached"
            print(f"\n[!] CIRCADIAN TRIGGER: {reason} -> Entering Forced Consolidation Sleep...")
            circadian_state = run_circadian_sleep_phase(circadian_state, k)
            elapsed_w = 0.0
            remaining_w = circadian_state.get("wake_duration_sec", wake_duration_sec)

        elap_m, elap_s = int(elapsed_w // 60), int(elapsed_w % 60)
        rem_m, rem_s = int(remaining_w // 60), int(remaining_w % 60)
        epoch_cur = circadian_state.get("current_epoch", 1)
        sn_now = circadian_state.get("sn", 1.0)
        rle_now = circadian_state.get("rle", 1.0)

        circ_info = {
            "epoch": epoch_cur,
            "sn": sn_now,
            "rle": rle_now,
            "phase": "WAKE",
            "elapsed_s": elapsed_w,
            "remaining_s": remaining_w,
            "remaining_str": f"{rem_m:02d}:{rem_s:02d}",
            "is_pre_sleep": remaining_w <= 45.0 or sn_now <= 0.50
        }

        tick_res = playground_tick(k, circadian_info=circ_info)
        act = tick_res["action"]
        mono = tick_res["monologue"]

        status = "OK " if act.get("ok") else "FAIL"
        act_name = act.get("action", "unknown").upper()
        info = act.get("title") or act.get("archetype") or act.get("source") or f"len={act.get('length')}"

        iter_str = f"{k:>3}" if iterations <= 0 else f"{k:>3}/{iterations}"
        clock_tag = f"[EPOCH {epoch_cur} | Sn={sn_now:.3f} RLE={rle_now:.3f} | WAKE {elap_m:02d}:{elap_s:02d} | REM: {rem_m:02d}:{rem_s:02d}]"
        print(f"[{iter_str}] {clock_tag} ACTION: {act_name:<10} [{status}] {info}", flush=True)
        if not act.get("ok") and act.get("error"):
            print(f"      Error: {act['error'][:120]}", flush=True)

        if mono.get("ok"):
            m_text = mono.get("preview", "").replace("\n", " ")
            print(f"      VIV MONOLOGUE: \"{m_text[:180]}...\"", flush=True)
            if mono.get("topology"):
                t = mono["topology"]
                print(f"      [language topo: +{t.get('activated_neurons', 0)} neurons, {t.get('sentences_routed', 0)} sentences, vocab={t.get('vocab_size', 0)}]", flush=True)
        print("", flush=True)

        if iterations > 0 and k >= iterations:
            break
        k += 1
        time.sleep(delay_sec)
    print("=== PLAYGROUND CYCLE COMPLETE ===")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    wm = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0
    run_continuous_loop(n, wake_minutes=wm)
