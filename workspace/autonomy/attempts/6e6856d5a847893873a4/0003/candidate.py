def solve(value):
    data = value.get("data", [])
    options = value.get("options", {})
    query = options.get("query", "")
    sort = options.get("sort", "alphabetical")
    limit = options.get("limit", 0)
    current_state = options.get("current_state", {})

    task_to_status = {task["task"]: current_state.get(task["task"], "not_started") for task in data}
    task_to_dependencies = {task["task"]: task["dependencies"] for task in data}
    task_to_id = {task["task"]: idx for idx, task in enumerate(data)}

    ready_tasks = []
    for task in data:
        task_name = task["task"]
        dependencies = task["dependencies"]
        if all(task_to_status[dep] == "completed" for dep in dependencies):
            ready_tasks.append(task_name)

    if query == "ready_tasks":
        results = ready_tasks
    elif query == "tasks with status failed":
        results = [task["task"] for task in data if task_to_status[task["task"]] == "failed"]
    elif query == "tasks with status completed":
        results = [task["task"] for task in data if task_to_status[task["task"]] == "completed"]
    else:
        results = ready_tasks

    if sort == "alphabetical":
        results = sorted(results)
    elif sort == "dependency_order":
        results.sort(key=lambda x: task_to_id[x])

    if limit > 0:
        results = results[:limit]

    return {"results": results}
