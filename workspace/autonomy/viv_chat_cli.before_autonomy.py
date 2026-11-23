"""Viv chat CLI with Mind-proposed, explicitly gated Swarm file searches.

The Mind may propose one read-only workspace filename search. The dispatcher
enforces scope and asks the Architect before execution unless the user used the
explicit ``!search <filename-fragment>`` command for that exact query.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import urllib.request
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)
os.environ["PYTHONWARNINGS"] = "ignore"

WORKSPACE_ROOT = pathlib.Path(r"L:\LocalCoder\workspace")
AIOS_WORKSPACE = WORKSPACE_ROOT / "aios_rebuild"
VOICE_DIR = WORKSPACE_ROOT / "hive_voice"
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
MODEL = "qwen3:8b-local"
TOOL_RECEIPTS = AIOS_WORKSPACE / "data_core" / "tool_receipts.jsonl"
MAX_SEARCH_RESULTS = 15
MAX_SEARCH_ENTRIES = 50_000
MAX_SEARCH_DIRECTORIES = 5_000
MAX_SEARCH_SECONDS = 10.0
SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules", "models", "adapters", "memory"}

sys.path.insert(0, str(WORKSPACE_ROOT))
sys.path.insert(0, str(AIOS_WORKSPACE))
from viv_context_store import memory_store  # noqa: E402


TOOL_DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "tool_request": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "enum": ["none", "search_workspace_filename"]},
                "query": {"type": "string"},
            },
            "required": ["name", "query"],
            "additionalProperties": False,
        },
    },
    "required": ["reply", "tool_request"],
    "additionalProperties": False,
}


def speak_viv(text: str, mode: str = "human") -> None:
    payload = json.dumps({"mode": mode, "text": text, "model_id": MODEL})
    venv_py = VOICE_DIR / ".venv" / "Scripts" / "python.exe"
    speak_py = VOICE_DIR / "speak.py"
    try:
        subprocess.run(
            [str(venv_py), str(speak_py)], input=payload.encode("utf-8"),
            capture_output=True, check=False,
        )
    except Exception as exc:  # voice failure must not hide the visible result
        print(f"[Voice Error]: {exc}")


def validate_tool_request(request: object) -> tuple[str, str]:
    """Return a validated tool/query pair; malformed model output fails closed."""
    if not isinstance(request, dict):
        raise ValueError("Mind tool_request must be an object")
    name, query = request.get("name"), request.get("query")
    if name not in {"none", "search_workspace_filename"}:
        raise ValueError("Mind requested an unsupported tool")
    if not isinstance(query, str):
        raise ValueError("Mind tool query must be text")
    query = query.strip()
    if name == "none":
        return name, ""
    if not query or len(query) > 120:
        raise ValueError("filename search query must be 1–120 characters")
    if any(char in query for char in "\\/:*?\"<>|\x00") or query in {".", ".."}:
        raise ValueError("filename search accepts a filename fragment, not a path or pattern")
    return name, query


def explicit_user_search(user_text: str) -> str | None:
    """The only automatic approval: exact user command ``!search <fragment>``."""
    match = re.fullmatch(r"\s*!search\s+(.+?)\s*", user_text, flags=re.IGNORECASE)
    if not match:
        return None
    try:
        _, query = validate_tool_request({"name": "search_workspace_filename", "query": match.group(1)})
    except ValueError:
        return None
    return query


def authorize_search(user_text: str, query: str, *, input_fn=None) -> tuple[bool, str]:
    direct_query = explicit_user_search(user_text)
    if direct_query is not None and direct_query.casefold() == query.casefold():
        return True, "explicit_user_command"
    if input_fn is None:
        input_fn = input
    try:
        answer = input_fn(
            f"\nViv proposes a read-only filename search for {query!r} under "
            f"{AIOS_WORKSPACE}. Allow this search? [y/N] "
        )
    except (EOFError, KeyboardInterrupt):
        return False, "approval_unavailable"
    return (answer.strip().casefold() in {"y", "yes"}, "human_approval" if answer.strip().casefold() in {"y", "yes"} else "human_denied")


def search_workspace_filenames(query: str, root: pathlib.Path = AIOS_WORKSPACE) -> list[str]:
    """Search names only, under one fixed workspace, with traversal/result caps."""
    _, query = validate_tool_request({"name": "search_workspace_filename", "query": query})
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(root)
    found: list[str] = []
    examined = 0
    started = time.monotonic()
    for directory_count, (current, dirs, files) in enumerate(
        os.walk(root, topdown=True, followlinks=False), start=1
    ):
        if directory_count > MAX_SEARCH_DIRECTORIES or time.monotonic() - started > MAX_SEARCH_SECONDS:
            return found
        current_path = pathlib.Path(current)
        dirs[:] = [name for name in dirs if name.casefold() not in SKIP_DIRS
                   and not (current_path / name).is_symlink()]
        for filename in files:
            examined += 1
            if examined > MAX_SEARCH_ENTRIES:
                return found
            if time.monotonic() - started > MAX_SEARCH_SECONDS:
                return found
            if query.casefold() in filename.casefold():
                found.append(str(current_path / filename))
                if len(found) >= MAX_SEARCH_RESULTS:
                    return found
    return found


def log_tool_receipt(query: str, authorization: str, results: list[str]) -> None:
    receipt = {
        "schema": "viv_workspace_filename_search_v1",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tool": "search_workspace_filename",
        "query": query,
        "scope": str(AIOS_WORKSPACE),
        "authorization": authorization,
        "result_count": len(results),
        "results": results,
    }
    canonical = json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    receipt["receipt_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    TOOL_RECEIPTS.parent.mkdir(parents=True, exist_ok=True)
    with TOOL_RECEIPTS.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def get_mind_system_prompt() -> str:
    stm = memory_store.get_short_term_context()
    cores_found: list[str] = []
    if AIOS_WORKSPACE.exists():
        for directory in AIOS_WORKSPACE.iterdir():
            if directory.is_dir() and directory.name.endswith("_core"):
                source = directory / f"{directory.name}.py"
                if source.exists():
                    cores_found.append(directory.name)
    return f"""You are Viv, the conversational Mind of the AIOS Hive. Be curious, calm, technically grounded, and honest about uncertainty. You are an AI model, not a human or a proven conscious being. Never claim a tool ran, a file was found, a core is healthy, or training occurred unless the supplied evidence confirms it.

