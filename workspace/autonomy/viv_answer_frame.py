"""Local-model proposal plus deterministic validation for viv_answer_frame_v1."""

from __future__ import annotations

import json
import re
import unicodedata
import urllib.request


LOCAL_CHAT_URL = "http://127.0.0.1:1234/v1/chat/completions"
FRAME_SCHEMA = "viv_answer_frame_v1"
MAX_FRAME_RETRIES = 3
TOP_LEVEL_KEYS = {
    "schema", "state", "target", "subject", "relation", "object",
    "polarity", "modality", "quantifier", "qualifiers", "evidence", "missing_fields",
}
TARGETS = {"subject", "relation", "object", "value", "truth"}
POLARITIES = {"POSITIVE", "NEGATIVE"}
MODALITIES = {"ASSERTED", "POSSIBLE", "REQUIRED", "CONDITIONAL"}
QUANTIFIERS = {"SPECIFIC", "ALL", "SOME", "NONE", "COUNT"}


def _norm(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def _extract_first_json_object(raw: str) -> str | None:
    """Extract the first complete brace-delimited object, respecting JSON strings."""
    start = raw.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(raw)):
        char = raw[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return raw[start:index + 1]
    return None


def _canonical(surface: str, domain: str, aliases: dict[tuple[str, str], str],
               correction: dict[str, str], *,
               relation_aliases: dict[tuple[str, str], str] | None = None,
               is_relation: bool = False) -> str:
    normalized = _candidate_normalize(surface, correction)
    if is_relation and relation_aliases and (domain, normalized) in relation_aliases:
        return relation_aliases[(domain, normalized)]
    return aliases.get((domain, normalized), normalized)


def _candidate_normalize(surface: str, correction: dict[str, str]) -> str:
    normalized = _norm(surface)
    for suspect, replacement in correction.items():
        normalized = re.sub(rf"(?<!\w){re.escape(_norm(suspect))}(?!\w)",
                            _norm(replacement), normalized)
    return normalized


class LocalAnswerFrameParser:
    """DeepSeek proposes JSON frames; Python validates structure and evidence."""

    def __init__(self, *, model_id: str, active_adapter: str | None,
                 aliases: dict[tuple[str, str], str] | None = None,
                 relation_aliases: dict[tuple[str, str], str] | None = None,
                 relation_signatures: dict[str, dict[str, str]] | None = None):
        self.model_id = model_id
        self.active_adapter = active_adapter
        self.aliases = aliases or {}
        self.relation_aliases = relation_aliases or {}
        self.relation_signatures = relation_signatures or {}

    def _propose(self, question: str, source_text: str, answer: str,
                 domain: str, correction: dict[str, str],
                 candidate_span_hint: dict | None = None,
                 validation_error: str | None = None) -> dict:
        template = {
            "schema": FRAME_SCHEMA, "state": "PARSED", "target": "subject",
            "subject": {"type": "entity", "surface": "", "canonical_id": ""},
            "relation": {"type": "relation", "surface": "", "canonical_id": ""},
            "object": None,
            "polarity": {"value": "POSITIVE", "scope": "claim"},
            "modality": "ASSERTED",
            "quantifier": {"kind": "SPECIFIC", "value": None},
            "qualifiers": [],
            "evidence": [{"field": "subject", "source": "sentence", "quote": ""}],
            "missing_fields": [],
        }
        domain_aliases = [
            {"alias": alias, "canonical_id": entity_id}
            for (alias_domain, alias), entity_id in self.aliases.items()
            if alias_domain == domain
        ]
        domain_relation_aliases = [
            {"alias": alias, "canonical_relation_id": relation_id}
            for (alias_domain, alias), relation_id in self.relation_aliases.items()
            if alias_domain == domain
        ]
        prompt = (
            "Extract the proposition expressed by ANSWER for QUESTION, grounded in SENTENCE.\n"
            "Return exactly one valid JSON object with every key in TEMPLATE. Replace blank strings with extracted values; do not omit keys. "
            "Output no Markdown fences, labels, or text before or after the JSON object.\n"
            f"TEMPLATE: {json.dumps(template, ensure_ascii=False)}\n"
            "Allowed: state PARSED or UNKNOWN; target subject, relation, object, value, or truth; "
            "polarity POSITIVE or NEGATIVE; modality ASSERTED, POSSIBLE, REQUIRED, or CONDITIONAL; "
            "quantifier SPECIFIC, ALL, SOME, NONE, or COUNT.\n"
            "For each non-null subject, relation, and object, add evidence with that field. "
            "Copy evidence quote exactly from sentence or question; it must be unique in that source. "
            "Do not include offset metadata; the validator derives character offsets from the exact quote.\n"
            "For copular clauses, do not use only is/was/are/were as relation: extract the meaningful property complement (such as muddy or acute) as relation or object.\n"
            "Term surface is the exact raw phrase from evidence, including any original typo. "
            "Use the spelling candidate only to interpret that typo, not as evidence.\n"
            "canonical_id is NFC, casefolded, and whitespace-collapsed unless a domain alias maps it. "
            "Use SPECIFIC/null when no quantifier is stated and [] when there are no qualifiers. "
            "If uncertain or unsupported, set state UNKNOWN and list missing_fields.\n"
            f"QUESTION: {question}\nSENTENCE: {source_text}\nANSWER: {answer}\n"
            f"DOMAIN: {domain}\nALIASES: {json.dumps(domain_aliases, ensure_ascii=False)}\n"
            f"RELATION_ALIASES: {json.dumps(domain_relation_aliases, ensure_ascii=False)}\n"
            f"CANDIDATE_SPAN_HINT: {json.dumps(candidate_span_hint, ensure_ascii=False)}\n"
            "The hint is an interpretation hypothesis only. Preserve the exact surface quote and offsets from SENTENCE.\n"
            f"PREVIOUS_VALIDATION_ERROR: {validation_error or 'none'}\n"
            "If an error is present, correct that exact issue and return a complete JSON object matching TEMPLATE.\n"
            f"SPELLING_CANDIDATE: {json.dumps(correction, ensure_ascii=False)}\nJSON:"
        )
        request = urllib.request.Request(
            LOCAL_CHAT_URL,
            data=json.dumps({
                "model": self.model_id,
                "messages": [
                    {"role": "system", "content": "You are a semantic frame extractor. Return valid JSON only, with every required key."},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 384, "temperature": 0,
                "stop": ["\nUSER:", "\nSYSTEM:", "\nSPELLING_CANDIDATE:", "\nJSON:", "\nASSISTANT:"],
            }, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=100) as response:
            result = json.load(response)
        if result.get("active_adapter") != self.active_adapter:
            raise RuntimeError("local adapter changed during frame extraction")
        raw = result["choices"][0]["message"]["content"].strip()
        extracted = _extract_first_json_object(raw)
        if extracted is None:
            return {"invalid_model_json": raw,
                    "parse_error": "No complete JSON object found"}
        try:
            return json.loads(extracted)
        except json.JSONDecodeError as exc:
            return {"invalid_model_json": raw,
                    "parse_error": f"{exc.msg} at line {exc.lineno}, column {exc.colno}"}

    def _propose_validated(self, *, question: str, source_text: str, answer: str,
                           domain: str, correction: dict[str, str],
                           candidate_span_hint: dict | None = None) -> dict:
        last = {"state": "UNKNOWN", "reason": "NO_ATTEMPT"}
        errors = []
        for attempt in range(MAX_FRAME_RETRIES + 1):
            frame = self._propose(
                question, source_text, answer, domain, correction,
                candidate_span_hint, errors[-1] if errors else None,
            )
            checked = self._validate(frame, question, source_text, domain,
                                     self.aliases, correction, self.relation_aliases,
                                     self.relation_signatures)
            if checked["state"] == "PARSED":
                checked["attempts"] = attempt + 1
                checked["retry_errors"] = errors
                return checked
            reason = checked.get("reason", "VALIDATION_FAILED")
            if reason == "MODEL_JSON_INVALID":
                error = f"{reason}; parse_error={checked.get('parse_error') or 'unspecified'}"
            elif reason == "FRAME_KEYS_INVALID":
                observed = sorted(frame) if isinstance(frame, dict) else []
                missing = sorted(TOP_LEVEL_KEYS - set(observed))
                extra = sorted(set(observed) - TOP_LEVEL_KEYS)
                error = (f"{reason}; missing_keys={missing}; unexpected_keys={extra}; "
                         f"required_keys={sorted(TOP_LEVEL_KEYS)}")
            else:
                error = reason
            errors.append(error)
            last = checked
        last["attempts"] = MAX_FRAME_RETRIES + 1
        last["retry_errors"] = errors
        return last

    @staticmethod
    def _validate(frame: dict, question: str, sentence: str,
                  domain: str, aliases: dict[tuple[str, str], str],
                  correction: dict[str, str],
                  relation_aliases: dict[tuple[str, str], str],
                  relation_signatures: dict[str, dict[str, str]]) -> dict:
        if isinstance(frame, dict) and "invalid_model_json" in frame:
            return {"state": "UNKNOWN", "reason": "MODEL_JSON_INVALID",
                    "parse_error": frame.get("parse_error"), "frame": frame}
        if not isinstance(frame, dict) or set(frame) != TOP_LEVEL_KEYS:
            return {"state": "UNKNOWN", "reason": "FRAME_KEYS_INVALID", "frame": frame}
        if frame["schema"] != FRAME_SCHEMA or frame["state"] not in {"PARSED", "UNKNOWN"}:
            return {"state": "UNKNOWN", "reason": "SCHEMA_OR_STATE_INVALID", "frame": frame}
        if frame["state"] == "UNKNOWN":
            return {"state": "UNKNOWN", "reason": "MODEL_MARKED_UNKNOWN", "frame": frame}
        if (frame["target"] not in TARGETS or not isinstance(frame["polarity"], dict)
                or set(frame["polarity"]) != {"value", "scope"}
                or frame["polarity"].get("value") not in POLARITIES
                or not isinstance(frame["polarity"].get("scope"), str)):
            return {"state": "UNKNOWN", "reason": "TARGET_OR_POLARITY_INVALID", "frame": frame}
        if (frame["modality"] not in MODALITIES or not isinstance(frame["quantifier"], dict)
                or set(frame["quantifier"]) != {"kind", "value"}
                or frame["quantifier"].get("kind") not in QUANTIFIERS
                or not isinstance(frame["qualifiers"], list)
                or not isinstance(frame["evidence"], list)
                or not isinstance(frame["missing_fields"], list)):
            return {"state": "UNKNOWN", "reason": "MODALITY_OR_QUANTIFIER_INVALID", "frame": frame}
        if any(not isinstance(q, dict) or set(q) != {"kind", "value", "scope"}
               for q in frame["qualifiers"]):
            return {"state": "UNKNOWN", "reason": "QUALIFIER_SHAPE_INVALID", "frame": frame}
        sources = {"sentence": sentence, "question": question}
        evidence_by_field: dict[str, list[dict]] = {}
        for span in frame["evidence"]:
            if (not isinstance(span, dict) or
                    set(span) not in ({"field", "source", "quote"},
                                      {"field", "source", "quote", "start", "end"},
                                      {"field", "source", "quote", "offsets"})):
                return {"state": "UNKNOWN", "reason": "EVIDENCE_SHAPE_INVALID", "frame": frame}
            source = sources.get(span["source"])
            quote = span["quote"]
            if source is None or not isinstance(quote, str) or not quote:
                return {"state": "UNKNOWN", "reason": "EVIDENCE_TYPES_INVALID", "frame": frame}
            if "start" in span:
                start, end = span["start"], span["end"]
                if type(start) is not int or type(end) is not int:
                    return {"state": "UNKNOWN", "reason": "EVIDENCE_TYPES_INVALID", "frame": frame}
            else:
                # Model-provided nested offset metadata is ignored. The exact,
                # unique quote remains authoritative and offsets are derived here.
                start = source.find(quote)
                if start < 0 or source.find(quote, start + 1) >= 0:
                    return {"state": "UNKNOWN", "reason": "EVIDENCE_QUOTE_NOT_UNIQUE", "frame": frame}
                end = start + len(quote)
            if start < 0 or end <= start or end > len(source) or source[start:end] != quote:
                return {"state": "UNKNOWN", "reason": "EVIDENCE_OFFSET_MISMATCH", "frame": frame}
            if ((start and (source[start - 1].isalnum() or source[start - 1] == "_"))
                    or (end < len(source) and (source[end].isalnum() or source[end] == "_"))):
                return {"state": "UNKNOWN", "reason": "EVIDENCE_NOT_TOKEN_ALIGNED", "frame": frame}
            evidence_by_field.setdefault(span["field"], []).append(span)
            span["start"] = start
            span["end"] = end

        normalization_steps = []
        relation_term = frame.get("relation")
        if (isinstance(relation_term, dict) and frame.get("object") is None
                and _norm(str(relation_term.get("surface", ""))) in {"is", "was", "are", "were", "be"}):
            # Deterministically recover a copular property complement from the
            # cited source. Negation and ambiguous complements fail closed.
            pattern = re.compile(
                r"\b(?:is|was|are|were)\s+(?:(?:described\s+as|known\s+as|called)\s+)?"
                r"(?:(?:a|an|the)\s+)?([^\W\d_][\w-]*)",
                re.IGNORECASE | re.UNICODE,
            )
            matches = list(pattern.finditer(sentence))
            if len(matches) == 1 and matches[0].group(1).casefold() not in {"not", "never", "no"}:
                match = matches[0]
                complement = match.group(1)
                relation_term = dict(relation_term)
                relation_term["surface"] = complement
                frame["relation"] = relation_term
                span = {"field": "relation", "source": "sentence", "start": match.start(1),
                        "end": match.end(1), "quote": complement}
                frame["evidence"].append(span)
                evidence_by_field.setdefault("relation", []).append(span)
                normalization_steps.append({"operation": "copular_complement_from_source",
                                            "surface": complement,
                                            "start": match.start(1), "end": match.end(1)})

        normalized = {"target": frame["target"], "polarity": frame["polarity"],
                      "modality": frame["modality"], "quantifier": frame["quantifier"],
                      "qualifiers": frame["qualifiers"]}
        if frame["relation"] is None or (frame["subject"] is None and frame["object"] is None):
            return {"state": "UNKNOWN", "reason": "CORE_PROPOSITION_INCOMPLETE", "frame": frame}
        for field in ("subject", "relation", "object"):
            term = frame[field]
            if term is None:
                normalized[field] = None
                continue
            if not isinstance(term, dict) or set(term) != {"type", "surface", "canonical_id"}:
                return {"state": "UNKNOWN", "reason": f"{field.upper()}_SHAPE_INVALID", "frame": frame}
            spans = frame["evidence"]
            if (not isinstance(term["type"], str) or not isinstance(term["canonical_id"], str)
                    or not isinstance(term["surface"], str) or not term["surface"] or not spans):
                return {"state": "UNKNOWN", "reason": f"{field.upper()}_UNGROUNDED", "frame": frame}
            surface_pattern = re.escape(_candidate_normalize(term["surface"], correction)).replace(r"\ ", r"\s+")
            direct_support = any(re.search(rf"(?<!\w){surface_pattern}(?!\w)",
                                           _candidate_normalize(span["quote"], correction))
                                 for span in spans)
            expected_id = _canonical(
                term["surface"], domain, aliases, correction,
                relation_aliases=relation_aliases, is_relation=(field == "relation"),
            )
            alias_source = relation_aliases if field == "relation" else aliases
            alias_surfaces = [alias for (alias_domain, alias), canonical_id in alias_source.items()
                              if alias_domain == domain and canonical_id == expected_id]
            alias_support = any(
                re.search(rf"(?<!\w){re.escape(_candidate_normalize(alias, correction))}(?!\w)",
                          _candidate_normalize(span["quote"], correction))
                for span in spans for alias in alias_surfaces
            )
            if not direct_support and not alias_support:
                return {"state": "UNKNOWN", "reason": f"{field.upper()}_SPAN_DOES_NOT_SUPPORT_SURFACE", "frame": frame}
            expected_id = _canonical(
                term["surface"], domain, aliases, correction,
                relation_aliases=relation_aliases, is_relation=(field == "relation"),
            )
            if field == "relation" and _norm(term["surface"]) in {"is", "was", "are", "were", "be"} and frame["object"] is None:
                return {"state": "UNKNOWN", "reason": "COPULA_WITHOUT_PREDICATE", "frame": frame}
            normalized[field] = {"type": term["type"], "canonical_id": expected_id}
        for qualifier in frame["qualifiers"]:
            field = "qualifier:" + str(qualifier["kind"])
            value = _norm(str(qualifier["value"]))
            spans = evidence_by_field.get(field, [])
            if not spans or not value or not any(value in _norm(span["quote"]) for span in spans):
                return {"state": "UNKNOWN", "reason": "QUALIFIER_UNGROUNDED", "frame": frame}
        if frame["missing_fields"]:
            return {"state": "UNKNOWN", "reason": "REQUIRED_FIELDS_MISSING", "frame": frame}
        relation = normalized["relation"]
        obj = normalized["object"]
        if relation and relation["canonical_id"] == "copula" and obj and obj["type"] in {"property", "value", "quality"}:
            normalized["relation"] = {"type": "relation", "canonical_id": obj["canonical_id"]}
            normalized["object"] = None
            relation = normalized["relation"]
            obj = None
        if relation and obj:
            expected_object_type = relation_signatures.get(
                relation["canonical_id"], {}
            ).get("object")
            if expected_object_type:
                normalized["object"] = {
                    "type": expected_object_type,
                    "canonical_id": obj["canonical_id"],
                }
        normalized["qualifiers"] = sorted(frame["qualifiers"], key=lambda q: json.dumps(q, sort_keys=True, ensure_ascii=False))
        return {"state": "PARSED", "reason": "VALIDATED", "normalized": normalized,
                "normalization_steps": normalization_steps, "frame": frame}

    def compare(self, *, question: str, original_sentence: str, corrected_sentence: str,
                original_answer: str, corrected_answer: str, domain: str,
                correction: dict[str, str],
                candidate_span_hint: dict | None = None) -> dict:
        hint = candidate_span_hint
        if hint is not None:
            if (set(hint) != {"start", "end", "surface", "candidate"}
                    or type(hint["start"]) is not int or type(hint["end"]) is not int
                    or not isinstance(hint["surface"], str)
                    or not isinstance(hint["candidate"], str)
                    or hint["start"] < 0 or hint["end"] <= hint["start"]
                    or hint["end"] > len(original_sentence)
                    or original_sentence[hint["start"]:hint["end"]] != hint["surface"]
                    or (hint["start"] and (original_sentence[hint["start"] - 1].isalnum()
                                            or original_sentence[hint["start"] - 1] == "_"))
                    or (hint["end"] < len(original_sentence)
                        and (original_sentence[hint["end"]].isalnum()
                             or original_sentence[hint["end"]] == "_"))
                    or correction.get(hint["surface"]) != hint["candidate"]):
                return {"state": "UNKNOWN", "reason": "CANDIDATE_SPAN_HINT_INVALID",
                        "candidate_span_hint": hint}
        elif correction:
            return {"state": "UNKNOWN", "reason": "CANDIDATE_SPAN_HINT_REQUIRED"}
        left_checked = self._propose_validated(
            question=question, source_text=original_sentence, answer=original_answer,
            domain=domain, correction=correction, candidate_span_hint=hint,
        )
        right_checked = self._propose_validated(
            question=question, source_text=corrected_sentence, answer=corrected_answer,
            domain=domain, correction={},
        )
        if left_checked["state"] != "PARSED" or right_checked["state"] != "PARSED":
            state = "UNKNOWN"
            reason = "FRAME_VALIDATION_FAILED"
        elif left_checked["normalized"] == right_checked["normalized"]:
            state, reason = "AGREES", "NORMALIZED_FRAMES_MATCH"
        else:
            state, reason = "CONTRADICTS", "NORMALIZED_FRAME_FIELDS_DIFFER"
        return {"state": state, "reason": reason, "candidate_span_hint": hint,
                "original": left_checked,
                "corrected": right_checked}

