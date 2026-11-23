"""
Autonomous DAG Orchestrator & Task Queue Engine (Pillar 1: Self-Directed Autonomous Loop).
Decomposes high-level architectural goals into ordered tasks (Analyze -> Test -> Author -> Heal -> Seal),
persists state across reboots, and drives autonomous execution through verification gates.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

AUTONOMY_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = AUTONOMY_DIR.parent
DB_PATH = AUTONOMY_DIR / "viv_code_topology.sqlite3"

try:
    from local_model_client import LocalModelClient, default_client
    from autonomous_repair_loop import AutonomousRepairLoop
    from snapshot_manager import SnapshotManager
    from topological_context_injector import TopologicalContextInjector
    from clawd_notifier import notify_clawd, ensure_clawd_running
except ImportError:
    from .local_model_client import LocalModelClient, default_client
    from .autonomous_repair_loop import AutonomousRepairLoop
    from .snapshot_manager import SnapshotManager
    from .topological_context_injector import TopologicalContextInjector
    try:
        from .clawd_notifier import notify_clawd, ensure_clawd_running
    except ImportError:
        def notify_clawd(*args, **kwargs): pass
        def ensure_clawd_running(): pass


class DAGOrchestrator:
    def __init__(
        self,
        db_path: Path = DB_PATH,
        client: Optional[LocalModelClient] = None,
        repair_loop: Optional[AutonomousRepairLoop] = None,
        snapshot_manager: Optional[SnapshotManager] = None,
        injector: Optional[TopologicalContextInjector] = None,
    ):
        self.db_path = db_path
        self.client = client or default_client
        self.snapshot_manager = snapshot_manager or SnapshotManager()
        self.repair_loop = repair_loop or AutonomousRepairLoop(client=self.client, snapshot_manager=self.snapshot_manager)
        self.injector = injector or TopologicalContextInjector(db_path=self.db_path, client=self.client)

        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        try:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS autonomous_dag_tasks (
                task_id TEXT PRIMARY KEY,
                goal_id TEXT NOT NULL,
                step_order INTEGER NOT NULL,
                step_type TEXT NOT NULL,
                target_file TEXT,
                objective TEXT NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER DEFAULT 0,
                result_receipt TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """)
            conn.commit()
        finally:
            conn.close()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def create_goal_dag(
        self,
        goal_id: str,
        core_name: str,
        core_description: str,
        target_dir: Path,
        language: str = "python",
    ) -> List[Dict[str, Any]]:
        """
        Decomposes an architectural module rebuild into a 3-stage DAG:
        1. AUTHOR_TESTS: Author unit tests enforcing core requirements.
        2. AUTHOR_CODE: Author modular implementation satisfying tests and topological contracts.
        3. VERIFY_AND_SEAL: Run closed-loop repair until Exit Code 0, seal receipt, and register primitives.
        """
        ext = ".rs" if language.lower() in ("rust", "rs") else ".py"
        test_ext = "_test.rs" if language.lower() in ("rust", "rs") else "_test.py"

        target_file = target_dir / f"{core_name}{ext}"
        test_file = target_dir / f"{core_name}{test_ext}"

        tasks = [
            {
                "task_id": f"{goal_id}_STEP_1_TESTS",
                "goal_id": goal_id,
                "step_order": 1,
                "step_type": "AUTHOR_TESTS",
                "target_file": str(test_file),
                "objective": f"Author comprehensive unit tests asserting: {core_description}. Import `{core_name}`.",
                "status": "PENDING",
            },
            {
                "task_id": f"{goal_id}_STEP_2_CODE",
                "goal_id": goal_id,
                "step_order": 2,
                "step_type": "AUTHOR_CODE",
                "target_file": str(target_file),
                "objective": f"Author clean, modular, zero-cloud implementation of `{core_name}` satisfying: {core_description}.",
                "status": "PENDING",
            },
            {
                "task_id": f"{goal_id}_STEP_3_VERIFY",
                "goal_id": goal_id,
                "step_order": 3,
                "step_type": "VERIFY_AND_SEAL",
                "target_file": str(target_file),
                "objective": f"Verify `{core_name}` satisfies: {core_description}. Pass all assertions in `{test_file.name}` on silicon.",
                "status": "PENDING",
            },
        ]

        conn = self._get_connection()
        try:
            now = datetime.now().isoformat()
            for t in tasks:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO autonomous_dag_tasks
                    (task_id, goal_id, step_order, step_type, target_file, objective, status, attempts, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                    """,
                    (t["task_id"], t["goal_id"], t["step_order"], t["step_type"], t["target_file"], t["objective"], t["status"], now, now),
                )
            conn.commit()
            print(f"[+] [DAGOrchestrator] Created {len(tasks)}-step DAG for Goal '{goal_id}' ({core_name}).")
            return tasks
        finally:
            conn.close()

    def get_next_pending_task(self, goal_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            row = conn.execute(
                """
                SELECT * FROM autonomous_dag_tasks
                WHERE goal_id = ? AND status = 'PENDING'
                ORDER BY step_order ASC LIMIT 1
                """,
                (goal_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def update_task_status(self, task_id: str, status: str, receipt: Optional[str] = None):
        conn = self._get_connection()
        try:
            now = datetime.now().isoformat()
            conn.execute(
                """
                UPDATE autonomous_dag_tasks
                SET status = ?, result_receipt = ?, updated_at = ?, attempts = attempts + 1
                WHERE task_id = ?
                """,
                (status, receipt, now, task_id),
            )
            conn.commit()
        finally:
            conn.close()

    def execute_task(self, task: Dict[str, Any], language: str = "python") -> bool:
        task_id = task["task_id"]
        step_type = task["step_type"]
        target_file = Path(task["target_file"])
        objective = task["objective"]

        print(f"\n==========================================================================")
        print(f"[*] [DAG Task: {task_id}] Step: {step_type}")
        print(f"[*] Objective: {objective}")
        print(f"==========================================================================")

        self.update_task_status(task_id, "IN_PROGRESS")
        ensure_clawd_running()
        notify_clawd("working", "PreToolUse", tool_name=step_type)

        target_file.parent.mkdir(parents=True, exist_ok=True)

        core_stem = target_file.stem.replace("_test", "")

        if step_type == "AUTHOR_TESTS":
            # 1. Author tests
            topological_context = self.injector.build_topological_context(objective, language=language)
            prompt = f"""You are Viv, sovereign AIOS engineer.
Task: Write clean, runnable unit tests for: {objective}.
{topological_context}

Requirements:
1. Write concise, executable test code under 120 lines using `unittest`.
2. IMPORTANT: Do NOT define the target class or functions inside this test file. Import them directly: `from {core_stem} import *` or specific classes.
3. ALWAYS place all required standard library imports (e.g. `import os`, `import shutil`, `import unittest`, `import tempfile`, `import sys`) at the VERY TOP of the file. Do NOT put imports inside individual test methods.
4. Use `tempfile.mkdtemp()` in setUp() for temporary directories instead of hardcoded '/tmp/' paths.
5. Ensure assertions test initialization, primary methods, edge cases, and error states.
6. Include `if __name__ == '__main__':\n    unittest.main()` runner so running `python {target_file.name}` directly executes all tests.
7. Output ONLY the raw Python test code without markdown wrappers, backticks, or conversational explanations.
"""
            print(f"[*] Generating unit test suite for {core_stem}...")
            code = self.client.generate_code(prompt)
            if len(code.strip()) < 50:
                print("[!] Generated test suite was too short. Retrying generation...")
                code = self.client.generate_code(prompt)
            target_file.write_text(code, encoding="utf-8")
            print(f"[+] Saved test suite to {target_file.name} ({len(code)} chars).")

            # Check test syntax and undefined names immediately on silicon
            ruff_exe = Path(sys.executable).parent / "ruff.exe"
            lint_cmd = [str(ruff_exe), "check", "--select", "F821", str(target_file)] if ruff_exe.exists() else [sys.executable, "-m", "py_compile", str(target_file)]
            compile_res = self.repair_loop.run_command(lint_cmd, cwd=target_file.parent)
            if compile_res["exit_code"] != 0:
                print("[-] Test file validation check failed. Initiating self-healing on test file...")
                repair_res = self.repair_loop.repair_and_verify(
                    file_path=target_file,
                    verify_cmd=lint_cmd,
                    task_objective=f"Fix syntax errors and undefined imports/variables in test suite: {objective}",
                    language=language,
                    cwd=target_file.parent,
                    task_id=f"{task_id}_SYNTAX_HEAL",
                )
                if not repair_res["success"]:
                    self.update_task_status(task_id, "FAILED", receipt="Test validation heal failed")
                    return False

            self.update_task_status(task_id, "VERIFIED")
            return True

        elif step_type == "AUTHOR_CODE":
            # 2. Author implementation
            topological_context = self.injector.build_topological_context(objective, language=language)
            prompt = f"""You are Viv, sovereign AIOS engineer.
Task: Write clean, complete implementation for: {objective}.
{topological_context}

Requirements:
1. Implement the requested classes and functions for `{target_file.name}`.
2. Define all required methods, constructors, and properties completely.
3. Keep the code concise, focused, and under 150 lines. Do not generate verbose boilerplates or long method comments.
4. ALWAYS place all required standard library imports (e.g. `import os`, `import shutil`, `import hashlib`, `import json`, `import time`) at the VERY TOP of the file. Do NOT use inline imports.
5. In constructors, always ensure directories (e.g. `self.snapshot_dir`) are created with `os.makedirs(self.snapshot_dir, exist_ok=True)`.
6. Zero external cloud dependencies.
7. Output ONLY the raw Python code without markdown wrappers, backticks, or conversational explanations.
"""
            print(f"[*] Generating core implementation code for {core_stem}...")
            code = self.client.generate_code(prompt)
            if len(code.strip()) < 50:
                print("[!] Generated code was too short. Retrying generation...")
                code = self.client.generate_code(prompt)
            target_file.write_text(code, encoding="utf-8")
            print(f"[+] Saved implementation code to {target_file.name} ({len(code)} chars).")

            # Check code syntax and undefined names immediately on silicon
            ruff_exe = Path(sys.executable).parent / "ruff.exe"
            lint_cmd = [str(ruff_exe), "check", "--select", "F821", str(target_file)] if ruff_exe.exists() else [sys.executable, "-m", "py_compile", str(target_file)]
            compile_res = self.repair_loop.run_command(lint_cmd, cwd=target_file.parent)
            if compile_res["exit_code"] != 0:
                print("[-] Code validation check failed. Initiating self-healing on code file...")
                repair_res = self.repair_loop.repair_and_verify(
                    file_path=target_file,
                    verify_cmd=lint_cmd,
                    task_objective=f"Fix syntax errors and undefined imports/variables in code: {objective}",
                    language=language,
                    cwd=target_file.parent,
                    task_id=f"{task_id}_SYNTAX_HEAL",
                )
                if not repair_res["success"]:
                    self.update_task_status(task_id, "FAILED", receipt="Code validation heal failed")
                    return False

            self.update_task_status(task_id, "VERIFIED")
            return True

        elif step_type == "VERIFY_AND_SEAL":
            # 3. Verify and self-heal
            test_file = target_file.parent / f"{target_file.stem}_test.py"
            if not test_file.exists():
                print(f"[!] Test file not found: {test_file.name}")
                self.update_task_status(task_id, "FAILED", receipt="Test file missing")
                return False

            verify_cmd = [sys.executable, str(test_file)]
            res = self.repair_loop.repair_and_verify(
                file_path=target_file,
                verify_cmd=verify_cmd,
                task_objective=objective,
                language=language,
                cwd=target_file.parent,
                task_id=task_id,
            )

            if res["success"]:
                receipt_path = res.get("receipt_path", "")
                self.update_task_status(task_id, "VERIFIED", receipt=receipt_path)

                # Register newly verified implementation into topology
                self.injector.register_verified_primitive(
                    primitive_id=f"PRIM_{target_file.stem.upper()}",
                    intent_description=objective,
                    verified_code=target_file.read_text(encoding="utf-8", errors="replace"),
                    test_harness_code=test_file.read_text(encoding="utf-8", errors="replace"),
                    language=language,
                )
                return True
            else:
                self.update_task_status(task_id, "FAILED", receipt="Self-healing exhausted")
                return False

        return False

    def run_autonomous_goal(self, goal_id: str, language: str = "python") -> bool:
        """Runs through all pending tasks in the DAG sequentially until completion."""
        print(f"\n==========================================================================")
        print(f"   STARTING AUTONOMOUS GOAL EXECUTION: {goal_id}")
        print(f"==========================================================================")

        while True:
            task = self.get_next_pending_task(goal_id)
            if not task:
                print(f"\n[+] All tasks for goal '{goal_id}' are complete!")
                notify_clawd("idle", "AfterAgent", tool_name="goal_complete")
                return True

            success = self.execute_task(task, language=language)
            if not success:
                print(f"\n[!] Task '{task['task_id']}' failed. Autonomous goal halted.")
                notify_clawd("error", "StopFailure", tool_name="task_failed")
                return False


def self_test():
    print("==========================================================================")
    print("   AUTONOMOUS DAG ORCHESTRATOR SILICON VERIFICATION")
    print("==========================================================================")
    orchestrator = DAGOrchestrator()

    test_target_dir = WORKSPACE_ROOT / "temp_dag_test"
    goal_id = f"GOAL_DAG_TEST_{int(time.time())}"

    # 1. Create 3-step DAG
    tasks = orchestrator.create_goal_dag(
        goal_id=goal_id,
        core_name="string_sanitizer",
        core_description="String sanitization utility with `sanitize_alphanumeric(text: str) -> str` removing non-alphanumeric chars",
        target_dir=test_target_dir,
        language="python",
    )
    assert len(tasks) == 3, "Expected 3 DAG tasks"

    # 2. Run the full autonomous loop
    success = orchestrator.run_autonomous_goal(goal_id=goal_id, language="python")
    assert success, "Autonomous goal execution failed"

    # 3. Clean up test files
    try:
        import shutil
        shutil.rmtree(test_target_dir, ignore_errors=True)
    except Exception:
        pass

    print("\n==========================================================================")
    print("   DAG ORCHESTRATOR TEST RESULT: SUCCESS")
    print("==========================================================================")


if __name__ == "__main__":
    self_test()
