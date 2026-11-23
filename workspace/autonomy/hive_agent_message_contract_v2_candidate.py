def validate_agent_message(value):
    """Validate agent message envelope JSON structure."""
    errors = []
    
    # Must be a dict
    if not isinstance(value, dict):
        return tuple(errors)  # Empty list is valid for non-dict
    
    # Check required string fields exist and are strings
    required_strings = ['agent_id', 'agent_type', 'task_id', 'status', 'audience', 'trust_class', 'message']
    
    for field in required_strings:
        if field not in value or not isinstance(value[field], str):
            errors.append(field)
    
    # Validate agent_type exactly matches model or human
    valid_agent_types = ['model', 'human']
    if 'agent_type' in value and value['agent_type'] not in valid_agent_types:
        errors.append('INVALID_AGENT_TYPE')
    
    # Validate status exactly matches DONE, NEEDS_USER, or BLOCKED
    valid_statuses = ['DONE', 'NEEDS_USER', 'BLOCKED']
    if 'status' in value and value['status'] not in valid_statuses:
        errors.append('INVALID_STATUS')
    
    # Validate audience exactly matches mind
    if 'audience' in value and value['audience'] != 'mind':
        errors.append('INVALID_AUDIENCE')
    
    # Validate trust_class based on agent_type
    model_trust = ['unverified_model_output']
    human_trust = ['human_agent_statement']
    
    if 'trust_class' in value:
        if value['agent_type'] == 'model':
            if value['trust_class'] not in model_trust:
                errors.append('INVALID_TRUST_CLASS')
        elif value['agent_type'] == 'human':
            if value['trust_class'] not in human_trust:
                errors.append('INVALID_TRUST_CLASS')
    
    # Validate artifact_refs is a list of strings (optional)
    if 'artifact_refs' in value and not isinstance(value['artifact_refs'], list):
        errors.append('MISSING_ARTIFACT_REFS')
    
    # Validate claims is a list of objects with specific structure
    if 'claims' in value:
        if not isinstance(value['claims'], list):
            errors.append('CLAIMS_NOT_LIST')
        else:
            for claim in value['claims']:
                if not isinstance(claim, dict):
                    continue  # Allow extra fields or malformed entries
                required_claim_fields = ['text', 'evidence_ids', 'kind']
                for field in required_claim_fields:
                    if field not in claim or not isinstance(claim[field], str):
                        errors.append('INVALID_CLAIM')
    
    # Validate uncertainties is a list of strings (optional)
    if 'uncertainties' in value and not isinstance(value['uncertainties'], list):
        errors.append('MISSING_UNCERTAINTIES')
    
    # Validate conflicts_with is a list of strings (optional)
    if 'conflicts_with' in value and not isinstance(value['conflicts_with'], list):
        errors.append('MISSING_CONFLICTS_WITH')
    
    # Validate parent_task_id is optional, must be null or non-empty string
    if 'parent_task_id' in value:
        if value['parent_task_id'] is None:
            pass  # Valid
        elif not isinstance(value['parent_task_id'], str) or len(value['parent_task_id']) == 0:
            errors.append('INVALID_PARENT_TASK_ID')
    
    return tuple(errors)
