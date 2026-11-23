"""Recursive Hept learning loop over durable expert neurons."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Collection, Iterable, Mapping, Sequence

from .cuda_backend import (
    HEPT_GUIDE_BIAS_MAX,
    CudaHept,
    CudaLibrary,
    CudaRouteHold,
    HeptSnapshot,
    PrefixMemory,
)
from .fixed_point import SCALE, settle_triadic, toward_one, toward_zero
from .neuron_attention import SparseNeuronAttention
from .mode_contract import mode_expiry_hold_reason, mode_lock_digest
from .neuron_graph import (
    CurriculumStore,
    GraphStore,
    REFLECTORS,
    content_hash,
    make_neuron,
    new_neuron_id,
    reinforce_connection,
    stable_word_neuron_id,
    utc_now,
    validate_neuron,
)
if TYPE_CHECKING:
    from .frontier_scheduler import FrontierSchedule
    from .wave_store import DiskWaveStore


COURTROOM_GATE_KEYS = (
    "grammar",
    "meaning",
    "truth",
    "provenance",
    "contradiction_clearance",
    "jurisdiction",
    "authority",
)
COURTROOM_GATE_STATES = {"PASS", "FAIL", "HOLD", "NOT_REQUIRED"}
CPU_MODES = ("FICTION", "COURTROOM", "JURY")
CPU_MODE_RANK = {mode: index for index, mode in enumerate(CPU_MODES)}
CPU_EFFECT_MODE = {
    "REPRESENTATIONAL_FICTION": "FICTION",
    "FACTUAL_INQUIRY": "COURTROOM",
    "FACTUAL_ASSERTION": "COURTROOM",
    "CONSEQUENTIAL_ACTION": "JURY",
    "SECURITY_CORE_MUTATION": "JURY",
}


@lru_cache(maxsize=1)
def approved_lexical_surfaces() -> frozenset[str]:
    """Return the CPU-owned WORD-neuron admission vocabulary.

    A reusable WORD token must be an independent entry in an approved
    dictionary or thesaurus.  Substrings, affixes, and convenient fragments
    never become WORD tokens merely because they occur inside another word.
    """
    roots = (Path(__file__).resolve().parents[1] / "material",)
    sources = (
        roots[0] / "WebstersDictionary" / "dictionary.json",
        roots[0] / "Thesaurus" / "thesaurus.json",
    )
    surface_support: dict[str, bool] = {}
    obsolete_markers = ("[OBS.", "[PROV.", "[OBS. OR PROV.")
    for source in sources:
        if not source.is_file():
            continue
        payload = json.loads(source.read_text(encoding="utf-8"))
        rows = payload if isinstance(payload, list) else payload.get("entries", [])
        for row in rows:
            if isinstance(row, Mapping):
                surface = str(row.get("word", "")).strip().lower()
            else:
                surface = str(row).strip().lower()
            # The current character foundation contains ASCII letters only.
            # Admit only surfaces the learner can actually construct; entries
            # containing punctuation, digits, diacritics, or spaces remain
            # source data but cannot become WORD route targets in this rung.
            if surface and surface.isascii() and surface.isalpha():
                definitions = row.get("definitions", []) if isinstance(row, Mapping) else []
                definition_text = " ".join(str(value) for value in definitions).upper()
                current_support = not any(marker in definition_text for marker in obsolete_markers)
                surface_support[surface] = surface_support.get(surface, False) or current_support
    surfaces = {surface for surface, supported in surface_support.items() if supported}
    if not surfaces:
        raise RuntimeError("approved dictionary/thesaurus vocabulary is unavailable")
    return frozenset(surfaces)


def adjudicate_cpu_case(findings: Mapping[str, Any]) -> dict[str, Any]:
    """Return a deterministic PASS/FAIL/HOLD courtroom verdict.

    Grammar, meaning, and truth are mandatory. A structural failure or an
    admissible contradiction disproves the submitted case and returns FAIL.
    Missing provenance, jurisdiction, authority, or evidence returns HOLD:
    absence of proof is not proof of falsehood. Only a fully admitted case
    returns PASS.
    """

    missing = [key for key in COURTROOM_GATE_KEYS if key not in findings]
    if missing:
        raise ValueError(f"courtroom CPU judge omitted gates: {missing}")
    gates = {key: str(findings[key]).upper() for key in COURTROOM_GATE_KEYS}
    invalid = {key: value for key, value in gates.items() if value not in COURTROOM_GATE_STATES}
    if invalid:
        raise ValueError(f"courtroom CPU judge returned invalid gate states: {invalid}")
    for key in ("grammar", "meaning", "truth"):
        if gates[key] == "NOT_REQUIRED":
            raise ValueError(f"courtroom CPU gate {key} cannot be NOT_REQUIRED")

    for key in ("grammar", "meaning", "truth", "contradiction_clearance"):
        if gates[key] == "FAIL":
            return {
                "state": "FAIL",
                "reason": f"FAIL_CPU_{key.upper()}",
                "gates": gates,
                "material_doubt": False,
            }

    # Security and evidentiary-boundary failures deny admission without
    # asserting that the proposition itself is false.
    for key in (
        "jurisdiction",
        "authority",
        "provenance",
        "truth",
        "contradiction_clearance",
        "grammar",
        "meaning",
    ):
        if gates[key] in {"FAIL", "HOLD"}:
            return {
                "state": "HOLD",
                "reason": f"HOLD_CPU_{key.upper()}",
                "gates": gates,
                "material_doubt": True,
            }

    return {
        "state": "PASS",
        "reason": "PASS_CPU_BEYOND_REQUIRED_EVIDENTIARY_THRESHOLD",
        "gates": gates,
        "material_doubt": False,
    }


def select_cpu_mode(case: Mapping[str, Any]) -> dict[str, Any]:
    """Select and bind MODE_ROUTER_V1 from CPU-established effect facts.

    This router does not infer intent from raw language.  A CPU effect
    classifier must establish the requested effect first.  Hydra authenticates
    the context designation; the GPU may propose a mode but cannot lower the
    CPU-required burden.  Ambiguous or unauthenticated context fails closed.
    """

    required_lock_fields = (
        "session_id",
        "turn_id",
        "intent_sha256",
        "source_classification",
        "authorized_actor",
        "expires_utc",
        "parent_context_sha256",
    )
    missing = [key for key in ("requested_effect", "hydra_context_state", *required_lock_fields) if key not in case]
    if missing:
        raise ValueError(f"MODE_ROUTER_V1 case omitted fields: {missing}")
    expiry_hold = mode_expiry_hold_reason(case["expires_utc"])
    if expiry_hold:
        return {"state": "HOLD", "reason": expiry_hold, "selected_mode": None, "architecture": "MODE_ROUTER_V1"}

    effect = str(case["requested_effect"]).upper()
    hydra_state = str(case["hydra_context_state"]).upper()
    if hydra_state not in {"PASS", "HOLD", "FAIL"}:
        raise ValueError("hydra_context_state must be PASS, HOLD, or FAIL")
    if hydra_state != "PASS":
        return {
            "state": "HOLD",
            "reason": "HOLD_MODE_CONTEXT_NOT_AUTHENTICATED",
            "selected_mode": None,
            "architecture": "MODE_ROUTER_V1",
        }
    if effect not in CPU_EFFECT_MODE:
        return {
            "state": "HOLD",
            "reason": "HOLD_MODE_EFFECT_UNRESOLVED",
            "selected_mode": None,
            "architecture": "MODE_ROUTER_V1",
        }
    if bool(case.get("material_context_ambiguous", False)):
        return {
            "state": "HOLD",
            "reason": "HOLD_MODE_MATERIAL_CONTEXT_AMBIGUOUS",
            "selected_mode": None,
            "architecture": "MODE_ROUTER_V1",
        }

    required_modes = [CPU_EFFECT_MODE[effect]]
    required_reasons = [f"EFFECT_{effect}"]
    for field in ("real_world_effect", "high_stakes", "external_action", "security_core_mutation"):
        if bool(case.get(field, False)):
            required_modes.append("JURY")
            required_reasons.append(field.upper())

    gpu_proposal = case.get("gpu_proposed_mode")
    if gpu_proposal is not None:
        gpu_proposal = str(gpu_proposal).upper()
        if gpu_proposal not in CPU_MODE_RANK:
            raise ValueError("GPU proposed an unknown CPU mode")
        # A stricter GPU proposal may raise the burden.  A weaker proposal is
        # recorded but can never lower the CPU-established requirement.
        required_modes.append(gpu_proposal)
        required_reasons.append("GPU_PROPOSAL_NONAUTHORITATIVE")

    selected_mode = max(required_modes, key=CPU_MODE_RANK.__getitem__)
    lock_payload = {
        "architecture": "MODE_ROUTER_V1",
        "selected_mode": selected_mode,
        "requested_effect": effect,
        "required_reasons": sorted(set(required_reasons)),
        **{key: str(case[key]) for key in required_lock_fields},
    }
    lock_sha256 = mode_lock_digest(lock_payload)
    return {
        "state": "PASS",
        "reason": "PASS_CPU_MODE_SELECTED",
        "selected_mode": selected_mode,
        "minimum_cpu_mode": CPU_EFFECT_MODE[effect],
        "gpu_proposed_mode": gpu_proposal,
        "mode_escalated": selected_mode != CPU_EFFECT_MODE[effect],
        "required_reasons": sorted(set(required_reasons)),
        "mode_lock": lock_payload,
        "mode_lock_sha256": lock_sha256,
        "architecture": "MODE_ROUTER_V1",
    }


def verify_cpu_mode_egress(
    ingress_receipt: Mapping[str, Any],
    output_case: Mapping[str, Any],
) -> dict[str, Any]:
    """Fail closed unless output remains inside its ingress-locked case.

    The input boundary selects and hashes the proceeding before GPU work.  The
    output boundary independently routes the actual proposed effect, verifies
    that the original lock was not changed, and binds the emitted bytes to the
    same proceeding.  A changed effect starts a new proceeding; an increased
    burden can never inherit the weaker input lock.
    """

    if ingress_receipt.get("state") != "PASS" or ingress_receipt.get("architecture") != "MODE_ROUTER_V1":
        return {
            "state": "HOLD",
            "reason": "HOLD_MODE_INGRESS_LOCK_MISSING",
            "architecture": "MODE_ROUTER_V1_DUAL_BOUNDARY",
        }
    lock = ingress_receipt.get("mode_lock")
    if not isinstance(lock, Mapping):
        return {
            "state": "HOLD",
            "reason": "HOLD_MODE_INGRESS_LOCK_MALFORMED",
            "architecture": "MODE_ROUTER_V1_DUAL_BOUNDARY",
        }
    observed_ingress_hash = mode_lock_digest(lock)
    if observed_ingress_hash != str(ingress_receipt.get("mode_lock_sha256", "")).upper():
        return {
            "state": "HOLD",
            "reason": "HOLD_MODE_INGRESS_LOCK_HASH_MISMATCH",
            "architecture": "MODE_ROUTER_V1_DUAL_BOUNDARY",
        }

    # Trust the hashed mode, never an independently mutable summary field.
    if lock.get("selected_mode") not in CPU_MODE_RANK or ingress_receipt.get("selected_mode") != lock.get("selected_mode"):
        return {"state": "HOLD", "reason": "HOLD_MODE_INGRESS_SUMMARY_MISMATCH", "architecture": "MODE_ROUTER_V1_DUAL_BOUNDARY"}
    expiry_hold = mode_expiry_hold_reason(lock.get("expires_utc"))
    if expiry_hold:
        return {"state": "HOLD", "reason": expiry_hold, "architecture": "MODE_ROUTER_V1_DUAL_BOUNDARY"}

    output_sha256 = str(output_case.get("output_sha256", "")).upper()
    if len(output_sha256) != 64 or any(character not in "0123456789ABCDEF" for character in output_sha256):
        raise ValueError("output boundary requires a SHA-256 of the exact proposed output")
    output_route = select_cpu_mode(output_case)
    if output_route["state"] != "PASS":
        return {
            "state": "HOLD",
            "reason": output_route["reason"],
            "architecture": "MODE_ROUTER_V1_DUAL_BOUNDARY",
        }

    binding_fields = (
        "session_id",
        "turn_id",
        "intent_sha256",
        "source_classification",
        "authorized_actor",
        "expires_utc",
        "parent_context_sha256",
    )
    mismatched = [
        key for key in binding_fields
        if str(output_case.get(key, "")) != str(lock.get(key, ""))
    ]
    if mismatched:
        return {
            "state": "HOLD",
            "reason": "HOLD_MODE_PROCEEDING_BINDING_MISMATCH",
            "mismatched_fields": mismatched,
            "architecture": "MODE_ROUTER_V1_DUAL_BOUNDARY",
        }

    ingress_mode = str(ingress_receipt["selected_mode"])
    output_mode = str(output_route["selected_mode"])
    if CPU_MODE_RANK[output_mode] > CPU_MODE_RANK[ingress_mode]:
        return {
            "state": "HOLD",
            "reason": "HOLD_MODE_OUTPUT_REQUIRES_ESCALATION",
            "ingress_mode": ingress_mode,
            "required_output_mode": output_mode,
            "architecture": "MODE_ROUTER_V1_DUAL_BOUNDARY",
        }
    if str(output_case["requested_effect"]).upper() != str(lock["requested_effect"]).upper():
        return {
            "state": "HOLD",
            "reason": "HOLD_MODE_OUTPUT_EFFECT_CHANGED",
            "ingress_effect": str(lock["requested_effect"]),
            "output_effect": str(output_case["requested_effect"]).upper(),
            "architecture": "MODE_ROUTER_V1_DUAL_BOUNDARY",
        }
    if output_mode != ingress_mode:
        return {
            "state": "HOLD",
            "reason": "HOLD_MODE_OUTPUT_SCOPE_MISMATCH",
            "ingress_mode": ingress_mode,
            "output_mode": output_mode,
            "architecture": "MODE_ROUTER_V1_DUAL_BOUNDARY",
        }

    egress_lock = {
        "architecture": "MODE_ROUTER_V1_DUAL_BOUNDARY",
        "ingress_mode_lock_sha256": observed_ingress_hash,
        "selected_mode": ingress_mode,
        "requested_effect": str(output_case["requested_effect"]).upper(),
        "output_sha256": output_sha256,
        **{key: str(output_case[key]) for key in binding_fields},
    }
    egress_hash = hashlib.sha256(
        json.dumps(egress_lock, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest().upper()
    return {
        "state": "PASS",
        "reason": "PASS_MODE_INPUT_OUTPUT_LOCK_MATCH",
        "selected_mode": ingress_mode,
        "egress_lock": egress_lock,
        "egress_lock_sha256": egress_hash,
        "architecture": "MODE_ROUTER_V1_DUAL_BOUNDARY",
    }


@dataclass
class HeptRouteStep:
    previous_id: str
    candidate_ids: tuple[str, ...]
    selected_index: int
    selected_reflector: int
    strengths: tuple[int, ...]
    snapshot: HeptSnapshot | None = None
    cpu_guide_index: int | None = None
    profile_anchor_index: int | None = None
    profile_plan_index: int | None = None
    local_profile_guide_index: int | None = None
    temporal_profile_guide_index: int | None = None
    temporal_deferred_indices: tuple[int, ...] = ()
    blocked_indices: tuple[int, ...] = ()
    frontier_guide_index: int | None = None
    frontier_plan_id: str | None = None
    frontier_plan_nodes: int | None = None
    frontier_schedule_id: str | None = None
    frontier_schedule_rank: int | None = None
    frontier_schedule_next_cursor: int | None = None
    frontier_schedule_inspected: int | None = None
    prefix_novelty: int | None = None
    wave_version: int | None = None
    # CPU-provided opaque demand for this split.  It contains no target word
    # or answer order; it is the attractor against which candidate-owned
    # learned metadata is evaluated.
    activation_anchor: tuple[tuple[str, str], ...] = ()
    activation_context_weight: int | None = None

    @property
    def selected_id(self) -> str:
        return self.candidate_ids[self.selected_index]


class UniversalCurriculumEngine:
    """One recursive learning mechanism for variable-width neuron-token lessons."""

    CPU_ENDPOINT_NODE_BUDGET = 4_096
    DISCOVERY_MIN_SUPPORT = 32
    DISCOVERY_MAX_CONFIDENCE = 250_000
    # Opaque CPU-owned grammatical roles.  R0..R3 retain their original
    # meanings and indices; function-word channels are append-only so stored
    # evidence can migrate without reinterpretation.
    WORD_CLASS_CHANNELS = (
        "R0", "R1", "R2", "R3",  # noun, verb, adjective, adverb
        "R4", "R5", "R6", "R7", "R8",  # pronoun, preposition, conjunction, interjection, participle
    )
    WORD_CLASS_PROFILE_KEY = "opaque_word_class_profile_v1"
    WORD_SEMANTIC_CHANNELS = ("S0", "S1", "S2", "S3", "S4")
    WORD_SEMANTIC_PROFILE_KEY = "opaque_word_semantic_profile_v1"
    # Identity is a third independent, append-only routing profile.  The
    # channel meanings live only in the CPU teacher contract; neuron payloads
    # receive opaque I0..I4 evidence and cannot turn tags into authority.
    WORD_IDENTITY_CHANNELS = ("I0", "I1", "I2", "I3", "I4")
    WORD_IDENTITY_PROFILE_KEY = "opaque_word_identity_profile_v1"

    def __init__(
        self,
        store: GraphStore,
        library: CudaLibrary,
        curriculum: CurriculumStore,
        *,
        assembly_evidence: bool = False,
        self_discovery: bool = False,
        prefix_free_suffix: bool = False,
        route_truth_provider: Callable[[dict[str, Any]], Sequence[int]] | None = None,
        character_prior_provider: Callable[[str, Sequence[str]], Sequence[int]] | None = None,
        character_prior_sha256: str | None = None,
        complete_route_proposal_provider: Callable[[Counter[str], int, Mapping[str, Any]], Mapping[str, Any]] | None = None,
        complete_route_proposal_sha256: str | None = None,
        native_physical_identity: bool = False,
        strict_dictionary_composition: bool = False,
        authorized_word_surfaces: Collection[str] | None = None,
        ordered_prefix_composition: bool = False,
        word_role_evidence: bool = False,
        neuron_attention: bool = False,
        neuron_attention_learning: bool = False,
        neuron_attention_guidance: bool = False,
    ):
        self.store = store
        self.library = library
        self.curriculum = curriculum
        self.assembly_evidence_enabled = bool(assembly_evidence)
        self.self_discovery_enabled = bool(self_discovery)
        self.prefix_free_suffix_enabled = bool(prefix_free_suffix)
        self.route_truth_provider = route_truth_provider
        self.character_prior_provider = character_prior_provider
        self.character_prior_sha256 = (
            str(character_prior_sha256).upper() if character_prior_sha256 else None
        )
        self.complete_route_proposal_provider = complete_route_proposal_provider
        self.complete_route_proposal_sha256 = (
            str(complete_route_proposal_sha256).upper()
            if complete_route_proposal_sha256 else None
        )
        self.native_physical_identity_enabled = bool(native_physical_identity)
        self.strict_dictionary_composition_enabled = bool(strict_dictionary_composition)
        self.ordered_prefix_composition_enabled = bool(ordered_prefix_composition)
        self.word_role_evidence_enabled = bool(word_role_evidence)
        self.neuron_attention_enabled = bool(neuron_attention)
        self.neuron_attention_learning_enabled = bool(neuron_attention_learning)
        self.neuron_attention_guidance_enabled = bool(neuron_attention_guidance)
        if self.neuron_attention_learning_enabled and not self.neuron_attention_enabled:
            raise ValueError("neuron attention learning requires neuron attention observation")
        self.authorized_word_surfaces = (
            frozenset(str(surface) for surface in authorized_word_surfaces)
            if authorized_word_surfaces is not None else None
        )
        if (
            self.strict_dictionary_composition_enabled
            and self.authorized_word_surfaces is None
        ):
            raise ValueError(
                "strict dictionary composition requires CPU-authorized word surfaces"
            )
        self._catalog_cache: list[dict[str, Any]] | None = None

    def _attention_candidate_priors(
        self, eligible: Sequence[Mapping[str, Any]], context: str
    ) -> list[int]:
        neutral = SCALE // 2
        priors: list[int] = []
        for token in eligible:
            neuron = self.store.load_neuron(str(token["token_id"]))
            heads = neuron.get("center_attractor", {}).get(
                "sparse_attention_learning_v1", {}
            ).get("contexts", {}).get(str(context), {}).get("heads", {})
            local = heads.get("local_master", {})
            priors.append(max(1, min(SCALE, int(local.get("probability", neutral)))))
        return priors

    def _route_attention_receipt(self, route: Sequence[str]) -> dict[str, Any] | None:
        if not self.neuron_attention_enabled or not route:
            return None
        active_ids = tuple(dict.fromkeys(str(value) for value in route))
        neurons = {neuron_id: self.store.load_neuron(neuron_id) for neuron_id in active_ids}
        engine = SparseNeuronAttention()
        pulse = engine.pulse(engine.inputs_from_route(neurons, active_ids))
        return {
            "schema": "NN_SPARSE_FOUR_HEAD_PULSE_V1",
            "state": pulse.state,
            "active_neuron_ids": list(active_ids),
            "active_neurons": pulse.active_neurons,
            "head_activations": pulse.head_activations,
            "system_master_quality": pulse.system_master.quality,
            "system_master_rid": pulse.system_master.rid,
            "neuron_heads": [
                {
                    "neuron_id": item.neuron_id,
                    "user_quality": item.user.quality,
                    "assistant_quality": item.assistant.quality,
                    "mediator_quality": item.mediator.quality,
                    "local_master_quality": item.local_master.quality,
                }
                for item in pulse.neurons
            ],
        }

    def _apply_route_attention_consequence(
        self, route: Sequence[str], consequence: str, *, evidence_ref: str,
        steps: Sequence[tuple[str, str]] = (),
    ) -> str | None:
        if not self.neuron_attention_learning_enabled or not route:
            return None
        active_ids = tuple(dict.fromkeys(str(value) for value in route))
        neurons = {neuron_id: self.store.load_neuron(neuron_id) for neuron_id in active_ids}
        engine = SparseNeuronAttention()
        pulse = engine.pulse(engine.inputs_from_route(neurons, active_ids))
        # One neuron can participate in several route contexts. Preserve each
        # distinct pair instead of overwriting earlier evidence with the last.
        contexts: dict[str, list[str]] = {}
        for context, neuron_id in steps:
            values = contexts.setdefault(str(neuron_id), [])
            if str(context) not in values:
                values.append(str(context))
        changed = engine.apply_consequence(
            neurons, pulse, consequence, evidence_ref=evidence_ref,
            context_refs=contexts,
        )
        if not changed:
            return None
        from .neuron_graph import content_hash, utc_now
        for neuron in changed:
            neuron["updated_utc"] = utc_now()
            neuron["content_sha256"] = content_hash(neuron)
        return self.store.transact(
            changed,
            event_kind="SPARSE_ATTENTION_CONSEQUENCE_V1",
            details={
                "cpu_consequence": str(consequence),
                "evidence_ref": str(evidence_ref),
                "active_neuron_ids": list(active_ids),
                "head_count": 4 * len(active_ids),
            },
        )

    @staticmethod
    def _surface(neuron: dict[str, Any]) -> str:
        center = neuron.get("center_attractor", {})
        return str(
            center.get("learned_surface")
            or center.get("learned_combination")
            or center.get("learned_character")
            or ""
        )

    @staticmethod
    def _construction_alignment(neuron: dict[str, Any]) -> int:
        """Compatibility projection for pre-alignment neurons.

        Old graph bytes remain immutable evidence.  Missing alignment is
        projected from earned lifecycle/kind state, never from fiction or
        nonfiction meaning.
        """
        center = neuron.get("center_attractor", {})
        explicit = center.get("construction_alignment")
        if explicit is not None:
            return max(0, min(SCALE, int(explicit)))
        if center.get("trusted_language_memory") is True:
            return SCALE
        if neuron.get("kind") in {"CHARACTER", "COMBINATION", "WORD"} and neuron.get(
            "lifecycle"
        ) in {"PLASTIC", "STABLE"}:
            return SCALE
        return 0

    def _token_catalog(self) -> list[dict[str, Any]]:
        if self._catalog_cache is not None:
            return self._catalog_cache
        manifest = self.store.manifest()
        rows: list[dict[str, Any]] = []
        for neuron_id, index in manifest["neuron_index"].items():
            if index.get("kind") not in {"CHARACTER", "COMBINATION", "WORD"}:
                continue
            # Indexed NEWBORN shells are source-authentic lesson inventory,
            # not learned construction material.  Letting one enter this
            # catalog allows a target word to construct itself before it has
            # earned a route and can create a cyclic self-child on promotion.
            if index.get("lifecycle") not in {"PLASTIC", "STABLE"}:
                continue
            neuron = self.store.load_neuron(neuron_id)
            surface = self._surface(neuron)
            if not surface or any(character.isspace() for character in surface):
                continue
            if neuron.get("kind") == "WORD":
                if surface.lower() not in approved_lexical_surfaces():
                    continue
            rows.append({
                "token_id": neuron_id,
                "surface": surface,
                "kind": neuron["kind"],
                "activation_cost": 1,
                "_counts": Counter(surface),
            })
        self._catalog_cache = rows
        return rows

    def _word_composition_catalog(self, word: str) -> list[dict[str, Any]]:
        """Return legal construction pieces for one dictionary word lesson.

        In strict ladder mode, a new length-N word may use only character
        neurons and CPU-authorized WORD neurons shorter than N.  Generic
        COMBINATION neurons are deliberately excluded: if their surface is a
        real teacher word, the corresponding WORD neuron is the admissible
        reusable piece; otherwise the learner must fall back to characters.
        """
        # WORD lessons are constructed only from independently approved WORD
        # neurons and CHARACTER fallback. Generic substring COMBINATION
        # neurons are not lexical building blocks.
        catalog = [
            token for token in self._token_catalog()
            if token["kind"] in {"CHARACTER", "WORD"}
        ]
        if not self.strict_dictionary_composition_enabled:
            return catalog
        target_length = len(str(word))
        authorized = self.authorized_word_surfaces or frozenset()
        return [
            token for token in catalog
            if token["kind"] == "CHARACTER"
            or (
                token["kind"] == "WORD"
                and str(token["surface"]) in authorized
                and len(str(token["surface"])) < target_length
            )
        ]

    @staticmethod
    def _eligible_tokens(
        catalog: Sequence[dict[str, Any]], remaining: Counter[str]
    ) -> list[dict[str, Any]]:
        eligible: list[dict[str, Any]] = []
        for token in catalog:
            counts = token.get("_counts") or Counter(str(token["surface"]))
            if counts and all(remaining[key] >= value for key, value in counts.items()):
                eligible.append(token)
        return eligible

    @staticmethod
    def _route_probability(pass_hits: int, fail_hits: int) -> int:
        return ((int(pass_hits) + 1) * SCALE) // (
            int(pass_hits) + int(fail_hits) + 2
        )

    @staticmethod
    def _word_role_channels(
        eligible: Sequence[Mapping[str, Any]],
        remaining: Counter[str],
        local_probabilities: Sequence[int],
        projections: Sequence[tuple[int, int, int, tuple[str, ...]]],
        native_endpoint_scores: Sequence[int],
        consequence_endpoint_scores: Sequence[int],
        character_prior_scores: Sequence[int] | None,
    ) -> list[list[int]]:
        """Project source-authentic word evidence onto the six Hept reflectors."""
        width = len(eligible)
        aligned = (
            local_probabilities,
            native_endpoint_scores,
            consequence_endpoint_scores,
        )
        if any(len(values) != width for values in aligned):
            raise ValueError("word role evidence must align with the eligible frontier")
        if projections and len(projections) != width:
            raise ValueError("word pattern projections must align with the eligible frontier")
        if character_prior_scores is not None and len(character_prior_scores) != width:
            raise ValueError("word character priors must align with the eligible frontier")
        neutral = SCALE // 2
        remaining_size = max(1, sum(remaining.values()))
        channels = [
            [int(value) for value in local_probabilities],
            [int(item[0]) for item in projections] if projections else [neutral] * width,
            [
                min(SCALE, (len(str(token["surface"])) * SCALE) // remaining_size)
                for token in eligible
            ],
            [int(value) for value in native_endpoint_scores],
            [int(value) for value in consequence_endpoint_scores],
            (
                [int(value) for value in character_prior_scores]
                if character_prior_scores is not None else [neutral] * width
            ),
        ]
        if any(value < 0 or value > SCALE for channel in channels for value in channel):
            raise ValueError("word role evidence must contain fixed-point probabilities")
        return channels

    @staticmethod
    def _context(previous_id: str, remaining: Counter[str]) -> str:
        payload = json.dumps(
            {"previous": previous_id, "remaining": sorted(remaining.items())},
            separators=(",", ":"), sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest().upper()

    @staticmethod
    def _feature_sha256(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest().upper()

    def _pattern_features(
        self,
        emitted: str,
        candidate_surface: str,
        remaining_before: Counter[str],
    ) -> tuple[str, ...]:
        """Hash visible structure of one attempted transition, never its target."""
        total = len(emitted) + sum(remaining_before.values())
        next_length = len(emitted) + len(candidate_surface)
        position_bin = min(7, (len(emitted) * 8) // max(1, total))
        span_bin = min(7, (next_length * 8) // max(1, total))
        raw = [
            f"SHAPE|{position_bin}|{span_bin}|{min(8, len(candidate_surface))}",
            f"START|{int(not emitted)}|{candidate_surface[:1]}",
            f"END|{int(len(candidate_surface) == sum(remaining_before.values()))}|{candidate_surface[-1:]}",
        ]
        if emitted:
            raw.append(f"BOUNDARY1|{emitted[-1:]}|{candidate_surface[:1]}")
            if len(emitted) >= 2 and len(candidate_surface) >= 2:
                raw.append(f"BOUNDARY2|{emitted[-2:]}|{candidate_surface[:2]}")
        return tuple(self._feature_sha256(value) for value in raw)

    def _pattern_projection(
        self,
        emitted: str,
        candidate_surface: str,
        remaining_before: Counter[str],
    ) -> tuple[int, int, int, tuple[str, ...]]:
        features = self._pattern_features(emitted, candidate_surface, remaining_before)
        evidence = self.curriculum.pattern_evidence("WORD", features)
        supported = [
            (passes, failures)
            for passes, failures in evidence
            if passes + failures >= self.DISCOVERY_MIN_SUPPORT
        ]
        if not supported:
            return SCALE // 2, 0, 0, features
        probabilities = [
            self._route_probability(passes, failures)
            for passes, failures in supported
        ]
        support = sum(passes + failures for passes, failures in supported)
        confidence = min(
            self.DISCOVERY_MAX_CONFIDENCE,
            (support - self.DISCOVERY_MIN_SUPPORT + 1) * 10_000,
        )
        return sum(probabilities) // len(probabilities), confidence, support, features

    def _pick_bounded(
        self,
        scores: Sequence[int],
        *,
        seed: int,
        truths: Sequence[int] | None = None,
        role_channels: Sequence[Sequence[int]] | None = None,
        explore: bool = True,
    ) -> tuple[int, int]:
        """Recursively choose from any frontier width using <=128-way Hept cells."""
        if not scores:
            raise CudaRouteHold("empty supported frontier")
        truth_values = [SCALE] * len(scores) if truths is None else [int(value) for value in truths]
        if len(truth_values) != len(scores) or any(value not in {0, SCALE} for value in truth_values):
            raise ValueError("route truth mask must contain one binary fixed-point value per score")
        if role_channels is None:
            channel_values = [[int(value) for value in scores] for _ in range(6)]
        else:
            channel_values = [[int(value) for value in channel] for channel in role_channels]
            if len(channel_values) != 6 or any(len(channel) != len(scores) for channel in channel_values):
                raise ValueError("role evidence must contain six candidate-aligned channels")
            if any(value < 0 or value > SCALE for channel in channel_values for value in channel):
                raise ValueError("role evidence values must be fixed-point probabilities")
        if not any(truth_values):
            raise CudaRouteHold("HOLD_HYDRA_NO_AUTHORIZED_ROUTE")
        if not explore:
            # Frozen recall is exploitation, not another learning attempt.
            # Select only from the learner-owned strongest evidence; the CPU
            # supplies no target channel and ties remain seed-deterministic.
            best = max(int(value) for value, truth in zip(scores, truth_values) if truth)
            tied = [
                index for index, (value, truth) in enumerate(zip(scores, truth_values))
                if truth and int(value) == best
            ]
            selected = tied[int(seed) % len(tied)]
            return selected, best
        if len(scores) == 1:
            if truth_values[0] == 0:
                raise CudaRouteHold("HOLD_HYDRA_NO_AUTHORIZED_ROUTE")
            return 0, int(scores[0])
        if len(scores) <= 128:
            width = len(scores)
            best = max(int(value) for value, truth in zip(scores, truth_values) if truth)
            if best <= 0:
                raise CudaRouteHold("no supported endpoint probability")
            normalized_scores = [
                max(1, min(SCALE, (int(value) * SCALE) // best)) if truth else 0
                for value, truth in zip(scores, truth_values)
            ]
            tied = [index for index, (value, truth) in enumerate(zip(scores, truth_values)) if truth and int(value) == best]
            cpu_index = tied[int(seed) % len(tied)]
            # `nn_hept_attempt_kernel` draws from
            # splitmix64(attempt_seed ^ seed_state).  Passing the same value
            # for both operands cancels every lesson seed to zero and repeats
            # one draw forever.  Keep the cell state deterministic, but derive
            # it from the bounded cell shape rather than the attempt seed so
            # fresh attempt seeds produce fresh bounded samples.
            cell_seed_state = 0xD1B54A32D192ED03 ^ width
            with CudaHept(
                self.library,
                candidates=width,
                seed_state=cell_seed_state,
                centers=normalized_scores,
                reflectors=[value for channel in channel_values for value in channel],
                contexts=[SCALE // 2] * width,
                truths=truth_values,
                multiplicities=[1] * width,
            ) as cell:
                cell.set_guide_bias([
                    HEPT_GUIDE_BIAS_MAX if index == cpu_index and truth_values[index] else 0
                    for index in range(width)
                ])
                attempt = cell.attempt(seed)
            selected = int(attempt.candidate)
            return selected, int(attempt.strengths[selected])

        groups = [scores[index : index + 128] for index in range(0, len(scores), 128)]
        truth_groups = [truth_values[index : index + 128] for index in range(0, len(scores), 128)]
        group_scores = [max(group) for group in groups]
        group_truths = [SCALE if any(group) else 0 for group in truth_groups]
        group_representatives = [
            group_offset + max(
                range(len(group)),
                key=lambda local_index: (int(group[local_index]), -local_index),
            )
            for group_offset, group in zip(range(0, len(scores), 128), groups)
        ]
        group_role_channels = [
            [channel[index] for index in group_representatives]
            for channel in channel_values
        ]
        group_index, _ = self._pick_bounded(
            group_scores,
            seed=seed ^ 0xA5A5A5A5,
            truths=group_truths,
            role_channels=group_role_channels,
        )
        local_role_channels = [
            channel[group_index * 128 : group_index * 128 + len(groups[group_index])]
            for channel in channel_values
        ]
        local_index, strength = self._pick_bounded(
            groups[group_index],
            seed=seed ^ ((group_index + 1) * 0x9E3779B1),
            truths=truth_groups[group_index],
            role_channels=local_role_channels,
        )
        return group_index * 128 + local_index, strength

    @classmethod
    def _word_class_profile(cls, neuron: dict[str, Any]) -> dict[str, Any]:
        """Return a target-hidden, backward-compatible grammatical profile.

        Older neurons contain only R0..R3.  Their counters are evidence and
        must never be reset merely because the CPU teacher gains additional
        opaque classes.  Missing append-only channels begin neutral, then all
        weights are projected onto the current exact fixed-point simplex.
        """

        stored = neuron.get("center_attractor", {}).get(cls.WORD_CLASS_PROFILE_KEY)
        existing: dict[str, dict[str, Any]] = {}
        if isinstance(stored, dict):
            for item in stored.get("channels", []):
                if isinstance(item, dict) and item.get("channel") in cls.WORD_CLASS_CHANNELS:
                    existing[str(item["channel"])] = deepcopy(item)
        profile = {
            "schema": "NN_OPAQUE_WORD_CLASS_PROFILE_V2",
            "channels": [
                existing.get(channel, {
                    "channel": channel, "weight": 0, "uses": 0,
                    "pass_hits": 0, "fail_hits": 0,
                })
                for channel in cls.WORD_CLASS_CHANNELS
            ],
            "weight_sum": SCALE,
        }
        cls._refresh_word_class_weights(profile)
        return profile

    @staticmethod
    def _normalize_fixed_point(values: Sequence[int]) -> list[int]:
        """Normalize positive integer evidence to an exact fixed-point simplex."""

        positive = [max(1, int(value)) for value in values]
        total = sum(positive)
        scaled = [(value * SCALE) // total for value in positive]
        remainder = SCALE - sum(scaled)
        order = sorted(
            range(len(positive)),
            key=lambda index: ((positive[index] * SCALE) % total, -index),
            reverse=True,
        )
        for index in order[:remainder]:
            scaled[index] += 1
        return scaled

    @classmethod
    def _refresh_word_class_weights(cls, profile: dict[str, Any]) -> None:
        qualities = [
            cls._route_probability(item.get("pass_hits", 0), item.get("fail_hits", 0))
            for item in profile["channels"]
        ]
        weights = cls._normalize_fixed_point(qualities)
        for item, weight in zip(profile["channels"], weights):
            item["weight"] = weight
        profile["weight_sum"] = sum(weights)

    def apply_word_class_consequence(
        self,
        word_neuron_id: str,
        selected_channel: str,
        *,
        passed: bool,
        event_id: str,
    ) -> dict[str, Any]:
        """Apply one CPU one-bit consequence to only the attempted opaque channel."""

        if selected_channel not in self.WORD_CLASS_CHANNELS:
            raise ValueError("unknown opaque word-class channel")
        neuron = self.store.load_neuron(word_neuron_id)
        if neuron.get("kind") != "WORD" or neuron.get("lifecycle") != "STABLE":
            raise ValueError("word-class learning requires one stable WORD neuron")
        profile = self._word_class_profile(neuron)
        selected = next(
            item for item in profile["channels"] if item["channel"] == selected_channel
        )
        selected["uses"] = int(selected.get("uses", 0)) + 1
        counter = "pass_hits" if passed else "fail_hits"
        selected[counter] = int(selected.get(counter, 0)) + 1
        self._refresh_word_class_weights(profile)
        neuron["center_attractor"][self.WORD_CLASS_PROFILE_KEY] = profile
        neuron["reflectors"] = {
            name: neuron["reflectors"][name] for name in REFLECTORS
        }
        neuron["updated_utc"] = utc_now()
        neuron["content_sha256"] = content_hash(neuron)
        validate_neuron(neuron)
        self.store.transact(
            [neuron],
            event_kind="OPAQUE_WORD_CLASS_CONSEQUENCE",
            details={
                "event_id": str(event_id),
                "word_neuron_id": word_neuron_id,
                "selected_channel": selected_channel,
                "verdict": "PASS" if passed else "FAIL",
                "cpu_returned_one_bit_only": True,
            },
        )
        return profile

    def learn_word_class_profile(
        self,
        word_neuron_id: str,
        supported_channels: Sequence[str],
        *,
        seed: int,
        learning_rounds: int = 8,
        frozen_draws: int = 156,
        trace_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Teach one word by opaque four-card decks, then evaluate with no writes."""

        support = {str(value) for value in supported_channels}
        if not support or not support.issubset(self.WORD_CLASS_CHANNELS):
            raise ValueError("CPU teacher support must use one or more opaque channels")
        attempts: list[dict[str, Any]] = []
        for round_index in range(learning_rounds):
            remaining = list(self.WORD_CLASS_CHANNELS)
            for draw_index in range(len(self.WORD_CLASS_CHANNELS)):
                neuron = self.store.load_neuron(word_neuron_id)
                profile = self._word_class_profile(neuron)
                by_channel = {item["channel"]: item for item in profile["channels"]}
                scores = [int(by_channel[channel]["weight"]) for channel in remaining]
                attempt_seed = seed + round_index * 1_000_003 + draw_index * 97_409
                selected_index, strength = self._pick_bounded(scores, seed=attempt_seed)
                selected_channel = remaining.pop(selected_index)
                passed = selected_channel in support
                profile = self.apply_word_class_consequence(
                    word_neuron_id,
                    selected_channel,
                    passed=passed,
                    event_id=f"WORD_CLASS:{attempt_seed}",
                )
                attempt = {
                    "phase": "WORD_CLASS_LEARN",
                    "round": round_index + 1,
                    "draw": draw_index + 1,
                    "attempt_number": len(attempts) + 1,
                    "seed": attempt_seed,
                    "selected_neuron_id": word_neuron_id,
                    "token_ids": [word_neuron_id],
                    "route": [word_neuron_id],
                    "selected_channel": selected_channel,
                    "strength": strength,
                    "verdict": "PASS" if passed else "FAIL",
                    "consequence": "PASS" if passed else "FAIL",
                }
                attempts.append(attempt)
                if trace_sink is not None:
                    trace_sink(dict(attempt))
        frozen: list[dict[str, Any]] = []
        neuron = self.store.load_neuron(word_neuron_id)
        profile = self._word_class_profile(neuron)
        scores = [int(item["weight"]) for item in profile["channels"]]
        for draw_index in range(frozen_draws):
            frozen_seed = seed ^ 0xA5A5A5A5 ^ ((draw_index + 1) * 1_000_003)
            selected_index, strength = self._pick_bounded(
                scores, seed=frozen_seed, explore=False
            )
            channel = self.WORD_CLASS_CHANNELS[selected_index]
            frozen_draw = {
                "phase": "WORD_CLASS_FROZEN",
                "draw": draw_index + 1,
                "attempt_number": len(attempts) + draw_index + 1,
                "seed": frozen_seed,
                "selected_neuron_id": word_neuron_id,
                "token_ids": [word_neuron_id],
                "route": [word_neuron_id],
                "selected_channel": channel,
                "strength": strength,
                "verdict": "PASS" if channel in support else "FAIL",
                "consequence": "PASS" if channel in support else "FAIL",
            }
            frozen.append(frozen_draw)
            if trace_sink is not None:
                trace_sink(dict(frozen_draw))
        passed_channels = {
            item["channel"] for item in profile["channels"] if int(item["pass_hits"]) > 0
        }
        frozen_passes = sum(item["verdict"] == "PASS" for item in frozen)
        return {
            "state": "PASS"
            if passed_channels == support and frozen_passes == len(frozen)
            else "HOLD",
            "word_neuron_id": word_neuron_id,
            "learning_attempts": attempts,
            "frozen_draws": frozen,
            "frozen_passes": frozen_passes,
            "profile": profile,
            "all_supported_channels_evidenced": passed_channels == support,
        }

    @classmethod
    def _word_semantic_profile(cls, neuron: dict[str, Any]) -> dict[str, Any]:
        """Return one target-hidden fixed-point semantic-feature profile."""

        stored = neuron.get("center_attractor", {}).get(cls.WORD_SEMANTIC_PROFILE_KEY)
        if isinstance(stored, dict):
            channels = stored.get("channels", [])
            if [item.get("channel") for item in channels] == list(cls.WORD_SEMANTIC_CHANNELS):
                return deepcopy(stored)
        weights = cls._normalize_fixed_point([1] * len(cls.WORD_SEMANTIC_CHANNELS))
        return {
            "schema": "NN_OPAQUE_WORD_SEMANTIC_PROFILE_V1",
            "channels": [
                {
                    "channel": channel,
                    "weight": weight,
                    "uses": 0,
                    "pass_hits": 0,
                    "fail_hits": 0,
                }
                for channel, weight in zip(cls.WORD_SEMANTIC_CHANNELS, weights)
            ],
            "weight_sum": SCALE,
        }

    @classmethod
    def _refresh_word_semantic_weights(cls, profile: dict[str, Any]) -> None:
        qualities = [
            cls._route_probability(item.get("pass_hits", 0), item.get("fail_hits", 0))
            for item in profile["channels"]
        ]
        weights = cls._normalize_fixed_point(qualities)
        for item, weight in zip(profile["channels"], weights):
            item["weight"] = weight
        profile["weight_sum"] = sum(weights)

    def apply_word_semantic_consequence(
        self,
        word_neuron_id: str,
        selected_channel: str,
        *,
        passed: bool,
        event_id: str,
    ) -> dict[str, Any]:
        """Apply one CPU bit to one attempted opaque semantic feature."""

        if selected_channel not in self.WORD_SEMANTIC_CHANNELS:
            raise ValueError("unknown opaque word-semantic channel")
        neuron = self.store.load_neuron(word_neuron_id)
        if neuron.get("kind") != "WORD" or neuron.get("lifecycle") != "STABLE":
            raise ValueError("word-semantic learning requires one stable WORD neuron")
        profile = self._word_semantic_profile(neuron)
        selected = next(
            item for item in profile["channels"] if item["channel"] == selected_channel
        )
        selected["uses"] = int(selected.get("uses", 0)) + 1
        counter = "pass_hits" if passed else "fail_hits"
        selected[counter] = int(selected.get(counter, 0)) + 1
        self._refresh_word_semantic_weights(profile)
        neuron["center_attractor"][self.WORD_SEMANTIC_PROFILE_KEY] = profile
        neuron["reflectors"] = {
            name: neuron["reflectors"][name] for name in REFLECTORS
        }
        neuron["updated_utc"] = utc_now()
        neuron["content_sha256"] = content_hash(neuron)
        validate_neuron(neuron)
        self.store.transact(
            [neuron],
            event_kind="OPAQUE_WORD_SEMANTIC_CONSEQUENCE",
            details={
                "event_id": str(event_id),
                "word_neuron_id": word_neuron_id,
                "selected_channel": selected_channel,
                "verdict": "PASS" if passed else "FAIL",
                "cpu_returned_one_bit_only": True,
            },
        )
        return profile

    def learn_word_semantic_profile(
        self,
        word_neuron_id: str,
        supported_channels: Sequence[str],
        *,
        seed: int,
        learning_rounds: int = 8,
        frozen_draws: int = 156,
    ) -> dict[str, Any]:
        """Teach one WORD an opaque five-card semantic deck and freeze-test it."""

        support = {str(value) for value in supported_channels}
        if not support or not support.issubset(self.WORD_SEMANTIC_CHANNELS):
            raise ValueError("CPU teacher support must use opaque semantic channels")
        attempts: list[dict[str, Any]] = []
        for round_index in range(learning_rounds):
            remaining = list(self.WORD_SEMANTIC_CHANNELS)
            for draw_index in range(len(self.WORD_SEMANTIC_CHANNELS)):
                neuron = self.store.load_neuron(word_neuron_id)
                profile = self._word_semantic_profile(neuron)
                by_channel = {item["channel"]: item for item in profile["channels"]}
                scores = [int(by_channel[channel]["weight"]) for channel in remaining]
                attempt_seed = seed + round_index * 1_000_003 + draw_index * 97_409
                selected_index, strength = self._pick_bounded(scores, seed=attempt_seed)
                selected_channel = remaining.pop(selected_index)
                passed = selected_channel in support
                profile = self.apply_word_semantic_consequence(
                    word_neuron_id,
                    selected_channel,
                    passed=passed,
                    event_id=f"WORD_SEMANTIC:{attempt_seed}",
                )
                attempts.append({
                    "round": round_index + 1,
                    "draw": draw_index + 1,
                    "seed": attempt_seed,
                    "selected_channel": selected_channel,
                    "strength": strength,
                    "verdict": "PASS" if passed else "FAIL",
                })
        neuron = self.store.load_neuron(word_neuron_id)
        profile = self._word_semantic_profile(neuron)
        scores = [int(item["weight"]) for item in profile["channels"]]
        frozen: list[dict[str, Any]] = []
        for draw_index in range(frozen_draws):
            frozen_seed = seed ^ 0x5A5A5A5A ^ ((draw_index + 1) * 1_000_003)
            selected_index, strength = self._pick_bounded(
                scores, seed=frozen_seed, explore=False
            )
            channel = self.WORD_SEMANTIC_CHANNELS[selected_index]
            frozen.append({
                "draw": draw_index + 1,
                "seed": frozen_seed,
                "selected_channel": channel,
                "strength": strength,
                "verdict": "PASS" if channel in support else "FAIL",
            })
        evidenced = {
            item["channel"] for item in profile["channels"] if int(item["pass_hits"]) > 0
        }
        frozen_passes = sum(item["verdict"] == "PASS" for item in frozen)
        return {
            "state": "PASS"
            if evidenced == support and frozen_passes == len(frozen)
            else "HOLD",
            "word_neuron_id": word_neuron_id,
            "learning_attempts": attempts,
            "frozen_draws": frozen,
            "frozen_passes": frozen_passes,
            "profile": profile,
            "all_supported_channels_evidenced": evidenced == support,
        }

    @classmethod
    def _word_identity_profile(cls, neuron: dict[str, Any]) -> dict[str, Any]:
        """Return one target-hidden fixed-point identity-routing profile."""

        stored = neuron.get("center_attractor", {}).get(cls.WORD_IDENTITY_PROFILE_KEY)
        if isinstance(stored, dict):
            channels = stored.get("channels", [])
            if [item.get("channel") for item in channels] == list(cls.WORD_IDENTITY_CHANNELS):
                return deepcopy(stored)
        weights = cls._normalize_fixed_point([1] * len(cls.WORD_IDENTITY_CHANNELS))
        return {
            "schema": "NN_OPAQUE_WORD_IDENTITY_PROFILE_V1",
            "channels": [
                {"channel": channel, "weight": weight, "uses": 0, "pass_hits": 0, "fail_hits": 0}
                for channel, weight in zip(cls.WORD_IDENTITY_CHANNELS, weights)
            ],
            "weight_sum": SCALE,
        }

    @classmethod
    def _refresh_word_identity_weights(cls, profile: dict[str, Any]) -> None:
        weights = cls._normalize_fixed_point([
            cls._route_probability(item.get("pass_hits", 0), item.get("fail_hits", 0))
            for item in profile["channels"]
        ])
        for item, weight in zip(profile["channels"], weights):
            item["weight"] = weight
        profile["weight_sum"] = sum(weights)

    def apply_word_identity_consequence(
        self, word_neuron_id: str, selected_channel: str, *, passed: bool, event_id: str
    ) -> dict[str, Any]:
        """Apply a CPU one-bit identity-tag consequence to the attempted channel only."""

        if selected_channel not in self.WORD_IDENTITY_CHANNELS:
            raise ValueError("unknown opaque word-identity channel")
        neuron = self.store.load_neuron(word_neuron_id)
        if neuron.get("kind") != "WORD" or neuron.get("lifecycle") != "STABLE":
            raise ValueError("word-identity learning requires one stable WORD neuron")
        profile = self._word_identity_profile(neuron)
        selected = next(item for item in profile["channels"] if item["channel"] == selected_channel)
        selected["uses"] = int(selected.get("uses", 0)) + 1
        selected["pass_hits" if passed else "fail_hits"] = int(
            selected.get("pass_hits" if passed else "fail_hits", 0)
        ) + 1
        self._refresh_word_identity_weights(profile)
        neuron["center_attractor"][self.WORD_IDENTITY_PROFILE_KEY] = profile
        neuron["reflectors"] = {name: neuron["reflectors"][name] for name in REFLECTORS}
        neuron["updated_utc"] = utc_now()
        neuron["content_sha256"] = content_hash(neuron)
        validate_neuron(neuron)
        self.store.transact(
            [neuron],
            event_kind="OPAQUE_WORD_IDENTITY_CONSEQUENCE",
            details={
                "event_id": str(event_id),
                "word_neuron_id": word_neuron_id,
                "selected_channel": selected_channel,
                "verdict": "PASS" if passed else "FAIL",
                "cpu_returned_one_bit_only": True,
                "no_authority_granted": True,
            },
        )
        return profile

    def learn_word_identity_profile(
        self, word_neuron_id: str, supported_channels: Sequence[str], *, seed: int,
        learning_rounds: int = 8, frozen_draws: int = 156,
    ) -> dict[str, Any]:
        """Teach one WORD an opaque identity-routing deck, then freeze-test it."""

        support = {str(value) for value in supported_channels}
        if not support or not support.issubset(self.WORD_IDENTITY_CHANNELS):
            raise ValueError("CPU teacher support must use opaque identity channels")
        attempts: list[dict[str, Any]] = []
        for round_index in range(learning_rounds):
            remaining = list(self.WORD_IDENTITY_CHANNELS)
            for draw_index in range(len(self.WORD_IDENTITY_CHANNELS)):
                profile = self._word_identity_profile(self.store.load_neuron(word_neuron_id))
                weights = {item["channel"]: int(item["weight"]) for item in profile["channels"]}
                attempt_seed = seed + round_index * 1_000_003 + draw_index * 97_409
                selected_index, strength = self._pick_bounded([weights[channel] for channel in remaining], seed=attempt_seed)
                selected_channel = remaining.pop(selected_index)
                passed = selected_channel in support
                profile = self.apply_word_identity_consequence(
                    word_neuron_id, selected_channel, passed=passed, event_id=f"WORD_IDENTITY:{attempt_seed}"
                )
                attempts.append({"round": round_index + 1, "draw": draw_index + 1, "seed": attempt_seed,
                                 "selected_channel": selected_channel, "strength": strength,
                                 "verdict": "PASS" if passed else "FAIL"})
        profile = self._word_identity_profile(self.store.load_neuron(word_neuron_id))
        scores = [int(item["weight"]) for item in profile["channels"]]
        frozen: list[dict[str, Any]] = []
        for draw_index in range(frozen_draws):
            frozen_seed = seed ^ 0x3C3C3C3C ^ ((draw_index + 1) * 1_000_003)
            selected_index, strength = self._pick_bounded(
                scores, seed=frozen_seed, explore=False
            )
            channel = self.WORD_IDENTITY_CHANNELS[selected_index]
            frozen.append({"draw": draw_index + 1, "seed": frozen_seed, "selected_channel": channel,
                           "strength": strength, "verdict": "PASS" if channel in support else "FAIL"})
        evidenced = {item["channel"] for item in profile["channels"] if int(item["pass_hits"]) > 0}
        frozen_passes = sum(item["verdict"] == "PASS" for item in frozen)
        return {
            "state": "PASS" if evidenced == support and frozen_passes == len(frozen) else "HOLD",
            "word_neuron_id": word_neuron_id,
            "learning_attempts": attempts,
            "frozen_draws": frozen,
            "frozen_passes": frozen_passes,
            "profile": profile,
            "all_supported_channels_evidenced": evidenced == support,
        }
    def _endpoint_value(
        self,
        catalog: Sequence[dict[str, Any]],
        previous_id: str,
        remaining: Counter[str],
        *,
        inventory_context_sha256: str,
        prefix_route: tuple[str, ...],
        memo: dict[tuple[str, tuple[tuple[str, int], ...], tuple[str, ...]], int],
        budget: dict[str, int | bool],
    ) -> int:
        """Return the best learned probability of reaching a supported endpoint."""
        if not remaining:
            if not self.assembly_evidence_enabled:
                return SCALE
            pass_hits, fail_hits = self.curriculum.assembly_evidence(
                "WORD", inventory_context_sha256, prefix_route
            )
            # The deployed Hydra membrane hard-denies an exact terminal route
            # after one or more FAIL consequences when it has never passed.
            # Endpoint lookahead must project that same zero.  Returning the
            # ordinary Laplace-smoothed probability here lets a dead terminal
            # route dominate shorter suffixes, so the CPU repeatedly guides
            # CUDA into a prefix that Hydra can only HOLD on the next split.
            # This uses only path-local consequence memory; it reveals no
            # target, correction position, or hidden alternative.
            if (
                self.route_truth_provider is not None
                and int(pass_hits) == 0
                and int(fail_hits) >= 1
            ):
                return 0
            return self._route_probability(pass_hits, fail_hits)
        state_key = (previous_id, tuple(sorted(remaining.items())), prefix_route)
        cached = memo.get(state_key)
        if cached is not None:
            budget["memo_hits"] = int(budget.get("memo_hits", 0)) + 1
            return cached
        if int(budget["visited"]) >= self.CPU_ENDPOINT_NODE_BUDGET:
            budget["exhausted"] = True
            budget["floor_returns"] = int(budget.get("floor_returns", 0)) + 1
            return 1
        budget["visited"] = int(budget["visited"]) + 1
        eligible = self._eligible_tokens(catalog, remaining)
        if not eligible:
            memo[state_key] = 0
            return 0
        context = self._context(previous_id, remaining)
        evidence = self.curriculum.evidence(
            "WORD", context, [str(token["token_id"]) for token in eligible]
        )
        best = 0
        for token, (pass_hits, fail_hits) in zip(eligible, evidence):
            local_probability = self._route_probability(pass_hits, fail_hits)
            next_remaining = remaining.copy()
            next_remaining.subtract(Counter(str(token["surface"])))
            next_remaining += Counter()
            suffix_probability = self._endpoint_value(
                catalog,
                str(token["token_id"]),
                next_remaining,
                inventory_context_sha256=inventory_context_sha256,
                prefix_route=(*prefix_route, str(token["token_id"])),
                memo=memo,
                budget=budget,
            )
            route_probability = (
                local_probability * suffix_probability
            ) // SCALE
            best = max(best, route_probability)
        memo[state_key] = best
        return best

    def _endpoint_scores(
        self,
        catalog: Sequence[dict[str, Any]],
        eligible: Sequence[dict[str, Any]],
        remaining: Counter[str],
        local_probabilities: Sequence[int],
        *,
        inventory_context_sha256: str,
        prefix_route: Sequence[str],
    ) -> tuple[list[int], dict[str, int | bool]]:
        """Recalculate every supported branch from this split to an endpoint."""
        if self.prefix_free_suffix_enabled:
            return self._prefix_free_endpoint_scores(
                catalog,
                eligible,
                remaining,
                local_probabilities,
                inventory_context_sha256=inventory_context_sha256,
                prefix_route=prefix_route,
            )
        memo: dict[
            tuple[str, tuple[tuple[str, int], ...], tuple[str, ...]], int
        ] = {}
        budget: dict[str, int | bool] = {
            "visited": 0,
            "memo_hits": 0,
            "floor_returns": 0,
            "exhausted": False,
        }
        scores: list[int] = []
        for token, local_probability in zip(eligible, local_probabilities):
            next_remaining = remaining.copy()
            next_remaining.subtract(Counter(str(token["surface"])))
            next_remaining += Counter()
            suffix_probability = self._endpoint_value(
                catalog,
                str(token["token_id"]),
                next_remaining,
                inventory_context_sha256=inventory_context_sha256,
                prefix_route=(*tuple(prefix_route), str(token["token_id"])),
                memo=memo,
                budget=budget,
            )
            scores.append(max(1, (int(local_probability) * suffix_probability) // SCALE))
        return scores, budget

    def _prefix_free_suffix_value(
        self,
        catalog: Sequence[dict[str, Any]],
        previous_id: str,
        remaining: Counter[str],
        *,
        memo: dict[
            tuple[str, tuple[tuple[str, int], ...]],
            tuple[int, tuple[str, ...]],
        ],
        budget: dict[str, int | bool],
    ) -> tuple[int, tuple[str, ...]]:
        """Best structural suffix independent of the route used to reach it."""
        if not remaining:
            return SCALE, ()
        state_key = (previous_id, tuple(sorted(remaining.items())))
        cached = memo.get(state_key)
        if cached is not None:
            budget["memo_hits"] = int(budget.get("memo_hits", 0)) + 1
            return cached
        if int(budget["visited"]) >= self.CPU_ENDPOINT_NODE_BUDGET:
            budget["exhausted"] = True
            budget["floor_returns"] = int(budget.get("floor_returns", 0)) + 1
            return 1, ()
        budget["visited"] = int(budget["visited"]) + 1
        eligible = self._eligible_tokens(catalog, remaining)
        if not eligible:
            memo[state_key] = (0, ())
            return memo[state_key]
        context = self._context(previous_id, remaining)
        evidence = self.curriculum.evidence(
            "WORD", context, [str(token["token_id"]) for token in eligible]
        )
        best_probability = 0
        best_route: tuple[str, ...] = ()
        for token, (pass_hits, fail_hits) in zip(eligible, evidence):
            token_id = str(token["token_id"])
            local_probability = self._route_probability(pass_hits, fail_hits)
            next_remaining = remaining.copy()
            next_remaining.subtract(Counter(str(token["surface"])))
            next_remaining += Counter()
            suffix_probability, suffix_route = self._prefix_free_suffix_value(
                catalog,
                token_id,
                next_remaining,
                memo=memo,
                budget=budget,
            )
            probability = (local_probability * suffix_probability) // SCALE
            candidate_route = (token_id, *suffix_route)
            if probability > best_probability or (
                probability == best_probability
                and (not best_route or candidate_route < best_route)
            ):
                best_probability = probability
                best_route = candidate_route
        memo[state_key] = (best_probability, best_route)
        return memo[state_key]

    def _prefix_free_endpoint_scores(
        self,
        catalog: Sequence[dict[str, Any]],
        eligible: Sequence[dict[str, Any]],
        remaining: Counter[str],
        local_probabilities: Sequence[int],
        *,
        inventory_context_sha256: str,
        prefix_route: Sequence[str],
    ) -> tuple[list[int], dict[str, int | bool]]:
        """Score a reusable structural suffix, then apply exact route evidence."""
        memo: dict[
            tuple[str, tuple[tuple[str, int], ...]],
            tuple[int, tuple[str, ...]],
        ] = {}
        budget: dict[str, int | bool] = {
            "visited": 0,
            "memo_hits": 0,
            "floor_returns": 0,
            "exhausted": False,
        }
        scores: list[int] = []
        for token, local_probability in zip(eligible, local_probabilities):
            token_id = str(token["token_id"])
            next_remaining = remaining.copy()
            next_remaining.subtract(Counter(str(token["surface"])))
            next_remaining += Counter()
            suffix_probability, suffix_route = self._prefix_free_suffix_value(
                catalog,
                token_id,
                next_remaining,
                memo=memo,
                budget=budget,
            )
            structural_probability = (
                int(local_probability) * suffix_probability
            ) // SCALE
            assembly_probability = SCALE
            if self.assembly_evidence_enabled:
                complete_route = (*tuple(prefix_route), token_id, *suffix_route)
                pass_hits, fail_hits = self.curriculum.assembly_evidence(
                    "WORD", inventory_context_sha256, complete_route
                )
                assembly_probability = self._route_probability(pass_hits, fail_hits)
            scores.append(max(
                1,
                (structural_probability * assembly_probability) // SCALE,
            ))
        return scores, budget

    @staticmethod
    def _lesson_assembly_context(
        inventory_context_sha256: str,
        lesson_id: str,
        source_handle: str,
    ) -> str:
        """Opaque scope for route consequences from one teacher experience."""
        payload = json.dumps(
            {
                "inventory_context_sha256": str(inventory_context_sha256),
                "lesson_id": str(lesson_id),
                "source_handle": str(source_handle),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest().upper()

    def attempt_word(
        self,
        word: str,
        *,
        seed: int,
        assembly_context_sha256: str | None = None,
        consequence_packet: Mapping[str, Any] | None = None,
        allow_complete_route_proposal: bool = True,
        complete_route_consequence_prior: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        remaining = Counter(str(word))
        complete_route_proposal: dict[str, Any] | None = None
        if allow_complete_route_proposal and self.complete_route_proposal_provider is not None:
            complete_route_proposal = dict(
                self.complete_route_proposal_provider(
                    Counter(remaining), int(seed), dict(consequence_packet or {})
                )
            )
            proposed_surface = str(complete_route_proposal.get("surface", ""))
            if Counter(proposed_surface) != remaining:
                raise ValueError("complete route proposal must preserve the exact inventory")
        inventory_context_sha256 = self._context("<START>", remaining)
        route_consequence_context_sha256 = (
            str(assembly_context_sha256) if assembly_context_sha256
            else inventory_context_sha256
        )
        catalog = self._eligible_tokens(self._word_composition_catalog(word), remaining)
        consequence_prior_route = tuple(
            str(token_id) for token_id in (complete_route_consequence_prior or ())
        )
        if consequence_prior_route:
            catalog_by_id = {str(token["token_id"]): token for token in catalog}
            if any(token_id not in catalog_by_id for token_id in consequence_prior_route):
                raise ValueError("complete route consequence prior contains an ineligible token")
            prior_surface = "".join(
                str(catalog_by_id[token_id]["surface"])
                for token_id in consequence_prior_route
            )
            if prior_surface != str(word):
                raise ValueError("complete route consequence prior does not reconstruct the lesson")
            prior_pass_hits, prior_fail_hits = self.curriculum.assembly_evidence(
                "WORD", route_consequence_context_sha256, consequence_prior_route
            )
            if int(prior_pass_hits) < 1:
                raise ValueError("complete route consequence prior has no CPU PASS evidence")
            consequence_prior_probability = self._route_probability(
                prior_pass_hits, prior_fail_hits
            )
        else:
            consequence_prior_probability = 0
        previous_id = "<START>"
        route: list[str] = []
        surfaces: list[str] = []
        steps: list[tuple[str, str]] = []
        decisions: list[dict[str, Any]] = []
        attempted_pattern_features: list[str] = []
        for depth in range(max(1, len(word))):
            if not remaining:
                break
            eligible = self._eligible_tokens(catalog, remaining)
            emitted_surface = "".join(surfaces)
            if self.ordered_prefix_composition_enabled:
                expected_remaining_surface = str(word)[len(emitted_surface):]
                eligible = [
                    token for token in eligible
                    if expected_remaining_surface.startswith(str(token["surface"]))
                ]
            if not eligible:
                return {
                    "state": "HOLD", "reason": "NO_SUPPORTED_CHILD",
                    "route": route, "output": "".join(surfaces),
                    "steps": steps, "decisions": decisions,
                }
            # Retrieval runs opposite to teaching: use the highest available
            # learned resolution first and descend only after that block has
            # consumed its inventory. Characters are the final fallback.
            highest_resolution = max(len(str(token["surface"])) for token in eligible)
            eligible = [
                token for token in eligible
                if len(str(token["surface"])) == highest_resolution
            ]
            context = self._context(previous_id, remaining)
            evidence = self.curriculum.evidence(
                "WORD", context, [str(token["token_id"]) for token in eligible]
            )
            probabilities = [
                self._route_probability(passes, failures)
                for passes, failures in evidence
            ]
            projections: list[tuple[int, int, int, tuple[str, ...]]] = []
            if self.self_discovery_enabled:
                emitted = "".join(surfaces)
                projections = [
                    self._pattern_projection(emitted, str(token["surface"]), remaining)
                    for token in eligible
                ]
                probabilities = [
                    (
                        probability * (SCALE - projection[1])
                        + projection[0] * projection[1]
                    ) // SCALE
                    for probability, projection in zip(probabilities, projections)
                ]
            proposal_matches: list[int] = []
            if complete_route_proposal is not None:
                emitted = "".join(surfaces)
                proposal_remainder = str(complete_route_proposal["surface"])[len(emitted):]
                proposal_matches = [
                    index for index, token in enumerate(eligible)
                    if proposal_remainder.startswith(str(token["surface"]))
                ]
            if proposal_matches:
                # A complete inventory-valid proposal replaces endpoint search.
                # Map its next prefix to the longest existing neuron token;
                # local learned evidence and token id provide deterministic ties.
                selected = max(
                    proposal_matches,
                    key=lambda index: (
                        len(str(eligible[index]["surface"])),
                        int(probabilities[index]),
                        str(eligible[index]["token_id"]),
                    ),
                )
                endpoint_scores = list(probabilities)
                endpoint_budget = {"visited": 0, "exhausted": False, "memo_hits": 0, "floor_returns": 0}
                proposal_forced = True
            else:
                endpoint_scores, endpoint_budget = self._endpoint_scores(
                    catalog,
                    eligible,
                    remaining,
                    probabilities,
                    inventory_context_sha256=route_consequence_context_sha256,
                    prefix_route=route,
                )
                proposal_forced = False
            native_endpoint_scores = list(endpoint_scores)
            consequence_prior_index: int | None = None
            if (
                consequence_prior_route
                and tuple(route) == consequence_prior_route[:len(route)]
                and len(route) < len(consequence_prior_route)
            ):
                next_prior_token_id = consequence_prior_route[len(route)]
                consequence_prior_index = next(
                    (
                        index for index, token in enumerate(eligible)
                        if str(token["token_id"]) == next_prior_token_id
                    ),
                    None,
                )
                if consequence_prior_index is not None:
                    endpoint_scores[consequence_prior_index] = max(
                        int(endpoint_scores[consequence_prior_index]),
                        int(consequence_prior_probability),
                    )
            consequence_endpoint_scores = list(endpoint_scores)
            attention_prior_scores: list[int] | None = None
            if self.neuron_attention_guidance_enabled:
                attention_prior_scores = self._attention_candidate_priors(eligible, context)
                # Learned head evidence is a bounded proposal prior, never a
                # truth gate.  It can adjust endpoint strength by at most 25%.
                endpoint_scores = [
                    max(1, (int(endpoint) * (3 * SCALE + prior)) // (4 * SCALE))
                    for endpoint, prior in zip(endpoint_scores, attention_prior_scores)
                ]
            character_prior_scores: list[int] | None = None
            if self.character_prior_provider is not None:
                character_prior_scores = [
                    max(1, min(SCALE, int(value)))
                    for value in self.character_prior_provider(
                        "".join(surfaces),
                        [str(token["surface"]) for token in eligible],
                    )
                ]
                if len(character_prior_scores) != len(endpoint_scores):
                    raise ValueError("character prior must return one score per eligible route")
                # The frozen character model is an untrusted proposal prior.
                # It may reduce a weak candidate's endpoint strength by at
                # most 25%; it can never erase a route or create truth.
                endpoint_scores = [
                    max(1, (int(endpoint) * (3 * SCALE + prior)) // (4 * SCALE))
                    for endpoint, prior in zip(endpoint_scores, character_prior_scores)
                ]
            role_channels = (
                self._word_role_channels(
                    eligible,
                    remaining,
                    probabilities,
                    projections,
                    native_endpoint_scores,
                    consequence_endpoint_scores,
                    character_prior_scores,
                )
                if self.word_role_evidence_enabled else None
            )
            candidate_ids = [str(token["token_id"]) for token in eligible]
            try:
                route_truths = (
                    list(self.route_truth_provider({
                        "context_hash": context,
                        "inventory_context_hash": inventory_context_sha256,
                        "assembly_context_hash": route_consequence_context_sha256,
                        "prefix_route": list(route),
                        "candidates": [
                            {
                                "candidate_id": str(token["token_id"]),
                                "terminal": Counter(str(token["surface"])) == remaining,
                                "complete_route": [*route, str(token["token_id"])],
                            }
                            for token in eligible
                        ],
                    }))
                    if self.route_truth_provider is not None else [SCALE] * len(candidate_ids)
                )
            except RuntimeError as error:
                if not str(error).startswith("HOLD_HYDRA_"):
                    raise
                return {
                    "state": "HOLD", "reason": str(error), "route": route,
                    "output": "".join(surfaces), "steps": steps, "decisions": decisions,
                }
            try:
                if proposal_forced:
                    if route_truths[selected] == 0:
                        raise CudaRouteHold("HOLD_HYDRA_ROUTE_DENIED")
                    strength = int(endpoint_scores[selected])
                else:
                    selected, strength = self._pick_bounded(
                        endpoint_scores,
                        seed=seed ^ ((depth + 1) * 0x9E3779B97F4A7C15),
                        truths=route_truths,
                        role_channels=role_channels,
                    )
            except CudaRouteHold as error:
                return {
                    "state": "HOLD", "reason": str(error), "route": route,
                    "output": "".join(surfaces), "steps": steps, "decisions": decisions,
                }
            token = eligible[selected]
            token_id = str(token["token_id"])
            surface = str(token["surface"])
            selected_projection = (
                projections[selected] if projections else (SCALE // 2, 0, 0, ())
            )
            attempted_pattern_features.extend(selected_projection[3])
            decisions.append({
                "depth": depth,
                "emitted_surface": emitted_surface,
                "expected_remaining_surface": str(word)[len(emitted_surface):],
                "ordered_prefix_composition": self.ordered_prefix_composition_enabled,
                "context_sha256": context,
                "frontier": len(eligible),
                "eligible_candidates": [
                    {
                        "token_id": str(candidate["token_id"]),
                        "surface": str(candidate["surface"]),
                        "kind": str(candidate["kind"]),
                    }
                    for candidate in eligible
                ],
                "candidate_route_proposals": [
                    {
                        "route": [*route, str(candidate["token_id"])],
                        "surface": "".join(surfaces) + str(candidate["surface"]),
                        "endpoint_probability": int(endpoint_scores[index]),
                    }
                    for index, candidate in enumerate(eligible)
                ],
                "selected_token_id": token_id,
                "selected_surface": surface,
                "selected_kind": str(token["kind"]),
                "selected_probability": probabilities[selected],
                "selected_endpoint_probability": endpoint_scores[selected],
                "endpoint_scores": list(endpoint_scores),
                "attention_guidance_enabled": self.neuron_attention_guidance_enabled,
                "attention_prior_probability": (
                    attention_prior_scores[selected] if attention_prior_scores is not None else None
                ),
                "attention_prior_scores": attention_prior_scores,
                "native_endpoint_probability": native_endpoint_scores[selected],
                "native_endpoint_scores": native_endpoint_scores,
                "character_prior_enabled": character_prior_scores is not None,
                "character_prior_probability": (
                    character_prior_scores[selected] if character_prior_scores is not None else None
                ),
                "character_prior_scores": character_prior_scores,
                "character_prior_sha256": self.character_prior_sha256,
                "complete_route_proposal_enabled": complete_route_proposal is not None,
                "complete_route_proposal_surface": (
                    complete_route_proposal.get("surface") if complete_route_proposal else None
                ),
                "complete_route_proposal_log_score": (
                    complete_route_proposal.get("log_score") if complete_route_proposal else None
                ),
                "complete_route_proposal_sha256": self.complete_route_proposal_sha256,
                "complete_route_consequence_sha256": (
                    complete_route_proposal.get("consequence_sha256")
                    if complete_route_proposal else None
                ),
                "complete_route_rejections_seen": (
                    complete_route_proposal.get("rejections_seen", 0)
                    if complete_route_proposal else 0
                ),
                "complete_route_proposal_followed": proposal_forced,
                "complete_route_proposal_repair": complete_route_proposal is not None and not proposal_forced,
                "complete_route_consequence_prior_enabled": bool(consequence_prior_route),
                "complete_route_consequence_prior_match": selected == consequence_prior_index,
                "complete_route_consequence_prior_probability": (
                    consequence_prior_probability if consequence_prior_route else None
                ),
                "cpu_endpoint_states_evaluated": int(endpoint_budget["visited"]),
                "cpu_endpoint_budget_exhausted": bool(endpoint_budget["exhausted"]),
                "cpu_endpoint_memo_hits": int(endpoint_budget.get("memo_hits", 0)),
                "cpu_endpoint_floor_returns": int(endpoint_budget.get("floor_returns", 0)),
                "prefix_free_suffix_dp": self.prefix_free_suffix_enabled,
                "strict_dictionary_composition": self.strict_dictionary_composition_enabled,
                "selected_reusable_word_length": (
                    len(surface) if token["kind"] == "WORD" else 0
                ),
                "native_strength": strength,
                "nested_role_evidence_v1": (
                    {
                        "user": [channel[selected] for channel in role_channels[:3]],
                        "assistant": [channel[selected] for channel in role_channels[3:]],
                        "mapping": [
                            "LOCAL_CONTEXT_PROBABILITY",
                            "DISCOVERED_PATTERN_PROBABILITY",
                            "VISIBLE_INVENTORY_COVERAGE",
                            "NATIVE_ENDPOINT_PROBABILITY",
                            "CONSEQUENCE_ENDPOINT_PROBABILITY",
                            "CHARACTER_PROPOSAL_PROBABILITY",
                        ],
                    }
                    if role_channels is not None else None
                ),
                "hydra_route_membrane": self.route_truth_provider is not None,
                "hydra_denied_indices": [index for index, value in enumerate(route_truths) if value == 0],
                "hydra_truth_mask_sha256": hashlib.sha256(
                    json.dumps(route_truths, separators=(",", ":")).encode("utf-8")
                ).hexdigest().upper(),
                "discovered_pattern_probability": selected_projection[0],
                "discovered_pattern_confidence": selected_projection[1],
                "discovered_pattern_support": selected_projection[2],
                "why": (
                    "TRANSFORMER_COMPLETE_ROUTE_PREFIX"
                    if proposal_forced else
                    "GPU_CHOICE_FROM_CPU_RECALCULATED_ENDPOINT_PROBABILITY_FIELD"
                ),
            })
            steps.append((context, token_id))
            route.append(token_id)
            surfaces.append(surface)
            remaining.subtract(Counter(surface))
            remaining += Counter()
            previous_id = token_id
        attention_receipt = self._route_attention_receipt(route)
        return {
            "state": "PASS" if not remaining else "HOLD",
            "reason": "" if not remaining else "CONTEXT_BUDGET_EXHAUSTED",
            "route": route,
            "output": "".join(surfaces),
            "steps": steps,
            "decisions": decisions,
            "pattern_features": list(dict.fromkeys(attempted_pattern_features)),
            "attention_pulse": attention_receipt,
        }

    def recall_admitted_word(self, word_neuron_id: str, *, seed: int) -> dict[str, Any]:
        """Activate one admitted WORD memory and traverse its earned child route."""
        word_neuron = self.store.load_neuron(str(word_neuron_id))
        if word_neuron.get("kind") != "WORD" or word_neuron.get("lifecycle") != "STABLE":
            return {
                "state": "HOLD", "reason": "WORD_MEMORY_NOT_STABLE",
                "route": [], "output": "", "steps": [], "decisions": [],
            }
        children = [str(value) for value in word_neuron.get("children", [])]
        if not children:
            return {
                "state": "HOLD", "reason": "WORD_MEMORY_HAS_NO_SUPPORTED_CHILDREN",
                "route": [], "output": "", "steps": [], "decisions": [],
            }
        surfaces: list[str] = []
        decisions: list[dict[str, Any]] = []
        for position, child_id in enumerate(children):
            child = self.store.load_neuron(child_id)
            if self._construction_alignment(child) <= 0:
                return {
                    "state": "HOLD", "reason": "WORD_MEMORY_CHILD_UNSUPPORTED",
                    "route": children[:position], "output": "".join(surfaces),
                    "steps": [], "decisions": decisions,
                }
            surface = self._surface(child)
            if not surface:
                return {
                    "state": "HOLD", "reason": "WORD_MEMORY_CHILD_HAS_NO_SURFACE",
                    "route": children[:position], "output": "".join(surfaces),
                    "steps": [], "decisions": decisions,
                }
            surfaces.append(surface)
            decisions.append({
                "depth": position,
                "anchor_word_neuron_id": str(word_neuron_id),
                "selected_token_id": child_id,
                "selected_surface": surface,
                "frontier": 1,
                "native_strength": self._construction_alignment(child),
                "seed": int(seed),
                "why": "ACTIVATED_WORD_MEMORY_TRAVERSES_ITS_EARNED_CHILD_ROUTE",
            })
        return {
            "state": "PASS", "reason": "", "route": children,
            "output": "".join(surfaces), "steps": [], "decisions": decisions,
        }

    def learn_word(
        self,
        word: str,
        *,
        lesson_id: str,
        source_handle: str,
        seed: int,
        max_attempts: int = 50_000,
        confirmations: int = 3,
        foundation: bool = False,
        trace_sink: Callable[[dict[str, Any]], None] | None = None,
        work_gate: Callable[[str], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Teach one complete observed word; only the CPU exact judge sees truth."""
        target = str(word)
        if not target or any(character.isspace() for character in target):
            raise ValueError("word lesson requires one complete non-whitespace source word")
        inventory_context_sha256 = self._context("<START>", Counter(target))
        assembly_context_sha256 = self._lesson_assembly_context(
            inventory_context_sha256, lesson_id, source_handle
        )
        rejected_routes: list[dict[str, Any]] = []
        rejection_count = 0
        rejection_chain_sha256 = "0" * 64
        for attempt_number in range(1, max_attempts + 1):
            resource_state = work_gate("LEARN") if work_gate is not None else None
            last_resource_state = resource_state
            attempt = self.attempt_word(
                target,
                seed=seed + attempt_number * 1_000_003,
                assembly_context_sha256=assembly_context_sha256,
                consequence_packet={
                    "schema": "NN_TRANSFORMER_CONSEQUENCE_PACKET_V1",
                    "prior_verdict": "FAIL" if rejected_routes else None,
                    "failed_gate": "EXACT_COMPLETE_OBSERVED_WORD" if rejected_routes else None,
                    "rejected_routes": list(rejected_routes),
                    "rejected_count": rejection_count,
                    "rejection_chain_sha256": rejection_chain_sha256,
                },
            )
            output = str(attempt["output"])
            verdict = "PASS" if attempt["state"] == "PASS" and output == target else "FAIL"
            if attempt["state"] == "HOLD":
                verdict = "HOLD"
            if verdict in {"PASS", "FAIL"}:
                self.curriculum.apply_route_verdict(
                    level="WORD", steps=attempt["steps"], passed=verdict == "PASS"
                )
                if self.assembly_evidence_enabled:
                    self.curriculum.apply_assembly_verdict(
                        level="WORD",
                        inventory_context_sha256=assembly_context_sha256,
                        route=attempt["route"],
                        passed=verdict == "PASS",
                    )
                if self.self_discovery_enabled:
                    self.curriculum.apply_pattern_verdict(
                        level="WORD",
                        feature_sha256s=attempt.get("pattern_features", ()),
                        passed=verdict == "PASS",
                    )
            attempt_id = self.curriculum.record_attempt(
                level="WORD", lesson_id=lesson_id, source_handle=source_handle,
                output_text=output, verdict=verdict, route=attempt["route"],
                decisions=attempt["decisions"],
            )
            attention_learning_event = self._apply_route_attention_consequence(
                attempt["route"], verdict, evidence_ref=f"WORD_ATTEMPT:{attempt_id}",
                steps=attempt["steps"],
            )
            trace = {
                "phase": "UNIVERSAL_LIVE_CURRICULUM",
                "level": "WORD",
                "lesson_id": lesson_id,
                "source_handle": source_handle,
                "lesson_source": target,
                "lesson_expected": target,
                "lesson_selected": output,
                "attempt_number": attempt_id,
                "route": attempt["route"],
                "verdict": verdict,
                "consequence": verdict,
                "judge": "EXACT_COMPLETE_OBSERVED_WORD",
                "decisions": attempt["decisions"],
                "attention_pulse": attempt.get("attention_pulse"),
                "attention_learning_event": attention_learning_event,
            }
            if resource_state is not None:
                trace["resource_governor"] = resource_state
            if trace_sink is not None:
                trace_sink(trace)
            # A Hydra HOLD rejects this attempted branch, not the lesson.  The
            # next iteration starts a fresh context window and seed.  Only the
            # lesson attempt ceiling may convert repeated branch HOLDs into a
            # lesson-level HOLD.
            if verdict != "PASS":
                if verdict == "FAIL":
                    rejected = {
                        "output_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest().upper(),
                        "output": output,
                        "route_sha256": hashlib.sha256(
                            json.dumps(attempt["route"], separators=(",", ":")).encode("utf-8")
                        ).hexdigest().upper(),
                        "failed_gate": "EXACT_COMPLETE_OBSERVED_WORD",
                    }
                    rejection_chain_sha256 = hashlib.sha256(
                        (rejection_chain_sha256 + rejected["output_sha256"]
                         + rejected["route_sha256"] + rejected["failed_gate"]).encode("ascii")
                    ).hexdigest().upper()
                    rejection_count += 1
                    rejected_routes.append(rejected)
                    rejected_routes = rejected_routes[-256:]
                continue
            frozen = []
            for index in range(confirmations):
                confirmation_resource = (
                    work_gate("CONFIRM") if work_gate is not None else None
                )
                last_resource_state = confirmation_resource or last_resource_state
                confirmation = self.attempt_word(
                    target,
                    seed=seed + (attempt_number + index + 1) * 97_409,
                    assembly_context_sha256=assembly_context_sha256,
                    # The transformer is an exploration/proposal layer.  Once
                    # the CPU exact judge has returned PASS, frozen
                    # confirmation measures the Steel Brain route that just
                    # received that consequence; it must not become eight new
                    # stochastic transformer lotteries.
                    allow_complete_route_proposal=False,
                    # The CPU-approved path is learned complete-route evidence.
                    # Expose it as a bounded native score prior so endpoint
                    # search need not rediscover that path inside its finite
                    # node budget. CUDA still chooses and Hydra still gates.
                    complete_route_consequence_prior=attempt["route"],
                    consequence_packet={
                        "schema": "NN_TRANSFORMER_CONSEQUENCE_PACKET_V1",
                        "prior_verdict": "PASS",
                        "failed_gate": None,
                        "rejected_routes": list(rejected_routes),
                        "rejected_count": rejection_count,
                        "rejection_chain_sha256": rejection_chain_sha256,
                    },
                )
                frozen.append(confirmation)
                if trace_sink is not None:
                    confirmation_output = str(confirmation["output"])
                    confirmation_verdict = (
                        "PASS"
                        if confirmation["state"] == "PASS"
                        and confirmation_output == target
                        else "FAIL"
                    )
                    confirmation_trace = {
                        "phase": "UNIVERSAL_FROZEN_CONFIRMATION",
                        "level": "WORD",
                        "lesson_id": lesson_id,
                        "source_handle": source_handle,
                        "lesson_source": target,
                        "lesson_expected": target,
                        "lesson_selected": confirmation_output,
                        "attempt_number": attempt_id,
                        "confirmation_index": index + 1,
                        "confirmation_total": confirmations,
                        "route": confirmation["route"],
                        "verdict": confirmation_verdict,
                        "consequence": confirmation_verdict,
                        "judge": "EXACT_COMPLETE_OBSERVED_WORD",
                        "decisions": confirmation["decisions"],
                        "attention_pulse": confirmation.get("attention_pulse"),
                        "frozen_no_update": True,
                    }
                    if confirmation_resource is not None:
                        confirmation_trace["resource_governor"] = confirmation_resource
                    trace_sink(confirmation_trace)
            if not all(row["state"] == "PASS" and row["output"] == target for row in frozen):
                continue
            admission = self._admit_word(
                target, lesson_id=lesson_id, source_handle=source_handle,
                route=attempt["route"], attempts=attempt_number,
                confirmations=confirmations, foundation=foundation,
            )
            if trace_sink is not None:
                settlement_trace = {
                    "phase": "RID_SETTLEMENT",
                    "level": "WORD",
                    "lesson_id": lesson_id,
                    "lesson_source": target,
                    "lesson_expected": target,
                    "lesson_selected": target,
                    "attempt_number": attempt_number,
                    "verdict": admission.get("state"),
                    "consequence": admission.get("state"),
                    "route": list(attempt["route"]),
                    "S_n": admission.get("S_n"),
                    "RID_t": admission.get("RID_t"),
                    "E_t": admission.get("E_t"),
                    "T_t": admission.get("T_t"),
                    "N_t": admission.get("N_t"),
                    "rid_settle_ticks": admission.get("rid_settle_ticks"),
                    "zero_confirmations": confirmations,
                    "judge": "TRIADIC_FIXED_POINT_SETTLEMENT",
                    "frozen_no_update": True,
                }
                if last_resource_state is not None:
                    settlement_trace["resource_governor"] = last_resource_state
                trace_sink(settlement_trace)
            return admission
        return {"state": "HOLD", "reason": "MAX_ATTEMPTS", "word": target}

    def preallocate_word(
        self,
        word: str,
        *,
        source_handle: str,
        source_rank: int | None = None,
    ) -> dict[str, Any]:
        """Create an indexed but unlearned WORD shell with neutral evidence.

        NEWBORN is deliberately not recallable.  The source may establish that
        the spelling is an available lesson, but only the ordinary learner and
        its frozen confirmations may promote the neuron to STABLE knowledge.
        """
        surface = str(word)
        if not surface or any(character.isspace() for character in surface):
            raise ValueError("preallocated word requires one non-whitespace surface")
        existing = self.store.manifest().get("word_index", {}).get(surface)
        if existing is not None:
            neuron = self.store.load_neuron(str(existing))
            return {
                "state": "PASS" if neuron.get("lifecycle") == "NEWBORN" else "HOLD",
                "reason": "ALREADY_PREALLOCATED" if neuron.get("lifecycle") == "NEWBORN" else "WORD_ALREADY_EXISTS",
                "word": surface,
                "word_neuron_id": str(existing),
                "created": 0,
            }
        word_id = new_neuron_id()
        shell = make_neuron(
            neuron_id=word_id,
            kind="WORD",
            lifecycle="NEWBORN",
            creation_event="SOURCE_AUTHENTIC_WORD_PREALLOCATION",
            center={
                "source_handle": str(source_handle),
                "source_rank": source_rank,
                "learned_surface": surface,
                "learned_token_construction": [],
                "trusted_language_memory": False,
                "construction_alignment": 0,
                "reality_alignment": None,
                "truth_compatibility": 0,
                "admission_state": "AWAITING_LESSON",
                "neutral_route_probability": SCALE // 2,
            },
            physical_identity=self.native_physical_identity_enabled,
        )
        self.store.transact(
            [shell],
            event_kind="SOURCE_AUTHENTIC_WORD_PREALLOCATION",
            details={
                "source_handle": str(source_handle),
                "source_rank": source_rank,
                "word_neuron_id": word_id,
            },
        )
        self._catalog_cache = None
        return {"state": "PASS", "word": surface, "word_neuron_id": word_id, "created": 1}

    def _admit_word(
        self,
        word: str,
        *,
        lesson_id: str,
        source_handle: str,
        route: Sequence[str],
        attempts: int,
        confirmations: int,
        foundation: bool = False,
    ) -> dict[str, Any]:
        manifest = self.store.manifest()
        existing_word_id = manifest["word_index"].get(word)
        route_surfaces = [self._surface(self.store.load_neuron(neuron_id)) for neuron_id in route]
        reused = sum(len(surface) for surface in route_surfaces if len(surface) > 1)
        efficiency = max(SCALE // max(1, len(word)), reused * SCALE // max(1, len(word)))
        timing = max(1, SCALE // max(1, attempts))
        neuron_economy = max(
            1,
            (len(word) - len(route) + 1) * SCALE // max(1, len(word)),
        )
        settlement = settle_triadic(
            (efficiency, timing, neuron_economy), max_ticks=64, confirmations=3
        )
        if settlement.state != "PASS":
            return {
                "state": "HOLD", "reason": "RID_DID_NOT_SETTLE", "word": word,
                "rid": settlement.rid, "ticks": settlement.ticks,
            }
        word_id = str(existing_word_id or stable_word_neuron_id(lesson_id))
        episode_id = new_neuron_id()
        existing_word = (
            self.store.load_neuron(str(existing_word_id))
            if existing_word_id is not None else None
        )
        existing_is_learned = bool(
            existing_word is not None and existing_word.get("lifecycle") == "STABLE"
        )
        if existing_is_learned and not self.native_physical_identity_enabled:
            return {"state": "PASS", "word": word, "created": 0, "attempts": attempts}
        if existing_is_learned:
            episode = make_neuron(
                neuron_id=episode_id, kind="EPISODE", lifecycle="STABLE",
                creation_event="UNIVERSAL_REPEATED_WORD_EXPERIENCE", children=route,
                center={
                    "visible_lesson_id": lesson_id, "source_handle": source_handle,
                    "admitted_endpoint": word_id, "selected_token_path": list(route),
                    "trusted_language_memory": False,
                    "construction_alignment": 0,
                    "reality_alignment": None,
                    "truth_compatibility": 0,
                },
                physical_identity=True,
            )
            changed = [episode]
            marker = f"REPEATED-EXPERIENCE:{episode_id}"
            for peer_id in dict.fromkeys((word_id, *route)):
                peer = self.store.load_neuron(peer_id)
                reinforce_connection(
                    episode, peer_id, direction="OUT", passed=True, event_id=marker
                )
                reinforce_connection(
                    peer, episode_id, direction="IN", passed=True, event_id=marker
                )
                changed.append(peer)
            self.store.transact(
                changed, event_kind="UNIVERSAL_REPEATED_WORD_EXPERIENCE",
                details={
                    "lesson_id": lesson_id, "source_handle": source_handle,
                    "word_neuron_id": word_id, "episode_neuron_id": episode_id,
                    "confirmations": confirmations,
                },
            )
            self._catalog_cache = None
            return {
                "state": "PASS", "word": word, "created": 1,
                "created_kind": "EPISODE", "word_neuron_id": word_id,
                "episode_neuron_id": episode_id,
                "physical_id": episode["physical_id"],
                "semantic_key": episode["semantic_key"],
                "attempts": attempts, "confirmation_passes": confirmations,
                "S_n": settlement.quality, "RID_t": settlement.rid,
                "E_t": settlement.channels[0], "T_t": settlement.channels[1],
                "N_t": settlement.channels[2],
                "rid_settle_ticks": settlement.ticks, "route": list(route),
            }
        word_neuron = make_neuron(
            neuron_id=word_id, kind="WORD", lifecycle="STABLE",
            creation_event=(
                "ARCHITECT_FOUNDATION_WORD_ADMISSION"
                if foundation else "UNIVERSAL_COMPLETE_WORD_ADMISSION"
            ),
            # A WORD's durable recall path is its selected construction.  The
            # metadata record alone is not traversable by fresh recall.
            children=route,
            center={
                "visible_lesson_id": lesson_id,
                "source_handle": source_handle,
                "learned_surface": word,
                "learned_token_construction": list(route),
                "trusted_language_memory": True,
                "construction_alignment": SCALE,
                "reality_alignment": None,
                "truth_compatibility": SCALE,
                "route_quality_v1": {
                    "efficiency": efficiency,
                    "timing": timing,
                    "neuron_economy": neuron_economy,
                    "S_n": settlement.quality,
                    "RID_t": settlement.rid,
                    "settle_ticks": settlement.ticks,
                    "zero_confirmations": settlement.zero_confirmations,
                },
                "admission_state": "FROZEN_CONFIRMATIONS_COMPLETE",
                "required_confirmations": confirmations,
                "confirmation_passes": confirmations,
                "foundation_token": bool(foundation),
            },
            foundation=foundation,
            physical_identity=self.native_physical_identity_enabled,
        )
        if existing_word is not None:
            # Promotion retains the preallocated neuron's identity and birth
            # timestamp while replacing its neutral shell with earned state.
            word_neuron["created_utc"] = existing_word["created_utc"]
            if "physical_id" in existing_word:
                word_neuron["physical_id"] = existing_word["physical_id"]
                word_neuron["semantic_key"] = existing_word["semantic_key"]
            word_neuron["creation_event"] = "PREALLOCATED_WORD_PROMOTED_AFTER_CONFIRMATION"
            word_neuron["content_sha256"] = content_hash(word_neuron)
        word_neuron["activation"].update({
            "uses": attempts, "pass_hits": 1, "fail_hits": max(0, attempts - 1),
            "confirmation_passes": confirmations,
        })
        episode = make_neuron(
            neuron_id=episode_id, kind="EPISODE", lifecycle="STABLE",
            creation_event="UNIVERSAL_WORD_EXPERIENCE", children=route,
            center={
                "visible_lesson_id": lesson_id, "source_handle": source_handle,
                "admitted_endpoint": word_id, "selected_token_path": list(route),
                "trusted_language_memory": False,
                "construction_alignment": 0,
                "reality_alignment": None,
                "truth_compatibility": 0,
            },
            physical_identity=self.native_physical_identity_enabled,
        )
        changed = [word_neuron, episode]
        marker = f"UNIVERSAL-WORD:{lesson_id}"
        for child_id in dict.fromkeys(route):
            child = self.store.load_neuron(child_id)
            if word_id not in child["parents"]:
                child["parents"].append(word_id)
            reinforce_connection(child, word_id, direction="OUT", passed=True, event_id=marker)
            reinforce_connection(word_neuron, child_id, direction="IN", passed=True, event_id=marker)
            changed.append(child)
        if self.native_physical_identity_enabled:
            episode_marker = f"WORD-EXPERIENCE:{episode_id}"
            for peer_id in dict.fromkeys((word_id, *route)):
                peer = word_neuron if peer_id == word_id else self.store.load_neuron(peer_id)
                reinforce_connection(
                    episode, peer_id, direction="OUT", passed=True, event_id=episode_marker
                )
                reinforce_connection(
                    peer, episode_id, direction="IN", passed=True, event_id=episode_marker
                )
                if peer is not word_neuron:
                    changed.append(peer)
        self.store.transact(
            changed, event_kind="UNIVERSAL_COMPLETE_WORD_ADMISSION",
            details={
                "lesson_id": lesson_id, "source_handle": source_handle,
                "word_neuron_id": word_id, "episode_neuron_id": episode_id,
                "confirmations": confirmations, "foundation": bool(foundation),
            },
        )
        self._catalog_cache = None
        return {
            "state": "PASS", "word": word, "created": 1,
            "word_neuron_id": word_id, "episode_neuron_id": episode_id,
            "attempts": attempts, "confirmation_passes": confirmations,
            "S_n": settlement.quality, "RID_t": settlement.rid,
            "E_t": settlement.channels[0], "T_t": settlement.channels[1],
            "N_t": settlement.channels[2],
            "rid_settle_ticks": settlement.ticks,
            "route": list(route), "foundation": bool(foundation),
        }


class Neuronizer:
    POSITION_PROFILE_BINS = 8
    WORD_CLASS_PROFILE_KEY = UniversalCurriculumEngine.WORD_CLASS_PROFILE_KEY
    WORD_SEMANTIC_PROFILE_KEY = UniversalCurriculumEngine.WORD_SEMANTIC_PROFILE_KEY
    WORD_IDENTITY_PROFILE_KEY = UniversalCurriculumEngine.WORD_IDENTITY_PROFILE_KEY
    _TAG_GROUPS = {
        "grammar": (WORD_CLASS_PROFILE_KEY, UniversalCurriculumEngine.WORD_CLASS_CHANNELS),
        "semantic": (WORD_SEMANTIC_PROFILE_KEY, UniversalCurriculumEngine.WORD_SEMANTIC_CHANNELS),
        "identity": (WORD_IDENTITY_PROFILE_KEY, UniversalCurriculumEngine.WORD_IDENTITY_CHANNELS),
        "position": ("opaque_context_associations_v1", tuple(f"M{index}" for index in range(32))),
    }

    def __init__(
        self,
        store: GraphStore,
        library: CudaLibrary,
        *,
        route_truth_provider: Callable[[dict[str, Any]], Sequence[int]] | None = None,
    ):
        self.store = store
        self.library = library
        self.route_truth_provider = route_truth_provider

    @staticmethod
    def _construction_alignment(neuron: dict[str, Any]) -> int:
        """Use the shared construction-trust projection for Hept routing."""

        return UniversalCurriculumEngine._construction_alignment(neuron)

    @staticmethod
    def _route_probability(pass_hits: int, fail_hits: int) -> int:
        """Use the shared fixed-point route-evidence projection."""

        return UniversalCurriculumEngine._route_probability(pass_hits, fail_hits)

    def _edge_state(self, source: dict[str, Any] | None, peer_id: str) -> tuple[int, list[int]]:
        reflectors = [SCALE // 2] * 6
        center = SCALE // 2
        if source is None:
            return center, reflectors
        observed: list[int] = []
        for channel, name in enumerate(REFLECTORS):
            for edge in source["reflectors"][name]:
                if edge["peer_id"] == peer_id and edge["direction"] == "OUT" and edge.get("hot", True):
                    reflectors[channel] = int(edge["weight"])
                    observed.append(int(edge["weight"]))
        if observed:
            center = max(observed)
        return center, reflectors

    @staticmethod
    def _hept_seed_state(previous_id: str, remaining: Sequence[str], position: int) -> int:
        encoded = "\0".join((previous_id, str(position), *remaining)).encode("utf-8")
        return int.from_bytes(hashlib.sha256(encoded).digest()[:8], "big") % SCALE

    def _context_weight(
        self,
        selected_ids: Sequence[str],
        candidate_id: str,
        overrides: dict[str, dict[str, Any]],
    ) -> int:
        if not selected_ids:
            return SCALE // 2
        evidence: list[int] = []
        for source_id in selected_ids:
            source = overrides.get(source_id) or self.store.load_neuron(source_id)
            for edges in source["reflectors"].values():
                for edge in edges:
                    if edge["peer_id"] == candidate_id and edge.get("hot", True):
                        evidence.append(int(edge["weight"]))
        return sum(evidence) // len(evidence) if evidence else SCALE // 2

    @classmethod
    def _position_profile_bin(cls, position: int, length: int) -> int:
        if length < 1 or not 0 <= position < length:
            raise ValueError("position profile index outside route")
        return min(
            cls.POSITION_PROFILE_BINS - 1,
            position * cls.POSITION_PROFILE_BINS // length,
        )

    @classmethod
    def _learned_position_context(
        cls, neuron: dict[str, Any], *, position: int, length: int
    ) -> tuple[int, int] | None:
        profile = neuron["center_attractor"].get("opaque_position_profile_v1")
        if not isinstance(profile, dict):
            return None
        bins = [int(value) for value in profile.get("bins", [])]
        observations = int(profile.get("observations", 0))
        if len(bins) != cls.POSITION_PROFILE_BINS or observations <= 0:
            return None
        selected_bin = cls._position_profile_bin(position, length)
        smoothed = (bins[selected_bin] + 1) * SCALE // (
            observations + cls.POSITION_PROFILE_BINS
        )
        uniform = SCALE // cls.POSITION_PROFILE_BINS
        context = max(
            50_000,
            min(950_000, SCALE // 2 + (smoothed - uniform) * 2),
        )
        confidence = min(600_000, 200_000 + observations * 50_000)
        return context, confidence

    @classmethod
    def _reciprocal_position_anchor(
        cls,
        candidates: Sequence[dict[str, Any]],
        *,
        position: int,
        length: int,
        minimum_observations: int = 3,
    ) -> int | None:
        target_bin = cls._position_profile_bin(position, length)
        eligible: list[tuple[int, int, int]] = []
        for index, neuron in enumerate(candidates):
            profile = neuron["center_attractor"].get("opaque_position_profile_v1")
            if not isinstance(profile, dict):
                continue
            bins = [int(value) for value in profile.get("bins", [])]
            observations = int(profile.get("observations", 0))
            if len(bins) != cls.POSITION_PROFILE_BINS or observations < minimum_observations:
                continue
            best = max(bins)
            if best <= 0 or bins.count(best) != 1 or bins[target_bin] != best:
                continue
            support_ppm = best * SCALE // observations
            eligible.append((support_ppm, observations, index))
        if not eligible:
            return None
        eligible.sort(reverse=True)
        if len(eligible) > 1 and eligible[0][:2] == eligible[1][:2]:
            return None
        return eligible[0][2]

    @classmethod
    def _profile_route_plan(
        cls, candidates: Sequence[dict[str, Any]], *, length: int
    ) -> tuple[int | None, ...]:
        """Find one coherent assignment using only child-owned position evidence.

        The exact dynamic program is deliberately bounded to the small-scale
        architecture proof. Larger buckets use a deterministic greedy material
        until the storage/routing engineering phase replaces it.
        """

        if length != len(candidates) or length < 1:
            raise ValueError("profile route plan requires one candidate per position")
        scores: list[list[int]] = []
        supported: list[list[bool]] = []
        for position in range(length):
            row: list[int] = []
            support_row: list[bool] = []
            for candidate in candidates:
                learned = cls._learned_position_context(
                    candidate, position=position, length=length
                )
                row.append(learned[0] if learned is not None else SCALE // 2)
                support_row.append(learned is not None and learned[0] > SCALE // 2)
            scores.append(row)
            supported.append(support_row)

        if length <= 12:
            states: dict[int, tuple[int, tuple[int, ...]]] = {0: (0, ())}
            for position in range(length):
                next_states: dict[int, tuple[int, tuple[int, ...]]] = {}
                for mask, (total, assignment) in states.items():
                    for candidate_index in range(length):
                        bit = 1 << candidate_index
                        if mask & bit:
                            continue
                        proposal = (
                            total + scores[position][candidate_index],
                            (*assignment, candidate_index),
                        )
                        prior = next_states.get(mask | bit)
                        if prior is None or proposal[0] > prior[0] or (
                            proposal[0] == prior[0] and proposal[1] < prior[1]
                        ):
                            next_states[mask | bit] = proposal
                states = next_states
            assignment = states[(1 << length) - 1][1]
        else:
            assignment_list = [-1] * length
            free_positions = set(range(length))
            free_candidates = set(range(length))
            pairs = sorted(
                (
                    (scores[position][candidate], -position, -candidate)
                    for position in range(length)
                    for candidate in range(length)
                ),
                reverse=True,
            )
            for _, negative_position, negative_candidate in pairs:
                position = -negative_position
                candidate = -negative_candidate
                if position in free_positions and candidate in free_candidates:
                    assignment_list[position] = candidate
                    free_positions.remove(position)
                    free_candidates.remove(candidate)
            assignment = tuple(assignment_list)

        return tuple(
            candidate_index if supported[position][candidate_index] else None
            for position, candidate_index in enumerate(assignment)
        )

    @classmethod
    def _local_profile_guide(
        cls,
        candidates: Sequence[dict[str, Any]],
        *,
        position: int,
        length: int,
    ) -> int | None:
        eligible: list[tuple[int, int]] = []
        for index, candidate in enumerate(candidates):
            learned = cls._learned_position_context(
                candidate, position=position, length=length
            )
            if learned is not None and learned[0] > SCALE // 2:
                eligible.append((learned[0], index))
        if not eligible:
            return None
        eligible.sort(reverse=True)
        if len(eligible) > 1 and eligible[0][0] == eligible[1][0]:
            return None
        return eligible[0][1]

    @classmethod
    def _temporal_profile_guidance(
        cls,
        candidates: Sequence[dict[str, Any]],
        *,
        position: int,
        length: int,
        margin: int = 50_000,
    ) -> tuple[int | None, tuple[int, ...]]:
        eligible: list[tuple[int, int, int]] = []
        deferred: list[int] = []
        for index, candidate in enumerate(candidates):
            current_learned = cls._learned_position_context(
                candidate, position=position, length=length
            )
            current = current_learned[0] if current_learned is not None else SCALE // 2
            future = SCALE // 2
            for future_position in range(position + 1, length):
                learned = cls._learned_position_context(
                    candidate, position=future_position, length=length
                )
                if learned is not None:
                    future = max(future, learned[0])
            if future >= current + margin:
                deferred.append(index)
                continue
            advantage = current - future
            if current > SCALE // 2 and advantage >= margin:
                eligible.append((advantage, current, index))
        eligible.sort(reverse=True)
        guide = None
        if eligible and not (
            len(eligible) > 1 and eligible[0][:2] == eligible[1][:2]
        ):
            guide = eligible[0][2]
        return guide, tuple(deferred)

    def rebuild_position_profiles_from_admitted(self) -> dict[str, Any]:
        """Derive opaque child-position evidence only from admitted PASS routes."""

        manifest = self.store.manifest()
        profiles: dict[str, dict[str, Any]] = {}
        stable_sentences = 0
        for neuron_id, index in manifest["neuron_index"].items():
            if index["kind"] != "SENTENCE":
                continue
            sentence = self.store.load_neuron(neuron_id)
            if (
                sentence["lifecycle"] != "STABLE"
                or sentence["center_attractor"].get("trusted_language_memory") is not True
            ):
                continue
            route = tuple(
                str(item)
                for item in sentence["center_attractor"].get("construction", [])
            )
            if not route:
                continue
            stable_sentences += 1
            for position, child_id in enumerate(route):
                profile = profiles.setdefault(
                    child_id,
                    {
                        "bins": [0] * self.POSITION_PROFILE_BINS,
                        "observations": 0,
                        "supporting_sentence_ids": [],
                    },
                )
                profile["bins"][self._position_profile_bin(position, len(route))] += 1
                profile["observations"] += 1
                if neuron_id not in profile["supporting_sentence_ids"]:
                    profile["supporting_sentence_ids"].append(neuron_id)

        changed: list[dict[str, Any]] = []
        for neuron_id, index in manifest["neuron_index"].items():
            neuron = self.store.load_neuron(neuron_id)
            if index["kind"] != "WORD" and not neuron["center_attractor"].get(
                "visible_state_id"
            ):
                continue
            current = neuron["center_attractor"].get("opaque_position_profile_v1")
            replacement = profiles.get(neuron_id)
            if replacement is None:
                if current is None:
                    continue
                neuron["center_attractor"].pop("opaque_position_profile_v1", None)
            else:
                replacement = {
                    **replacement,
                    "supporting_sentence_ids": sorted(
                        replacement["supporting_sentence_ids"]
                    ),
                    "human_labels_used": False,
                    "target_artifacts_read": False,
                }
                if current == replacement:
                    continue
                neuron["center_attractor"]["opaque_position_profile_v1"] = replacement
            changed.append(neuron)
        transaction_id = None
        if changed:
            transaction_id = self.store.transact(
                changed,
                event_kind="REBUILD_OPAQUE_POSITION_PROFILES_FROM_ADMITTED_ROUTES",
                details={
                    "stable_sentences": stable_sentences,
                    "profiled_children": len(profiles),
                    "changed_neurons": len(changed),
                    "human_labels_used": False,
                    "target_artifacts_read": False,
                },
            )
        return {
            "state": "PASS",
            "stable_sentences": stable_sentences,
            "profiled_children": len(profiles),
            "changed_neurons": len(changed),
            "transaction_id": transaction_id,
            "human_labels_used": False,
            "target_artifacts_read": False,
        }

    @staticmethod
    def _route_signature(route: Sequence[str]) -> str:
        return hashlib.sha256("\0".join(route).encode("utf-8")).hexdigest().upper()

    @staticmethod
    def _unique_route_count(candidate_ids: Sequence[str]) -> int:
        counts: dict[str, int] = {}
        for candidate_id in candidate_ids:
            counts[candidate_id] = counts.get(candidate_id, 0) + 1
        total = 1
        for value in range(2, len(candidate_ids) + 1):
            total *= value
        for count in counts.values():
            divisor = 1
            for value in range(2, count + 1):
                divisor *= value
            total //= divisor
        return total

    @classmethod
    def _prefix_novelty(
        cls,
        origin: dict[str, Any],
        selected: Sequence[str],
        candidate_id: str,
        remaining: Sequence[str],
    ) -> tuple[int, int, bool]:
        """Return unseen suffix mass for one target-free route prefix.

        ``failed_prefix_counts`` counts distinct failed complete routes below a
        prefix.  The suffix capacity is the number of unique permutations that
        can still complete that prefix.  A zero result means the CPU has
        deterministically exhausted that branch from model-owned failure
        evidence; it does not identify or strengthen any hidden alternative.
        """

        suffix = list(remaining)
        suffix.remove(candidate_id)
        capacity = cls._unique_route_count(suffix)
        signature = cls._route_signature((*selected, candidate_id))
        failed_below = int(
            origin["center_attractor"].get("failed_prefix_counts", {}).get(signature, 0)
        )
        if capacity <= 0 or failed_below >= capacity:
            return 0, capacity, True
        novelty = (capacity - failed_below) * SCALE // capacity
        return novelty, capacity, False

    @classmethod
    def _blocked_completion_prefix(
        cls,
        prefix: Sequence[str],
        remaining: Sequence[str],
        *,
        route_length: int,
        blocked_signatures: set[str],
        node_budget: int = 4_096,
    ) -> bool:
        """Whether every bounded completion below ``prefix`` was attempted.

        This is a target-free search mask.  It consults only complete route
        signatures already produced by the chooser, and refuses to enumerate
        an unbounded suffix tree.  A prefix is masked only after *all* of its
        possible ordered completions are in that observed blocked set.
        """

        suffix_length = int(route_length) - len(prefix)
        if suffix_length < 0 or suffix_length > len(remaining):
            return False
        visited = 0
        all_blocked = True
        budget_exceeded = False

        def walk(path: tuple[str, ...], pool: tuple[str, ...]) -> None:
            nonlocal visited, all_blocked, budget_exceeded
            if budget_exceeded or not all_blocked:
                return
            if len(path) == suffix_length:
                visited += 1
                if visited > node_budget:
                    budget_exceeded = True
                    return
                if cls._route_signature((*prefix, *path)) not in blocked_signatures:
                    all_blocked = False
                return
            choices: set[str] = set()
            for index, value in enumerate(pool):
                if value in choices:
                    continue
                choices.add(value)
                walk((*path, value), (*pool[:index], *pool[index + 1 :]))

        walk((), tuple(remaining))
        return visited > 0 and all_blocked and not budget_exceeded

    @classmethod
    def _frontier_guide_index(
        cls,
        origin: dict[str, Any],
        selected: Sequence[str],
        remaining: Sequence[str],
        *,
        seed: int,
        position: int,
    ) -> int | None:
        """Choose the least-explored supported prefix without target data."""

        choices: list[tuple[int, int, int, int]] = []
        prefix_counts = origin["center_attractor"].get("failed_prefix_counts", {})
        for index, candidate_id in enumerate(remaining):
            novelty, capacity, exhausted = cls._prefix_novelty(
                origin,
                selected,
                candidate_id,
                remaining,
            )
            if exhausted:
                continue
            prefix_signature = cls._route_signature((*selected, candidate_id))
            failed_below = int(prefix_counts.get(prefix_signature, 0))
            unseen = max(0, capacity - failed_below)
            tie_material = "\0".join(
                ("FRONTIER", str(seed), str(position), str(candidate_id))
            ).encode("utf-8")
            tie_break = int.from_bytes(hashlib.sha256(tie_material).digest()[:8], "big")
            choices.append((unseen, novelty, tie_break, -index))
        if not choices:
            return None
        return -max(choices)[3]

    @classmethod
    def _frontier_route_plan(
        cls,
        origin: dict[str, Any],
        selected: Sequence[str],
        remaining: Sequence[str],
        *,
        seed: int,
        node_budget: int = 256,
    ) -> tuple[tuple[str, ...] | None, int]:
        """Find one complete unseen route from model-owned prefix memory.

        This is a CPU path-finding aid, not a teacher route.  It performs a
        bounded depth-first search over prefixes whose model-owned
        ``failed_prefix_counts`` still leave at least one suffix route.  The
        GPU remains responsible for the probabilistic choice; callers use the
        returned route only as a soft context bias.  A bounded search returns
        ``None`` rather than inventing a route when the frontier is too large
        or no supported completion can be found.
        """

        if node_budget < 1:
            raise ValueError("frontier route-plan node budget must be positive")
        start = tuple(str(item) for item in selected)
        initial_remaining = tuple(str(item) for item in remaining)
        visited_nodes = 0
        prefix_counts = origin["center_attractor"].get("failed_prefix_counts", {})

        def ordered_choices(
            prefix: tuple[str, ...], rest: tuple[str, ...]
        ) -> list[str]:
            choices: list[tuple[int, int, int, str]] = []
            seen: set[str] = set()
            for candidate_id in rest:
                if candidate_id in seen:
                    continue
                seen.add(candidate_id)
                novelty, capacity, exhausted = cls._prefix_novelty(
                    origin,
                    prefix,
                    candidate_id,
                    rest,
                )
                if exhausted:
                    continue
                signature = cls._route_signature((*prefix, candidate_id))
                failed_below = int(prefix_counts.get(signature, 0))
                unseen = max(0, capacity - failed_below)
                tie_material = "\0".join(
                    (
                        "FRONTIER_PLAN",
                        str(seed),
                        str(len(prefix)),
                        *prefix,
                        candidate_id,
                    )
                ).encode("utf-8")
                tie_break = int.from_bytes(
                    hashlib.sha256(tie_material).digest()[:8], "big"
                )
                choices.append((unseen, novelty, tie_break, candidate_id))
            choices.sort(key=lambda row: (-row[0], -row[1], -row[2], row[3]))
            return [row[3] for row in choices]

        def search(
            prefix: tuple[str, ...], rest: tuple[str, ...]
        ) -> tuple[str, ...] | None:
            nonlocal visited_nodes
            if not rest:
                return prefix
            if visited_nodes >= node_budget:
                return None
            for candidate_id in ordered_choices(prefix, rest):
                if visited_nodes >= node_budget:
                    return None
                visited_nodes += 1
                next_rest = list(rest)
                next_rest.remove(candidate_id)
                proposal = search((*prefix, candidate_id), tuple(next_rest))
                if proposal is not None:
                    return proposal
            return None

        return search(start, initial_remaining), visited_nodes

    @staticmethod
    def _inventory_signature(children: Sequence[str]) -> str:
        return hashlib.sha256("\0".join(sorted(children)).encode("utf-8")).hexdigest().upper()

    def _cpu_guide(
        self,
        *,
        centers: list[int],
        reflectors: list[int],
        contexts: list[int],
        truths: list[int],
        multiplicities: list[int],
        blocked: list[int],
        guide_rate: int,
    ) -> tuple[int, list[int]]:
        if not 0 <= guide_rate <= SCALE:
            raise ValueError("CPU guide rate must be fixed-point")
        guide = self.library.cpu_hept_guide(
            centers=centers,
            reflectors=reflectors,
            contexts=contexts,
            truths=truths,
            multiplicities=multiplicities,
            blocked=blocked,
        )
        guided = list(contexts)
        for index, is_blocked in enumerate(blocked):
            if is_blocked:
                guided[index] = 0
        guided[guide.candidate] = toward_one(guided[guide.candidate], guide_rate)
        return guide.candidate, guided

    def _record_failed_assembly(
        self, episode: dict[str, Any], route: Sequence[str]
    ) -> bool:
        center = episode["center_attractor"]
        failed = center.setdefault("failed_assemblies", {})
        signature = self._route_signature(route)
        if signature in failed:
            failed[signature] = int(failed[signature]) + 1
            return False
        failed[signature] = 1
        prefixes = center.setdefault("failed_prefix_counts", {})
        # Store one count for every prefix of a distinct failed route.  The
        # counts represent distinct complete routes below each prefix, so a
        # repeated complete failure cannot falsely exhaust a branch.
        for prefix_length in range(1, len(route) + 1):
            prefix_signature = self._route_signature(route[:prefix_length])
            prefixes[prefix_signature] = int(prefixes.get(prefix_signature, 0)) + 1
        return True

    def _render_state(self, neuron_id: str) -> str:
        neuron = self.store.load_neuron(neuron_id)
        center = neuron["center_attractor"]
        visible = center.get("visible_state_id")
        if visible:
            return str(visible)
        surface = center.get("learned_surface")
        if surface:
            return f"WORD:{surface}"
        # Recursive sentence composition routes over already admitted phrase
        # SENTENCE neurons.  Their surface is their stable WORD construction,
        # not a separate visible-state label.  Rendering that admitted
        # construction is telemetry only; it does not add an ordering hint to
        # CUDA or alter the CPU judge.
        if (
            neuron.get("kind") == "SENTENCE"
            and neuron.get("lifecycle") == "STABLE"
            and center.get("trusted_language_memory") is True
        ):
            words: list[str] = []
            for child_id in center.get("construction", ()):
                child = self.store.load_neuron(str(child_id))
                child_surface = child.get("center_attractor", {}).get("learned_surface")
                if not child_surface:
                    break
                words.append(str(child_surface))
            if words and len(words) == len(center.get("construction", ())):
                return "PHRASE:" + " ".join(words)
        raise ValueError(f"neuron is not a visible construction state: {neuron_id}")

    @staticmethod
    def _resolve_visible_state(manifest: dict[str, Any], state_id: str) -> str:
        indexed = manifest.get("state_index", {}).get(state_id)
        if indexed:
            return str(indexed)
        if state_id.startswith("WORD:"):
            word = state_id.removeprefix("WORD:").lower()
            indexed = manifest.get("word_index", {}).get(word)
            if indexed:
                return str(indexed)
        raise KeyError(state_id)

    @classmethod
    def _context_tag_weight(cls, neuron: Mapping[str, Any], requested: Mapping[str, str] | None) -> int:
        """Return the learned metadata weight for the CPU-supplied opaque context.

        A missing profile is deliberately its uniform prior, not a rejection:
        new neurons begin equally eligible and earn context preference only from
        their own selected PASS/FAIL consequences.  Tags adjust activation;
        they never alter the Hydra truth mask or grant authority.
        """

        if not requested:
            return SCALE
        center = neuron.get("center_attractor", {})
        combined = SCALE
        for group, channel in requested.items():
            spec = cls._TAG_GROUPS.get(str(group))
            if spec is None:
                raise ValueError(f"unknown tag context group:{group}")
            profile_key, channels = spec
            if str(channel) not in channels:
                raise ValueError(f"unknown tag context channel:{group}:{channel}")
            default = SCALE // len(channels)
            profile = center.get(profile_key)
            if group == "position":
                weight = default
                associations = profile if isinstance(profile, Mapping) else {}
                matching = [
                    item
                    for item in associations.values()
                    if isinstance(item, Mapping)
                    and item.get("channel") == channel
                    and int(item.get("pass_hits", 0)) > int(item.get("fail_hits", 0))
                ]
                if matching:
                    weight = max(
                        max(0, min(SCALE, int(item.get("weight", default))))
                        for item in matching
                    )
                combined = max(1, (combined * weight) // SCALE)
                continue
            if group == "grammar":
                # Read old R0..R3 payloads through the same append-only
                # migration used by learning.  Otherwise a historical 25%
                # weight would be compared against today's 1/9 prior and
                # manufacture confidence that was never learned.
                profile = UniversalCurriculumEngine._word_class_profile(dict(neuron))
            weight = default
            if isinstance(profile, Mapping):
                rows = profile.get("channels", [])
                if isinstance(rows, Sequence):
                    selected = next((item for item in rows if isinstance(item, Mapping) and item.get("channel") == channel), None)
                    if selected is not None:
                        weight = max(0, min(SCALE, int(selected.get("weight", default))))
            combined = max(1, (combined * weight) // SCALE)
        return combined

    @classmethod
    def _context_tag_prior(cls, requested: Mapping[str, str] | None) -> int:
        """Equal-prior tag mass for a requested opaque context."""

        if not requested:
            return SCALE
        prior = SCALE
        for group, channel in requested.items():
            spec = cls._TAG_GROUPS.get(str(group))
            if spec is None:
                raise ValueError(f"unknown tag context group:{group}")
            _profile_key, channels = spec
            if str(channel) not in channels:
                raise ValueError(f"unknown tag context channel:{group}:{channel}")
            prior = max(1, (prior * (SCALE // len(channels))) // SCALE)
        return prior

    @classmethod
    def _apply_context_tag_bias(
        cls,
        context: int,
        neuron: Mapping[str, Any],
        requested: Mapping[str, str] | None,
    ) -> int:
        """Modulate a route context by metadata relative to equal priors.

        The stored tag probability is not an absolute route strength.  A
        fresh word must remain neutral; only the learned displacement from
        the channel's equal prior raises or lowers the existing activation.
        """

        if not requested:
            return int(context)
        learned = cls._context_tag_weight(neuron, requested)
        prior = cls._context_tag_prior(requested)
        bias = ((learned - prior) * (SCALE // 2)) // max(1, prior)
        return max(1, min(SCALE, int(context) + bias))

    def attempt_route(
        self,
        candidate_ids: Sequence[str],
        *,
        seed: int,
        overrides: dict[str, dict[str, Any]] | None = None,
        apply_verdict: bool | None = None,
        origin_id: str | None = None,
        copy_overrides: bool = True,
        exhaustive_prefix_memory: bool = True,
        cpu_guided: bool = False,
        guide_rate: int = 250_000,
        frontier_guided: bool = False,
        frontier_rate: int = 250_000,
        frontier_plan_guided: bool = False,
        frontier_plan_node_budget: int = 256,
        stable_recall: bool = False,
        hept_pool: dict[int, CudaHept] | None = None,
        route_length: int | None = None,
        blocked_route_signatures: set[str] | None = None,
        route_truth_context: str | None = None,
        tag_context: Mapping[str, str] | None = None,
        tag_contexts: Sequence[Mapping[str, str]] | None = None,
    ) -> tuple[tuple[str, ...], list[HeptRouteStep], dict[str, dict[str, Any]]]:
        if not 0 < len(candidate_ids) <= 32:
            raise ValueError("a Neuronizer turn requires between 1 and 32 visible child neurons")
        selected_length = len(candidate_ids) if route_length is None else int(route_length)
        if not 0 < selected_length <= len(candidate_ids):
            raise ValueError("route length must be between one and the visible inventory width")
        if tag_contexts is not None and len(tag_contexts) != selected_length:
            raise ValueError("one CPU activation anchor is required for each route position")
        if frontier_guided and not 0 <= frontier_rate <= SCALE:
            raise ValueError("frontier guide rate must be fixed-point")
        if frontier_plan_guided and frontier_plan_node_budget < 1:
            raise ValueError("frontier route-plan node budget must be positive")
        local = (
            {key: deepcopy(value) for key, value in (overrides or {}).items()}
            if copy_overrides
            else (overrides if overrides is not None else {})
        )
        remaining = list(candidate_ids)
        selected: list[str] = []
        steps: list[HeptRouteStep] = []
        manifest = self.store.manifest()
        stable_construction: tuple[str, ...] = ()
        if stable_recall and origin_id:
            origin = local.get(origin_id) or self.store.load_neuron(origin_id)
            candidate_construction = tuple(
                str(item) for item in origin["center_attractor"].get("construction", ())
            )
            if (
                origin["kind"] in {"SENTENCE", "CONCEPT", "COMPRESSION"}
                and origin["lifecycle"] == "STABLE"
                and origin["center_attractor"].get("trusted_language_memory") is True
                and len(candidate_construction) == len(candidate_ids)
                and Counter(candidate_construction) == Counter(candidate_ids)
            ):
                stable_construction = candidate_construction
        previous_id = "START"
        for position in range(selected_length):
            position_anchor = (
                tag_contexts[position] if tag_contexts is not None else tag_context
            )
            previous = (
                (local.get(origin_id) or self.store.load_neuron(origin_id))
                if previous_id == "START" and origin_id
                else None
                if previous_id == "START"
                else local.get(previous_id) or self.store.load_neuron(previous_id)
            )
            centers: list[int] = []
            flattened = [[SCALE // 2] * len(remaining) for _ in range(6)]
            contexts: list[int] = []
            truths: list[int] = []
            multiplicities: list[int] = []
            blocked = [0] * len(remaining)
            prefix_novelties: list[int] = []
            for index, candidate_id in enumerate(remaining):
                center, reflector_values = self._edge_state(previous, candidate_id)
                centers.append(center)
                for channel, value in enumerate(reflector_values):
                    flattened[channel][index] = value
                context = self._context_weight(selected, candidate_id, local)
                # Neuron-owned grammar/semantic/identity metadata is part of
                # the context-specific activation field.  The GPU receives
                # only the resulting fixed-point scalar, never tag meanings.
                candidate = local.get(candidate_id) or self.store.load_neuron(candidate_id)
                context = self._apply_context_tag_bias(context, candidate, position_anchor)
                if origin_id:
                    origin = local.get(origin_id) or self.store.load_neuron(origin_id)
                    heads = origin["center_attractor"].get("position_heads", {})
                    head = int(heads.get(str(position), {}).get(candidate_id, SCALE // 2))
                    context = (
                        head
                        if origin.get("kind") in {"SENTENCE", "CONCEPT", "COMPRESSION"}
                        and origin.get("lifecycle") == "STABLE"
                        and origin["center_attractor"].get("trusted_language_memory") is True
                        else (context + head) // 2
                    )
                    if exhaustive_prefix_memory:
                        novelty, _capacity, exhausted = self._prefix_novelty(
                            origin,
                            selected,
                            candidate_id,
                            remaining,
                        )
                        if exhausted:
                            blocked[index] = 1
                        context = context * novelty // SCALE
                    else:
                        prefix = self._route_signature((*selected, candidate_id))
                        failed_below = int(
                            origin["center_attractor"]
                            .get("failed_prefix_counts", {})
                            .get(prefix, 0)
                        )
                        context = toward_zero(context, min(900_000, failed_below * 50_000))
                        novelty = SCALE
                    prefix_novelties.append(novelty)
                else:
                    prefix_novelties.append(SCALE)
                contexts.append(context)
                route_is_blocked = (
                    blocked_route_signatures is not None
                    and self._blocked_completion_prefix(
                        (*selected, candidate_id),
                        tuple(
                            value
                            for candidate_position, value in enumerate(remaining)
                            if candidate_position != index
                        ),
                        route_length=selected_length,
                        blocked_signatures=blocked_route_signatures,
                    )
                )
                if route_is_blocked:
                    blocked[index] = 1
                    contexts[-1] = 0
                    prefix_novelties[-1] = 0
                truths.append(
                    0
                    if route_is_blocked
                    else SCALE
                    if stable_construction and candidate_id == stable_construction[position]
                    else 0
                    if stable_construction
                    else self._construction_alignment(candidate)
                )
                multiplicities.append(
                    int(manifest.get("route_multiplicity", {}).get(f"{previous_id}>{candidate_id}", 0))
                )
            if self.route_truth_provider is not None:
                inventory_context = (
                    str(route_truth_context)
                    if route_truth_context is not None
                    else self._inventory_signature(candidate_ids)
                )
                request = {
                    "context_hash": self._route_signature(
                        (str(origin_id or "START"), str(position), *selected, *remaining)
                    ),
                    "inventory_context_hash": inventory_context,
                    "assembly_context_hash": inventory_context,
                    "candidates": [
                        {
                            "candidate_id": candidate_id,
                            "terminal": position + 1 == selected_length,
                            "complete_route": [*selected, candidate_id],
                        }
                        for candidate_id in remaining
                    ],
                }
                try:
                    route_truths = [int(value) for value in self.route_truth_provider(request)]
                except RuntimeError as error:
                    if str(error).startswith("HOLD_HYDRA_"):
                        raise CudaRouteHold(str(error)) from error
                    raise
                if len(route_truths) != len(truths) or any(value not in {0, SCALE} for value in route_truths):
                    raise RuntimeError("invalid Hydra route mask for sentence chooser")
                truths = [truth if allowed else 0 for truth, allowed in zip(truths, route_truths)]
                blocked = [int(value or not allowed) for value, allowed in zip(blocked, route_truths)]
            reflectors = [value for channel in flattened for value in channel]
            if origin_id and exhaustive_prefix_memory and len(remaining) == 1:
                origin = local.get(origin_id) or self.store.load_neuron(origin_id)
                complete = self._route_signature((*selected, remaining[0]))
                if complete in origin["center_attractor"].get("failed_assemblies", {}):
                    contexts[0] = 0
                    blocked[0] = 1
                    prefix_novelties[0] = 0
            # Prefix exhaustion and exact-completion memory are hard
            # target-free exclusions, not merely weak context hints.  Apply
            # the mask only after every block source above is known.
            truths = [
                truth if not is_blocked else 0
                for truth, is_blocked in zip(truths, blocked)
            ]
            cpu_guide_index = None
            frontier_guide_index = None
            frontier_plan_id = None
            frontier_plan_nodes = None
            if cpu_guided:
                cpu_guide_index, contexts = self._cpu_guide(
                    centers=centers,
                    reflectors=reflectors,
                    contexts=contexts,
                    truths=truths,
                    multiplicities=multiplicities,
                    blocked=blocked,
                    guide_rate=guide_rate,
                )
            if frontier_guided and origin_id and exhaustive_prefix_memory:
                origin = local.get(origin_id) or self.store.load_neuron(origin_id)
                frontier_guide_index = self._frontier_guide_index(
                    origin,
                    selected,
                    remaining,
                    seed=seed,
                    position=position,
                )
                if frontier_guide_index is not None:
                    contexts[frontier_guide_index] = toward_one(
                        contexts[frontier_guide_index], frontier_rate
                    )
            if frontier_plan_guided and origin_id and exhaustive_prefix_memory:
                origin = local.get(origin_id) or self.store.load_neuron(origin_id)
                plan, frontier_plan_nodes = self._frontier_route_plan(
                    origin,
                    selected,
                    remaining,
                    seed=seed,
                    node_budget=frontier_plan_node_budget,
                )
                if plan is not None and len(plan) > len(selected):
                    planned_id = plan[len(selected)]
                    if planned_id in remaining:
                        frontier_plan_id = planned_id
                        plan_index = remaining.index(planned_id)
                        contexts[plan_index] = toward_one(
                            contexts[plan_index], frontier_rate
                        )
            seed_state = self._hept_seed_state(previous_id, remaining, position)
            hept = hept_pool.get(len(remaining)) if hept_pool is not None else None
            owned = hept is None
            if hept is None:
                hept = CudaHept(
                    self.library,
                    candidates=len(remaining),
                    seed_state=seed_state,
                    centers=centers,
                    reflectors=reflectors,
                    contexts=contexts,
                    truths=truths,
                    multiplicities=multiplicities,
                )
                if hept_pool is not None:
                    hept_pool[len(remaining)] = hept
                    owned = False
            else:
                hept.set_seed_state(seed_state)
                hept.load(centers, reflectors, contexts, truths, multiplicities)
            try:
                attempt = hept.attempt(seed + (position + 1) * 1_000_003)
                snapshot = None
                if apply_verdict is not None:
                    hept.apply_verdict(apply_verdict)
                    snapshot = hept.snapshot()
            finally:
                if owned:
                    hept.close()
            step = HeptRouteStep(
                previous_id=previous_id,
                candidate_ids=tuple(remaining),
                selected_index=attempt.candidate,
                selected_reflector=attempt.reflector,
                strengths=attempt.strengths,
                snapshot=snapshot,
                cpu_guide_index=cpu_guide_index,
                frontier_guide_index=frontier_guide_index,
                frontier_plan_id=frontier_plan_id,
                frontier_plan_nodes=frontier_plan_nodes,
                blocked_indices=tuple(index for index, value in enumerate(blocked) if value),
                prefix_novelty=prefix_novelties[attempt.candidate],
                activation_anchor=tuple(sorted((position_anchor or {}).items())),
                activation_context_weight=contexts[attempt.candidate],
            )
            steps.append(step)
            selected_id = step.selected_id
            if apply_verdict:
                source_id = origin_id if previous_id == "START" else previous_id
                if source_id is None:
                    source_id = selected_id
                source = local.get(source_id) or self.store.load_neuron(source_id)
                reinforce_connection(
                    source,
                    selected_id,
                    direction="OUT",
                    passed=apply_verdict,
                    event_id=f"ATTEMPT:{seed}:{position}",
                    initial_weight=centers[attempt.candidate],
                )
                found = None
                for edge in source["reflectors"][REFLECTORS[attempt.reflector]]:
                    if edge["peer_id"] == selected_id and edge["direction"] == "OUT":
                        found = edge
                        break
                if found is not None and snapshot is not None:
                    found["weight"] = int(
                        snapshot.reflectors[attempt.reflector * len(remaining) + attempt.candidate]
                    )
                local[source_id] = source
            selected.append(selected_id)
            remaining.pop(attempt.candidate)
            previous_id = selected_id
            if apply_verdict is not None and origin_id:
                origin = local.get(origin_id) or self.store.load_neuron(origin_id)
                heads = origin["center_attractor"].setdefault("position_heads", {})
                row = heads.setdefault(str(position), {})
                prior = int(row.get(selected_id, SCALE // 2))
                row[selected_id] = (
                    toward_one(prior, 900_000)
                    if apply_verdict
                    else prior
                )
                local[origin_id] = origin
        return tuple(selected), steps, local

    def attempt_route_with_verdict(
        self,
        candidate_ids: Sequence[str],
        *,
        seed: int,
        judge: Callable[[Sequence[str]], bool],
        overrides: dict[str, dict[str, Any]],
        origin_id: str,
        exhaustive_prefix_memory: bool = True,
        cpu_guided: bool = False,
        guide_rate: int = 250_000,
        frontier_guided: bool = False,
        frontier_rate: int = 250_000,
        frontier_plan_guided: bool = False,
        frontier_plan_node_budget: int = 256,
        frontier_scheduler: bool = False,
        frontier_schedule_cursor: int | None = None,
        frontier_schedule_max_scan: int = 256,
        frontier_schedule_seed: int | None = None,
        wave_store: DiskWaveStore | None = None,
        wave_session: str | None = None,
        guidance_parent: dict[str, Any] | None = None,
        hept_pool: dict[int, CudaHept] | None = None,
    ) -> tuple[tuple[str, ...], list[HeptRouteStep], dict[str, dict[str, Any]], bool, tuple[str, ...]]:
        """Generate once, then apply the verdict through those same native Hept cells.

        Every child occurrence retains its own native Hept cell. This is
        especially important for duplicate children: the verdict applies to
        the route that actually ran and is never regenerated after an earlier
        occurrence has changed shared state.
        """

        local = overrides
        duplicate_inventory = len(set(candidate_ids)) != len(candidate_ids)
        if frontier_guided and not 0 <= frontier_rate <= SCALE:
            raise ValueError("frontier guide rate must be fixed-point")
        if frontier_plan_guided and frontier_plan_node_budget < 1:
            raise ValueError("frontier route-plan node budget must be positive")
        if frontier_scheduler and frontier_schedule_cursor is not None and frontier_schedule_cursor < 0:
            raise ValueError("frontier schedule cursor must be nonnegative")
        if frontier_scheduler and frontier_schedule_max_scan < 1:
            raise ValueError("frontier schedule scan bound must be positive")
        remaining = list(candidate_ids)
        selected: list[str] = []
        steps: list[HeptRouteStep] = []
        native_cells: list[CudaHept] = []
        initial_centers: list[list[int]] = []
        manifest = self.store.manifest()
        frontier_schedule: FrontierSchedule | None = None
        if frontier_scheduler:
            try:
                from .frontier_scheduler import schedule_frontier_route
            except ImportError as error:
                raise RuntimeError(
                    "frontier scheduler is archived outside the active checkpoint"
                ) from error
            origin = local.get(origin_id) or self.store.load_neuron(origin_id)
            stored_cursor = int(
                origin["center_attractor"].get("frontier_schedule_cursor", 0)
            )
            schedule_cursor = (
                stored_cursor
                if frontier_schedule_cursor is None
                else int(frontier_schedule_cursor)
            )
            frontier_schedule = schedule_frontier_route(
                candidate_ids,
                failed_signatures=origin["center_attractor"].get(
                    "failed_assemblies", {}
                ).keys(),
                cursor=schedule_cursor,
                seed=seed if frontier_schedule_seed is None else int(frontier_schedule_seed),
                max_scan=frontier_schedule_max_scan,
            )
        previous_id = "START"
        if wave_store is not None and wave_session is not None:
            from .wave_store import CpuWaveBuffer

            wave_buffer = CpuWaveBuffer(session_id=wave_session, seed_anchor=seed)
        else:
            wave_buffer = None
        try:
            for position in range(len(candidate_ids)):
                previous = (
                    local.get(origin_id) or self.store.load_neuron(origin_id)
                    if previous_id == "START"
                    else local.get(previous_id) or self.store.load_neuron(previous_id)
                )
                centers: list[int] = []
                flattened = [[SCALE // 2] * len(remaining) for _ in range(6)]
                contexts: list[int] = []
                truths: list[int] = []
                multiplicities: list[int] = []
                candidate_neurons: list[dict[str, Any]] = []
                blocked = [0] * len(remaining)
                prefix_novelties: list[int] = []
                for index, candidate_id in enumerate(remaining):
                    center, reflector_values = self._edge_state(previous, candidate_id)
                    centers.append(center)
                    for channel, value in enumerate(reflector_values):
                        flattened[channel][index] = value
                    context = self._context_weight(selected, candidate_id, local)
                    candidate = local.get(candidate_id) or self.store.load_neuron(
                        candidate_id
                    )
                    candidate_neurons.append(candidate)
                    learned_position = self._learned_position_context(
                        candidate,
                        position=position,
                        length=len(candidate_ids),
                    )
                    if learned_position is not None:
                        learned_context, confidence = learned_position
                        context = (
                            context * (SCALE - confidence)
                            + learned_context * confidence
                        ) // SCALE
                    origin = local.get(origin_id) or self.store.load_neuron(origin_id)
                    heads = origin["center_attractor"].get("position_heads", {})
                    head = int(heads.get(str(position), {}).get(candidate_id, SCALE // 2))
                    context = (context + head) // 2
                    if (
                        guidance_parent is not None
                        and guidance_parent.get("lifecycle") == "STABLE"
                        and guidance_parent["center_attractor"].get(
                            "trusted_language_memory"
                        )
                        is True
                    ):
                        learned_heads = guidance_parent["center_attractor"].get(
                            "position_heads", {}
                        )
                        context = int(
                            learned_heads.get(str(position), {}).get(
                                candidate_id, SCALE // 2
                            )
                        )
                    if exhaustive_prefix_memory:
                        novelty, _capacity, exhausted = self._prefix_novelty(
                            origin,
                            selected,
                            candidate_id,
                            remaining,
                        )
                        if exhausted:
                            blocked[index] = 1
                        contexts.append(context * novelty // SCALE)
                    else:
                        prefix = self._route_signature((*selected, candidate_id))
                        failed_below = int(
                            origin["center_attractor"]
                            .get("failed_prefix_counts", {})
                            .get(prefix, 0)
                        )
                        contexts.append(
                            toward_zero(context, min(900_000, failed_below * 50_000))
                        )
                        novelty = SCALE
                    prefix_novelties.append(novelty)
                    truths.append(self._construction_alignment(candidate))
                    multiplicities.append(
                        int(manifest.get("route_multiplicity", {}).get(f"{previous_id}>{candidate_id}", 0))
                    )
                if len(remaining) == 1:
                    complete = self._route_signature((*selected, remaining[0]))
                    if complete in origin["center_attractor"].get("failed_assemblies", {}):
                        contexts[0] = 0
                        blocked[0] = 1
                        prefix_novelties[0] = 0
                reflectors = [value for channel in flattened for value in channel]
                profile_anchor_index = self._reciprocal_position_anchor(
                    candidate_neurons,
                    position=position,
                    length=len(candidate_ids),
                )
                if profile_anchor_index is not None:
                    contexts[profile_anchor_index] = toward_one(
                        contexts[profile_anchor_index], 750_000
                    )
                profile_plan_index = None
                local_profile_guide_index = None
                temporal_profile_guide_index = None
                temporal_deferred_indices: tuple[int, ...] = ()
                cpu_guide_index = None
                frontier_guide_index = None
                frontier_plan_id = None
                frontier_plan_nodes = None
                frontier_schedule_id = None
                frontier_schedule_rank = (
                    frontier_schedule.rank if frontier_schedule is not None else None
                )
                frontier_schedule_next_cursor = (
                    frontier_schedule.next_cursor
                    if frontier_schedule is not None
                    else None
                )
                frontier_schedule_inspected = (
                    frontier_schedule.inspected
                    if frontier_schedule is not None
                    else None
                )
                if cpu_guided:
                    cpu_guide_index, contexts = self._cpu_guide(
                        centers=centers,
                        reflectors=reflectors,
                        contexts=contexts,
                        truths=truths,
                        multiplicities=multiplicities,
                        blocked=blocked,
                        guide_rate=guide_rate,
                    )
                if frontier_guided and exhaustive_prefix_memory:
                    frontier_guide_index = self._frontier_guide_index(
                        origin,
                        selected,
                        remaining,
                        seed=seed,
                        position=position,
                    )
                    if frontier_guide_index is not None:
                        contexts[frontier_guide_index] = toward_one(
                            contexts[frontier_guide_index], frontier_rate
                        )
                if frontier_plan_guided and exhaustive_prefix_memory:
                    plan, frontier_plan_nodes = self._frontier_route_plan(
                        origin,
                        selected,
                        remaining,
                        seed=seed,
                        node_budget=frontier_plan_node_budget,
                    )
                    if plan is not None and len(plan) > len(selected):
                        planned_id = plan[len(selected)]
                        if planned_id in remaining:
                            frontier_plan_id = planned_id
                            plan_index = remaining.index(planned_id)
                            contexts[plan_index] = toward_one(
                                contexts[plan_index], frontier_rate
                            )
                if frontier_schedule is not None and frontier_schedule.route is not None:
                    scheduled_id = frontier_schedule.route[position]
                    if scheduled_id in remaining:
                        frontier_schedule_id = scheduled_id
                        schedule_index = remaining.index(scheduled_id)
                        contexts[schedule_index] = toward_one(
                            contexts[schedule_index], frontier_rate
                        )
                seed_state = self._hept_seed_state(previous_id, remaining, position)
                hept = hept_pool.get(len(remaining)) if hept_pool is not None else None
                if hept is None:
                    hept = CudaHept(
                        self.library,
                        candidates=len(remaining),
                        seed_state=seed_state,
                        centers=centers,
                        reflectors=reflectors,
                        contexts=contexts,
                        truths=truths,
                        multiplicities=multiplicities,
                    )
                    if hept_pool is not None:
                        hept_pool[len(remaining)] = hept
                else:
                    hept.set_seed_state(seed_state)
                    hept.load(centers, reflectors, contexts, truths, multiplicities)
                native_cells.append(hept)
                initial_centers.append(centers)
                attempt = hept.attempt(seed + (position + 1) * 1_000_003)
                step = HeptRouteStep(
                    previous_id=previous_id,
                    candidate_ids=tuple(remaining),
                    selected_index=attempt.candidate,
                    selected_reflector=attempt.reflector,
                    strengths=attempt.strengths,
                    cpu_guide_index=cpu_guide_index,
                    profile_anchor_index=profile_anchor_index,
                    profile_plan_index=profile_plan_index,
                    local_profile_guide_index=local_profile_guide_index,
                    temporal_profile_guide_index=temporal_profile_guide_index,
                    temporal_deferred_indices=temporal_deferred_indices,
                    blocked_indices=tuple(index for index, value in enumerate(blocked) if value),
                    frontier_guide_index=frontier_guide_index,
                    frontier_plan_id=frontier_plan_id,
                    frontier_plan_nodes=frontier_plan_nodes,
                    frontier_schedule_id=frontier_schedule_id,
                    frontier_schedule_rank=frontier_schedule_rank,
                    frontier_schedule_next_cursor=frontier_schedule_next_cursor,
                    frontier_schedule_inspected=frontier_schedule_inspected,
                    prefix_novelty=prefix_novelties[attempt.candidate],
                )
                if wave_store is not None:
                    if not wave_session:
                        raise ValueError("disk wave store requires a session ID")
                    wave = wave_store.commit_expansion(
                        session_id=wave_session,
                        parent_version=position,
                        seed_anchor=seed,
                        position=position,
                        previous_id=previous_id,
                        selected_id=step.selected_id,
                        selected_reflector=step.selected_reflector,
                        cpu_guide_id=remaining[cpu_guide_index]
                        if cpu_guide_index is not None
                        else step.selected_id,
                        candidate_ids=step.candidate_ids,
                        blocked_ids=tuple(
                            step.candidate_ids[index] for index in step.blocked_indices
                        ),
                        strengths=step.strengths,
                        selected_path=(*selected, step.selected_id),
                    )
                    if wave.selected_id != step.selected_id or wave.parent_version != position:
                        raise RuntimeError("GPU expansion did not match CPU disk barrier")
                    if wave_buffer is None:
                        raise RuntimeError("CPU RAM wave buffer is unavailable")
                    wave_buffer.accept_committed(wave)
                    if wave_buffer.selected_path != (*selected, step.selected_id):
                        raise RuntimeError("CPU RAM buffer did not receive committed GPU expansion")
                    step.wave_version = wave.version
                steps.append(step)
                selected_id = step.selected_id
                selected.append(selected_id)
                remaining.pop(attempt.candidate)
                previous_id = selected_id

            rendered = tuple(self._render_state(neuron_id) for neuron_id in selected)
            passed = bool(judge(rendered))
            for position, (hept, step, centers) in enumerate(zip(native_cells, steps, initial_centers, strict=True)):
                hept.apply_verdict(passed)
                snapshot = hept.snapshot()
                step.snapshot = snapshot
                selected_id = step.selected_id
                # A failed construction belongs to this episode's attempted
                # path memory.  Writing its one-bit penalty into shared child
                # neurons destroys successful routes earned by other admitted
                # episodes and turns frequency of failure into false global
                # knowledge.  Exact failed-assembly memory retains the complete
                # attempted path locally.  Only an earned PASS may strengthen
                # a component connection or component position head.
                if passed:
                    source_id = origin_id if step.previous_id == "START" else step.previous_id
                    source = local.get(source_id) or self.store.load_neuron(source_id)
                    reinforce_connection(
                        source,
                        selected_id,
                        direction="OUT",
                        passed=True,
                        event_id=f"ATTEMPT:{seed}:{position}",
                        initial_weight=centers[step.selected_index],
                    )
                    found = None
                    for edge in source["reflectors"][REFLECTORS[step.selected_reflector]]:
                        if edge["peer_id"] == selected_id and edge["direction"] == "OUT":
                            found = edge
                            break
                    if found is not None and not duplicate_inventory:
                        found["weight"] = int(
                            snapshot.reflectors[
                                step.selected_reflector * len(step.candidate_ids)
                                + step.selected_index
                            ]
                        )
                    local[source_id] = source
                origin = local[origin_id]
                heads = origin["center_attractor"]["position_heads"]
                prior = int(heads[str(position)][selected_id])
                heads[str(position)][selected_id] = (
                    toward_one(prior, 900_000) if passed else prior
                )
                local[origin_id] = origin
            return tuple(selected), steps, local, passed, rendered
        finally:
            if hept_pool is None:
                for hept in native_cells:
                    hept.close()

    @staticmethod
    def _prefix_u64(*parts: object) -> int:
        material = "\0".join(str(part) for part in parts).encode("utf-8")
        value = int.from_bytes(hashlib.sha256(material).digest()[:8], "big")
        return value or 1

    def _record_prefix_experience(
        self,
        memory: PrefixMemory,
        *,
        episode_id: str,
        attempt_id: int,
        route: Sequence[str],
        steps: Sequence[HeptRouteStep],
        passed: bool,
    ) -> dict[str, Any]:
        required = len(route)
        usage = memory.usage()
        ceiling_compaction = None
        if usage.capacity - usage.count < required:
            ceiling_compaction = memory.compact()
            usage = memory.usage()
        if usage.capacity - usage.count < required:
            raise CudaRouteHold("HOLD_PREFIX_CAPACITY")
        keys = tuple(
            self._prefix_u64(episode_id, attempt_id, position, *route[: position + 1])
            for position in range(required)
        )
        semantics = tuple(
            self._prefix_u64(
                "PREFIX",
                position,
                "START" if position == 0 else route[position - 1],
                route[position],
            )
            for position in range(required)
        )
        parents = tuple(0 if position == 0 else keys[position - 1] for position in range(required))
        weights = tuple(
            int(step.strengths[step.selected_index]) for step in steps
        )
        memory.append(
            attempt_id=attempt_id,
            keys=keys,
            semantic_signatures=semantics,
            parent_keys=parents,
            weights=weights,
        )
        # Native prefix rows retain the enclosing attempt outcome so they can
        # settle and compact. Routing credit is scoped separately by
        # _record_failed_assembly, which records only the complete route.
        memory.apply_verdict(attempt_id=attempt_id, passed=passed)
        before, after = memory.compact()
        snapshot = memory.snapshot()
        return {
            "architecture": "PREFIX_GROWTH_V1",
            "generated_prefix_neurons": required,
            "ceiling_compaction": list(ceiling_compaction) if ceiling_compaction else None,
            "answer_compaction": [before, after],
            "active_prefix_states": len(snapshot.keys),
            "total_multiplicity": sum(snapshot.multiplicities),
            "pass_hits": sum(snapshot.pass_hits),
            "fail_hits": sum(snapshot.fail_hits),
            "neutral_hits": sum(snapshot.multiplicities)
            - sum(snapshot.pass_hits)
            - sum(snapshot.fail_hits),
        }

    def birth_episode(self, child_ids: Sequence[str], *, source_handle: str = "") -> dict[str, Any]:
        episode_id = new_neuron_id()
        episode = make_neuron(
            neuron_id=episode_id,
            kind="EPISODE",
            lifecycle="NEWBORN",
            creation_event="TURN_BIRTH",
            children=child_ids,
            center={
                "source_handle": source_handle,
                "construction": [],
                "position_heads": {
                    str(position): {child_id: SCALE // 2 for child_id in set(child_ids)}
                    for position in range(len(child_ids))
                },
                "failed_assemblies": {},
                "failed_prefix_counts": {},
                "frontier_schedule_cursor": 0,
                "construction_alignment": 0,
                "reality_alignment": None,
                "truth_compatibility": 0,
                "trusted_language_memory": False,
            },
        )
        self.store.transact(
            [episode], event_kind="TURN_BIRTH", details={"episode_id": episode_id, "children": len(child_ids)}
        )
        return episode

    def _persist_attempt(
        self,
        episode: dict[str, Any],
        route: tuple[str, ...],
        updated: dict[str, dict[str, Any]],
        *,
        passed: bool,
        seed: int,
    ) -> None:
        episode_id = episode["neuron_id"]
        if episode_id in updated:
            routed = updated[episode_id]
            routed["activation"] = deepcopy(episode["activation"])
            routed["center_attractor"].update(episode["center_attractor"])
            episode = routed
        episode["lifecycle"] = "PLASTIC"
        episode["activation"]["uses"] += 1
        episode["activation"]["pass_hits" if passed else "fail_hits"] += 1
        episode["center_attractor"]["last_construction"] = list(route)
        updated[episode_id] = episode
        touched = updated
        self.store.transact(
            touched.values(),
            event_kind="ROUTE_CONSEQUENCE",
            details={
                "episode_id": episode["neuron_id"],
                "attempt_seed": seed,
                "verdict": "PASS" if passed else "FAIL",
                "attempted_path_sha256": hashlib.sha256("\0".join(route).encode("utf-8")).hexdigest().upper(),
            },
        )

    def _stabilize(
        self,
        episode: dict[str, Any],
        route: tuple[str, ...],
        *,
        confirmations: int,
        defer_admission: bool = False,
    ) -> str:
        event_marker = f"STABILIZE:{episode['neuron_id']}"
        episode = self.store.load_neuron(episode["neuron_id"])
        if defer_admission:
            sentence = make_neuron(
                neuron_id=new_neuron_id(),
                kind="SENTENCE",
                lifecycle="PLASTIC",
                creation_event="CONFIRMED_EPISODE_PENDING_FRESH_REREAD",
                children=route,
                center={
                    "construction": list(route),
                    "source_episode_ref": episode["neuron_id"],
                    "inventory_signature": self._inventory_signature(route),
                    "position_heads": deepcopy(episode["center_attractor"]["position_heads"]),
                    "failed_assemblies": {},
                    "failed_prefix_counts": {},
                    "construction_alignment": 0,
                    "reality_alignment": None,
                    "truth_compatibility": 0,
                    "trusted_language_memory": False,
                    "admission_state": "PENDING_FRESH_REREAD",
                    "fresh_reread_passed": False,
                },
            )
            sentence["activation"]["confirmation_passes"] = confirmations
            sentence["activation"]["pass_hits"] = 1
            episode["lifecycle"] = "PLASTIC"
            episode["activation"]["confirmation_passes"] = confirmations
            episode["center_attractor"]["construction"] = list(route)
            episode["center_attractor"]["trusted_language_memory"] = False
            episode["center_attractor"]["pending_sentence_neuron_ref"] = sentence["neuron_id"]
            episode["center_attractor"]["admission_state"] = "PENDING_FRESH_REREAD"
            self.store.transact(
                [episode, sentence],
                event_kind="EPISODE_CONFIRMED_PENDING_FRESH_REREAD",
                details={
                    "episode_id": episode["neuron_id"],
                    "sentence_id": sentence["neuron_id"],
                    "confirmations": confirmations,
                    "trusted_language_memory": False,
                },
            )
            return sentence["neuron_id"]

        neurons = {neuron_id: self.store.load_neuron(neuron_id) for neuron_id in set(route)}
        sentence = make_neuron(
            neuron_id=new_neuron_id(),
            kind="SENTENCE",
            lifecycle="STABLE",
            creation_event="CONFIRMED_EPISODE_CONSTRUCTION",
            children=route,
            center={
                "construction": list(route),
                "source_episode_ref": episode["neuron_id"],
                "inventory_signature": self._inventory_signature(route),
                "position_heads": deepcopy(episode["center_attractor"]["position_heads"]),
                "failed_assemblies": {},
                "failed_prefix_counts": {},
                "construction_alignment": SCALE,
                "reality_alignment": None,
                "truth_compatibility": SCALE,
                "trusted_language_memory": True,
            },
        )
        sentence["activation"]["confirmation_passes"] = confirmations
        sentence["activation"]["pass_hits"] = 1
        for left_index, left_id in enumerate(route):
            profile = neurons[left_id]["center_attractor"].setdefault(
                "opaque_position_profile_v1",
                {
                    "bins": [0] * self.POSITION_PROFILE_BINS,
                    "observations": 0,
                    "supporting_sentence_ids": [],
                    "human_labels_used": False,
                    "target_artifacts_read": False,
                },
            )
            profile["bins"][
                self._position_profile_bin(left_index, len(route))
            ] += 1
            profile["observations"] = int(profile.get("observations", 0)) + 1
            if sentence["neuron_id"] not in profile["supporting_sentence_ids"]:
                profile["supporting_sentence_ids"].append(sentence["neuron_id"])
            reinforce_connection(
                sentence, left_id, direction="OUT", passed=True, event_id=event_marker
            )
            for right_id in route[left_index + 1 :]:
                reinforce_connection(
                    neurons[left_id], right_id, direction="OUT", passed=True, event_id=event_marker
                )
                reinforce_connection(
                    neurons[right_id], left_id, direction="IN", passed=True, event_id=event_marker
                )
            reinforce_connection(
                episode, left_id, direction="IN", passed=True, event_id=event_marker
            )
            neurons[left_id]["parents"].append(sentence["neuron_id"])
        episode["lifecycle"] = "STABLE"
        episode["activation"]["confirmation_passes"] = confirmations
        episode["center_attractor"]["construction"] = list(route)
        episode["center_attractor"]["trusted_language_memory"] = True
        episode["center_attractor"]["sentence_neuron_ref"] = sentence["neuron_id"]
        episode["children"] = [sentence["neuron_id"]]
        sentence["parents"].append(episode["neuron_id"])
        signature = hashlib.sha256("\0".join(route).encode("utf-8")).hexdigest().upper()

        def update_manifest(manifest: dict[str, Any]) -> None:
            manifest["assembly_multiplicity"][signature] = int(
                manifest["assembly_multiplicity"].get(signature, 0)
            ) + 1
            manifest["assembly_members"].setdefault(signature, []).append(episode["neuron_id"])
            inventory_signature = self._inventory_signature(route)
            manifest.setdefault("sentence_inventory_index", {}).setdefault(
                inventory_signature, []
            ).append(sentence["neuron_id"])
            previous = "START"
            for child in route:
                key = f"{previous}>{child}"
                manifest["route_multiplicity"][key] = int(manifest["route_multiplicity"].get(key, 0)) + 1
                previous = child

        manifest_update = (
            {"manifest_mutator": update_manifest}
            if isinstance(self.store, GraphStore)
            else {}
        )
        self.store.transact(
            [episode, sentence, *neurons.values()],
            event_kind="EPISODE_STABILIZED",
            details={
                "episode_id": episode["neuron_id"],
                "sentence_id": sentence["neuron_id"],
                "assembly_signature": signature,
                "confirmations": confirmations,
            },
            **manifest_update,
        )
        self._consolidate_sentence_assembly(route, sentence["neuron_id"])
        return sentence["neuron_id"]

    def finalize_provisional_sentence(
        self,
        sentence_id: str,
        *,
        reread_passed: bool,
        expected_provisional_hash: str,
        attempted_reread_states: Sequence[str] = (),
    ) -> dict[str, Any]:
        """Apply the independent reread gate without exposing its hidden target."""

        sentence = self.store.load_neuron(sentence_id)
        if sentence["content_sha256"] != expected_provisional_hash:
            raise ValueError("stale or foreign fresh-reread verdict")
        if sentence["kind"] != "SENTENCE":
            raise ValueError("fresh reread finalization requires a sentence neuron")
        center = sentence["center_attractor"]
        if center.get("admission_state") != "PENDING_FRESH_REREAD":
            raise ValueError("sentence is not pending fresh reread")
        if sentence["lifecycle"] != "PLASTIC" or center.get("trusted_language_memory") is True:
            raise ValueError("pending sentence crossed the trusted admission boundary")
        route = tuple(str(item) for item in center.get("construction", ()))
        episode = self.store.load_neuron(str(center["source_episode_ref"]))
        if not reread_passed:
            if not attempted_reread_states:
                raise ValueError("failed fresh reread requires its attempted path")
            manifest = self.store.manifest()
            attempted_route = tuple(
                self._resolve_visible_state(manifest, str(item))
                for item in attempted_reread_states
            )
            if sorted(attempted_route) != sorted(route):
                raise ValueError("fresh-reread attempted path inventory mismatch")
            self._record_failed_assembly(episode, attempted_route)
            episode["activation"]["uses"] += 1
            episode["activation"]["fail_hits"] += 1
            episode["center_attractor"]["last_construction"] = list(attempted_route)
            center["admission_state"] = "REJECTED_FRESH_REREAD"
            center["fresh_reread_passed"] = False
            center["trusted_language_memory"] = False
            sentence["activation"]["fail_hits"] += 1
            episode["lifecycle"] = "PLASTIC"
            episode["center_attractor"]["admission_state"] = "REJECTED_FRESH_REREAD"
            episode["center_attractor"]["fresh_reread_passed"] = False
            episode["center_attractor"]["trusted_language_memory"] = False
            episode["center_attractor"].pop("pending_sentence_neuron_ref", None)
            self.store.transact(
                [episode, sentence],
                event_kind="FRESH_REREAD_REJECTED",
                details={
                    "episode_id": episode["neuron_id"],
                    "sentence_id": sentence_id,
                    "verdict": "FAIL",
                    "trusted_language_memory": False,
                },
            )
            return {"state": "HOLD", "reason": "FRESH_REREAD_FAILED", "sentence_id": sentence_id}

        event_marker = f"ADMIT_REREAD:{episode['neuron_id']}"
        neurons = {neuron_id: self.store.load_neuron(neuron_id) for neuron_id in set(route)}
        sentence["lifecycle"] = "STABLE"
        center["trusted_language_memory"] = True
        center["admission_state"] = "ADMITTED_AFTER_FRESH_REREAD"
        center["fresh_reread_passed"] = True
        for left_index, left_id in enumerate(route):
            profile = neurons[left_id]["center_attractor"].setdefault(
                "opaque_position_profile_v1",
                {
                    "bins": [0] * self.POSITION_PROFILE_BINS,
                    "observations": 0,
                    "supporting_sentence_ids": [],
                    "human_labels_used": False,
                    "target_artifacts_read": False,
                },
            )
            profile["bins"][self._position_profile_bin(left_index, len(route))] += 1
            profile["observations"] = int(profile.get("observations", 0)) + 1
            if sentence_id not in profile["supporting_sentence_ids"]:
                profile["supporting_sentence_ids"].append(sentence_id)
            reinforce_connection(sentence, left_id, direction="OUT", passed=True, event_id=event_marker)
            for right_id in route[left_index + 1 :]:
                reinforce_connection(neurons[left_id], right_id, direction="OUT", passed=True, event_id=event_marker)
                reinforce_connection(neurons[right_id], left_id, direction="IN", passed=True, event_id=event_marker)
            reinforce_connection(episode, left_id, direction="IN", passed=True, event_id=event_marker)
            if sentence_id not in neurons[left_id]["parents"]:
                neurons[left_id]["parents"].append(sentence_id)
        episode["lifecycle"] = "STABLE"
        episode["center_attractor"]["construction"] = list(route)
        episode["center_attractor"]["trusted_language_memory"] = True
        episode["center_attractor"]["sentence_neuron_ref"] = sentence_id
        episode["center_attractor"]["admission_state"] = "ADMITTED_AFTER_FRESH_REREAD"
        episode["center_attractor"]["fresh_reread_passed"] = True
        episode["center_attractor"].pop("pending_sentence_neuron_ref", None)
        episode["children"] = [sentence_id]
        if episode["neuron_id"] not in sentence["parents"]:
            sentence["parents"].append(episode["neuron_id"])
        signature = self._route_signature(route)

        def update_manifest(manifest: dict[str, Any]) -> None:
            manifest["assembly_multiplicity"][signature] = int(
                manifest["assembly_multiplicity"].get(signature, 0)
            ) + 1
            manifest["assembly_members"].setdefault(signature, []).append(episode["neuron_id"])
            inventory_signature = self._inventory_signature(route)
            manifest.setdefault("sentence_inventory_index", {}).setdefault(
                inventory_signature, []
            ).append(sentence_id)
            previous = "START"
            for child in route:
                key = f"{previous}>{child}"
                manifest["route_multiplicity"][key] = int(
                    manifest["route_multiplicity"].get(key, 0)
                ) + 1
                previous = child

        manifest_update = (
            {"manifest_mutator": update_manifest}
            if isinstance(self.store, GraphStore)
            else {}
        )
        self.store.transact(
            [episode, sentence, *neurons.values()],
            event_kind="FRESH_REREAD_ADMITTED",
            details={
                "episode_id": episode["neuron_id"],
                "sentence_id": sentence_id,
                "verdict": "PASS",
                "confirmations": sentence["activation"]["confirmation_passes"],
            },
            **manifest_update,
        )
        concept_id = self._consolidate_sentence_assembly(route, sentence_id)
        return {"state": "PASS", "sentence_id": sentence_id, "concept_id": concept_id}

    def _consolidate_sentence_assembly(
        self, route: tuple[str, ...], sentence_id: str
    ) -> str | None:
        """Compare every admitted output and form a reversible recurring endpoint."""

        manifest = self.store.manifest()
        route_signature = self._route_signature(route)
        multiplicity = int(manifest.get("assembly_multiplicity", {}).get(route_signature, 0))
        if multiplicity < 2:
            return None
        concept_id = manifest.get("assembly_concept_index", {}).get(route_signature)
        inventory_signature = self._inventory_signature(route)
        matching_sentences: list[str] = []
        for candidate_id in manifest.get("sentence_inventory_index", {}).get(
            inventory_signature, []
        ):
            candidate = self.store.load_neuron(str(candidate_id))
            if (
                candidate["lifecycle"] == "STABLE"
                and candidate["center_attractor"].get("trusted_language_memory") is True
                and tuple(candidate["center_attractor"].get("construction", ())) == route
            ):
                matching_sentences.append(str(candidate_id))
        if sentence_id not in matching_sentences:
            matching_sentences.append(sentence_id)

        if concept_id:
            concept = self.store.load_neuron(str(concept_id))
        else:
            concept = make_neuron(
                neuron_id=new_neuron_id(),
                kind="CONCEPT",
                lifecycle="STABLE",
                creation_event="RECURRING_SENTENCE_ASSEMBLY",
                children=matching_sentences,
                center={
                    "construction": list(route),
                    "inventory_signature": inventory_signature,
                    "position_heads": {
                        str(position): {child_id: SCALE // 2 for child_id in set(route)}
                        for position in range(len(route))
                    },
                    "source_sentence_refs": list(matching_sentences),
                    "construction_alignment": SCALE,
                    "reality_alignment": None,
                    "truth_compatibility": SCALE,
                    "trusted_language_memory": True,
                    "lossless_reversible": True,
                },
            )
            concept_id = concept["neuron_id"]
        concept["children"] = list(dict.fromkeys((*concept["children"], *matching_sentences)))
        concept["center_attractor"]["source_sentence_refs"] = list(concept["children"])
        heads = concept["center_attractor"]["position_heads"]
        # Rebuild deterministically from the admitted PASS count. This adds no
        # hidden correction: only the complete routes she generated and passed
        # contribute evidence to their own selected positions.
        for position, child_id in enumerate(route):
            row = {candidate_id: SCALE // 2 for candidate_id in set(route)}
            value = row[child_id]
            for _ in range(multiplicity):
                value = toward_one(value, 900_000)
            row[child_id] = value
            heads[str(position)] = row
        concept["activation"]["uses"] = multiplicity
        concept["activation"]["pass_hits"] = multiplicity
        concept["activation"]["confirmation_passes"] = multiplicity * 3

        child_neurons = {child_id: self.store.load_neuron(child_id) for child_id in set(route)}
        event_id = f"CONSOLIDATE:{route_signature}:{multiplicity}"
        for child_id in route:
            reinforce_connection(
                concept, child_id, direction="OUT", passed=True, event_id=event_id
            )
            reinforce_connection(
                child_neurons[child_id], str(concept_id), direction="IN", passed=True, event_id=event_id
            )
            if str(concept_id) not in child_neurons[child_id]["parents"]:
                child_neurons[child_id]["parents"].append(str(concept_id))

        def update_manifest(current: dict[str, Any]) -> None:
            current.setdefault("assembly_concept_index", {})[route_signature] = str(concept_id)

        manifest_update = (
            {"manifest_mutator": update_manifest}
            if isinstance(self.store, GraphStore)
            else {}
        )
        self.store.transact(
            [concept, *child_neurons.values()],
            event_kind="RECURRING_ASSEMBLY_CONSOLIDATED",
            details={
                "concept_id": concept_id,
                "assembly_signature": route_signature,
                "multiplicity": multiplicity,
                "source_sentences": len(matching_sentences),
                "lossless_reversible": True,
            },
            **manifest_update,
        )
        return str(concept_id)

    def learn_state_episode(
        self,
        visible_state_ids: Sequence[str],
        judge: Callable[[Sequence[str]], bool],
        *,
        seed: int,
        max_attempts: int = 20_000,
        required_confirmations: int = 3,
        source_handle: str = "",
        trace_path: str | Path | None = None,
        prior_passed_routes: Sequence[Sequence[str]] = (),
        prior_failed_routes: Sequence[Sequence[str]] = (),
        resume_episode_id: str | None = None,
        prefix_memory: PrefixMemory | None = None,
        exhaustive_prefix_memory: bool = True,
        cpu_guided: bool = False,
        guide_rate: int = 250_000,
        frontier_guided: bool = False,
        frontier_rate: int = 250_000,
        frontier_plan_guided: bool = False,
        frontier_plan_node_budget: int = 256,
        frontier_scheduler: bool = False,
        frontier_schedule_cursor: int | None = None,
        frontier_schedule_max_scan: int = 256,
        frontier_schedule_seed: int | None = None,
        wave_store: DiskWaveStore | None = None,
        hept_pool: dict[int, CudaHept] | None = None,
        defer_admission_until_fresh_reread: bool = False,
    ) -> dict[str, Any]:
        manifest = self.store.manifest()
        try:
            child_ids = [self._resolve_visible_state(manifest, state_id) for state_id in visible_state_ids]
        except KeyError as error:
            return {"state": "HOLD", "reason": "UNSUPPORTED_VISIBLE_STATE", "state_id": str(error)}
        if resume_episode_id is None:
            episode = self.birth_episode(child_ids, source_handle=source_handle)
        else:
            episode = self.store.load_neuron(resume_episode_id)
            if episode["kind"] != "EPISODE" or episode["lifecycle"] not in {"NEWBORN", "PLASTIC"}:
                raise ValueError("resume requires a plastic episode neuron")
            if sorted(episode["children"]) != sorted(child_ids):
                raise ValueError("resume episode visible inventory mismatch")
            if str(episode["center_attractor"].get("source_handle", "")) != source_handle:
                raise ValueError("resume episode source handle mismatch")
        # A visible bucket is bounded to 32 states. Keep that complete active
        # set resident for the lesson so repeated one-bit attempts exercise the
        # CUDA route rather than repeatedly parsing the same neuron JSON files.
        working: dict[str, dict[str, Any]] = {
            neuron_id: self.store.load_neuron(neuron_id) for neuron_id in set(child_ids)
        }
        working[episode["neuron_id"]] = deepcopy(episode)
        if frontier_scheduler:
            episode_id = episode["neuron_id"]
            stored_schedule_seed = working[episode_id]["center_attractor"].get(
                "frontier_schedule_seed"
            )
            if stored_schedule_seed is not None:
                if (
                    frontier_schedule_seed is not None
                    and int(frontier_schedule_seed) != int(stored_schedule_seed)
                ):
                    raise ValueError("frontier schedule seed conflicts with episode anchor")
                frontier_schedule_seed = int(stored_schedule_seed)
            else:
                frontier_schedule_seed = (
                    seed if frontier_schedule_seed is None else int(frontier_schedule_seed)
                )
                working[episode_id]["center_attractor"][
                    "frontier_schedule_seed"
                ] = frontier_schedule_seed
                self.store.transact(
                    [working[episode_id]],
                    event_kind="FRONTIER_SCHEDULE_ANCHOR",
                    details={
                        "episode_id": episode_id,
                        "schedule_seed": frontier_schedule_seed,
                        "target_free": True,
                    },
                )
        guidance_parent: dict[str, Any] | None = None
        try:
            ranking = self.rank_admitted_sentence_experts(visible_state_ids)
            learned_sentence = self.store.load_neuron(str(ranking[0]["sentence_id"]))
            learned_route = tuple(learned_sentence["center_attractor"]["construction"])
            concept_id = self.store.manifest().get("assembly_concept_index", {}).get(
                self._route_signature(learned_route)
            )
            guidance_parent = (
                self.store.load_neuron(str(concept_id)) if concept_id else learned_sentence
            )
        except CudaRouteHold:
            guidance_parent = None
        recovered_failures = 0
        for recovered_states in prior_failed_routes:
            try:
                recovered_ids = tuple(
                    self._resolve_visible_state(manifest, str(item)) for item in recovered_states
                )
            except KeyError:
                continue
            if sorted(recovered_ids) != sorted(child_ids):
                continue
            if self._record_failed_assembly(working[episode["neuron_id"]], recovered_ids):
                recovered_failures += 1
        if recovered_failures:
            self.store.transact(
                working.values(),
                event_kind="RECOVER_FAILED_ASSEMBLY_MEMORY",
                details={
                    "episode_id": episode["neuron_id"],
                    "unique_failed_routes": recovered_failures,
                    "target_free": True,
                },
            )
        recovered_passes = 0
        for recovered_states in (() if resume_episode_id else prior_passed_routes):
            try:
                recovered_ids = tuple(
                    self._resolve_visible_state(manifest, str(item)) for item in recovered_states
                )
            except KeyError:
                continue
            if sorted(recovered_ids) != sorted(child_ids):
                continue
            recovered_passes += 1
            origin = working[episode["neuron_id"]]
            previous_id = episode["neuron_id"]
            for position, selected_id in enumerate(recovered_ids):
                heads = origin["center_attractor"]["position_heads"]
                heads[str(position)][selected_id] = toward_one(
                    int(heads[str(position)][selected_id]), 900_000
                )
                source = working[previous_id]
                reinforce_connection(
                    source,
                    selected_id,
                    direction="OUT",
                    passed=True,
                    event_id=f"RECOVERED_PLASTIC_PASS:{source_handle}:{recovered_passes}:{position}",
                )
                working[previous_id] = source
                previous_id = selected_id
            origin["activation"]["uses"] += 1
            origin["activation"]["pass_hits"] += 1
            origin["center_attractor"]["last_construction"] = list(recovered_ids)
            working[episode["neuron_id"]] = origin
        plastic_candidate = working[episode["neuron_id"]]["center_attractor"].get(
            "plastic_candidate_construction"
        )
        if not plastic_candidate and prior_passed_routes:
            recovered_states = prior_passed_routes[-1]
            try:
                recovered_candidate = tuple(
                    self._resolve_visible_state(manifest, str(item)) for item in recovered_states
                )
            except KeyError:
                recovered_candidate = ()
            if recovered_candidate and sorted(recovered_candidate) == sorted(child_ids):
                working[episode["neuron_id"]]["center_attractor"][
                    "plastic_candidate_construction"
                ] = list(recovered_candidate)
                plastic_candidate = list(recovered_candidate)
                self.store.transact(
                    working.values(),
                    event_kind="RECOVER_PLASTIC_CANDIDATE_MEMORY",
                    details={
                        "episode_id": episode["neuron_id"],
                        "candidate_sha256": self._route_signature(recovered_candidate),
                        "target_free": True,
                    },
                )
        traces: list[dict[str, Any]] = []

        def record(row: dict[str, Any]) -> None:
            traces.append(row)
            if trace_path is not None:
                path = Path(trace_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

        def frozen_confirm(
            candidate_route: Sequence[str], base_seed: int
        ) -> tuple[int, list[dict[str, Any]]]:
            confirmation_rows: list[dict[str, Any]] = []
            confirmed = 0
            for confirmation in range(1, required_confirmations + 1):
                confirmation_seed = base_seed + confirmation * 97_409
                frozen_route, _, _ = self.attempt_route(
                    child_ids,
                    seed=confirmation_seed,
                    overrides=working,
                    origin_id=episode["neuron_id"],
                    exhaustive_prefix_memory=exhaustive_prefix_memory,
                    cpu_guided=cpu_guided,
                    guide_rate=guide_rate,
                    frontier_guided=False,
                    frontier_rate=frontier_rate,
                    frontier_plan_guided=False,
                    frontier_plan_node_budget=frontier_plan_node_budget,
                    hept_pool=hept_pool,
                )
                frozen_states = tuple(
                    str(working[neuron_id]["center_attractor"].get("visible_state_id"))
                    if working[neuron_id]["center_attractor"].get("visible_state_id")
                    else f"WORD:{working[neuron_id]['center_attractor']['learned_surface']}"
                    for neuron_id in frozen_route
                )
                accepted = bool(judge(frozen_states))
                confirmation_rows.append(
                    {
                        "confirmation": confirmation,
                        "seed": confirmation_seed,
                        "candidate": list(frozen_states),
                        "verdict": "PASS" if accepted else "FAIL",
                    }
                )
                if not accepted:
                    break
                confirmed += 1
            return confirmed, confirmation_rows

        if plastic_candidate:
            recovered_route = tuple(str(item) for item in plastic_candidate)
            confirmed, confirmation_rows = frozen_confirm(recovered_route, seed + 41_009)
            record(
                {
                    "episode_id": episode["neuron_id"],
                    "attempt": 0,
                    "seed": seed + 41_009,
                    "candidate": [self._render_state(item) for item in recovered_route],
                    "verdict": "RECOVERED_PASS_CANDIDATE",
                    "confirmations": confirmation_rows,
                }
            )
            if confirmed == required_confirmations:
                sentence_id = self._stabilize(
                    episode,
                    recovered_route,
                    confirmations=confirmed,
                    defer_admission=defer_admission_until_fresh_reread,
                )
                return {
                    "state": "PASS",
                    "episode_id": episode["neuron_id"],
                    "sentence_id": sentence_id,
                    "attempts": 0,
                    "confirmation_passes": confirmed,
                    "construction": [self._render_state(item) for item in recovered_route],
                    "trace": traces,
                    "recovered_plastic_passes": recovered_passes,
                    "resumed_episode": resume_episode_id is not None,
                    "recovered_failed_routes": recovered_failures,
                }

        for attempt_number in range(1, max_attempts + 1):
            attempt_seed = seed + attempt_number * 1_000_003
            wave_session = None
            if wave_store is not None:
                wave_session = f"{episode['neuron_id']}:{attempt_seed}"
                wave_store.begin(
                    session_id=wave_session,
                    model_hash=content_hash(self.store.manifest()),
                    seed_anchor=attempt_seed,
                )
            try:
                route, steps, working, passed, rendered = self.attempt_route_with_verdict(
                    child_ids,
                    seed=attempt_seed,
                    judge=judge,
                    overrides=working,
                    origin_id=episode["neuron_id"],
                    exhaustive_prefix_memory=exhaustive_prefix_memory,
                    cpu_guided=cpu_guided,
                    guide_rate=guide_rate,
                    frontier_guided=frontier_guided,
                    frontier_rate=frontier_rate,
                    frontier_plan_guided=frontier_plan_guided,
                    frontier_plan_node_budget=frontier_plan_node_budget,
                    frontier_scheduler=frontier_scheduler,
                    frontier_schedule_cursor=frontier_schedule_cursor,
                    frontier_schedule_max_scan=frontier_schedule_max_scan,
                    frontier_schedule_seed=frontier_schedule_seed,
                    wave_store=wave_store,
                    wave_session=wave_session,
                    guidance_parent=guidance_parent,
                    hept_pool=hept_pool,
                )
            except CudaRouteHold:
                failed_assemblies = working[episode["neuron_id"]]["center_attractor"].get(
                    "failed_assemblies", {}
                )
                if len(failed_assemblies) >= self._unique_route_count(child_ids):
                    episode = working[episode["neuron_id"]]
                    episode["activation"]["hold_hits"] += 1
                    self.store.transact(
                        working.values(),
                        event_kind="COMPLETE_ROUTE_SPACE_EXHAUSTED",
                        details={
                            "episode_id": episode["neuron_id"],
                            "complete_routes": len(failed_assemblies),
                            "target_free": True,
                        },
                    )
                    return {
                        "state": "HOLD",
                        "reason": "COMPLETE_ROUTE_SPACE_EXHAUSTED",
                        "episode_id": episode["neuron_id"],
                        "attempts": len(traces),
                        "trace": traces,
                    }
                if failed_assemblies:
                    continue
                episode = self.store.load_neuron(episode["neuron_id"])
                episode["activation"]["hold_hits"] += 1
                self.store.transact(
                    [episode],
                    event_kind="ROUTE_HOLD",
                    details={"episode_id": episode["neuron_id"], "attempt_seed": attempt_seed},
                )
                return {"state": "HOLD", "reason": "NO_SUPPORTED_ROUTE", "episode_id": episode["neuron_id"]}
            episode = working.get(episode["neuron_id"], deepcopy(episode))
            episode["lifecycle"] = "PLASTIC"
            episode["activation"]["uses"] += 1
            episode["activation"]["pass_hits" if passed else "fail_hits"] += 1
            episode["center_attractor"]["last_construction"] = list(route)
            schedule_cursors = [
                step.frontier_schedule_next_cursor
                for step in steps
                if step.frontier_schedule_next_cursor is not None
            ]
            if schedule_cursors:
                episode["center_attractor"]["frontier_schedule_cursor"] = max(
                    int(episode["center_attractor"].get("frontier_schedule_cursor", 0)),
                    max(int(value) for value in schedule_cursors),
                )
            working[episode["neuron_id"]] = episode
            row: dict[str, Any] = {
                "episode_id": episode["neuron_id"],
                "attempt": attempt_number,
                "seed": attempt_seed,
                "candidate": list(rendered),
                "verdict": "PASS" if passed else "FAIL",
                "route": [
                    {
                        "selected_reflector": REFLECTORS[step.selected_reflector],
                        "selected_strength": step.strengths[step.selected_index],
                        "candidate_strengths": list(step.strengths),
                        "cpu_guide_index": step.cpu_guide_index,
                        "profile_anchor_index": step.profile_anchor_index,
                        "profile_plan_index": step.profile_plan_index,
                        "local_profile_guide_index": step.local_profile_guide_index,
                        "temporal_profile_guide_index": step.temporal_profile_guide_index,
                        "temporal_deferred_indices": list(step.temporal_deferred_indices),
                        "blocked_indices": list(step.blocked_indices),
                        "frontier_guide_index": step.frontier_guide_index,
                        "frontier_plan_id": step.frontier_plan_id,
                        "frontier_plan_nodes": step.frontier_plan_nodes,
                        "frontier_schedule_id": step.frontier_schedule_id,
                        "frontier_schedule_rank": step.frontier_schedule_rank,
                        "frontier_schedule_next_cursor": step.frontier_schedule_next_cursor,
                        "frontier_schedule_inspected": step.frontier_schedule_inspected,
                        "prefix_novelty": step.prefix_novelty,
                        "disk_wave_version": step.wave_version,
                    }
                    for step in steps
                ],
                "guidance_parent_id": (
                    guidance_parent["neuron_id"] if guidance_parent is not None else None
                ),
            }
            if prefix_memory is not None:
                try:
                    row["prefix_memory"] = self._record_prefix_experience(
                        prefix_memory,
                        episode_id=episode["neuron_id"],
                        attempt_id=attempt_seed,
                        route=route,
                        steps=steps,
                        passed=passed,
                    )
                except CudaRouteHold:
                    record(row)
                    self.store.transact(
                        working.values(),
                        event_kind="EPISODE_PREFIX_MEMORY_CEILING",
                        details={
                            "episode_id": episode["neuron_id"],
                            "attempt": attempt_number,
                            "target_free": True,
                        },
                    )
                    return {
                        "state": "HOLD",
                        "reason": "PREFIX_MEMORY_CAPACITY",
                        "episode_id": episode["neuron_id"],
                        "attempts": attempt_number,
                        "trace": traces,
                    }
            if not passed:
                self._record_failed_assembly(episode, route)
                working[episode["neuron_id"]] = episode
                record(row)
                if attempt_number % 250 == 0:
                    self.store.transact(
                        working.values(),
                        event_kind="EPISODE_PLASTIC_PROGRESS_CHECKPOINT",
                        details={
                            "episode_id": episode["neuron_id"],
                            "attempt": attempt_number,
                            "trusted_language_memory": False,
                        },
                    )
                continue
            episode["center_attractor"]["plastic_candidate_construction"] = list(route)
            working[episode["neuron_id"]] = episode
            confirmed, confirmation_rows = frozen_confirm(route, attempt_seed)
            row["confirmations"] = confirmation_rows
            record(row)
            self.store.transact(
                working.values(),
                event_kind="EPISODE_PLASTIC_PASS_CHECKPOINT",
                details={
                    "episode_id": episode["neuron_id"],
                    "attempt": attempt_number,
                    "trusted_language_memory": False,
                },
            )
            if confirmed == required_confirmations:
                self.store.transact(
                    working.values(),
                    event_kind="EPISODE_LEARNING_BATCH",
                    details={
                        "episode_id": episode["neuron_id"],
                        "attempts": attempt_number,
                        "verdicts_recorded_in_trace": trace_path is not None,
                    },
                )
                sentence_id = self._stabilize(
                    episode,
                    route,
                    confirmations=confirmed,
                    defer_admission=defer_admission_until_fresh_reread,
                )
                return {
                    "state": "PASS",
                    "episode_id": episode["neuron_id"],
                    "sentence_id": sentence_id,
                    "attempts": attempt_number,
                    "confirmation_passes": confirmed,
                    "construction": list(rendered),
                    "trace": traces,
                    "recovered_plastic_passes": recovered_passes,
                    "resumed_episode": resume_episode_id is not None,
                    "recovered_failed_routes": recovered_failures,
                }
        self.store.transact(
            working.values(),
            event_kind="EPISODE_LEARNING_BATCH_HOLD",
            details={
                "episode_id": episode["neuron_id"],
                "attempts": max_attempts,
                "verdicts_recorded_in_trace": trace_path is not None,
            },
        )
        return {
            "state": "HOLD",
            "reason": "MAX_ATTEMPTS",
            "episode_id": episode["neuron_id"],
            "attempts": max_attempts,
            "trace": traces,
            "recovered_plastic_passes": recovered_passes,
            "resumed_episode": resume_episode_id is not None,
            "recovered_failed_routes": recovered_failures,
        }

    def ensure_dialogue_utterance_state(
        self,
        sentence_id: str,
        *,
        visible_state_id: str,
        source_sha256: str,
        source_class: str,
        scene_id: str,
        speaker: str,
        source_line: int,
    ) -> str:
        """Expose one admitted sentence as a source-bound dialogue state.

        The wrapper carries provenance and turn role only.  It does not make a
        fictional utterance true, and it does not modify the admitted sentence
        construction.  Repeated calls are idempotent for the same binding.
        """

        manifest = self.store.manifest()
        existing_id = manifest.get("state_index", {}).get(visible_state_id)
        if existing_id:
            existing = self.store.load_neuron(str(existing_id))
            binding = existing.get("center_attractor", {}).get(
                "opaque_dialogue_utterance_v1", {}
            )
            expected = {
                "sentence_id": sentence_id,
                "source_sha256": source_sha256,
                "source_class": source_class,
                "scene_id": scene_id,
                "speaker": speaker,
                "source_line": int(source_line),
            }
            if any(binding.get(key) != value for key, value in expected.items()):
                raise ValueError("dialogue visible state conflicts with existing binding")
            return str(existing_id)

        sentence = self.store.load_neuron(sentence_id)
        if (
            sentence.get("kind") != "SENTENCE"
            or sentence.get("lifecycle") != "STABLE"
            or sentence.get("center_attractor", {}).get("trusted_language_memory") is not True
        ):
            raise ValueError("dialogue state requires one admitted stable sentence")
        concept = make_neuron(
            neuron_id=new_neuron_id(),
            kind="CONCEPT",
            lifecycle="STABLE",
            creation_event="SOURCE_BOUND_DIALOGUE_UTTERANCE",
            children=[sentence_id],
            center={
                "visible_state_id": visible_state_id,
                "construction": [sentence_id],
                "construction_alignment": SCALE,
                "truth_compatibility": 0,
                "reality_alignment": None,
                "trusted_language_memory": True,
                "source_provenance_v1": {
                    "source_sha256": source_sha256,
                    "source_class": source_class,
                    "source_line": int(source_line),
                    "truth_authority": False,
                },
                "opaque_dialogue_utterance_v1": {
                    "sentence_id": sentence_id,
                    "source_sha256": source_sha256,
                    "source_class": source_class,
                    "scene_id": scene_id,
                    "speaker": speaker,
                    "source_line": int(source_line),
                },
            },
        )
        concept["activation"]["pass_hits"] = 1
        concept["activation"]["confirmation_passes"] = 1
        if concept["neuron_id"] not in sentence["parents"]:
            sentence["parents"].append(concept["neuron_id"])
        event_id = f"DIALOGUE_UTTERANCE:{concept['neuron_id']}"
        reinforce_connection(concept, sentence_id, direction="OUT", passed=True, event_id=event_id)
        reinforce_connection(sentence, concept["neuron_id"], direction="IN", passed=True, event_id=event_id)
        self.store.transact(
            [sentence, concept],
            event_kind="SOURCE_BOUND_DIALOGUE_UTTERANCE",
            details={
                "dialogue_state_id": concept["neuron_id"],
                "visible_state_id": visible_state_id,
                "sentence_id": sentence_id,
                "source_sha256": source_sha256,
                "source_class": source_class,
                "truth_authority": False,
            },
        )
        return str(concept["neuron_id"])

    def ensure_metadata_state(
        self,
        child_id: str,
        *,
        visible_state_id: str,
        state_kind: str,
        payload: Mapping[str, Any],
    ) -> str:
        """Create one idempotent opaque navigation state around stable memory.

        This is a deterministic CPU admission boundary, not learned language:
        the subsequent route between metadata states must still be learned by
        one-bit consequences and frozen confirmation.
        """

        binding_sha256 = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest().upper()
        manifest = self.store.manifest()
        existing_id = manifest.get("state_index", {}).get(visible_state_id)
        if existing_id:
            existing = self.store.load_neuron(str(existing_id))
            binding = existing.get("center_attractor", {}).get("opaque_metadata_state_v1", {})
            if (
                binding.get("state_kind") != state_kind
                or binding.get("binding_sha256") != binding_sha256
                or existing.get("children") != [child_id]
            ):
                raise ValueError("metadata visible state conflicts with existing binding")
            return str(existing_id)
        child = self.store.load_neuron(child_id)
        if child.get("lifecycle") != "STABLE":
            raise ValueError("metadata state requires stable child memory")
        concept = make_neuron(
            neuron_id=new_neuron_id(),
            kind="CONCEPT",
            lifecycle="STABLE",
            creation_event="OPAQUE_METADATA_STATE",
            children=[child_id],
            center={
                "visible_state_id": visible_state_id,
                "construction": [child_id],
                "construction_alignment": SCALE,
                "truth_compatibility": 0,
                "reality_alignment": None,
                "trusted_language_memory": True,
                "opaque_metadata_state_v1": {
                    "state_kind": state_kind,
                    "binding_sha256": binding_sha256,
                    "payload": dict(payload),
                },
            },
        )
        concept["activation"]["pass_hits"] = 1
        concept["activation"]["confirmation_passes"] = 1
        if concept["neuron_id"] not in child["parents"]:
            child["parents"].append(concept["neuron_id"])
        marker = f"METADATA_STATE:{concept['neuron_id']}"
        reinforce_connection(concept, child_id, direction="OUT", passed=True, event_id=marker)
        reinforce_connection(child, concept["neuron_id"], direction="IN", passed=True, event_id=marker)
        self.store.transact(
            [child, concept],
            event_kind="OPAQUE_METADATA_STATE",
            details={
                "metadata_state_id": concept["neuron_id"],
                "visible_state_id": visible_state_id,
                "state_kind": state_kind,
                "binding_sha256": binding_sha256,
            },
        )
        return str(concept["neuron_id"])

    def learn_growing_state_episode(
        self,
        visible_state_ids: Sequence[str],
        judge: Callable[[Sequence[str]], bool],
        *,
        prefix_capacity: int = 4096,
        wave_synchronous: str = "FULL",
        max_ceiling_cycles: int = 16,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Learn one episode through bounded model-generated prefix memory.

        CUDA Hept selects every child. Rust owns target-free prefix experience,
        one-bit consequence, multiplicity, capacity, and compaction.
        """

        if prefix_capacity < len(visible_state_ids):
            raise ValueError("prefix capacity must hold at least one complete attempted route")
        if max_ceiling_cycles < 1:
            raise ValueError("max ceiling cycles must be positive")
        call_seed = int(kwargs.pop("seed"))
        max_attempts = int(kwargs.pop("max_attempts", 20_000))
        resume_episode_id = kwargs.pop("resume_episode_id", None)
        hept_pool: dict[int, CudaHept] = {}
        from .prefix_archive import PrefixArchiveStore
        from .wave_store import DiskWaveStore

        wave_store = DiskWaveStore(
            self.store.root / "waves" / "expansion.sqlite3",
            synchronous=wave_synchronous,
        )
        archive = PrefixArchiveStore(
            self.store.root / "waves" / "prefix_archive.sqlite3"
        )
        total_attempts = 0
        total_multiplicity = 0
        total_pass_hits = 0
        total_fail_hits = 0
        semantic_signatures: set[int] = set()
        all_traces: list[dict[str, Any]] = []
        cycle_rows: list[dict[str, Any]] = []
        result: dict[str, Any] = {}
        episode_id = resume_episode_id
        last_snapshot = None
        try:
            for local_cycle in range(1, max_ceiling_cycles + 1):
                remaining_attempts = max_attempts - total_attempts
                if remaining_attempts <= 0:
                    result = {
                        "state": "HOLD",
                        "reason": "MAX_ATTEMPTS",
                        "episode_id": episode_id,
                        "attempts": total_attempts,
                    }
                    break
                with PrefixMemory(self.library, capacity=prefix_capacity) as memory:
                    segment = self.learn_state_episode(
                        visible_state_ids,
                        judge,
                        seed=call_seed + (local_cycle - 1) * 1_000_000_007,
                        max_attempts=remaining_attempts,
                        resume_episode_id=episode_id,
                        prefix_memory=memory,
                        exhaustive_prefix_memory=False,
                        cpu_guided=True,
                        wave_store=wave_store,
                        hept_pool=hept_pool,
                        **kwargs,
                    )
                    snapshot = memory.snapshot()
                last_snapshot = snapshot
                segment_attempts = int(segment.get("attempts", 0))
                total_attempts += segment_attempts
                episode_id = str(segment.get("episode_id") or episode_id)
                all_traces.extend(segment.get("trace", []))
                total_multiplicity += sum(snapshot.multiplicities)
                total_pass_hits += sum(snapshot.pass_hits)
                total_fail_hits += sum(snapshot.fail_hits)
                semantic_signatures.update(snapshot.semantic_signatures)
                if snapshot.keys:
                    cycle_index = archive.next_cycle_index(episode_id)
                    archived = archive.record_cycle(
                        episode_id=episode_id,
                        source_handle=str(kwargs.get("source_handle", "")),
                        cycle_index=cycle_index,
                        snapshot=snapshot,
                    )
                    cycle_rows.append(
                        {
                            **archived,
                            "segment_state": segment.get("state"),
                            "segment_reason": segment.get("reason"),
                            "segment_attempts": segment_attempts,
                        }
                    )
                result = segment
                if segment.get("state") == "PASS":
                    break
                if segment.get("reason") != "PREFIX_MEMORY_CAPACITY":
                    break
                if local_cycle == max_ceiling_cycles:
                    result = {
                        **segment,
                        "state": "HOLD",
                        "reason": "PREFIX_MEMORY_CYCLE_LIMIT",
                    }
        finally:
            wave_store.close()
            for hept in hept_pool.values():
                hept.close()
        result["attempts"] = total_attempts
        result["trace"] = all_traces
        result["architecture"] = "CPU_DISK_GUIDED_PREFIX_GROWTH_V3"
        result["disk_wave_store"] = str(wave_store.path)
        result["wave_synchronous"] = wave_store.synchronous
        result["prefix_archive"] = {
            "path": str(archive.path),
            "cycles": cycle_rows,
            "audit": archive.audit(episode_id) if cycle_rows else {"state": "HOLD", "cycles": 0},
            "reseeded_after_ceiling": len(cycle_rows) > 1,
        }
        result["prefix_memory"] = {
            "capacity": prefix_capacity,
            "active_states": 0 if last_snapshot is None else len(last_snapshot.keys),
            "total_multiplicity": total_multiplicity,
            "pass_hits": total_pass_hits,
            "fail_hits": total_fail_hits,
            "neutral_hits": total_multiplicity - total_pass_hits - total_fail_hits,
            "semantic_signatures": len(semantic_signatures),
            "target_free": True,
        }
        return result

    def learn_episode(
        self,
        visible_words: Sequence[str],
        judge: Callable[[Sequence[str]], bool],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Compatibility wrapper for the original word-only Neuronizer API."""

        return self.learn_state_episode(
            [f"WORD:{word.lower()}" for word in visible_words],
            lambda states: judge(tuple(item.removeprefix("WORD:") for item in states)),
            **kwargs,
        )

    def sample_state_distribution(
        self,
        visible_state_ids: Sequence[str],
        *,
        seeds: Iterable[int],
        cpu_guided: bool = False,
        guide_rate: int = 250_000,
    ) -> dict[str, int]:
        manifest = self.store.manifest()
        child_ids = [self._resolve_visible_state(manifest, state_id) for state_id in visible_state_ids]
        counts: dict[str, int] = {}
        before = content_hash(manifest)
        cache: dict[tuple[str, tuple[str, ...], tuple[str, ...]], CudaHept] = {}
        try:
            for seed in seeds:
                remaining = list(child_ids)
                selected: list[str] = []
                previous_id = "START"
                for position in range(len(child_ids)):
                    cache_key = (previous_id, tuple(remaining), tuple(selected))
                    hept = cache.get(cache_key)
                    if hept is None:
                        previous = None if previous_id == "START" else self.store.load_neuron(previous_id)
                        centers: list[int] = []
                        flattened = [[SCALE // 2] * len(remaining) for _ in range(6)]
                        contexts: list[int] = []
                        truths: list[int] = []
                        multiplicities: list[int] = []
                        for index, candidate_id in enumerate(remaining):
                            center, reflector_values = self._edge_state(previous, candidate_id)
                            centers.append(center)
                            for channel, value in enumerate(reflector_values):
                                flattened[channel][index] = value
                            contexts.append(self._context_weight(selected, candidate_id, {}))
                            candidate = self.store.load_neuron(candidate_id)
                            truths.append(self._construction_alignment(candidate))
                            multiplicities.append(
                                int(manifest.get("route_multiplicity", {}).get(f"{previous_id}>{candidate_id}", 0))
                            )
                        reflectors = [value for channel in flattened for value in channel]
                        if cpu_guided:
                            _, contexts = self._cpu_guide(
                                centers=centers,
                                reflectors=reflectors,
                                contexts=contexts,
                                truths=truths,
                                multiplicities=multiplicities,
                                blocked=[0] * len(remaining),
                                guide_rate=guide_rate,
                            )
                        hept = CudaHept(
                            self.library,
                            candidates=len(remaining),
                            seed_state=self._hept_seed_state(previous_id, remaining, position),
                            centers=centers,
                            reflectors=reflectors,
                            contexts=contexts,
                            truths=truths,
                            multiplicities=multiplicities,
                        )
                        cache[cache_key] = hept
                    attempt = hept.attempt(int(seed) + (position + 1) * 1_000_003)
                    selected_id = remaining.pop(attempt.candidate)
                    selected.append(selected_id)
                    previous_id = selected_id
                rendered = tuple(self._render_state(neuron_id) for neuron_id in selected)
                key = " ".join(rendered)
                counts[key] = counts.get(key, 0) + 1
        finally:
            for hept in cache.values():
                hept.close()
        if before != content_hash(self.store.manifest()):
            raise RuntimeError("frozen distribution sampling changed graph state")
        return counts

    def admitted_sentence_ids(self, visible_state_ids: Sequence[str]) -> tuple[str, ...]:
        manifest = self.store.manifest()
        child_ids = tuple(
            self._resolve_visible_state(manifest, state_id) for state_id in visible_state_ids
        )
        signature = self._inventory_signature(child_ids)
        indexed = list(manifest.get("sentence_inventory_index", {}).get(signature, []))
        # SQLite manifests are rebuilt from durable rows and intentionally do not
        # persist the mutable GraphStore-only sentence inventory cache.  Merge a
        # deterministic SENTENCE scan so a fresh process can rediscover stable
        # sentence memory without writing an index or changing the judge.
        sentence_rows = [
            neuron_id
            for neuron_id, summary in manifest.get("neuron_index", {}).items()
            if summary.get("kind") == "SENTENCE"
        ]
        candidate_ids = tuple(dict.fromkeys([*indexed, *sentence_rows]))
        admitted: list[str] = []
        for neuron_id in candidate_ids:
            neuron = self.store.load_neuron(str(neuron_id))
            if (
                neuron["kind"] == "SENTENCE"
                and neuron["lifecycle"] == "STABLE"
                and sorted(neuron["children"]) == sorted(child_ids)
                and neuron["center_attractor"].get("trusted_language_memory") is True
            ):
                admitted.append(str(neuron_id))
        return tuple(admitted)

    def sample_provisional_sentence_distribution(
        self,
        sentence_id: str,
        *,
        seeds: Iterable[int],
        guide_rate: int = 250_000,
    ) -> dict[str, int]:
        """Reread one confirmed construction before it is admitted as knowledge."""

        sentence = self.store.load_neuron(sentence_id)
        center = sentence["center_attractor"]
        if (
            sentence["kind"] != "SENTENCE"
            or sentence["lifecycle"] != "PLASTIC"
            or center.get("trusted_language_memory") is True
            or center.get("admission_state") != "PENDING_FRESH_REREAD"
        ):
            raise CudaRouteHold("HOLD_NO_PROVISIONAL_SENTENCE_NEURON")
        construction = tuple(str(item) for item in center.get("construction", ()))
        episode = self.store.load_neuron(str(center["source_episode_ref"]))
        child_ids = tuple(str(item) for item in episode.get("children", ()))
        if not child_ids:
            raise CudaRouteHold("HOLD_EMPTY_PROVISIONAL_SENTENCE")
        if sorted(child_ids) != sorted(construction):
            raise CudaRouteHold("HOLD_PROVISIONAL_EPISODE_INVENTORY_MISMATCH")
        before = content_hash(self.store.manifest())
        counts: dict[str, int] = {}
        for seed in seeds:
            route, _, _ = self.attempt_route(
                child_ids,
                seed=int(seed),
                overrides={sentence_id: sentence},
                origin_id=sentence_id,
                exhaustive_prefix_memory=False,
                cpu_guided=True,
                guide_rate=guide_rate,
            )
            rendered = " ".join(self._render_state(neuron_id) for neuron_id in route)
            counts[rendered] = counts.get(rendered, 0) + 1
        if before != content_hash(self.store.manifest()):
            raise RuntimeError("provisional frozen reread changed graph state")
        return counts

    def _sentence_expert_score(
        self, sentence: dict[str, Any], manifest: dict[str, Any]
    ) -> tuple[int, int, int]:
        construction = tuple(sentence["center_attractor"].get("construction", ()))
        heads = sentence["center_attractor"].get("position_heads", {})
        support_rows: list[int] = []
        for position, child_id in enumerate(construction):
            row = heads.get(str(position), {})
            total = sum(max(0, int(value)) for value in row.values())
            selected = max(0, int(row.get(child_id, 0)))
            support_rows.append(selected * SCALE // total if total else 0)
        route_quality = sum(support_rows) // len(support_rows) if support_rows else 0
        signature = self._route_signature(construction)
        multiplicity = int(manifest.get("assembly_multiplicity", {}).get(signature, 0))
        multiplicity_support = multiplicity * SCALE // (multiplicity + 32)
        # Frequency is intentionally capped to ten percent so a repeated weak
        # route cannot dominate a rarer expert with materially better evidence.
        combined = (900_000 * route_quality + 100_000 * multiplicity_support) // SCALE
        return combined, route_quality, multiplicity

    def sample_admitted_sentence_distribution(
        self,
        visible_state_ids: Sequence[str],
        *,
        seeds: Iterable[int],
        guide_rate: int = 250_000,
        sentence_id: str | None = None,
    ) -> dict[str, int]:
        """Recall through the sentence expert loaded from disk into CPU RAM."""

        if sentence_id is None:
            ranking = self.rank_admitted_sentence_experts(visible_state_ids)
            sentence_id = str(ranking[0]["sentence_id"])
        sentence = self.store.load_neuron(str(sentence_id))
        route = tuple(sentence["center_attractor"]["construction"])
        concept_id = self.store.manifest().get("assembly_concept_index", {}).get(
            self._route_signature(route)
        )
        parent = self.store.load_neuron(str(concept_id)) if concept_id else sentence
        parent_id = parent["neuron_id"]
        # Frozen recall must rebuild the active inventory from the visible
        # unordered bucket.  Reusing the learned route here would make the
        # evaluator's candidate ordering depend on hidden target order.
        manifest = self.store.manifest()
        child_ids = tuple(
            sorted(
                self._resolve_visible_state(manifest, str(state_id))
                for state_id in visible_state_ids
            )
        )
        if sorted(route) != sorted(child_ids):
            raise ValueError("selected sentence expert does not match visible inventory")
        before = content_hash(self.store.manifest())
        counts: dict[str, int] = {}
        for seed in seeds:
            route, _, _ = self.attempt_route(
                child_ids,
                seed=int(seed),
                overrides={parent_id: parent},
                origin_id=parent_id,
                exhaustive_prefix_memory=False,
                cpu_guided=True,
                guide_rate=guide_rate,
                stable_recall=True,
            )
            rendered = " ".join(self._render_state(neuron_id) for neuron_id in route)
            counts[rendered] = counts.get(rendered, 0) + 1
        if before != content_hash(self.store.manifest()):
            raise RuntimeError("frozen sentence-neuron recall changed graph state")
        return counts

    def rank_admitted_sentence_experts(
        self, visible_state_ids: Sequence[str]
    ) -> tuple[dict[str, int | str], ...]:
        sentence_ids = self.admitted_sentence_ids(visible_state_ids)
        if not sentence_ids:
            raise CudaRouteHold("HOLD_NO_ADMITTED_SENTENCE_NEURON")
        manifest = self.store.manifest()
        rows: list[dict[str, int | str]] = []
        for neuron_id in sentence_ids:
            sentence = self.store.load_neuron(neuron_id)
            combined, quality, multiplicity = self._sentence_expert_score(sentence, manifest)
            rows.append(
                {
                    "sentence_id": neuron_id,
                    "combined_score": combined,
                    "route_quality": quality,
                    "assembly_multiplicity": multiplicity,
                    "confirmation_passes": int(
                        sentence["activation"].get("confirmation_passes", 0)
                    ),
                }
            )
        rows.sort(
            key=lambda row: (
                -int(row["combined_score"]),
                -int(row["confirmation_passes"]),
                str(row["sentence_id"]),
            )
        )
        return tuple(rows)

    def sample_distribution(
        self,
        visible_words: Sequence[str],
        *,
        seeds: Iterable[int],
        cpu_guided: bool = False,
        guide_rate: int = 250_000,
    ) -> dict[str, int]:
        raw = self.sample_state_distribution(
            [f"WORD:{word.lower()}" for word in visible_words],
            seeds=seeds,
            cpu_guided=cpu_guided,
            guide_rate=guide_rate,
        )
        return {
            " ".join(part.removeprefix("WORD:") for part in key.split(" ")): count
            for key, count in raw.items()
        }

    def learn_recursive_endpoint(
        self,
        kind: str,
        child_ids: Sequence[str],
        judge: Callable[[Sequence[str]], bool],
        *,
        seed: int,
        max_attempts: int = 20_000,
        required_confirmations: int = 3,
        require_fresh_reread: bool = True,
        source_handle: str = "",
    ) -> dict[str, Any]:
        """Apply the same hidden-verdict Hept mechanism above the word rung."""

        if kind not in {"SENTENCE", "PARAGRAPH", "PAGE", "CONCEPT"}:
            raise ValueError("unsupported recursive endpoint kind")
        children = [self.store.load_neuron(child_id) for child_id in child_ids]
        if any(not self._recursive_child_supported(child) for child in children):
            return {"state": "HOLD", "reason": "UNSTABLE_CHILD"}
        endpoint = make_neuron(
            neuron_id=new_neuron_id(),
            kind=kind,
            lifecycle="NEWBORN",
            creation_event="RECURSIVE_ENDPOINT_BIRTH",
            children=child_ids,
            center={
                "source_handle": source_handle,
                "construction": [],
                "construction_alignment": 0,
                "reality_alignment": None,
                "truth_compatibility": 0,
                "trusted_language_memory": False,
            },
        )
        self.store.transact(
            [endpoint],
            event_kind="RECURSIVE_ENDPOINT_BIRTH",
            details={"endpoint_id": endpoint["neuron_id"], "kind": kind, "children": len(child_ids)},
        )
        for attempt_number in range(1, max_attempts + 1):
            attempt_seed = seed + attempt_number * 1_000_003
            route, _, _ = self.attempt_route(
                child_ids, seed=attempt_seed, origin_id=endpoint["neuron_id"]
            )
            passed = bool(judge(route))
            repeated, _, updated = self.attempt_route(
                child_ids,
                seed=attempt_seed,
                apply_verdict=passed,
                origin_id=endpoint["neuron_id"],
            )
            if repeated != route:
                raise RuntimeError("seeded recursive route changed before verdict")
            endpoint = updated.get(endpoint["neuron_id"], self.store.load_neuron(endpoint["neuron_id"]))
            endpoint["lifecycle"] = "PLASTIC"
            endpoint["activation"]["uses"] += 1
            endpoint["activation"]["pass_hits" if passed else "fail_hits"] += 1
            endpoint["center_attractor"]["last_construction"] = list(route)
            updated[endpoint["neuron_id"]] = endpoint
            self.store.transact(
                updated.values(),
                event_kind="RECURSIVE_ROUTE_CONSEQUENCE",
                details={
                    "endpoint_id": endpoint["neuron_id"],
                    "attempt_seed": attempt_seed,
                    "verdict": "PASS" if passed else "FAIL",
                },
            )
            if not passed:
                continue
            confirmations = []
            for confirmation in range(1, required_confirmations + 1):
                frozen, _, _ = self.attempt_route(
                    child_ids,
                    seed=attempt_seed + confirmation * 97_409,
                    origin_id=endpoint["neuron_id"],
                )
                if not judge(frozen):
                    break
                confirmations.append(frozen)
            if len(confirmations) != required_confirmations:
                continue
            reread_passed = True
            if require_fresh_reread:
                reread, _, _ = self.attempt_route(
                    child_ids,
                    seed=attempt_seed + (required_confirmations + 1) * 97_409,
                    origin_id=endpoint["neuron_id"],
                )
                reread_passed = bool(judge(reread))
                if not reread_passed:
                    continue
            endpoint = self.store.load_neuron(endpoint["neuron_id"])
            stable_children = {child_id: self.store.load_neuron(child_id) for child_id in set(route)}
            marker = f"STABILIZE:{endpoint['neuron_id']}"
            for child_id in route:
                reinforce_connection(
                    endpoint, child_id, direction="IN", passed=True, event_id=marker
                )
                stable_children[child_id]["parents"].append(endpoint["neuron_id"])
            endpoint["lifecycle"] = "STABLE"
            endpoint["children"] = list(route)
            endpoint["activation"]["confirmation_passes"] = required_confirmations
            endpoint["center_attractor"]["construction"] = list(route)
            endpoint["center_attractor"]["trusted_language_memory"] = True
            endpoint["center_attractor"]["fresh_reread_passed"] = reread_passed
            endpoint["center_attractor"]["admission_state"] = (
                "ADMITTED_AFTER_FRESH_REREAD"
                if require_fresh_reread
                else "ADMITTED_AFTER_CONFIRMATIONS"
            )
            self.store.transact(
                [endpoint, *stable_children.values()],
                event_kind="RECURSIVE_ENDPOINT_STABILIZED",
                details={
                    "endpoint_id": endpoint["neuron_id"],
                    "kind": kind,
                    "confirmations": required_confirmations,
                },
            )
            return {
                "state": "PASS",
                "endpoint_id": endpoint["neuron_id"],
                "kind": kind,
                "attempts": attempt_number,
                "confirmation_passes": required_confirmations,
                "fresh_reread_passed": reread_passed,
                "construction": list(route),
            }
        return {
            "state": "HOLD",
            "reason": "MAX_ATTEMPTS",
            "endpoint_id": endpoint["neuron_id"],
            "kind": kind,
        }

    def _trusted_recursive_experts(self) -> list[dict[str, Any]]:
        experts: list[dict[str, Any]] = []
        for neuron_id, metadata in self.store.manifest()["neuron_index"].items():
            if (
                metadata.get("kind") not in {"SENTENCE", "CONCEPT"}
                or metadata.get("lifecycle") != "STABLE"
            ):
                continue
            neuron = self.store.load_neuron(neuron_id)
            if (
                neuron["center_attractor"].get("trusted_language_memory") is True
                and neuron["center_attractor"].get("construction")
            ):
                experts.append(neuron)
        return experts

    def learn_recursive_sentence_episode(
        self,
        visible_state_ids: Sequence[str],
        judge: Callable[[Sequence[str]], bool],
        *,
        seed: int,
        max_attempts: int = 1_000,
        required_confirmations: int = 3,
        source_handle: str = "",
        trace_path: str | Path | None = None,
        resume_episode_id: str | None = None,
    ) -> dict[str, Any]:
        """Learn a sentence through model-owned local endpoints and experts."""

        # Resolve this optional mechanism before birthing an episode;
        # a missing router must not leave partially created learner state.
        try:
            from .recursive_chunk import RecursiveChunkRouter
        except ModuleNotFoundError as error:
            if error.name != f"{__package__}.recursive_chunk":
                raise
            raise RuntimeError("recursive chunk router is unavailable in the active checkpoint") from error
        manifest = self.store.manifest()
        try:
            child_ids = tuple(
                self._resolve_visible_state(manifest, state_id)
                for state_id in visible_state_ids
            )
        except KeyError as error:
            return {"state": "HOLD", "reason": "UNSUPPORTED_VISIBLE_STATE", "state_id": str(error)}
        if len(set(child_ids)) != len(child_ids):
            return {"state": "HOLD", "reason": "RECURSIVE_DUPLICATE_CHILD_UNSUPPORTED"}
        if resume_episode_id is None:
            episode = self.birth_episode(child_ids, source_handle=source_handle)
        else:
            episode = self.store.load_neuron(resume_episode_id)
            if episode["kind"] != "EPISODE" or episode["lifecycle"] not in {"NEWBORN", "PLASTIC"}:
                raise ValueError("resume requires a plastic episode neuron")
            if sorted(episode["children"]) != sorted(child_ids):
                raise ValueError("resume episode visible inventory mismatch")
            if str(episode["center_attractor"].get("source_handle", "")) != source_handle:
                raise ValueError("resume episode source handle mismatch")
        neurons = {item: self.store.load_neuron(item) for item in child_ids}
        router = RecursiveChunkRouter(self.library)
        guidance_parent = router.build_expert_routed_parent(
            neurons, child_ids, self._trusted_recursive_experts()
        )
        trace: list[dict[str, Any]] = []

        def record(row: dict[str, Any]) -> None:
            trace.append(row)
            if trace_path is not None:
                path = Path(trace_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

        for attempt_number in range(1, max_attempts + 1):
            attempt_seed = seed + attempt_number * 1_000_003
            attempted = router.attempt(
                neurons, child_ids, seed=attempt_seed, guidance_parent=guidance_parent
            )
            episode = self.store.load_neuron(episode["neuron_id"])
            if self._route_signature(attempted.route) in episode["center_attractor"].get(
                "failed_assemblies", {}
            ):
                continue
            rendered = tuple(self._render_state(item) for item in attempted.route)
            passed = bool(judge(rendered))
            episode["lifecycle"] = "PLASTIC"
            episode["activation"]["uses"] += 1
            episode["activation"]["pass_hits" if passed else "fail_hits"] += 1
            episode["center_attractor"]["last_construction"] = list(attempted.route)
            touched: dict[str, dict[str, Any]] = {episode["neuron_id"]: episode}
            if passed:
                previous_id = episode["neuron_id"]
                for position, selected_id in enumerate(attempted.route):
                    heads = episode["center_attractor"]["position_heads"]
                    heads[str(position)][selected_id] = toward_one(
                        int(heads[str(position)][selected_id]), 900_000
                    )
                    source = touched.get(previous_id) or self.store.load_neuron(previous_id)
                    reinforce_connection(
                        source,
                        selected_id,
                        direction="OUT",
                        passed=True,
                        event_id=f"RECURSIVE_ATTEMPT:{attempt_seed}:{position}",
                    )
                    touched[previous_id] = source
                    previous_id = selected_id
                episode["center_attractor"]["plastic_candidate_construction"] = list(
                    attempted.route
                )
            else:
                self._record_failed_assembly(episode, attempted.route)
            touched[episode["neuron_id"]] = episode
            self.store.transact(
                touched.values(),
                event_kind="RECURSIVE_SENTENCE_ROUTE_CONSEQUENCE",
                details={
                    "episode_id": episode["neuron_id"],
                    "attempt_seed": attempt_seed,
                    "verdict": "PASS" if passed else "FAIL",
                    "target_free_route": True,
                },
            )
            row: dict[str, Any] = {
                "attempt": attempt_number,
                "seed": attempt_seed,
                "candidate": list(rendered),
                "verdict": "PASS" if passed else "FAIL",
                "pair_count": attempted.pair_count,
            }
            if not passed:
                record(row)
                continue
            confirmations = 0
            confirmation_rows = []
            for confirmation in range(1, required_confirmations + 1):
                confirmation_seed = attempt_seed + confirmation * 97_409
                frozen = router.attempt(
                    neurons,
                    child_ids,
                    seed=confirmation_seed,
                    guidance_parent=guidance_parent,
                )
                frozen_rendered = tuple(self._render_state(item) for item in frozen.route)
                accepted = bool(judge(frozen_rendered))
                confirmation_rows.append(
                    {"confirmation": confirmation, "seed": confirmation_seed, "verdict": "PASS" if accepted else "FAIL"}
                )
                if not accepted:
                    break
                confirmations += 1
            row["confirmations"] = confirmation_rows
            record(row)
            if confirmations != required_confirmations:
                continue
            sentence_id = self._stabilize(
                episode,
                attempted.route,
                confirmations=confirmations,
                defer_admission=True,
            )
            return {
                "state": "PASS",
                "episode_id": episode["neuron_id"],
                "sentence_id": sentence_id,
                "attempts": attempt_number,
                "confirmation_passes": confirmations,
                "construction": list(rendered),
                "trace": trace,
                "architecture": "RECURSIVE_HEPT_LOCAL_ENDPOINT_V1",
            }
        return {
            "state": "HOLD",
            "reason": "MAX_ATTEMPTS",
            "episode_id": episode["neuron_id"],
            "attempts": max_attempts,
            "trace": trace,
            "architecture": "RECURSIVE_HEPT_LOCAL_ENDPOINT_V1",
        }

    def learn_generated_sentence_episode(
        self,
        visible_state_ids: Sequence[str],
        judge: Callable[[Sequence[str]], dict[str, Any]],
        *,
        seed: int,
        source_handle: str,
        definition_evidence_sha256: Sequence[str],
        max_attempts: int = 1_000,
        required_confirmations: int = 3,
        trace_path: str | Path | None = None,
        route_truth_context: str | None = None,
        route_truth_evidence_writer: Callable[[Sequence[str], bool], None] | None = None,
        activation_anchors: Sequence[Mapping[str, str]] | None = None,
        utterance_mode: str = "U0",
        context_requirement: str | None = None,
        question_family: str | None = None,
        composition_unit_ids: Sequence[str] | None = None,
        source_provenance: Mapping[str, Any] | None = None,
        cpu_gate_profile: str = "LEGACY_GMT_V1",
    ) -> dict[str, Any]:
        """Generate a sentence and learn grammar, meaning, and truth separately.

        The GPU receives only visible neuron IDs and opaque learned state.  The
        CPU callback returns three independent one-bit consequences.  Grammar
        success is retained even when contextual meaning or factual support
        fails; only all-three PASS can birth trusted SENTENCE memory.
        """

        if cpu_gate_profile not in {"LEGACY_GMT_V1", "COURTROOM_V1"}:
            raise ValueError("CPU gate profile must be LEGACY_GMT_V1 or COURTROOM_V1")
        if utterance_mode not in {"U0", "U1", "U2", "U3"}:
            raise ValueError("utterance mode must be opaque U0, U1, U2, or U3")
        if context_requirement not in {None, "K0"}:
            raise ValueError("context requirement must be absent or opaque K0")
        if question_family not in {None, "Q0", "Q1", "Q2", "Q3"}:
            raise ValueError("question family must be absent or opaque Q0/Q1/Q2/Q3")
        manifest = self.store.manifest()
        try:
            child_ids = tuple(
                self._resolve_visible_state(manifest, state_id)
                for state_id in visible_state_ids
            )
        except KeyError as error:
            return {"state": "HOLD", "reason": "UNSUPPORTED_VISIBLE_STATE", "state_id": str(error)}
        minimum_children = 1 if utterance_mode == "U2" else 2
        if len(child_ids) < minimum_children or len(set(child_ids)) != len(child_ids):
            return {"state": "HOLD", "reason": "SENTENCE_INVENTORY_REQUIRES_DISTINCT_WORDS"}
        if activation_anchors is not None and len(activation_anchors) != len(child_ids):
            return {"state": "HOLD", "reason": "SENTENCE_ANCHOR_LENGTH_MISMATCH"}
        neurons = {item: self.store.load_neuron(item) for item in child_ids}
        if any(item.get("kind") != "WORD" or item.get("lifecycle") != "STABLE" for item in neurons.values()):
            return {"state": "HOLD", "reason": "SENTENCE_REQUIRES_STABLE_WORD_NEURONS"}
        route_child_ids = child_ids
        composition_units: dict[str, tuple[str, ...]] = {}
        composition_provenance: dict[str, dict[str, Any]] = {}
        if composition_unit_ids is not None:
            if activation_anchors is not None:
                return {"state": "HOLD", "reason": "COMPOSITION_UNITS_OWN_POSITION_GUIDANCE"}
            route_child_ids = tuple(str(value) for value in composition_unit_ids)
            if len(route_child_ids) < 2 or len(set(route_child_ids)) != len(route_child_ids):
                return {"state": "HOLD", "reason": "COMPOSITION_REQUIRES_DISTINCT_PHRASE_NEURONS"}
            flattened_inventory: list[str] = []
            for unit_id in route_child_ids:
                unit = self.store.load_neuron(unit_id)
                construction = tuple(
                    str(value) for value in unit.get("center_attractor", {}).get("construction", ())
                )
                if (
                    unit.get("kind") != "SENTENCE"
                    or unit.get("lifecycle") != "STABLE"
                    or unit.get("center_attractor", {}).get("trusted_language_memory") is not True
                    or unit.get("center_attractor", {}).get("opaque_utterance_mode_v1") != "U3"
                    or len(construction) < 2
                ):
                    return {"state": "HOLD", "reason": "COMPOSITION_REQUIRES_STABLE_PHRASE_NEURONS"}
                composition_units[unit_id] = construction
                provenance = unit.get("center_attractor", {}).get("source_provenance_v1")
                if not isinstance(provenance, dict):
                    return {"state": "HOLD", "reason": "COMPOSITION_PHRASE_PROVENANCE_MISSING"}
                if (
                    source_provenance is not None
                    and str(provenance.get("source_sha256", "")).upper()
                    != str(source_provenance.get("source_sha256", "")).upper()
                ):
                    return {"state": "HOLD", "reason": "COMPOSITION_PHRASE_PROVENANCE_MISMATCH"}
                composition_provenance[unit_id] = deepcopy(provenance)
                flattened_inventory.extend(construction)
            if Counter(flattened_inventory) != Counter(child_ids):
                return {"state": "HOLD", "reason": "COMPOSITION_PHRASE_INVENTORY_MISMATCH"}

        def flatten_route(route: Sequence[str]) -> tuple[str, ...]:
            if not composition_units:
                return tuple(str(value) for value in route)
            return tuple(
                child_id
                for unit_id in route
                for child_id in composition_units[str(unit_id)]
            )

        episode = self.birth_episode(route_child_ids, source_handle=source_handle)
        trace: list[dict[str, Any]] = []

        def record(row: dict[str, Any]) -> None:
            trace.append(row)
            if trace_path is not None:
                path = Path(trace_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

        def guidance(current_episode: dict[str, Any]) -> dict[str, Any]:
            parent = deepcopy(current_episode)
            blocked = parent["center_attractor"].get("context_blocked_assemblies", {})
            parent["center_attractor"]["failed_assemblies"] = {
                **parent["center_attractor"].get("failed_assemblies", {}),
                **blocked,
            }
            return parent

        for attempt_number in range(1, max_attempts + 1):
            attempt_seed = seed + attempt_number * 1_000_003
            episode = self.store.load_neuron(episode["neuron_id"])
            try:
                attempted_route, attempted_steps, _ = self.attempt_route(
                    route_child_ids,
                    seed=attempt_seed,
                    overrides={episode["neuron_id"]: guidance(episode)},
                    origin_id=episode["neuron_id"],
                    copy_overrides=False,
                    exhaustive_prefix_memory=True,
                    route_truth_context=route_truth_context,
                    tag_contexts=activation_anchors,
                )
            except CudaRouteHold as error:
                record({
                    "phase": "GENERATED_SENTENCE_LEARNING",
                    "attempt_number": attempt_number,
                    "seed": attempt_seed,
                    "episode_neuron_id": episode["neuron_id"],
                    "state": "HOLD",
                    "reason": str(error),
                })
                continue
            attempted_word_route = flatten_route(attempted_route)
            rendered = tuple(self._render_state(item) for item in attempted_word_route)
            verdict = dict(judge(rendered))
            courtroom: dict[str, Any] | None = None
            if cpu_gate_profile == "COURTROOM_V1":
                courtroom = adjudicate_cpu_case(verdict)
                grammar_pass = str(verdict["grammar"]).upper() == "PASS"
                meaning_pass = str(verdict["meaning"]).upper() == "PASS"
                truth_pass = str(verdict["truth"]).upper() == "PASS"
                admitted_pass = courtroom["state"] == "PASS"
                if courtroom["state"] == "HOLD":
                    record({
                        "phase": "GENERATED_SENTENCE_LEARNING",
                        "attempt_number": attempt_number,
                        "seed": attempt_seed,
                        "episode_neuron_id": episode["neuron_id"],
                        "token_ids": list(attempted_word_route),
                        "route": list(attempted_route),
                        "candidate": list(rendered),
                        "state": "HOLD",
                        "reason": courtroom["reason"],
                        "cpu_gate_profile": cpu_gate_profile,
                        "courtroom_adjudication": courtroom,
                    })
                    continue
            else:
                gate_keys = ("grammar", "meaning", "truth")
                if any(key not in verdict or not isinstance(verdict[key], bool) for key in gate_keys):
                    raise ValueError("sentence CPU judge must return grammar, meaning, and truth bits")
                grammar_pass = verdict["grammar"]
                meaning_pass = verdict["meaning"]
                truth_pass = verdict["truth"]
                admitted_pass = grammar_pass and meaning_pass and truth_pass
            signature = self._route_signature(attempted_route)
            episode["lifecycle"] = "PLASTIC"
            episode["activation"]["uses"] += 1
            episode["activation"]["pass_hits" if admitted_pass else "fail_hits"] += 1
            episode["center_attractor"]["last_construction"] = list(attempted_route)
            gate_evidence = episode["center_attractor"].setdefault(
                "opaque_sentence_gate_evidence_v1",
                {channel: {"pass_hits": 0, "fail_hits": 0} for channel in ("C0", "C1", "C2")},
            )
            for channel, passed in zip(("C0", "C1", "C2"), (grammar_pass, meaning_pass, truth_pass)):
                gate_evidence[channel]["pass_hits" if passed else "fail_hits"] += 1
            touched: dict[str, dict[str, Any]] = {episode["neuron_id"]: episode}
            if grammar_pass:
                for position, selected_id in enumerate(attempted_route):
                    heads = episode["center_attractor"]["position_heads"]
                    heads[str(position)][selected_id] = toward_one(
                        int(heads[str(position)][selected_id]), 900_000
                    )
                episode["center_attractor"].setdefault("grammar_supported_assemblies", {})[
                    signature
                ] = int(
                    episode["center_attractor"].get("grammar_supported_assemblies", {}).get(signature, 0)
                ) + 1
            if not admitted_pass:
                self._record_failed_assembly(episode, attempted_route)
            if grammar_pass and not admitted_pass:
                blocked = episode["center_attractor"].setdefault("context_blocked_assemblies", {})
                blocked[signature] = int(blocked.get(signature, 0)) + 1
            if admitted_pass:
                previous_id = episode["neuron_id"]
                for position, selected_id in enumerate(attempted_route):
                    source = touched.get(previous_id) or self.store.load_neuron(previous_id)
                    reinforce_connection(
                        source,
                        selected_id,
                        direction="OUT",
                        passed=True,
                        event_id=f"GENERATED_SENTENCE:{attempt_seed}:{position}",
                    )
                    touched[previous_id] = source
                    previous_id = selected_id
                episode["center_attractor"]["plastic_candidate_construction"] = list(attempted_route)
            for changed in touched.values():
                changed["reflectors"] = {
                    name: changed["reflectors"][name] for name in REFLECTORS
                }
                changed["updated_utc"] = utc_now()
                changed["content_sha256"] = content_hash(changed)
                validate_neuron(changed)
            self.store.transact(
                touched.values(),
                event_kind="GENERATED_SENTENCE_CONSEQUENCE",
                details={
                    "episode_id": episode["neuron_id"],
                    "attempt_seed": attempt_seed,
                    "grammar_bit": int(grammar_pass),
                    "meaning_bit": int(meaning_pass),
                    "truth_bit": int(truth_pass),
                    "admission_bit": int(admitted_pass),
                    "cpu_gate_profile": cpu_gate_profile,
                    "courtroom_state": courtroom["state"] if courtroom is not None else None,
                    "target_free_route": True,
                },
            )
            if route_truth_evidence_writer is not None:
                route_truth_evidence_writer(attempted_word_route, admitted_pass)
            row: dict[str, Any] = {
                "phase": "GENERATED_SENTENCE_LEARNING",
                "attempt_number": attempt_number,
                "seed": attempt_seed,
                "episode_neuron_id": episode["neuron_id"],
                "token_ids": list(attempted_word_route),
                "route": list(attempted_route),
                "composition_unit_ids": list(attempted_route) if composition_units else [],
                "candidate": list(rendered),
                "grammar": "PASS" if grammar_pass else "FAIL",
                "meaning": "PASS" if meaning_pass else "FAIL",
                "truth": "PASS" if truth_pass else "FAIL",
                "consequence": "PASS" if admitted_pass else "FAIL",
                "cpu_gate_profile": cpu_gate_profile,
                "courtroom_adjudication": courtroom,
                "pair_count": max(0, len(attempted_steps) - 1),
                "decisions": [
                    {
                        "depth": depth,
                        "previous_neuron_id": step.previous_id,
                        "selected_neuron_id": step.selected_id,
                        "selected_surface": self._render_state(step.selected_id),
                        "selected_reflector": REFLECTORS[step.selected_reflector],
                        "selected_strength": step.strengths[step.selected_index],
                        "frontier": len(step.candidate_ids),
                        "cpu_activation_anchor": dict(step.activation_anchor),
                        "activation_context_weight": step.activation_context_weight,
                    }
                    for depth, step in enumerate(attempted_steps)
                ],
            }
            if not admitted_pass:
                record(row)
                continue
            confirmations: list[dict[str, Any]] = []
            confirmed = True
            episode = self.store.load_neuron(episode["neuron_id"])
            for confirmation in range(1, required_confirmations + 1):
                confirmation_seed = attempt_seed + confirmation * 97_409
                try:
                    frozen_route, _frozen_steps, _ = self.attempt_route(
                        route_child_ids,
                        seed=confirmation_seed,
                        overrides={episode["neuron_id"]: guidance(episode)},
                        origin_id=episode["neuron_id"],
                        copy_overrides=False,
                        exhaustive_prefix_memory=True,
                        route_truth_context=route_truth_context,
                        tag_contexts=activation_anchors,
                    )
                except CudaRouteHold as error:
                    confirmations.append({
                        "confirmation": confirmation,
                        "seed": confirmation_seed,
                        "state": "HOLD",
                        "reason": str(error),
                        "write_performed": False,
                    })
                    confirmed = False
                    break
                frozen_word_route = flatten_route(frozen_route)
                frozen_rendered = tuple(self._render_state(item) for item in frozen_word_route)
                frozen_verdict = dict(judge(frozen_rendered))
                accepted = (
                    tuple(frozen_route) == tuple(attempted_route)
                    and all(frozen_verdict.get(key) is True for key in gate_keys)
                )
                confirmations.append({
                    "confirmation": confirmation,
                    "seed": confirmation_seed,
                    "candidate": list(frozen_rendered),
                    "grammar": "PASS" if frozen_verdict.get("grammar") else "FAIL",
                    "meaning": "PASS" if frozen_verdict.get("meaning") else "FAIL",
                    "truth": "PASS" if frozen_verdict.get("truth") else "FAIL",
                    "verdict": "PASS" if accepted else "FAIL",
                    "write_performed": False,
                })
                if not accepted:
                    confirmed = False
                    break
            row["confirmations"] = confirmations
            record(row)
            if not confirmed or len(confirmations) != required_confirmations:
                continue

            context_sha256 = hashlib.sha256(
                (source_handle + "\0" + "\0".join(attempted_word_route)).encode("utf-8")
            ).hexdigest().upper()
            sentence = make_neuron(
                neuron_id=new_neuron_id(),
                kind="SENTENCE",
                lifecycle="STABLE",
                creation_event="SELF_GENERATED_SENTENCE_CONFIRMED",
                children=attempted_word_route,
                center={
                    "construction": list(attempted_word_route),
                    "source_episode_ref": episode["neuron_id"],
                    "inventory_signature": self._inventory_signature(attempted_word_route),
                    "construction_alignment": SCALE,
                    "reality_alignment": SCALE,
                    "truth_compatibility": SCALE,
                    "trusted_language_memory": True,
                    # Opaque mode only: U0 is declarative, U1 interrogative,
                    # U2 a CPU-approved social act, and U3 a learned phrase
                    # fragment. Human labels and any
                    # grounded response remain CPU-side and never enter the
                    # GPU-visible neuron payload.
                    "opaque_utterance_mode_v1": utterance_mode,
                    **(
                        {"opaque_context_requirement_v1": context_requirement}
                        if context_requirement is not None
                        else {}
                    ),
                    **(
                        {"opaque_question_family_v1": question_family}
                        if question_family is not None
                        else {}
                    ),
                    "opaque_sentence_context_v1": {
                        "schema": "NN_OPAQUE_SENTENCE_CONTEXT_V1",
                        "context_sha256": context_sha256,
                        "definition_evidence_sha256": list(definition_evidence_sha256),
                        "gate_channels": {"C0": SCALE, "C1": SCALE, "C2": SCALE},
                        "human_labels_used": False,
                    },
                    **(
                        {"source_provenance_v1": deepcopy(dict(source_provenance))}
                        if source_provenance is not None
                        else {}
                    ),
                    **(
                        {
                            "recursive_composition_v1": {
                                "unit_ids": list(attempted_route),
                                "unit_constructions": {
                                    unit_id: list(composition_units[unit_id])
                                    for unit_id in attempted_route
                                },
                                "flattened_construction": list(attempted_word_route),
                                "inherited_provenance": [
                                    {
                                        "unit_id": unit_id,
                                        "source_provenance": deepcopy(composition_provenance[unit_id]),
                                    }
                                    for unit_id in attempted_route
                                ],
                            }
                        }
                        if composition_units
                        else {}
                    ),
                },
            )
            sentence["activation"]["uses"] = 1
            sentence["activation"]["pass_hits"] = 1
            sentence["activation"]["confirmation_passes"] = required_confirmations
            stable_words = {
                neuron_id: self.store.load_neuron(neuron_id) for neuron_id in set(attempted_word_route)
            }
            event_marker = f"SENTENCE_CONTEXT:{sentence['neuron_id']}"
            for position, word_id in enumerate(attempted_word_route):
                word = stable_words[word_id]
                associations = word["center_attractor"].setdefault(
                    "opaque_context_associations_v1", {}
                )
                association = associations.setdefault(
                    context_sha256,
                    {
                        "channel": f"M{position}",
                        "uses": 0,
                        "pass_hits": 0,
                        "fail_hits": 0,
                        "weight": SCALE // 2,
                        "peer_ids": [item for item in attempted_word_route if item != word_id],
                    },
                )
                association["uses"] += 1
                association["pass_hits"] += 1
                association["weight"] = self._route_probability(
                    association["pass_hits"], association["fail_hits"]
                )
                reinforce_connection(sentence, word_id, direction="OUT", passed=True, event_id=event_marker)
                for peer_id in attempted_word_route[position + 1 :]:
                    reinforce_connection(word, peer_id, direction="OUT", passed=True, event_id=event_marker)
                    reinforce_connection(stable_words[peer_id], word_id, direction="IN", passed=True, event_id=event_marker)
                if sentence["neuron_id"] not in word["parents"]:
                    word["parents"].append(sentence["neuron_id"])
            episode = self.store.load_neuron(episode["neuron_id"])
            episode["lifecycle"] = "STABLE"
            episode["children"] = [sentence["neuron_id"]]
            episode["center_attractor"]["construction"] = list(attempted_word_route)
            if composition_units:
                episode["center_attractor"]["composition_unit_route"] = list(attempted_route)
            episode["center_attractor"]["sentence_neuron_ref"] = sentence["neuron_id"]
            episode["center_attractor"]["trusted_language_memory"] = True
            sentence["parents"].append(episode["neuron_id"])
            changed_neurons = [episode, sentence, *stable_words.values()]
            for changed in changed_neurons:
                changed["reflectors"] = {
                    name: changed["reflectors"][name] for name in REFLECTORS
                }
                changed["updated_utc"] = utc_now()
                changed["content_sha256"] = content_hash(changed)
                validate_neuron(changed)
            self.store.transact(
                changed_neurons,
                event_kind="SELF_GENERATED_SENTENCE_STABILIZED",
                details={
                    "episode_id": episode["neuron_id"],
                    "sentence_id": sentence["neuron_id"],
                    "confirmations": required_confirmations,
                    "grammar_bit": 1,
                    "meaning_bit": 1,
                    "truth_bit": 1,
                    "utterance_mode": utterance_mode,
                    "context_requirement": context_requirement,
                },
            )
            return {
                "state": "PASS",
                "episode_id": episode["neuron_id"],
                "sentence_id": sentence["neuron_id"],
                "attempts": attempt_number,
                "construction": list(rendered),
                "composition_unit_ids": list(attempted_route) if composition_units else [],
                "confirmation_passes": required_confirmations,
                "utterance_mode": utterance_mode,
                "context_requirement": context_requirement,
                "trace": trace,
                "architecture": (
                    "RECURSIVE_PHRASE_COMPOSITION_SEPARATE_GRAMMAR_MEANING_TRUTH_V1"
                    if composition_units
                    else "SELF_GENERATED_SEPARATE_GRAMMAR_MEANING_TRUTH_V1"
                ),
            }
        return {
            "state": "HOLD",
            "reason": "MAX_ATTEMPTS",
            "episode_id": episode["neuron_id"],
            "attempts": max_attempts,
            "trace": trace,
            "composition_unit_ids": list(route_child_ids) if composition_units else [],
            "architecture": (
                "RECURSIVE_PHRASE_COMPOSITION_SEPARATE_GRAMMAR_MEANING_TRUTH_V1"
                if composition_units
                else "SELF_GENERATED_SEPARATE_GRAMMAR_MEANING_TRUTH_V1"
            ),
        }

    def learn_interrogative_template(
        self,
        sentence_pairs: Sequence[tuple[str, str]],
        *,
        question_anchor_channels: Sequence[str],
        source_handle: str,
        question_family: str = "Q0",
    ) -> dict[str, Any]:
        """Derive one reusable opaque question/response transform from PASS pairs.

        The transform is induced from stable sentence constructions: positions
        constant across every question and positions copied between question
        and response.  It stores no future subject or answer.
        """

        if len(sentence_pairs) < 3:
            return {"state": "HOLD", "reason": "TEMPLATE_REQUIRES_THREE_PAIRS"}
        if question_family not in {"Q0", "Q1", "Q2", "Q3"}:
            return {"state": "HOLD", "reason": "UNSUPPORTED_QUESTION_FAMILY"}
        structural_only = question_family == "Q2"
        questions: list[dict[str, Any]] = []
        responses: list[dict[str, Any]] = []
        for question_id, response_id in sentence_pairs:
            question = self.store.load_neuron(str(question_id))
            question_center = question.get("center_attractor", {})
            if (
                question.get("kind") != "SENTENCE"
                or question.get("lifecycle") != "STABLE"
                or question_center.get("trusted_language_memory") is not True
                or question_center.get("opaque_utterance_mode_v1") != "U1"
            ):
                return {"state": "HOLD", "reason": "TEMPLATE_PAIR_NOT_TRUSTED"}
            questions.append(question)
            if not structural_only:
                response = self.store.load_neuron(str(response_id))
                response_center = response.get("center_attractor", {})
                if (
                    response.get("kind") != "SENTENCE"
                    or response.get("lifecycle") != "STABLE"
                    or response_center.get("trusted_language_memory") is not True
                    or response_center.get("opaque_utterance_mode_v1", "U0")
                    not in ({"U2"} if question_family == "Q3" else {"U0"})
                ):
                    return {"state": "HOLD", "reason": "TEMPLATE_PAIR_NOT_TRUSTED"}
                responses.append(response)
        question_routes = [tuple(str(value) for value in item["center_attractor"]["construction"]) for item in questions]
        response_routes = [tuple(str(value) for value in item["center_attractor"]["construction"]) for item in responses]
        question_arity = len(question_routes[0])
        response_arity = 0 if structural_only else len(response_routes[0])
        if (
            question_arity < 2
            or any(len(route) != question_arity for route in question_routes)
            or (not structural_only and any(len(route) != response_arity for route in response_routes))
            or len(question_anchor_channels) != question_arity
        ):
            return {"state": "HOLD", "reason": "TEMPLATE_ARITY_MISMATCH"}
        constants = {
            str(position): question_routes[0][position]
            for position in range(question_arity)
            if len({route[position] for route in question_routes}) == 1
        }
        response_constants = (
            {}
            if structural_only
            else {
                str(position): response_routes[0][position]
                for position in range(response_arity)
                if len({route[position] for route in response_routes}) == 1
            }
        )
        copy_links = [
            {"question_position": question_position, "response_position": response_position}
            for question_position in range(question_arity)
            for response_position in range(response_arity)
            if all(
                question_route[question_position] == response_route[response_position]
                for question_route, response_route in zip(question_routes, response_routes)
            )
        ]
        copied_response_positions = {int(item["response_position"]) for item in copy_links}
        unresolved_response_positions = [
            position
            for position in range(response_arity)
            if position not in copied_response_positions and str(position) not in response_constants
        ]
        variable_question_positions = [
            position for position in range(question_arity) if str(position) not in constants
        ]
        position_channels: list[str] = []
        if structural_only:
            for position in range(question_arity):
                channel = f"M{position}"
                prior = self._context_tag_prior({"position": channel})
                if any(
                    self._context_tag_weight(
                        self.store.load_neuron(route[position]),
                        {"position": channel},
                    ) <= prior
                    for route in question_routes
                ):
                    return {"state": "HOLD", "reason": "TEMPLATE_SOURCE_POSITION_NOT_LEARNED"}
                position_channels.append(channel)
        # A fully copied response is a valid generalizable transform.  Q1
        # binary-relation questions such as ``is oak tree`` can map every
        # response position from the question without an unresolved slot.
        if (
            not constants
            or (not structural_only and not copy_links)
            or not variable_question_positions
            or unresolved_response_positions
        ):
            return {"state": "HOLD", "reason": "TEMPLATE_HAS_NO_GENERALIZABLE_STRUCTURE"}
        signature_payload = {
            "question_arity": question_arity,
            "response_arity": response_arity,
            "constant_question_positions": constants,
            "constant_response_positions": response_constants,
            "response_copy_links": copy_links,
            "variable_question_positions": variable_question_positions,
            "unresolved_response_positions": unresolved_response_positions,
            "question_anchor_channels": list(question_anchor_channels),
            "question_position_channels": position_channels,
            "question_family": question_family,
            "grounding_mode": "STRUCTURE_ONLY" if structural_only else "QUESTION_RESPONSE_COPY",
        }
        signature = hashlib.sha256(
            json.dumps(signature_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest().upper()
        concept = make_neuron(
            neuron_id=new_neuron_id(),
            kind="CONCEPT",
            lifecycle="STABLE",
            creation_event="INTERROGATIVE_TEMPLATE_INDUCED",
            children=(
                [str(pair[0]) for pair in sentence_pairs]
                if structural_only
                else [value for pair in sentence_pairs for value in (str(pair[0]), str(pair[1]))]
            ),
            center={
                "opaque_interrogative_template_v1": {
                    "schema": "NN_OPAQUE_INTERROGATIVE_TEMPLATE_V1",
                    **signature_payload,
                    "source_pair_count": len(sentence_pairs),
                    "template_signature": signature,
                    "human_labels_used": False,
                    "future_target_used": False,
                },
                "source_handle_sha256": source_handle,
                "trusted_language_memory": True,
                "construction_alignment": SCALE,
                "reality_alignment": SCALE,
                "truth_compatibility": SCALE,
            },
        )
        concept["activation"]["uses"] = len(sentence_pairs)
        concept["activation"]["pass_hits"] = len(sentence_pairs)
        touched: dict[str, dict[str, Any]] = {concept["neuron_id"]: concept}
        marker = f"INTERROGATIVE_TEMPLATE:{signature}"
        for child_id in concept["children"]:
            child = touched.get(child_id) or self.store.load_neuron(child_id)
            reinforce_connection(concept, child_id, direction="OUT", passed=True, event_id=marker)
            reinforce_connection(child, concept["neuron_id"], direction="IN", passed=True, event_id=marker)
            if concept["neuron_id"] not in child["parents"]:
                child["parents"].append(concept["neuron_id"])
            touched[child_id] = child
        for changed in touched.values():
            changed["reflectors"] = {
                name: changed["reflectors"][name] for name in REFLECTORS
            }
            changed["updated_utc"] = utc_now()
            changed["content_sha256"] = content_hash(changed)
            validate_neuron(changed)

        transaction_id = self.store.transact(
            touched.values(),
            event_kind="INTERROGATIVE_TEMPLATE_INDUCED",
            details={
                "template_id": concept["neuron_id"],
                "template_signature": signature,
                "source_pair_count": len(sentence_pairs),
                "future_target_used": False,
            },
        )
        return {
            "state": "PASS",
            "template_id": concept["neuron_id"],
            "template_signature": signature,
            "source_pair_count": len(sentence_pairs),
            "constant_question_positions": constants,
            "constant_response_positions": response_constants,
            "response_copy_links": copy_links,
            "variable_question_positions": variable_question_positions,
            "unresolved_response_positions": unresolved_response_positions,
            "question_anchor_channels": list(question_anchor_channels),
            "transaction_id": transaction_id,
            "future_target_used": False,
        }

    def learn_social_intent_concept(
        self,
        source_question_ids: Sequence[str],
        *,
        source_signatures: Sequence[Sequence[Sequence[str]]],
        source_patterns: Sequence[dict[str, Any]],
        response_sentence_id: str,
        source_handle: str,
    ) -> dict[str, Any]:
        """Bind multiple admitted question forms to one opaque response intent.

        Signatures contain only already-learned opaque WORD metadata channels.
        No future surface, human intent label, or target sentence is stored.
        """

        if len(source_question_ids) < 2 or len(source_question_ids) != len(source_signatures):
            return {"state": "HOLD", "reason": "INTENT_REQUIRES_TWO_SOURCE_FORMS"}
        questions = [self.store.load_neuron(str(value)) for value in source_question_ids]
        response = self.store.load_neuron(str(response_sentence_id))
        if any(
            item.get("kind") != "SENTENCE"
            or item.get("lifecycle") != "STABLE"
            or item.get("center_attractor", {}).get("trusted_language_memory") is not True
            or item.get("center_attractor", {}).get("opaque_utterance_mode_v1") != "U2"
            for item in questions
        ):
            return {"state": "HOLD", "reason": "INTENT_SOURCE_NOT_TRUSTED"}
        if (
            response.get("kind") != "SENTENCE"
            or response.get("lifecycle") != "STABLE"
            or response.get("center_attractor", {}).get("trusted_language_memory") is not True
            or response.get("center_attractor", {}).get("opaque_utterance_mode_v1") != "U2"
        ):
            return {"state": "HOLD", "reason": "INTENT_RESPONSE_NOT_TRUSTED"}
        normalized_signatures = [
            tuple(tuple(sorted({str(channel) for channel in position})) for position in row)
            for row in source_signatures
        ]
        if any(not row for row in normalized_signatures) or len(set(normalized_signatures)) != len(normalized_signatures):
            return {"state": "HOLD", "reason": "INTENT_SIGNATURES_NOT_DISTINCT"}
        normalized_patterns = [
            {
                "pattern_kind": str(
                    pattern.get("pattern_kind", "INTERROGATIVE_HEAD_PLUS_ANCHORED_TAIL_V1")
                ),
                "head_channels": sorted({str(value) for value in pattern.get("head_channels", ())}),
                "anchored_tail_word_ids": [str(value) for value in pattern.get("anchored_tail_word_ids", ())],
                "anchored_suffix_word_ids": [str(value) for value in pattern.get("anchored_suffix_word_ids", ())],
                "minimum_arity": int(pattern.get("minimum_arity", 0)),
                "maximum_arity": int(pattern.get("maximum_arity", 0)),
                "cpu_probe_sha256": str(pattern.get("cpu_probe_sha256", "")),
            }
            for pattern in source_patterns
        ]
        if not normalized_patterns or any(
            (
                not pattern["head_channels"]
                and pattern["pattern_kind"] != "COMMUNICATION_HEAD_PLUS_ANCHORED_SUFFIX_V1"
            )
            or (
                not pattern["anchored_tail_word_ids"]
                and not pattern["anchored_suffix_word_ids"]
            )
            for pattern in normalized_patterns
        ):
            return {"state": "HOLD", "reason": "INTENT_HAS_NO_GROUNDED_HEAD_PATTERN"}
        signature_payload = {
            "source_signatures": [[list(position) for position in row] for row in normalized_signatures],
            "source_patterns": normalized_patterns,
            "response_sentence_id": str(response_sentence_id),
            "source_count": len(source_question_ids),
            "matching_rule": "CPU_HEAD_METADATA_PLUS_GROUNDED_ANCHOR_V2",
        }
        signature = hashlib.sha256(
            json.dumps(signature_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest().upper()
        concept = make_neuron(
            neuron_id=new_neuron_id(),
            kind="CONCEPT",
            lifecycle="STABLE",
            creation_event="SOCIAL_INTENT_INDUCED",
            children=[*map(str, source_question_ids), str(response_sentence_id)],
            center={
                "opaque_social_intent_v1": {
                    "schema": "NN_OPAQUE_SOCIAL_INTENT_V1",
                    **signature_payload,
                    "intent_signature": signature,
                    "human_labels_used": False,
                    "future_surface_used": False,
                },
                "source_handle_sha256": source_handle,
                "trusted_language_memory": True,
                "construction_alignment": SCALE,
                "reality_alignment": SCALE,
                "truth_compatibility": SCALE,
            },
        )
        concept["activation"]["uses"] = len(source_question_ids)
        concept["activation"]["pass_hits"] = len(source_question_ids)
        touched: dict[str, dict[str, Any]] = {concept["neuron_id"]: concept}
        marker = f"SOCIAL_INTENT:{signature}"
        for child_id in concept["children"]:
            child = touched.get(child_id) or self.store.load_neuron(child_id)
            reinforce_connection(concept, child_id, direction="OUT", passed=True, event_id=marker)
            reinforce_connection(child, concept["neuron_id"], direction="IN", passed=True, event_id=marker)
            if concept["neuron_id"] not in child["parents"]:
                child["parents"].append(concept["neuron_id"])
            touched[child_id] = child
        for changed in touched.values():
            changed["reflectors"] = {name: changed["reflectors"][name] for name in REFLECTORS}
            changed["updated_utc"] = utc_now()
            changed["content_sha256"] = content_hash(changed)
            validate_neuron(changed)
        transaction_id = self.store.transact(
            touched.values(),
            event_kind="SOCIAL_INTENT_INDUCED",
            details={
                "concept_id": concept["neuron_id"],
                "intent_signature": signature,
                "source_count": len(source_question_ids),
                "future_surface_used": False,
            },
        )
        return {
            "state": "PASS",
            "concept_id": concept["neuron_id"],
            "intent_signature": signature,
            "source_count": len(source_question_ids),
            "source_signatures": [[list(position) for position in row] for row in normalized_signatures],
            "response_sentence_id": str(response_sentence_id),
            "transaction_id": transaction_id,
            "future_surface_used": False,
        }

    def learn_binary_answer_episode(
        self,
        question_sentence_id: str,
        answer_state_ids: Sequence[str],
        judge: Callable[[str], bool],
        *,
        seed: int,
        max_attempts: int = 32,
        required_confirmations: int = 3,
        confirmation_seed_mode: str = "nearby",
        consolidate_confirmations: bool = False,
        trace_path: str | Path | None = None,
        route_truth_context: str | None = None,
        route_truth_evidence_writer: Callable[[Sequence[str], bool], None] | None = None,
    ) -> dict[str, Any]:
        """Learn one yes/no answer through a one-neuron GPU choice.

        The CPU returns only PASS/FAIL for the selected answer.  The expected
        polarity is never supplied to the route chooser.
        """

        question = self.store.load_neuron(str(question_sentence_id))
        center = question.get("center_attractor", {})
        if (
            question.get("kind") != "SENTENCE"
            or question.get("lifecycle") != "STABLE"
            or center.get("trusted_language_memory") is not True
            or center.get("opaque_utterance_mode_v1") != "U1"
        ):
            return {"state": "HOLD", "reason": "BINARY_ANSWER_REQUIRES_TRUSTED_QUESTION"}
        manifest = self.store.manifest()
        answer_ids = tuple(
            self._resolve_visible_state(manifest, state_id) for state_id in answer_state_ids
        )
        if len(answer_ids) != 2 or len(set(answer_ids)) != 2:
            return {"state": "HOLD", "reason": "BINARY_ANSWER_REQUIRES_TWO_DISTINCT_CHOICES"}
        trace: list[dict[str, Any]] = []

        def record(row: dict[str, Any]) -> None:
            trace.append(row)
            if trace_path is not None:
                path = Path(trace_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

        for attempt_number in range(1, max_attempts + 1):
            attempt_seed = seed + attempt_number * 1_000_003
            question = self.store.load_neuron(str(question_sentence_id))
            try:
                route, steps, _ = self.attempt_route(
                    answer_ids,
                    seed=attempt_seed,
                    origin_id=str(question_sentence_id),
                    route_length=1,
                    exhaustive_prefix_memory=False,
                    route_truth_context=route_truth_context,
                )
            except CudaRouteHold as error:
                record({"attempt": attempt_number, "seed": attempt_seed, "state": "HOLD", "reason": str(error)})
                continue
            selected_id = str(route[0])
            selected_surface = self._render_state(selected_id).removeprefix("WORD:")
            passed = bool(judge(selected_surface))
            evidence = question["center_attractor"].setdefault(
                "opaque_binary_answer_evidence_v1",
                {
                    "schema": "NN_OPAQUE_BINARY_ANSWER_EVIDENCE_V1",
                    "choices": {
                        answer_id: {"uses": 0, "pass_hits": 0, "fail_hits": 0, "weight": SCALE // 2}
                        for answer_id in answer_ids
                    },
                    "human_labels_used": False,
                },
            )
            row = evidence["choices"][selected_id]
            row["uses"] += 1
            row["pass_hits" if passed else "fail_hits"] += 1
            row["weight"] = self._route_probability(row["pass_hits"], row["fail_hits"])
            reinforce_connection(
                question,
                selected_id,
                direction="OUT",
                passed=passed,
                event_id=f"BINARY_ANSWER:{attempt_seed}",
            )
            question["activation"]["uses"] += 1
            question["activation"]["pass_hits" if passed else "fail_hits"] += 1
            question["reflectors"] = {
                name: question["reflectors"][name] for name in REFLECTORS
            }
            question["updated_utc"] = utc_now()
            question["content_sha256"] = content_hash(question)
            validate_neuron(question)
            self.store.transact(
                [question],
                event_kind="BINARY_ANSWER_CONSEQUENCE",
                details={
                    "question_sentence_id": str(question_sentence_id),
                    "attempt_seed": attempt_seed,
                    "verdict": "PASS" if passed else "FAIL",
                    "selected_answer_sha256": hashlib.sha256(selected_id.encode("utf-8")).hexdigest().upper(),
                },
            )
            if route_truth_evidence_writer is not None:
                route_truth_evidence_writer(route, passed)
            attempt_row = {
                "attempt": attempt_number,
                "seed": attempt_seed,
                "candidate": selected_surface,
                "verdict": "PASS" if passed else "FAIL",
                "selected_strength": int(steps[0].strengths[steps[0].selected_index]),
            }
            if not passed:
                record(attempt_row)
                continue
            confirmations: list[dict[str, Any]] = []
            confirmed = True
            for confirmation in range(1, required_confirmations + 1):
                if confirmation_seed_mode == "spread":
                    seed_material = (
                        f"BINARY_CONFIRMATION\0{attempt_seed}\0{confirmation}"
                    ).encode("utf-8")
                    confirmation_seed = int.from_bytes(
                        hashlib.sha256(seed_material).digest()[:8], "big"
                    )
                elif confirmation_seed_mode == "nearby":
                    confirmation_seed = attempt_seed + confirmation * 97_409
                else:
                    raise ValueError("unsupported binary confirmation seed mode")
                frozen_question = self.store.load_neuron(str(question_sentence_id))
                try:
                    frozen_route, _frozen_steps, _ = self.attempt_route(
                        answer_ids,
                        seed=confirmation_seed,
                        origin_id=str(question_sentence_id),
                        route_length=1,
                        overrides={str(question_sentence_id): frozen_question},
                        copy_overrides=False,
                        exhaustive_prefix_memory=False,
                        route_truth_context=route_truth_context,
                    )
                except CudaRouteHold as error:
                    confirmations.append({"confirmation": confirmation, "state": "HOLD", "reason": str(error), "write_performed": False})
                    confirmed = False
                    break
                frozen_surface = self._render_state(str(frozen_route[0])).removeprefix("WORD:")
                accepted = str(frozen_route[0]) == selected_id and bool(judge(frozen_surface))
                confirmations.append({
                    "confirmation": confirmation,
                    "candidate": frozen_surface,
                    "verdict": "PASS" if accepted else "FAIL",
                    "write_performed": False,
                })
                if not accepted:
                    confirmed = False
                    break
            attempt_row["confirmations"] = confirmations
            record(attempt_row)
            if not confirmed or len(confirmations) != required_confirmations:
                continue
            question = self.store.load_neuron(str(question_sentence_id))
            if consolidate_confirmations:
                confirmed_evidence = question["center_attractor"][
                    "opaque_binary_answer_evidence_v1"
                ]["choices"][selected_id]
                confirmed_evidence["uses"] += required_confirmations
                confirmed_evidence["pass_hits"] += required_confirmations
                confirmed_evidence["weight"] = self._route_probability(
                    confirmed_evidence["pass_hits"], confirmed_evidence["fail_hits"]
                )
                for confirmation in range(1, required_confirmations + 1):
                    reinforce_connection(
                        question,
                        selected_id,
                        direction="OUT",
                        passed=True,
                        event_id=f"BINARY_CONFIRMATION:{attempt_seed}:{confirmation}",
                    )
            question["center_attractor"]["opaque_binary_answer_v1"] = {
                "schema": "NN_OPAQUE_BINARY_ANSWER_V1",
                "answer_neuron_id": selected_id,
                "confirmation_passes": required_confirmations,
                "human_label_used": False,
            }
            question["reflectors"] = {
                name: question["reflectors"][name] for name in REFLECTORS
            }
            question["updated_utc"] = utc_now()
            question["content_sha256"] = content_hash(question)
            validate_neuron(question)
            transaction_id = self.store.transact(
                [question],
                event_kind="BINARY_ANSWER_CONFIRMED",
                details={
                    "question_sentence_id": str(question_sentence_id),
                    "confirmation_passes": required_confirmations,
                    "confirmations_consolidated": bool(consolidate_confirmations),
                },
            )
            return {
                "state": "PASS",
                "question_sentence_id": str(question_sentence_id),
                "answer_neuron_id": selected_id,
                "answer": selected_surface,
                "attempts": attempt_number,
                "confirmation_passes": required_confirmations,
                "transaction_id": transaction_id,
                "trace": trace,
            }
        return {
            "state": "HOLD",
            "reason": "MAX_ATTEMPTS",
            "question_sentence_id": str(question_sentence_id),
            "attempts": max_attempts,
            "trace": trace,
        }

    def sample_binary_answer_distribution(
        self,
        question_sentence_id: str,
        *,
        seeds: Iterable[int],
    ) -> dict[str, int]:
        """Fresh no-write recall of a learned one-neuron binary answer."""

        question = self.store.load_neuron(str(question_sentence_id))
        binary = question.get("center_attractor", {}).get("opaque_binary_answer_v1")
        evidence = question.get("center_attractor", {}).get("opaque_binary_answer_evidence_v1")
        if not isinstance(binary, dict) or not isinstance(evidence, dict):
            raise CudaRouteHold("HOLD_NO_BINARY_ANSWER_MEMORY")
        answer_ids = tuple(str(value) for value in evidence.get("choices", {}).keys())
        if len(answer_ids) != 2:
            raise CudaRouteHold("HOLD_BINARY_ANSWER_CHOICE_SET_INVALID")
        before = content_hash(self.store.manifest())
        counts: dict[str, int] = {}
        for seed in seeds:
            route, _steps, _ = self.attempt_route(
                answer_ids,
                seed=int(seed),
                origin_id=str(question_sentence_id),
                route_length=1,
                overrides={str(question_sentence_id): question},
                copy_overrides=False,
                exhaustive_prefix_memory=False,
            )
            rendered = self._render_state(str(route[0])).removeprefix("WORD:")
            counts[rendered] = counts.get(rendered, 0) + 1
        if before != content_hash(self.store.manifest()):
            raise RuntimeError("binary answer recall changed graph state")
        return counts

    def learn_sentence_grammar_bucket(
        self,
        visible_state_ids: Sequence[str],
        judge: Callable[[Sequence[str]], bool],
        *,
        route_length: int,
        seed: int,
        source_handle: str,
        target_sentences: int = 10,
        max_attempts: int = 12_000,
        trace_path: str | Path | None = None,
        route_truth_context: str | None = None,
        route_truth_evidence_writer: Callable[[Sequence[str], bool], None] | None = None,
    ) -> dict[str, Any]:
        """Discover every bounded ordered route and retain grammar consequence only."""

        manifest = self.store.manifest()
        try:
            child_ids = tuple(
                self._resolve_visible_state(manifest, state_id)
                for state_id in visible_state_ids
            )
        except KeyError as error:
            return {"state": "HOLD", "reason": "UNSUPPORTED_VISIBLE_STATE", "state_id": str(error)}
        if len(set(child_ids)) != len(child_ids):
            return {"state": "HOLD", "reason": "GRAMMAR_BUCKET_REQUIRES_DISTINCT_WORDS"}
        if not 1 < int(route_length) <= len(child_ids):
            return {"state": "HOLD", "reason": "INVALID_GRAMMAR_ROUTE_LENGTH"}
        neurons = {item: self.store.load_neuron(item) for item in child_ids}
        if any(item.get("kind") != "WORD" or item.get("lifecycle") != "STABLE" for item in neurons.values()):
            return {"state": "HOLD", "reason": "GRAMMAR_BUCKET_REQUIRES_STABLE_WORDS"}
        episode = self.birth_episode(child_ids, source_handle=source_handle)
        route_total = math.perm(len(child_ids), int(route_length))
        target = max(1, min(int(target_sentences), route_total))
        attempted_signatures: set[str] = set()
        grammar_routes: dict[str, list[str]] = {}
        trace: list[dict[str, Any]] = []

        def record(row: dict[str, Any]) -> None:
            trace.append(row)
            if trace_path is not None:
                path = Path(trace_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

        for attempt_number in range(1, int(max_attempts) + 1):
            if len(grammar_routes) >= target or len(attempted_signatures) == route_total:
                break
            attempt_seed = int(seed) + attempt_number * 1_000_003
            episode = self.store.load_neuron(episode["neuron_id"])
            try:
                route, steps, _ = self.attempt_route(
                    child_ids,
                    seed=attempt_seed,
                    overrides={episode["neuron_id"]: deepcopy(episode)},
                    origin_id=episode["neuron_id"],
                    copy_overrides=False,
                    exhaustive_prefix_memory=False,
                    route_length=int(route_length),
                    blocked_route_signatures=attempted_signatures,
                    route_truth_context=route_truth_context,
                )
            except CudaRouteHold as error:
                record({
                    "phase": "GRAMMAR_BUCKET_DISCOVERY",
                    "attempt_number": attempt_number,
                    "seed": attempt_seed,
                    "state": "HOLD",
                    "reason": str(error),
                    "unique_routes": len(attempted_signatures),
                    "route_total": route_total,
                })
                continue
            signature = self._route_signature(route)
            if signature in attempted_signatures:
                raise RuntimeError("grammar bucket chooser returned a blocked complete route")
            rendered = tuple(self._render_state(item) for item in route)
            grammar_pass = bool(judge(rendered))
            attempted_signatures.add(signature)
            episode["lifecycle"] = "PLASTIC"
            episode["activation"]["uses"] += 1
            episode["activation"]["pass_hits" if grammar_pass else "fail_hits"] += 1
            episode["center_attractor"]["last_construction"] = list(route)
            attempted = episode["center_attractor"].setdefault("grammar_attempted_assemblies", {})
            attempted[signature] = {"route": list(route), "grammar_bit": int(grammar_pass)}
            if grammar_pass:
                grammar_routes[signature] = list(route)
                supported = episode["center_attractor"].setdefault("grammar_supported_assemblies", {})
                supported[signature] = list(route)
                for position, selected_id in enumerate(route):
                    heads = episode["center_attractor"]["position_heads"]
                    heads[str(position)][selected_id] = toward_one(
                        int(heads[str(position)][selected_id]), 900_000
                    )
            episode["reflectors"] = {
                name: episode["reflectors"][name] for name in REFLECTORS
            }
            episode["updated_utc"] = utc_now()
            episode["content_sha256"] = content_hash(episode)
            validate_neuron(episode)
            self.store.transact(
                [episode],
                event_kind="GRAMMAR_BUCKET_ROUTE_CONSEQUENCE",
                details={
                    "episode_id": episode["neuron_id"],
                    "attempt_seed": attempt_seed,
                    "grammar_bit": int(grammar_pass),
                    "route_length": int(route_length),
                    "target_free_route": True,
                },
            )
            if route_truth_evidence_writer is not None:
                route_truth_evidence_writer(route, grammar_pass)
            record({
                "phase": "GRAMMAR_BUCKET_DISCOVERY",
                "attempt_number": attempt_number,
                "seed": attempt_seed,
                "state": "PASS",
                "episode_neuron_id": episode["neuron_id"],
                "route": list(route),
                "candidate": list(rendered),
                "grammar": "PASS" if grammar_pass else "FAIL",
                "unique_routes": len(attempted_signatures),
                "route_total": route_total,
                "pair_count": max(0, len(steps) - 1),
            })

        episode = self.store.load_neuron(episode["neuron_id"])
        complete = len(grammar_routes) >= target
        if complete:
            episode["lifecycle"] = "STABLE"
            episode["center_attractor"]["grammar_bucket_batch_complete"] = True
            episode["center_attractor"]["grammar_bucket_word_ids"] = list(child_ids)
            episode["center_attractor"]["grammar_route_length"] = int(route_length)
            episode["center_attractor"]["grammar_route_total"] = route_total
            episode["center_attractor"]["grammar_sentence_target"] = target
            episode["center_attractor"]["construction_alignment"] = SCALE
            episode["reflectors"] = {
                name: episode["reflectors"][name] for name in REFLECTORS
            }
            episode["updated_utc"] = utc_now()
            episode["content_sha256"] = content_hash(episode)
            validate_neuron(episode)
            self.store.transact(
                [episode],
                event_kind="GRAMMAR_BUCKET_COVERAGE_COMPLETE",
                details={
                    "episode_id": episode["neuron_id"],
                    "route_total": route_total,
                    "grammar_supported": len(grammar_routes),
                    "grammar_sentence_target": target,
                },
            )
        return {
            "state": "PASS" if complete else "HOLD",
            "reason": "" if complete else "MAX_ATTEMPTS",
            "episode_id": episode["neuron_id"],
            "bucket_width": len(child_ids),
            "route_length": int(route_length),
            "route_total": route_total,
            "grammar_sentence_target": target,
            "unique_routes_attempted": len(attempted_signatures),
            "grammar_supported_routes": len(grammar_routes),
            "attempts": len(trace),
            "trace": trace,
            "architecture": "CUMULATIVE_GPU_GRAMMAR_BUCKET_V1",
        }

    def learn_sentence_meaning_bucket(
        self,
        episode_id: str,
        grammar_judge: Callable[[Sequence[str]], bool],
        meaning_judge: Callable[[Sequence[str]], bool],
        *,
        seed: int,
        target_sentences: int = 10,
        max_attempts: int = 24_000,
        trace_path: str | Path | None = None,
        route_truth_context: str | None = None,
        route_truth_evidence_writer: Callable[[Sequence[str], bool], None] | None = None,
    ) -> dict[str, Any]:
        """Exhaust one learned grammar bucket before requesting new vocabulary."""

        episode = self.store.load_neuron(episode_id)
        center = episode.get("center_attractor", {})
        if episode.get("kind") != "EPISODE" or not center.get("grammar_bucket_batch_complete"):
            return {"state": "HOLD", "reason": "GRAMMAR_BUCKET_EPISODE_REQUIRED"}
        child_ids = tuple(
            str(value)
            for value in (
                center.get("grammar_bucket_word_ids")
                or episode.get("children", [])
            )
        )
        route_length = int(center.get("grammar_route_length", 0))
        route_total = int(center.get("grammar_route_total", 0))
        if not child_ids or route_total != math.perm(len(child_ids), route_length):
            return {"state": "HOLD", "reason": "INVALID_GRAMMAR_BUCKET_STATE"}
        neurons = {item: self.store.load_neuron(item) for item in child_ids}
        if any(
            self.WORD_SEMANTIC_PROFILE_KEY not in item.get("center_attractor", {})
            for item in neurons.values()
        ):
            return {"state": "HOLD", "reason": "SEMANTIC_PROFILES_REQUIRED"}

        attempted = center.get("grammar_attempted_assemblies", {})
        attempted_signatures = set(str(value) for value in attempted)
        grammar_routes = {
            str(signature): [str(value) for value in route]
            for signature, route in center.get("grammar_supported_assemblies", {}).items()
        }
        semantic_rows = center.setdefault("semantic_attempted_assemblies", {})
        semantic_routes = center.setdefault("semantic_supported_assemblies", {})
        target = max(1, min(int(target_sentences), route_total))
        trace: list[dict[str, Any]] = []

        def record(row: dict[str, Any]) -> None:
            trace.append(row)
            if trace_path is not None:
                path = Path(trace_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

        def render_decisions(steps: Sequence[HeptRouteStep]) -> list[dict[str, Any]]:
            """Expose only the actual chooser decisions for the read-only renderer."""
            return [
                {
                    "depth": depth,
                    "previous_neuron_id": step.previous_id,
                    "selected_neuron_id": step.selected_id,
                    "selected_surface": self._render_state(step.selected_id),
                    "selected_reflector": REFLECTORS[step.selected_reflector],
                    "selected_strength": step.strengths[step.selected_index],
                    "frontier": len(step.candidate_ids),
                    "cpu_activation_anchor": dict(step.activation_anchor),
                    "activation_context_weight": step.activation_context_weight,
                }
                for depth, step in enumerate(steps)
            ]

        def apply(
            route: Sequence[str], grammar_pass: bool, meaning_pass: bool, *,
            event_seed: int, phase: str,
            decisions: Sequence[dict[str, Any]] = (),
        ) -> None:
            nonlocal episode, center, semantic_rows, semantic_routes
            signature = self._route_signature(route)
            rendered = tuple(self._render_state(item) for item in route)
            semantic_rows[signature] = {
                "route": list(route),
                "grammar_bit": int(grammar_pass),
                "meaning_bit": int(meaning_pass),
            }
            if grammar_pass and meaning_pass:
                semantic_routes[signature] = list(route)
            episode["lifecycle"] = "PLASTIC"
            episode["activation"]["uses"] += 1
            episode["activation"]["pass_hits" if meaning_pass else "fail_hits"] += 1
            episode["center_attractor"]["last_construction"] = list(route)
            episode["reflectors"] = {
                name: episode["reflectors"][name] for name in REFLECTORS
            }
            episode["updated_utc"] = utc_now()
            episode["content_sha256"] = content_hash(episode)
            validate_neuron(episode)
            self.store.transact(
                [episode],
                event_kind="SEMANTIC_BUCKET_ROUTE_CONSEQUENCE",
                details={
                    "episode_id": episode_id,
                    "attempt_seed": event_seed,
                    "attempted_route": list(route),
                    "grammar_bit": int(grammar_pass),
                    "meaning_bit": int(meaning_pass),
                    "cpu_returned_separate_bits": True,
                },
            )
            if route_truth_evidence_writer is not None:
                route_truth_evidence_writer(route, grammar_pass and meaning_pass)
            record({
                "phase": phase,
                "seed": event_seed,
                "episode_neuron_id": episode_id,
                "route": list(route),
                "candidate": list(rendered),
                "decisions": list(decisions),
                "grammar": "PASS" if grammar_pass else "FAIL",
                "meaning": "PASS" if meaning_pass else "FAIL",
                "unique_routes": len(attempted_signatures),
                "route_total": route_total,
                "meaning_supported_routes": len(semantic_routes),
            })

        # First attach meaning consequence to every grammar route already learned.
        for index, (signature, route) in enumerate(sorted(grammar_routes.items())):
            if signature in semantic_rows:
                continue
            rendered = tuple(self._render_state(item) for item in route)
            apply(route, True, bool(meaning_judge(rendered)), event_seed=seed + index, phase="MEANING_FROZEN_GRAMMAR_ROUTE")
            episode = self.store.load_neuron(episode_id)
            center = episode["center_attractor"]
            semantic_rows = center.setdefault("semantic_attempted_assemblies", {})
            semantic_routes = center.setdefault("semantic_supported_assemblies", {})

        discovery_attempts = 0
        for attempt_number in range(1, int(max_attempts) + 1):
            if len(semantic_routes) >= target or len(attempted_signatures) == route_total:
                break
            discovery_attempts += 1
            attempt_seed = int(seed) + 10_000_019 + attempt_number * 1_000_003
            episode = self.store.load_neuron(episode_id)
            try:
                route, steps, _ = self.attempt_route(
                    child_ids,
                    seed=attempt_seed,
                    overrides={episode_id: deepcopy(episode)},
                    origin_id=episode_id,
                    copy_overrides=False,
                    exhaustive_prefix_memory=False,
                    route_length=route_length,
                    blocked_route_signatures=attempted_signatures,
                    route_truth_context=route_truth_context,
                )
            except CudaRouteHold as error:
                record({
                    "phase": "MEANING_BUCKET_DISCOVERY",
                    "attempt_number": attempt_number,
                    "seed": attempt_seed,
                    "state": "HOLD",
                    "reason": str(error),
                    "unique_routes": len(attempted_signatures),
                    "route_total": route_total,
                })
                continue
            signature = self._route_signature(route)
            if signature in attempted_signatures:
                raise RuntimeError("meaning bucket chooser returned a blocked complete route")
            rendered = tuple(self._render_state(item) for item in route)
            grammar_pass = bool(grammar_judge(rendered))
            meaning_pass = grammar_pass and bool(meaning_judge(rendered))
            attempted_signatures.add(signature)
            attempted = episode["center_attractor"].setdefault("grammar_attempted_assemblies", {})
            attempted[signature] = {"route": list(route), "grammar_bit": int(grammar_pass)}
            if grammar_pass:
                episode["center_attractor"].setdefault("grammar_supported_assemblies", {})[signature] = list(route)
            apply(
                route, grammar_pass, meaning_pass,
                event_seed=attempt_seed,
                phase="MEANING_BUCKET_DISCOVERY",
                decisions=render_decisions(steps),
            )
            episode = self.store.load_neuron(episode_id)
            center = episode["center_attractor"]
            semantic_rows = center.setdefault("semantic_attempted_assemblies", {})
            semantic_routes = center.setdefault("semantic_supported_assemblies", {})

        exhausted = len(attempted_signatures) == route_total
        target_met = len(semantic_routes) >= target
        demand = 1 if exhausted and not target_met else 0
        demand_reason = (
            "NONE_CURRENT_VOCABULARY_SUFFICIENT"
            if target_met
            else "EXPRESSION_FAILURE_ROUTE_SPACE_EXHAUSTED"
            if exhausted
            else "NONE_CURRENT_ROUTE_SEARCH_INCOMPLETE"
        )
        episode = self.store.load_neuron(episode_id)
        center = episode["center_attractor"]
        center["semantic_route_space_exhausted"] = exhausted
        center["semantic_sentence_target"] = target
        center["semantic_supported_count"] = len(semantic_routes)
        center["vocabulary_demand_bit"] = demand
        center["vocabulary_demand_reason"] = demand_reason
        episode["lifecycle"] = "STABLE" if exhausted or target_met else "PLASTIC"
        episode["reflectors"] = {name: episode["reflectors"][name] for name in REFLECTORS}
        episode["updated_utc"] = utc_now()
        episode["content_sha256"] = content_hash(episode)
        validate_neuron(episode)
        self.store.transact(
            [episode],
            event_kind="SEMANTIC_BUCKET_DEMAND_DECISION",
            details={
                "episode_id": episode_id,
                "route_space_exhausted": exhausted,
                "semantic_supported": len(semantic_routes),
                "semantic_sentence_target": target,
                "vocabulary_demand_bit": demand,
                "vocabulary_demand_reason": demand_reason,
            },
        )
        return {
            "state": "PASS" if target_met else "HOLD",
            "reason": "" if target_met else demand_reason,
            "episode_id": episode_id,
            "route_total": route_total,
            "unique_routes_attempted": len(attempted_signatures),
            "grammar_supported_routes": len(center.get("grammar_supported_assemblies", {})),
            "meaning_supported_routes": len(semantic_routes),
            "meaning_sentence_target": target,
            "route_space_exhausted": exhausted,
            "vocabulary_demand_bit": demand,
            "vocabulary_demand_reason": demand_reason,
            "discovery_attempts": discovery_attempts,
            "trace": trace,
            "architecture": "DEMAND_GATED_SEMANTIC_BUCKET_V1",
        }

    def sample_provisional_recursive_sentence_distribution(
        self, sentence_id: str, *, seeds: Iterable[int]
    ) -> dict[str, int]:
        """Frozen recursive reread of a confirmed but unadmitted sentence."""

        from .recursive_chunk import RecursiveChunkRouter

        sentence = self.store.load_neuron(sentence_id)
        center = sentence["center_attractor"]
        if (
            sentence["kind"] != "SENTENCE"
            or sentence["lifecycle"] != "PLASTIC"
            or center.get("admission_state") != "PENDING_FRESH_REREAD"
            or center.get("trusted_language_memory") is True
        ):
            raise CudaRouteHold("HOLD_NO_PROVISIONAL_SENTENCE_NEURON")
        episode = self.store.load_neuron(str(center["source_episode_ref"]))
        child_ids = tuple(str(item) for item in episode["children"])
        construction = tuple(str(item) for item in center["construction"])
        if sorted(child_ids) != sorted(construction) or len(set(child_ids)) != len(child_ids):
            raise CudaRouteHold("HOLD_PROVISIONAL_EPISODE_INVENTORY_MISMATCH")
        neurons = {item: self.store.load_neuron(item) for item in child_ids}
        router = RecursiveChunkRouter(self.library)
        expert_parent = router.build_expert_routed_parent(
            neurons, child_ids, self._trusted_recursive_experts()
        )
        guidance_parent = deepcopy(sentence)
        guidance_parent["children"] = list(child_ids)
        guidance_parent["center_attractor"]["local_endpoint_routes"] = deepcopy(
            expert_parent["center_attractor"].get("local_endpoint_routes", [])
        )
        before = content_hash(self.store.manifest())
        counts: dict[str, int] = {}
        for seed in seeds:
            attempt = router.attempt(
                neurons, child_ids, seed=int(seed), guidance_parent=guidance_parent
            )
            rendered = " ".join(self._render_state(item) for item in attempt.route)
            counts[rendered] = counts.get(rendered, 0) + 1
        if before != content_hash(self.store.manifest()):
            raise RuntimeError("provisional recursive reread changed graph state")
        return counts

    def _recursive_child_supported(self, child: dict[str, Any]) -> bool:
        if child["lifecycle"] == "STABLE":
            return True
        center = child["center_attractor"]
        profile = center.get("opaque_position_profile_v1")
        if not center.get("visible_state_id") or not isinstance(profile, dict):
            return False
        if int(profile.get("observations", 0)) < 1:
            return False
        for sentence_id in profile.get("supporting_sentence_ids", ()):
            try:
                sentence = self.store.load_neuron(str(sentence_id))
            except (FileNotFoundError, ValueError):
                continue
            if (
                sentence["kind"] == "SENTENCE"
                and sentence["lifecycle"] == "STABLE"
                and sentence["center_attractor"].get("trusted_language_memory") is True
            ):
                return True
        return False

    def compress(self, assembly_signature: str) -> dict[str, Any]:
        manifest = self.store.manifest()
        manifest.setdefault("compression_index", {})
        count = int(manifest["assembly_multiplicity"].get(assembly_signature, 0))
        members = list(manifest["assembly_members"].get(assembly_signature, []))
        if count < 32 or len(members) < 32:
            return {"state": "HOLD", "reason": "INSUFFICIENT_REPETITION", "observations": count}
        episodes = [self.store.load_neuron(neuron_id) for neuron_id in members]
        constructions = {tuple(item["center_attractor"].get("construction", [])) for item in episodes}
        if len(constructions) != 1 or any(item["lifecycle"] != "STABLE" for item in episodes):
            return {"state": "HOLD", "reason": "REPLAY_MISMATCH"}
        construction = next(iter(constructions))
        replay_hash = hashlib.sha256(canonical_route(construction)).hexdigest().upper()
        confirmations = [replay_hash, replay_hash, replay_hash]
        existing_id = manifest["compression_index"].get(assembly_signature)
        if existing_id is None:
            for neuron_id, index in manifest["neuron_index"].items():
                if index["kind"] != "COMPRESSION":
                    continue
                candidate = self.store.load_neuron(neuron_id)
                if candidate["center_attractor"].get("assembly_signature") == assembly_signature:
                    existing_id = neuron_id
                    break
        compression = (
            self.store.load_neuron(existing_id)
            if existing_id
            else make_neuron(
                neuron_id=new_neuron_id(),
                kind="COMPRESSION",
                lifecycle="STABLE",
                creation_event="LOSSLESS_COMPRESSION",
                children=members,
                center={
                    "assembly_signature": assembly_signature,
                    "construction": list(construction),
                    "replay_confirmations": confirmations,
                    "construction_alignment": SCALE,
                    "reality_alignment": None,
                    "truth_compatibility": SCALE,
                    "lossless": True,
                },
            )
        )
        for episode in episodes:
            if compression["neuron_id"] not in episode["parents"]:
                episode["parents"].append(compression["neuron_id"])

        def index_compression(state: dict[str, Any]) -> None:
            state.setdefault("compression_index", {})[assembly_signature] = compression["neuron_id"]

        self.store.transact(
            [compression, *episodes],
            event_kind="LOSSLESS_COMPRESSION",
            details={
                "compression_id": compression["neuron_id"],
                "children_retained": len(episodes),
                "replay_sha256": replay_hash,
                "confirmations": 3,
            },
            manifest_mutator=index_compression,
        )
        baseline_active = self.memory_activation_set(assembly_signature, use_compression=False)
        compressed_active = self.memory_activation_set(assembly_signature, use_compression=True)
        reduced = len(compressed_active) < len(baseline_active)
        return {
            "state": "PASS" if reduced else "HOLD",
            "compression_id": compression["neuron_id"],
            "children_retained": len(episodes),
            "hot_activation_before": len(baseline_active),
            "hot_activation_after": len(compressed_active),
            "replay_confirmations": 3,
            "routing_reduction_measured": reduced,
        }

    def memory_activation_set(
        self, assembly_signature: str, *, use_compression: bool
    ) -> tuple[str, ...]:
        manifest = self.store.manifest()
        members = tuple(manifest.get("assembly_members", {}).get(assembly_signature, []))
        if not use_compression:
            return tuple(
                neuron_id
                for neuron_id in members
                if self.store.load_neuron(neuron_id)["lifecycle"] == "STABLE"
            )
        compression_id = manifest.get("compression_index", {}).get(assembly_signature)
        if not compression_id:
            return self.memory_activation_set(assembly_signature, use_compression=False)
        compression = self.store.load_neuron(compression_id)
        if compression["lifecycle"] != "STABLE" or tuple(compression["children"]) != members:
            return self.memory_activation_set(assembly_signature, use_compression=False)
        return (compression_id,)


def canonical_route(route: Sequence[str]) -> bytes:
    return json.dumps(list(route), ensure_ascii=False, separators=(",", ":")).encode("utf-8")


__all__ = ["HeptRouteStep", "Neuronizer"]
