import json
import time
import sys
import unittest
from pathlib import Path
from subprocess import CompletedProcess, TimeoutExpired
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent / "aios_rebuild"))

from main_core import body_runtime_client


class BodyRuntimeClientTests(unittest.TestCase):
    def request(self):
        return {
            "body_resources": {"thermal_samples": [], "requested_threads": 2},
        }

    def rust_verdict(self, *, allowed=False, reasons=None):
        return {
            "allowed": allowed,
            "disposition": "ALLOW_MIND_RUNTIME" if allowed else "HOLD_MIND_RUNTIME",
            "authority": "deterministic_aios_body_rust",
            "reasons": [] if reasons is None and allowed else (reasons or ["fixture"]),
            "expected_core_count": 1 if allowed else 0,
            "bound_core_count": 1 if allowed else 0,
            "active_without_health_report": [],
            "stability_sn": 0.8 if allowed else None,
            "minimum_stability_sn": 0.45,
            "requested_threads": 2,
        }

    def test_uses_fixed_hardened_wsl_docker_command_and_stdin_payload(self):
        request = self.request()
        request["candidate_run_id"] = "run-1"
        verdict = self.rust_verdict(reasons=["fixture"])
        completed = CompletedProcess([], 0, json.dumps(verdict), "wsl warning")
        with patch.object(body_runtime_client.shutil, "which", return_value="wsl.exe"), \
             patch.object(body_runtime_client.subprocess, "run", return_value=completed) as run:
            result = body_runtime_client.authorize(request)

        command = run.call_args.args[0]
        self.assertEqual(result["gate"], "rust")
        self.assertEqual(result["execution_boundary"], "wsl_docker")
        self.assertEqual(result["body_image"], body_runtime_client.BODY_IMAGE)
        self.assertEqual(run.call_args.kwargs["input"], json.dumps(
            request, ensure_ascii=True, separators=(",", ":"), sort_keys=True))
        self.assertEqual(command, [
            "wsl.exe", "-d", "Ubuntu", "--", "docker", "run", "--rm", "--interactive",
            "--pull=never", "--network=none", "--read-only", "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true", "--user=10001:10001",
            "--memory=256m", "--memory-swap=256m", "--cpus=1", "--pids-limit=32",
            "--shm-size=8m",
            "--tmpfs=/tmp:rw,noexec,nosuid,size=32m,mode=1777",
            "--tmpfs=/opt/aios_rebuild/data_core/FractalCache:rw,noexec,nosuid,size=32m,mode=1777",
            "--tmpfs=/opt/aios_rebuild/data_core/log:rw,noexec,nosuid,size=8m,mode=1777",
            "--tmpfs=/opt/aios_rebuild/dream_core/state:rw,noexec,nosuid,size=16m,mode=1777",
            "--tmpfs=/opt/aios_rebuild/memory:rw,noexec,nosuid,size=16m,mode=1777",
            "--tmpfs=/opt/aios_rebuild/marketplace_core/config:rw,noexec,nosuid,size=8m,mode=1777",
            "--tmpfs=/opt/aios_rebuild/music_core/config:rw,noexec,nosuid,size=8m,mode=1777",
            "--tmpfs=/opt/aios_rebuild/music_core/music_library:rw,noexec,nosuid,size=8m,mode=1777",
            "--tmpfs=/opt/aios_rebuild/template_core/config:rw,noexec,nosuid,size=8m,mode=1777",
            "--env=AIOS_WORKSPACE_ROOT=/opt/aios_rebuild",
            "--env=AIOS_ROOT=/opt/aios_rebuild",
            "--env=AIOS_PYTHON_ENV_PATH=/usr/local/bin",
            "--env=AIOS_LOG_DIR=/tmp/aios/log",
            "--env=AIOS_DEBUG_DIR=/tmp/aios/debug",
            "--log-driver=none", body_runtime_client.BODY_IMAGE,
        ])
        self.assertFalse(run.call_args.kwargs.get("shell", False))

    def test_accepts_only_complete_internally_consistent_rust_allow(self):
        allowed = self.rust_verdict(allowed=True)
        with patch.object(body_runtime_client.subprocess, "run",
                          return_value=CompletedProcess([], 0, json.dumps(allowed), "")):
            result = body_runtime_client.authorize(self.request())
        self.assertTrue(result["allowed"])
        self.assertEqual(result["execution_boundary"], "wsl_docker")

        allowed["reasons"] = ["hidden_hold"]
        with patch.object(body_runtime_client.subprocess, "run",
                          return_value=CompletedProcess([], 0, json.dumps(allowed), "")):
            result = body_runtime_client.authorize(self.request())
        self.assertFalse(result["allowed"])
        self.assertEqual(result["reasons"], ["wsl_body_response_invalid_schema"])

    def test_accepts_only_goal_bound_ram_override_matching_the_rust_sample(self):
        request = self.request()
        request["goal_id"] = "01a1d847-3b27-7533-bbc2-c718ace48ae7"
        request["body_resources"]["ram_percent"] = 95.4
        allowed = self.rust_verdict(allowed=True)
        allowed["architect_permission"] = {
            "status": "applied",
            "grant_id": "architect-test-ram-grant",
            "scope": "localcoder_runtime",
            "goal_id": request["goal_id"],
            "expires_unix": int(time.time()) + 3600,
            "waived_reasons": ["ram_at_or_above_limit"],
            "observed_ram_percent": 95.4,
        }
        with patch.object(body_runtime_client.subprocess, "run",
                          return_value=CompletedProcess([], 0, json.dumps(allowed), "")):
            result = body_runtime_client.authorize(request)
        self.assertTrue(result["allowed"])

        for field, value in [
            ("goal_id", "another-goal"),
            ("observed_ram_percent", 95.3),
            ("observed_ram_percent", 96.5),
        ]:
            bad = dict(allowed)
            bad["architect_permission"] = dict(allowed["architect_permission"])
            bad["architect_permission"][field] = value
            with self.subTest(field=field, value=value), patch.object(
                body_runtime_client.subprocess, "run",
                return_value=CompletedProcess([], 0, json.dumps(bad), ""),
            ):
                result = body_runtime_client.authorize(request)
            self.assertFalse(result["allowed"])
            self.assertEqual(result["reasons"], ["wsl_body_response_invalid_schema"])

        too_high = dict(request)
        too_high["body_resources"] = dict(request["body_resources"], ram_percent=96.5)
        with patch.object(body_runtime_client.subprocess, "run",
                          return_value=CompletedProcess([], 0, json.dumps(allowed), "")):
            result = body_runtime_client.authorize(too_high)
        self.assertFalse(result["allowed"])
        self.assertEqual(result["reasons"], ["wsl_body_response_invalid_schema"])

    def test_nonzero_docker_exit_fails_closed(self):
        completed = CompletedProcess([], 125, "", "docker unavailable")
        with patch.object(body_runtime_client.subprocess, "run", return_value=completed):
            result = body_runtime_client.authorize(self.request())
        self.assertFalse(result["allowed"])
        self.assertEqual(result["disposition"], "HOLD_MIND_RUNTIME")
        self.assertEqual(result["reasons"], ["wsl_body_nonzero_exit:125"])

    def test_missing_or_invalid_image_pin_holds_before_docker(self):
        for image_pin in ("", "aios-body-runtime:latest", "sha256:bad"):
            with self.subTest(image_pin=image_pin), patch.object(
                body_runtime_client, "BODY_IMAGE", image_pin
            ), patch.object(body_runtime_client.subprocess, "run") as run:
                result = body_runtime_client.authorize(self.request())
            self.assertFalse(result["allowed"])
            self.assertEqual(result["reasons"], ["body_image_pin_unavailable_or_invalid"])
            run.assert_not_called()

    def test_invalid_or_mismatched_body_response_fails_closed(self):
        for output, reason in [
            ("not-json", "wsl_body_response_invalid_json"),
            ("[]", "wsl_body_response_invalid_shape"),
            (json.dumps({"allowed": True, "disposition": "ALLOW_MIND_RUNTIME",
                         "authority": "untrusted"}), "wsl_body_response_authority_mismatch"),
            (json.dumps({**self.rust_verdict(), "unexpected": True}),
             "wsl_body_response_invalid_schema"),
        ]:
            with self.subTest(reason=reason), patch.object(
                body_runtime_client.subprocess, "run",
                return_value=CompletedProcess([], 0, output, ""),
            ):
                result = body_runtime_client.authorize(self.request())
            self.assertFalse(result["allowed"])
            self.assertEqual(result["reasons"], [reason])

    def test_timeout_and_oversized_request_fail_closed_without_fallback(self):
        with patch.object(body_runtime_client.subprocess, "run",
                          side_effect=TimeoutExpired("wsl", 10)) as run:
            timed_out = body_runtime_client.authorize(self.request())
        self.assertEqual(timed_out["reasons"], ["wsl_body_request_timed_out"])
        run.assert_called_once()

        with patch.object(body_runtime_client.subprocess, "run") as run:
            request = self.request()
            request["body_resources"]["padding"] = "x" * body_runtime_client.MAX_REQUEST_BYTES
            oversized = body_runtime_client.authorize(request)
        self.assertEqual(oversized["reasons"], ["body_request_exceeds_1_mibibyte_limit"])
        run.assert_not_called()

    def test_untyped_or_extra_top_level_input_is_rejected_before_docker(self):
        request = self.request()
        request["command"] = "sh"
        with patch.object(body_runtime_client.subprocess, "run") as run:
            result = body_runtime_client.authorize(request)
        self.assertEqual(result["reasons"], ["body_request_schema_invalid"])
        run.assert_not_called()

        request = self.request()
        request["goal_id"] = "unsafe goal id"
        with patch.object(body_runtime_client.subprocess, "run") as run:
            result = body_runtime_client.authorize(request)
        self.assertEqual(result["reasons"], ["body_request_schema_invalid"])
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
