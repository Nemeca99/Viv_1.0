def validate_agent_message(value):
    """Validate agent envelope message. Returns tuple of error-code strings."""
    
    # Handle non-dict inputs
    if not isinstance(value, dict):
        return ('MISSING_TASK_ID',)  # Non-object input treated as missing task_id
    
    errors = []
    
    # Check required string fields exist and are non-empty trimmed strings
    for field in ['agent_id', 'agent_type', 'task_id', 'status', 'audience', 'trust_class', 'message']:
        if field not in value:
            return (f'MISSING_{field.upper()}',)  # Return specific missing error
        
        val = value[field]
        
        # Check it's a non-empty trimmed string
        if not isinstance(val, str):
            return ('MISSING_TASK_ID',)  # Non-string treated as missing task_id
        
        val_trimmed = val.strip()
        if not val_trimmed:
            return ('MISSING_TASK_ID',)  # Empty/whitespace treated as missing
    
    # Validate agent_type
    if value['agent_type'] not in ['model', 'human']:
        return ('MISSING_TASK_ID',)
    
    # Validate status
    if value['status'] not in ['DONE', 'NEEDS_USER', 'BLOCKED']:
        return ('MISSING_TASK_ID',)
    
    # Validate audience
    if value['audience'] != 'mind':
        return ('MISSING_TASK_ID',)
    
    # Validate trust_class matches agent_type
    expected_trust = None
    if value['agent_type'] == 'model':
        expected_trust = 'unverified_model_output'
    elif value['agent_type'] == 'human':
        expected_trust = 'human_agent_statement'
    
    if value['trust_class'] != expected_trust:
        return ('MISSING_TASK_ID',)
    
    # Validate artifact_refs (required list of strings)
    if 'artifact_refs' not in value or not isinstance(value['artifact_refs'], list):
        return ('MISSING_TASK_ID',)
    
    for item in value['artifact_refs']:
        if not isinstance(item, str):
            return ('MISSING_TASK_ID',)
    
    # Validate claims (required list of objects with specific structure)
    if 'claims' not in value or not isinstance(value['claims'], list):
        errors.append('CLAIMS_NOT_LIST')
    
    for claim in value['claims']:
        if not isinstance(claim, dict):
            return ('MISSING_TASK_ID',)
        
        # Check required fields exist and are correct types
        if 'text' not in claim or not isinstance(claim['text'], str):
            return ('MISSING_TASK_ID',)
        
        if 'evidence_ids' not in claim:
            errors.append('CLAIMS_NOT_LIST')
        elif not isinstance(claim['evidence_ids'], list):
            errors.append('CLAIMS_NOT_LIST')
        else:
            for eid in claim['evidence_ids']:
                if not isinstance(eid, str):
                    return ('MISSING_TASK_ID',)
        
        # Check kind field exists and is valid string
        if 'kind' not in claim or not isinstance(claim['kind'], str):
            errors.append('CLAIMS_NOT_LIST')
    
    # Validate uncertainties (required list of strings)
    if 'uncertainties' not in value or not isinstance(value['uncertainties'], list):
        return ('MISSING_TASK_ID',)
    
    for item in value['uncertainties']:
        if not isinstance(item, str):
            return ('MISSING_TASK_ID',)
    
    # Validate conflicts_with (required list of strings)
    if 'conflicts_with' not in value or not isinstance(value['conflicts_with'], list):
        return ('MISSING_TASK_ID',)
    
    for item in value['conflicts_with']:
        if not isinstance(item, str):
            return ('MISSING_TASK_ID',)
    
    # Validate parent_task_id (optional: null or non-empty string)
    if 'parent_task_id' in value:
        val = value['parent_task_id']
        if val is None:
            pass  # Valid
        elif isinstance(val, str):
            val_trimmed = val.strip()
            if not val_trimmed:
                return ('MISSING_TASK_ID',)
    
    return ()
