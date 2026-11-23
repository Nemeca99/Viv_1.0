"""Offline node-deployment and endpoint-allowlist policy evaluator.

The evaluator is intentionally not a transport and never opens a socket. It
decides whether a proposed node/endpoint binding is eligible for a read-only
loopback rehearsal. Activation and external endpoints remain denied until a
separate deployment authority record exists.
"""
from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import json
from pathlib import Path
from typing import Any


DEFAULT_POLICY_CONTRACT = Path("foundation/artifacts/auto/agentic/NODE_FEDERATION_DEPLOYMENT_ALLOWLIST_CONTRACT.json")
DEFAULT_ALLOWLIST = Path("foundation/artifacts/auto/agentic/NODE_FEDERATION_DEPLOYMENT_ALLOWLIST.json")
READ_ONLY_POLICY_REHEARSAL = "READ_ONLY_POLICY_REHEARSAL"
ACTIVATION = "ACTIVATION"
LOOPBACK_ONLY = "LOOPBACK_ONLY"
EXTERNAL = "EXTERNAL"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1"})
HEX64 = frozenset("0123456789ABCDEF")
FORBIDDEN_FIELD_NAMES = frozenset(
    {
        "prompt",
        "prompts",
        "output",
        "outputs",
        "user_content",
        "knowledge",
        "dataset",
        "datasets",
        "tokens",
        "logits",
        "hidden_states",
        "scratchpad",
        "scratchpads",
        "expert_content",
        "payload",
        "raw_payload",
    }
)
REQUIRED_PROPOSAL_FIELDS = frozenset(
    {
        "evaluation_mode",
        "node_id",
        "key_id",
        "public_key_sha256",
        "node_identity_hash",
        "lineage_hash",
        "node_state",
        "endpoint_id",
        "endpoint_class",
        "host",
        "port",
        "tls_server_name",
        "ca_certificate_sha256",
        "server_certificate_sha256",
        "privacy_contract_sha256",
        "rate_limit_per_minute",
        "max_in_flight_frames",
        "max_retries",
        "max_frame_bytes",
        "master_to_node_content_channel",
        "raw_payload_forwarding",
        "raw_payload_persistence",
        "training_authorized",
        "run_authorized",
        "promotion_authorized",
        "deployment_authorized",
        "network_write_authorized",
    }
)


