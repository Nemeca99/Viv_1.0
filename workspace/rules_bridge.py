"""
Rules Transformer Tool Bridge
Exposes Python JSON Schemas and RPC bridge to the Rust Symbolic Core Engine (L:\Rules\target\release\rules_core.exe).
"""

import json
import os
import subprocess
from typing import Any, Dict, Optional

RUST_ENGINE = r"L:\Rules\target\release\rules_core.exe"

# 1. JSON Schemas for Transformer Function Calling
TOOLS_SCHEMA = [
    {
        "name": "verify_rules_engine",
        "description": "Checks operational status of the Rust Rules Core engine.",
        "parameters": {
            "type": "object",
            "properties": {
                "drive": {"type": "string", "description": "Target drive letter, e.g., 'L'"}
            },
            "required": ["drive"],
        },
    },
    {
        "name": "quarantine_path",
        "description": "Safely moves a target file or folder into <drive>:\\_sweep_quarantine\\ with full manifest logging. Requires explicit user approval.",
        "parameters": {
            "type": "object",
            "properties": {
                "drive": {"type": "string", "description": "Target drive letter, e.g. 'C', 'L'"},
                "target_path": {"type": "string", "description": "Absolute file or folder path to quarantine"},
                "reason": {"type": "string", "description": "Explanation of why this item is being quarantined"},
                "user_approved": {"type": "boolean", "description": "Must be True if user explicitly granted consent"},
            },
            "required": ["drive", "target_path", "reason", "user_approved"],
        },
    },
    {
        "name": "explain_quarantine_memory",
        "description": "Reads quarantine manifests and returns human-readable refresher explanation of why items were saved/quarantined.",
        "parameters": {
            "type": "object",
            "properties": {
                "drive": {"type": "string", "description": "Target drive letter, e.g. 'L'"}
            },
            "required": ["drive"],
        },
    },
]


def call_rust_core(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Invokes compiled Rust symbolic core engine deterministically."""
    if not os.path.exists(RUST_ENGINE):
        return {
            "status": "DENIED",
            "message": f"Rust core binary missing at {RUST_ENGINE}. Please recompile.",
        }

    raw_input = json.dumps(payload)
    try:
        output = subprocess.check_output([RUST_ENGINE, raw_input], stderr=subprocess.STDOUT)
        return json.loads(output.decode("utf-8"))
    except subprocess.CalledProcessError as e:
        try:
            return json.loads(e.output.decode("utf-8"))
        except Exception:
            return {"status": "DENIED", "message": f"Execution error: {e}"}


def explain_quarantine_memory(drive: str) -> str:
    """Refresher Memory tool reading quarantine manifest."""
    manifest_path = os.path.join(f"{drive.upper()}:\\", "_sweep_quarantine", "quarantine_manifest.jsonl")
    if not os.path.exists(manifest_path):
        return f"No quarantine records found on Drive {drive.upper()}:."

    records = []
    with open(manifest_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))

    if not records:
        return f"Quarantine log on Drive {drive.upper()}: is empty."

    summary = [f"### Quarantine Refresher Log for Drive {drive.upper()}:"]
    total_bytes = 0
    for r in records:
        gb = r.get("bytes", 0) / 1e9
        total_bytes += r.get("bytes", 0)
        summary.append(
            f"- **Item:** `{r.get('original_path')}`\n"
            f"  - **Saved On:** {r.get('timestamp')}\n"
            f"  - **Size:** {gb:.2f} GB\n"
            f"  - **Refresher Context:** {r.get('reason')}\n"
        )
    summary.append(f"**Total Quarantined Volume:** {total_bytes / 1e9:.2f} GB")
    return "\n".join(summary)


if __name__ == "__main__":
    print("Rules Bridge Operational. Exposed Schemas:")
    print(json.dumps(TOOLS_SCHEMA, indent=2))
