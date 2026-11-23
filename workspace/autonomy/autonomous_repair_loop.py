"""
Autonomous Self-Healing Repair Loop (Pillar 2: The Deterministic Brake).
Automatically catches compiler, interpreter, and test failures, parses diagnostics,
re-prompts the local model with the exact failure, applies the patch, and re-verifies.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# Import the unified local client
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
AUTONOMY_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(AUTONOMY_DIR))

try:
    from local_model_client import LocalModelClient, default_client
    from snapshot_manager import SnapshotManager
    from clawd_notifier import notify_clawd, ensure_clawd_running
except ImportError:
    from .local_model_client import LocalModelClient, default_client
    from .snapshot_manager import SnapshotManager
    try:
        from .clawd_notifier import notify_clawd, ensure_clawd_running
    except ImportError:
        def notify_clawd(*args, **kwargs): pass
        def ensure_clawd_running(): pass


class AutonomousRepairLoop:
    def __init__(
        self,
        client: Optional[LocalModelClient] = None,
        max_retries: int = 3,
        python_exe: str = sys.executable,
        snapshot_manager: Optional[SnapshotManager] = None,
    ):
        self.client = client or default_client
        self.max_retries = max_retries
        self.python_exe = python_exe
        self.snapshot_manager = snapshot_manager or SnapshotManager()

    def run_command(self, cmd: Union[str, List[str]], cwd: Optional[Path] = None) -> Dict[str, Any]:
        """Runs a command and returns exit code, stdout, and stderr."""
        cmd_list = cmd if isinstance(cmd, list) else cmd.split()
        try:
            res = subprocess.run(
                cmd_list,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=str(cwd or WORKSPACE_ROOT),
                timeout=60,
                check=False,
            )
            return {
                "exit_code": res.returncode,
                "stdout": res.stdout.strip(),
                "stderr": res.stderr.strip(),
                "combined": f"{res.stdout}\n{res.stderr}".strip(),
            }
        except subprocess.TimeoutExpired as te:
            return {
                "exit_code": 124,
                "stdout": (te.stdout or "").strip(),
                "stderr": "Command timed out after 60 seconds",
                "combined": "Command timed out after 60 seconds",
            }
        except Exception as exc:
            return {
                "exit_code": 1,
                "stdout": "",
                "stderr": str(exc),
                "combined": str(exc),
            }

    def extract_diagnostic_summary(self, combined_output: str, is_rust: bool = False) -> str:
        """Extracts the critical error trace or compiler message to keep prompt focused."""
        lines = combined_output.splitlines()
        if not lines:
            return "(No output recorded)"

        if is_rust:
            # Rust compiler diagnostics: capture lines containing error: or note:
            error_lines = [line for line in lines if "error[" in line or "error:" in line or "-->" in line]
            if error_lines:
                return "\n".join(lines[:40])  # First 40 lines of rust diagnostic
            return "\n".join(lines[-30:])

        # Python diagnostics: locate Traceback or AssertionError
        tb_idx = -1
        for idx, line in enumerate(lines):
            if "Traceback (most recent call last):" in line:
                tb_idx = idx
                break
        if tb_idx >= 0:
            return "\n".join(lines[tb_idx:])
        
        # Capture last 25 lines as fallback
        return "\n".join(lines[-25:])

    def repair_and_verify(
        self,
        file_path: Path,
        verify_cmd: Union[str, List[str]],
        task_objective: str,
        language: str = "python",
        cwd: Optional[Path] = None,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Executes verify_cmd. If it fails, enters an autonomous diagnostic self-healing loop
        up to max_retries attempts, with pre-task snapshotting, automatic rollback on exhaustion,
        and ancestral receipt sealing on success.
        """
        file_path = Path(file_path).resolve()
        is_rust = language.lower() in ("rust", "rs") or file_path.suffix == ".rs"
        history: List[Dict[str, Any]] = []
        actual_task_id = task_id or f"task_{file_path.stem}_{int(time.time())}"

        # 0. Create pre-task snapshot for rollback safety
        self.snapshot_manager.create_snapshot(actual_task_id, [file_path])

        print(f"\n[*] Starting AutonomousRepairLoop for: {file_path.name}")
        print(f"[*] Task Objective: {task_objective}")
        print(f"[*] Task ID: {actual_task_id}")
        print(f"[*] Max Self-Healing Retries: {self.max_retries}")

        for attempt in range(1, self.max_retries + 2):
            # 1. Run Verification
            print(f"[*] [Cycle {attempt}] Executing verification...")
            notify_clawd("working", "PreToolUse", tool_name="verification")
            run_res = self.run_command(verify_cmd, cwd=cwd)
            exit_code = run_res["exit_code"]

            if exit_code == 0:
                print(f"[+] [Cycle {attempt}] PASS! Exit Code 0 reached on silicon.")
                notify_clawd("idle", "AfterAgent", tool_name="verification_pass")
                receipt_path = self.snapshot_manager.seal_epoch(
                    task_id=actual_task_id,
                    task_objective=task_objective,
                    evidence={"attempts": attempt, "exit_code": 0, "output": run_res["combined"]},
                )
                return {
                    "success": True,
                    "attempts": attempt,
                    "final_exit_code": 0,
                    "final_output": run_res["combined"],
                    "receipt_path": str(receipt_path),
                    "history": history,
                }

            # If failed and attempts exhausted
            diagnostic = self.extract_diagnostic_summary(run_res["combined"], is_rust=is_rust)
            history.append({
                "attempt": attempt,
                "exit_code": exit_code,
                "diagnostic": diagnostic,
            })

            notify_clawd("error", "PostToolUseFailure", tool_name="verification_failure")
            print(f"[-] [Cycle {attempt}] Verification failed (Exit Code {exit_code}).")
            print(f"[-] Diagnostic summary:\n{diagnostic}\n")

            if attempt > self.max_retries:
                print(f"[!] [Cycle {attempt}] Retry budget exhausted ({self.max_retries} attempts). Triggering automatic rollback.")
                self.snapshot_manager.rollback(actual_task_id, reason=f"Repair exhausted after {self.max_retries} cycles")
                return {
                    "success": False,
                    "attempts": attempt - 1,
                    "final_exit_code": exit_code,
                    "final_output": run_res["combined"],
                    "history": history,
                }

            # 2. Read Current File and Check for Test Suite Context
            if not file_path.exists():
                current_code = "(File does not exist yet)"
            else:
                current_code = file_path.read_text(encoding="utf-8", errors="replace")

            test_file_context = ""
            possible_test_files = [
                file_path.parent / f"{file_path.stem}_test.py",
                file_path.parent / f"test_{file_path.stem}.py",
                file_path.parent / f"{file_path.stem}_test.rs",
            ]
            for tf in possible_test_files:
                if tf.exists() and tf != file_path:
                    try:
                        tf_content = tf.read_text(encoding="utf-8", errors="replace")
                        test_file_context = f"\nTest Suite Context (`{tf.name}`):\n```{language}\n{tf_content}\n```\n"
                        break
                    except Exception:
                        pass

            # 3. Formulate Self-Healing Prompt
            repair_prompt = f"""You are Viv, sovereign AIOS engineer. A verification check failed on silicon.

File to Fix: `{file_path.name}`
Target Objective:
{task_objective}
{test_file_context}
Current Implementation:
```{language}
{current_code}
```

Diagnostic / Traceback:
```
{diagnostic}
```

Instructions:
1. Identify the exact root cause of the error or failed assertion.
2. Fix the implementation to satisfy all invariants and assertions in the test suite.
3. ALWAYS place all required standard library imports (e.g. `import os`, `import shutil`, `import hashlib`, `import json`, `import time`, etc.) at the VERY TOP of the file. Do NOT use inline imports.
4. Ensure any directory paths used (e.g. `snapshot_dir`) are created with `os.makedirs(path, exist_ok=True)` in `__init__` before file write operations.
5. In paths, join directory and filename using `os.path.join()` (e.g. `os.path.getsize(os.path.join(self.snapshot_dir, f))`).
6. Do NOT change, omit, or rename working dictionary keys (e.g. 'quota_used' must remain 'quota_used', 'status' must remain 'status', 'snapshot_count' must remain 'snapshot_count').
7. Output ONLY the complete, working replacement code for `{file_path.name}`.
8. Do not include markdown conversational filler, disclaimers, or explanations outside the code.
"""

            # 4. Generate Corrected Code
            print(f"[*] [Cycle {attempt}] Re-prompting local model for self-healing patch...")
            t0 = time.time()
            fixed_code = self.client.generate_code(
                prompt=repair_prompt,
                system_prompt="You are Viv, the sovereign AIOS Core Mind and engineer. Fix the code to pass all assertions. Output clean code directly.",
                temperature=0.1,
                max_tokens=8192,
            )
            elapsed = time.time() - t0
            print(f"[*] [Cycle {attempt}] Patch generated in {elapsed:.2f}s ({len(fixed_code)} chars).")

            if len(fixed_code.strip()) < 50:
                print(f"[!] [Cycle {attempt}] Generated patch was empty or too short ({len(fixed_code)} chars). Refusing to clobber disk.")
                continue

            # 5. Apply Patch to Disk
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(fixed_code, encoding="utf-8")
            print(f"[*] [Cycle {attempt}] Applied patch to {file_path.name}.")

        return {
            "success": False,
            "attempts": self.max_retries,
            "history": history,
        }


