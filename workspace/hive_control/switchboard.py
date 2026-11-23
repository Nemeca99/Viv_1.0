"""One-request transport from Rust to Viv/Swarm/NumPy services.

The Rust process owns task state, keys, tool approval, and artifact writes.
This process returns data only and never writes an artifact.
"""

from __future__ import annotations

import ast
import importlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "hive_numpy_bridge"))


def _integer_cases(check: dict[str, Any]) -> list[tuple[int, int]]:
    rows = check.get("cases")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 32:
        raise ValueError("verification requires 1 to 32 explicit cases")
    cases: list[tuple[int, int]] = []
    for row in rows:
        if (
            not isinstance(row, dict)
            or type(row.get("input")) is not int
            or type(row.get("expected")) is not int
            or abs(row["input"]) > 1_000_000
            or abs(row["expected"]) > 1_000_001
        ):
            raise ValueError("case values must be bounded integers")
        cases.append((row["input"], row["expected"]))
    return cases


def _verify_python_increment(code: str, cases: list[tuple[int, int]]) -> dict[str, Any]:
    """Admit only a tiny AST grammar; never execute worker-produced Python."""
    try:
        module = ast.parse(code)
    except SyntaxError as exc:
        return {"passed": False, "error": f"SyntaxError: {exc}"}
    if len(module.body) != 1 or not isinstance(module.body[0], ast.FunctionDef):
        return {"passed": False, "error": "source must contain only increment()"}
    function = module.body[0]
    valid = (
        function.name == "increment"
        and not function.decorator_list
        and not function.args.defaults
        and not function.args.kwonlyargs
        and function.args.vararg is None
        and function.args.kwarg is None
        and len(function.args.args) == 1
        and function.args.args[0].arg == "value"
        and isinstance(function.returns, ast.Name)
        and function.returns.id == "int"
        and isinstance(function.args.args[0].annotation, ast.Name)
        and function.args.args[0].annotation.id == "int"
        and len(function.body) == 1
        and isinstance(function.body[0], ast.Return)
        and isinstance(function.body[0].value, ast.BinOp)
        and isinstance(function.body[0].value.left, ast.Name)
        and function.body[0].value.left.id == "value"
        and isinstance(function.body[0].value.op, ast.Add)
        and isinstance(function.body[0].value.right, ast.Constant)
        and type(function.body[0].value.right.value) is int
        and function.body[0].value.right.value == 1
    )
    if not valid:
        return {
            "passed": False,
            "error": "source violates the bounded Python increment grammar",
            "execution": "not_run_static_ast_contract",
        }
    ruff = ROOT / ".hive_proof_env" / "Scripts" / "ruff.exe"
    if not ruff.is_file():
        return {"passed": False, "error": "pinned Ruff executable unavailable"}
    added_final_newline = not code.endswith("\n")
    normalized_code = code.rstrip("\r\n") + "\n"
    try:
        with tempfile.TemporaryDirectory(prefix="hive-python-static-") as folder:
            source = Path(folder) / "candidate.py"
            source.write_text(normalized_code, encoding="utf-8")
            checks = {}
            for name, args in (
                ("ruff", ["check", "--isolated", str(source)]),
                ("ruff_format", ["format", "--check", "--isolated", str(source)]),
            ):
                result = subprocess.run(
                    [str(ruff), *args],
                    capture_output=True,
                    text=True,
                    timeout=20,
                    check=False,
                )
                checks[name] = result.returncode == 0
            passed = all(value + 1 == expected for value, expected in cases) and all(
                checks.values()
            )
            return {
                "passed": passed,
                "error": None if passed else "source, quality checks, or cases failed",
                "case_count": len(cases),
                "quality_checks": {
                    **checks,
                    "final_newline_added": added_final_newline,
                },
                "execution": "not_run_static_ast_contract",
            }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"passed": False, "error": f"{type(exc).__name__}: {exc}"}


