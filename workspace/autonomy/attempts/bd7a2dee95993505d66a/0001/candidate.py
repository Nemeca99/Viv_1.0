def solve(value):
    import json
    from collections import defaultdict

    def parse_input(data, options):
        query = options.get('query', '')
        sort = options.get('sort', '')
        order = options.get('order', 'descending')
        return data, query, sort, order

    def filter_failures(data, query):
        filtered = []
        for item in data:
            if query in item['reason']:
                filtered.append(item)
        return filtered

    def sort_failures(failures, sort_key, order):
        if sort_key == 'severity':
            sorted_failures = sorted(failures, key=lambda x: x['severity'], reverse=(order == 'descending'))
        elif sort_key == 'timestamp':
            sorted_failures = sorted(failures, key=lambda x: x['timestamp'], reverse=(order == 'descending'))
        else:
            sorted_failures = failures
        return sorted_failures

    def group_by_dependency(failures):
        grouped = defaultdict(list)
        for failure in failures:
            for dep in failure['dependencies']:
                grouped[dep].append(failure)
        return grouped

    def format_output(grouped, query):
        results = []
        for dep, failures in grouped.items():
            results.append({
                'dependency': dep,
                'reason': query,
                'severity': 'high' if any(f['severity'] == 'high' for f in failures) else 'medium',
                'timestamp': max(f['timestamp'] for f in failures)
            })
        return results

    data, query, sort_key, order = parse_input(value['input']['data'], value['input']['options'])
    filtered = filter_failures(data, query)
    sorted_failures = sort_failures(filtered, sort_key, order)
    grouped = group_by_dependency(sorted_failures)
    results = format_output(grouped, query)
    return {"results": results}
