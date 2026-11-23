def solve(value):
    from collections import defaultdict

    def filter_and_sort(data, options):
        results = []
        query = options.get("query", "").lower()
        sort_by = options.get("sort_by", "")

        for item in data:
            if query and query not in item.get("reason", "").lower() and query not in item.get("task", "").lower():
                continue
            results.append(item)

        if sort_by == "severity":
            severity_order = {"high": 0, "medium": 1, "low": 2}
            results.sort(key=lambda x: severity_order.get(x.get("severity", "low")))
        elif sort_by == "reason":
            reason_order = {
                "Missing dependency": 0,
                "Invalid configuration": 1,
                "Unknown error": 2,
            }
            results.sort(key=lambda x: reason_order.get(x.get("reason", ""), 3))
        elif sort_by == "timestamp":
            results.sort(key=lambda x: x.get("timestamp", ""))
        return results

    def resolve_dependencies(data):
        task_map = defaultdict(list)
        for item in data:
            task_map[item["task"]].append(item)
        return task_map

    def identify_runnable_tasks(data):
        task_map = resolve_dependencies(data)
        runnable_tasks = []

        for task, items in task_map.items():
            all_deps_resolved = True
            for item in items:
                if item["status"] != "completed":
                    all_deps_resolved = False
                    break

            if all_deps_resolved:
                runnable_tasks.append({
                    "task": task,
                    "status": "completed",
                    "dependencies": [item["dependencies"] for item in items]
                })

        return runnable_tasks

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
    elif options.get("query") and options.get("sort_by") == "reason":
        results = filter_and_sort(data, options)
    elif options:
        results = filter_and_sort(data, options)
    else:
        results = data

    return {"results": results}
