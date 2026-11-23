"""Read-only review of local endpoint candidates for Viv federation.

The inventory is intentionally local and non-contacting.  This gate rejects
unrelated listeners, does not select a service, and cannot create or admit a
federation endpoint.  An empty eligible-candidate set is a safe hold.
"""
from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from .node_federation_operator_input_completion_review import (
    FederationOperatorInputCompletionReviewValidator,
)


HERE = Path(__file__).resolve().parent
FOUNDATION_ROOT = HERE.parent
REPOSITORY_ROOT = FOUNDATION_ROOT.parent
DEFAULT_CANDIDATE_CONTRACT = (
    FOUNDATION_ROOT
    / "artifacts"
    / "auto"
    / "agentic"
    / "NODE_FEDERATION_ENDPOINT_CANDIDATE_REVIEW_CONTRACT.json"
)
DEFAULT_CANDIDATE_PROPOSAL = (
    FOUNDATION_ROOT
    / "artifacts"
    / "auto"
    / "agentic"
    / "NODE_FEDERATION_ENDPOINT_CANDIDATE_REVIEW_PROPOSAL.json"
)
DEFAULT_CANDIDATE_INVENTORY = (
    FOUNDATION_ROOT
    / "artifacts"
    / "auto"
    / "agentic"
    / "NODE_FEDERATION_ENDPOINT_CANDIDATE_INVENTORY.json"
)
DEFAULT_COMPLETION_REVIEW_RECEIPT = (
    FOUNDATION_ROOT
    / "artifacts"
    / "auto"
    / "agentic"
    / "NODE_FEDERATION_OPERATOR_INPUT_COMPLETION_REVIEW_STAGE_RECEIPT.json"
)
CONTRACT_SCHEMA_VERSION = "viv_node_federation_endpoint_candidate_review_contract_v1"
PROPOSAL_SCHEMA_VERSION = "viv_node_federation_endpoint_candidate_review_proposal_v1"
INVENTORY_SCHEMA_VERSION = "viv_node_federation_endpoint_candidate_inventory_v1"
EXPECTED_CONTRACT_STATUS = "CLOSED_ENDPOINT_CANDIDATE_REVIEW"
EXPECTED_PROPOSAL_STATUS = "READ_ONLY_ENDPOINT_CANDIDATE_REVIEW"
EXPECTED_INVENTORY_STATUS = "READ_ONLY_LOCAL_LISTENER_INVENTORY"
EXPECTED_DECISION = "HOLD_NO_ELIGIBLE_FEDERATION_ENDPOINT"
EXPECTED_NEXT_STATE = "NO_ELIGIBLE_FEDERATION_ENDPOINT"


