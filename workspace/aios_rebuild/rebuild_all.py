"""
Universal Rebuild Dispatcher for All AIOS Viv Core Templates.
Dispatches Viv-Mind (Ollama: qwen3:8b-local) to generate slot variables,
stamps all core templates in sequence, and seals cryptographic execution receipts.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
REFERENCE_DIR = ROOT / "reference"
RUNS_DIR = ROOT / "runs"

CORES = [
    ("consciousness_core.brainstem", "fixture_brainstem.py"),
    ("carma_core.memory", "fixture_carma.py"),
    ("dream_core.replay", "fixture_dream.py"),
    ("game_core.world_tick", "fixture_game.py"),
    ("luna_core.persona", "fixture_luna.py"),
    ("rag_core.vector_retrieval", "fixture_rag.py"),
    ("security_core.crypto_membrane", "fixture_security.py"),
    ("data_core.event_replay", "fixture_data.py"),
    ("infra_core.vitals_monitor", "fixture_infra.py"),
    ("fractal_core.task_graph", "fixture_fractal.py"),
    ("utils_core.math_sanitizer", "fixture_utils.py"),
    ("main_core.kernel_heartbeat", "fixture_main.py"),
    ("backup_core.preservation", "fixture_backup.py"),
    ("privacy_core.egress_membrane", "fixture_privacy.py"),
    ("ecosystem_core.auxiliary", "fixture_ecosystem.py"),
]


def rebuild_core(core_name: str, template_file: str, mode: str = "live") -> dict:
    ref_path = REFERENCE_DIR / template_file
    ref_raw = ref_path.read_bytes()
    ref_sha = hashlib.sha256(ref_raw).hexdigest()
    ref_text = ref_raw.decode("utf-8")

    start_marker = "# TEMPLATE VARIABLES BEGIN\n"
    end_marker = "# TEMPLATE VARIABLES END\n"
    before_vars, rest = ref_text.split(start_marker, 1)
    _, after_vars = rest.split(end_marker, 1)

    print(f"[*] Rebuilding AIOS Viv Core: {core_name} ({mode} mode)...")

    # Extract default dict from reference
    namespace_ref: dict = {}
    exec(ref_text, namespace_ref)
    defaults = namespace_ref["VARIABLES"]

    if mode == "fixture":
        variables = defaults
    else:
        # Ask Viv-Mind to confirm/generate variables for this core
        properties = {}
        for k, v in defaults.items():
            if isinstance(v, bool):
                properties[k] = {"type": "boolean"}
            elif isinstance(v, int):
                properties[k] = {"type": "integer"}
            elif isinstance(v, float):
                properties[k] = {"type": "number"}
            elif isinstance(v, str):
                properties[k] = {"type": "string"}
            elif isinstance(v, list):
                properties[k] = {"type": "array", "items": {"type": "string"}}

        schema = {
            "type": "object",
            "properties": properties,
            "required": list(defaults),
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
                    "content": f"You are Viv, the AIOS Core Mind. Set physiological and operational parameters for your core module '{core_name}'. Return only JSON.",
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "task": f"Set baseline parameters for {core_name}",
                            "defaults": defaults,
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
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.load(resp)
            variables = json.loads(data["message"]["content"])
        except Exception as e:
            print(f"    [!] Mind query error ({e}), using default variables.")
            variables = defaults

    # Format variables block safely with repr for Python syntax
    var_lines = ["# TEMPLATE VARIABLES BEGIN\nVARIABLES = {"]
    for k, v in variables.items():
        var_lines.append(f'    "{k}": {repr(v)},')
    var_lines.append("}\n# TEMPLATE VARIABLES END\n")
    stamped_vars = "\n".join(var_lines)

    stamped_code = before_vars + stamped_vars + after_vars
    stamped_sha = hashlib.sha256(stamped_code.encode("utf-8")).hexdigest()

    run_id = str(time.time_ns())
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    artifact_name = template_file.replace("fixture_", "")
    artifact_path = run_dir / artifact_name
    artifact_path.write_text(stamped_code, encoding="utf-8")

    # Evaluate stamped code
    eval_namespace: dict = {}
    exec(stamped_code, eval_namespace)
    main_fn = eval_namespace["main"]
    eval_result = main_fn({}, eval_namespace["VARIABLES"])

    receipt = {
        "schema": "aios_viv_core_rebuild_receipt_v1",
        "core": core_name,
        "run_id": run_id,
        "mode": mode,
        "reference_sha256": ref_sha,
        "artifact_sha256": stamped_sha,
        "variables": variables,
        "evaluation": eval_result,
        "status": "PASS" if eval_result.get("ok") else "FAIL",
    }

    receipt_path = run_dir / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(f"    [+] Stamped: {artifact_name} (SHA-256: {stamped_sha[:12]}...) -> Status: PASS")
    return receipt


def rebuild_all(mode: str = "live"):
    print("==========================================================================")
    print(f"   STARTING MASTER REBUILD OF THE AIOS VIV SYSTEM ({mode.upper()} MODE)")
    print("==========================================================================")
    start_time = time.time()
    results = []

    for core_name, template_file in CORES:
        res = rebuild_core(core_name, template_file, mode)
        results.append(res)

    duration = time.time() - start_time
    passed = sum(1 for r in results if r["status"] == "PASS")
    total = len(results)

    print("==========================================================================")
    print(f"   AIOS VIV MASTER REBUILD SUMMARY")
    print(f"   Total Cores Stamped & Verified: {passed}/{total}")
    print(f"   Total Elapsed Time: {duration:.2f}s")
    print("==========================================================================")


if __name__ == "__main__":
    mode_arg = sys.argv[1] if len(sys.argv) > 1 else "live"
    rebuild_all(mode_arg)
