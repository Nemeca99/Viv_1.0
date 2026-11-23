def validate_agent_message(value):
    """Validate agent message envelope with stable, field-specific error codes."""
    
    # Check if value is a dict
    if not isinstance(value, dict):
        return ('MESSAGE_NOT_OBJECT',)
    
    errors = []
    
    # Required fields: agent_id, agent_type, task_id, status, audience, trust_class, message
    
    # Validate agent_id
    if 'agent_id' not in value:
        errors.append('MISSING_AGENT_ID')
    elif not isinstance(value['agent_id'], str) or value['agent_id'].strip() == '':
        errors.append('INVALID_AGENT_ID')
    
    # Validate agent_type (model or human)
    if 'agent_type' not in value:
        errors.append('MISSING_AGENT_TYPE')
    elif not isinstance(value['agent_type'], str) or value['agent_type'].strip() == '':
        errors.append('INVALID_AGENT_TYPE')
    else:
        # Check trust_class matches agent_type
        if 'trust_class' in value and value['trust_class'] != '':
            if value['agent_type'] == 'model' and value['trust_class'] != 'unverified_model_output':
                errors.append('INVALID_TRUST_CLASS')
            elif value['agent_type'] == 'human' and value['trust_class'] != 'human_agent_statement':
                errors.append('INVALID_TRUST_CLASS')
    
    # Validate task_id
    if 'task_id' not in value:
        errors.append('MISSING_TASK_ID')
    elif not isinstance(value['task_id'], str) or value['task_id'].strip() == '':
        errors.append('INVALID_TASK_ID')
    
    # Validate status (DONE, NEEDS_USER, BLOCKED)
    if 'status' not in value:
        errors.append('MISSING_STATUS')
    elif not isinstance(value['status'], str) or value['status'].strip() == '':
        errors.append('INVALID_STATUS')
    else:
        valid_statuses = ['DONE', 'NEEDS_USER', 'BLOCKED']
        if value['status'] not in valid_statuses:
            errors.append('INVALID_STATUS')
    
    # Validate audience (mind)
    if 'audience' not in value:
        errors.append('MISSING_AUDIENCE')
    elif not isinstance(value['audience'], str) or value['audience'].strip() == '':
        errors.append('INVALID_AUDIENCE')
    
    # Validate trust_class
    if 'trust_class' not in value:
        errors.append('MISSING_TRUST_CLASS')
    elif not isinstance(value['trust_class'], str) or value['trust_class'].strip() == '':
        errors.append('INVALID_TRUST_CLASS')
    
    # Validate message
    if 'message' not in value:
        errors.append('MISSING_MESSAGE')
    elif not isinstance(value['message'], str) or value['message'].strip() == '':
        errors.append('INVALID_MESSAGE')
    
    # Required lists: artifact_refs, claims, uncertainties, conflicts_with
    
    # Validate artifact_refs
    if 'artifact_refs' not in value:
        errors.append('MISSING_ARTIFACT_REFS')
    elif not isinstance(value['artifact_refs'], list):
        errors.append('ARTIFACT_REFS_NOT_LIST')
    else:
        for item in value['artifact_refs']:
            if not isinstance(item, str):
                errors.append('ARTIFACT_REF_ITEM_NOT_STRING')
    
    # Validate claims
    if 'claims' not in value:
        errors.append('MISSING_CLAIMS')
    elif not isinstance(value['claims'], list):
        errors.append('CLAIMS_NOT_LIST')
    else:
        for claim in value['claims']:
            if not isinstance(claim, dict):
                errors.append('CLAIM_ITEM_NOT_OBJECT')
            else:
                # Validate claim structure
                if 'text' not in claim or not isinstance(claim.get('text'), str) or claim.get('text', '').strip() == '':
                    errors.append('INVALID_CLAIM_TEXT')
                elif 'evidence_ids' not in claim or not isinstance(claim.get('evidence_ids'), list):
                    errors.append('CLAIM_EVIDENCE_IDS_NOT_LIST')
                else:
                    for eid in claim['evidence_ids']:
                        if not isinstance(eid, str):
                            errors.append('EVIDENCE_ID_ITEM_NOT_STRING')
                elif 'kind' not in claim or claim.get('kind') not in ['retrieved_fact', 'inference', 'proposal']:
                    errors.append('INVALID_CLAIM_KIND')
    
    # Validate uncertainties
    if 'uncertainties' not in value:
        errors.append('MISSING_UNCERTAINITIES')
    elif not isinstance(value['uncertainties'], list):
        errors.append('UNCERTAINITIES_NOT_LIST')
    
    # Validate conflicts_with
    if 'conflicts_with' not in value:
        errors.append('MISSING_CONFLICTS_WITH')
    elif not isinstance(value['conflicts_with'], list):
        errors.append('CONFLICTS_WITH_NOT_LIST')
    
    # parent_task_id may be absent or null; otherwise require non-empty trimmed string
    if 'parent_task_id' in value and value['parent_task_id'] is not None:
        if not isinstance(value['parent_task_id'], str) or value['parent_task_id'].strip() == '':
            errors.append('INVALID_PARENT_TASK_ID')
    
    return tuple(errors)
