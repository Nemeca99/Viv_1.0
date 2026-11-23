import json
import re
from datetime import datetime, timezone
from pathlib import Path


def is_authorized_curriculum_practice_word(word, domain_info):
    if not isinstance(word, str) or not isinstance(domain_info, dict):
        return False
    concepts = domain_info.get("concepts")
    if not isinstance(concepts, (list, tuple, set)):
        return False
    allowed = {value.casefold() for value in concepts if isinstance(value, str)}
    return word.casefold() in allowed


def run_speech_spelling_practice(brain, word, domain_info):
    if not is_authorized_curriculum_practice_word(word, domain_info):
        raise PermissionError("tutor_word_outside_active_curriculum_domain")
    spelling = brain.spell(word)
    speech = brain.speak_toddler(word)
    spelling_surface = str(spelling.get("neural_spelled") or "").split("[", 1)[0]
    spelled_letters = "".join(re.findall(r"[a-z]", spelling_surface.casefold()))
    return {
        "word": word.casefold(),
        "spelling": spelling,
        "speech": speech,
        "spelling_matches": spelled_letters == word.casefold(),
    }


def append_definition_candidates(pending_words, candidates):
    queued = list(pending_words)
    normalized = {word.casefold() for word in queued if isinstance(word, str)}
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        word = candidate.casefold()
        if word and word not in normalized:
            queued.append(word)
            normalized.add(word)
    return queued


def resolve_definition_candidate(pending_words, word):
    queued = list(pending_words)
    if queued and isinstance(word, str) and queued[0].casefold() == word.casefold():
        return queued[1:]
    return queued


def has_explicit_definition_cue(response, word):
    if not isinstance(response, str) or not isinstance(word, str) or not word.strip():
        return False
    token = re.escape(word.casefold().strip())
    return bool(re.search(rf"\b{token}\s+(?:is|means|refers\s+to|stands\s+for|denotes)\b", response.casefold()))


def include_spelling_feedback(feedback, word, spelling_matches):
    if spelling_matches:
        return feedback
    return f"{feedback} The spelling check for '{word}' did not match; practice that word again."


def record_architect_review_context(queue, words, context, cycle):
    for word in words:
        if not isinstance(word, str) or not word.strip():
            continue
        normalized = word.casefold().strip()
        candidate = queue.setdefault(normalized, {
            "word": normalized,
            "contexts": [],
            "definition_attempts": [],
        })
        item = {"cycle": int(cycle), "text": str(context)}
        if item not in candidate["contexts"]:
            candidate["contexts"].append(item)


def record_architect_review_definition(queue, word, definition, tutor_accepted, cycle):
    if not isinstance(word, str) or not word.strip():
        return
    normalized = word.casefold().strip()
    candidate = queue.setdefault(normalized, {
        "word": normalized,
        "contexts": [],
        "definition_attempts": [],
    })
    attempt = {
        "cycle": int(cycle),
        "definition": str(definition),
        "tutor_accepted": bool(tutor_accepted),
    }
    if attempt not in candidate["definition_attempts"]:
        candidate["definition_attempts"].append(attempt)


def append_architect_review_session(path, session_id, candidates):
    if not candidates:
        return None
    record = {
        "schema": "socratic_architect_word_review_v1",
        "session_id": str(session_id),
        "status": "awaiting_architect_review",
        "stable_vocabulary_changed": False,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidates": [candidates[word] for word in sorted(candidates)],
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return record


def assess_tutor_response(response, known_words, word_parts, *, definition_required=False,
                          definition_text=None, definition_target=None,
                          tutor_accepts_definition=None):
    words = re.findall(r"[a-z]+", response.casefold()) if isinstance(response, str) else []
    normalized_known = {word.casefold() for word in known_words if isinstance(word, str)}
    unknown_words = list(dict.fromkeys(word for word in words if word not in normalized_known))
    well_formed = (
        isinstance(response, str)
        and bool(response[:1].isupper())
        and response.rstrip().endswith((".", "?", "!"))
        and len(words) >= 3
    )
    if well_formed and words[0] in {"the", "a", "an"} and len(words) >= 3:
        second_part = word_parts.get(words[1])
        third_part = word_parts.get(words[2])
        if second_part == "verb" or (third_part is not None and third_part != "verb"):
            well_formed = False

    needs_definition = bool(unknown_words) or definition_required
    definition_words = re.findall(r"[a-z]+", definition_text.casefold()) if isinstance(definition_text, str) else []
    definition_matches_target = (
        definition_target is None
        or not unknown_words
        or unknown_words == [definition_target.casefold()]
    )
    definition_accepted = (
        needs_definition
        and len(definition_words) >= 3
        and tutor_accepts_definition is True
        and definition_matches_target
    )
    passed = well_formed and (not unknown_words or definition_accepted) and (
        not definition_required or definition_accepted
    )
    if len(unknown_words) > 1:
        disposition = "multiple_unknown_words"
    elif needs_definition and not definition_accepted:
        disposition = (
            "definition_not_accepted"
            if tutor_accepts_definition is False and len(definition_words) >= 3
            else "definition_required"
        )
    elif not well_formed:
        disposition = "incorrect_format"
    else:
        disposition = "passed"
    return {
        "passed": passed,
        "disposition": disposition,
        "well_formed": well_formed,
        "unknown_words": unknown_words,
        "needs_definition": needs_definition,
        "definition_accepted": definition_accepted,
    }
