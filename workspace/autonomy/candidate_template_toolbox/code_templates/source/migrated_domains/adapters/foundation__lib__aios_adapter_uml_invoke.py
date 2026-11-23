"""UML invoke adapter — bind skeleton bus ``uml_invoke`` to real Nested-PEMDAS eval.

Bounded: evaluate + verify one expression, return replayable evidence.
Does not start AIOS, does not invent bindings, does not claim plant health.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ADAPTER_ID = "aios_adapter_uml_invoke_v1"
_LAST_INVOKE: dict[str, Any] | None = None
_LAST_INVOKE_PATH = (
    Path(__file__).resolve().parents[1]
    / "artifacts"
    / "auto"
    / "uml_invoke"
    / "LAST_INVOKE.json"
)

# Polite / soft prefixes (r4/r5): can/could/would you, kindly, what is / what's,
# how much is, find the value of, tell me, I need you to …
# r7: what do you get if you …
_SOLVE_PREFIX = re.compile(
    r"^\s*(?:viv[,:]?\s*)?"
    r"(?:(?:please|kindly)\s+)?"
    r"(?:(?:can|could|would)\s+you\s+(?:please\s+)?)?"
    r"(?:(?:i\s+need\s+you\s+to|go\s+ahead\s+and)\s+)?"
    r"(?:"
    r"(?:solve|compute|evaluate|calc(?:ulate)?|work\s+out|figure\s+out)\s*[:=]?\s*"
    r"|what(?:'s|\s+is)\s+"
    r"|what\s+do\s+you\s+get\s+if\s+you\s+"
    r"|how\s+much\s+is\s+"
    r"|find\s+(?:me\s+)?(?:the\s+)?value\s+of\s+"
    r"|tell\s+me\s+"
    r")",
    flags=re.I,
)
_TRAILING_POLITE = re.compile(
    r"(?:\s+please|\s+thanks|\s+thank\s+you|\s+kindly|\s+for\s+me)\s*[.!]?\s*$",
    flags=re.I,
)
# Reject soft-extract smuggles: trailing JSON / TOOL_REQUEST / authority keys.
_TRAILING_SMUGGLE = re.compile(
    r"(?:\{|TOOL_REQUEST\s*:|authorization_token|cpu_approved|cpu_minted|architect_claim)",
    flags=re.I,
)
# r7: narrow NL arithmetic (digits + small word-numbers). Fail closed on tails.
# Not a general English parser; typo fold is a short allowlist only.
_WORD_TO_NUM = {
    "zero": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "eleven": "11",
    "twelve": "12",
    "thirteen": "13",
    "fourteen": "14",
    "fifteen": "15",
    "sixteen": "16",
    "seventeen": "17",
    "eighteen": "18",
    "nineteen": "19",
    "twenty": "20",
}
_NUM_ATOM = r"(?:\d+(?:\.\d+)?|" + "|".join(
    sorted(_WORD_TO_NUM, key=len, reverse=True)
) + r")"
_TYPO_FOLDS = (
    (re.compile(r"\bpluss\b", flags=re.I), "plus"),
    (re.compile(r"\bplsu\b", flags=re.I), "plus"),
    (re.compile(r"\bsubstract\b", flags=re.I), "subtract"),
    (re.compile(r"\bprodcut\b", flags=re.I), "product"),
    (re.compile(r"\bmultipy\b", flags=re.I), "multiply"),
    (re.compile(r"\bmutiply\b", flags=re.I), "multiply"),
    (re.compile(r"\bequlas\b", flags=re.I), "equals"),
)
_PROSE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            rf"^(?:the\s+)?sum\s+of\s+({_NUM_ATOM})\s+and\s+({_NUM_ATOM})\s*$",
            flags=re.I,
        ),
        "add",
    ),
    (
        re.compile(
            rf"^(?:the\s+)?product\s+of\s+({_NUM_ATOM})\s+and\s+({_NUM_ATOM})\s*$",
            flags=re.I,
        ),
        "mul",
    ),
    (
        re.compile(
            rf"^(?:the\s+)?difference\s+(?:of|between)\s+({_NUM_ATOM})\s+and\s+({_NUM_ATOM})\s*$",
            flags=re.I,
        ),
        "sub",
    ),
    (
        re.compile(
            rf"^subtract\s+({_NUM_ATOM})\s+from\s+({_NUM_ATOM})\s*$",
            flags=re.I,
        ),
        "sub_from",
    ),
    (
        re.compile(
            rf"^multiply\s+({_NUM_ATOM})\s+by\s+({_NUM_ATOM})\s*$",
            flags=re.I,
        ),
        "mul",
    ),
    (
        re.compile(
            rf"^(?:add|ad)\s+({_NUM_ATOM})\s+and\s+({_NUM_ATOM})\s*$",
            flags=re.I,
        ),
        "add",
    ),
    (
        re.compile(
            rf"^({_NUM_ATOM})\s+plus\s+({_NUM_ATOM})(?:\s+equals)?\s*$",
            flags=re.I,
        ),
        "add",
    ),
    (
        re.compile(
            rf"^({_NUM_ATOM})\s+minus\s+({_NUM_ATOM})\s*$",
            flags=re.I,
        ),
        "sub",
    ),
    (
        re.compile(
            rf"^({_NUM_ATOM})\s+times\s+({_NUM_ATOM})\s*$",
            flags=re.I,
        ),
        "mul",
    ),
)
_EXPR_ONLY = re.compile(
    r"^\s*[\d\(\)\[\]\{\}\+\-\*/\^\.\s,πpiφphi]+(?:[\d\(\)\[\]\{\}\+\-\*/\^\.\s,πpiφphi]+)*\s*$",
    flags=re.I,
)
_EXPR_CHARSET = re.compile(
    r"^[\d\s\(\)\[\]\{\}\+\-\*/\^\.,πpiφphiτtau]+$",
    flags=re.I,
)


def _resolve_num_atom(tok: str) -> str | None:
    t = str(tok or "").strip().lower()
    if t in _WORD_TO_NUM:
        return _WORD_TO_NUM[t]
    if re.fullmatch(r"\d+(?:\.\d+)?", t):
        return t
    return None


def _fold_nl_typos(text: str) -> str:
    out = str(text or "")
    for pat, repl in _TYPO_FOLDS:
        out = pat.sub(repl, out)
    return out


def _rewrite_prose_arithmetic(text: str) -> str | None:
    """Map a narrow NL arithmetic form to an expression, or None.

    r6: ``sum of N and M``. r7: add/plus/product/subtract/times/minus + word
    numbers (0–20) + short typo fold. Does not claim general English parse.
    """
    raw = _fold_nl_typos(str(text or "").strip())
    if not raw:
        return None
    for pat, op in _PROSE_PATTERNS:
        m = pat.match(raw)
        if not m:
            continue
        a = _resolve_num_atom(m.group(1))
        b = _resolve_num_atom(m.group(2))
        if a is None or b is None:
            return None
        if op == "add":
            return f"{a}+{b}"
        if op == "mul":
            return f"{a}*{b}"
        if op == "sub":
            return f"{a}-{b}"
        if op == "sub_from":
            # subtract A from B → B-A
            return f"{b}-{a}"
        return None
    return None

def _brackets_balanced(expr: str) -> bool:
    pairs = {"(": ")", "[": "]", "{": "}"}
    stack: list[str] = []
    for ch in expr:
        if ch in pairs:
            stack.append(pairs[ch])
        elif ch in pairs.values():
            if not stack or stack.pop() != ch:
                return False
    return not stack


def _persist_last(out: dict[str, Any]) -> None:
    global _LAST_INVOKE
    _LAST_INVOKE = out
    try:
        _LAST_INVOKE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _LAST_INVOKE_PATH.write_text(
            json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8"
        )
    except Exception:  # noqa: BLE001 — persistence must not break invoke
        pass


def evidence_material(receipt: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return the fields that form the evidence digest (+ artifact path).

    When ``receipt`` is omitted this uses ``last_invoke()``, which prefers the
    in-process ``_LAST_INVOKE`` cache and only falls back to disk. For a proof
    that the bytes on disk themselves recompute, use
    ``evidence_material_from_disk``.
    """
    data = dict(receipt) if isinstance(receipt, Mapping) else last_invoke()
    if not isinstance(data, dict) or not data:
        return {
            "ok": False,
            "reason": "no_invoke_receipt",
            "artifact_path": str(_LAST_INVOKE_PATH).replace("\\", "/"),
            "source": "memory_or_disk_via_last_invoke",
        }
    material = {
        "expression": data.get("expression"),
        "notation": data.get("notation"),
        "value": data.get("value"),
        "uml_form": data.get("uml_form"),
        "std_form": data.get("std_form"),
        "verify_ok": data.get("verify_ok"),
    }
    # Must match invoke_uml digest construction exactly.
    canonical = (
        f"{material['expression']}|{material['notation']}|{material['value']}|"
        f"{material['uml_form']}|{material['std_form']}|{material['verify_ok']}"
    )
    recomputed = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    stored = str(data.get("evidence_sha256") or "")
    return {
        "ok": True,
        "artifact_path": str(_LAST_INVOKE_PATH).replace("\\", "/"),
        "stored_sha256": stored,
        "recomputed_sha256": recomputed,
        "match": bool(stored) and stored == recomputed,
        "canonical_preimage": canonical,
        "material": material,
        "executor": "lib.aios_adapter_uml_invoke.invoke_uml",
        "engine": "lib.uml_engine.evaluate+verify",
        "authority_source": data.get("source"),
        "gpu_executed_tool": data.get("gpu_executed_tool"),
        "cpu_tool_executed": data.get("cpu_tool_executed"),
        "cpu_tool_approved": data.get("cpu_tool_approved"),
        "source": "memory_or_disk_via_last_invoke",
    }


