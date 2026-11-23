def solve(value):
    data = value.get("data", [])
    options = value.get("options", {})
    query = options.get("query", "")
    limit = options.get("limit", 0)
    sort = options.get("sort", "")

    results = []

    for task in data:
        task_name = task.get("task", "")
        dependencies = task.get("dependencies", [])
        can_execute = True

        for dep in dependencies:
            dep_task = next((t for t in data if t.get("task") == dep), None)
            if dep_task and dep_task.get("status") == "failed":
                can_execute = False
                break

        if can_execute and "completed" in query:
            results.append(task_name)

    if sort == "task":
        results.sort()

    if limit > 0:
        results = results[:limit]

    return {"results": results}
