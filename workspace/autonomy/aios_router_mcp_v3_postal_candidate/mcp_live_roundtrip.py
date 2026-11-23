"""One bounded live postal cycle through Rust Body and PrivacyCore receipts.

Runs the pinned candidate MCP image once against the configured router DB and
key volume. It does not invoke a model or enable a daemon. Each action obtains
a fresh Rust Body verdict and PrivacyCore decision before writing its receipt.
The Queen actor is fixed here because this script is invoked by the
Architect-designated Codex Queen, outside the local OpenCode Drone session.
"""

from __future__ import annotations

import hashlib
import json
import queue
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


PROJECT = Path(r"L:\LocalCoder")
WORKSPACE = PROJECT / "workspace"
RECEIPTS = PROJECT / ".opencode" / "receipts"
PRIVACY_HELPER = WORKSPACE / "autonomy" / "privacy_core_router_db_gate_queen_v1_candidate.py"
PYTHON = Path(r"L:\.venv\Scripts\python.exe")
GOAL_ID = "01a1e340-84ed-77c3-92f3-3eb738b89f5b"
PRIVACY_TARGET = r"L:\LocalCoder\workspace\aios_rebuild\memory\aios_router\router.sqlite3"
IMAGE = "sha256:91a19a582ab99f6b51ecb12712afe4f0c2fe91fe4bcd48e59a7d159bd5d43f72"
KEY_VOLUME = "aios-router-postal-key-v1"
DRONE_ID = "localcoder-viv-drone-01"
LIVE_DB_MOUNT = "/mnt/l/LocalCoder/workspace/aios_rebuild/memory/aios_router"
RECEIPT_MOUNT = "/mnt/l/LocalCoder/.opencode/receipts"


