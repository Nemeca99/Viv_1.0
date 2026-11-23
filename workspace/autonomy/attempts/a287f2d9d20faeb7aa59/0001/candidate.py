def solve(value):
    results = []
    for item in value['data']:
        if 'query' in value['options'] and value['options']['query'] in item['reason']:
            results.append(item)
    if 'sort_by' in value['options'] and 'order' in value['options']:
        if value['options']['sort_by'] == 'reason':
            results.sort(key=lambda x: x['reason'])
            if value['options']['order'] == 'desc':
                results = results[::-1]
    return {"results": results}