"""Read-only UML boundary grounding for candidate code proposals.

This loads the Architect's UML_Calc engine and records its actual outputs for
the reserved logic-zero/division/modulo boundary. It is prompt context only:
it does not write topology, memory, training data, or execute model code.
"""
from __future__ import annotations

import hashlib
import importlib.util
import re
import sys
from pathlib import Path
from typing import Any

UML_ENGINE_PATH = Path(r"L:\LocalCoder\UML_Calc\uml_engine.py")
_MODULE_NAME = "viv_candidate_uml_engine_v1"
_ENGINE: Any = None
_TRIGGERS = re.compile(
    # Require arithmetic vocabulary. Bare slash/percent characters occur in
    # ordinary prose such as "character/count pairs" and must not contaminate
    # unrelated prompts with division-by-zero context.
    r"(?<![A-Za-z])(?:divid(?:e|es|ed|ing)|division|divisible|divisor|"
    r"denominator|quotient|modulo|modulus|remainder|exact multiple|multiple of)(?![A-Za-z])",
    re.IGNORECASE,
)
_CASES = ("<0,0>", "<!0,!0>", "<4,0>", "%[4,0]")


def _engine() -> Any:
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE
    if not UML_ENGINE_PATH.is_file():
        raise FileNotFoundError(f"UML_ENGINE_MISSING:{UML_ENGINE_PATH}")
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, UML_ENGINE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError("UML_ENGINE_SPEC_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    _ENGINE = module
    return module


def context_for_task(task: dict[str, Any]) -> dict[str, Any]:
    """Return executed UML evidence only for arithmetic-related coding tasks."""
    spec_text = str(task.get("spec", ""))
    if not _TRIGGERS.search(spec_text):
        return {"applicable": False, "engine_sha256": None, "cases": [], "prompt_context": ""}

    uml = _engine()
    cases = []
    for expression in _CASES:
        try:
            value, _node, notation, _trace = uml.evaluate(expression)
            rendered = uml.fmt(value)
            cases.append({"expression": expression, "result": str(rendered),
                          "notation": str(notation), "error": None})
        except Exception as exc:  # The UML engine's rejection is evidence too.
            cases.append({"expression": expression, "result": None,
                          "notation": "uml", "error": f"{type(exc).__name__}: {exc}"})

    if len(cases) != len(_CASES):
        raise RuntimeError("UML_BOUNDARY_CASE_COUNT_MISMATCH")
    if cases[0]["result"] != "!0" or cases[1]["result"] != "1" or cases[2]["result"] != "inf":
        raise RuntimeError("UML_ENGINE_BOUNDARY_CONTRACT_CHANGED")
    if not (cases[3]["error"] and cases[3]["error"].startswith("ZeroDivisionError:")):
        raise RuntimeError("UML_MODULO_ZERO_REJECTION_CONTRACT_CHANGED")

    lines = [
        "Verified Viv UML boundary from the local deterministic UML_Calc engine:",
        "<0,0> -> !0 (symbolic Logic Space, distinct from ordinary numeric zero).",
        "<!0,!0> -> 1.",
        "<4,0> -> inf.",
        "%[4,0] -> ZeroDivisionError in UML; do not execute modulo with a zero divisor.",
        "Preserve the task's explicit return contract. If it defines a result for a zero divisor, "
        "branch before host-language division or modulo; do not replace UML !0 with an assumed float.",
    ]
    spec_lower = spec_text.casefold()
    has_zero_operand = "zero" in spec_lower and any(
        term in spec_lower for term in ("divisor", "denominator", "division", "multiple"))
    if has_zero_operand and "false" in spec_lower:
        lines.append(
            "This task explicitly requires False for its zero-divisor case; make the zero branch "
            "return False. A zero check joined with OR that makes the function return True is wrong."
        )
    return {
        "applicable": True,
        "engine_path": str(UML_ENGINE_PATH),
        "engine_sha256": hashlib.sha256(UML_ENGINE_PATH.read_bytes()).hexdigest(),
        "cases": cases,
        "prompt_context": "\n".join(lines),
    }


__all__ = ["UML_ENGINE_PATH", "context_for_task"]