def _verify_rust_increment(code: str, cases: list[tuple[int, int]]) -> dict[str, Any]:
    """Admit only a fixed safe expression, then ask rustc to compile (never run) it."""
    pattern = r"fn\s+increment\s*\(\s*value\s*:\s*i32\s*\)\s*->\s*i32\s*\{\s*value\s*\+\s*1\s*\}"
    if re.fullmatch(pattern, code.strip(), flags=re.DOTALL) is None:
        return {
            "passed": False,
            "error": "source violates the bounded Rust increment grammar",
        }
    if any(
        not -(2**31) <= value < 2**31 or expected != value + 1
        for value, expected in cases
    ):
        return {
            "passed": False,
            "error": "cases violate bounded i32 increment contract",
        }
    rustc = shutil.which("rustc")
    rustfmt = shutil.which("rustfmt")
    if rustc is None or rustfmt is None:
        return {"passed": False, "error": "rustc or rustfmt unavailable"}
    try:
        with tempfile.TemporaryDirectory(prefix="hive-rust-static-") as folder:
            source = Path(folder) / "candidate.rs"
            output = Path(folder) / "candidate.rmeta"
            added_final_newline = not code.endswith("\n")
            source.write_text(code.rstrip("\r\n") + "\n", encoding="utf-8")
            formatted = subprocess.run(
                [rustfmt, "--check", "--edition", "2021", str(source)],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            if formatted.returncode != 0:
                return {
                    "passed": False,
                    "error": f"rustfmt check failed: {(formatted.stderr + formatted.stdout)[-2000:]}",
                }
            result = subprocess.run(
                [
                    rustc,
                    "--edition=2021",
                    "--crate-type=lib",
                    "--emit=metadata",
                    str(source),
                    "-o",
                    str(output),
                ],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        passed = result.returncode == 0
        return {
            "passed": passed,
            "error": None if passed else result.stderr[-2000:],
            "case_count": len(cases),
            "quality_checks": {
                "rustfmt": True,
                "rustc_metadata_compile": passed,
                "final_newline_added": added_final_newline,
            },
            "execution": "compiled_not_run_static_source_contract",
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"passed": False, "error": f"{type(exc).__name__}: {exc}"}


def mind(phase: str, mode: str, greeting: str | None = None) -> dict[str, Any]:
    from hive_foreman_memory import load_latest, routing_packet

    foreman = routing_packet(load_latest())
    if mode == "fixture":
        values = (
            {
                "module_docstring": "Hive greeting module",
                "import_template_id": "python.typing_final_import",
            }
            if phase == "header"
            else {"greeting": greeting, "function_name": "greet"}
        )
        return {
            "values": values,
            "approved_tools": ["render_template", "write_run_artifact"],
            "foreman_snapshot_id": foreman["snapshot_id"],
            "mode": "fixture",
        }
    if mode != "live":
        raise ValueError("unknown Mind mode")
    if phase == "header":
        schema = {
            "type": "object",
            "properties": {
                "module_docstring": {
                    "type": "string",
                    "enum": ["Hive greeting module"],
                },
                "import_template_id": {
                    "type": "string",
                    "enum": ["python.typing_final_import"],
                },
                "approved_tools": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["render_template", "write_run_artifact"],
                    },
                    "minItems": 2,
                    "maxItems": 2,
                },
            },
            "required": ["module_docstring", "import_template_id", "approved_tools"],
            "additionalProperties": False,
        }
        task = {
            "objective": "Prepare data slots for a three-step hello.py template chain.",
            "requested_tools": ["render_template", "write_run_artifact"],
            "user_authority": "The Architect authorized this isolated LocalCoder proof.",
            "foreman_context": foreman,
        }
    elif phase == "greeting":
        schema = {
            "type": "object",
            "properties": {
                "greeting": {"type": "string", "enum": [greeting]},
                "function_name": {"type": "string", "enum": ["greet"]},
                "approved_tools": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["render_template", "write_run_artifact"],
                    },
                    "minItems": 2,
                    "maxItems": 2,
                },
            },
            "required": ["greeting", "function_name", "approved_tools"],
            "additionalProperties": False,
        }
        task = {
            "objective": "Resume after the Architect's reply; prepare template data slots.",
            "human_reply": greeting,
            "requested_tools": ["render_template", "write_run_artifact"],
            "foreman_context": foreman,
        }
    else:
        raise ValueError("unknown Mind phase")
    body = {
        "model": "qwen3:8b-local",
        "stream": False,
        "format": schema,
        "think": False,
        "keep_alive": "10m",
        "messages": [
            {
                "role": "system",
                "content": "You are Viv, the Hive Mind. Return only typed data slots and explicitly approve only the two requested, user-authorized proof tools. No source code or tool calls. Follow the supplied Foreman context.",
            },
            {"role": "user", "content": json.dumps(task, ensure_ascii=False)},
        ],
        "options": {"temperature": 0, "seed": 42, "num_ctx": 4096, "num_predict": 128},
    }
    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=240) as response:
        result = json.load(response)
    parsed = json.loads(result["message"]["content"])
    approved = parsed.pop("approved_tools")
    return {
        "values": parsed,
        "approved_tools": approved,
        "foreman_snapshot_id": foreman["snapshot_id"],
        "mode": "live",
        "model_metrics": {
            key: result.get(key)
            for key in (
                "total_duration",
                "load_duration",
                "prompt_eval_count",
                "eval_count",
                "done_reason",
            )
        },
    }


