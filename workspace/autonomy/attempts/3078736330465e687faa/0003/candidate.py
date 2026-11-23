def solve(value):
    results = []
    data = value.get('input', {}).get('data', [])
    options = value.get('input', {}).get('options', {})
    query = options.get('query', '')
    limit = options.get('limit', 5)
    sort_key = options.get('sort', 'timestamp')
    
    for item in data:
        if query in item.get('reason', '') and item.get('status') == 'failed':
            results.append(item)
    
    if sort_key == 'timestamp':
        results.sort(key=lambda x: x.get('timestamp'))
    elif sort_key == 'id':
        results.sort(key=lambda x: x.get('id'))
    
    return {"results": results[:limit]}