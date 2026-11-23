def solve(value):
    from collections import defaultdict

    def filter_and_sort(data, options):
        results = []
        for item in data:
            if options.get("query") and options["query"] not in item.get("reason", "").lower():
                continue
            results.append(item)
        if options.get("sort_by") == "severity":
            results.sort(key=lambda x: x.get("severity", "low"))
        elif options.get("sort_by") == "timestamp":
            results.sort(key=lambda x: x.get("timestamp", ""))
        elif options.get("sort_by") == "reason":
            results.sort(key=lambda x: x.get("reason", ""))
        return results

    def resolve_dependencies(data):
        task_map = defaultdict(list)
        for item in data:
            task_map[item["task"]].append(item)
        return task_map

    def identify_runnable_tasks(data, options):
        results = []
        for item in data:
            if item["status"] == "completed":
                results.append(item)
        return results

    def sort_by_severity(data):
        severity_order = {"high": 0, "medium": 1, "low": 2}
        return sorted(data, key=lambda x: severity_order.get(x.get("severity", "low")))

    def sort_by_reason(data):
        reason_order = {
            "Missing dependency": 0,
            "Invalid configuration": 1,
            "Unknown error": 2,
        }
        return sorted(data, key=lambda x: reason_order.get(x.get("reason", ""), 3))

    def filter_by_reason(data, reason_contains):
        results = []
        for item in data:
            if reason_contains in item.get("reason", "").lower():
                results.append(item)
        return results

    if not value:
        return {"results": []}

    data = value.get("data", [])
    options = value.get("options", {})

    if options.get("query") and options.get("sort_by") == "severity":
        results = filter_and_sort(data, options)
        results = sort_by_severity(results)
    elif options.get("query") and options.get("sort_by") == "reason":
        results = filter_and_sort(data, options)
        results = sort_by_reason(results)
    elif options.get("query") and options.get("sort_by") == "timestamp":
        results = filter_and_sort(data, options)
        results = sorted(results, key=lambda x: x.get("timestamp", ""))
    elif options.get("query") and options.get("sort_by") == "severity" and options.get("reason_contains"):
        results = filter_by_reason(data, options.get("reason_contains"))
        results = sort_by_severity(results)
    elif options.get("query") and options.get("sort_by") == "reason" and options.get("reason_contains"):
        results = filter_by_reason(data, options.get("reason_contains"))
        results = sort_by_reason(results)
    else:
        results = data

    return {"results": results}