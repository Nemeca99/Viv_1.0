"""Viv self-life: understand -> build only if needed -> log -> talk only if novel.

Honest mode: idle + silence when nothing changed. No status-parrot LLM loop.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

from lib.aios_sandbox import JOURNAL, SANDBOX_ROOT, ensure_sandbox_home
from lib.cpu_execution_envelope import append_audit_receipt
from lib.deterministic_internal_boundary import write_projection
from lib.master_rid import load_master_rid
from lib.paths import AUTO_ARTIFACTS, FOUNDATION_ROOT

LIFE_LOG = AUTO_ARTIFACTS / "organism" / "life.jsonl"
LEGACY_LIFE_LOG = LIFE_LOG
LIFE_LOG = AUTO_ARTIFACTS / "organism" / "life_ledger.jsonl"
LIFE_STATE = AUTO_ARTIFACTS / "organism" / "self_state.json"
FLIGHT = JOURNAL / "flight_recorder.jsonl"
LEGACY_FLIGHT = FLIGHT
FLIGHT = JOURNAL / "flight_recorder_ledger.jsonl"
SELF_MD = JOURNAL / "SELF.md"
SELF_MAP = AUTO_ARTIFACTS / "organism" / "self_map.json"


def _utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _gated_write(path: Path, content: str, s_n: float) -> tuple[bool, str]:
    result = write_projection(path, content, master_s_n=s_n)
    return bool(result.get("ok")), str(result.get("reason") or "write_ok")


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    append_audit_receipt(
        path,
        {"event_schema": "viv_self_event_v1", **dict(row)},
        run_id_prefix="aios_self",
    )


def _count_txt(root: Path) -> tuple[int, int]:
    n, b = 0, 0
    if not root.is_dir():
        return 0, 0
    for f in root.rglob("*.txt"):
        n += 1
        try:
            b += f.stat().st_size
        except OSError:
            pass
    return n, b


def _load_life_state() -> dict[str, Any]:
    if not LIFE_STATE.is_file():
        return {}
    try:
        return json.loads(LIFE_STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def understand_self() -> dict[str, Any]:
    ensure_sandbox_home()
    out: dict[str, Any] = {"at": _utc(), "who": "Viv"}

    try:
        m = load_master_rid()
        out["plant"] = {
            "master_s_n": m.master_s_n,
            "status": m.status,
            "rsr": m.master_rsr,
            "ltp": m.master_ltp,
            "rle": m.master_rle,
        }
        sn = float(m.master_s_n)
    except Exception as exc:  # noqa: BLE001
        out["plant"] = {"error": str(exc)}
        sn = 0.5

    toolbox = _template_status()
    tools = sorted(
        str(row.get("template_id"))
        for row in toolbox.get("templates", [])
        if isinstance(row, dict) and row.get("template_id")
    )
    out["template_status"] = toolbox
    out["tools_authored"] = tools
    dream_n, dream_b = _count_txt(SANDBOX_ROOT / "dream")
    out["dream"] = {"files": dream_n, "bytes": dream_b}
    out["dream_files"] = dream_n

    try:
        from lib.security_membrane import membrane_status

        st = membrane_status()
        out["security"] = {"armed": st.get("armed"), "version": st.get("version")}
    except Exception as exc:  # noqa: BLE001
        out["security"] = {"error": str(exc)}

    try:
        from voice_core.speak import speak_status

        vs = speak_status()
        out["voice"] = {
            "backend": vs.get("backend"),
            "served_name": vs.get("served_name"),
            "reachable": vs.get("reachable"),
        }
    except Exception as exc:  # noqa: BLE001
        out["voice"] = {"error": str(exc)}

    gaps: list[str] = []
    if "self_map" not in tools:
        gaps.append("self_map")
    if "flight_digest" not in tools:
        gaps.append("flight_digest")
    if "capability_audit" not in tools:
        gaps.append("capability_audit")
    if dream_n == 0:
        gaps.append("needs_dream")
    out["gaps"] = gaps
    out["s_n"] = sn
    out["understanding"] = (
        f"Viv S_n={sn:.4f} {(out.get('plant') or {}).get('status')} "
        f"tools={len(tools)} dreams={dream_n} gaps={','.join(gaps) or 'none'}"
    )
    return out


def _deltas(understanding: dict[str, Any], prev: dict[str, Any]) -> list[str]:
    last = (prev.get("last") or {}) if prev else {}
    plant = understanding.get("plant") or {}
    old_plant = last.get("plant") or {}
    deltas: list[str] = []
    try:
        sn = float(plant.get("master_s_n") or 0)
        old_sn = float(old_plant.get("master_s_n") or sn)
        if abs(sn - old_sn) >= 0.05:
            deltas.append(f"S_n {old_sn:.3f}->{sn:.3f}")
    except (TypeError, ValueError):
        pass
    if str(plant.get("status")) != str(old_plant.get("status") or plant.get("status")):
        deltas.append(f"status {old_plant.get('status')}->{plant.get('status')}")
    old_tools = set(last.get("tools") or [])
    new_tools = set(understanding.get("tools_authored") or [])
    added = sorted(new_tools - old_tools)
    if added:
        deltas.append("new tools " + ",".join(added))
    dream_n = int(understanding.get("dream_files") or 0)
    old_dream = int(last.get("dream_files") or 0)
    if dream_n > old_dream:
        deltas.append(f"dreams {old_dream}->{dream_n}")
    if understanding.get("gaps"):
        deltas.append("gaps " + ",".join(understanding["gaps"]))
    return deltas


def _template_status() -> dict[str, Any]:
    """Read-only view of approved templates; never inspects or imports code."""
    try:
        repo_root = FOUNDATION_ROOT.parent
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))
        from build_tools.template_builder_v1 import toolbox_status

        return toolbox_status()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "state": "HOLD", "reason": f"template_status_unavailable:{exc}", "templates": []}


def _template_for_gap(gap: str) -> str:
    """Map a legacy gap to an explicit template ID, without carrying source."""
    return {
        "self_map": "self_map",
        "flight_digest": "flight_digest",
        "capability_audit": "capability_audit",
        "needs_dream": "capability_audit",
    }.get(gap, "capability_audit")


def build_self(understanding: dict[str, Any]) -> dict[str, Any]:
    from lib.aios_coder import run_sandbox_tool, write_sandbox_tool

    sn = float(understanding.get("s_n") or 0.5)
    gaps = list(understanding.get("gaps") or [])
    prev = _load_life_state()
    deltas = _deltas(understanding, prev)
    understanding["deltas"] = deltas

    if not gaps:
        plant_delta = any(d.startswith("S_n ") or d.startswith("status ") for d in deltas)
        available = {
            str(row.get("template_id"))
            for row in (understanding.get("template_status") or {}).get("templates", [])
            if isinstance(row, dict) and row.get("template_id")
        }
        if plant_delta:
            if (understanding.get("template_status") or {}).get("active_generation") and "plant_digest" in available:
                rn = run_sandbox_tool(tool="plant_digest", s_n=sn)
                return {
                    "ok": bool(rn.get("ok")),
                    "kind": "observe",
                    "gap": "plant_delta",
                    "tool": "plant_digest",
                    "stdout": (rn.get("stdout") or "")[:400],
                    "deltas": deltas,
                    "novel": True,
                    "s_n": sn,
                }
            return {
                "ok": False,
                "kind": "code_hold",
                "gap": "plant_delta",
                "template_id": "plant_digest",
                "reason": "template_authoring_required",
                "template_status": understanding.get("template_status") or {},
                "deltas": deltas,
                "novel": True,
                "s_n": sn,
            }
        return {
            "ok": True,
            "kind": "idle",
            "gap": None,
            "reason": "no_gaps_no_significant_delta",
            "deltas": deltas,
            "novel": False,
            "s_n": sn,
        }

    gap = gaps[0]
    if gap == "needs_dream":
        from lib.aios_dream import perform_dream_cycle

        dream = perform_dream_cycle(force=True)
        return {
            "ok": bool(dream.get("ok")),
            "kind": "dream",
            "gap": gap,
            "result": {"cycle": dream.get("cycle"), "path": dream.get("dream_path")},
            "deltas": deltas,
            "novel": True,
            "s_n": sn,
        }

    name = _template_for_gap(gap)
    template_status = understanding.get("template_status") or _template_status()
    available = {
        str(row.get("template_id"))
        for row in template_status.get("templates", [])
        if isinstance(row, dict) and row.get("template_id")
    }
    if name not in available:
        return {
            "ok": False,
            "kind": "code_hold",
            "gap": gap,
            "template_id": name,
            "reason": "template_authoring_required",
            "template_status": template_status,
            "deltas": deltas,
            "novel": True,
            "s_n": sn,
        }
    active_generation = template_status.get("active_generation")
    if active_generation and name in (understanding.get("tools_authored") or []):
        rn = run_sandbox_tool(tool=name, s_n=sn)
        return {
            "ok": bool(rn.get("ok")),
            "kind": "observe",
            "gap": gap,
            "tool": name,
            "stdout": (rn.get("stdout") or "")[:400],
            "deltas": deltas,
            "novel": True,
            "s_n": sn,
        }

    wr = write_sandbox_tool(tool=name, s_n=sn)
    if not wr.get("ok"):
        return {"ok": False, "kind": "code", "gap": gap, "write": wr, "deltas": deltas, "novel": True, "s_n": sn}
    rn = run_sandbox_tool(tool=name, s_n=sn)
    return {
        "ok": bool(rn.get("ok")),
        "kind": "code",
        "gap": gap,
        "tool": name,
        "generation_id": wr.get("generation_id"),
        "stdout": (rn.get("stdout") or "")[:400],
        "deltas": deltas,
        "novel": True,
        "s_n": sn,
    }


def log_self(
    understanding: dict[str, Any],
    build: dict[str, Any],
    *,
    spoken: str | None = None,
) -> dict[str, Any]:
    ensure_sandbox_home()
    sn = float(understanding.get("s_n") or 0.5)
    novel = bool(build.get("novel"))
    row = {
        "event": "self_life",
        "at": _utc(),
        "understanding": understanding.get("understanding"),
        "gaps": understanding.get("gaps"),
        "deltas": understanding.get("deltas") or build.get("deltas"),
        "plant": understanding.get("plant"),
        "tools": understanding.get("tools_authored"),
        "dream_files": understanding.get("dream_files"),
        "build": {
            "ok": build.get("ok"),
            "kind": build.get("kind"),
            "gap": build.get("gap"),
            "tool": build.get("tool"),
            "stdout": (build.get("stdout") or "")[:240],
            "result": build.get("result"),
            "novel": novel,
        },
        "spoken": (spoken or "")[:280],
        "s_n": sn,
    }
    _append_jsonl(LIFE_LOG, row)
    _append_jsonl(FLIGHT, row)

    map_body = {
        "updated_at": _utc(),
        "understanding": understanding.get("understanding"),
        "plant_s_n": (understanding.get("plant") or {}).get("master_s_n"),
        "plant_status": (understanding.get("plant") or {}).get("status"),
        "tools": understanding.get("tools_authored"),
        "gaps": understanding.get("gaps"),
        "deltas": row.get("deltas"),
        "last_kind": build.get("kind"),
    }
    ok_m, reason_m = _gated_write(SELF_MAP, json.dumps(map_body, indent=2), sn)
    md = "\n".join(
        [
            f"# Viv SELF — {_utc()}",
            f"**State:** {understanding.get('understanding')}",
            f"**Deltas:** {', '.join(row.get('deltas') or []) or '(none)'}",
            f"**Action:** {build.get('kind')} novel={novel}",
            f"**Out:** {(build.get('stdout') or build.get('reason') or build.get('result') or '')}",
            f"**Said:** {spoken or '(silent)'}",
            "",
        ]
    )
    ok_s, reason_s = _gated_write(SELF_MD, md, sn)

    remembered: dict[str, Any] = {"ok": False, "skipped": "not_novel"}
    if novel:
        try:
            from lib.carma_memory import remember

            remembered = remember(
                f"[self] deltas={row.get('deltas')} kind={build.get('kind')} "
                f"out={(build.get('stdout') or '')[:100]}",
                provenance="live",
                tags=["self", "delta"],
                s_n=sn,
            )
        except Exception as exc:  # noqa: BLE001
            remembered = {"ok": False, "error": str(exc)}

    state_result = write_projection(
        LIFE_STATE,
        json.dumps({"updated_at": _utc(), "last": row}, indent=2),
        master_s_n=sn,
    )
    if not state_result.get("ok"):
        return {
            "ok": False,
            "state": "HOLD_SECURITY",
            "reason": state_result.get("reason"),
            "flight": str(FLIGHT).replace("\\", "/"),
        }
    return {
        "ok": bool(ok_s),
        "flight": str(FLIGHT).replace("\\", "/"),
        "self_md": str(SELF_MD).replace("\\", "/"),
        "map_write": reason_m,
        "md_write": reason_s,
        "remembered": remembered,
    }


def talk_self(understanding: dict[str, Any], build: dict[str, Any]) -> dict[str, Any]:
    """Speak only on novelty. Personality-shaped CPU line — no LLM status parrot."""
    sn = float(understanding.get("s_n") or 0.0)
    if sn < 0.37:
        return {"ok": False, "skipped": "s_n_dormancy", "source": "silence", "text": ""}
    if build.get("kind") == "idle" or not build.get("novel"):
        return {"ok": True, "skipped": "nothing_new", "source": "silence", "text": ""}

    deltas = list(build.get("deltas") or understanding.get("deltas") or [])
    status = str((understanding.get("plant") or {}).get("status") or "?")
    out = (build.get("stdout") or "").strip()[:120]
    try:
        from lib.aios_personality import render_cpu_line

        line = render_cpu_line(deltas=deltas, stdout=out, status=status, s_n=sn)
    except Exception:
        line = f"Change: {'; '.join(deltas) if deltas else build.get('gap')}. "
        if out:
            line += f"{out} "
        line += f"Status {status}; Master S_n is {sn:.4f}."
    if not line.strip():
        return {"ok": True, "skipped": "nothing_new", "source": "silence", "text": ""}
    return {"ok": True, "source": "cpu_honest+dna", "text": line.strip()[:400]}


def self_life_cycle(*, speak: bool = True) -> dict[str, Any]:
    ensure_sandbox_home()
    understanding = understand_self()
    build = build_self(understanding)
    spoken_rep: dict[str, Any] = {"ok": False, "skipped": "speak_off", "text": ""}
    if speak:
        spoken_rep = talk_self(understanding, build)
    log = log_self(understanding, build, spoken=(spoken_rep.get("text") or None))
    return {
        "ok": bool(understanding.get("understanding")) and bool(build.get("ok")),
        "at": _utc(),
        "understand": understanding,
        "build": build,
        "log": log,
        "talk": spoken_rep,
        "sandbox": "L:/Continue/Viv/sandbox/",
    }
