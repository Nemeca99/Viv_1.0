def solve(value):
    if not isinstance(value, dict) or 'data' not in value or 'options' not in value:
        return {"results": []}
    data = value.get('data', [])
    query = value.get('options', {}).get('query', '')
    results = []
    for item in data:
        if isinstance(item, dict) and 'reason' in item and 'status' in item:
            if query in item['reason'] or query in item['status']:
                results.append(item)
    return {"results": results}