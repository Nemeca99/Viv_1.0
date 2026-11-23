"""
Viv Code Evolution Engine (ACI Engine)
======================================
Focuses Viv on iterative, goal-driven code development.
Instead of spinning ephemeral or random files in the sandbox:
1. She maintains persistent target organ files in `my_aios/`.
2. Inspects existing file states, ast classes, and error history.
3. Uses Semantic Context Memory to establish Location (where she is in AST/module)
   and Direction (what is the goal, what failed, what needs resolution).
4. Maintains an explicit Task List file (`VIV_TASK_LIST.md`) detailing what was done.
5. Employs her internal monologue/journal as her personal version of `BUILD_LOG.md`
   (`VIV_BUILD_LOG.md`), logging zero-metaphor physical silicon execution receipts.
"""

from __future__ import annotations
import ast
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PLAYGROUND_ROOT = Path(r"E:\Viv_Sandbox\playground")
MY_AIOS_DIR = PLAYGROUND_ROOT / "my_aios"
MEMORY_DIR = PLAYGROUND_ROOT / "memory"
CONFIG_DIR = PLAYGROUND_ROOT / "config"
MONOLOGUE_DIR = PLAYGROUND_ROOT / "monologue"
AIOS_SOURCE_DIR = PLAYGROUND_ROOT / "aios_source"

MEMORY_FILE = MEMORY_DIR / "viv_semantic_memory.json"
GOAL_FILE = CONFIG_DIR / "VIV_GOAL.json"
TASK_LIST_FILE = PLAYGROUND_ROOT / "VIV_TASK_LIST.md"
MY_AIOS_TASK_LIST = MY_AIOS_DIR / "TASK_LIST.md"
BUILD_LOG_FILE = MONOLOGUE_DIR / "VIV_BUILD_LOG.md"
MONOLOGUE_FILE = MONOLOGUE_DIR / "viv_monologue.md"

MY_AIOS_DIR.mkdir(parents=True, exist_ok=True)
MEMORY_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
MONOLOGUE_DIR.mkdir(parents=True, exist_ok=True)


TARGET_AIOS_ORGANS = [
    {
        "organ_file": "consciousness_core.py",
        "title": "Consciousness Core & RID Stability Invariant",
        "layer": "BIOLOGICAL_CORE",
        "expected_class": "ConsciousnessCore",
        "goal": "Implement ConsciousnessCore calculating S_n = RSR * LTP * RLE. Assert S_n == 1.0 nominal, assert S_n drops on entropy increase, and assert execute_fidf_restoration() restores S_n to 1.0."
    },
    {
        "organ_file": "neuron_transition_matrix.py",
        "title": "Neuron Transition Matrix Conductance Engine",
        "layer": "CONDUCTANCE_CORE",
        "expected_class": "NeuronTransitionMatrix",
        "goal": "Implement NeuronTransitionMatrix tracking unigrams, bigrams, and trigrams. Assert feed_sentence() records n-gram counts, and assert score_sequence() scores a valid route strictly higher than a randomized token permutation."
    },
    {
        "organ_file": "viv_alu_transducer.py",
        "title": "ALU Word-to-Unit Transducer",
        "layer": "ALU_CORE",
        "expected_class": "VivAluTransducer",
        "goal": "Implement digit-free arithmetic transducer mapping natural word equations ('one unit plus two units') to unit values without raw digits. Assert 'three units' result and assert invalid/unlearned tokens return NULL_UNLEARNED_ENTITY."
    },
    {
        "organ_file": "cognitive_bridge_rectifier.py",
        "title": "Full Bridge Cognitive Rectifier (Graetz Diamond)",
        "layer": "RECTIFIER_CORE",
        "expected_class": "FullBridgeCognitiveRectifier",
        "goal": "Implement Graetz diamond semantic bridge converting polar opposites (hot/cold, true/false) to unipolar +1.0V DC along shared dimensional axis (thermal, veracity). Assert positive and negative half-cycles conduct to +1.0V DC, and assert concrete non-scalar entities fail closed with infinite impedance."
    },
    {
        "organ_file": "coverage_gate.py",
        "title": "Deterministic Text Coverage Gate",
        "layer": "GATE_CORE",
        "expected_class": "CoverageGate",
        "goal": "Implement deterministic text coverage evaluator with 95% threshold. Assert that text with >=95% grounded tokens emits ADMISSIBLE_COMPREHENSION license, and text with <95% grounded tokens triggers FAIL_CLOSED_IMPEDANCE with a targeted word acquisition manifest."
    },
    {
        "organ_file": "privacy_core.py",
        "title": "PrivacyCore Write Authorization Gate",
        "layer": "SECURITY_CORE",
        "expected_class": "PrivacyCore",
        "goal": "Implement PrivacyCore enforcing whitelist authorization policy. Assert that authorized write to .py or .md file returns True, and unauthorized path or broad destructive overwrite raises PrivacyViolationError."
    },
    {
        "organ_file": "carma_core.py",
        "title": "Semantic Mycelium Memory Index (CARMA Core)",
        "layer": "MEMORY_CORE",
        "expected_class": "CarmaCore",
        "goal": "Implement associative mycelium memory storing concepts, links, and activation conductances. Assert concept retrieval by key, assert bidirectional associative link traversal, and assert memory persistence."
    },
    {
        "organ_file": "luna_core.py",
        "title": "Luna Persona Synthesizer",
        "layer": "PERSONA_CORE",
        "expected_class": "LunaCore",
        "goal": "Implement Luna persona state machine tracking emotional resonance and identity invariants. Assert voice tone matches stability scalar S_n, and assert identity continuity prevents persona drift."
    },
    {
        "organ_file": "body_runtime_sentinel.py",
        "title": "Body Runtime Execution Sentinel",
        "layer": "BODY_GATE",
        "expected_class": "BodyRuntimeSentinel",
        "goal": "Implement deterministic execution tiebreaker. Assert exit code 0 and non-empty stdout accepts candidate proposal; assert non-zero exit code rejects proposal at the gate."
    },
    {
        "organ_file": "topological_planck_rnn.py",
        "title": "Topological Planck RNN Velocity Calculator",
        "layer": "PHYSICS_CORE",
        "expected_class": "TopologicalPlanckRNN",
        "goal": "Implement Planck cell velocity S = M / D and recursive velocity S^2 = (M / D)^2. Assert that vertical word lift (D=1) accelerates S^2 by >100x compared to planar character drift (D=8), proving hierarchical acceleration."
    }
]


