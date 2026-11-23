def solve(value):
    if not value or not isinstance(value, dict) or 'data' not in value or 'options' not in value:
        return {"results": []}
    data = value.get('data', [])
    options = value.get('options', {})
    query = options.get('query', '')
    sort_by = options.get('sort_by', 'reason')
    order = options.get('order', 'asc')
    results = []
    for item in data:
        if not isinstance(item, dict) or 'reason' not in item or 'status' not in item:
            continue
        reason = item.get('reason', '')
        status = item.get('status', '')
        if query in reason or query in status:
            results.append(item)
    if sort_by == 'reason':
        results.sort(key=lambda x: x.get('reason', ''))
    elif sort_by == 'status':
        results.sort(key=lambda x: x.get('status', ''))
    elif sort_by == 'title':
        results.sort(key=lambda x: x.get('title', ''))
    if order == 'desc':
        results.reverse()
    return {"results": results}