def plan(mode: str, evidence: dict[str, Any]) -> dict[str, Any]:
    from hive_foreman_memory import load_latest, routing_packet

    foreman = routing_packet(load_latest())
    tasks = [
        {
            "id": "task-001",
            "agent_id": "stamp-header",
            "agent_kind": "deterministic",
            "capability": "stamp-template",
            "objective": "Stamp the module header",
            "depends_on": ["discover-templates"],
        },
        {
            "id": "task-002",
            "agent_id": "stamp-import",
            "agent_kind": "deterministic",
            "capability": "stamp-template",
            "objective": "Stamp the typing import",
            "depends_on": ["task-001"],
        },
        {
            "id": "human-greeting",
            "agent_id": "queen-via-viv",
            "agent_kind": "human",
            "capability": "reply",
            "objective": "Supply the greeting string",
            "depends_on": ["task-002"],
        },
        {
            "id": "task-003",
            "agent_id": "stamp-function",
            "agent_kind": "deterministic",
            "capability": "stamp-template",
            "objective": "Stamp the greeting function",
            "depends_on": ["task-002", "human-greeting"],
        },
    ]
    if mode == "fixture":
        return {
            "tasks": tasks,
            "foreman_snapshot_id": foreman["snapshot_id"],
            "mode": mode,
        }
    if mode != "live":
        raise ValueError("unknown Mind mode")
    task_schema = {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "agent_id": {"type": "string"},
            "agent_kind": {"type": "string", "enum": ["deterministic", "human"]},
            "capability": {"type": "string", "enum": ["stamp-template", "reply"]},
            "objective": {"type": "string"},
            "depends_on": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "id",
            "agent_id",
            "agent_kind",
            "capability",
            "objective",
            "depends_on",
        ],
        "additionalProperties": False,
    }
    schema = {
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "items": task_schema,
                "minItems": 4,
                "maxItems": 4,
            }
        },
        "required": ["tasks"],
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
                "content": "You are Viv, the Hive Mind. Plan four bounded jobs for the user's hello.py task. Use exactly the four task IDs and assigned agents shown in the user request; choose dependencies so the import follows the header, the human greeting follows the import, and the function follows the greeting. Return JSON only. No tools or source code.",
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "user_task": "Build hello.py with a greeting function using approved templates.",
                        "discovery_evidence": evidence,
                        "foreman_context": foreman,
                        "required_tasks": tasks,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "options": {"temperature": 0, "seed": 42, "num_ctx": 4096, "num_predict": 400},
    }
    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=240) as response:
        result = json.load(response)
    parsed = json.loads(result["message"]["content"])
    return {
        "tasks": parsed["tasks"],
        "foreman_snapshot_id": foreman["snapshot_id"],
        "mode": mode,
        "model_metrics": {
            key: result.get(key)
            for key in (
                "total_duration",
                "load_duration",
                "prompt_eval_count",
                "eval_count",
                "done_reason",
            )
        },
    }


