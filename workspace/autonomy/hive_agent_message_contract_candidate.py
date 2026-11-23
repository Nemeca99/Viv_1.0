def validate_agent_message(value):
    """
    Pure function that validates agent message envelope structure and values.
    
    Returns: tuple of error-code strings (empty if valid)
    
    Valid envelopes must have:
    - agent_type: "model" or "human"
    - status: "DONE", "NEEDS_USER", or "BLOCKED"
    - audience: "mind"
    - trust_class: "unverified_model_output" for model, "human_agent_statement" for human
    - claims: mapping with string text, list evidence_ids, kind in ["retrieved_fact", "inference", "proposal"]
    - artifact_refs: list of strings (may be empty)
    - uncertainties: list of strings (may be empty)
    - conflicts_with: list of strings (may be empty)
    - parent_task_id: null or non-empty string
    
    Does not raise; returns () on valid input.
    """
    errors = []
    
    if value is None:
        return ("NULL_INPUT",)
    
    # Must be a dict
    if not isinstance(value, dict):
        return ("NOT_DICT",)
    
    # Check required fields exist and have correct types
    for field in ["agent_type", "status", "audience", "trust_class", "claims"]:
        if field not in value:
            errors.append(f"MISSING_{field.upper()}")
    
    # Validate agent_type
    if "agent_type" in value:
        if not isinstance(value["agent_type"], str):
            errors.append("AGENT_TYPE_NOT_STRING")
        elif value["agent_type"] not in ["model", "human"]:
            errors.append(f"INVALID_AGENT_TYPE:{value['agent_type']}")
    
    # Validate status
    if "status" in value:
        if not isinstance(value["status"], str):
            errors.append("STATUS_NOT_STRING")
        elif value["status"] not in ["DONE", "NEEDS_USER", "BLOCKED"]:
            errors.append(f"INVALID_STATUS:{value['status']}")
    
    # Validate audience
    if "audience" in value:
        if not isinstance(value["audience"], str):
            errors.append("AUDIENCE_NOT_STRING")
        elif value["audience"] != "mind":
            errors.append(f"INVALID_AUDIENCE:{value['audience']}")
    
    # Validate trust_class based on agent_type
    if "trust_class" in value:
        if not isinstance(value["trust_class"], str):
            errors.append("TRUST_CLASS_NOT_STRING")
        elif value["agent_type"] == "model":
            if value["trust_class"] != "unverified_model_output":
                errors.append(f"INVALID_TRUST_CLASS_FOR_MODEL:{value['trust_class']}")
        else:  # human
            if value["trust_class"] != "human_agent_statement":
                errors.append(f"INVALID_TRUST_CLASS_FOR_HUMAN:{value['trust_class']}")
    
    # Validate claims structure
    if "claims" in value:
        if not isinstance(value["claims"], dict):
            errors.append("CLAIMS_NOT_DICT")
        else:
            for claim_key, claim_value in value["claims"].items():
                # Each claim must be a mapping (dict)
                if not isinstance(claim_value, dict):
                    errors.append(f"INVALID_CLAIM_SHAPE:{claim_key}")
                    continue
                
                # Check text field is string
                if "text" not in claim_value:
                    errors.append(f"MISSING_TEXT_IN_CLAIM:{claim_key}")
                elif not isinstance(claim_value["text"], str):
                    errors.append(f"CLAIM_TEXT_NOT_STRING:{claim_key}")
                
                # Check evidence_ids is list
                if "evidence_ids" not in claim_value:
                    errors.append(f"MISSING_EVIDENCE_IDS_IN_CLAIM:{claim_key}")
                elif not isinstance(claim_value["evidence_ids"], list):
                    errors.append(f"EVIDENCE_IDS_NOT_LIST:{claim_key}")
                
                # Check kind is one of the allowed values
                if "kind" not in claim_value:
                    errors.append(f"MISSING_KIND_IN_CLAIM:{claim_key}")
                elif not isinstance(claim_value["kind"], str):
                    errors.append(f"CLAIM_KIND_NOT_STRING:{claim_key}")
                elif claim_value["kind"] not in ["retrieved_fact", "inference", "proposal"]:
                    errors.append(f"INVALID_KIND_IN_CLAIM:{claim_key}:{claim_value['kind']}")
    
    # Validate artifact_refs is list of strings (may be empty)
    if "artifact_refs" in value:
        if not isinstance(value["artifact_refs"], list):
            errors.append("ARTIFACT_REFS_NOT_LIST")
        else:
            for ref in value["artifact_refs"]:
                if not isinstance(ref, str):
                    errors.append(f"ARTIFACT_REF_NOT_STRING:{ref}")
    
    # Validate uncertainties is list of strings (may be empty)
    if "uncertainties" in value:
        if not isinstance(value["uncertainties"], list):
            errors.append("UNCERTAINTIES_NOT_LIST")
        else:
            for u in value["uncertainties"]:
                if not isinstance(u, str):
                    errors.append(f"UNCERTAINTY_NOT_STRING:{u}")
    
    # Validate conflicts_with is list of strings (may be empty)
    if "conflicts_with" in value:
        if not isinstance(value["conflicts_with"], list):
            errors.append("CONFLICTS_WITH_NOT_LIST")
        else:
            for c in value["conflicts_with"]:
                if not isinstance(c, str):
                    errors.append(f"CONFLICT_NOT_STRING:{c}")
    
    # Validate parent_task_id is null or non-empty string
    if "parent_task_id" in value:
        pt = value["parent_task_id"]
        if pt is None:
            pass  # Valid - null allowed
        elif not isinstance(pt, str):
            errors.append("PARENT_TASK_ID_NOT_STRING")
        elif len(pt) == 0:
            errors.append("PARENT_TASK_ID_EMPTY")
    
    return tuple(errors)
