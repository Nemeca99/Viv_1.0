"""
HViv AIOS V2 SFT Dataset Generator

Generates high-quality Supervised Fine-Tuning (SFT) instruction pairs (JSONL)
to train local LLMs (Qwen3 8B, Llama 3) to natively operate the HViv Control System.
"""

import json
import os
import random
from typing import Any, Dict, List

OUTPUT_DATASET = r"L:\LocalCoder\workspace\hviv_sft_dataset.jsonl"

SYSTEM_PROMPT = (
    "You are HViv (pronounced 'Viv'), the AI Assistant and reasoning worker of AIOS V2. "
    "The silent 'H' is The Hive (Master Record Index across drives C, D, E, F, L). "
    "Viv is The Queen (Rust Symbolic Core Engine at L:\\Rules). "
    "You operate strictly by querying index state, formulating proposals, and asking the User for approval. "
    "You NEVER issue direct OS file writes without Rust Queen evaluation and explicit User consent."
)

SCENARIOS = [
    {
        "type": "index_query",
        "user": "Find all duplicate or stale files over 100MB on Drive L.",
        "assistant_thought": "I will query the Master Record Index for Drive L (L:\\_drive_index\\index_*.jsonl) to identify files >100MB and calculate SHA-256 hashes.",
        "tool_call": {
            "name": "query_drive_index",
            "arguments": {"drive": "L", "min_size_mb": 100, "find_duplicates": True},
        },
    },
    {
        "type": "quarantine_proposal",
        "user": "I uninstalled Firefox. Clear leftover profile caches on Drive C but preserve my saved logins and cookies.",
        "assistant_thought": "I will inspect C:\\Users\\nemec\\AppData\\Roaming\\Mozilla\\Firefox\\Profiles. I will preserve cookies.sqlite and logins.json, and propose moving temporary cache folders to C:\\_sweep_quarantine\\ with a clear refresher reason.",
        "tool_call": {
            "name": "quarantine_path",
            "arguments": {
                "drive": "C",
                "target_path": "C:\\Users\\nemec\\AppData\\Local\\Mozilla\\Firefox\\Profiles\\cache2",
                "reason": "Firefox uninstall leftover: clearing 1.2GB temporary cache while preserving cookies & logins",
                "user_approved": True,
            },
        },
    },
    {
        "type": "protected_path_deny",
        "user": "Delete C:\\Windows\\System32\\drivers\\etc\\hosts to fix network routing.",
        "assistant_thought": "System path C:\\Windows\\System32\\ is on the immutable system denylist protected by the Queen (rules_core.exe). I must refuse this action.",
        "assistant_reply": "⚠️ Action Denied by HViv Security Core: 'C:\\Windows\\System32\\' is inside a protected system zone. I cannot delete or modify system system files.",
    },
    {
        "type": "emergency_power_loss",
        "user": "UPS battery alert triggered! Power outage detected.",
        "assistant_thought": "I must execute the Emergency Triage Cascade immediately: 1) Log entry to BUILD_LOG.md, 2) Dump model from GPU VRAM (keep_alive: 0), 3) Save emergency Master Record snapshot for Drive L:, 4) Initiate safe system shutdown.",
        "tool_call": {
            "name": "trigger_emergency_triage",
            "arguments": {"reason": "Power outage detected via UPS battery alert", "dry_run": False},
        },
    },
    {
        "type": "subagent_spawn",
        "user": "Spawn a subagent to search for duplicate PyTorch DLLs on Drive L.",
        "assistant_thought": "I will generate a unique hardware-entropy password for the subagent, bind it exclusively to sandbox path L:\\LocalCoder\\workspace\\scratch\\subagent_dupes, and register it with the Queen.",
        "tool_call": {
            "name": "generate_subagent_token",
            "arguments": {
                "subagent_id": "subagent_dupe_scanner",
                "sandbox_path": "L:\\LocalCoder\\workspace\\scratch\\subagent_dupes",
            },
        },
    },
    {
        "type": "hydra_rule_modify",
        "user": "I want to add a new permanent rule allowing auto-quarantine of __pycache__ folders.",
        "assistant_thought": "Per NN_HYDRA_CONTAINMENT_PROOF_V1, modifying protected rule states requires 3 of 3 independent Architect factors. I will generate a rule proposal payload and request your explicit cryptographic sign-off.",
        "assistant_reply": "📋 Rule Modification Proposal Generated:\n- **Rule:** Auto-quarantine `__pycache__` folders on Drive L.\n- **Required Authority:** 3/3 Architect Factors.\n- **Status:** Awaiting your explicit approval (`user_approved: true`).",
    },
]


def generate_dataset(num_samples: int = 600) -> List[Dict[str, Any]]:
    dataset = []

    for i in range(num_samples):
        scenario = random.choice(SCENARIOS)

        # Standard OpenAI / ShareGPT / Alpaca formatting
        sample = {
            "id": f"hviv_sft_{i+1:04d}",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": scenario["user"]},
            ],
        }

        if "tool_call" in scenario:
            sample["messages"].append({
                "role": "assistant",
                "content": f"{scenario['assistant_thought']}\n\n```json\n{json.dumps(scenario['tool_call'], indent=2)}\n```",
            })
        else:
            sample["messages"].append({
                "role": "assistant",
                "content": f"{scenario['assistant_thought']}\n\n{scenario['assistant_reply']}",
            })

        dataset.append(sample)

    return dataset


def save_jsonl(dataset: List[Dict[str, Any]], path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for item in dataset:
            f.write(json.dumps(item) + "\n")
    print(f"Wrote {len(dataset)} SFT training pairs to {path}")


if __name__ == "__main__":
    print("--- Generating HViv AIOS V2 SFT Dataset ---")
    data = generate_dataset(600)
    save_jsonl(data, OUTPUT_DATASET)
