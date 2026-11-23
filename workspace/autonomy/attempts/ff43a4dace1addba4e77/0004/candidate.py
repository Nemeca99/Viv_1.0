def solve(value):
    data = value.get("data", [])
    options = value.get("options", {})
    current_state = options.get("current_state", {})
    
    completed = set(current_state.get("completed", []))
    failed = set(current_state.get("failed", []))
    in_progress = set(current_state.get("in_progress", []))
    
    task_to_dependency = {task["task"]: set(task["dependencies"]) for task in data}
    dependency_to_task = {dep: [] for task in data for dep in task["dependencies"]}
    for task in data:
        for dep in task["dependencies"]:
            dependency_to_task[dep].append(task["task"])
    
    ready_tasks = []
    for task in data:
        task_name = task["task"]
        dependencies = task_to_dependency[task_name]
        if all(dep in completed for dep in dependencies) and task_name not in in_progress and task_name not in failed:
            ready_tasks.append(task_name)
    
    return {"results": ready_tasks}