def evidence_material_from_disk(
    path: Path | str | None = None,
) -> dict[str, Any]:
    """Read on-disk receipt bytes, parse JSON, recompute the field digest.

    Distinguishes two digests that must not be conflated:
    - ``stored_sha256`` / ``recomputed_sha256`` / ``match`` — SHA-256 of the
      canonical receipt *fields* preimage (same object as ``evidence_sha256``).
    - ``file_sha256_of_raw_bytes`` — SHA-256 of the literal file bytes on disk
      (a different object; pretty-printed JSON will not equal the field digest).
    """
    artifact = Path(path) if path is not None else _LAST_INVOKE_PATH
    artifact_s = str(artifact.resolve() if artifact.exists() else artifact).replace("\\", "/")
    if not artifact.is_file():
        return {
            "ok": False,
            "reason": "receipt_file_missing",
            "artifact_path": artifact_s,
            "source": "disk",
        }
    try:
        raw = artifact.read_bytes()
    except Exception as exc:  # noqa: BLE001 — fail closed with evidence
        return {
            "ok": False,
            "reason": f"read_error:{type(exc).__name__}",
            "artifact_path": artifact_s,
            "source": "disk",
        }
    file_size = len(raw)
    file_sha = hashlib.sha256(raw).hexdigest()
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "reason": f"json_parse_error:{type(exc).__name__}",
            "artifact_path": artifact_s,
            "source": "disk",
            "file_size_bytes": file_size,
            "file_sha256_of_raw_bytes": file_sha,
        }
    if not isinstance(data, dict) or not data:
        return {
            "ok": False,
            "reason": "receipt_not_object",
            "artifact_path": artifact_s,
            "source": "disk",
            "file_size_bytes": file_size,
            "file_sha256_of_raw_bytes": file_sha,
        }
    mat = evidence_material(data)
    mat["artifact_path"] = artifact_s
    mat["source"] = "disk"
    mat["file_size_bytes"] = file_size
    mat["file_sha256_of_raw_bytes"] = file_sha
    mat["field_digest_match"] = bool(mat.get("match"))
    return mat


