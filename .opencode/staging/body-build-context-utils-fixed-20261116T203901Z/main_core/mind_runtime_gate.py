"""Fail-closed bridge for mind processes that must obey AIOS body authority."""
import time
import urllib.request


def query_body_gate(kernel=None, *, requested_threads: int = 1,
                    candidate_run_id: str | None = None,
                    goal_id: str | None = None) -> dict:
    if kernel is None:
        if candidate_run_id is None:
            try:
                try:
                    from main_core.body_resources import WORKSPACE_ROOT, collect_body_resources
                    from main_core.body_runtime_client import authorize
                except ImportError:
                    from aios_rebuild.main_core.body_resources import WORKSPACE_ROOT, collect_body_resources
                    from aios_rebuild.main_core.body_runtime_client import authorize

                resources = collect_body_resources(
                    workspace_root=WORKSPACE_ROOT,
                    requested_threads=requested_threads,
                )
                request = {"body_resources": resources}
                if goal_id is not None:
                    request["goal_id"] = goal_id
                decision = authorize(request)
            except Exception as error:
                return {
                    "allowed": False,
                    "disposition": "HOLD_MIND_RUNTIME",
                    "authority": "deterministic_aios_body_rust",
                    "reasons": [f"body_gate_unavailable:{type(error).__name__}"],
                }
            if isinstance(decision, dict):
                # Preserve the Rust verdict; attach the exact host sample for diagnosis only.
                diagnostics = decision.get("resource_diagnostics")
                diagnostics = dict(diagnostics) if isinstance(diagnostics, dict) else {}
                diagnostics["host_ram_percent"] = resources.get("ram_percent")
                diagnostics["host_sample_window_seconds"] = resources.get("sample_window_seconds")
                return {**decision, "resource_diagnostics": diagnostics}
            return {
                "allowed": False,
                "disposition": "HOLD_MIND_RUNTIME",
                "authority": "deterministic_aios_body_rust",
                "reasons": ["body_gate_returned_invalid_decision"],
            }

        try:
            try:
                from main_core.main_core import kernel as body_kernel
            except ImportError:
                from aios_rebuild.main_core.main_core import kernel as body_kernel
        except Exception as error:
            return {
                "allowed": False,
                "disposition": "HOLD_MIND_RUNTIME",
                "authority": "deterministic_aios_body_rust",
                "reasons": [f"body_gate_unavailable:{type(error).__name__}"],
            }
        kernel = body_kernel

    try:
        if candidate_run_id is None:
            decision = kernel.get_mind_runtime_gate(requested_threads=requested_threads)
        else:
            decision = kernel.get_mind_runtime_gate(
                requested_threads=requested_threads, candidate_run_id=candidate_run_id)
    except Exception as error:
        return {
            "allowed": False,
            "disposition": "HOLD_MIND_RUNTIME",
            "authority": "deterministic_aios_body_rust",
            "reasons": [f"body_gate_unavailable:{type(error).__name__}"],
        }

    if not isinstance(decision, dict):
        return {
            "allowed": False,
            "disposition": "HOLD_MIND_RUNTIME",
            "authority": "deterministic_aios_body_rust",
            "reasons": ["body_gate_returned_invalid_decision"],
        }
    return decision


def _is_rust_allow(decision: dict) -> bool:
    return (
        decision.get("allowed") is True
        and decision.get("disposition") == "ALLOW_MIND_RUNTIME"
        and decision.get("authority") == "deterministic_aios_body_rust"
    )


def _hold_decision(decision: dict) -> dict:
    if decision.get("allowed") is True:
        reasons = list(decision.get("reasons", []))
        reasons.append("body_gate_allow_verdict_missing_or_invalid_authority")
        return {**decision, "allowed": False, "disposition": "HOLD_MIND_RUNTIME",
                "reasons": reasons}
    return decision


