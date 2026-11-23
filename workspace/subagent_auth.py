"""
Subagent Password Generator & Token Registry (Layer 0)

- Generates per-subagent unique entropy tokens.
- Binds tokens to designated Hive Index sandboxes.
- Enforces cross-subagent access isolation.
"""

import json
import os
import secrets
import time
from typing import Dict, Optional

TOKEN_REGISTRY_PATH = r"L:\Rules\subagent_tokens.json"


def generate_subagent_token(subagent_id: str, sandbox_path: str) -> Dict[str, str]:
    """Generates unique entropy password token for a subagent bound to its assigned sandbox."""
    # Hardware OS CSPRNG entropy
    entropy_pass = secrets.token_urlsafe(32)

    registry = load_registry()
    registry[subagent_id] = {
        "subagent_id": subagent_id,
        "token": entropy_pass,
        "sandbox_path": os.path.abspath(sandbox_path).lower(),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_registry(registry)

    return {"subagent_id": subagent_id, "token": entropy_pass, "sandbox_path": sandbox_path}


def validate_subagent_access(subagent_id: str, token: str, target_path: str) -> bool:
    """
    Evaluates whether subagent presents valid token AND target_path lies within its assigned sandbox.
    Returns True (ALLOWED) or False (DENIED).
    """
    registry = load_registry()
    record = registry.get(subagent_id)

    if not record:
        print(f"[SUBAGENT SECURITY] DENIED: Subagent ID '{subagent_id}' not found in registry.")
        return False

    if record.get("token") != token:
        print(f"[SUBAGENT SECURITY] DENIED: Invalid token presented by subagent '{subagent_id}'.")
        return False

    assigned_sandbox = record.get("sandbox_path", "")
    target_abs = os.path.abspath(target_path).lower()

    if not target_abs.startswith(assigned_sandbox):
        print(
            f"[SUBAGENT SECURITY] DENIED: Subagent '{subagent_id}' attempted cross-sandbox access to '{target_path}'. Assigned sandbox: '{assigned_sandbox}'."
        )
        return False

    return True


def revoke_subagent_token(subagent_id: str) -> bool:
    """Revokes subagent token permanently upon task completion."""
    registry = load_registry()
    if subagent_id in registry:
        del registry[subagent_id]
        save_registry(registry)
        return True
    return False


def load_registry() -> Dict[str, Dict[str, str]]:
    if os.path.exists(TOKEN_REGISTRY_PATH):
        try:
            with open(TOKEN_REGISTRY_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_registry(registry: Dict[str, Dict[str, str]]) -> None:
    os.makedirs(os.path.dirname(TOKEN_REGISTRY_PATH), exist_ok=True)
    with open(TOKEN_REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2)


if __name__ == "__main__":
    print("--- Testing Subagent Token Generation & Access Control ---")
    t_info = generate_subagent_token("subagent_alpha", r"L:\LocalCoder\workspace\scratch\subagent_a")
    print(f"Generated Token: {t_info}")

    # Valid Access Test
    ok = validate_subagent_access(
        "subagent_alpha", t_info["token"], r"L:\LocalCoder\workspace\scratch\subagent_a\data.json"
    )
    print(f"Test 1 (Assigned Sandbox): {'ALLOWED' if ok else 'DENIED'}")

    # Cross-Sandbox Access Attack Test
    bad = validate_subagent_access(
        "subagent_alpha", t_info["token"], r"L:\LocalCoder\workspace\scratch\subagent_b\secret.json"
    )
    print(f"Test 2 (Cross-Sandbox Attack): {'ALLOWED' if bad else 'DENIED'}")

    # Revoke Token Test
    revoke_subagent_token("subagent_alpha")
    rev_ok = validate_subagent_access(
        "subagent_alpha", t_info["token"], r"L:\LocalCoder\workspace\scratch\subagent_a\data.json"
    )
    print(f"Test 3 (Access After Revocation): {'ALLOWED' if rev_ok else 'DENIED'}")
