import sys
import unittest
from contextlib import nullcontext
from io import BytesIO
from pathlib import Path
from urllib.request import Request
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent / "aios_rebuild"))

from main_core.mind_runtime_gate import (
    BodyRuntimeHold,
    PrivacyEgressHold,
    query_body_gate,
    require_body_runtime,
    require_model_egress,
    open_authorized_model_request,
    _RejectModelRedirect,
)


class FakeKernel:
    def __init__(self, decision=None, error=None):
        self.decision = decision
        self.error = error
        self.candidate_run_id = None

    def get_mind_runtime_gate(self, requested_threads=1, candidate_run_id=None):
        if self.error:
            raise self.error
        self.candidate_run_id = candidate_run_id
        return self.decision


class MindRuntimeGateTests(unittest.TestCase):
    def test_mind_swarm_bridge_ollama_uses_the_shared_body_gate(self):
        from hive_control.mind_swarm_bridge import call_ollama
        response = BytesIO(b'{"message":{"content":"ok"}}')
        with patch("aios_rebuild.main_core.mind_runtime_gate.open_authorized_model_request",
                   return_value=nullcontext(response)) as authorized:
            result = call_ollama({"model": "qwen3:8b-local"})
        self.assertEqual(result["message"]["content"], "ok")
        request = authorized.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:11434/api/chat")
        self.assertEqual(authorized.call_args.kwargs,
                         {"timeout": 300, "requested_threads": 2})

    def test_mind_swarm_bridge_body_hold_prevents_ollama_dispatch(self):
        from aios_rebuild.main_core.mind_runtime_gate import BodyRuntimeHold
        from hive_control.mind_swarm_bridge import call_ollama
        hold = BodyRuntimeHold({"allowed": False, "disposition": "HOLD_MIND_RUNTIME"})
        with patch("aios_rebuild.main_core.mind_runtime_gate.open_authorized_model_request",
                   side_effect=hold) as authorized:
            with self.assertRaises(BodyRuntimeHold):
                call_ollama({"model": "qwen3:8b-local"})
        authorized.assert_called_once()

    def test_authorized_model_request_checks_exact_url_then_body_then_network(self):
        request = Request("http://127.0.0.1:11434/api/chat")
        response = object()
        order = []
        opener = Mock()
        opener.open.side_effect = lambda actual_request, timeout: (
            order.append(("network", actual_request, timeout)), response)[1]
        with patch("main_core.mind_runtime_gate.require_model_egress",
                   side_effect=lambda url, privacy_core=None: order.append(("privacy", url))), \
             patch("main_core.mind_runtime_gate.require_body_runtime",
                   side_effect=lambda kernel, requested_threads: order.append(
                       ("body", requested_threads))), \
             patch("main_core.mind_runtime_gate.urllib.request.build_opener",
                   return_value=opener) as build_opener:
            opened = open_authorized_model_request(request, timeout=7, requested_threads=3)
        self.assertIs(opened, response)
        self.assertEqual(order[0], ("privacy", request.full_url))
        self.assertEqual(order[1], ("body", 3))
        self.assertEqual(order[2], ("network", request, 7))
        self.assertEqual(build_opener.call_args.args[0].proxies, {})
        self.assertIsInstance(build_opener.call_args.args[1], _RejectModelRedirect)

    def test_authorized_model_request_never_connects_after_either_hold(self):
        request = Request("http://127.0.0.1:11434/api/chat")
        privacy_hold = PrivacyEgressHold({"allowed": False, "reason": "deny"})
        with patch("main_core.mind_runtime_gate.require_model_egress", side_effect=privacy_hold), \
             patch("main_core.mind_runtime_gate.require_body_runtime") as body, \
             patch("main_core.mind_runtime_gate.urllib.request.build_opener") as opener:
            with self.assertRaises(PrivacyEgressHold):
                open_authorized_model_request(request, timeout=1)
        body.assert_not_called()
        opener.assert_not_called()

        body_hold = BodyRuntimeHold({"allowed": False, "disposition": "HOLD_MIND_RUNTIME"})
        with patch("main_core.mind_runtime_gate.require_model_egress"), \
             patch("main_core.mind_runtime_gate.require_body_runtime", side_effect=body_hold), \
             patch("main_core.mind_runtime_gate.urllib.request.build_opener") as opener:
            with self.assertRaises(BodyRuntimeHold):
                open_authorized_model_request(request, timeout=1)
        opener.assert_not_called()

    def test_model_redirect_is_denied_without_following_new_target(self):
        handler = _RejectModelRedirect()
        request = Request("http://127.0.0.1:11434/api/chat")
        with self.assertRaises(PrivacyEgressHold) as raised:
            handler.redirect_request(request, None, 302, "Found", {}, "https://example.com/away")
        self.assertEqual(raised.exception.decision["reason"],
                         "model_egress_redirect_not_authorized")

    def test_model_egress_requires_explicit_privacy_allow(self):
        class PrivacyPolicy:
            def authorize_egress_url(self, endpoint):
                self.endpoint = endpoint
                return {"allowed": True, "reason": "egress_policy_passed"}

        policy = PrivacyPolicy()
        decision = require_model_egress("http://127.0.0.1:11434/api/chat", policy)
        self.assertTrue(decision["allowed"])
        self.assertEqual(policy.endpoint, "http://127.0.0.1:11434/api/chat")

        with self.assertRaises(PrivacyEgressHold):
            require_model_egress("http://127.0.0.1:11434/api/chat", type(
                "DenyPolicy", (), {"authorize_egress_url": lambda self, endpoint:
                                   {"allowed": False, "reason": "egress_endpoint_not_loopback"}}
            )())

    def test_returns_rust_allow_decision(self):
        decision = {"allowed": True, "authority": "deterministic_aios_body_rust"}
        self.assertEqual(query_body_gate(FakeKernel(decision)), decision)

    def test_default_gate_uses_body_client_without_eager_kernel_import(self):
        from main_core.body_resources import WORKSPACE_ROOT

        resources = {"requested_threads": 2, "thermal_samples": []}
        decision = {"allowed": False, "disposition": "HOLD_MIND_RUNTIME",
                    "authority": "deterministic_aios_body_rust", "reasons": ["fixture"]}
        with patch("main_core.body_resources.collect_body_resources",
                   return_value=resources) as collect, \
             patch("main_core.body_runtime_client.authorize", return_value=decision) as authorize, \
             patch.dict("sys.modules", {"main_core.main_core": None,
                                         "aios_rebuild.main_core.main_core": None}):
            self.assertEqual(query_body_gate(requested_threads=2), decision)
        collect.assert_called_once_with(
            workspace_root=WORKSPACE_ROOT,
            requested_threads=2,
        )
        authorize.assert_called_once_with({"body_resources": resources})

    def test_preserves_rust_hold_decision(self):
        decision = {"allowed": False, "reasons": ["privacy_unverified"]}
        self.assertEqual(query_body_gate(FakeKernel(decision)), decision)

    def test_body_gate_errors_fail_closed(self):
        decision = query_body_gate(FakeKernel(error=RuntimeError("offline")))
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["disposition"], "HOLD_MIND_RUNTIME")

    def test_invalid_gate_result_fails_closed(self):
        decision = query_body_gate(FakeKernel(None))
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["reasons"], ["body_gate_returned_invalid_decision"])

    def test_passes_requested_thread_budget_to_body(self):
        class RecordingKernel(FakeKernel):
            requested_threads = None

            def get_mind_runtime_gate(self, requested_threads=1):
                self.requested_threads = requested_threads
                return {"allowed": True}

        kernel = RecordingKernel()
        query_body_gate(kernel, requested_threads=4)
        self.assertEqual(kernel.requested_threads, 4)

    def test_runtime_guard_rechecks_and_halts_when_body_withdraws_authorization(self):
        kernel = FakeKernel({"allowed": True, "disposition": "ALLOW_MIND_RUNTIME",
                             "authority": "deterministic_aios_body_rust"})
        guard = __import__("main_core.mind_runtime_gate", fromlist=["RuntimeBodyGuard"]).RuntimeBodyGuard(
            requested_threads=2, kernel=kernel)
        with patch("main_core.mind_runtime_gate.time.monotonic", side_effect=[1.0, 7.0]):
            guard.check(force=True)
            kernel.decision = {"allowed": False, "disposition": "HOLD_MIND_RUNTIME",
                               "reasons": ["ram_at_or_above_limit"]}
            with self.assertRaisesRegex(RuntimeError, "body authority held"):
                guard.check()

    def test_candidate_runtime_guard_binds_the_rust_check_to_run_id(self):
        kernel = FakeKernel({"allowed": True, "disposition": "ALLOW_MIND_RUNTIME",
                             "authority": "deterministic_aios_body_rust"})
        guard = __import__("main_core.mind_runtime_gate", fromlist=["RuntimeBodyGuard"]).RuntimeBodyGuard(
            requested_threads=2, kernel=kernel, candidate_run_id="test-candidate-run")
        guard.check(force=True)
        self.assertEqual(kernel.candidate_run_id, "test-candidate-run")

    def test_require_body_runtime_accepts_only_explicit_rust_allow(self):
        allowed = {"allowed": True, "disposition": "ALLOW_MIND_RUNTIME",
                   "authority": "deterministic_aios_body_rust"}
        self.assertEqual(require_body_runtime(FakeKernel(allowed)), allowed)

        with self.assertRaises(RuntimeError) as raised:
            require_body_runtime(FakeKernel({"allowed": True}))
        self.assertFalse(raised.exception.verdict["allowed"])
        self.assertIn("body_gate_allow_verdict_missing_or_invalid_authority",
                      raised.exception.verdict["reasons"])


if __name__ == "__main__":
    unittest.main()
