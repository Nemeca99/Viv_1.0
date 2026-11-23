def solve(value):
    if not isinstance(value, dict) or 'data' not in value or 'options' not in value:
        return {"results": []}
    data = value.get('data', [])
    options = value.get('options', {})
    sort_by = options.get('sort_by', 'reason')
    order = options.get('order', 'asc')
    limit = options.get('limit', 10)
    results = []
    for item in data:
        if not isinstance(item, dict) or 'reason' not in item or 'status' not in item:
            continue
        reason = item.get('reason')
        status = item.get('status')
        title = item.get('title', '')
        if reason and status:
            results.append({
                'reason': reason,
                'status': status,
                'title': title
            })
    if sort_by == 'reason':
        results.sort(key=lambda x: x['reason'])
    elif sort_by == 'status':
        results.sort(key=lambda x: x['status'])
    elif sort_by == 'title':
        results.sort(key=lambda x: x['title'])
    if order == 'desc':
        results.reverse()
    return {"results": results[:limit]}