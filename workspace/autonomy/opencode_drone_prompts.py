def format_drone_self_prompt(agenda: str, verified_facts: str, next_action: str) -> str:
    """Formats only caller-supplied facts; does not verify truth or grant authority."""
    
    values = (agenda, verified_facts, next_action)
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError("All three inputs must be non-empty strings after whitespace trimming")

    trimmed_agenda, trimmed_facts, trimmed_next = (value.strip() for value in values)
    
    if not trimmed_agenda or not trimmed_facts or not trimmed_next:
        raise ValueError("All three inputs must be non-empty strings after whitespace trimming")
    
    return f"""[DRONE SELF-PROMPT]

Agenda: {trimmed_agenda}

Verified facts: {trimmed_facts}

Next bounded action: {trimmed_next}"""