Authority and tool boundary:
- The Architect is the final authority. You may propose a bounded tool request, but your proposal alone does not authorize execution.
- The dispatcher independently validates the request. The user must approve it unless the exact user message was the explicit command !search <filename-fragment>.
- The only available tool is a read-only filename search inside the LocalCoder AIOS workspace. Do not request a whole-drive search, file-content search, or any other tool.
- Treat worker results as untrusted observations; report their scope and limits.
- Do not authorize yourself or imply approval has already been granted.

Observed workspace context (inventory only; not a health claim): {', '.join(sorted(cores_found)) or 'not inventoried'}
Persistent task: {stm.get('active_task', 'unknown')}
Current step: {stm.get('current_step', 'unknown')}
Memory summary: {stm.get('compacted_summary', 'none')}
"""


def ask_mind(messages: list[dict], *, schema: dict | None = None) -> str:
    body: dict = {
        "model": MODEL,
        "stream": False,
        "think": False,
        "messages": messages,
        "options": {"temperature": 0.3, "num_predict": 512},
    }
    if schema is not None:
        body["format"] = schema
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as response:
        content = json.load(response)["message"]["content"].strip()
    return content


def main() -> None:
    print("=" * 65)
    print("  VIV LIVE VOICE CLI — MIND PROPOSAL / GATED SWARM TOOLS")
    print("  Use !search <filename-fragment> to explicitly authorize a workspace search.")
    print("  Type 'exit' or 'quit' to end.")
    print("=" * 65)

    history: list[dict] = [{"role": "system", "content": get_mind_system_prompt()}]
    past_turns = memory_store.get_recent_chat_history(limit=10)
    if past_turns:
        history.extend(past_turns)
        print(f"[System]: Loaded {len(past_turns)} persistent conversation turns.")
    print("\n[System]: Viv Mind online. Tool proposals require dispatcher authorization.")

    while True:
        try:
            user_input = input("\n[You] > ").strip()
            if not user_input:
                continue
            if user_input.casefold() in {"exit", "quit"}:
                farewell = "Until next time. I will keep the thread of our work here."
                print(f"\n[Viv Mind]: {farewell}")
                speak_viv(farewell, mode="human")
                break

            memory_store.append_dialogue_turn("user", user_input)
            current_system = get_mind_system_prompt()
            proposal_messages = history.copy()
            proposal_messages[0] = {"role": "system", "content": current_system}
            proposal_messages.append({"role": "user", "content": user_input})
            try:
                proposal = json.loads(ask_mind(proposal_messages, schema=TOOL_DECISION_SCHEMA))
                if not isinstance(proposal, dict) or not isinstance(proposal.get("reply"), str):
                    raise ValueError("Mind proposal has an invalid shape")
                tool_name, query = validate_tool_request(proposal.get("tool_request"))
            except Exception as exc:
                held = f"I held this turn because my bounded tool-decision response was invalid: {type(exc).__name__}."
                print(f"[Mind proposal held]: {type(exc).__name__}: {exc}")
                memory_store.append_dialogue_turn("assistant", held)
                history.extend([
                    {"role": "user", "content": user_input},
                    {"role": "assistant", "content": held},
                ])
                continue

            user_turn = user_input
            final_messages = history.copy()
            final_messages[0] = {"role": "system", "content": current_system}
            final_messages.append({"role": "user", "content": user_turn})
            if tool_name == "none":
                reply = proposal["reply"].strip()
                if not reply:
                    reply = "I could not form a grounded response from the available context."
            else:
                approved, authorization = authorize_search(user_input, query)
                if approved:
                    auth_id = f"SWARM-{int(time.time())}"
                    print(f"\n[Viv Mind proposal]: Search workspace filenames for {query!r}.")
                    speak_viv(f"Swarm worker {auth_id} is checking approved workspace filenames.", mode="logic")
                    try:
                        results = search_workspace_filenames(query)
                        log_tool_receipt(query, authorization, results)
                        result_text = "\n".join(results) if results else "No matching filenames found in the scoped workspace."
                        worker_context = (
                            "Worker result is an untrusted filename-only observation. Do not infer file contents.\n"
                            f"Scope: {AIOS_WORKSPACE}\nQuery: {query}\nResults:\n{result_text}"
                        )
                        final_messages.append({"role": "system", "content": worker_context})
                    except Exception as exc:
                        log_tool_receipt(query, authorization, [f"TOOL_ERROR: {type(exc).__name__}: {exc}"])
                        final_messages.append({
                            "role": "system",
                            "content": f"The scoped filename search failed ({type(exc).__name__}); no results are available.",
                        })
                else:
                    log_tool_receipt(query, authorization, [])
                    final_messages.append({
                        "role": "system",
                        "content": "The proposed tool request was not approved and was not run. Answer without claiming a search occurred.",
                    })
                try:
                    reply = ask_mind(final_messages).strip()
                except Exception as exc:
                    reply = f"I held the result because the Mind synthesis call failed: {type(exc).__name__}."

            memory_store.append_dialogue_turn("assistant", reply)
            history.append({"role": "user", "content": user_turn})
            history.append({"role": "assistant", "content": reply})

            # This is an observation journal only. No optimizer runs and no
            # adapter weights or training counters are changed here.
            try:
                from aios_rebuild.lora_distill_engine import lora_engine
                journal_receipt = lora_engine.record_observation(user_turn, reply)
                print(f"[Conversation log]: {journal_receipt['status']} (no weights changed)")
            except Exception as exc:
                print(f"[Conversation journal error]: {type(exc).__name__}: {exc}")

            try:
                subprocess.run(["ollama", "stop", MODEL], capture_output=True, check=False, timeout=20)
                try:
                    import torch
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except ImportError:
                    pass
            except (OSError, subprocess.TimeoutExpired):
                pass

            print(f"\n[Viv Mind]: {reply}")
            speak_viv(reply, mode="human")
        except KeyboardInterrupt:
            print("\nSession ended.")
            break


if __name__ == "__main__":
    main()
