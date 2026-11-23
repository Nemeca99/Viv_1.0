"""PrivacyCore preflight for the Rust-gated OpenCode memory append tool."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path("L:/LocalCoder")
STATE = ROOT / "workspace/aios_rebuild/memory/hermes_agent"
MEMORY = STATE / "memories"
RUST_GATE = ROOT / "workspace/hive_control/target/release/localcoder_memory_gate.exe"


def direct_memory_intent(text):
    lower = text.casefold()
    intent = any(word in lower for word in ("remember", "save", "store", "add", "write", "update", "make sure"))
    target = any(word in lower for word in ("memory", "user.md", "user profile", "this model knows"))
    negated = any(phrase in lower for phrase in (
        "don't remember", "do not remember", "don't save", "do not save", "never store", "don't store", "do not store"
    ))
    return intent and target and not negated


def main():
    raw = sys.stdin.read(16385)
    if len(raw) > 16384:
        raise ValueError("request exceeds 16 KiB")
    request = json.loads(raw)
    target_name = request.get("target", "USER.md")
    if target_name not in ("USER.md", "MEMORY.md"):
        raise ValueError("target must be USER.md or MEMORY.md")
    quote = request.get("quote")
    messages = request.get("user_messages")
    session_id = request.get("session_id")
    if not isinstance(quote, str) or not quote.strip() or len(quote.encode("utf-8")) > 2000:
        raise ValueError("quote must be nonempty and at most 2000 UTF-8 bytes")
    if not isinstance(messages, list) or not all(isinstance(m, str) for m in messages):
        raise ValueError("user_messages must be text from the active OpenCode session")
    source = next((m for m in reversed(messages) if quote in m and direct_memory_intent(m)), None)
    if source is None:
        raise PermissionError("no exact Architect quote with direct memory intent in this session")
    if not isinstance(session_id, str) or not session_id or len(session_id) > 160:
        raise ValueError("invalid OpenCode session identity")

    target = MEMORY / target_name
    receipt_id = uuid.uuid4().hex
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    snapshot = STATE / "snapshots" / f"{digest}.snapshot"
    receipt = STATE / "receipts" / f"memory-{receipt_id}.jsonl"
    lock = target.with_name(f"{target_name}.lock")
    source_file = ROOT / "workspace/aios_rebuild/privacy_core/privacy_core.py"
    spec = importlib.util.spec_from_file_location("localcoder_memory_privacy", source_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    core = module.PrivacyCore()
    for path in (target, snapshot, receipt, lock):
        decision = core.authorize_file_write(str(path))
        if decision.get("allowed") is not True:
            raise PermissionError(f"PrivacyCore denied {path}: {decision}")

    payload = {
        "architect_approved": True,
        "privacy_authorized": True,
        "target": target_name,
        "quote": quote,
        "source_user_text": source,
        "session_id": session_id,
        "receipt_id": receipt_id,
    }
    completed = subprocess.run([str(RUST_GATE)], input=json.dumps(payload), text=True,
        capture_output=True, timeout=20, check=False)
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or "Rust memory gate denied the append")
    print(completed.stdout.strip())


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"ok": False, "error": str(error)}), file=sys.stderr)
        raise SystemExit(1)

