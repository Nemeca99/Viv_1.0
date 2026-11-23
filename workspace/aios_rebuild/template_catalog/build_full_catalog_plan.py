"""Build a verified all-core candidate menu and obtain one Mind selection plan."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime import AiosTemplateCatalog

WORKSPACE = Path(__file__).resolve().parents[2]
MODEL = "qwen3:8b-local"
OLLAMA = "http://127.0.0.1:11434/api/chat"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def write_new(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()


def plan_schema(cards: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    core_names = list(cards)
    keys = sorted({row["candidate_key"] for rows in cards.values() for row in rows})
    return {
        "type": "object",
        "properties": {
            "intent": {"type": "string", "minLength": 40, "maxLength": 120},
            "selections": {
                "type": "array",
                "minItems": len(core_names),
                "maxItems": len(core_names),
                "items": {
                    "type": "object",
                    "properties": {
                        "core": {"type": "string", "enum": core_names},
                        "candidate_keys": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 1,
                            "items": {"type": "string", "enum": keys},
                        },
                        "reason": {"type": "string", "minLength": 12, "maxLength": 72},
                    },
                    "required": ["core", "candidate_keys", "reason"],
                    "additionalProperties": False,
                },
            },
            "approved_tools": {
                "type": "array",
                "minItems": 2,
                "maxItems": 2,
                "items": {
                    "type": "string",
                    "enum": ["stamp_catalog_templates", "verify_template_composition"],
                },
                "uniqueItems": True,
            },
        },
        "required": ["intent", "selections", "approved_tools"],
        "additionalProperties": False,
    }


def build(args: argparse.Namespace) -> tuple[Path, Path, Path]:
    catalog_dir = args.catalog_dir.resolve(strict=True)
    source_root = args.source_candidate.resolve(strict=True)
    out = args.run_dir.resolve(strict=False)
    if out.exists() or not out.is_relative_to(
        WORKSPACE / "aios_rebuild" / "rebuild_runs" / "full_catalog_rebuilds"
    ):
        raise ValueError("run directory must be a new child of full_catalog_rebuilds")
    out.mkdir(parents=True, exist_ok=False)

    runtime = AiosTemplateCatalog(catalog_dir, source_root)
    cards = runtime.candidate_cards(per_core=8)
    registry_hash = sha((catalog_dir / "registry.json").read_bytes())
    for core, rows in cards.items():
        rows.sort(
            key=lambda row: sha(
                f"{registry_hash}\0{core}\0{row['template_id']}\0mind-menu-order-v1".encode()
            )
        )
        for index, row in enumerate(rows, start=1):
            row["candidate_key"] = f"T{index}"
    menu = {
        "schema": "viv_full_aios_template_menu_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "catalog_registry_sha256": registry_hash,
        "selection_note": "Top-level source candidates are deterministically ranked by class status, source-path depth, direct-call count, and span size. This score is not a quality judgment.",
        "cards": cards,
    }
    menu_raw = (
        json.dumps(menu, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        + b"\n"
    )
    menu_path = out / "candidate_menu.json"
    write_new(menu_path, menu_raw)
    menu_hash = sha(menu_raw)

    sys.path.insert(0, str(WORKSPACE))
    from hive_foreman_memory import load_latest, routing_packet

    foreman = load_latest()
    if foreman.get("record_sha256") != args.foreman_snapshot_id:
        raise ValueError(
            "requested Foreman snapshot is not the current persisted snapshot"
        )
    packet = routing_packet(foreman)
    if packet["snapshot_id"] != args.foreman_snapshot_id:
        raise ValueError("Foreman routing packet ID mismatch")

    prompt_cards = {
        core: [
            {
                key: row[key]
                for key in (
                    "candidate_key",
                    "qualified_name",
                    "kind",
                    "source_path",
                    "parameters",
                    "direct_calls",
                    "docstring",
                    "source_lines",
                )
            }
            for row in rows
        ]
        for core, rows in cards.items()
    }
    system = (
        "You are Viv, the Mind coordinating a full AIOS rebuild candidate across all 19 cores. "
        "Study the user's goal, Foreman snapshot, and existing source catalog cards. For every core, "
        "choose exactly 1 existing top-level template from that core's listed options, comparing names "
        "and descriptions rather than selecting by menu position. Preserve broad "
        "system coverage. Return only the requested structured data. Do not write code, invent IDs, "
        "claim tests passed, or claim the selected snippets form a complete working replacement. "
        "The Swarm can only stamp the exact selected source spans; selection is your action here. "
        "Use only each core's short candidate keys, never print hash IDs. Keep one selection per core. "
        "For each reason, name the selected class or function and give a short phrase explaining its role; "
        "use at most 8 words and stay under 72 characters. The intent must be one sentence, under 120 "
        "characters, naming the full AIOS rebuild candidate composition. "
        "Approve only the two listed candidate-scoped tools."
    )
    user = {
        "user_goal": args.goal,
        "foreman_snapshot": packet,
        "verified_catalog": {
            "registry_sha256": menu["catalog_registry_sha256"],
            "menu_sha256": menu_hash,
            "cores_in_manifest_order": runtime.core_order,
            "eligible_template_cards_by_core": prompt_cards,
            "template_count": runtime.registry["template_count"],
            "source_file_count": runtime.registry["python_source_files_indexed"],
        },
        "execution_contract": {
            "mind_generations_for_this_plan": 1,
            "swarm_generation_per_task": 0,
            "required_cores": list(runtime.core_order),
            "approved_tools_exactly": [
                "stamp_catalog_templates",
                "verify_template_composition",
            ],
            "one_task_per_core": True,
            "candidate_only": True,
        },
    }
    request_body = {
        "model": args.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
        "stream": False,
        "think": False,
        "format": plan_schema(cards),
        "keep_alive": "10m",
        "options": {
            "temperature": 0,
            "seed": 42,
            "num_ctx": 16384,
            "num_predict": 1500,
        },
    }
    request_raw = json.dumps(request_body, ensure_ascii=False, sort_keys=True).encode(
        "utf-8"
    )
    request_path = out / "mind_request.json"
    write_new(request_path, request_raw)
    started = datetime.now(timezone.utc)
    request = urllib.request.Request(
        OLLAMA,
        data=request_raw,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        result = json.load(response)
    raw = result.get("message", {}).get("content", "")
    transcript = {
        "schema": "viv_full_aios_catalog_mind_transcript_v1",
        "status": "RAW_CAPTURED",
        "model": args.model,
        "request_sha256": sha(request_raw),
        "request_path": str(request_path),
        "foreman_snapshot_id": args.foreman_snapshot_id,
        "candidate_menu_sha256": menu_hash,
        "raw_output": raw,
        "model_metrics": {
            key: result.get(key)
            for key in (
                "total_duration",
                "load_duration",
                "prompt_eval_count",
                "prompt_eval_duration",
                "eval_count",
                "eval_duration",
                "done_reason",
            )
        },
        "started_utc": started.isoformat(),
        "finished_utc": datetime.now(timezone.utc).isoformat(),
    }
    transcript_path = out / "mind_transcript.json"
    write_new(
        transcript_path,
        json.dumps(transcript, ensure_ascii=False, indent=2).encode("utf-8") + b"\n",
    )
    try:
        model_plan = json.loads(raw)
    except json.JSONDecodeError as error:
        transcript["status"] = "HOLD_INVALID_MODEL_JSON"
        transcript["parse_error"] = str(error)
        transcript_path.write_text(
            json.dumps(transcript, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        raise ValueError(
            "Mind returned invalid JSON; raw transcript preserved"
        ) from error
    plan = {
        "schema": "viv_full_aios_catalog_plan_v1",
        "plan_origin": "viv_mind_model",
        "foreman_snapshot_id": args.foreman_snapshot_id,
        "catalog_registry_sha256": menu["catalog_registry_sha256"],
        "candidate_menu_sha256": menu_hash,
        **model_plan,
    }
    plan_path = out / "mind_plan.json"
    write_new(
        plan_path,
        json.dumps(plan, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        + b"\n",
    )
    transcript["status"] = "PLAN_CAPTURED_NOT_ADMITTED"
    transcript["mind_plan_sha256"] = sha(plan_path.read_bytes())
    transcript_path.write_text(
        json.dumps(transcript, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return menu_path, plan_path, transcript_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog-dir", type=Path, required=True)
    parser.add_argument("--source-candidate", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--foreman-snapshot-id", required=True)
    parser.add_argument("--goal", required=True)
    parser.add_argument("--model", default=MODEL)
    args = parser.parse_args()
    menu, plan, transcript = build(args)
    print(
        json.dumps(
            {
                "status": "PLAN_CAPTURED_NOT_ADMITTED",
                "menu": str(menu),
                "plan": str(plan),
                "transcript": str(transcript),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
