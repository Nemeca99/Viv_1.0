def solve(value):
    from collections import defaultdict
    import heapq

    data = value.get("data", [])
    options = value.get("options", {})
    completed_tasks = set(options.get("completed_tasks", []))
    task_graph = defaultdict(list)
    task_dependencies = defaultdict(set)

    for task in data:
        task_name = task["task"]
        dependencies = task.get("dependencies", [])
        task_graph[task_name] = []
        task_dependencies[task_name] = set(dependencies)

    for task in data:
        task_name = task["task"]
        dependencies = task.get("dependencies", [])
        for dep in dependencies:
            task_graph[dep].append(task_name)

    def is_task_runnable(task_name):
        return all(dep in completed_tasks for dep in task_dependencies[task_name])

    runnable_tasks = [task["task"] for task in data if is_task_runnable(task["task"])]

    return {"results": runnable_tasks}