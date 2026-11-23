def solve(value):
    results = []
    query = value.get('options', {}).get('query', '')
    sort_by = value.get('options', {}).get('sort_by', '')
    order = value.get('options', {}).get('order', 'asc')
    
    for item in value.get('data', []):
        if query and query.lower() in item.get('reason', '').lower():
            results.append(item)
    
    if sort_by and sort_by in ['reason', 'status', 'title']:
        if sort_by == 'reason':
            key = lambda x: x['reason'].lower()
        elif sort_by == 'status':
            key = lambda x: x['status'].lower()
        else:  # sort_by == 'title'
            key = lambda x: x['title'].lower()
        
        results.sort(key=key)
        if order == 'desc':
            results = results[::-1]
    
    return {"results": results}