class DeploymentPolicyError(ValueError):
    """Raised when the hash-pinned policy inputs are malformed."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash_bytes(value: bytes) -> str:
    return sha256(value).hexdigest().upper()


def _hash_file(path: Path) -> str:
    try:
        return _hash_bytes(path.read_bytes())
    except OSError as exc:
        raise DeploymentPolicyError(f"deployment_policy_file_unreadable:{path}") from exc


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeploymentPolicyError(f"deployment_policy_json_unreadable:{path}") from exc
    if not isinstance(value, dict):
        raise DeploymentPolicyError(f"deployment_policy_json_must_be_object:{path}")
    return value


def _is_hex64(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value.upper()) <= HEX64


def _contains_forbidden_field(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key).lower() in FORBIDDEN_FIELD_NAMES:
                return True
            if _contains_forbidden_field(nested):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_field(item) for item in value)
    return False


class FederationDeploymentPolicy:
    """Hash-pinned, non-mutating evaluator for a node deployment proposal."""

    def __init__(
        self,
        *,
        contract_path: Path = DEFAULT_POLICY_CONTRACT,
        allowlist_path: Path = DEFAULT_ALLOWLIST,
    ) -> None:
        self.contract_path = Path(contract_path)
        self.allowlist_path = Path(allowlist_path)
        self.contract = _load_json(self.contract_path)
        self.allowlist = _load_json(self.allowlist_path)
        self.contract_sha256 = _hash_file(self.contract_path)
        self.allowlist_sha256 = _hash_file(self.allowlist_path)
        self._validate_policy_inputs()
        self._nodes = {
            item["node_id"]: item for item in self.allowlist["node_bindings"]
        }
        self._endpoints = {
            item["endpoint_id"]: item for item in self.allowlist["endpoint_allowlist"]
        }

    def evaluate(self, proposal: Mapping[str, Any]) -> dict[str, Any]:
        """Return aggregate policy evidence without retaining proposal content."""
        proposal_hash = _hash_bytes(_canonical(dict(proposal))) if isinstance(proposal, Mapping) else None
        reasons: list[str] = []
        if not isinstance(proposal, Mapping):
            reasons.append("proposal_must_be_object")
            return self._decision(False, reasons, proposal_hash)
        if _contains_forbidden_field(proposal):
            reasons.append("private_content_field_present")
        missing = sorted(REQUIRED_PROPOSAL_FIELDS - set(proposal))
        if missing:
            reasons.append("required_policy_fields_missing")
        if reasons:
            return self._decision(False, reasons, proposal_hash, proposal)

        node_id = str(proposal["node_id"])
        key_id = str(proposal["key_id"])
        endpoint_id = str(proposal["endpoint_id"])
        node = self._nodes.get(node_id)
        endpoint = self._endpoints.get(endpoint_id)
        if node is None:
            reasons.append("node_not_allowlisted")
        if endpoint is None:
            reasons.append("endpoint_not_allowlisted")
        if node is not None:
            self._compare_node_binding(proposal, node, reasons)
        if endpoint is not None:
            self._compare_endpoint_binding(proposal, endpoint, reasons)
        self._compare_privacy_and_authority(proposal, reasons)
        self._compare_budgets(proposal, endpoint, reasons)

        is_loopback_rehearsal = (
            proposal.get("evaluation_mode") == READ_ONLY_POLICY_REHEARSAL
            and proposal.get("endpoint_class") == LOOPBACK_ONLY
            and proposal.get("host") in LOOPBACK_HOSTS
        )
        if proposal.get("endpoint_class") == EXTERNAL:
            reasons.append("external_endpoint_policy_closed")
        if proposal.get("evaluation_mode") == ACTIVATION:
            reasons.append("deployment_activation_authority_closed")
        if not is_loopback_rehearsal:
            reasons.append("proposal_is_not_allowed_read_only_loopback_rehearsal")
        accepted = not reasons
        return self._decision(accepted, reasons, proposal_hash, proposal)

    def snapshot(self) -> dict[str, Any]:
        """Return policy metadata only; no allowlist bodies or proposal content."""
        return {
            "contract_sha256": self.contract_sha256,
            "allowlist_sha256": self.allowlist_sha256,
            "node_binding_count": len(self._nodes),
            "endpoint_allowlist_count": len(self._endpoints),
            "external_endpoint_allowlist_count": len(self.allowlist.get("external_endpoint_allowlist", [])),
            "external_activation_enabled": False,
            "network_contacted": False,
            "network_write_authorized": False,
            "raw_policy_content_retained": False,
        }

    def _validate_policy_inputs(self) -> None:
        if self.contract.get("schema_version") != "viv_node_federation_deployment_allowlist_contract_v1":
            raise DeploymentPolicyError("deployment_policy_contract_schema_mismatch")
        if self.allowlist.get("schema_version") != "viv_node_federation_deployment_allowlist_v1":
            raise DeploymentPolicyError("deployment_policy_allowlist_schema_mismatch")
        expected_allowlist_hash = self.contract.get("allowlist_fixture", {}).get("sha256")
        if expected_allowlist_hash != self.allowlist_sha256:
            raise DeploymentPolicyError("deployment_policy_allowlist_hash_mismatch")
        required_privacy = self.contract["privacy"]["required_telemetry_contract_hash"]
        if self.allowlist.get("privacy_contract_sha256") != required_privacy:
            raise DeploymentPolicyError("deployment_policy_privacy_contract_mismatch")
        for item in self.allowlist.get("node_bindings", []):
            if not isinstance(item, dict) or not _is_hex64(item.get("public_key_sha256")):
                raise DeploymentPolicyError("deployment_policy_node_binding_hash_invalid")
            if item.get("public_key_sha256", "").upper() != item.get("node_identity_hash", "").upper():
                raise DeploymentPolicyError("deployment_policy_node_identity_hash_mismatch")
        for item in self.allowlist.get("endpoint_allowlist", []):
            if not isinstance(item, dict):
                raise DeploymentPolicyError("deployment_policy_endpoint_entry_invalid")
            if not _is_hex64(item.get("ca_certificate_sha256")) or not _is_hex64(item.get("server_certificate_sha256")):
                raise DeploymentPolicyError("deployment_policy_certificate_pin_invalid")
            if item.get("endpoint_class") == "EXTERNAL":
                raise DeploymentPolicyError("deployment_policy_external_fixture_forbidden")

    @staticmethod
    def _compare_node_binding(proposal: Mapping[str, Any], node: Mapping[str, Any], reasons: list[str]) -> None:
        for field in ("key_id", "public_key_sha256", "node_identity_hash", "lineage_hash"):
            if str(proposal.get(field, "")).upper() != str(node.get(field, "")).upper():
                reasons.append(f"node_{field}_binding_mismatch")
        if proposal.get("node_state") != "ACTIVE" or node.get("status") != "ACTIVE":
            reasons.append("node_state_not_active")
        if proposal.get("node_state") == "REVOKED":
            reasons.append("node_revoked")
        if proposal.get("node_state") == "QUARANTINED":
            reasons.append("node_quarantined")
        if proposal.get("key_id") not in node.get("allowed_key_ids", [proposal.get("key_id")]):
            reasons.append("node_key_id_not_allowlisted")

    @staticmethod
    def _compare_endpoint_binding(proposal: Mapping[str, Any], endpoint: Mapping[str, Any], reasons: list[str]) -> None:
        for field in (
            "endpoint_class",
            "host",
            "port",
            "tls_server_name",
            "ca_certificate_sha256",
            "server_certificate_sha256",
        ):
            left = proposal.get(field)
            right = endpoint.get(field)
            if isinstance(left, str) and isinstance(right, str):
                if left.upper() != right.upper():
                    reasons.append(f"endpoint_{field}_binding_mismatch")
            elif left != right:
                reasons.append(f"endpoint_{field}_binding_mismatch")
        if endpoint.get("status") != "ALLOWLISTED":
            reasons.append("endpoint_not_active_allowlisted")
        if proposal.get("node_id") not in endpoint.get("allowed_node_ids", []):
            reasons.append("endpoint_node_not_allowlisted")
        if proposal.get("key_id") not in endpoint.get("allowed_key_ids", []):
            reasons.append("endpoint_key_not_allowlisted")
        if proposal.get("endpoint_class") == LOOPBACK_ONLY and proposal.get("host") not in LOOPBACK_HOSTS:
            reasons.append("loopback_host_not_loopback")

    def _compare_privacy_and_authority(self, proposal: Mapping[str, Any], reasons: list[str]) -> None:
        required_privacy = self.contract["privacy"]["required_telemetry_contract_hash"]
        if str(proposal.get("privacy_contract_sha256", "")).upper() != required_privacy.upper():
            reasons.append("privacy_contract_hash_mismatch")
        if proposal.get("master_to_node_content_channel") is not False:
            reasons.append("master_to_node_content_channel_forbidden")
        if proposal.get("raw_payload_forwarding") is not False:
            reasons.append("raw_payload_forwarding_forbidden")
        if proposal.get("raw_payload_persistence") is not False:
            reasons.append("raw_payload_persistence_forbidden")
        for field in ("training_authorized", "run_authorized", "promotion_authorized", "deployment_authorized", "network_write_authorized"):
            if proposal.get(field) is not False:
                reasons.append(f"{field}_must_be_closed_for_policy_rehearsal")

    def _compare_budgets(
        self,
        proposal: Mapping[str, Any],
        endpoint: Mapping[str, Any] | None,
        reasons: list[str],
    ) -> None:
        if endpoint is None:
            return
        limits = self.contract["budgets"]
        for field in ("rate_limit_per_minute", "max_in_flight_frames", "max_retries", "max_frame_bytes"):
            value = proposal.get(field)
            limit_field = {"rate_limit_per_minute": "max_rate_per_minute"}.get(field, field)
            contract_limit = limits[limit_field]
            endpoint_limit = endpoint.get(limit_field, contract_limit)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                reasons.append(f"{field}_invalid")
            elif value > contract_limit or value > endpoint_limit:
                reasons.append(f"{field}_exceeds_allowlisted_budget")

    def _decision(
        self,
        accepted: bool,
        reasons: list[str],
        proposal_hash: str | None,
        proposal: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        node_id = proposal.get("node_id") if isinstance(proposal, Mapping) else None
        endpoint_id = proposal.get("endpoint_id") if isinstance(proposal, Mapping) else None
        endpoint_class = proposal.get("endpoint_class") if isinstance(proposal, Mapping) else None
        return {
            "accepted": accepted,
            "decision": "ALLOW_LOOPBACK_POLICY_ONLY" if accepted else "DENY_DEPLOYMENT_POLICY",
            "reason_codes": list(dict.fromkeys(reasons)),
            "node_id": node_id,
            "endpoint_id": endpoint_id,
            "endpoint_class": endpoint_class,
            "proposal_sha256": proposal_hash,
            "contract_sha256": self.contract_sha256,
            "allowlist_sha256": self.allowlist_sha256,
            "network_contacted": False,
            "network_write_authorized": False,
            "deployment_changed": False,
            "raw_proposal_persisted": False,
        }


__all__ = [
    "ACTIVATION",
    "DEFAULT_ALLOWLIST",
    "DEFAULT_POLICY_CONTRACT",
    "DeploymentPolicyError",
    "EXTERNAL",
    "FederationDeploymentPolicy",
    "LOOPBACK_ONLY",
    "READ_ONLY_POLICY_REHEARSAL",
]
