def solve(value):
    if not isinstance(value, dict):
        return []
    query = value.get('query', '').lower()
    data = value.get('data', [])
    results = []
    for item in data:
        reason = item.get('reason', '').lower()
        if query in reason:
            results.append(item)
    return results