def solve(value):
    if not value or not isinstance(value, dict) or 'data' not in value or 'options' not in value:
        return {"results": []}
    
    data = value['data']
    options = value['options']
    sort_by = options.get('sort', 'reason')
    order = options.get('order', 'asc')
    limit = options.get('limit', None)
    query = options.get('query', None)
    
    # Define the priority order for severity
    severity_order = {
        'Missing dependency': 0,
        'Invalid configuration': 1,
        'Unknown error': 2
    }
    
    # Filter and sort the data
    filtered = []
    for item in data:
        if query and query not in item.get('reason', '').lower():
            continue
        if item.get('status') == 'failed':
            filtered.append(item)
    
    # Sort based on severity and reason
    filtered.sort(key=lambda x: (severity_order.get(x.get('reason', ''), 3), x.get('reason', '').lower()))
    
    # Apply order
    if order == 'desc':
        filtered = filtered[::-1]
    
    # Apply limit
    if limit is not None:
        filtered = filtered[:limit]
    
    return {"results": filtered}