class GatedMcp:
    def __init__(self, session_id: str, receipt_dir: Path) -> None:
        self.session_id = session_id
        self.receipt_dir = receipt_dir
        self.proc: subprocess.Popen[str] | None = None
        self.stdout_lines: queue.Queue[str | None] = queue.Queue()
        self.stderr_lines: list[str] = []
        self.next_id = 1
        self.last_receipt_ms = 0
        self.gate_audits: list[dict[str, Any]] = []

    def start(self) -> None:
        self.receipt_dir.mkdir(parents=True, exist_ok=True)
        command = [
            "wsl.exe", "--distribution", "Ubuntu", "--exec", "docker", "run",
            "--rm", "--interactive", "--pull=never", "--network=none", "--read-only",
            "--cap-drop=ALL", "--security-opt=no-new-privileges:true", "--user=10001:10001",
            "--memory=256m", "--memory-swap=256m", "--cpus=1", "--pids-limit=32",
            "--shm-size=8m", "--mount",
            f"type=bind,source={LIVE_DB_MOUNT},target=/var/lib/aios-router",
            "--mount",
            f"type=volume,source={KEY_VOLUME},target=/var/lib/aios-router-key",
            "--mount",
            f"type=bind,source={RECEIPT_MOUNT},target=/var/lib/aios-body-receipts,readonly",
            IMAGE,
        ]
        self.proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        assert self.proc.stdout is not None and self.proc.stderr is not None
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stdout(self) -> None:
        assert self.proc is not None and self.proc.stdout is not None
        for line in self.proc.stdout:
            self.stdout_lines.put(line)
        self.stdout_lines.put(None)

    def _read_stderr(self) -> None:
        assert self.proc is not None and self.proc.stderr is not None
        self.stderr_lines.extend(self.proc.stderr)

    def _fresh_body_and_privacy(self, source: str, actor: dict[str, str] | None) -> str:
        body = subprocess.run(
            [str(PYTHON), "-m", "aios_rebuild.main_core.mind_runtime_gate", "--goal-id", GOAL_ID],
            cwd=WORKSPACE,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if body.returncode != 0:
            raise RuntimeError(f"Rust Body gate process failed: {body.stderr[-2000:]}")
        try:
            verdict = json.loads(body.stdout)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"Rust Body gate returned invalid JSON: {body.stdout[-2000:]}") from error
        if not (
            verdict.get("allowed") is True
            and verdict.get("disposition") == "ALLOW_MIND_RUNTIME"
            and verdict.get("authority") == "deterministic_aios_body_rust"
        ):
            raise RuntimeError(f"Rust Body gate HOLD for {source}: {verdict}")

        privacy = subprocess.run(
            [str(PYTHON), "-B", str(PRIVACY_HELPER), "--authorize-router-db"],
            cwd=WORKSPACE,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if privacy.returncode != 0:
            raise RuntimeError(f"PrivacyCore process failed: {privacy.stderr[-2000:]}")
        try:
            decision = json.loads(privacy.stdout)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"PrivacyCore returned invalid JSON: {privacy.stdout[-2000:]}") from error
        if not (
            decision.get("schema") == "privacy_core_file_write_decision_v1"
            and decision.get("authority") == "PrivacyCore.authorize_file_write"
            and decision.get("target_path") == PRIVACY_TARGET
            and decision.get("allowed") is True
            and decision.get("reason") == "file_write_policy_passed"
        ):
            raise RuntimeError(f"PrivacyCore denied {source}: {decision}")
        expected_paths = [
            PRIVACY_TARGET,
            PRIVACY_TARGET + "-wal",
            PRIVACY_TARGET + "-shm",
            PRIVACY_TARGET + "-journal",
        ]
        checked = decision.get("checked_paths")
        if not isinstance(checked, list) or [entry.get("path") for entry in checked] != expected_paths:
            raise RuntimeError(f"PrivacyCore checked an unexpected path set: {decision}")

        now_ms = int(time.time() * 1000)
        self.last_receipt_ms = max(now_ms, self.last_receipt_ms + 2)
        captured = datetime.fromtimestamp(
            self.last_receipt_ms / 1000, tz=timezone.utc
        ).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        receipt: dict[str, Any] = {
            "schema": "opencode_body_gate_receipt_v1",
            "source": source,
            "session_id": self.session_id,
            "authority": verdict.get("authority"),
            "disposition": verdict.get("disposition"),
            "allowed": verdict.get("allowed"),
            "reasons": verdict.get("reasons", []),
            "body_image": verdict.get("body_image"),
            "resource_diagnostics": verdict.get("resource_diagnostics"),
            "architect_permission": verdict.get("architect_permission"),
            "privacy_core": decision,
            "captured_at": captured,
        }
        if actor is not None:
            receipt["postal_actor"] = actor
        filename = f"codex-postal-{self.session_id}-{self.next_id:04d}-body-gate.json"
        path = self.receipt_dir / filename
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(receipt, stream, separators=(",", ":"))
        self.gate_audits.append({
            "source": source,
            "captured_at": captured,
            "body_image": verdict.get("body_image"),
            "body_allowed": verdict.get("allowed"),
            "architect_permission_status": (verdict.get("architect_permission") or {}).get("status"),
            "privacy_allowed": decision.get("allowed"),
            "receipt_file": filename,
        })
        return filename

    def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        assert self.proc is not None and self.proc.stdin is not None
        request_id = self.next_id
        self.next_id += 1
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        self.proc.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        self.proc.stdin.flush()
        deadline = time.monotonic() + 20
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"MCP response timed out: {method}")
            try:
                line = self.stdout_lines.get(timeout=remaining)
            except queue.Empty as error:
                raise TimeoutError(f"MCP response timed out: {method}") from error
            if line is None:
                raise RuntimeError(f"MCP server exited: {''.join(self.stderr_lines[-20:])}")
            try:
                response = json.loads(line)
            except json.JSONDecodeError:
                continue
            if response.get("id") == request_id:
                if "error" in response:
                    raise RuntimeError(f"MCP {method} error: {response['error']}")
                return response

    def notify(self, method: str) -> None:
        assert self.proc is not None and self.proc.stdin is not None
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        self.proc.stdin.flush()

    def call(
        self,
        name: str,
        args: dict[str, Any],
        actor_role: str | None = None,
        actor_id: str | None = None,
    ) -> Any:
        actor = {"role": actor_role, "agent_id": actor_id} if actor_role and actor_id else None
        self._fresh_body_and_privacy(f"tool:aios_router_{name}", actor)
        response = self.send("tools/call", {"name": name, "arguments": args})
        result = response.get("result", {})
        if result.get("isError"):
            raise RuntimeError(f"MCP tool {name} failed: {result}")
        content = result.get("content", [])
        text = next((part.get("text") for part in content if part.get("type") == "text"), "")
        payload = json.loads(text) if text else result.get("structuredContent", {})
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise RuntimeError(f"Router denied {name}: {payload}")
        return payload.get("result", payload)

    def close(self) -> int:
        if self.proc is None:
            return 0
        if self.proc.stdin is not None:
            self.proc.stdin.close()
        try:
            return self.proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            return self.proc.wait(timeout=5)


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = stamp + "_" + uuid4().hex[:8]
    run_dir = PROJECT / "workspace" / "autonomy" / "aios_router_mcp_v3_postal_candidate" / "mcp_live_runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    session = "codex_postal_smoke_" + run_id.replace("T", "").replace("Z", "")
    task_id = "codex_postal_smoke_" + run_id.replace("T", "").replace("Z", "")
    assignment = f"Bounded two-turn postal routing smoke for Drone {DRONE_ID}; stop after the verified Queen summary."
    assignment_hash = hashlib.sha256(assignment.encode("utf-8")).hexdigest()
    common = {"session_id": session, "task_id": task_id, "assignment_hash": assignment_hash}
    mcp = GatedMcp(session, RECEIPTS)
    summary: dict[str, Any] = {
        "schema": "aios_router_postal_live_gate_roundtrip_v1",
        "result": "running",
        "test_scope": "one live router task with two bounded turns",
        "rust_body_gate": "required per tool action",
        "privacy_core": "required per tool action",
        "queen_actor": "codex",
        "drone_actor": DRONE_ID,
        "docker_image": IMAGE,
        "database": PRIVACY_TARGET,
        "key_volume": KEY_VOLUME,
        "daemon_enabled": False,
        "model_invoked": False,
        "live_router_modified": True,
        "session_id": session,
        "task_id": task_id,
    }
    try:
        mcp.start()
        initialized = mcp.send("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "codex-queen-live-postal-test", "version": "1"},
        })
        mcp.notify("notifications/initialized")
        summary["mcp_protocol"] = initialized.get("result", {}).get("protocolVersion")
        listed = mcp.send("tools/list", {}).get("result", {}).get("tools", [])
        available = {tool.get("name") for tool in listed}
        required = {
            "open_build_task", "lookup_drone_seed", "accept_self_prompt", "complete_lane",
            "postal_register_drone", "postal_drone_submit", "postal_drone_read_inbox",
            "postal_queen_list_outbox", "postal_queen_read_outbox",
            "postal_queen_dispatch", "postal_queen_summary",
        }
        missing = sorted(required - available)
        if missing:
            raise RuntimeError(f"MCP tool list missing required entries: {missing}")

        seed = mcp.call("lookup_drone_seed", {"agent_id": DRONE_ID})
        if seed.get("agent_id") != DRONE_ID or not isinstance(seed.get("seed"), int):
            raise RuntimeError(f"Existing Drone seed was not verified: {seed}")
        mcp.call("open_build_task", {
            **common, "assignment": assignment, "lane_ids": ["drone"], "max_turns_per_lane": 2,
        })
        registration = mcp.call("postal_register_drone", {**common, "agent_id": DRONE_ID}, "drone", DRONE_ID)
        inbox_id = registration["inbox_id"]

        mcp.call("accept_self_prompt", {
            **common, "lane_id": "drone", "turn": 0, "prompt": "Return the first bounded postal receipt.",
        })
        first = mcp.call("postal_drone_submit", {
            **common, "lane_id": "drone", "turn": 0, "agent_id": DRONE_ID,
            "reply_to_message_id": None, "body": "[DRONE] live gated turn one",
        }, "drone", DRONE_ID)
        outbox = mcp.call("postal_queen_list_outbox", common, "queen", "queen")
        mcp.call("postal_queen_read_outbox", {**common, "message_id": first["message_id"]}, "queen", "queen")
        delivery0 = mcp.call("postal_queen_dispatch", {
            **common, "source_message_id": first["message_id"], "destination_agent_id": DRONE_ID,
            "destination_inbox_id": inbox_id, "body": "[QUEEN] send the second bounded report",
        }, "queen", "queen")
        inbox0 = mcp.call("postal_drone_read_inbox", {
            **common, "agent_id": DRONE_ID, "limit": 4,
        }, "drone", DRONE_ID)
        queen_message = next(item for item in inbox0["messages"] if item.get("kind") == "queen_message")

        mcp.call("accept_self_prompt", {
            **common, "lane_id": "drone", "turn": 1,
            "prompt": "Reply to the Queen message; this is the final bounded turn.",
        })
        second = mcp.call("postal_drone_submit", {
            **common, "lane_id": "drone", "turn": 1, "agent_id": DRONE_ID,
            "reply_to_message_id": queen_message["message_id"],
            "body": "[DRONE] live gated turn two",
        }, "drone", DRONE_ID)
        mcp.call("postal_queen_read_outbox", {**common, "message_id": second["message_id"]}, "queen", "queen")
        bounce = mcp.call("postal_queen_dispatch", {
            **common, "source_message_id": second["message_id"], "destination_agent_id": DRONE_ID,
            "destination_inbox_id": "inbox_" + "0" * 64, "body": "[QUEEN] invalid-route test",
        }, "queen", "queen")
        delivery1 = mcp.call("postal_queen_dispatch", {
            **common, "source_message_id": second["message_id"], "destination_agent_id": DRONE_ID,
            "destination_inbox_id": inbox_id, "body": "[QUEEN] corrected route acknowledged",
        }, "queen", "queen")
        inbox1 = mcp.call("postal_drone_read_inbox", {
            **common, "agent_id": DRONE_ID, "limit": 4,
        }, "drone", DRONE_ID)
        mcp.call("complete_lane", {
            **common, "lane_id": "drone", "receipt": "two live gated postal turns completed",
        })
        task_summary = mcp.call("postal_queen_summary", common, "queen", "queen")

        bounce_bodies = []
        for item in inbox1["messages"]:
            if item.get("kind") == "bounce":
                try:
                    bounce_bodies.append(json.loads(item.get("body", "{}")))
                except json.JSONDecodeError:
                    pass
        assert delivery0.get("status") == "delivered"
        assert bounce.get("status") == "bounced"
        assert bounce.get("reason_code") == "inbox_handshake_mismatch"
        assert delivery1.get("status") == "delivered"
        assert any(item.get("reason_code") == "inbox_handshake_mismatch" for item in bounce_bodies)
        assert task_summary.get("state") == "completed"
        assert task_summary.get("outbox_messages") == 2
        summary.update({
            "result": "passed",
            "seed_verified": True,
            "outbox_count_after_turn_one": outbox.get("count"),
            "turns_submitted": task_summary.get("lanes", [{}])[0].get("completed_turns"),
            "invalid_handshake_reason": bounce.get("reason_code"),
            "corrected_route_status": delivery1.get("status"),
            "bounce_visible_in_drone_inbox": True,
            "postal_event_chain": task_summary.get("postal_event_chain"),
            "task_summary": task_summary,
        })
    except Exception as error:
        summary["result"] = "failed"
        summary["failure"] = f"{type(error).__name__}: {error}"
    finally:
        summary["gate_audits"] = mcp.gate_audits
        summary["container_exit_code"] = mcp.close()
        summary["container_stderr_tail"] = "".join(mcp.stderr_lines[-20:])[-4000:]
        result_path = run_dir / "RESULT.json"
        with result_path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(summary, stream, indent=2)
            stream.write("\n")
    print(json.dumps(summary, indent=2))
    return 0 if summary.get("result") == "passed" and summary.get("container_exit_code") == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
