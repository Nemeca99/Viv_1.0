"""Refresh mutable implementation receipts without changing the design lock."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "HIVE_LOCK_MANIFEST.json"


def pin(relative: str) -> tuple[str, str]:
    path = (ROOT / relative).resolve(strict=True)
    path.relative_to(ROOT.resolve(strict=True))
    return relative.replace("\\", "/"), hashlib.sha256(
        path.read_bytes()
    ).hexdigest().upper()


def set_pair(target: dict[str, object], name: str, relative: str) -> None:
    target[name], target[f"{name}_sha256"] = pin(relative)


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    evidence = manifest["implementation_evidence"]
    set_pair(
        evidence,
        "run_manifest",
        "hive_numpy_bridge/artifacts/20260928T2342534081128Z/run_manifest.json",
    )
    evidence["bridge_receipt_sha256"] = pin(
        "hive_numpy_bridge/artifacts/20260928T2342534081128Z/bridge_receipt.json"
    )[1]
    rust = evidence["rust_control_proof"]
    for name, relative in {
        "live_receipt": "hive_control/runs/1790639617210539000/run_receipt.json",
        "artifact": "hive_control/runs/1790639617210539000/hello.py",
        "fault_receipt": "hive_control/runs/1790639639931716000/run_receipt.json",
        "rust_control": "hive_control/src/lib.rs",
        "rust_graph": "hive_control/src/graph.rs",
        "rust_runner": "hive_control/src/main.rs",
        "switchboard": "hive_control/switchboard.py",
        "cargo_lock": "hive_control/Cargo.lock",
        "runner_script": "hive_control/run_proof.ps1",
        "parallel_runner": "hive_control/src/bin/parallel_proof.rs",
        "parallel_receipt": "hive_control/runs/parallel-1790638721623858700/run_receipt.json",
        "parallel_artifact": "hive_control/runs/parallel-1790638721623858700/F.txt",
    }.items():
        set_pair(rust, name, relative)
    rebuild: dict[str, object] = {
        "scope": "isolated fixture.echo rebuild from a pinned legacy source; Mind plans and selects slots, deterministic workers stamp; not the full toolbox"
    }
    for name, relative in {
        "live_receipt": "template_rebuild/runs/1790639286606457600/receipt.json",
        "artifact": "template_rebuild/runs/1790639286606457600/fixture_echo.py",
        "registry": "template_rebuild/runs/1790639286606457600/registry.json",
        "fault_receipt": "template_rebuild/runs/1790639297250871900/receipt.json",
        "reference": "template_rebuild/reference/fixture_echo.py",
        "runner": "hive_control/src/bin/template_rebuild.rs",
        "runtime": "template_rebuild/runtime.py",
        "verifier": "template_rebuild/verify_run.py",
        "verifier_test": "template_rebuild/test_verify_run.py",
    }.items():
        set_pair(rebuild, name, relative)
    evidence["template_rebuild_proof"] = rebuild
    voice: dict[str, object] = {
        "scope": "Historical Qwen3 TTS auditions; selected voice runtime is recorded separately; no voice training"
    }
    for name, relative in {
        "preset_receipt": "hive_voice/samples/audition_receipt.json",
        "aiden_wav": "hive_voice/samples/archived_voices/viv_aiden_audition.wav",
        "ryan_wav": "hive_voice/samples/archived_voices/viv_ryan_audition.wav",
        "anchor_receipt": "hive_voice/samples/anchor_receipt.json",
        "anchor_wav": "hive_voice/samples/archived_voices/viv_anchor_design_v1.wav",
        "preset_script": "hive_voice/generate_sample.py",
        "anchor_script": "hive_voice/generate_anchor.py",
        "custom_voice_config": "hive_voice/models/Qwen3-TTS-12Hz-1.7B-CustomVoice/config.json",
        "voice_design_config": "hive_voice/models/Qwen3-TTS-12Hz-1.7B-VoiceDesign/config.json",
        "refinement_script": "hive_voice/refine_anchor.py",
        "finish_script": "hive_voice/finish_voice.py",
        "refinement_receipt": "hive_voice/samples/anchor_refinement_receipt.json",
        "finish_receipt": "hive_voice/samples/voice_finish_receipt.json",
        "slower_wav": "hive_voice/samples/archived_voices/viv_anchor_slower_v2.wav",
        "inflection_wav": "hive_voice/samples/archived_voices/viv_anchor_inflection_v2.wav",
        "refined_wav": "hive_voice/samples/archived_voices/viv_anchor_refined_v2.wav",
        "pondering_raw_wav": "hive_voice/samples/archived_voices/viv_pondering_raw_v1.wav",
        "pondering_wav": "hive_voice/samples/archived_voices/viv_pondering_v1.wav",
        "mature_script": "hive_voice/mature_refine.py",
        "mature_receipt": "hive_voice/samples/mature_refinement_receipt.json",
        "faster_base_wav": "hive_voice/samples/archived_voices/viv_base_10pct_faster_v3.wav",
        "soft_distant_base_wav": "hive_voice/samples/archived_voices/viv_base_soft_distant_v3.wav",
        "mature_design_wav": "hive_voice/samples/viv_mature_female_design_v3.wav",
        "mature_design_faster_wav": "hive_voice/samples/viv_mature_female_design_faster_v3.wav",
    }.items():
        set_pair(voice, name, relative)
    evidence["voice_audition"] = voice
    runtime: dict[str, object] = {
        "scope": "Observed OpenCode Companion and Build autoplay with separate selected voices, archived WAVs and full-text transcripts; no voice training"
    }
    for name, relative in {
        "proof": "hive_voice/autoplay_proof.json",
        "speaker": "hive_voice/speak.py",
        "selector": "hive_voice/voice_event.mjs",
        "selector_test": "hive_voice/test_voice_event.mjs",
        "plugin": ".opencode/plugins/voice.js",
        "base_model_config": "hive_voice/models/Qwen3-TTS-12Hz-1.7B-Base/config.json",
        "human_output_wav": "hive_voice/outputs/20260929T003509_1790642109142230800_msg_0ea95c45a001wM0xf0Seey1cKG_human.wav",
        "human_transcript": "hive_voice/outputs/20260929T003509_1790642109142230800_msg_0ea95c45a001wM0xf0Seey1cKG_human.txt",
        "logic_output_wav": "hive_voice/outputs/20260929T003836_1790642316915736400_msg_0ea985253001910IO1eYNJ0OCY_logic.wav",
        "logic_transcript": "hive_voice/outputs/20260929T003836_1790642316915736400_msg_0ea985253001910IO1eYNJ0OCY_logic.txt",
    }.items():
        set_pair(runtime, name, relative)
    evidence["voice_runtime"] = runtime
    quality: dict[str, object] = {
        "scope": "Staged single-file Python hygiene proof with source and prepared hashes, diff, zero-finding PASS, and unused-import HOLD; not yet bound to Rust dispatch"
    }
    for name, relative in {
        "pass_receipt": "hive_quality/runs/1790707823492840500_281f1ae9/receipt.json",
        "prepared_source": "hive_quality/runs/1790707823492840500_281f1ae9/fixture_echo.py",
        "preparation_diff": "hive_quality/runs/1790707823492840500_281f1ae9/preparation.diff",
        "source": "template_rebuild/reference/fixture_echo.py",
        "runner": "hive_quality/prepare.py",
        "runner_test": "hive_quality/test_prepare.py",
        "config": "pyproject.toml",
        "requirements": "requirements-quality.txt",
        "rust_manifest": "hive_control/Cargo.toml",
    }.items():
        set_pair(quality, name, relative)
    evidence["quality_preparation"] = quality
    placement: dict[str, object] = {
        "scope": "Rust-owned bounded NumPy CPU to CuPy GPU to NumPy CPU transfer; normal result PASS, changed returned cell HOLD; not live Mind inference or a speed benchmark"
    }
    for name, relative in {
        "pass_receipt": "hive_numpy_bridge/artifacts/gpu_placement_20260929_final1/pass_receipt.json",
        "fault_receipt": "hive_numpy_bridge/artifacts/gpu_placement_20260929_final1/fault_receipt.json",
        "rust_runner": "hive_control/src/bin/gpu_array_bridge.rs",
        "python_switchboard": "hive_numpy_bridge/gpu_switchboard.py",
        "numpy_cupy_backend": "hive_numpy_bridge/gpu_backend.py",
        "gpu_test": "hive_numpy_bridge/tests/test_gpu_backend.py",
        "gpu_requirements": "hive_numpy_bridge/requirements-gpu.txt",
    }.items():
        set_pair(placement, name, relative)
    evidence["cpu_gpu_placement"] = placement
    horizontal: dict[str, object] = {
        "scope": "Rust-only bottom Swarm layer: entropy-bound task snapshots, three parallel tasks then dependency-gated composition, and pre-dispatch parent drift HOLD"
    }
    for name, relative in {
        "pass_receipt": "hive_control/runs/swarm-horizontal-1790708860604898900/run_receipt.json",
        "pass_transcript": "hive_control/runs/swarm-horizontal-1790708860604898900/task_transcript.jsonl",
        "pass_artifact": "hive_control/runs/swarm-horizontal-1790708860604898900/F.txt",
        "fault_receipt": "hive_control/runs/swarm-horizontal-1790708863717382700/run_receipt.json",
        "fault_transcript": "hive_control/runs/swarm-horizontal-1790708863717382700/task_transcript.jsonl",
        "dev_failure_receipt": "hive_control/runs/swarm-horizontal-1790708473055441900/run_receipt.json",
        "rust_runner": "hive_control/src/bin/swarm_horizontal.rs",
    }.items():
        set_pair(horizontal, name, relative)
    evidence["horizontal_swarm"] = horizontal
    vague: dict[str, object] = {
        "scope": "Two live Qwen3 8B plans from the same vague goal; default and function-only capability profiles; Rust-stamped artifacts, task transcripts, and played voice outputs. This tests bounded replanning, not open-ended coding quality."
    }
    for name, relative in {
        "analysis_note": "hive_control/runs/VAGUE_GOAL_PROBE_20260929.md",
        "planner_bridge": "hive_control/mind_file_bridge.py",
        "rust_runner": "hive_control/src/bin/mind_planned_file.rs",
        "foreman_router": "hive_foreman_memory.py",
        "first_receipt": "hive_control/runs/mind-vague-1790709121822693800/run_receipt.json",
        "first_plan_transcript": "hive_control/runs/mind-vague-1790709121822693800/mind_plan_transcript.json",
        "first_swarm_transcript": "hive_control/runs/mind-vague-1790709121822693800/swarm_task_transcript.jsonl",
        "first_final_transcript": "hive_control/runs/mind-vague-1790709121822693800/mind_final_transcript.json",
        "first_artifact": "hive_control/runs/mind-vague-1790709121822693800/example.py",
        "first_voice_wav": "hive_voice/outputs/20260929T191252_1790709172910258300_mind-vague-1790709121822693800_logic.wav",
        "first_voice_transcript": "hive_voice/outputs/20260929T191252_1790709172910258300_mind-vague-1790709121822693800_logic.txt",
        "second_receipt": "hive_control/runs/mind-vague-1790709250463746800/run_receipt.json",
        "second_plan_transcript": "hive_control/runs/mind-vague-1790709250463746800/mind_plan_transcript.json",
        "second_swarm_transcript": "hive_control/runs/mind-vague-1790709250463746800/swarm_task_transcript.jsonl",
        "second_final_transcript": "hive_control/runs/mind-vague-1790709250463746800/mind_final_transcript.json",
        "second_artifact": "hive_control/runs/mind-vague-1790709250463746800/example.py",
        "second_voice_wav": "hive_voice/outputs/20260929T191458_1790709298048084800_mind-vague-1790709250463746800_logic.wav",
        "second_voice_transcript": "hive_voice/outputs/20260929T191458_1790709298048084800_mind-vague-1790709250463746800_logic.txt",
    }.items():
        set_pair(vague, name, relative)
    evidence["mind_vague_probe"] = vague
    adapters: dict[str, object] = {
        "scope": "Visible-development hierarchical QLoRA proof on Qwen3 1.7B; shared behavior improves schema adherence; Rust specialist passes 3/3 prepared executable fixtures; Python specialist remains unadmitted at 2/3"
    }
    for name, relative in {
        "report": "swarm_adapters/RUN_REPORT_20260929.md",
        "identity_design": "swarm_adapters/IDENTITY_AND_ADAPTER_STACK.md",
        "rsi_design": "swarm_adapters/RSI_BOOTSTRAP.md",
        "dataset_manifest": "swarm_adapters/data/manifest.json",
        "dataset_generator": "swarm_adapters/generate_datasets.py",
        "trainer": "swarm_adapters/train_adapter.py",
        "behavior_evaluator": "swarm_adapters/evaluate_behavior.py",
        "specialist_evaluator": "swarm_adapters/evaluate_specialist.py",
        "shared_receipt": "swarm_adapters/runs/viv-swarm-default-v2/training_receipt.json",
        "shared_weights": "swarm_adapters/runs/viv-swarm-default-v2/swarm-default/adapter_model.safetensors",
        "shared_eval": "swarm_adapters/runs/viv-swarm-default-v2/behavior_eval.json",
        "python_receipt": "swarm_adapters/runs/viv-python-specialist-v1/training_receipt.json",
        "python_weights": "swarm_adapters/runs/viv-python-specialist-v1/python-specialist/adapter_model.safetensors",
        "python_eval": "swarm_adapters/runs/viv-python-specialist-v1/behavior_eval_v3.json",
        "rust_receipt": "swarm_adapters/runs/viv-rust-specialist-v1/training_receipt.json",
        "rust_weights": "swarm_adapters/runs/viv-rust-specialist-v1/rust-specialist/adapter_model.safetensors",
        "rust_eval": "swarm_adapters/runs/viv-rust-specialist-v1/behavior_eval_v3.json",
        "voice_selector": "hive_voice/voice_event.mjs",
        "voice_selector_test": "hive_voice/test_voice_event.mjs",
    }.items():
        set_pair(adapters, name, relative)
    evidence["hierarchical_adapters"] = adapters
    MANIFEST.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print("implementation evidence refreshed; design lock unchanged")


if __name__ == "__main__":
    main()
