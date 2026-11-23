def solve(value):
    data = value.get("data", [])
    options = value.get("options", {})
    current_state = options.get("current_state", {})
    
    completed_tasks = set(current_state.get("completed", []))
    failed_tasks = set(current_state.get("failed", []))
    in_progress_tasks = set(current_state.get("in_progress", []))
    
    task_to_dependency = {}
    for task in data:
        task_name = task.get("task")
        dependencies = task.get("dependencies", [])
        task_to_dependency[task_name] = dependencies
    
    available_tasks = []
    for task_name, dependencies in task_to_dependency.items():
        if task_name in failed_tasks or task_name in in_progress_tasks:
            continue
        if all(dep in completed_tasks for dep in dependencies):
            available_tasks.append(task_name)
    
    return {"results": available_tasks}