class EndpointCandidateReviewError(ValueError):
    """Raised when endpoint-candidate review inputs cannot be loaded."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash_bytes(value: bytes) -> str:
    return sha256(value).hexdigest().upper()


def _hash_file(path: Path) -> str:
    try:
        return _hash_bytes(path.read_bytes())
    except OSError as exc:
        raise EndpointCandidateReviewError(f"endpoint_candidate_file_unreadable:{path}") from exc


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EndpointCandidateReviewError(f"endpoint_candidate_{label}_unreadable:{path}") from exc
    if not isinstance(value, dict):
        raise EndpointCandidateReviewError(f"endpoint_candidate_{label}_must_be_object:{path}")
    return value


def _resolve_repo_path(value: Any) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else REPOSITORY_ROOT / path


class FederationEndpointCandidateReviewValidator:
    """Validate the local candidate inventory and closed proposal."""

    def __init__(
        self,
        *,
        contract_path: Path = DEFAULT_CANDIDATE_CONTRACT,
        proposal_path: Path = DEFAULT_CANDIDATE_PROPOSAL,
        inventory_path: Path = DEFAULT_CANDIDATE_INVENTORY,
    ) -> None:
        self.contract_path = Path(contract_path)
        self.proposal_path = Path(proposal_path)
        self.inventory_path = Path(inventory_path)
        self.contract = _load_json(self.contract_path, "contract")
        self.proposal = _load_json(self.proposal_path, "proposal")
        self.inventory = _load_json(self.inventory_path, "inventory")
        self.contract_sha256 = _hash_file(self.contract_path)
        self.proposal_sha256 = _hash_file(self.proposal_path)
        self.inventory_sha256 = _hash_file(self.inventory_path)
        self.completion_review = FederationOperatorInputCompletionReviewValidator()

    def validate(self) -> dict[str, Any]:
        """Return aggregate candidate evidence without contact or persistence."""
        return self.evaluate_proposal(self.proposal)

    def evaluate_proposal(self, proposal: Mapping[str, Any] | Any) -> dict[str, Any]:
        """Evaluate an in-memory proposal without external effects."""
        format_reasons = self._validate_contract()
        completion_result = self.completion_review.validate()
        if not completion_result.get("preflight_pass"):
            format_reasons.append("parent_completion_review_preflight_invalid")
        if completion_result.get("decision") != "HOLD_OPERATOR_INPUT_REQUIRED":
            format_reasons.append("parent_completion_review_decision_mismatch")
        if completion_result.get("safe_hold") is not True:
            format_reasons.append("parent_completion_review_safe_hold_mismatch")

        format_reasons.extend(self._validate_inventory())
        if not isinstance(proposal, Mapping):
            format_reasons.append("endpoint_candidate_proposal_must_be_object")
        else:
            if proposal.get("schema_version") != PROPOSAL_SCHEMA_VERSION:
                format_reasons.append("endpoint_candidate_proposal_schema_mismatch")
            if proposal.get("proposal_status") != EXPECTED_PROPOSAL_STATUS:
                format_reasons.append("endpoint_candidate_proposal_status_invalid")
            if proposal.get("proposal_decision") != EXPECTED_DECISION:
                format_reasons.append("endpoint_candidate_proposal_decision_invalid")
            if proposal.get("safe_hold") is not True:
                format_reasons.append("endpoint_candidate_proposal_safe_hold_invalid")
            if proposal.get("parent_completion_review_receipt_sha256") != self._parent_receipt_sha256():
                format_reasons.append("endpoint_candidate_proposal_parent_receipt_hash_mismatch")
            if proposal.get("candidate_inventory_path") != self._relative(self.inventory_path):
                format_reasons.append("endpoint_candidate_proposal_inventory_path_mismatch")
            if proposal.get("candidate_inventory_sha256") != self.inventory_sha256:
                format_reasons.append("endpoint_candidate_proposal_inventory_hash_mismatch")
            for field, expected in (
                ("observed_listener_count", self.inventory.get("total_listeners_observed")),
                ("observed_loopback_listener_count", self.inventory.get("loopback_listeners_observed")),
                ("eligible_federation_endpoint_count", 0),
            ):
                if proposal.get(field) != expected:
                    format_reasons.append(f"endpoint_candidate_proposal_{field}_mismatch")
            if proposal.get("federation_protocol_candidates") != []:
                format_reasons.append("endpoint_candidate_proposal_candidates_must_be_empty")
            for field in (
                "network_contacted",
                "dns_resolved",
                "certificate_fetched",
                "socket_opened",
                "activation_performed",
                "deployment_changed",
                "automatic_selection",
                "automatic_admission",
                "automatic_retry",
                "automatic_reauthorization",
            ):
                if proposal.get(field) is not False:
                    format_reasons.append(f"endpoint_candidate_proposal_{field}_must_be_false")
            if proposal.get("operator_selection_required") is not True:
                format_reasons.append("endpoint_candidate_proposal_operator_selection_required")

        hold_reasons = ["no_eligible_federation_endpoint", "operator_selection_required"]
        reason_codes = list(dict.fromkeys(format_reasons + hold_reasons))
        safe_hold = (
            isinstance(proposal, Mapping)
            and proposal.get("proposal_status") == EXPECTED_PROPOSAL_STATUS
            and proposal.get("proposal_decision") == EXPECTED_DECISION
            and proposal.get("safe_hold") is True
            and proposal.get("eligible_federation_endpoint_count") == 0
            and proposal.get("operator_selection_required") is True
            and all(proposal.get(field) is False for field in (
                "network_contacted",
                "dns_resolved",
                "certificate_fetched",
                "socket_opened",
                "activation_performed",
                "deployment_changed",
                "automatic_selection",
                "automatic_admission",
                "automatic_retry",
                "automatic_reauthorization",
            ))
        )
        review_validated = not format_reasons
        preflight_pass = review_validated and safe_hold
        if not safe_hold:
            reason_codes.append("endpoint_candidate_safe_hold_violated")
            preflight_pass = False

        return {
            "preflight_pass": preflight_pass,
            "candidate_review_preflight_pass": preflight_pass,
            "review_validated": review_validated,
            "decision": EXPECTED_DECISION,
            "safe_hold": safe_hold,
            "proposal_id": proposal.get("proposal_id") if isinstance(proposal, Mapping) else None,
            "proposal_status": proposal.get("proposal_status") if isinstance(proposal, Mapping) else None,
            "contract_sha256": self.contract_sha256,
            "proposal_sha256": self.proposal_sha256,
            "inventory_sha256": self.inventory_sha256,
            "parent_completion_review_receipt_sha256": self._parent_receipt_sha256(),
            "reason_codes": list(dict.fromkeys(reason_codes)),
            "observed_listener_count": self.inventory.get("total_listeners_observed"),
            "observed_loopback_listener_count": self.inventory.get("loopback_listeners_observed"),
            "eligible_federation_endpoint_count": 0,
            "federation_protocol_candidates": [],
            "operator_selection_required": True,
            "persisted_operator_endpoint_record_found": False,
            "persisted_federation_endpoint_contract_found": False,
            "network_contacted": False,
            "dns_resolved": False,
            "certificate_fetched": False,
            "socket_opened": False,
            "activation_performed": False,
            "deployment_changed": False,
            "automatic_selection": False,
            "automatic_admission": False,
            "automatic_retry": False,
            "automatic_reauthorization": False,
            "parent_completion_review_validated": completion_result.get("preflight_pass") is True,
            "parent_completion_review_safe_hold": completion_result.get("safe_hold") is True,
        }

    def _validate_contract(self) -> list[str]:
        reasons: list[str] = []
        contract = self.contract
        if contract.get("schema_version") != CONTRACT_SCHEMA_VERSION:
            reasons.append("endpoint_candidate_contract_schema_mismatch")
        if contract.get("status") != EXPECTED_CONTRACT_STATUS:
            reasons.append("endpoint_candidate_contract_status_invalid")
        parent = contract.get("parent_completion_review")
        if not isinstance(parent, Mapping):
            reasons.append("endpoint_candidate_parent_completion_section_invalid")
            parent = {}
        completion = self.completion_review
        for field, actual_path, hash_field in (
            ("contract_path", completion.contract_path, "contract_sha256"),
            ("request_path", completion.request_path, "request_sha256"),
            ("receipt_path", DEFAULT_COMPLETION_REVIEW_RECEIPT, "receipt_sha256"),
        ):
            declared_path = _resolve_repo_path(parent.get(field))
            if declared_path != actual_path:
                reasons.append(f"endpoint_candidate_parent_{field}_mismatch")
            actual_hash = _hash_file(actual_path) if actual_path.is_file() else None
            if parent.get(hash_field) != actual_hash:
                reasons.append(f"endpoint_candidate_parent_{hash_field}_mismatch")
        parent_receipt = _load_json(
            _resolve_repo_path(parent.get("receipt_path")) or Path(""),
            "parent_completion_receipt",
        )
        if parent_receipt.get("status") != parent.get("required_status"):
            reasons.append("endpoint_candidate_parent_receipt_status_mismatch")
        if parent_receipt.get("preflight_result", {}).get("decision") != parent.get("required_decision"):
            reasons.append("endpoint_candidate_parent_receipt_decision_mismatch")
        if parent_receipt.get("preflight_result", {}).get("safe_hold") is not parent.get("required_safe_hold"):
            reasons.append("endpoint_candidate_parent_receipt_safe_hold_mismatch")

        inventory = contract.get("candidate_inventory")
        if not isinstance(inventory, Mapping):
            reasons.append("endpoint_candidate_inventory_section_invalid")
            inventory = {}
        if _resolve_repo_path(inventory.get("path")) != self.inventory_path:
            reasons.append("endpoint_candidate_inventory_path_mismatch")
        if inventory.get("sha256") != self.inventory_sha256:
            reasons.append("endpoint_candidate_inventory_hash_mismatch")
        if inventory.get("required_status") != EXPECTED_INVENTORY_STATUS:
            reasons.append("endpoint_candidate_inventory_status_contract_mismatch")
        if inventory.get("required_decision") != EXPECTED_DECISION:
            reasons.append("endpoint_candidate_inventory_decision_contract_mismatch")

        proposal = contract.get("proposal")
        if not isinstance(proposal, Mapping):
            reasons.append("endpoint_candidate_proposal_section_invalid")
            proposal = {}
        if _resolve_repo_path(proposal.get("path")) != self.proposal_path:
            reasons.append("endpoint_candidate_proposal_path_mismatch")
        if proposal.get("sha256") != self.proposal_sha256:
            reasons.append("endpoint_candidate_proposal_hash_mismatch")
        if proposal.get("required_status") != EXPECTED_PROPOSAL_STATUS:
            reasons.append("endpoint_candidate_proposal_status_contract_mismatch")
        if proposal.get("required_decision") != EXPECTED_DECISION:
            reasons.append("endpoint_candidate_proposal_decision_contract_mismatch")

        rules = contract.get("review_rules")
        if not isinstance(rules, Mapping):
            reasons.append("endpoint_candidate_review_rules_invalid")
            rules = {}
        for field in (
            "external_discovery",
            "dns_resolution",
            "certificate_fetch",
            "socket_contact",
            "endpoint_selection",
            "endpoint_admission",
            "activation",
            "deployment",
            "automatic_retry",
            "automatic_reauthorization",
            "raw_endpoint_payload_persistence",
        ):
            if rules.get(field) is not False:
                reasons.append(f"endpoint_candidate_review_rule_{field}_forbidden")

        implementation = contract.get("implementation")
        if not isinstance(implementation, Mapping):
            reasons.append("endpoint_candidate_implementation_invalid")
            implementation = {}
        for field in (
            "network_sender",
            "dns_resolver",
            "certificate_fetcher",
            "socket_opener",
            "subprocess_runner",
            "filesystem_writer",
            "automatic_selection_capability",
            "candidate_admission_capability",
            "activation_capability",
            "deployment_capability",
            "reauthorization_capability",
        ):
            if implementation.get(field) is not False:
                reasons.append(f"endpoint_candidate_implementation_{field}_forbidden")
        return list(dict.fromkeys(reasons))

    def _validate_inventory(self) -> list[str]:
        inventory = self.inventory
        reasons: list[str] = []
        if inventory.get("schema_version") != INVENTORY_SCHEMA_VERSION:
            reasons.append("endpoint_candidate_inventory_schema_mismatch")
        if inventory.get("inventory_status") != EXPECTED_INVENTORY_STATUS:
            reasons.append("endpoint_candidate_inventory_status_invalid")
        if inventory.get("review_decision") != EXPECTED_DECISION:
            reasons.append("endpoint_candidate_inventory_decision_invalid")
        if inventory.get("safe_hold") is not True:
            reasons.append("endpoint_candidate_inventory_safe_hold_invalid")
        if inventory.get("federation_protocol_candidates") != []:
            reasons.append("endpoint_candidate_inventory_candidates_must_be_empty")
        if inventory.get("eligible_federation_endpoints") != []:
            reasons.append("endpoint_candidate_inventory_eligible_endpoints_must_be_empty")
        if inventory.get("persisted_operator_endpoint_record_found") is not False:
            reasons.append("endpoint_candidate_inventory_operator_record_must_be_missing")
        if inventory.get("persisted_federation_endpoint_contract_found") is not False:
            reasons.append("endpoint_candidate_inventory_contract_must_be_missing")
        if inventory.get("operator_selection_required") is not True:
            reasons.append("endpoint_candidate_inventory_operator_selection_required")
        for field in (
            "network_contacted",
            "dns_resolved",
            "certificate_fetched",
            "socket_opened_by_review",
            "external_discovery_performed",
            "automatic_endpoint_selection",
            "automatic_endpoint_admission",
            "automatic_activation",
            "automatic_retry",
            "automatic_reauthorization",
        ):
            if inventory.get(field) is not False:
                reasons.append(f"endpoint_candidate_inventory_{field}_must_be_false")
        summary = inventory.get("listener_process_summary")
        if not isinstance(summary, list):
            reasons.append("endpoint_candidate_inventory_process_summary_invalid")
        else:
            for item in summary:
                if not isinstance(item, Mapping) or item.get("federation_admitted") is not False:
                    reasons.append("endpoint_candidate_inventory_unadmitted_process_summary_required")
        return list(dict.fromkeys(reasons))

    def _parent_receipt_sha256(self) -> str:
        receipt_path = _resolve_repo_path(self.contract.get("parent_completion_review", {}).get("receipt_path"))
        if receipt_path is None:
            return ""
        return _hash_file(receipt_path)

    @staticmethod
    def _relative(path: Path) -> str:
        try:
            return path.relative_to(REPOSITORY_ROOT).as_posix()
        except ValueError:
            return path.as_posix()


__all__ = [
    "DEFAULT_CANDIDATE_CONTRACT",
    "DEFAULT_CANDIDATE_INVENTORY",
    "DEFAULT_CANDIDATE_PROPOSAL",
    "EndpointCandidateReviewError",
    "FederationEndpointCandidateReviewValidator",
]