def require_body_runtime(kernel=None, *, requested_threads: int = 1,
                         candidate_run_id: str | None = None,
                         goal_id: str | None = None) -> dict:
    decision = query_body_gate(kernel, requested_threads=requested_threads,
                               candidate_run_id=candidate_run_id, goal_id=goal_id)
    if not _is_rust_allow(decision):
        raise BodyRuntimeHold(_hold_decision(decision))
    return decision


def require_model_egress(endpoint: str, privacy_core=None) -> dict:
    if privacy_core is None:
        from aios_rebuild.privacy_core.privacy_core import PrivacyCore

        privacy_core = PrivacyCore()
    try:
        decision = privacy_core.authorize_egress_url(endpoint)
    except Exception as error:
        raise PrivacyEgressHold({
            "allowed": False,
            "reason": f"privacy_egress_authorization_unavailable:{type(error).__name__}",
        }) from error
    if not isinstance(decision, dict) or decision.get("allowed") is not True:
        raise PrivacyEgressHold(decision if isinstance(decision, dict) else {
            "allowed": False,
            "reason": "privacy_egress_decision_invalid",
        })
    return decision


def open_authorized_model_request(request, *, timeout: float, requested_threads: int = 2,
                                  kernel=None, privacy_core=None,
                                  goal_id: str | None = None):
    """Authorize the exact request target and body immediately before network I/O."""
    endpoint = request.full_url if isinstance(request, urllib.request.Request) else request
    require_model_egress(endpoint, privacy_core)
    require_body_runtime(kernel, requested_threads=requested_threads, goal_id=goal_id)
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _RejectModelRedirect(),
    )
    return opener.open(request, timeout=timeout)


class BodyRuntimeHold(RuntimeError):
    def __init__(self, verdict: dict):
        self.verdict = verdict
        super().__init__("AIOS body authority held mind runtime")


class PrivacyEgressHold(RuntimeError):
    def __init__(self, decision: dict):
        self.decision = decision
        super().__init__("AIOS PrivacyCore held model egress")


class _RejectModelRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        raise PrivacyEgressHold({
            "allowed": False,
            "reason": "model_egress_redirect_not_authorized",
        })


class RuntimeBodyGuard:
    def __init__(self, *, requested_threads: int, kernel=None,
                 candidate_run_id: str | None = None, goal_id: str | None = None,
                 poll_interval_seconds: float = 5.0):
        self.requested_threads = requested_threads
        self.kernel = kernel
        self.candidate_run_id = candidate_run_id
        self.goal_id = goal_id
        self.poll_interval_seconds = poll_interval_seconds
        self.last_check = 0.0
        self.last_verdict = None

    def check(self, *, force: bool = False) -> dict:
        now = time.monotonic()
        if force or self.last_verdict is None or now - self.last_check >= self.poll_interval_seconds:
            self.last_verdict = query_body_gate(
                self.kernel, requested_threads=self.requested_threads,
                candidate_run_id=self.candidate_run_id, goal_id=self.goal_id)
            self.last_check = now
            if not _is_rust_allow(self.last_verdict):
                # Absorb transient host WSL scheduling jitter under peak CPU load
                if any("timed_out" in str(r) for r in self.last_verdict.get("reasons", [])):
                    time.sleep(1.0)
                    self.last_verdict = query_body_gate(
                        self.kernel, requested_threads=self.requested_threads,
                        candidate_run_id=self.candidate_run_id, goal_id=self.goal_id)
                    self.last_check = time.monotonic()
        if not _is_rust_allow(self.last_verdict):
            raise BodyRuntimeHold(_hold_decision(self.last_verdict))
        return self.last_verdict


def main(argv=None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Query the deterministic Rust Body runtime gate.")
    parser.add_argument("--goal-id", default=None)
    args = parser.parse_args(argv)
    try:
        decision = require_body_runtime(requested_threads=2, goal_id=args.goal_id)
    except BodyRuntimeHold as hold:
        print(json.dumps(hold.verdict, sort_keys=True))
        return 2
    print(json.dumps(decision, sort_keys=True))
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
