def solve(value):
    results = []
    if not value or not isinstance(value, dict) or 'data' not in value or 'options' not in value:
        return {"results": results}
    data = value.get('data', [])
    options = value.get('options', {})
    sort_by = options.get('sort_by', 'reason')
    order = options.get('order', 'asc')
    limit = options.get('limit', 0)
    filtered_data = []
    for item in data:
        if not isinstance(item, dict) or 'reason' not in item or 'status' not in item:
            continue
        reason = item.get('reason', '')
        status = item.get('status', '')
        if status in ['failed', 'invalid_spec']:
            filtered_data.append(item)
    if sort_by == 'reason':
        filtered_data.sort(key=lambda x: x.get('reason', ''))
    elif sort_by == 'status':
        filtered_data.sort(key=lambda x: x.get('status', ''))
    elif sort_by == 'title':
        filtered_data.sort(key=lambda x: x.get('title', ''))
    if order == 'desc':
        filtered_data.reverse()
    if limit > 0:
        filtered_data = filtered_data[:limit]
    return {"results": filtered_data}