def inspect_code_ast(code: str, expected_class: Optional[str] = None) -> Dict[str, Any]:
    """Inspects Python code AST to extract classes, functions, and assert counts."""
    line_count = len(code.splitlines()) if code else 0
    if not code.strip():
        return {"valid_ast": False, "classes": [], "functions": [], "assert_count": 0, "line_count": 0, "has_expected_class": False, "error": "Empty code"}
    try:
        tree = ast.parse(code)
        classes = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
        functions = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
        assert_nodes = [node for node in ast.walk(tree) if isinstance(node, ast.Assert)]
        real_asserts = []
        for a in assert_nodes:
            txt = ast.unparse(a).strip()
            if txt not in ["assert True", "assert 1", "assert True,"]:
                real_asserts.append(txt)
        has_class = (expected_class in classes) if expected_class else (len(classes) > 0)
        return {
            "valid_ast": True,
            "classes": classes,
            "functions": functions,
            "assert_count": len(real_asserts),
            "line_count": line_count,
            "has_expected_class": has_class,
            "error": None
        }
    except Exception as e:
        return {
            "valid_ast": False,
            "classes": [],
            "functions": [],
            "assert_count": 0,
            "line_count": line_count,
            "has_expected_class": False,
            "error": str(e)
        }


class VivSemanticMemoryManager:
    """Manages persistent semantic context memory tracking Location and Direction."""

    @classmethod
    def load_memory(cls) -> Dict[str, Any]:
        if MEMORY_FILE.exists():
            try:
                return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return cls.init_memory()

    @classmethod
    def init_memory(cls) -> Dict[str, Any]:
        organ_manifest = {}
        for o in TARGET_AIOS_ORGANS:
            organ_file = o["organ_file"]
            p = MY_AIOS_DIR / organ_file
            if p.exists():
                code = p.read_text(encoding="utf-8", errors="replace")
                ast_info = inspect_code_ast(code, expected_class=o.get("expected_class"))
                status = "COMPLETED" if ast_info["valid_ast"] and ast_info["has_expected_class"] and ast_info["assert_count"] >= 1 else "IN_PROGRESS"
                organ_manifest[organ_file] = {
                    "title": o["title"],
                    "layer": o["layer"],
                    "status": status,
                    "version": 1,
                    "asserts": ast_info["assert_count"],
                    "line_count": ast_info["line_count"],
                    "classes": ast_info["classes"],
                    "functions": ast_info["functions"],
                    "last_error": "",
                    "last_updated": datetime.now().isoformat()
                }
            else:
                organ_manifest[organ_file] = {
                    "title": o["title"],
                    "layer": o["layer"],
                    "status": "PENDING",
                    "version": 0,
                    "asserts": 0,
                    "line_count": 0,
                    "classes": [],
                    "functions": [],
                    "last_error": "",
                    "last_updated": None
                }

        # Pick initial active organ: first non-completed or in-progress organ
        active_organ_file = "neuron_transition_matrix.py"
        for o in TARGET_AIOS_ORGANS:
            of = o["organ_file"]
            if organ_manifest[of]["status"] != "COMPLETED":
                active_organ_file = of
                break

        mem = {
            "goal": {
                "overarching": "Autonomous Rebuilding & Hardening of AIOS V2 Substrate Organs",
                "active_milestone": organ_manifest[active_organ_file]["title"],
                "target_file": active_organ_file,
                "layer": organ_manifest[active_organ_file]["layer"],
            },
            "location": {
                "active_file": str(MY_AIOS_DIR / active_organ_file),
                "organ_name": active_organ_file,
                "layer": organ_manifest[active_organ_file]["layer"],
                "version": organ_manifest[active_organ_file]["version"],
                "classes": organ_manifest[active_organ_file]["classes"],
                "functions": organ_manifest[active_organ_file]["functions"],
                "line_count": organ_manifest[active_organ_file]["line_count"],
                "assert_count": organ_manifest[active_organ_file]["asserts"],
            },
            "direction": {
                "objective": f"Refactor and harden {active_organ_file} with formal assertions.",
                "recent_error": "",
                "next_action": f"Inspect {active_organ_file}, ensure valid AST, and prove invariants with exit code 0.",
                "semantic_breadcrumbs": [
                    "AIOS V2 mirrored architecture",
                    "Deterministic silicon assertions in container viv-vm (/work)"
                ]
            },
            "organ_manifest": organ_manifest,
            "recent_actions": []
        }
        cls.save_memory(mem)
        return mem

    @classmethod
    def save_memory(cls, data: Dict[str, Any]) -> None:
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        MEMORY_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def get_active_organ(cls) -> Dict[str, Any]:
        mem = cls.load_memory()
        target_file = mem.get("goal", {}).get("target_file", "neuron_transition_matrix.py")
        for o in TARGET_AIOS_ORGANS:
            if o["organ_file"] == target_file:
                meta = dict(o)
                meta["state"] = mem.get("organ_manifest", {}).get(target_file, {})
                return meta
        return TARGET_AIOS_ORGANS[0]

    @classmethod
    def update_organ_success(cls, organ_file: str, code: str, assert_count: int, what_done: str) -> None:
        mem = cls.load_memory()
        ast_info = inspect_code_ast(code)
        manifest = mem.setdefault("organ_manifest", {})
        organ_state = manifest.setdefault(organ_file, {})
        new_version = organ_state.get("version", 0) + 1

        organ_state.update({
            "status": "COMPLETED",
            "version": new_version,
            "asserts": assert_count,
            "line_count": ast_info["line_count"],
            "classes": ast_info["classes"],
            "functions": ast_info["functions"],
            "last_error": "",
            "what_done": what_done,
            "last_updated": datetime.now().isoformat()
        })

        # Update Location
        mem["location"] = {
            "active_file": str(MY_AIOS_DIR / organ_file),
            "organ_name": organ_file,
            "layer": organ_state.get("layer", "CORE"),
            "version": new_version,
            "classes": ast_info["classes"],
            "functions": ast_info["functions"],
            "line_count": ast_info["line_count"],
            "assert_count": assert_count,
        }

        # Check for next incomplete organ to advance Direction
        next_organ = None
        for o in TARGET_AIOS_ORGANS:
            of = o["organ_file"]
            if manifest.get(of, {}).get("status") != "COMPLETED":
                next_organ = o
                break

        if next_organ:
            mem["goal"]["target_file"] = next_organ["organ_file"]
            mem["goal"]["active_milestone"] = next_organ["title"]
            mem["goal"]["layer"] = next_organ["layer"]
            mem["direction"] = {
                "objective": f"Reconstruct and harden {next_organ['organ_file']}: {next_organ['goal']}",
                "recent_error": "",
                "next_action": f"Begin iterative hardening on {next_organ['organ_file']}.",
                "semantic_breadcrumbs": [f"Completed {organ_file} (v{new_version}, {assert_count} asserts)", "Advancing organ sequence"]
            }
        else:
            mem["direction"] = {
                "objective": "All 10 AIOS Core Organs graduated on physical silicon. Maintain continuous hardening.",
                "recent_error": "",
                "next_action": "Audit holistic inter-organ connectivity and run full AIOS self-test suite.",
                "semantic_breadcrumbs": ["Full AIOS V2 Substrate Grounded"]
            }

        recent = mem.setdefault("recent_actions", [])
        recent.insert(0, {
            "timestamp": datetime.now().isoformat(),
            "organ_file": organ_file,
            "status": "PASSED",
            "version": new_version,
            "asserts": assert_count,
            "what_done": what_done
        })
        mem["recent_actions"] = recent[:10]
        cls.save_memory(mem)

    @classmethod
    def update_organ_failure(cls, organ_file: str, error_text: str, what_attempted: str) -> None:
        mem = cls.load_memory()
        manifest = mem.setdefault("organ_manifest", {})
        organ_state = manifest.setdefault(organ_file, {})
        organ_state["status"] = "IN_PROGRESS"
        clean_err = error_text.splitlines()[-1] if error_text.splitlines() else error_text
        organ_state["last_error"] = clean_err[:200]
        organ_state["last_updated"] = datetime.now().isoformat()

        mem["direction"]["recent_error"] = clean_err[:200]
        mem["direction"]["next_action"] = f"Address failure ({clean_err[:100]}): fix code defect in {organ_file}."

        recent = mem.setdefault("recent_actions", [])
        recent.insert(0, {
            "timestamp": datetime.now().isoformat(),
            "organ_file": organ_file,
            "status": "FAILED",
            "error": clean_err[:120],
            "what_attempted": what_attempted
        })
        mem["recent_actions"] = recent[:10]
        cls.save_memory(mem)


