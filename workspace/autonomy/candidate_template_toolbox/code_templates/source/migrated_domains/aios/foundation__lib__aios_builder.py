"""Legacy AIOS builder facade.

The historical catalog is retained as migration evidence, but it no longer
hands source text to the coding path. New capability must exist as an indexed
template and be selected by ID; the central coder facade rejects raw source.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

from lib.aios_coder import run_sandbox_tool, write_sandbox_tool
from lib.aios_sandbox import WORK, ensure_sandbox_home
from lib.security_membrane import tool_gate

BUILD = WORK / "aios_build"
MANIFEST = BUILD / "MANIFEST.md"
BUILT_LOG = BUILD / "BUILT.jsonl"
SCORECARD = BUILD / "scorecard.json"

# Real AIOS construction modules — not plant_brief theater.  These are a
# migration catalog only: source bodies are deliberately absent.  A module
# becomes executable only after an operator explicitly authors or adopts an
# indexed template with the same ID.
_MODULES: dict[str, dict[str, str]] = {
    "goal_board_status": {"why": "Expose standing goals + step progress for Architect review"},
    "attempt_replay": {"why": "Replay autonomy_attempts.jsonl — prove multi-step agency"},
    "plant_trend": {"why": "Score Master S_n, dormancy, and load from RID artifacts"},
    "build_scorecard": {"why": "Score which AIOS pillars have sandbox evidence versus gaps"},
    "handoff_packet": {"why": "Write an Architect handoff when stuck, dormant, or out of zone"},
    "organism_state_probe": {"why": "Probe organism state for AIOS spine health"},
    "next_build_ticket": {"why": "Emit the next AIOS build ticket from observed gaps"},
    "session_digest": {"why": "Digest sandbox sessions for continuity across Architect sessions"},
}


def _utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_build_home() -> Path:
    ensure_sandbox_home()
    BUILD.mkdir(parents=True, exist_ok=True)
    if not MANIFEST.is_file():
        MANIFEST.write_text(
            "# AIOS Build Manifest\n\nDeterministic template selections and receipts are recorded here. Foundation stays immutable.\n\n",
            encoding="utf-8",
        )
    return BUILD


def _template_status() -> dict[str, Any]:
    """Read the deterministic toolbox without importing any generated module."""
    try:
        repo_root = Path(__file__).resolve().parents[2]
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))
        from build_tools.template_builder_v1 import toolbox_status

        return toolbox_status()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "state": "HOLD", "reason": f"template_status_unavailable:{exc}", "templates": []}


def survey_gaps() -> dict[str, Any]:
    """Perceive which catalog IDs have an approved active template."""
    ensure_build_home()
    template_status = _template_status()
    have = {
        str(row.get("template_id"))
        for row in template_status.get("templates", [])
        if isinstance(row, dict) and row.get("template_id")
    }
    missing = [name for name in _MODULES if name not in have]
    # Prefer modules that are not yet built
    next_name = missing[0] if missing else None
    report = {
        "ok": True,
        "have": sorted(have),
        "missing": missing,
        "next": next_name,
        "catalog": list(_MODULES.keys()),
        "template_status": template_status,
        "at": _utc(),
    }
    SCORECARD.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def invent_next_module(*, s_n: float, force_name: str | None = None) -> dict[str, Any]:
    """Request an indexed template; no source body can be supplied here."""
    ensure_build_home()
    survey = survey_gaps()
    name = force_name or survey.get("next")
    if not name:
        # Catalog exhausted — invent a stamped extension probe from scorecard
        name = f"aios_ext_{datetime.now(timezone.utc).strftime('%H%M%S')}"
        why = "Catalog complete — extension probe from live scorecard"
    else:
        spec = _MODULES.get(name)
        if not spec:
            return {"ok": False, "error": f"unknown_module:{name}"}
        why = spec["why"]

    status = survey.get("template_status") or {}
    known = {
        str(row.get("template_id"))
        for row in status.get("templates", [])
        if isinstance(row, dict) and row.get("template_id")
    }
    if name not in known:
        return {
            "ok": False,
            "state": "HOLD",
            "error": "template_authoring_required",
            "reason": "catalog_id_is_not_an_approved_template",
            "module": name,
            "why": why,
            "template_status": status,
            "next": "human_review_author_or_adopt_indexed_template",
        }

    wr = write_sandbox_tool(tool=name, s_n=s_n)
    if not wr.get("ok"):
        return {"ok": False, "error": wr.get("reason"), "write": wr, "module": name}

    row = {
        "event": "invent",
        "at": _utc(),
        "module": name,
        "why": why,
        "path": wr.get("path"),
        "current": wr.get("current"),
        "generation_id": wr.get("generation_id"),
        "s_n": s_n,
    }
    with BUILT_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")

    return {
        "ok": True,
        "module": name,
        "why": why,
        "path": wr.get("path"),
        "current": wr.get("current"),
        "generation_id": wr.get("generation_id"),
        "stdout": f"invented {name} -> {wr.get('path')}",
    }


def run_module(*, module: str, s_n: float) -> dict[str, Any]:
    ensure_build_home()
    rn = run_sandbox_tool(tool=module, s_n=s_n)
    ok = bool(rn.get("ok"))
    row = {
        "event": "run",
        "at": _utc(),
        "module": module,
        "ok": ok,
        "stdout": (rn.get("stdout") or "")[:400],
        "s_n": s_n,
    }
    with BUILT_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    return {
        "ok": ok,
        "module": module,
        "stdout": (rn.get("stdout") or "")[:400],
        "error": None if ok else (rn.get("reason") or rn.get("stderr") or "run_fail"),
        "run": rn,
    }


def write_manifest(*, module: str, path: str, why: str, run_stdout: str, s_n: float) -> dict[str, Any]:
    ensure_build_home()
    line = (
        f"- [{_utc()}] **{module}** — {why}\n"
        f"  - generation_or_receipt: `{path}`\n"
        f"  - run: `{(run_stdout or '').strip()[:200]}`\n"
        f"  - s_n={s_n:.4f}\n"
    )
    gate = str(MANIFEST).replace("\\", "/")
    existing = MANIFEST.read_text(encoding="utf-8") if MANIFEST.is_file() else "# AIOS Build Manifest\n\n"
    content = existing.rstrip() + "\n" + line + "\n"
    verdict = tool_gate("write_file", {"path": gate, "content": content}, s_n)
    if not verdict.get("allowed"):
        return {"ok": False, "error": str(verdict.get("reason", "denied"))}
    MANIFEST.write_text(content, encoding="utf-8")
    return {
        "ok": True,
        "stdout": f"manifest_updated {MANIFEST}",
        "path": str(MANIFEST).replace("\\", "/"),
    }


def verify_last_build() -> dict[str, Any]:
    ensure_build_home()
    if not BUILT_LOG.is_file():
        return {"ok": False, "error": "no_built_log"}
    rows = [json.loads(l) for l in BUILT_LOG.read_text(encoding="utf-8").splitlines() if l.strip()]
    invents = [r for r in rows if r.get("event") == "invent"]
    runs = [r for r in rows if r.get("event") == "run" and r.get("ok")]
    if not invents:
        return {"ok": False, "error": "no_invent_events"}
    last = invents[-1]
    if not MANIFEST.is_file():
        return {"ok": False, "error": "missing_manifest"}
    generation_id = str(last.get("generation_id") or "")
    status = _template_status()
    if generation_id and status.get("active_generation") == generation_id:
        return {
            "ok": True,
            "stdout": f"verified generation={generation_id} runs_ok={len(runs)} invents={len(invents)}",
            "module": last.get("module"),
            "generation_id": generation_id,
            "template_status": status,
        }
    return {
        "ok": False,
        "error": "last_generation_not_active_or_missing",
        "module": last.get("module"),
        "generation_id": generation_id,
        "template_status": status,
    }