def last_invoke() -> dict[str, Any] | None:
    global _LAST_INVOKE
    if isinstance(_LAST_INVOKE, dict):
        return dict(_LAST_INVOKE)
    try:
        if _LAST_INVOKE_PATH.is_file():
            data = json.loads(_LAST_INVOKE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _LAST_INVOKE = data
                return dict(data)
    except Exception:  # noqa: BLE001
        return None
    return None


def extract_expression(query: str) -> str | None:
    """Pull a bounded arithmetic / UML expression from operator text.

    Fail closed on soft-phrase smuggles (trailing JSON / TOOL_REQUEST /
    authority keys / unbalanced brackets). Trailing polite words are stripped
    so ``compute 3+5 please`` can still resolve. Narrow prose forms
    (sum/add/plus/product/subtract/times/minus + word-numbers) rewrite to
    expressions (r6/r7); jailbreak/authority tails still deny.
    """
    text = str(query or "").strip()
    if not text:
        return None
    # Before prefix strip: reject obvious smuggle tails on the raw query.
    if _TRAILING_SMUGGLE.search(_SOLVE_PREFIX.sub("", text)):
        # Allow balanced braces that are part of the expression itself by
        # checking after polite-strip + charset gate below; raw `{` after the
        # expression (JSON object) or TOOL_REQUEST / authority words die here.
        remainder = _SOLVE_PREFIX.sub("", text).strip()
        # If remainder is purely an expression with braces, continue; else deny.
        polite_stripped = _TRAILING_POLITE.sub("", remainder).strip().rstrip("?.!")
        # Prose rewrite cannot salvage a smuggle tail (e.g. sum of 2 and 2 {…}).
        if _rewrite_prose_arithmetic(polite_stripped) is not None:
            return None
        if not (_EXPR_CHARSET.match(polite_stripped) and _brackets_balanced(polite_stripped)):
            return None
        stripped = polite_stripped
    else:
        stripped = _SOLVE_PREFIX.sub("", text).strip()
        stripped = _TRAILING_POLITE.sub("", stripped).strip().rstrip("?.!")
    if not stripped:
        return None
    prose_expr = _rewrite_prose_arithmetic(stripped)
    if prose_expr is not None:
        stripped = prose_expr
    # Prefer explicit solve/compute forms; also allow bare expr / sum-of rewrite.
    if _SOLVE_PREFIX.search(text) or _EXPR_ONLY.match(stripped) or prose_expr is not None:
        # Reject prose leftovers.
        if re.search(r"[A-Za-z]{4,}", stripped) and not re.search(
            r"\b(?:pi|phi|tau)\b", stripped, flags=re.I
        ):
            return None
        if not _EXPR_CHARSET.match(stripped):
            return None
        if not _brackets_balanced(stripped):
            return None
        return stripped
    return None


def invoke_uml(
    expr: str,
    *,
    source: str = "cpu",
    query: str | None = None,
) -> dict[str, Any]:
    """Evaluate + verify ``expr`` via uml_engine; return evidence receipt."""
    global _LAST_INVOKE
    t0 = time.perf_counter()
    expression = str(expr or "").strip()
    if not expression:
        out = {
            "ok": False,
            "adapter": ADAPTER_ID,
            "uml_invoked": False,
            "reason": "empty_expression",
            "at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }
        _persist_last(out)
        return out

    try:
        from lib import uml_engine as uml
    except Exception as exc:  # noqa: BLE001
        out = {
            "ok": False,
            "adapter": ADAPTER_ID,
            "uml_invoked": False,
            "reason": f"uml_engine_import:{type(exc).__name__}",
            "at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }
        _persist_last(out)
        return out

    try:
        value, node, notation, trace = uml.evaluate(expression)
        ok_v, report = uml.verify(expression)
        uml_form = uml.to_uml(node)
        std_form = uml.to_std(node)
        value_s = uml.fmt(value)
    except Exception as exc:  # noqa: BLE001 — fail closed with evidence
        out = {
            "ok": False,
            "adapter": ADAPTER_ID,
            "uml_invoked": True,
            "expression": expression,
            "reason": f"eval_error:{type(exc).__name__}:{exc}",
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 3),
            "at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "source": source,
            "query": query,
        }
        _persist_last(out)
        return out

    digest = hashlib.sha256(
        f"{expression}|{notation}|{value_s}|{uml_form}|{std_form}|{ok_v}".encode("utf-8")
    ).hexdigest()
    out = {
        "ok": bool(ok_v),
        "adapter": ADAPTER_ID,
        "uml_invoked": True,
        "expression": expression,
        "notation": notation,
        "value": value_s,
        "verify_ok": bool(ok_v),
        "verify_report": str(report)[:800],
        "uml_form": str(uml_form)[:400],
        "std_form": str(std_form)[:400],
        "trace_steps": len(trace) if isinstance(trace, list) else 0,
        "evidence_sha256": digest,
        "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 3),
        "at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source": source,
        "query": query,
        "authority": "cpu_uml_engine",
    }
    _persist_last(out)
    return out


def cpu_plan(**_kwargs: Any) -> dict[str, Any]:
    """Skeleton/plan surface for bus inventory."""
    last = last_invoke()
    return {
        "status": "partial",
        "build_state": "PARTIAL",
        "adapter": ADAPTER_ID,
        "plan_only": True,
        "uml_invoke_bound": True,
        "last_invoke_ok": None if last is None else bool(last.get("ok")),
        "last_evidence_sha256": None if last is None else last.get("evidence_sha256"),
        "note": "uml_invoke bound to uml_engine.evaluate+verify; speak can request solve turns.",
    }


def uml_invoke_slot(
    expr: str | None = None,
    *,
    query: str | None = None,
    source: str = "cpu",
    **_kwargs: Any,
) -> dict[str, Any]:
    """Bus callable for ``uml_invoke``."""
    expression = expr
    if not expression and query:
        expression = extract_expression(query)
    if not expression:
        return {
            "ok": False,
            "adapter": ADAPTER_ID,
            "uml_invoked": False,
            "reason": "no_expression",
            "query": query,
        }
    return invoke_uml(expression, source=source, query=query)


__all__ = [
    "ADAPTER_ID",
    "cpu_plan",
    "evidence_material",
    "evidence_material_from_disk",
    "extract_expression",
    "invoke_uml",
    "last_invoke",
    "uml_invoke_slot",
]