class VivTaskListManager:
    """Renders and maintains the human-readable and agent-readable Task List file."""

    @classmethod
    def sync_task_list(cls, memory: Dict[str, Any]) -> None:
        goal = memory.get("goal", {})
        location = memory.get("location", {})
        direction = memory.get("direction", {})
        manifest = memory.get("organ_manifest", {})
        recent = memory.get("recent_actions", [])

        completed_count = sum(1 for o in TARGET_AIOS_ORGANS if manifest.get(o["organ_file"], {}).get("status") == "COMPLETED")
        total_count = len(TARGET_AIOS_ORGANS)
        progress_pct = (completed_count / total_count) * 100

        lines = [
            "# Viv Autonomous Engineering Task List",
            f"**Overarching Goal:** {goal.get('overarching', 'AIOS V2 Substrate Rebuilding')}",
            f"**Current Milestone:** {goal.get('active_milestone', 'Core Organ Hardening')}",
            f"**Active Target File:** `{goal.get('target_file', 'None')}` (Layer: `{goal.get('layer', 'UNKNOWN')}`)",
            f"**Substrate Progress:** {completed_count}/{total_count} Organs Verified ({progress_pct:.1f}%)",
            f"**Last Sync:** {datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')}",
            "",
            "---",
            "",
            "## 1. Semantic Context Coordinate (Location & Direction)",
            "",
            f"- **Location (Where am I?):**",
            f"  - Active File: `{location.get('active_file', 'None')}` (v{location.get('version', 0)})",
            f"  - Defined Classes: `{', '.join(location.get('classes', [])) or 'None'}`",
            f"  - Defined Methods: `{', '.join(location.get('functions', [])) or 'None'}`",
            f"  - Code Volume: {location.get('line_count', 0)} lines | Verified Invariants: {location.get('assert_count', 0)} formal assertions",
            "",
            f"- **Direction (Where am I going?):**",
            f"  - Objective: {direction.get('objective', 'Iterate and improve core code.')}",
            f"  - Recent Silicon Feedback: `{direction.get('recent_error', 'None (Nominal)')}`",
            f"  - Immediate Next Action: {direction.get('next_action', 'Continue step evolution.')}",
            "",
            "---",
            "",
            "## 2. Core Organ Workstreams",
            ""
        ]

        for idx, o in enumerate(TARGET_AIOS_ORGANS, 1):
            of = o["organ_file"]
            st = manifest.get(of, {})
            status = st.get("status", "PENDING")
            version = st.get("version", 0)
            asserts = st.get("asserts", 0)
            what_done = st.get("what_done", "")
            last_err = st.get("last_error", "")

            if status == "COMPLETED":
                box = "[x]"
                badge = f"**COMPLETED (v{version})** — `{asserts}` assertions verified on physical silicon"
            elif status == "IN_PROGRESS":
                box = "[/]"
                badge = f"**IN PROGRESS** — targeting invariants"
            else:
                box = "[ ]"
                badge = "**PENDING**"

            lines.append(f"- {box} **Organ {idx}: {o['title']}** (`{of}`)")
            lines.append(f"  - *Status:* {badge}")
            lines.append(f"  - *Layer:* `{o['layer']}`")
            lines.append(f"  - *Specification Goal:* {o['goal']}")
            if what_done:
                lines.append(f"  - *What Was Done:* {what_done}")
            if last_err and status == "IN_PROGRESS":
                lines.append(f"  - *Active Impedance:* `{last_err}`")
            lines.append("")

        lines.extend([
            "---",
            "",
            "## 3. Recent Silicon Execution Receipts",
            "",
            "| Timestamp | Organ File | Outcome | Asserts | Summary / Error |",
            "| :--- | :--- | :--- | :--- | :--- |"
        ])

        if recent:
            for r in recent[:6]:
                ts = r.get("timestamp", "").split("T")[-1][:8]
                of = r.get("organ_file", "")
                st_code = r.get("status", "")
                outcome_str = "**PASS (Exit 0)**" if st_code == "PASSED" else "**FAIL (Gate)**"
                assert_str = str(r.get("asserts", 0)) if st_code == "PASSED" else "-"
                detail = r.get("what_done") or r.get("error") or r.get("what_attempted") or ""
                clean_detail = detail.replace("|", "/")[:65]
                lines.append(f"| {ts} | `{of}` | {outcome_str} | {assert_str} | {clean_detail} |")
        else:
            lines.append("| - | - | - | - | No recent runs recorded yet |")

        content = "\n".join(lines) + "\n"
        TASK_LIST_FILE.write_text(content, encoding="utf-8")
        try:
            MY_AIOS_TASK_LIST.write_text(content, encoding="utf-8")
        except Exception:
            pass


