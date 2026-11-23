def solve(value):
    from collections import defaultdict, deque
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

    runnable_tasks = []
    queue = deque([task["task"] for task in data if is_task_runnable(task["task"])])
    visited = set()

    while queue:
        current_task = queue.popleft()
        if current_task in visited:
            continue
        visited.add(current_task)
        runnable_tasks.append(current_task)
        for dependent in task_graph[current_task]:
            if dependent not in visited and all(dep in completed_tasks for dep in task_dependencies[dependent]):
                queue.append(dependent)

    return {"results": runnable_tasks}