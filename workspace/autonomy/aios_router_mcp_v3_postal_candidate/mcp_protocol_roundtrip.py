"""One-shot MCP stdio postal round trip against isolated candidate state.

This is a transport/integration smoke, not evidence that the live OpenCode
Body/PrivacyCore plugins issued these synthetic fixture receipts. The
container has no network, a read-only root, and tmpfs-only router/key state.
"""

from __future__ import annotations

import hashlib
import json
import queue
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any


ROOT = Path(__file__).resolve().parent
IMAGE = "sha256:91a19a582ab99f6b51ecb12712afe4f0c2fe91fe4bcd48e59a7d159bd5d43f72"
PRIVACY_TARGET = (
    r"L:\LocalCoder\workspace\aios_rebuild\memory\aios_router\router.sqlite3"
)
SESSION = "mcp_postal_smoke_session"
AGENT = "localcoder-viv-drone-01"
LANE = "drone"
TASK = "mcp_postal_smoke_20261116"
ASSIGNMENT = f"Bounded postal round trip for {AGENT}; two turns maximum."
ASSIGNMENT_HASH = hashlib.sha256(ASSIGNMENT.encode("utf-8")).hexdigest()


class McpProcess:
    def __init__(self, receipt_dir: Path) -> None:
        self.receipt_dir = receipt_dir
        self.proc: subprocess.Popen[str] | None = None
        self.lines: queue.Queue[str | None] = queue.Queue()
        self.stderr_lines: list[str] = []
        self.next_id = 1
        self.last_receipt_ms = 0

    @staticmethod
    def wsl_mount(path: Path) -> str:
        parts = PureWindowsPath(str(path)).parts
        drive = parts[0][0].lower()
        return "/mnt/" + drive + "/" + "/".join(parts[1:])

    def start(self) -> None:
        self.receipt_dir.mkdir(parents=True, exist_ok=True)
        mount = self.wsl_mount(self.receipt_dir)
        command = [
            "wsl.exe", "--distribution", "Ubuntu", "--exec", "docker", "run",
            "--rm", "--interactive", "--network=none", "--read-only",
            "--cap-drop=ALL", "--security-opt=no-new-privileges:true",
            "--user=10001:10001", "--memory=256m", "--memory-swap=256m",
            "--cpus=1", "--pids-limit=32", "--shm-size=8m",
            "--tmpfs", "/var/lib/aios-router:rw,noexec,nosuid,size=64m,uid=10001,gid=10001",
            "--tmpfs", "/var/lib/aios-router-key:rw,noexec,nosuid,size=4m,uid=10001,gid=10001",
            "--mount", f"type=bind,source={mount},target=/var/lib/aios-body-receipts",
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
            self.lines.put(line)
        self.lines.put(None)

    def _read_stderr(self) -> None:
        assert self.proc is not None and self.proc.stderr is not None
        self.stderr_lines.extend(self.proc.stderr)

    def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        assert self.proc is not None and self.proc.stdin is not None
        request_id = self.next_id
        self.next_id += 1
        message: dict[str, Any] = {
            "jsonrpc": "2.0", "id": request_id, "method": method,
        }
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
                line = self.lines.get(timeout=remaining)
            except queue.Empty as error:
                raise TimeoutError(f"MCP response timed out: {method}") from error
            if line is None:
                details = "".join(self.stderr_lines[-20:])
                raise RuntimeError(f"MCP process ended during {method}: {details}")
            try:
                response = json.loads(line)
            except json.JSONDecodeError:
                continue
            if response.get("id") == request_id:
                if "error" in response:
                    raise RuntimeError(f"MCP {method} error: {response['error']}")
                return response

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        assert self.proc is not None and self.proc.stdin is not None
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self.proc.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        self.proc.stdin.flush()

    def write_receipt(
        self, source: str, actor_role: str | None = None, actor_id: str | None = None
    ) -> None:
        now_ms = int(time.time() * 1000)
        self.last_receipt_ms = max(now_ms, self.last_receipt_ms + 2)
        captured = datetime.fromtimestamp(
            self.last_receipt_ms / 1000, tz=timezone.utc
        ).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        checked_paths = [
            PRIVACY_TARGET,
            PRIVACY_TARGET + "-wal",
            PRIVACY_TARGET + "-shm",
            PRIVACY_TARGET + "-journal",
        ]
        receipt: dict[str, Any] = {
            "schema": "opencode_body_gate_receipt_v1",
            "source": source,
            "session_id": SESSION,
            "authority": "deterministic_aios_body_rust",
            "disposition": "ALLOW_MIND_RUNTIME",
            "allowed": True,
            "captured_at": captured,
            "privacy_core": {
                "schema": "privacy_core_file_write_decision_v1",
                "authority": "PrivacyCore.authorize_file_write",
                "target_path": PRIVACY_TARGET,
                "allowed": True,
                "reason": "file_write_policy_passed",
                "checked_paths": [
                    {"path": path, "allowed": True, "reason": "file_write_policy_passed"}
                    for path in checked_paths
                ],
            },
        }
        if actor_role is not None and actor_id is not None:
            receipt["postal_actor"] = {"role": actor_role, "agent_id": actor_id}
        filename = f"fixture-{self.next_id:04d}-{self.last_receipt_ms}-body-gate.json"
        path = self.receipt_dir / filename
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(receipt, stream, separators=(",", ":"))

    def call(
        self,
        name: str,
        arguments: dict[str, Any],
        actor_role: str | None = None,
        actor_id: str | None = None,
    ) -> Any:
        self.write_receipt(f"tool:aios_router_{name}", actor_role, actor_id)
        response = self.send("tools/call", {"name": name, "arguments": arguments})
        result = response.get("result", {})
        if result.get("isError"):
            raise RuntimeError(f"tool {name} failed: {result}")
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            payload: Any = structured
        else:
            content = result.get("content", [])
            text = next((part.get("text") for part in content if part.get("type") == "text"), "")
            payload = json.loads(text) if text else {}
        if isinstance(payload, dict) and payload.get("ok") is False:
            raise RuntimeError(f"tool {name} denied: {payload}")
        return payload.get("result", payload) if isinstance(payload, dict) else payload

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
    run_dir = ROOT / "mcp_smoke_runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipts = run_dir / "receipts"
    receipts.mkdir(parents=True, exist_ok=False)
    mcp = McpProcess(receipts)
    summary: dict[str, Any] = {
        "schema": "aios_router_postal_mcp_protocol_smoke_v1",
        "synthetic_gate_receipts": True,
        "live_router_touched": False,
        "daemon_enabled": False,
        "docker_image": IMAGE,
        "session_id": SESSION,
        "task_id": TASK,
    }
    try:
        mcp.start()
        initialized = mcp.send("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "localcoder-postal-smoke", "version": "1"},
        })
        mcp.notify("notifications/initialized")
        summary["mcp_protocol"] = initialized.get("result", {}).get("protocolVersion")
        listed = mcp.send("tools/list", {}).get("result", {}).get("tools", [])
        names = {tool.get("name") for tool in listed}
        required = {
            "open_build_task", "assign_drone_seed", "accept_self_prompt",
            "complete_lane", "postal_register_drone", "postal_drone_submit",
            "postal_drone_read_inbox", "postal_queen_list_outbox",
            "postal_queen_read_outbox", "postal_queen_dispatch", "postal_queen_summary",
        }
        missing = sorted(required - names)
        if missing:
            raise RuntimeError(f"MCP tool catalog missing: {missing}")

        common = {
            "session_id": SESSION,
            "task_id": TASK,
            "assignment_hash": ASSIGNMENT_HASH,
        }
        mcp.call("open_build_task", {
            **common, "assignment": ASSIGNMENT, "lane_ids": [LANE], "max_turns_per_lane": 2,
        })
        mcp.call("assign_drone_seed", {**common, "agent_id": AGENT})
        registration = mcp.call("postal_register_drone", {**common, "agent_id": AGENT}, "drone", AGENT)
        inbox_id = registration["inbox_id"]

        mcp.call("accept_self_prompt", {
            **common, "lane_id": LANE, "turn": 0, "prompt": "Complete one bounded postal smoke turn.",
        })
        first = mcp.call("postal_drone_submit", {
            **common, "lane_id": LANE, "turn": 0, "agent_id": AGENT,
            "reply_to_message_id": None, "body": "[DRONE] first bounded MCP turn",
        }, "drone", AGENT)
        outbox0 = mcp.call("postal_queen_list_outbox", common, "queen", "queen")
        mcp.call("postal_queen_read_outbox", {
            **common, "message_id": first["message_id"],
        }, "queen", "queen")
        delivered0 = mcp.call("postal_queen_dispatch", {
            **common, "source_message_id": first["message_id"],
            "destination_agent_id": AGENT, "destination_inbox_id": inbox_id,
            "body": "[QUEEN] continue to the second bounded turn",
        }, "queen", "queen")
        inbox0 = mcp.call("postal_drone_read_inbox", {
            **common, "agent_id": AGENT, "limit": 4,
        }, "drone", AGENT)
        queen_message = next(
            message for message in inbox0["messages"] if message.get("kind") == "queen_message"
        )

        mcp.call("accept_self_prompt", {
            **common, "lane_id": LANE, "turn": 1,
            "prompt": "Reply to the Queen message and finish the bounded task.",
        })
        second = mcp.call("postal_drone_submit", {
            **common, "lane_id": LANE, "turn": 1, "agent_id": AGENT,
            "reply_to_message_id": queen_message["message_id"],
            "body": "[DRONE] second bounded MCP turn",
        }, "drone", AGENT)
        mcp.call("postal_queen_read_outbox", {
            **common, "message_id": second["message_id"],
        }, "queen", "queen")
        bounced = mcp.call("postal_queen_dispatch", {
            **common, "source_message_id": second["message_id"],
            "destination_agent_id": AGENT, "destination_inbox_id": "inbox_" + "0" * 64,
            "body": "[QUEEN] test bounce",
        }, "queen", "queen")
        delivered1 = mcp.call("postal_queen_dispatch", {
            **common, "source_message_id": second["message_id"],
            "destination_agent_id": AGENT, "destination_inbox_id": inbox_id,
            "body": "[QUEEN] route corrected after the recorded bounce",
        }, "queen", "queen")
        inbox1 = mcp.call("postal_drone_read_inbox", {
            **common, "agent_id": AGENT, "limit": 4,
        }, "drone", AGENT)
        mcp.call("complete_lane", {
            **common, "lane_id": LANE, "receipt": "two MCP postal turns completed",
        })
        task_summary = mcp.call("postal_queen_summary", common, "queen", "queen")

        bounce_messages = []
        for message in inbox1["messages"]:
            if message.get("kind") == "bounce":
                try:
                    bounce_messages.append(json.loads(message.get("body", "{}")))
                except json.JSONDecodeError:
                    pass
        assert delivered0["status"] == "delivered"
        assert bounced["status"] == "bounced"
        assert bounced["reason_code"] == "inbox_handshake_mismatch"
        assert delivered1["status"] == "delivered"
        assert any(item.get("reason_code") == "inbox_handshake_mismatch" for item in bounce_messages)
        assert task_summary["state"] == "completed"
        assert task_summary["outbox_messages"] == 2
        summary.update({
            "result": "passed",
            "tool_catalog_count": len(listed),
            "registered_inbox_id": inbox_id,
            "first_outbox_count": outbox0.get("count"),
            "turns_submitted": 2,
            "invalid_handshake": bounced["reason_code"],
            "corrected_delivery": delivered1["status"],
            "bounce_visible_to_drone": True,
            "task_summary": task_summary,
        })
    finally:
        exit_code = mcp.close()
        summary["container_exit_code"] = exit_code
        summary["container_stderr_tail"] = "".join(mcp.stderr_lines[-20:])[-4000:]
        receipt_path = run_dir / "RESULT.json"
        with receipt_path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(summary, stream, indent=2)
            stream.write("\n")
    print(json.dumps(summary, indent=2))
    return 0 if summary.get("result") == "passed" and exit_code == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
