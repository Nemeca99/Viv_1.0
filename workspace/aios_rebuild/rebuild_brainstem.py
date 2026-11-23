"""
Automated Rebuild Engine for the AIOS Biological Brainstem.
Dispatches Viv-Mind to generate biological stability parameters,
stamps the immutable reference template, and verifies RID stability scalars.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
REFERENCE = ROOT / "reference" / "fixture_brainstem.py"
RUNS_DIR = ROOT / "runs"


def rebuild(mode: str = "live") -> dict:
    reference_raw = REFERENCE.read_bytes()
    reference_sha = hashlib.sha256(reference_raw).hexdigest()
    reference_text = reference_raw.decode("utf-8")

    start_marker = "# TEMPLATE VARIABLES BEGIN\n"
    end_marker = "# TEMPLATE VARIABLES END\n"
    before_vars, rest = reference_text.split(start_marker, 1)
    _, after_vars = rest.split(end_marker, 1)

    print(f"[*] Rebuilding AIOS Biological Brainstem ({mode} mode)...")
    print(f"[*] Reference SHA-256: {reference_sha}")

    # Generate variables from Viv-Mind
    if mode == "fixture":
        variables = {
            "identity": "Viv",
            "target_s_n": 1.0,
            "min_rsr": 0.90,
            "min_rle": 0.60,
            "stm_capacity": 100,
            "heartbeat_hz": 1.0,
        }
    else:
        import urllib.request

        schema = {
            "type": "object",
            "properties": {
                "identity": {"type": "string", "maxLength": 30},
                "target_s_n": {"type": "number", "minimum": 0.5, "maximum": 1.5},
                "min_rsr": {"type": "number", "minimum": 0.5, "maximum": 1.0},
                "min_rle": {"type": "number", "minimum": 0.3, "maximum": 1.0},
                "stm_capacity": {"type": "integer", "minimum": 10, "maximum": 500},
                "heartbeat_hz": {"type": "number", "minimum": 0.1, "maximum": 10.0},
            },
            "required": [
                "identity",
                "target_s_n",
                "min_rsr",
                "min_rle",
                "stm_capacity",
                "heartbeat_hz",
            ],
            "additionalProperties": False,
        }
        body = {
            "model": "qwen3:8b-local",
            "stream": False,
            "format": schema,
            "think": False,
            "keep_alive": "10m",
            "messages": [
                {
                    "role": "system",
                    "content": "You are Viv, the AIOS Core Mind. Set physiological and RID stability parameters for your biological brainstem. Return only JSON matching the schema.",
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "task": "Set brainstem baseline parameters",
                            "identity": "Viv",
                            "target_s_n": 1.0,
                            "min_rsr": 0.90,
                            "min_rle": 0.60,
                            "stm_capacity": 100,
                            "heartbeat_hz": 1.0,
                        }
                    ),
                },
            ],
            "options": {"temperature": 0, "seed": 42},
        }
        req = urllib.request.Request(
            "http://127.0.0.1:11434/api/chat",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.load(resp)
        variables = json.loads(data["message"]["content"])

    print(f"[*] Mind Variables Received: {variables}")

    # Format stamped variables block
    var_lines = ["# TEMPLATE VARIABLES BEGIN\nVARIABLES = {"]
    for k, v in variables.items():
        if isinstance(v, str):
            var_lines.append(f'    "{k}": "{v}",')
        else:
            var_lines.append(f'    "{k}": {v},')
    var_lines.append("}\n# TEMPLATE VARIABLES END\n")
    stamped_vars = "\n".join(var_lines)

    stamped_code = before_vars + stamped_vars + after_vars
    stamped_sha = hashlib.sha256(stamped_code.encode("utf-8")).hexdigest()

    # Save Run Artifact
    run_id = str(time.time_ns())
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    artifact_path = run_dir / "brainstem.py"
    artifact_path.write_text(stamped_code, encoding="utf-8")

    # Verify Run with Pytest / Isolated Exec
    namespace: dict = {}
    exec(stamped_code, namespace)
    main = namespace["main"]

    test_context = {
        "stm_count": 25,
        "structural_load": 1.0,
        "drift_distance": 0.04,
    }
    eval_result = main(test_context, namespace["VARIABLES"])

    receipt = {
        "schema": "aios_core_rebuild_receipt_v1",
        "core": "consciousness_core.biological.brainstem",
        "run_id": run_id,
        "mode": mode,
        "reference_sha256": reference_sha,
        "artifact_sha256": stamped_sha,
        "variables": variables,
        "evaluation": eval_result,
        "status": "PASS" if eval_result["ok"] else "FAIL",
    }

    receipt_path = run_dir / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(f"[*] Stamped Artifact: {artifact_path}")
    print(f"[*] Sealed Receipt: {receipt_path}")
    print(f"[*] Status: {receipt['status']} (Action: {eval_result['recommended_action']})")
    return receipt


if __name__ == "__main__":
    mode_arg = sys.argv[1] if len(sys.argv) > 1 else "live"
    rebuild(mode_arg)