def dispatch(request: dict[str, Any]) -> dict[str, Any]:
    op = request.get("op")
    if op == "template_rebuild_mind":
        from hive_foreman_memory import load_latest, routing_packet

        foreman = routing_packet(load_latest())
        phase = request["phase"]
        if phase == "plan":
            payload = {
                "tasks": [
                    {"id": "import", "depends_on": []},
                    {"id": "variables", "depends_on": ["import"]},
                    {"id": "function", "depends_on": ["variables"]},
                    {"id": "registry", "depends_on": ["function"]},
                ]
            }
            properties = {
                "tasks": {
                    "type": "array",
                    "minItems": 4,
                    "maxItems": 4,
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "depends_on": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["id", "depends_on"],
                        "additionalProperties": False,
                    },
                }
            }
        elif phase == "slots":
            payload = {"message": "hive-template-rebuild", "suffix": "verified"}
            properties = {
                "message": {"type": "string", "maxLength": 80},
                "suffix": {"type": "string", "maxLength": 80},
            }
        else:
            raise ValueError("unknown template rebuild phase")
        if request["mode"] == "fixture":
            return {"value": payload, "foreman_snapshot_id": foreman["snapshot_id"]}
        if request["mode"] != "live":
            raise ValueError("unknown template rebuild mode")
        schema = {
            "type": "object",
            "properties": properties,
            "required": list(properties),
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
                    "content": "You are Viv, the Hive Mind. Return only JSON data. The swarm stamps approved source spans. Never generate source code or tool calls. Follow the Foreman snapshot.",
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "task": "Rebuild the AIOS fixture.echo template as four bounded stamp tasks. Preserve the source function body. Select short literal values for the two declared VARIABLES keys.",
                            "phase": phase,
                            "reference_sha256": request["reference_sha256"],
                            "required_plan": payload if phase == "plan" else None,
                            "declared_slots": ["message", "suffix"],
                            "foreman_context": foreman,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "options": {
                "temperature": 0,
                "seed": 42,
                "num_ctx": 4096,
                "num_predict": 300,
            },
        }
        api = urllib.request.Request(
            "http://127.0.0.1:11434/api/chat",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(api, timeout=240) as response:
            result = json.load(response)
        return {
            "value": json.loads(result["message"]["content"]),
            "foreman_snapshot_id": foreman["snapshot_id"],
            "model_metrics": {
                key: result.get(key)
                for key in (
                    "total_duration",
                    "load_duration",
                    "prompt_eval_count",
                    "eval_count",
                    "done_reason",
                )
            },
        }
    if op == "mind":
        return mind(request["phase"], request["mode"], request.get("greeting"))
    if op == "plan":
        return plan(request["mode"], request["evidence"])
    if op == "render":
        from hive_template_runtime import TemplateRuntime

        rendered = TemplateRuntime().render(request["template_id"], request["slots"])
        return {
            "template_id": rendered.template_id,
            "source_sha256": rendered.source_sha256,
            "output_sha256": rendered.output_sha256,
            "code": rendered.code,
        }
    if op == "validate":
        source = request["source"]

        def allowed_import(
            name: str,
            globals_: Any = None,
            locals_: Any = None,
            fromlist: tuple[str, ...] = (),
            level: int = 0,
        ) -> Any:
            if (
                name == "typing"
                and set(fromlist).issubset({"Final", "Optional"})
                and level == 0
            ):
                return importlib.import_module("typing")
            raise ImportError("template proof import outside allowlist")

        try:
            namespace: dict[str, Any] = {
                "__builtins__": {"__import__": allowed_import, "str": str}
            }
            exec(compile(source, "hello.py", "exec", dont_inherit=True), namespace)
            actual = namespace["greet"]()
            return {"passed": actual == request["expected"], "actual": actual}
        except (NameError, ImportError, SyntaxError, KeyError) as exc:
            return {"passed": False, "error": type(exc).__name__, "detail": str(exc)}
    if op == "numeric_contract":
        import numpy as np
        from numpy_backend import array_contract_summary

        return {"numpy_version": np.__version__, "summary": array_contract_summary()}
    if op == "execute_numerical_placement":
        # Explicit NumPy host (CPU) <-> CuPy device (VRAM) computation
        sys.path.insert(0, str(ROOT / "hive_numpy_bridge"))
        import gpu_backend

        req = request.get("payload") or {
            "n": 4,
            "matrix_a": [
                [1.0, 2.0, 3.0, 4.0],
                [5.0, 6.0, 7.0, 8.0],
                [9.0, 10.0, 11.0, 12.0],
                [13.0, 14.0, 15.0, 16.0],
            ],
            "matrix_b": [
                [2.0, 0.0, 1.0, 3.0],
                [1.0, 2.0, 0.0, 4.0],
                [3.0, 1.0, 2.0, 0.0],
                [0.0, 4.0, 3.0, 1.0],
            ],
            "bias": [0.5, 1.5, -0.5, 2.0],
            "inject_fault": request.get("inject_fault", False),
        }
        res = gpu_backend.run(req)
        return res
    if op == "stage_prepare":
        # Stage and check a task-scoped Python source file before dispatch
        sys.path.insert(0, str(ROOT / "hive_quality"))
        import prepare as pq

        source_arg = request["source"]
        source_path = str(
            (ROOT / source_arg).resolve()
            if not Path(source_arg).is_absolute()
            else source_arg
        )
        receipt = pq.prepare(source_path)
        return {
            "status": receipt["status"],
            "source": receipt["source"],
            "source_sha256": receipt["source_sha256"],
            "prepared": receipt["prepared"],
            "prepared_sha256": receipt["prepared_sha256"],
            "diff": receipt["diff"],
            "checks": {
                "format": receipt["checks"]["format"]["exit_code"] == 0,
                "ruff": receipt["checks"]["ruff"]["exit_code"] == 0,
                "vulture": receipt["checks"]["vulture"]["exit_code"] == 0,
                "compile": receipt["checks"]["compile"]["exit_code"] == 0,
            },
        }
    if op == "specialist_infer":
        # Dispatch bounded task to stacked specialist LoRA adapter
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer

        language = request["language"]
        task_prompt = request["prompt"]
        if language == "python":
            specialist_run = "viv-python-specialist-v2"
            subname = "python-specialist"
        elif language == "rust":
            specialist_run = "viv-rust-specialist-v1"
            subname = "rust-specialist"
        else:
            specialist_run = "viv-aios-specialist-v2"
            subname = "viv-aios-specialist-v2"
        base_dir = ROOT / "swarm_adapters" / "models" / "Qwen3-1.7B"
        shared_dir = (
            ROOT / "swarm_adapters" / "runs" / "viv-swarm-default-v2" / "swarm-default"
        )
        run_dir = ROOT / "swarm_adapters" / "runs" / specialist_run
        specialist_name = subname
        specialist_dir = (
            run_dir / subname
            if (run_dir / subname / "adapter_config.json").exists()
            else run_dir
        )

        tokenizer = AutoTokenizer.from_pretrained(base_dir, local_files_only=True)
        tokenizer.pad_token = tokenizer.eos_token
        # Swarm inference is intentionally CPU/RAM resident. Keep Viv's Mind
        # model and its VRAM allocation independent from specialist workers.
        torch.set_num_threads(4)
        torch.set_num_interop_threads(1)
        base = AutoModelForCausalLM.from_pretrained(
            base_dir,
            local_files_only=True,
            device_map={"": "cpu"},
            torch_dtype=torch.float32,
        )
        model = PeftModel.from_pretrained(
            base,
            shared_dir,
            adapter_name="swarm-default",
            torch_device="cpu",
            device_map={"": "cpu"},
        )
        model.load_adapter(
            specialist_dir,
            adapter_name=specialist_name,
            torch_device="cpu",
            device_map={"": "cpu"},
        )
        model.base_model.set_adapter(["swarm-default", specialist_name])
        active_adapters = list(model.active_adapters)
        expected_adapters = ["swarm-default", specialist_name]
        if active_adapters != expected_adapters:
            raise RuntimeError(
                f"specialist adapter composition mismatch: {active_adapters}"
            )
        model.requires_grad_(False)
        model.eval()
        trainable_parameter_count = sum(
            parameter.numel()
            for parameter in model.parameters()
            if parameter.requires_grad
        )
        if trainable_parameter_count != 0:
            raise RuntimeError("inference loaded trainable adapter parameters")
        model_devices = {parameter.device.type for parameter in model.parameters()}
        if model_devices != {"cpu"}:
            raise RuntimeError(
                f"Swarm worker escaped CPU placement: {sorted(model_devices)}"
            )
        worker_device = "cpu"

        messages = [
            {
                "role": "system",
                "content": (
                    "You are Viv operating as one stateless internal Hive Swarm worker. "
                    "Every Mind, Swarm, and AIOS component is Viv. Perform exactly one bounded task. "
                    "Use only supplied inputs. Do not add tasks, contact agents, or claim unperformed work. "
                    "Return one JSON object with status, result, evidence, and unknowns."
                ),
            },
            {"role": "user", "content": task_prompt},
        ]
        prompt = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True, enable_thinking=False
        )
        encoded = tokenizer(prompt, return_tensors="pt", add_special_tokens=False).to(
            worker_device
        )
        with torch.inference_mode():
            output = model.generate(
                **encoded,
                max_new_tokens=160,
                do_sample=False,
                pad_token_id=tokenizer.eos_token_id,
            )
        raw = tokenizer.decode(
            output[0, encoded["input_ids"].shape[1] :], skip_special_tokens=True
        ).strip()
        parsed = None
        try:
            parsed = json.loads(raw)
        except Exception:
            pass
        normalization_steps = []
        if (
            language in {"python", "rust"}
            and isinstance(parsed, dict)
            and isinstance(parsed.get("result"), str)
            and not parsed["result"].endswith("\n")
        ):
            parsed["result"] = parsed["result"].rstrip("\r\n") + "\n"
            normalization_steps.append("ensure_final_newline")
        return {
            "language": language,
            "specialist_run": specialist_run,
            "worker_device": worker_device,
            "active_adapters": active_adapters,
            "trainable_parameter_count": trainable_parameter_count,
            "normalization_steps": normalization_steps,
            "raw_output": raw,
            "parsed": parsed,
            "generation_count": 1,
        }
    if op == "specialist_verify":
        # Deterministic checking outside the model. Never execute model code.
        language = request["language"]
        code = request["code"]
        check = request["check"]
        if not isinstance(code, str) or not isinstance(check, dict):
            return {"passed": False, "error": "invalid verifier input"}
        if language == "aios":
            pattern = check.get("pattern")
            passed = bool(pattern and isinstance(pattern, str) and pattern in code)
            return {
                "passed": passed,
                "error": None if passed else f"missing pattern: {pattern}",
            }
        if language not in {"python", "rust"}:
            return {"passed": False, "error": "verification language is not admitted"}
        try:
            cases = _integer_cases(check)
        except ValueError as exc:
            return {"passed": False, "error": str(exc)}
        if language == "python":
            return _verify_python_increment(code, cases)
        return _verify_rust_increment(code, cases)
    raise ValueError("operation unavailable")


def main() -> int:
    try:
        line = sys.stdin.readline()
        if not line or len(line) > 100_000:
            raise ValueError("request missing or too large")
        result = dispatch(json.loads(line))
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(
            json.dumps({"ok": False, "error": type(exc).__name__, "detail": str(exc)})
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