def self_test_on_silicon():
    """Verifies that the repair loop catches an intentional bug and self-heals it."""
    print("==========================================================================")
    print("   AUTONOMOUS REPAIR LOOP SILICON VERIFICATION")
    print("==========================================================================")
    
    test_dir = WORKSPACE_ROOT
    probe_py = test_dir / "temp_self_heal_probe.py"
    test_py = test_dir / "temp_self_heal_test.py"

    # Step 1: Write an intentionally buggy probe file
    buggy_code = """
def calculate_compound_interest(principal: float, rate: float, periods: int) -> float:
    # BUG: using simple addition instead of compounding formula
    return principal + rate * periods
"""
    probe_py.write_text(buggy_code.strip(), encoding="utf-8")

    # Step 2: Write verification test
    test_code = """
from temp_self_heal_probe import calculate_compound_interest

# principal 1000, rate 0.05, 2 periods -> 1000 * (1.05)^2 = 1102.5
result = calculate_compound_interest(1000.0, 0.05, 2)
assert abs(result - 1102.5) < 1e-4, f"Expected 1102.5, got {result}"

# principal 100, rate 0.10, 1 period -> 110.0
assert abs(calculate_compound_interest(100.0, 0.10, 1) - 110.0) < 1e-4

print("COMPOUND INTEREST TEST PASSED")
"""
    test_py.write_text(test_code.strip(), encoding="utf-8")

    # Step 3: Run autonomous repair loop
    repair_loop = AutonomousRepairLoop(max_retries=3)
    res = repair_loop.repair_and_verify(
        file_path=probe_py,
        verify_cmd=[sys.executable, str(test_py)],
        task_objective="Implement `calculate_compound_interest(principal: float, rate: float, periods: int) -> float` using standard formula `principal * (1.0 + rate) ** periods`.",
        language="python",
        cwd=test_dir,
    )

    # Step 4: Clean up probe files
    try:
        probe_py.unlink(missing_ok=True)
        test_py.unlink(missing_ok=True)
    except Exception:
        pass

    print("\n==========================================================================")
    print(f"   PYTHON SELF TEST RESULT: {'SUCCESS' if res['success'] else 'FAILED'}")
    print(f"   Attempts Required: {res['attempts']}")
    print("==========================================================================")
    if not res["success"]:
        sys.exit(1)

    # Step 5: Rust compiler self-healing test on silicon
    print("\n==========================================================================")
    print("   RUST COMPILER SELF-HEALING SILICON VERIFICATION")
    print("==========================================================================")
    probe_rs = test_dir / "temp_rust_heal_probe.rs"
    probe_exe = test_dir / "temp_rust_heal_probe.exe"

    buggy_rs = """
fn multiply(a: i32, b: i32) -> i32 {
    "invalid_type_error"
}

fn main() {
    assert_eq!(multiply(3, 4), 12);
    println!("RUST HEAL OK");
}
"""
    probe_rs.write_text(buggy_rs.strip(), encoding="utf-8")

    res_rust = repair_loop.repair_and_verify(
        file_path=probe_rs,
        verify_cmd=["rustc", str(probe_rs), "-o", str(probe_exe)],
        task_objective="Fix `multiply(a: i32, b: i32) -> i32` so it returns the product `a * b` and compiles cleanly.",
        language="rust",
        cwd=test_dir,
    )

    # Run the compiled binary to ensure runtime assertion passes
    if res_rust["success"] and probe_exe.exists():
        run_exe = repair_loop.run_command([str(probe_exe)], cwd=test_dir)
        print(f"[*] Compiled binary output: {run_exe['stdout']}")
        assert "RUST HEAL OK" in run_exe["stdout"], f"Expected 'RUST HEAL OK', got: {run_exe['stdout']}"

    # Clean up probe files
    try:
        probe_rs.unlink(missing_ok=True)
        probe_exe.unlink(missing_ok=True)
        (test_dir / "temp_rust_heal_probe.pdb").unlink(missing_ok=True)
    except Exception:
        pass

    print("\n==========================================================================")
    print(f"   RUST SELF TEST RESULT: {'SUCCESS' if res_rust['success'] else 'FAILED'}")
    print(f"   Attempts Required: {res_rust['attempts']}")
    print("==========================================================================")
    if not res_rust["success"]:
        sys.exit(1)


if __name__ == "__main__":
    self_test_on_silicon()