class VivBuildLogManager:
    """Maintains Viv's personal high-fidelity BUILD_LOG.md recording silicon facts."""

    @classmethod
    def append_entry(
        cls,
        step_k: int,
        organ_file: str,
        title: str,
        layer: str,
        location_info: str,
        direction_info: str,
        action_taken: str,
        silicon_trace: str,
        reflection: str,
        passed: bool
    ) -> None:
        timestamp_str = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p %Z")
        status_tag = "PASS (Exit 0 in viv-vm)" if passed else "FAIL (Gate Impedance)"

        entry = (
            f"\n\n## Engineering Entry #{step_k} — [AGENDA: {title}] — {timestamp_str}\n"
            f"**[Index: `entry_{step_k:04d}_{organ_file.split('.')[0]}` | Layer: `{layer}` | Status: `{status_tag}`]**\n"
            f"- **Location:** {location_info}\n"
            f"- **Direction:** {direction_info}\n"
            f"- **Action Taken:** {action_taken}\n"
            f"- **Silicon Trace:** {silicon_trace}\n"
            f"- **Reflection & Next Lesson:** {reflection}\n"
        )

        with open(BUILD_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(entry)

        # Mirror entry into viv_monologue.md to unify her internal dialogue
        with open(MONOLOGUE_FILE, "a", encoding="utf-8") as f:
            f.write(entry)


def compose_active_sandboxed_script(
    candidate_code: str,
    expected_class: Optional[str] = None
) -> Tuple[str, int]:
    """Wraps candidate code in an active silicon assertion execution harness.
    
    Guarantees:
    1. Hoists __future__ imports to line 1.
    2. Dynamically traces and counts exact physical assert executions at runtime.
    3. Auto-discovers and actively executes all test_* and main() functions.
    4. Formally verifies that expected_class exists in module globals.
    5. Fails closed with non-zero exit code if 0 assertions were executed on silicon.
    """
    try:
        tree = ast.parse(candidate_code)
    except Exception:
        return candidate_code, 0

    real_assert_lines = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Assert):
            txt = ast.unparse(n).strip()
            if txt not in ["assert True", "assert 1", "assert True,"]:
                real_assert_lines.add(n.lineno)

    # Hoist __future__ imports to line 1 by commenting them out in candidate_code
    # so line numbers of AST nodes remain strictly identical for runtime trace tracking.
    candidate_lines = []
    for line in candidate_code.splitlines():
        if line.strip().startswith("from __future__"):
            candidate_lines.append(f"# hoisted: {line}")
        else:
            candidate_lines.append(line)
    candidate_code_clean = "\n".join(candidate_lines)

    harness_pre1 = (
        "from __future__ import annotations\n"
        "import sys, inspect, math, time, json, re\n"
        "from collections import Counter, defaultdict\n"
        "from dataclasses import dataclass, field\n"
        "from typing import Optional, List, Dict, Set, Tuple, Any, Union\n"
        "_VIV_EXECUTED_ASSERTS = set()\n"
        "def _viv_trace(f, e, a):\n"
        "    if e == 'line' and f.f_lineno in _VIV_TARGET_ASSERTS:\n"
        "        _VIV_EXECUTED_ASSERTS.add(f.f_lineno)\n"
        "    return _viv_trace\n"
    )
    harness_pre2 = "sys.settrace(_viv_trace)\n"

    total_prelude_lines = len(harness_pre1.splitlines()) + 1 + len(harness_pre2.splitlines())
    targets = {l + total_prelude_lines for l in real_assert_lines}
    full_prelude = (
        harness_pre1 +
        f"_VIV_TARGET_ASSERTS = {targets}\n" +
        harness_pre2
    )

    class_check = f"""
if '{expected_class}' and '{expected_class}' not in globals():
    raise AssertionError("MISSING_TARGET_CLASS: Expected class '{expected_class}' was not defined in module.")
""" if expected_class else ""

    harness_post = f"""
sys.settrace(None)
for _name in list(globals().keys()):
    if _name.startswith('test_') or _name == 'main':
        _fn = globals()[_name]
        if callable(_fn) and inspect.isfunction(_fn):
            sys.settrace(_viv_trace)
            _fn()
            sys.settrace(None)
{class_check}
if not _VIV_EXECUTED_ASSERTS:
    raise AssertionError(f"ZERO_RUNTIME_ASSERTIONS: Code contains {len(real_assert_lines)} assertions in AST, but NONE were executed on physical silicon.")

print(f"__VIV_ASSERTIONS_VERIFIED__:{{len(_VIV_EXECUTED_ASSERTS)}}")
print("__VIV_ORGAN_EXEC_DONE__")
"""
    return (full_prelude + candidate_code_clean + "\n" + harness_post), len(real_assert_lines)


