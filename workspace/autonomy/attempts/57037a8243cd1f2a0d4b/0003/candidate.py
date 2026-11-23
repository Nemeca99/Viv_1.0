def solve(value):
    data = value.get("data", [])
    options = value.get("options", {})
    query = options.get("query", "")
    sort = options.get("sort", "task")
    limit = options.get("limit", float('inf'))

    completed_tasks = set()
    failed_tasks = set()
    in_progress_tasks = set()

    for task in data:
        status = task.get("status", "")
        if status == "completed":
            completed_tasks.add(task.get("task", ""))
        elif status == "failed":
            failed_tasks.add(task.get("task", ""))
        elif status == "in_progress":
            in_progress_tasks.add(task.get("task", ""))

    results = []

    for task in data:
        task_name = task.get("task", "")
        dependencies = task.get("dependencies", [])

        if task_name in failed_tasks:
            continue

        all_deps_completed = True
        for dep in dependencies:
            if dep not in completed_tasks:
                all_deps_completed = False
                break

        if all_deps_completed:
            results.append(task_name)

    if sort == "dependency_order":
        results.sort(key=lambda x: data.index(next(task for task in data if task.get("task") == x)))

    if query == "tasks with status failed":
        results = [task for task in data if task.get("status") == "failed"]

    results = list(set(results))[:limit]

    return {"results": results}