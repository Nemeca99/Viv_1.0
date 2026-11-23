def solve(value):
    results = []
    for item in value['input']['data']:
        if value['input']['options']['query'] in item['reason'] and item['status'] == 'failed':
            results.append(item)
    results.sort(key=lambda x: x['timestamp'])
    return {"results": results[:value['input']['options']['limit']]}