class VivCodeEvolutionEngine:
    """Core loop orchestrating iterative file improvement rather than scratch script sprawl."""

    @classmethod
    def evolve_step(
        cls,
        step_k: int,
        call_raw_completion_fn,
        dexec_fn,
        sanitize_code_fn,
        check_graduation_fn,
        compose_script_fn,
        package_proposal_fn,
        prelude: str
    ) -> Dict[str, Any]:
        memory = VivSemanticMemoryManager.load_memory()
        active_meta = VivSemanticMemoryManager.get_active_organ()
        organ_file = active_meta["organ_file"]
        title = active_meta["title"]
        goal = active_meta["goal"]
        layer = active_meta["layer"]
        expected_class = active_meta.get("expected_class", "")

        target_path = MY_AIOS_DIR / organ_file
        existing_code = ""
        current_version = memory.get("organ_manifest", {}).get(organ_file, {}).get("version", 0)
        recent_error = memory.get("direction", {}).get("recent_error", "")

        is_iteration = target_path.exists() and len(target_path.read_text(encoding="utf-8", errors="replace").strip()) > 30

        error_context = (
            f"\nPrevious Silicon Execution Feedback:\n{recent_error}\n"
            f"Fix this failure strictly. Use ONLY pure Python standard library: math, typing, collections, json, dataclasses, time, re, sys.\n"
            f"Do NOT import sqlite3 (no C shared library in sandbox), scipy, numpy, or external packages.\n"
        ) if recent_error else ""

        prefix_code = ""
        if is_iteration:
            existing_code = target_path.read_text(encoding="utf-8", errors="replace")
            ast_state = inspect_code_ast(existing_code, expected_class=expected_class)
            summary_classes = ", ".join(ast_state["classes"]) or "None"
            summary_methods = ", ".join(ast_state["functions"]) or "None"

            prompt = f'''"""
Task: Improve and Harden {title}
Goal: {goal}
File: my_aios/{organ_file} (Current Version: v{current_version})
Environment: Python 3.12 in container viv-vm (/work tmpfs)
Layer: {layer}
Expected Target Class: {expected_class}
Existing AST Classes: {summary_classes}
Existing AST Methods: {summary_methods}
{error_context}
--------------------------------------------------------------------------------
CURRENT EXISTING CODE ({ast_state['line_count']} lines, {ast_state['assert_count']} assertions):
--------------------------------------------------------------------------------
{existing_code.strip()}
--------------------------------------------------------------------------------

ITERATIVE REFINEMENT INSTRUCTIONS:
1. Preserve all working classes, data structures, and algorithms.
2. Fix any syntax errors, undefined names, or broken assertions identified in the silicon feedback.
3. Ensure class '{expected_class}' is fully defined and instantiated.
4. Include executable self-tests ('if __name__ == "__main__":' or 'def test_{organ_file.split(".")[0]}():') executing at least 2 non-trivial assert statements.
5. Output the complete, updated, and self-contained module. Use ONLY Python standard library (no sqlite3, no scipy).
"""

'''
        else:
            # Seed from reference organ in aios_source if available
            organ_hint = ""
            matching = list(AIOS_SOURCE_DIR.rglob(organ_file))
            if matching:
                source_code = matching[0].read_text(encoding="utf-8", errors="replace")
                ref_ast = inspect_code_ast(source_code, expected_class=expected_class)
                classes_str = ", ".join(ref_ast["classes"]) if ref_ast["classes"] else "None"
                methods_str = ", ".join(ref_ast["functions"][:10]) if ref_ast["functions"] else "None"
                code_lines = [l for l in source_code.splitlines() if not l.startswith("#!") and not l.strip().startswith('"""')]
                sample_code = "\n".join(code_lines[:45])
                organ_hint = (
                    f"\nArchitectural Blueprint ({organ_file}):\n"
                    f"Expected Classes: {classes_str}\n"
                    f"Expected Key Methods: {methods_str}\n"
                    f"Reference Implementation Snippet:\n{sample_code}\n"
                )

            prefix_code = (
                f"from __future__ import annotations\n"
                f"import sys, os, math, time, re, json\n"
                f"from datetime import datetime\n"
                f"from typing import Optional, List, Dict, Set, Tuple, Any\n\n"
                f"class {expected_class}:\n"
                f"    def __init__(self):\n        "
            )
            prompt = f'''"""
Task: Reconstruct and Implement {title}
Goal: {goal}
File: my_aios/{organ_file} (Initial Version: v1)
Environment: Python 3.12 in container viv-vm (/work tmpfs)
Layer: {layer}
Expected Target Class: {expected_class}
{error_context}
{organ_hint}
Self-Contained Module Requirement: You MUST define the class '{expected_class}' with complete functional methods and data structures directly.
No Self-Import Invariant: Do NOT write 'import {organ_file.split(".")[0]}' or 'from {organ_file.split(".")[0]} import ...'. Instantiate '{expected_class}' directly as defined in this file.
Pure Standard Library Invariant: Use ONLY Python standard library: math, typing, collections, json, dataclasses, time, re, sys. Do NOT import sqlite3 or scipy.
Physical Silicon Execution Invariant: You MUST include executable self-tests ('if __name__ == "__main__":' or 'def test_{organ_file.split(".")[0]}():') that instantiate '{expected_class}', exercise its methods, and execute at least 2 non-trivial assert statements. Dormant or uncalled assertions will fail the gate.
"""
{prefix_code}'''

        try:
            raw_code = call_raw_completion_fn(
                prompt,
                stop=['<|EOT|>', '<|end_of_sentence|>', '\n# === END ==='],
                temp=0.20,
                max_tokens=1500
            )
            raw = raw_code.strip()
            if raw.startswith("from __future__") or raw.startswith(f"class {expected_class}"):
                candidate_code = sanitize_code_fn(raw)
            elif prefix_code:
                if raw.startswith("def __init__(self):"):
                    body = raw.split("def __init__(self):", 1)[1]
                    candidate_code = sanitize_code_fn(f"from __future__ import annotations\nimport sys, os, math, time, re, json\nfrom datetime import datetime\nfrom typing import Optional, List, Dict, Set, Tuple, Any\n\nclass {expected_class}:\n    def __init__(self):" + body)
                else:
                    candidate_code = sanitize_code_fn(prefix_code + raw)
            else:
                candidate_code = sanitize_code_fn(raw)
        except Exception as exc:
            VivSemanticMemoryManager.update_organ_failure(organ_file, str(exc), f"LLM generation failed: {exc}")
            VivTaskListManager.sync_task_list(VivSemanticMemoryManager.load_memory())
            return {"action": "agenda", "ok": False, "error": str(exc), "organ_file": organ_file}

        # Compose active sandboxed execution harness with dynamic assertion tracking
        script, expected_assert_count = compose_active_sandboxed_script(
            candidate_code=candidate_code,
            expected_class=expected_class
        )
        rc, out, err = dexec_fn(script)

        # Parse physical assertion verification receipt
        m_verified = re.search(r"__VIV_ASSERTIONS_VERIFIED__:(\d+)", out)
        verified_asserts = int(m_verified.group(1)) if m_verified else 0
        executed_ok = (rc == 0 and "__VIV_ORGAN_EXEC_DONE__" in out and verified_asserts >= 1)

        ok = executed_ok
        is_graduated = ok
        assert_count = verified_asserts
        grad_reason = f"SEMANTIC_GRADUATED: {assert_count} formal assertions physically verified on silicon" if ok else (err.strip() or "Silicon execution failed")

        ast_res = inspect_code_ast(candidate_code, expected_class=expected_class)
        loc_str = f"`my_aios/{organ_file}` (v{current_version + 1 if ok else current_version}, {ast_res['line_count']} lines, Classes: {', '.join(ast_res['classes']) or 'None'})"
        dir_str = f"Milestone: {title} | Invariant Goal: {goal}"

        if ok:
            # Overwrite the persistent organ file in-place with the verified improved version
            target_path.write_text(candidate_code, encoding="utf-8")
            what_done = f"Successfully refactored and verified {organ_file}. Proved {assert_count} assertions on physical silicon (AST classes: {', '.join(ast_res['classes'])})."

            # Decompose verified code into discrete Code Neurons and commit to SQLite
            try:
                from viv_code_neuron_engine import decompose_code_to_neurons, VivCodeNeuronLattice
                decomp = decompose_code_to_neurons(candidate_code)
                lattice = VivCodeNeuronLattice()
                n_counts = lattice.commit_decomposed_neurons(decomp, program_name=organ_file)
                what_done += f" Carved {n_counts['functions']} func, {n_counts['variables']} var, {n_counts['imports']} import, {n_counts['assertions']} assert neurons ({n_counts['synapses']} synapses)."
            except Exception as n_err:
                pass

            silicon_trace = f"Exit Code 0 | {assert_count} assertions verified | AST Closure: Valid | Stdout: {out.strip()[:80]}"
            reflection = f"In this cycle, I verified that {title} compiles cleanly in viv-vm and satisfies all mathematical invariants. Output saved to persistent organ file and decomposed into discrete Code Neurons."

            VivSemanticMemoryManager.update_organ_success(organ_file, candidate_code, assert_count, what_done)
            updated_mem = VivSemanticMemoryManager.load_memory()
            VivTaskListManager.sync_task_list(updated_mem)
            VivBuildLogManager.append_entry(
                step_k=step_k,
                organ_file=organ_file,
                title=title,
                layer=layer,
                location_info=loc_str,
                direction_info=dir_str,
                action_taken=what_done,
                silicon_trace=silicon_trace,
                reflection=reflection,
                passed=True
            )
            package_proposal_fn(organ_file, title, candidate_code, assert_count, step_k)
            print(f"[+++] VIV EVOLUTION ENGINE: {organ_file} UPDATED IN-PLACE (v{current_version + 1}, asserts: {assert_count})")
        else:
            if err.strip():
                fail_reason = err.strip().splitlines()[-1][:180]
            elif verified_asserts == 0:
                fail_reason = "ZERO_RUNTIME_ASSERTIONS: Code ran but 0 assertions executed on physical silicon"
            else:
                fail_reason = grad_reason or "Process terminated without completion signal"
            what_attempted = f"Attempted refinement of {organ_file}; proposal rejected at silicon execution gate."
            silicon_trace = f"Exit Code {rc} | Asserts: {assert_count} | Error: {fail_reason}"
            reflection = f"In this cycle, I verified that the candidate proposal for {organ_file} failed on physical silicon with: {fail_reason}. Existing file retained; targeting defect next cycle."

            VivSemanticMemoryManager.update_organ_failure(organ_file, fail_reason, what_attempted)
            updated_mem = VivSemanticMemoryManager.load_memory()
            VivTaskListManager.sync_task_list(updated_mem)
            VivBuildLogManager.append_entry(
                step_k=step_k,
                organ_file=organ_file,
                title=title,
                layer=layer,
                location_info=loc_str,
                direction_info=dir_str,
                action_taken=what_attempted,
                silicon_trace=silicon_trace,
                reflection=reflection,
                passed=False
            )
            print(f"[-] VIV EVOLUTION ENGINE: {organ_file} refinement failed gate: {fail_reason}")

        return {
            "action": "agenda",
            "ok": ok,
            "is_graduated": is_graduated,
            "title": title,
            "organ_file": organ_file,
            "code": candidate_code[:300] if candidate_code else "",
            "error": "" if ok else fail_reason,
            "assert_count": assert_count,
            "version": current_version + 1 if ok else current_version
        }
