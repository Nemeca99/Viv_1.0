def solve(value):
    data = value.get("data", [])
    options = value.get("options", {})
    current_state = options.get("current_state", {})
    completed = current_state.get("completed", [])
    failed = current_state.get("failed", [])
    in_progress = current_state.get("in_progress", [])
    task_to_dependency = {}
    dependency_to_tasks = {}
    for task_data in data:
        task = task_data["task"]
        dependencies = task_data["dependencies"]
        task_to_dependency[task] = dependencies
        for dep in dependencies:
            if dep not in dependency_to_tasks:
                dependency_to_tasks[dep] = []
            dependency_to_tasks[dep].append(task)
    runnable_tasks = []
    for task in task_to_dependency:
        dependencies = task_to_dependency[task]
        if all(dep in completed for dep in dependencies) and task not in failed:
            runnable_tasks.append(task)
    return {"results": runnable_tasks}